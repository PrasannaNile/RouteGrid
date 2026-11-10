"""RouteGrid entry point.

Listens to the configured IMAP folder and routes every new message to a
ZEISS India queue as it arrives.

    python main.py
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from src.config import (
    APP_PASSWORD,
    EMAIL_ACCOUNT,
    IMAP_FOLDER,
    IMAP_PORT,
    IMAP_SERVER,
    QUEUE_ROOT,
)
from src.ingestion.imap_listener import ImapListener
from src.routing.decision import format_decision
from src.routing.router import route_email


def log_mail(mail: dict[str, Any]) -> None:
    print("\n========== NEW EMAIL ==========")
    print("UID:", mail.get("id"))
    print("From:", mail.get("from"))
    print("Subject:", mail.get("subject"))
    print("Date:", mail.get("date"))
    print("Body:", mail.get("body"))
    print("-------------------------------")


async def email_consumer(queue: asyncio.Queue) -> None:
    """Route messages from the listener until the process is stopped."""

    while True:
        mail = await queue.get()

        try:
            log_mail(mail)

            decision = await route_email(mail)

            print("Routed to:", format_decision(decision))
            print("===============================\n")
        except Exception as exc:
            print(f"Email processing failed: {exc}")
        finally:
            queue.task_done()


async def main() -> None:
    if not EMAIL_ACCOUNT or not APP_PASSWORD:
        raise ValueError("Missing EMAIL_ACCOUNT or APP_PASSWORD in .env")

    print(f"RouteGrid listening on {IMAP_SERVER}:{IMAP_PORT} [{IMAP_FOLDER}]")
    print(f"Queue directory: {QUEUE_ROOT}")

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    stop_event = threading.Event()

    listener = ImapListener(loop, queue, stop_event)
    thread = threading.Thread(
        target=listener.run,
        name="imap-listener",
        daemon=True,
    )
    thread.start()

    try:
        await email_consumer(queue)
    finally:
        stop_event.set()
        thread.join(timeout=5)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
