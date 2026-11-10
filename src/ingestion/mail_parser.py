"""Turn raw MIME messages into normalized mail records."""

from __future__ import annotations

import email
from email import policy
from email.header import decode_header
from typing import Any


def clean_header_text(value: str | None) -> str:
    """Decode RFC 2047 MIME-encoded headers into plain text."""

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


def get_email_body(msg: email.message.Message) -> str:
    """Return the first non-attachment ``text/plain`` part."""

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


def parse_raw_email(raw_bytes: bytes, uid: Any) -> dict[str, Any]:
    """Build the normalized record used by the router and the queues."""

    msg = email.message_from_bytes(raw_bytes, policy=policy.default)

    return {
        "id": str(uid),
        "subject": clean_header_text(msg.get("Subject")),
        "from": clean_header_text(msg.get("From")),
        "date": clean_header_text(msg.get("Date")),
        "body": get_email_body(msg),
    }
