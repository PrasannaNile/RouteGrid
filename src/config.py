"""Configuration, loaded once from ``.env`` and the environment."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


# ============ IMAP ============

IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.mail.yahoo.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
EMAIL_ACCOUNT = os.getenv("EMAIL_ACCOUNT")
APP_PASSWORD = os.getenv("APP_PASSWORD")
IMAP_FOLDER = os.getenv("IMAP_FOLDER", "INBOX")

# Seconds IMAP IDLE waits for a server notification before re-checking.
IDLE_TIMEOUT = int(os.getenv("IDLE_TIMEOUT", "60"))
RECONNECT_DELAY = int(os.getenv("RECONNECT_DELAY", "5"))


# ============ DECISIONS API ============

API_KEY = os.getenv("API_KEY") or os.getenv("OPENROUTER_API_KEY")
DECISIONS_ENDPOINT = "https://openrouter.ai/api/alpha/decisions"

ROUTER_MODEL = os.getenv("ROUTER_MODEL", "parallel/decisions-fast:free")

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "60"))
RETRY_ATTEMPTS = int(os.getenv("RETRY_ATTEMPTS", "3"))
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504, 529})

# Keep the state we send well inside the model's context window.
MAX_BODY_CHARS = int(os.getenv("MAX_BODY_CHARS", "8000"))


# ============ ROUTING ============

# Minimum probability for the winning queue. Below this the mail is reviewed
# by a human instead of being routed on a coin flip.
CONFIDENCE_THRESHOLD = float(os.getenv("ROUTER_THRESHOLD", "0.60"))

# Minimum probability that the mail is a real ZEISS inquiry at all.
INQUIRY_THRESHOLD = float(os.getenv("ROUTER_INQUIRY_THRESHOLD", "0.50"))

QUEUE_ROOT = Path(os.getenv("QUEUE_DIR", BASE_DIR / "queues"))

REVIEW_QUEUE = "_review"
