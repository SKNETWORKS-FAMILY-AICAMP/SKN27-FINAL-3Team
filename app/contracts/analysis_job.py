"""Pydantic DTOs for canonical asynchronous analysis job endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AnalysisJobContractModel(BaseModel):
    """Preserve additive supervisor and agent payload fields in the shadow contract."""

    model_config = ConfigDict(extra="allow")


class AnalysisJobRequest(AnalysisJobContractModel):
    session_id: str | None = Field(default=None, min_length=1, max_length=128)
    job_id: str | None = Field(default=None, min_length=1, max_length=128)
    message_id: str | None = Field(default=None, min_length=1, max_length=128)
    user_text: str | None = Field(default=None, min_length=1)
    routing_intent: str | None = Field(default=None, min_length=1, max_length=120)
    attachments: list[dict[str, Any]] | None = None


class AnalysisJobSummary(AnalysisJobContractModel):
    job_id: str = Field(min_length=1, max_length=128)
    status: str = Field(min_length=1, max_length=64)


class AnalysisJobAccepted(AnalysisJobSummary):
    contract_version: str = Field(min_length=1, max_length=64)
    session_id: str | None = Field(default=None, min_length=1, max_length=128)
    message_id: str | None = Field(default=None, min_length=1, max_length=128)
    execution_mode: str = Field(min_length=1, max_length=64)


class AnalysisJobListResponse(AnalysisJobContractModel):
    jobs: list[AnalysisJobSummary]


class AnalysisJobAcceptedResponse(AnalysisJobContractModel):
    job: AnalysisJobAccepted


class AnalysisJobDetailResponse(AnalysisJobContractModel):
    job: AnalysisJobSummary


class AnalysisUserClaim(AnalysisJobContractModel):
    """A user-provided statement kept separate from confirmed facts."""

    field: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=2000)
    source_type: str | None = Field(default=None, min_length=1, max_length=64)


class AnalysisResult(AnalysisJobSummary):
    contract_version: str = Field(min_length=1, max_length=64)
    user_claims: list[AnalysisUserClaim] = Field(default_factory=list)


class AnalysisResultResponse(AnalysisJobContractModel):
    result: AnalysisResult


class AnalysisJobError(AnalysisJobContractModel):
    contract_version: str | None = Field(default=None, min_length=1, max_length=64)
    type: str | None = Field(default=None, min_length=1, max_length=64)
    code: str = Field(min_length=1, max_length=120)
    status: int | None = Field(default=None, ge=400, le=599)
    message: str = Field(min_length=1)


class AnalysisJobErrorResponse(AnalysisJobContractModel):
    error: AnalysisJobError
