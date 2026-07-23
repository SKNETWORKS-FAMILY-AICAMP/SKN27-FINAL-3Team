"""Narrow result normalization for attachment document classification."""

from __future__ import annotations

from math import isfinite
from typing import Any, Mapping


CLASSIFICATIONS = frozenset({"fine_notice", "accident_evidence", "unknown"})
CONFIDENCE_BANDS = ((0.85, "high"), (0.60, "medium"), (0.00, "low"))


def normalize_classification(raw: Mapping[str, Any]) -> dict[str, str | bool]:
    """Keep only the classification fields permitted across the chat boundary."""

    classification = str(raw.get("classification") or "unknown").strip().lower()
    if classification not in CLASSIFICATIONS:
        classification = "unknown"
    confidence_band = _confidence_band(_bounded_float(raw.get("confidence")))
    if classification == "unknown" or confidence_band == "low":
        return {
            "classification": "unknown",
            "confidence_band": confidence_band,
            "requires_confirmation": False,
            "next_action": "change_purpose",
        }
    return {
        "classification": classification,
        "confidence_band": confidence_band,
        "requires_confirmation": True,
        "next_action": "confirm_classification",
    }


def _bounded_float(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not isfinite(normalized):
        return 0.0
    return min(max(normalized, 0.0), 1.0)


def _confidence_band(confidence: float) -> str:
    return next(label for threshold, label in CONFIDENCE_BANDS if confidence >= threshold)
