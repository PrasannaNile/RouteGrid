import os
from pathlib import Path
from dotenv import load_dotenv
from src.ingestion.imap_client import IMAPClient

# Explicitly find and load the .env file from the project root
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=ROOT_DIR / ".env")

IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", 993))
EMAIL_ACCOUNT = os.getenv("EMAIL_ACCOUNT")
APP_PASSWORD = os.getenv("APP_PASSWORD")
FETCH_LIMIT = int(os.getenv("FETCH_LIMIT", 5))

def main():
    # Defensive check: fail early with a clear message if credentials aren't loaded
    if not EMAIL_ACCOUNT or not APP_PASSWORD:
        print(f"DEBUG: EMAIL_ACCOUNT is {repr(EMAIL_ACCOUNT)}")
        print(f"DEBUG: APP_PASSWORD is {repr(APP_PASSWORD)}")
        raise ValueError("Could not read credentials from .env. Check your .env file location and variable names.")

    client = IMAPClient(IMAP_SERVER, IMAP_PORT, EMAIL_ACCOUNT, APP_PASSWORD)
    print("Connecting to mailbox...")
    client.connect()

    print(f"Fetching latest {FETCH_LIMIT} emails...")
    emails = client.fetch_latest_emails(limit=FETCH_LIMIT)

    for idx, item in enumerate(emails, start=1):
        print(f"--- Email #{idx} ---")
        print(f"From:    {item['from']}")
        print(f"Date:    {item['date']}")
        print(f"Subject: {item['subject']}")
        print(f"Body:    {item['body'].strip()[:200]}...")
        print("-" * 50 + "\n")

    client.disconnect()
    print("Done.")

if __name__ == "__main__":
    main()