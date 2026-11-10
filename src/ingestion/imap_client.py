import imaplib
import ssl
from typing import List, Dict
from src.ingestion.mail_parser import parse_raw_email


class IMAPClient:
    def __init__(self, host: str, port: int, username: str, password: str):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.mail = None

    def connect(self):
        # Create standard SSL context
        context = ssl.create_default_context()
        
        # Enforce TLS 1.2 to avoid buggy TLS 1.3 / OpenSSL 3.x middlebox renegotiations
        context.maximum_version = ssl.TLSVersion.TLSv1_2
        context.minimum_version = ssl.TLSVersion.TLSv1_2

        # Connect with the explicit context
        self.mail = imaplib.IMAP4_SSL(self.host, self.port, ssl_context=context)
        self.mail.login(self.username, self.password)

    def fetch_latest_emails(self, limit: int = 5, folder: str = "INBOX") -> List[Dict]:
        if not self.mail:
            raise ConnectionError("IMAP client is not connected. Call connect() first.")

        self.mail.select(folder, readonly=True)
        status, search_data = self.mail.search(None, "ALL")
        if status != "OK":
            return []

        message_ids = search_data[0].split()
        target_ids = message_ids[-limit:]

        parsed_emails = []
        for email_id in reversed(target_ids):
            status, data = self.mail.fetch(email_id, "(RFC822)")
            if status != "OK":
                continue

            raw_bytes = data[0][1]
            parsed_data = parse_raw_email(raw_bytes)
            parsed_data["id"] = email_id.decode()
            parsed_emails.append(parsed_data)

        return parsed_emails

    def disconnect(self):
        if self.mail:
            try:
                self.mail.close()
            except Exception:
                pass
            self.mail.logout()
            self.mail = None