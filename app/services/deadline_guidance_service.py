"""Present verified appeal deadlines without recalculating statutory rules."""

from __future__ import annotations

import json
import os
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any


POLICY_CONTRACT_VERSION = "deadline_guidance_policy.v1"
GUIDANCE_CONTRACT_VERSION = "deadline_guidance.v1"
DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "deadline_guidance_policy.v1.json"
)


@lru_cache(maxsize=1)
def _deadline_guidance_policy() -> dict[str, Any]:
    configured_path = os.environ.get("DEADLINE_GUIDANCE_POLICY_PATH", "").strip()
    path = Path(configured_path).expanduser() if configured_path else DEFAULT_POLICY_PATH
    raw = json.loads(path.read_text(encoding="utf-8"))
    _validate_policy(raw)
    return raw


def build_deadline_guidance(
    structured_result: dict[str, Any],
    *,
    source_node_code: str,
    today: date | None = None,
) -> dict[str, Any]:
    """Classify one verified deadline emitted by an agent result."""

    policy = _deadline_guidance_policy()
    deadline = _parse_date(structured_result.get("computed_deadline"))
    effective_today = today or date.today()
    if deadline is None:
        status = "needs_confirmation"
        days_remaining = None
    else:
        days_remaining = (deadline - effective_today).days
        if bool(structured_result.get("deadline_passed")) or days_remaining < 0:
            status = "overdue"
        elif days_remaining <= policy["due_soon_days"]:
            status = "due_soon"
        else:
            status = "normal"

    guidance = policy["statuses"][status]
    deadline_value = deadline.isoformat() if deadline else None
    return {
        "contract_version": GUIDANCE_CONTRACT_VERSION,
        "status": status,
        "deadline": deadline_value,
        "days_remaining": days_remaining,
        "source_node_code": _text(source_node_code),
        "card_title": _text(guidance["card_title"]),
        "reason": _format_reason(guidance["reason"], deadline_value),
        "limitations": _string_list(guidance["limitations"]),
        "next_actions": _string_list(guidance["next_actions"]),
    }


def _validate_policy(policy: Any) -> None:
    if not isinstance(policy, dict):
        raise ValueError("deadline_guidance_policy_must_be_an_object")
    if policy.get("contract_version") != POLICY_CONTRACT_VERSION:
        raise ValueError("unsupported_deadline_guidance_policy_version")
    if not isinstance(policy.get("due_soon_days"), int) or policy["due_soon_days"] < 0:
        raise ValueError("deadline_guidance_policy_requires_due_soon_days")
    statuses = policy.get("statuses")
    if not isinstance(statuses, dict) or set(statuses) != {
        "overdue",
        "due_soon",
        "normal",
        "needs_confirmation",
    }:
        raise ValueError("deadline_guidance_policy_requires_all_statuses")
    for guidance in statuses.values():
        if (
            not isinstance(guidance, dict)
            or not _text(guidance.get("card_title"))
            or not _text(guidance.get("reason"))
        ):
            raise ValueError("deadline_guidance_policy_requires_display_text")
        if not _string_list(guidance.get("limitations")) or not _string_list(guidance.get("next_actions")):
            raise ValueError("deadline_guidance_policy_requires_safe_guidance")


def _parse_date(value: Any) -> date | None:
    if not _text(value):
        return None
    try:
        return date.fromisoformat(_text(value)[:10])
    except ValueError:
        return None


def _format_reason(template: str, deadline: str | None) -> str:
    return template.format(deadline=deadline or "확인 필요")


def _string_list(value: Any) -> list[str]:
    return [_text(item) for item in value or [] if _text(item)]


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""
