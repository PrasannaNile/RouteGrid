"""Typed models for OpenRouter's Decisions API.

The Decisions API takes an application ``state`` plus a record of typed
``questions`` and returns one typed answer per question, with probabilities,
instead of generated text.

Reference: https://openrouter.ai/docs/guides/community/jev
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

QUESTION_TYPES = frozenset({"noul", "choice", "score", "box"})


@dataclass(frozen=True)
class Question:
    """One typed question for a Decisions model.

    ``noul``   - yes/no judgement, answered with a probability.
    ``choice`` - pick one option from ``criteria`` (name -> description).
    ``score``  - pick a level from an ordered ``criteria`` list, lowest first.
    ``box``    - locate a target in an image (instructions only).
    """

    type: str
    instructions: str
    criteria: Mapping[str, Any] | Sequence[Any] | None = None

    def __post_init__(self) -> None:
        if self.type not in QUESTION_TYPES:
            raise ValueError(
                f"Unsupported question type {self.type!r}; "
                f"expected one of {sorted(QUESTION_TYPES)}"
            )

        if self.type == "noul" and self.criteria is not None:
            if not isinstance(self.criteria, Mapping) or set(self.criteria) != {
                "true",
                "false",
            }:
                raise ValueError(
                    'A "noul" question has exactly two criteria: "true" and "false".'
                )

        if self.type == "choice":
            if not isinstance(self.criteria, Mapping) or not self.criteria:
                raise ValueError(
                    'A "choice" question needs a non-empty criteria mapping '
                    "of option name -> description."
                )

        if self.type == "score":
            if (
                isinstance(self.criteria, (str, bytes))
                or not isinstance(self.criteria, Sequence)
                or len(self.criteria) < 2
            ):
                raise ValueError(
                    'A "score" question needs an ordered list of at least '
                    "two levels, lowest first."
                )

        if self.type == "box" and self.criteria is not None:
            raise ValueError('A "box" question takes instructions only, no criteria.')

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "type": self.type,
            "instructions": self.instructions,
        }

        if self.criteria is not None:
            body["criteria"] = (
                dict(self.criteria)
                if isinstance(self.criteria, Mapping)
                else list(self.criteria)
            )

        return body


@dataclass
class DecisionPayload:
    """Request body for the Decisions endpoint."""

    model: str
    state: str | Mapping[str, Any] | Sequence[Any]
    questions: Mapping[str, Question]
    session_id: str | None = None
    user: str | None = None

    def __post_init__(self) -> None:
        if not self.model:
            raise ValueError("A Decisions request needs a model ID.")

        if not self.questions:
            raise ValueError("A Decisions request needs at least one question.")

        for key, question in self.questions.items():
            if not isinstance(question, Question):
                raise TypeError(f"Question {key!r} must be a Question instance.")

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "state": self.state,
            "questions": {
                key: question.to_dict()
                for key, question in self.questions.items()
            },
        }

        if self.session_id:
            body["session_id"] = self.session_id
        if self.user:
            body["user"] = self.user

        return body


@dataclass(frozen=True)
class Answer:
    """One typed answer from the Decisions API.

    Always read ``type`` (and therefore ``value``) rather than guessing:
    a model may answer some questions and skip others.
    """

    key: str
    type: str
    payload: Mapping[str, Any] = field(repr=False)

    def __post_init__(self) -> None:
        if self.type not in QUESTION_TYPES:
            raise ValueError(
                f"Answer {self.key!r} has unexpected type {self.type!r}."
            )

        if self.type not in self.payload:
            raise ValueError(
                f"Answer {self.key!r} is missing its {self.type!r} field."
            )

    @property
    def value(self) -> Any:
        value = self.payload[self.type]
        if self.type in {"noul", "score"}:
            return float(value)
        return value

    @property
    def probabilities(self) -> dict[str, float]:
        raw = self.payload.get("probabilities") or {}
        return {str(key): float(value) for key, value in raw.items()}

    @property
    def confidence(self) -> float | None:
        value = self.payload.get("confidence")
        return None if value is None else float(value)

    @property
    def legend(self) -> dict[str, Any]:
        return dict(self.payload.get("legend") or {})


def parse_answers(
    raw: Mapping[str, Any],
    expected: Mapping[str, str] | None = None,
) -> dict[str, Answer]:
    """Validate a raw ``answers`` object and wrap it in ``Answer`` objects."""

    if not isinstance(raw, Mapping):
        raise ValueError("The Decisions response has no 'answers' object.")

    answers: dict[str, Answer] = {}

    for key, body in raw.items():
        if not isinstance(body, Mapping):
            raise ValueError(f"Answer {key!r} is not an object.")

        answer = Answer(key=key, type=body.get("type"), payload=body)

        if expected and key in expected and expected[key] != answer.type:
            raise ValueError(
                f"Answer {key!r} is {answer.type!r}, expected {expected[key]!r}."
            )

        answers[key] = answer

    return answers
