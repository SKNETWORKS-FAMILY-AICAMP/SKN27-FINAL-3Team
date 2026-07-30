"""검색 단계에서 외부로 안전하게 전달할 수 있는 오류."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class SearchStageError(RuntimeError):
    code: str
    message: str
    stage: str
    retryable: bool = False

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "stage": self.stage,
            "retryable": self.retryable,
        }
