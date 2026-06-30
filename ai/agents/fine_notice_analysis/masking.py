import re
from typing import Optional

# lambda 기반으로 재정의 (슬라이싱 필요)
_LAMBDA_PATTERNS: list[tuple[re.Pattern, object]] = [
    (re.compile(r"\d{6}-[1-4]\d{6}"),   lambda m: "●●●●●●-●●●●●●●"),
    (re.compile(r"\d{3}[가-힣]\d{4}"),  lambda m: m.group()[:4] + "●●●●"),
    (re.compile(r"\d{2}[가-힣]\d{4}"),  lambda m: m.group()[:3] + "●●●●"),
    (re.compile(r"\d{2}[나-힣]\d{3}"),  lambda m: m.group()[:3] + "●●●"),
    (re.compile(r"외교\d{5}"),          lambda m: "외교●●●●●"),
]


def mask_personal_info(text: str) -> str:
    """GPT raw 응답 전체에 개인정보 마스킹 적용 (R-11)."""
    for pattern, replacement in _LAMBDA_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def mask_field(value: Optional[str]) -> Optional[str]:
    """단일 필드 코드 레벨 이중 마스킹."""
    if value is None:
        return None
    return mask_personal_info(value)
