"""Central privacy boundary for chat text passed to storage and AI services."""

from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from app.security.pii_masking import detect_text_categories, sanitize_pii


ANALYSIS_TEXT_FIELDS = (
    "conversation_history",
    "facts",
    "fact_sources",
    "fact_conflicts",
    "ocr_confirmation",
    "context",
    "slot_state",
    "upstream_results",
)


@dataclass(frozen=True)
class ChatInputPrivacyPolicy:
    max_chars: int = 8_000
    block_secrets: bool = True
    resident_id_policy: str = "block"
    driver_license_policy: str = "block"

    @classmethod
    def from_runtime(cls) -> "ChatInputPrivacyPolicy":
        return cls(
            max_chars=_positive_int(os.environ.get("CHAT_INPUT_MAX_CHARS"), 8_000),
            block_secrets=_truthy(os.environ.get("CHAT_INPUT_BLOCK_SECRETS", "1")),
            resident_id_policy=os.environ.get("CHAT_INPUT_RESIDENT_ID_POLICY", "block"),
            driver_license_policy=os.environ.get(
                "CHAT_INPUT_DRIVER_LICENSE_POLICY",
                "block",
            ),
        )


@dataclass(frozen=True)
class ChatInputPrivacyDecision:
    status: str
    safe_user_text: str
    category_counts: tuple[tuple[str, int], ...]
    blocked_categories: tuple[str, ...]
    message: str

    def public_metadata(self) -> dict[str, Any]:
        return {
            "contract_version": "chat_input_privacy.v1",
            "status": self.status,
            "masked_categories": [category for category, _count in self.category_counts],
            "blocked_categories": list(self.blocked_categories),
            "category_counts": dict(self.category_counts),
            "message": self.message,
        }


class ChatInputRejected(ValueError):
    """Stable rejection that intentionally does not retain or echo raw input."""

    def __init__(self, decision: ChatInputPrivacyDecision) -> None:
        super().__init__(decision.message)
        self.decision = decision


def protect_chat_input_payload(
    payload: dict[str, Any],
    *,
    policy: ChatInputPrivacyPolicy | None = None,
) -> dict[str, Any]:
    """Return a sanitized copy suitable for persistence, Supervisor, Agent and RAG."""

    active_policy = policy or ChatInputPrivacyPolicy.from_runtime()
    user_text = str(payload.get("safe_user_text") or payload.get("user_text") or "")
    decision = inspect_chat_input(user_text, policy=active_policy)
    if decision.status == "blocked":
        raise ChatInputRejected(decision)

    protected = deepcopy(payload)
    protected["user_text"] = decision.safe_user_text
    protected["safe_user_text"] = decision.safe_user_text
    for field in ANALYSIS_TEXT_FIELDS:
        if field in protected:
            protected[field] = sanitize_pii(protected[field])
    protected["privacy_gateway"] = decision.public_metadata()
    return protected


def inspect_chat_input(
    user_text: str,
    *,
    policy: ChatInputPrivacyPolicy | None = None,
) -> ChatInputPrivacyDecision:
    active_policy = policy or ChatInputPrivacyPolicy.from_runtime()
    category_counts = detect_text_categories(user_text)
    blocked: list[str] = []
    if len(user_text) > active_policy.max_chars:
        blocked.append("input_too_long")
    if active_policy.block_secrets and category_counts.get("secret"):
        blocked.append("secret")
    if active_policy.resident_id_policy == "block" and category_counts.get("resident_id"):
        blocked.append("resident_id")
    if active_policy.driver_license_policy == "block" and category_counts.get("driver_license"):
        blocked.append("driver_license")

    safe_text = str(sanitize_pii(user_text))
    status = "blocked" if blocked else ("needs_redaction" if category_counts else "accepted")
    message = (
        "민감정보 또는 허용 범위를 벗어난 입력이 감지되어 요청을 처리하지 않았습니다."
        if blocked
        else (
            "민감정보가 감지되어 일부 내용을 가렸습니다."
            if category_counts
            else "입력 검증을 통과했습니다."
        )
    )
    return ChatInputPrivacyDecision(
        status=status,
        safe_user_text=safe_text,
        category_counts=tuple(sorted(category_counts.items())),
        blocked_categories=tuple(blocked),
        message=message,
    )


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
