"""HTTP client for OpenRouter's Decisions API.

Only this module talks HTTP. The rest of the app deals in
``DecisionPayload`` / ``Answer`` objects.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests

from .config import (
    API_KEY,
    DECISIONS_ENDPOINT,
    REQUEST_TIMEOUT,
    RETRY_ATTEMPTS,
    RETRY_STATUSES,
)
from .models import Answer, DecisionPayload, parse_answers


class DecisionsError(RuntimeError):
    """Raised when the Decisions API cannot be reached or rejects a request."""


@dataclass(frozen=True)
class DecisionsResponse:
    """A validated Decisions API response."""

    answers: dict[str, Answer]
    model: str
    cost: float | None
    raw: dict[str, Any]


def _describe_http_error(response: requests.Response) -> str:
    detail = (response.text or "").strip()
    if len(detail) > 500:
        detail = detail[:500] + "..."

    hints = {
        400: "The model may not support this request shape; see the error body.",
        401: "API_KEY must be an OpenRouter key.",
        402: "The OpenRouter account is out of credits.",
        429: "Rate limited and retries were exhausted.",
    }

    message = f"Decisions API returned HTTP {response.status_code}"
    if detail:
        message += f": {detail}"

    hint = hints.get(response.status_code)
    if hint:
        message += f" ({hint})"

    return message


def ask(
    payload: DecisionPayload,
    *,
    api_key: str | None = API_KEY,
    timeout: int = REQUEST_TIMEOUT,
    attempts: int = RETRY_ATTEMPTS,
) -> DecisionsResponse:
    """Submit a Decisions request, retrying transient failures."""

    if not api_key:
        raise DecisionsError("API_KEY not found in .env")

    body = payload.to_dict()
    last_error: DecisionsError | None = None

    for attempt in range(attempts):
        try:
            response = requests.post(
                DECISIONS_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            last_error = DecisionsError(f"Could not reach OpenRouter: {exc}")
        else:
            if response.status_code == 200:
                return _parse_response(response, fallback_model=payload.model)

            last_error = DecisionsError(_describe_http_error(response))
            if response.status_code not in RETRY_STATUSES:
                raise last_error

        if attempt + 1 < attempts:
            time.sleep(2**attempt)

    assert last_error is not None
    raise last_error


def _parse_response(
    response: requests.Response,
    *,
    fallback_model: str,
) -> DecisionsResponse:
    try:
        data = response.json()
    except ValueError as exc:
        raise DecisionsError(f"Decisions API returned invalid JSON: {exc}")

    try:
        answers = parse_answers(data.get("answers") or {})
    except ValueError as exc:
        raise DecisionsError(f"Invalid Decisions response: {exc}")

    usage = data.get("usage") or {}

    return DecisionsResponse(
        answers=answers,
        model=data.get("model", fallback_model),
        cost=usage.get("cost"),
        raw=data,
    )
