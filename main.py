
import os
import ssl
import imaplib
import email
import socket
from pathlib import Path
from email.header import decode_header
from dotenv import load_dotenv


# ============ CONFIGURATION ============

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv()

IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com").strip()
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
EMAIL_ACCOUNT = os.getenv("EMAIL_ACCOUNT")
APP_PASSWORD = os.getenv("APP_PASSWORD")
FETCH_LIMIT = int(os.getenv("FETCH_LIMIT", "5"))


# ============ EMAIL PARSER ============

def clean_header_text(value):
    if not value:
        return ""

    parts = []
    for content, encoding in decode_header(value):
        if isinstance(content, bytes):
            parts.append(content.decode(encoding or "utf-8", errors="replace"))
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
        return payload.decode(charset, errors="replace")

    return "[No plain text content available]"


def parse_raw_email(raw_bytes):
    msg = email.message_from_bytes(raw_bytes)

    return {
        "subject": clean_header_text(msg.get("Subject")),
        "from": clean_header_text(msg.get("From")),
        "date": clean_header_text(msg.get("Date")),
        "body": get_email_body(msg),
    }


# ============ IMAP CLIENT ============

class IMAPClient:
    def __init__(self, host, port, username, password):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.mail = None

    def connect(self):
        if not self.host:
            raise ValueError("IMAP_SERVER is empty")

        print(f"Connecting to {self.host}:{self.port}...")

        context = ssl.create_default_context()

        self.mail = imaplib.IMAP4_SSL(
            self.host,
            self.port,
            ssl_context=context,
            timeout=15
        )

        self.mail.login(self.username, self.password)
        print("Connected successfully!")

    def fetch_latest_emails(self, limit=5, folder="INBOX"):
        if self.mail is None:
            raise ConnectionError("Not connected to IMAP server")

        if limit <= 0:
            return []

        status, _ = self.mail.select(folder, readonly=True)
        if status != "OK":
            raise RuntimeError(f"Cannot select mailbox: {folder}")

        status, data = self.mail.search(None, "ALL")
        if status != "OK" or not data or not data[0]:
            return []

        message_ids = data[0].split()
        target_ids = message_ids[-limit:]

        emails = []

        for message_id in reversed(target_ids):
            status, response = self.mail.fetch(
                message_id, "(RFC822)"
            )

            if status != "OK":
                continue

            raw_bytes = next(
                (
                    item[1]
                    for item in response
                    if isinstance(item, tuple)
                    and isinstance(item[1], bytes)
                ),
                None
            )

            if raw_bytes is None:
                continue

            parsed = parse_raw_email(raw_bytes)
            parsed["id"] = message_id.decode()
            emails.append(parsed)

        return emails

    def disconnect(self):
        if self.mail is not None:
            try:
                self.mail.logout()
            finally:
                self.mail = None


# ============ MAIN ============

def main():
    if not EMAIL_ACCOUNT or not APP_PASSWORD:
        raise ValueError(
            "Missing EMAIL_ACCOUNT or APP_PASSWORD in .env"
        )

    client = IMAPClient(
        IMAP_SERVER,
        IMAP_PORT,
        EMAIL_ACCOUNT,
        APP_PASSWORD
    )

    try:
        client.connect()

        print(f"Fetching latest {FETCH_LIMIT} emails...\n")
        emails = client.fetch_latest_emails(FETCH_LIMIT)

        print(f"Fetched {len(emails)} emails\n")

        for index, item in enumerate(emails, start=1):
            print(f"--- Email #{index} ---")
            print(f"From:    {item['from']}")
            print(f"Date:    {item['date']}")
            print(f"Subject: {item['subject']}")
            print(f"Body:    {item['body'].strip()[:200]}...")
            print("-" * 50 + "\n")

        print("Done.")

    except socket.gaierror:
        print(
            f"DNS Error: Cannot resolve '{IMAP_SERVER}'. "
            "Check IMAP_SERVER in your .env file."
        )

    except imaplib.IMAP4.error as exc:
        print(f"IMAP Error: {exc}")

    except (OSError, ssl.SSLError) as exc:
        print(f"Connection Error: {exc}")

    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
