"""Bounded public consultation-type routing.

The browser may select a consultation category, but it must never select a
Supervisor plan or an individual Agent.  Keep this mapping intentionally small
and return an empty value for everything outside the published categories.
"""

from __future__ import annotations

from typing import Any


PUBLIC_CONSULTATION_TYPE_INTENTS = {
    "general": "general_consultation",
    "fault_ratio": "accident_initial_consultation",
    "fine_notice": "fine_notice_procedure",
}


def resolve_public_consultation_intent(value: Any) -> str:
    """Map a published consultation type to one server-owned routing intent."""

    return PUBLIC_CONSULTATION_TYPE_INTENTS.get(str(value or "").strip(), "")
