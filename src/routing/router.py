"""Classify inbound mail and enqueue it for a ZEISS queue.

Every message is sent to a Decisions model which answers three typed
questions: whether the mail is a genuine ZEISS India inquiry, which queue
owns it, and how urgent it is. The result is appended to
``queues/<queue>/<date>.jsonl``; anything unclear goes to ``queues/_review``
instead of being guessed at.

One-off CLI:
    python -m src.routing.router sample.json --dry-run
    python -m src.routing.router --body "My IOL order never arrived"
    python -m src.routing.router sample.eml
    python -m src.routing.router --list-queues
"""

from __future__ import annotations

import argparse
import asyncio
import ast
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import (
    CONFIDENCE_THRESHOLD,
    INQUIRY_THRESHOLD,
    MAX_BODY_CHARS,
    QUEUE_ROOT,
    REVIEW_QUEUE,
    ROUTER_MODEL,
)
from ..decisions import DecisionsError, ask
from ..models import Answer, DecisionPayload, Question
from .decision import RoutingDecision, format_decision
from .queues import QUEUES, QUEUES_BY_SLUG, enqueue

URGENCY_LEVELS = (
    "Routine - can be handled in normal queue order",
    "Time-sensitive - a customer is blocked or a deadline is close",
    "Urgent - production line down, safety issue, legal deadline or data breach",
)


# ============ CLASSIFICATION ============

def build_questions() -> dict[str, Question]:
    """The three questions asked about every message."""

    return {
        "is_zeiss_inquiry": Question(
            type="noul",
            instructions=(
                "Is this message a genuine inbound inquiry or request that a "
                "ZEISS India department should handle, rather than an "
                "automated notification, newsletter, marketing blast, spam "
                "or personal mail unrelated to ZEISS?"
            ),
            criteria={
                "true": (
                    "A customer, prospect, partner, supplier, regulator or "
                    "employee is asking ZEISS India for information, support, "
                    "a quotation, an order or action."
                ),
                "false": (
                    "An automated system notification (security alert, "
                    "password change, delivery receipt), newsletter, "
                    "marketing email, spam or unrelated personal mail."
                ),
            },
        ),
        "department": Question(
            type="choice",
            instructions=(
                "Which ZEISS India queue should own this message? Choose the "
                "single best fit. Service and repair requests are not product "
                "sales inquiries, and lens orders are not general inquiries."
            ),
            criteria={
                queue.slug: f"{queue.address}: {queue.purpose}"
                for queue in QUEUES
            },
        ),
        "urgency": Question(
            type="score",
            instructions="How urgently does this message need a response?",
            criteria=list(URGENCY_LEVELS),
        ),
    }


def build_state(mail: dict[str, Any]) -> dict[str, Any]:
    """The application state the model reasons over."""

    body = (mail.get("body") or "").strip()

    return {
        "channel": "email",
        "from": mail.get("from", ""),
        "subject": mail.get("subject", ""),
        "date": mail.get("date", ""),
        "body": body[:MAX_BODY_CHARS],
    }


def _require(
    answers: dict[str, Answer],
    key: str,
    expected_type: str,
) -> Answer:
    answer = answers.get(key)

    if answer is None:
        raise DecisionsError(f"The model returned no answer for {key!r}.")

    if answer.type != expected_type:
        raise DecisionsError(
            f"Answer {key!r} is {answer.type!r}, expected {expected_type!r}."
        )

    return answer


def _urgency(answers: dict[str, Answer]) -> float | None:
    answer = answers.get("urgency")

    if answer is not None and answer.type == "score":
        return answer.value

    return None


def interpret(
    answers: dict[str, Answer],
    *,
    threshold: float = CONFIDENCE_THRESHOLD,
    inquiry_threshold: float = INQUIRY_THRESHOLD,
    model: str = ROUTER_MODEL,
    cost: float | None = None,
) -> RoutingDecision:
    """Turn validated answers into a routing decision."""

    inquiry = _require(answers, "is_zeiss_inquiry", "noul")
    department = _require(answers, "department", "choice")

    inquiry_probability = inquiry.value
    urgency = _urgency(answers)

    if inquiry_probability < inquiry_threshold:
        return RoutingDecision(
            queue=REVIEW_QUEUE,
            address="",
            confidence=inquiry_probability,
            probabilities=department.probabilities,
            is_zeiss_inquiry=inquiry_probability,
            urgency=urgency,
            reason=(
                f"not a ZEISS inquiry (p={inquiry_probability:.2f} < "
                f"{inquiry_threshold:.2f})"
            ),
            model=model,
            cost=cost,
        )

    slug = department.value

    if slug not in QUEUES_BY_SLUG:
        return RoutingDecision(
            queue=REVIEW_QUEUE,
            address="",
            confidence=None,
            probabilities=department.probabilities,
            is_zeiss_inquiry=inquiry_probability,
            urgency=urgency,
            reason=f"model chose unknown queue {slug!r}",
            model=model,
            cost=cost,
        )

    probabilities = department.probabilities
    confidence = probabilities.get(slug)

    if confidence is None:
        # Some models omit probabilities; fall back to the overall confidence.
        confidence = department.confidence

    if confidence is not None and confidence < threshold:
        return RoutingDecision(
            queue=REVIEW_QUEUE,
            address="",
            confidence=confidence,
            probabilities=probabilities,
            is_zeiss_inquiry=inquiry_probability,
            urgency=urgency,
            reason=(
                f"low confidence for {slug} (p={confidence:.2f} < "
                f"{threshold:.2f})"
            ),
            model=model,
            cost=cost,
        )

    queue = QUEUES_BY_SLUG[slug]

    return RoutingDecision(
        queue=queue.slug,
        address=queue.address,
        confidence=confidence,
        probabilities=probabilities,
        is_zeiss_inquiry=inquiry_probability,
        urgency=urgency,
        reason="" if confidence is not None else "unscored by model",
        model=model,
        cost=cost,
    )


def classify(
    mail: dict[str, Any],
    *,
    model: str = ROUTER_MODEL,
    threshold: float = CONFIDENCE_THRESHOLD,
    inquiry_threshold: float = INQUIRY_THRESHOLD,
    session_id: str | None = None,
) -> RoutingDecision:
    """Ask the Decisions model where a message belongs."""

    questions = build_questions()

    payload = DecisionPayload(
        model=model,
        state=build_state(mail),
        questions=questions,
        session_id=session_id,
    )

    response = ask(payload)

    # Validate that the model answered the questions we actually asked.
    for key, question in questions.items():
        _require(response.answers, key, question.type)

    return interpret(
        response.answers,
        threshold=threshold,
        inquiry_threshold=inquiry_threshold,
        model=response.model,
        cost=response.cost,
    )


# ============ DISPATCH ============

def route(
    mail: dict[str, Any],
    *,
    root: Path = QUEUE_ROOT,
    **classify_kwargs: Any,
) -> tuple[RoutingDecision, Path]:
    """Classify a message and enqueue it.

    Never raises on classification failure: the message lands in the review
    queue with the error attached, so no mail is lost.
    """

    try:
        decision = classify(mail, **classify_kwargs)
    except Exception as exc:
        decision = RoutingDecision(
            queue=REVIEW_QUEUE,
            address="",
            method="error",
            reason=f"classification_failed: {exc}",
        )

    path = enqueue(mail, decision, root=root)

    return decision, path


async def route_email(
    mail: dict[str, Any],
    *,
    root: Path = QUEUE_ROOT,
    **kwargs: Any,
) -> RoutingDecision:
    """Async wrapper: runs the blocking HTTP call in a worker thread."""

    decision, _ = await asyncio.to_thread(route, mail, root=root, **kwargs)
    return decision


# ============ CLI ============

def _load_mail(args: argparse.Namespace) -> dict[str, Any]:
    mail: dict[str, Any] = {
        "id": "cli",
        "subject": "",
        "from": "",
        "date": datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z"),
        "body": "",
    }

    if args.source:
        path = Path(args.source)

        if not path.exists():
            raise SystemExit(f"File not found: {path}")

        suffix = path.suffix.lower()

        if suffix == ".json":
            text = path.read_text(encoding="utf-8")

            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                # Older fixtures were Python dict literals, not strict JSON.
                try:
                    data = ast.literal_eval(text)
                except (ValueError, SyntaxError) as exc:
                    raise SystemExit(f"{path} is not valid JSON: {exc}")

            if not isinstance(data, dict):
                raise SystemExit(f"{path} must contain a JSON object.")

            mail.update(data)
        elif suffix in {".eml", ".msg"}:
            from ..ingestion.mail_parser import parse_raw_email

            mail.update(parse_raw_email(path.read_bytes(), path.stem))
        else:
            mail["body"] = path.read_text(encoding="utf-8")

    # Explicit flags win over values read from the file.
    if args.subject:
        mail["subject"] = args.subject
    if args.sender:
        mail["from"] = args.sender
    if args.body:
        mail["body"] = args.body

    if not mail["body"] and not mail["subject"]:
        raise SystemExit("Provide a JSON/EML file, a text file or --body.")

    return mail


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Route an email to a ZEISS India queue."
    )
    parser.add_argument(
        "source",
        nargs="?",
        help="JSON mail record, .eml file, or plain-text body file.",
    )
    parser.add_argument("--body", help="Raw body text.")
    parser.add_argument("--subject", default="", help="Mail subject.")
    parser.add_argument(
        "--sender", "--from", dest="sender", default="", help="Sender header."
    )
    parser.add_argument(
        "--model",
        default=ROUTER_MODEL,
        help=f"Decisions model (default: {ROUTER_MODEL}).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=CONFIDENCE_THRESHOLD,
        help="Minimum queue probability before routing.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify only; do not write to a queue file.",
    )
    parser.add_argument(
        "--list-queues", action="store_true", help="Print the queue registry."
    )

    args = parser.parse_args(argv)

    if args.list_queues:
        for queue in QUEUES:
            print(f"{queue.slug:<20} {queue.address:<28} {queue.purpose}")
        print(f"{REVIEW_QUEUE:<20} {'(local)':<28} Low confidence / not an inquiry.")
        return 0

    mail = _load_mail(args)

    if args.dry_run:
        try:
            decision = classify(mail, model=args.model, threshold=args.threshold)
        except DecisionsError as exc:
            print(f"Classification failed: {exc}", file=sys.stderr)
            return 1
        print(format_decision(decision))
        print(json.dumps(decision.probabilities, indent=2, sort_keys=True))
        return 0

    decision, path = route(mail, model=args.model, threshold=args.threshold)

    print(format_decision(decision))
    print(f"Queued at: {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
