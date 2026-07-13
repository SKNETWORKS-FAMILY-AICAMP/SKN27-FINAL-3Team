"""Pydantic request DTOs for consultation Case v2 endpoints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateConsultationCaseRequest(StrictRequest):
    session_id: str = Field(min_length=1, max_length=64)
    title: str = Field(default="", max_length=200)
    case_type: Literal["accident_fault"] = "accident_fault"
    consultation_state: dict[str, Any] = Field(default_factory=dict)
    location: dict[str, Any] = Field(default_factory=dict)


class ConfirmCaseFactsRequest(StrictRequest):
    facts: dict[str, Any] = Field(min_length=1)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    user_edit_history: list[dict[str, Any]] = Field(default_factory=list)


class StartCaseAnalysisRequest(StrictRequest):
    fact_version_id: str = Field(default="", max_length=64)
