from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class RatioParseResult:
    decision_fault_ratio: str | None
    a_role: str | None
    b_role: str | None
    a_ratio: int | None
    b_ratio: int | None
    claimant_final_ratio: int | None
    respondent_final_ratio: int | None


def _role(value: str | None) -> str | None:
    if not value:
        return None
    if "피청구" in value:
        return "respondent"
    if "청구" in value:
        return "claimant"
    return None


def parse_decision_ratio(text: str) -> RatioParseResult:
    pattern = re.compile(
        r"(A\s*\((?P<a_role>\s*청구\s*|\s*피청구\s*)\)\s*:\s*B\s*\((?P<b_role>\s*청구\s*|\s*피청구\s*)\)\s*=\s*(?P<a>\d{1,3})\s*:\s*(?P<b>\d{1,3}))"
    )
    match = pattern.search(text or "")
    if not match:
        return RatioParseResult(None, None, None, None, None, None, None)

    a_role = _role(match.group("a_role"))
    b_role = _role(match.group("b_role"))
    a_ratio = int(match.group("a"))
    b_ratio = int(match.group("b"))
    claimant = a_ratio if a_role == "claimant" else b_ratio if b_role == "claimant" else None
    respondent = a_ratio if a_role == "respondent" else b_ratio if b_role == "respondent" else None
    return RatioParseResult(match.group(1), a_role, b_role, a_ratio, b_ratio, claimant, respondent)


def find_final_ratio_text(text: str) -> str | None:
    text = re.sub(r"\s+", " ", text or "")
    patterns = [
        r"(청구차량\s*\d{1,3}\s*%\s*(?:●|/|,|\s)+피청구차량\s*\d{1,3}\s*%)",
        r"(청구인\s*\d{1,3}\s*%\s*(?:●|/|,|\s)+피청구인\s*\d{1,3}\s*%)",
        r"(A\s*\d{1,3}\s*%\s*(?:●|/|,|\s)+B\s*\d{1,3}\s*%)",
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text)
        if matches:
            return matches[-1].strip()
    candidates = re.findall(r"((?:청구|피청구|A|B)[^%]{0,25}\d{1,3}\s*%)", text)
    return " ".join(candidates[-2:]).strip() if len(candidates) >= 2 else None
