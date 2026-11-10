"""IMAP IDLE listener: watches a folder and pushes new mail into a queue.

The mailbox is opened read-only: flags are never set and messages are never
moved. Only mail that arrives after the listener starts is processed; the
existing backlog is skipped by starting from the highest UID in the folder.
"""

from __future__ import annotations

import asyncio
import ssl
import threading
from typing import Any

from imapclient import IMAPClient

from ..config import (
    APP_PASSWORD,
    EMAIL_ACCOUNT,
    IDLE_TIMEOUT,
    IMAP_FOLDER,
    IMAP_PORT,
    IMAP_SERVER,
    RECONNECT_DELAY,
)
from .mail_parser import parse_raw_email


class ImapListener:
    """Runs in a thread and feeds parsed mail into an ``asyncio.Queue``."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue,
        stop_event: threading.Event,
        *,
        server: str = IMAP_SERVER,
        port: int = IMAP_PORT,
        account: str | None = EMAIL_ACCOUNT,
        password: str | None = APP_PASSWORD,
        folder: str = IMAP_FOLDER,
        idle_timeout: int = IDLE_TIMEOUT,
        reconnect_delay: int = RECONNECT_DELAY,
    ) -> None:
        self.loop = loop
        self.queue = queue
        self.stop_event = stop_event

        self.server = server
        self.port = port
        self.account = account
        self.password = password
        self.folder = folder
        self.idle_timeout = idle_timeout
        self.reconnect_delay = reconnect_delay

    # ---------- lifecycle ----------

    def run(self) -> None:
        """Thread target: connect, then watch until ``stop_event`` is set."""

        if not self.account or not self.password:
            raise ValueError("Missing EMAIL_ACCOUNT or APP_PASSWORD in .env")

        last_uid: int | None = None
        last_uidvalidity: Any = None

        while not self.stop_event.is_set():
            try:
                with self._connect() as client:
                    info = client.select_folder(self.folder, readonly=True)
                    uidvalidity = info[b"UIDVALIDITY"]

                    # A replaced mailbox resets UIDs; start over.
                    if last_uidvalidity != uidvalidity:
                        last_uid = None
                        last_uidvalidity = uidvalidity

                    # Skip the existing backlog: only new arrivals are routed.
                    if last_uid is None:
                        existing = client.search(["ALL"])
                        last_uid = max(existing, default=0)

                    print(
                        f"Watching {self.folder} for new mail "
                        f"(UID > {last_uid})..."
                    )

                    last_uid = self._watch(client, last_uid)

            except Exception as exc:
                if self.stop_event.is_set():
                    break

                print(f"IMAP connection error: {exc}")
                print(f"Reconnecting in {self.reconnect_delay}s...")
                self.stop_event.wait(self.reconnect_delay)

    def _connect(self) -> IMAPClient:
        print(f"Connecting to {self.server}:{self.port}...")

        client = IMAPClient(
            self.server,
            port=self.port,
            ssl=True,
            ssl_context=ssl.create_default_context(),
            timeout=30,
        )
        client.login(self.account, self.password)

        return client

    # ---------- watching ----------

    def _watch(self, client: IMAPClient, last_uid: int) -> int:
        """Loop on IDLE until the connection fails or we are asked to stop."""

        while not self.stop_event.is_set():
            last_uid = self._fetch_new(client, last_uid)

            client.idle()
            try:
                client.idle_check(timeout=self.idle_timeout)
            finally:
                client.idle_done()

        return last_uid

    def _fetch_new(self, client: IMAPClient, last_uid: int) -> int:
        """Fetch every message with a UID greater than ``last_uid``."""

        candidates = client.search(["UID", f"{last_uid + 1}:*"])
        new_uids = sorted(uid for uid in candidates if uid > last_uid)

        for uid in new_uids:
            data = client.fetch([uid], ["RFC822"])
            raw = data.get(uid, {}).get(b"RFC822")

            if raw is None:
                continue

            parsed = parse_raw_email(raw, uid)

            # Thread-safe hand-off to the async consumer.
            self.loop.call_soon_threadsafe(self.queue.put_nowait, parsed)

            last_uid = uid

        return last_uid
