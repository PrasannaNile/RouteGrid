import email
from email.header import decode_header


def clean_header_text(header_val: str) -> str:
    """Decodes MIME-encoded headers into a clean string."""
    if not header_val:
        return ""
    decoded_fragments = decode_header(header_val)
    parsed_parts = []
    for content, encoding in decoded_fragments:
        if isinstance(content, bytes):
            parsed_parts.append(content.decode(encoding or "utf-8", errors="replace"))
        else:
            parsed_parts.append(str(content))
    return "".join(parsed_parts)


def get_email_body(msg_obj) -> str:
    """Extracts plaintext body from multipart or single-part messages."""
    if msg_obj.is_multipart():
        for part in msg_obj.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition"))

            if content_type == "text/plain" and "attachment" not in disposition:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
    else:
        payload = msg_obj.get_payload(decode=True)
        charset = msg_obj.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")

    return "[No plain text content available]"


def parse_raw_email(raw_bytes: bytes) -> dict:
    """Converts raw email bytes into a clean dictionary."""
    msg = email.message_from_bytes(raw_bytes)
    return {
        "subject": clean_header_text(msg.get("Subject")),
        "from": clean_header_text(msg.get("From")),
        "date": clean_header_text(msg.get("Date")),
        "body": get_email_body(msg),
    }