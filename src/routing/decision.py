"""The routing decision for a single message."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import REVIEW_QUEUE


@dataclass
class RoutingDecision:
    """Where a message should go, and why."""

    queue: str
    address: str
    confidence: float | None = None
    probabilities: dict[str, float] = field(default_factory=dict)
    urgency: float | None = None
    is_zeiss_inquiry: float | None = None
    method: str = "decisions"
    reason: str = ""
    model: str = ""
    cost: float | None = None

    @property
    def is_review(self) -> bool:
        return self.queue == REVIEW_QUEUE


def format_decision(decision: RoutingDecision) -> str:
    """One-line summary for logs."""

    target = decision.address or "human review"

    if decision.confidence is None:
        confidence = "n/a"
    else:
        confidence = f"{decision.confidence:.2f}"

    summary = f"{decision.queue} ({target}) confidence={confidence}"

    if decision.urgency is not None:
        summary += f" urgency={decision.urgency:.2f}"

    if decision.reason:
        summary += f" - {decision.reason}"

    return summary
