from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.services.consultation_v2_service import CORE_FACT_QUESTIONS


_CORE_FIELDS = tuple(field for field, _question in CORE_FACT_QUESTIONS)
_CONFLICT_KEYS = frozenset({"field", "candidates"})
_CANDIDATE_KEYS = frozenset(
    {"value", "source_message_id", "confidence"}
)
_SELF_MARKER = r"(?:저는|제가|나는|내가|제\s*차(?:량)?|우리\s*차(?:량)?)"
_GREEN_CLAIM = re.compile(
    rf"{_SELF_MARKER}[^.!?。]{{0,32}}(?:녹색(?:\s*신호)?|초록불)"
)
_RED_CLAIM = re.compile(
    rf"{_SELF_MARKER}[^.!?。]{{0,32}}(?:빨간불|적색(?:\s*신호)?)"
)
_UNCERTAINTY_MARKERS = (
    "보일 수도",
    "보일수도",
    "것처럼",
    "가능",
    "수 있습니다",
    "수 있어",
)


def _normalized_value(value: str) -> str:
    return " ".join(value.split()).casefold()


def _normalize_candidate(
    value: Any,
    *,
    default_source_message_id: str,
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or set(value) != _CANDIDATE_KEYS:
        return None
    candidate_value = str(value.get("value") or "").strip()
    if not candidate_value:
        return None
    source_message_id = (
        default_source_message_id
        or str(value.get("source_message_id") or "").strip()
    )
    confidence = value.get("confidence")
    if (
        not source_message_id
        or isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(float(confidence))
        or not 0.0 <= float(confidence) <= 1.0
    ):
        return None
    return {
        "value": candidate_value,
        "source_message_id": source_message_id,
        "confidence": float(confidence),
    }


def normalize_fact_conflicts(
    value: Any,
    *,
    default_source_message_id: str = "",
) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        return []

    candidates_by_field: dict[str, list[dict[str, Any]]] = {}
    for raw_conflict in value:
        if (
            not isinstance(raw_conflict, Mapping)
            or set(raw_conflict) != _CONFLICT_KEYS
        ):
            continue
        field = str(raw_conflict.get("field") or "").strip()
        raw_candidates = raw_conflict.get("candidates")
        if (
            field not in _CORE_FIELDS
            or not isinstance(raw_candidates, Sequence)
            or isinstance(raw_candidates, (str, bytes, bytearray))
            or len(raw_candidates) < 2
        ):
            continue

        normalized_candidates: list[dict[str, Any]] = []
        normalized_values: set[str] = set()
        valid = True
        for raw_candidate in raw_candidates:
            candidate = _normalize_candidate(
                raw_candidate,
                default_source_message_id=default_source_message_id,
            )
            if candidate is None:
                valid = False
                break
            normalized = _normalized_value(candidate["value"])
            if normalized in normalized_values:
                valid = False
                break
            normalized_values.add(normalized)
            normalized_candidates.append(candidate)
        if not valid or len(normalized_candidates) < 2:
            continue

        merged = candidates_by_field.setdefault(field, [])
        existing_values = {
            _normalized_value(candidate["value"]) for candidate in merged
        }
        for candidate in normalized_candidates:
            if _normalized_value(candidate["value"]) not in existing_values:
                merged.append(candidate)
                existing_values.add(_normalized_value(candidate["value"]))

    return [
        {"field": field, "candidates": candidates_by_field[field]}
        for field in _CORE_FIELDS
        if len(candidates_by_field.get(field, [])) >= 2
    ]


def detect_same_message_fact_conflicts(
    user_text: str,
    source_message_id: str,
) -> list[dict[str, Any]]:
    text = str(user_text or "").strip()
    message_id = str(source_message_id or "").strip()
    if not text or not message_id:
        return []

    segments = [
        segment.strip()
        for segment in re.split(r"[.!?。]+", text)
        if segment.strip()
    ]
    green_segments = [segment for segment in segments if _GREEN_CLAIM.search(segment)]
    red_segments = [segment for segment in segments if _RED_CLAIM.search(segment)]
    if not green_segments or not red_segments:
        return []

    red_uncertain = any(
        marker in segment
        for segment in red_segments
        for marker in _UNCERTAINTY_MARKERS
    )
    return [
        {
            "field": "signal_priority",
            "candidates": [
                {
                    "value": "녹색 신호에 직진했다는 진술",
                    "source_message_id": message_id,
                    "confidence": 0.9,
                },
                {
                    "value": (
                        "빨간불에 진입한 것으로 보일 수 있다는 진술"
                        if red_uncertain
                        else "빨간불에 진입했다는 진술"
                    ),
                    "source_message_id": message_id,
                    "confidence": 0.8 if red_uncertain else 0.9,
                },
            ],
        }
    ]
