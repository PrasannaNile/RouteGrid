
import os
import ssl
import email
import asyncio
import threading
import time

from pathlib import Path
from email.header import decode_header
from email import policy
from dotenv import load_dotenv
from imapclient import IMAPClient


# ============ CONFIGURATION ============

load_dotenv(Path(__file__).resolve().parent / ".env")

IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.mail.yahoo.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
EMAIL_ACCOUNT = os.getenv("EMAIL_ACCOUNT")
APP_PASSWORD = os.getenv("APP_PASSWORD")

FOLDER = "INBOX"
RECONNECT_DELAY = 5
IDLE_TIMEOUT = 60


# ============ EMAIL PARSER ============

def clean_header_text(value):
    if not value:
        return ""

    parts = []

    for content, encoding in decode_header(value):
        if isinstance(content, bytes):
            try:
                text = content.decode(
                    encoding or "utf-8",
                    errors="replace"
                )
            except (LookupError, UnicodeError):
                text = content.decode("utf-8", errors="replace")
            parts.append(text)
        else:
            parts.append(str(content))

    return "".join(parts)


def get_email_body(msg):
    for part in msg.walk():
        if part.get_content_type() != "text/plain":
            continue

        if part.get_content_disposition() == "attachment":
            continue

        payload = part.get_payload(decode=True)

        if payload is None:
            continue

        charset = part.get_content_charset() or "utf-8"

        try:
            return payload.decode(charset, errors="replace")
        except (LookupError, UnicodeError):
            return payload.decode("utf-8", errors="replace")

    return "[No plain text content available]"


def parse_raw_email(raw_bytes, uid):
    msg = email.message_from_bytes(raw_bytes, policy=policy.default)

    return {
        "id": str(uid),
        "subject": clean_header_text(msg.get("Subject")),
        "from": clean_header_text(msg.get("From")),
        "date": clean_header_text(msg.get("Date")),
        "body": get_email_body(msg),
    }


# ============ ASYNC EMAIL PROCESSOR ============

async def process_email(mail):
    """
    Called automatically whenever a new email arrives.
    Add your own processing logic here.
    """

    print("\n========== NEW EMAIL ==========")
    print("UID:", mail["id"])
    print("From:", mail["from"])
    print("Subject:", mail["subject"])
    print("Date:", mail["date"])
    print("Body:", mail["body"])
    print("===============================\n")

    # Your custom async processing:
    # await classify_email(mail)
    # await save_to_database(mail)
    # await send_to_backend(mail)


# ============ IMAP LISTENER ============

def watch_mailbox(loop, queue, stop_event):
    """
    Runs in a separate thread.
    Listens for new mail using IMAP IDLE.
    Pushes new messages into the asyncio queue.
    """

    last_uid = None
    last_uidvalidity = None

    while not stop_event.is_set():
        try:
            print(f"Connecting to {IMAP_SERVER}:{IMAP_PORT}...")

            with IMAPClient(
                IMAP_SERVER,
                port=IMAP_PORT,
                ssl=True,
                ssl_context=ssl.create_default_context(),
                timeout=30
            ) as client:

                client.login(EMAIL_ACCOUNT, APP_PASSWORD)

                info = client.select_folder(FOLDER, readonly=True)
                uidvalidity = info[b"UIDVALIDITY"]

                # Detect mailbox replacement/reset
                if last_uidvalidity != uidvalidity:
                    last_uid = None
                    last_uidvalidity = uidvalidity

                if last_uid is None:
                    existing = client.search(["ALL"])
                    last_uid = max(existing, default=0)

                print("Connected. Watching for new emails...")

                def fetch_new():
                    nonlocal last_uid

                    # Find messages with UID greater than last_uid
                    candidates = client.search([
                        "UID", f"{last_uid + 1}:*"
                    ])

                    new_uids = sorted(
                        uid for uid in candidates
                        if uid > last_uid
                    )

                    for uid in new_uids:
                        data = client.fetch([uid], ["RFC822"])
                        raw = data.get(uid, {}).get(b"RFC822")

                        if raw is None:
                            continue

                        parsed = parse_raw_email(raw, uid)

                        # Thread-safe push to async queue
                        loop.call_soon_threadsafe(
                            queue.put_nowait,
                            parsed
                        )

                        last_uid = uid

                while not stop_event.is_set():

                    # First, catch any mail received since last check
                    fetch_new()

                    # Enter server-push notification mode
                    client.idle()

                    try:
                        client.idle_check(timeout=IDLE_TIMEOUT)
                    finally:
                        client.idle_done()

                    # On notification or timeout, check for new UIDs

        except Exception as exc:
            if stop_event.is_set():
                break

            print(f"IMAP connection error: {exc}")
            print(f"Reconnecting in {RECONNECT_DELAY}s...")

            stop_event.wait(RECONNECT_DELAY)


# ============ ASYNC CONSUMER ============

async def email_consumer(queue):
    while True:
        mail = await queue.get()

        try:
            await process_email(mail)
        except Exception as exc:
            print(f"Email processing failed: {exc}")
        finally:
            queue.task_done()


# ============ MAIN ============

async def main():
    if not EMAIL_ACCOUNT or not APP_PASSWORD:
        raise ValueError(
            "Missing EMAIL_ACCOUNT or APP_PASSWORD in .env"
        )

    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()
    stop_event = threading.Event()

    listener = threading.Thread(
        target=watch_mailbox,
        args=(loop, queue, stop_event),
        daemon=True
    )

    listener.start()

    try:
        await email_consumer(queue)
    finally:
        stop_event.set()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
