"""Public shadow contracts for the existing chat session Django endpoints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatContractRequest(BaseModel):
    """Strict documented request shape; it is not attached to Django views."""

    model_config = ConfigDict(extra="forbid")


class ChatSessionCreateRequest(ChatContractRequest):
    """Draft session issuance accepts no client-owned identity field."""


class ChatMessageRequest(ChatContractRequest):
    session_id: str | None = Field(default=None, min_length=1, max_length=128)
    user_text: str | None = Field(default=None, min_length=1)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    conversation_history: list[dict[str, Any]] = Field(default_factory=list)
    conversation_save_state: Literal["saved", "pending", "session_only"] | None = None
    execution_mode: str | None = Field(default=None, min_length=1, max_length=64)
    routing_intent: str | None = Field(default=None, min_length=1, max_length=120)
    case_storage_consent: bool | None = None


class ChatSaveStateRequest(ChatContractRequest):
    session_id: str = Field(min_length=1, max_length=128)
    conversation_save_state: Literal["saved", "pending", "session_only"]
    conversation_save_source: str | None = Field(default=None, max_length=120)


class ChatPublicResponseModel(BaseModel):
    """Permissive response documentation preserves current public extensions."""

    model_config = ConfigDict(extra="allow")


class ChatSessionCreateResponse(ChatPublicResponseModel):
    contract_version: Literal["chat_session.v1"]
    session_id: str = Field(min_length=1, max_length=128)
    user_id: str | None = Field(default=None, min_length=1, max_length=128)
    status: str = Field(min_length=1, max_length=64)
    created_at: str = Field(min_length=1)


class ChatMessageResponse(ChatPublicResponseModel):
    contract_version: str | None = Field(default=None, min_length=1, max_length=64)
    status: str = Field(min_length=1, max_length=64)
    session_id: str | None = Field(default=None, min_length=1, max_length=128)
    message_id: str | None = Field(default=None, min_length=1, max_length=128)
    execution_mode: str | None = Field(default=None, min_length=1, max_length=64)
    work_item: dict[str, Any] | None = None
    supervisor_execution: dict[str, Any] | None = None
    persistence: dict[str, Any] | None = None


class ConversationSaveResult(ChatPublicResponseModel):
    status: Literal["updated", "skipped"]
    conversation_save_state: Literal["saved", "pending", "session_only"]
    reason: str | None = None
    session_id: str | None = Field(default=None, min_length=1, max_length=128)


class ChatSaveStateResponse(ChatPublicResponseModel):
    conversation_save: ConversationSaveResult


class ChatApiError(ChatPublicResponseModel):
    code: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1)
    status: int | None = Field(default=None, ge=400, le=599)


class ChatApiErrorResponse(ChatPublicResponseModel):
    error: ChatApiError
