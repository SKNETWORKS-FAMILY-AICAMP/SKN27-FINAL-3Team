from __future__ import annotations

import re
from typing import Any


JsonDict = dict[str, Any]


TARGET_FIELDS = [
    "_case_id",
    "사건명",
    "사건번호",
    "선고일자",
    "법원명",
    "사건종류명",
    "판시사항",
    "판결요지",
    "참조조문",
    "참조판례",
    "판례내용",
    "주문",
    "이유",
    "과실비율",
    "source_provider",
    "source_reference",
    "_matched_keywords",
    "topic_labels",
]

LIST_FIELDS = {
    "_matched_keywords",
    "topic_labels",
}

NULL_DEFAULT_FIELDS = set(TARGET_FIELDS) - LIST_FIELDS

ERROR_MESSAGE_PATTERNS = (
    "일치하는 판례가 없습니다",
    "판례명을 확인",
    "검색 결과가 없습니다",
    "조회된 데이터가 없습니다",
)


def normalize_empty(value: Any) -> Any:
    """Normalize empty strings and empty containers to None."""

    if value is None:
        return None

    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None

    if isinstance(value, (list, tuple, set, dict)) and not value:
        return None

    return value


def normalize_date(value: Any) -> str | None:
    """
    Normalize judgment date values.

    Supports YYYYMMDD and common dotted or dashed variants.
    """

    value = normalize_empty(value)

    if value is None:
        return None

    text = str(value).strip()
    digits = re.sub(r"\D", "", text)

    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"

    return text


def normalize_list(value: Any) -> list[Any]:
    """Normalize a value into a list."""

    value = normalize_empty(value)

    if value is None:
        return []

    if isinstance(value, list):
        return [item for item in value if normalize_empty(item) is not None]

    if isinstance(value, tuple | set):
        return [item for item in value if normalize_empty(item) is not None]

    return [value]


def normalize_values(row: JsonDict) -> JsonDict:
    """Normalize dates, list fields, and empty values for a schema row."""

    normalized = dict(row)

    normalized["선고일자"] = normalize_date(normalized.get("선고일자"))

    for field in LIST_FIELDS:
        normalized[field] = normalize_list(normalized.get(field))

    for field in NULL_DEFAULT_FIELDS:
        normalized[field] = normalize_empty(normalized.get(field))

    return normalized


def is_error_message(value: Any) -> bool:
    """Return True when a field value looks like an API failure message."""

    if not isinstance(value, str):
        return False

    return any(pattern in value for pattern in ERROR_MESSAGE_PATTERNS)


def is_valid_case(row: JsonDict) -> bool:
    """
    Check whether a raw row is a usable precedent detail row.

    A row is invalid if it is a JSON decode failure, an API failure response,
    or it lacks the minimum case id/title/body fields.
    """

    if row.get("_json_decode_error"):
        return False

    if is_error_message(row.get("Law")):
        return False

    case_id = normalize_empty(row.get("_case_id") or row.get("판례정보일련번호"))
    case_name = normalize_empty(row.get("사건명"))
    case_text = normalize_empty(row.get("판례내용"))

    return bool(case_id and case_name and case_text)


def invalid_reason(row: JsonDict) -> str:
    """Return a simple reason label for an invalid raw row."""

    if row.get("_json_decode_error"):
        return "json_decode_error"

    if is_error_message(row.get("Law")):
        return "api_no_matching_precedent"

    if not normalize_empty(row.get("_case_id") or row.get("판례정보일련번호")):
        return "missing_case_id"

    if not normalize_empty(row.get("사건명")):
        return "missing_case_name"

    if not normalize_empty(row.get("판례내용")):
        return "missing_case_text"

    return "unknown_invalid_reason"


def split_valid_invalid_cases(rows: list[JsonDict]) -> tuple[list[JsonDict], list[JsonDict]]:
    """Split raw rows into valid cases and invalid rows with reason labels."""

    valid_rows: list[JsonDict] = []
    invalid_rows: list[JsonDict] = []

    for row in rows:
        if is_valid_case(row):
            valid_rows.append(row)
            continue

        invalid_row = dict(row)
        invalid_row["_invalid_reason"] = invalid_reason(row)
        invalid_rows.append(invalid_row)

    return valid_rows, invalid_rows


def normalize_case_schema(row: JsonDict) -> JsonDict:
    """Map a raw API row to the final 18-field preprocessing schema."""

    schema_row: JsonDict = {field: None for field in TARGET_FIELDS}

    schema_row.update(
        {
            "_case_id": row.get("_case_id") or row.get("판례정보일련번호"),
            "사건명": row.get("사건명"),
            "사건번호": row.get("사건번호"),
            "선고일자": row.get("선고일자"),
            "법원명": row.get("법원명"),
            "사건종류명": row.get("사건종류명"),
            "판시사항": row.get("판시사항"),
            "판결요지": row.get("판결요지"),
            "참조조문": row.get("참조조문"),
            "참조판례": row.get("참조판례"),
            "판례내용": row.get("판례내용"),
            "주문": row.get("주문"),
            "이유": row.get("이유"),
            "과실비율": row.get("과실비율"),
            "source_provider": row.get("source_provider"),
            "source_reference": row.get("source_reference"),
            "_matched_keywords": row.get("_matched_keywords"),
            "topic_labels": row.get("topic_labels"),
        }
    )

    return normalize_values(schema_row)


def normalize_cases(rows: list[JsonDict]) -> list[JsonDict]:
    """Normalize multiple raw rows to the final schema."""

    return [normalize_case_schema(row) for row in rows]
