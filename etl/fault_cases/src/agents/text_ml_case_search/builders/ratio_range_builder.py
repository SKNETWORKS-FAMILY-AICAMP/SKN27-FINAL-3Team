from __future__ import annotations

import re
from typing import Any


RATIO_PATTERN = re.compile(r"(\d{1,3})\s*[:：]\s*(\d{1,3})")


def build_ratio_range_label(*, evidence: list[dict[str, Any]]) -> str:
    """Build a reference ratio label from RAG evidence."""

    for item in evidence:
        metadata = item.get("metadata") or {}
        decision_fault_ratio = _clean(metadata.get("decision_fault_ratio"))
        if decision_fault_ratio:
            return decision_fault_ratio

    for item in evidence:
        metadata = item.get("metadata") or {}
        claimant = _clean(metadata.get("claimant_final_ratio"))
        respondent = _clean(metadata.get("respondent_final_ratio"))
        if claimant and respondent:
            return f"claimant {claimant} : respondent {respondent}"

    for item in evidence:
        match = RATIO_PATTERN.search(_clean(item.get("chunk_text")))
        if match:
            return f"{match.group(1)} : {match.group(2)}"

    return ""


def _clean(value: Any) -> str:
    return str(value or "").strip()
