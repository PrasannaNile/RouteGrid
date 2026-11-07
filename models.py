from dataclasses import dataclass, asdict
from typing import Literal

@dataclass
class Question:
    type: Literal["noul", "choice", "score"]
    instructions: str
    criteria: dict[str, str] | list[str]

@dataclass
class DecisionPayload:
    state: str
    questions: dict[str, Question]
    model: str = "parallel/decisions-fast:free"

    def to_dict(self) -> dict:
        return asdict(self)