"""Public shadow contract for the existing MyPage summary Django endpoint."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MyPagePublicResponseModel(BaseModel):
    """Keep additive operational metadata compatible with the current response."""

    model_config = ConfigDict(extra="allow")


class MyPageCaseSummary(MyPagePublicResponseModel):
    """Stable case identity fields; runtime may expose additional case metadata."""

    job_id: str | None = Field(default=None, min_length=1, max_length=128)
    session_id: str | None = Field(default=None, min_length=1, max_length=128)
    status: str | None = Field(default=None, min_length=1, max_length=64)


class MyPageSummaryResponse(MyPagePublicResponseModel):
    """Compatibility-preserving summary returned by ``GET /api/mypage/summary/``."""

    active_cases: int = Field(ge=0)
    due_soon_cases: int = Field(ge=0)
    saved_reports: int = Field(ge=0)
    recent_analysis_count: int = Field(ge=0)
    cases: list[MyPageCaseSummary]
    conversation_save_policy: dict[str, Any]
    limitations: list[str]
