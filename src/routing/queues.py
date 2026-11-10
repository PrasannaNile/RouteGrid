"""ZEISS India queue registry and JSONL queue writer."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import QUEUE_ROOT
from .decision import RoutingDecision


@dataclass(frozen=True)
class Queue:
    """One downstream destination."""

    slug: str
    address: str
    purpose: str


QUEUES: tuple[Queue, ...] = (
    Queue(
        "info_in",
        "info.in@zeiss.com",
        "General ZEISS India inquiries, company information and customer "
        "assistance, including mail that does not clearly belong to a "
        "specialist queue.",
    ),
    Queue(
        "mikroservice_india",
        "mikroservice.india@zeiss.com",
        "Microscopy technical support, equipment servicing, repairs, "
        "maintenance visits and service contracts.",
    ),
    Queue(
        "info_microscopy_in",
        "info.microscopy.in@zeiss.com",
        "Microscopy product inquiries, sales information, application "
        "assistance, quotations and demo requests.",
    ),
    Queue(
        "info_meditec_in",
        "info.meditec.in@zeiss.com",
        "Medical technology inquiries, ophthalmology and surgical equipment, "
        "clinical applications and Meditec sales.",
    ),
    Queue(
        "iolorder_in",
        "iolorder.in@zeiss.com",
        "Intraocular lens (IOL) orders, medical consumables, order status, "
        "delivery and related order inquiries.",
    ),
    Queue(
        "info_metrology_in",
        "info.metrology.in@zeiss.com",
        "Industrial metrology, measuring equipment, quality inspection, "
        "calibration and related support.",
    ),
    Queue(
        "zeiss_co_in",
        "info@zeiss.co.in",
        "General inquiries about ZEISS India optical products and services, "
        "including vision care, eyeglass lenses and consumer optics.",
    ),
    Queue(
        "dpo_in",
        "dpo.in@zeiss.com",
        "Data privacy concerns, personal data access or deletion requests, "
        "and GDPR or Indian privacy compliance.",
    ),
    Queue(
        "legal_in",
        "legal.in@zeiss.com",
        "Legal inquiries, compliance matters, contracts, litigation and "
        "privacy-related legal concerns.",
    ),
    Queue(
        "webmaster",
        "webmaster@zeiss.com",
        "Website technical problems, broken links, login failures on ZEISS "
        "websites and other website-related issues.",
    ),
)

QUEUES_BY_SLUG = {queue.slug: queue for queue in QUEUES}

_queue_lock = threading.Lock()


def queue_path(queue: str, *, root: Path = QUEUE_ROOT) -> Path:
    """Path of today's queue file, e.g. ``queues/legal_in/2026-11-10.jsonl``."""

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return root / queue / f"{stamp}.jsonl"


def enqueue(
    mail: dict[str, Any],
    decision: RoutingDecision,
    *,
    root: Path = QUEUE_ROOT,
) -> Path:
    """Append the message and its routing decision to the queue file."""

    path = queue_path(decision.queue, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)

    record = {
        "queued_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "queue": decision.queue,
        "address": decision.address,
        "decision": {
            "confidence": decision.confidence,
            "probabilities": decision.probabilities,
            "urgency": decision.urgency,
            "is_zeiss_inquiry": decision.is_zeiss_inquiry,
            "method": decision.method,
            "reason": decision.reason,
            "model": decision.model,
            "cost_usd": decision.cost,
        },
        "mail": {
            "id": mail.get("id"),
            "from": mail.get("from"),
            "subject": mail.get("subject"),
            "date": mail.get("date"),
            "body": mail.get("body"),
        },
    }

    line = json.dumps(record, ensure_ascii=False) + "\n"

    with _queue_lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)

    return path
