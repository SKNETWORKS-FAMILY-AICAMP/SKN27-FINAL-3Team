"""Public shadow contract for the existing canonical history endpoint."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HistoryPublicModel(BaseModel):
    """Preserve additive history metadata while documenting stable fields."""

    model_config = ConfigDict(extra="allow")


class HistoryEvent(HistoryPublicModel):
    event_id: str = Field(min_length=1, max_length=128)
    event_type: str = Field(min_length=1, max_length=128)
    event_version: str = Field(min_length=1, max_length=64)
    occurred_at: str = Field(min_length=1)
    actor: dict[str, Any]
    subject: dict[str, Any]
    source: dict[str, Any]
    status: str = Field(min_length=1, max_length=64)


class HistoryListResponse(HistoryPublicModel):
    """Compatibility-preserving response from ``GET /api/history/``."""

    history_contract: str = Field(min_length=1, max_length=64)
    storage: dict[str, Any]
    history_policy: dict[str, Any]
    after_service_summary: dict[str, Any]
    count: int = Field(ge=0)
    events: list[HistoryEvent]
    limitations: list[str]


class HistoryApiError(HistoryPublicModel):
    code: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1)
    status: int | None = Field(default=None, ge=400, le=599)


class HistoryApiErrorResponse(HistoryPublicModel):
    error: HistoryApiError
