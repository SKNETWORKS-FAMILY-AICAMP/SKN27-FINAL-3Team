"""Pydantic DTOs for canonical uploaded-file API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class FileContractModel(BaseModel):
    """Keep documentation aligned with additive runtime attachment metadata."""

    model_config = ConfigDict(extra="allow")


class FileUploadRequest(FileContractModel):
    session_id: str = Field(min_length=1, max_length=128)
    file: bytes | None = None
    case_id: str | None = Field(default=None, min_length=1, max_length=64)
    message_id: str | None = Field(default=None, min_length=1, max_length=128)
    purpose: str | None = Field(default=None, min_length=1, max_length=64)
    type: str | None = Field(default=None, min_length=1, max_length=64)
    filename: str | None = Field(default=None, min_length=1, max_length=255)
    original_filename: str | None = Field(default=None, min_length=1, max_length=255)
    content_type: str | None = Field(default=None, min_length=1, max_length=255)
    size_bytes: int | None = Field(default=None, ge=0)


class FileAttachment(FileContractModel):
    attachment_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    purpose: str = Field(min_length=1, max_length=64)
    type: str = Field(min_length=1, max_length=64)
    original_filename: str = Field(min_length=1, max_length=255)
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=0)
    storage_uri: str = Field(min_length=1)
    object_storage: dict[str, Any]
    status: str = Field(min_length=1, max_length=64)
    scan_status: str = Field(min_length=1, max_length=64)
    privacy_risk: bool
    created_at: datetime
    checks: dict[str, Any]
    agent_handoff: dict[str, Any]
    limitations: list[str]
    persistence: dict[str, Any]
    case_id: str | None = None
    message_id: str | None = None
    retention_expires_at: datetime | None = None
    deleted_at: datetime | None = None
    scan_result: dict[str, Any] | None = None


class FileAttachmentResponse(FileContractModel):
    attachment: FileAttachment


class FileReadAttachment(FileContractModel):
    """Allow-listed public representation for canonical FileRead GET routes."""

    model_config = ConfigDict(extra="forbid")

    attachment_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    purpose: str = Field(min_length=1, max_length=64)
    type: str = Field(min_length=1, max_length=64)
    original_filename: str = Field(min_length=1, max_length=255)
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=0)
    status: str = Field(min_length=1, max_length=64)
    scan_status: str = Field(min_length=1, max_length=64)
    privacy_risk: bool
    created_at: datetime
    limitations: list[str]
    case_id: str | None = None
    message_id: str | None = None
    retention_expires_at: datetime | None = None


class FileAttachmentListResponse(FileContractModel):
    attachments: list[FileReadAttachment]


class FileAttachmentDetailResponse(FileContractModel):
    attachment: FileReadAttachment

class FileObjectAccessError(FileContractModel):
    contract_version: Literal["object_access.v1"]
    type: Literal["object_access"]
    code: Literal["object_access_denied"]
    status: Literal[403]
    message: str
    required_action: Literal["login_or_owner_match"]
    access: dict[str, Any]


class FileObjectAccessErrorResponse(FileContractModel):
    error: FileObjectAccessError


class FileGuestSessionError(FileContractModel):
    contract_version: Literal["guest_identity_policy.v1"]
    type: Literal["authorization"]
    code: Literal["guest_session_invalid"]
    status: Literal[401]
    message: str
    required_action: Literal["refresh_guest_session"]
    reason: str
    guest_id: str
    guest_status: str


class FileGuestSessionErrorResponse(FileContractModel):
    error: FileGuestSessionError


class FileUploadValidationError(FileContractModel):
    contract_version: Literal["file_upload_error.v1"]
    type: Literal["validation"]
    code: Literal["session_id_required"]
    status: Literal[400]
    message: str
    required_action: Literal["create_or_select_session"]


class FileUploadValidationErrorResponse(FileContractModel):
    error: FileUploadValidationError


class FileUploadTooLargeError(FileContractModel):
    contract_version: Literal["file_upload_error.v1"]
    type: Literal["validation"]
    code: Literal["file_too_large"]
    status: Literal[413]
    message: str
    size_bytes: int = Field(ge=0)
    limit_bytes: int = Field(ge=1)
    required_action: Literal["select_smaller_file"]


class FileUploadTooLargeErrorResponse(FileContractModel):
    error: FileUploadTooLargeError


class FileRateLimitError(FileContractModel):
    contract_version: Literal["rate_limit.v1"]
    type: Literal["rate_limit"]
    code: Literal["rate_limit_exceeded"]
    status: Literal[429]
    message: str
    required_action: str
    usage: dict[str, Any]


class FileRateLimitErrorResponse(FileContractModel):
    error: FileRateLimitError


class FileUploadStorageError(FileContractModel):
    contract_version: Literal["file_upload_error.v1"]
    type: Literal["service_unavailable"]
    code: Literal["upload_storage_unavailable"]
    status: Literal[503]
    message: str
    required_action: Literal["retry_upload"]
    retryable: Literal[True]


class FileUploadStorageErrorResponse(FileContractModel):
    error: FileUploadStorageError


class FileAttachmentNotFoundError(FileContractModel):
    code: Literal["attachment_not_found"]
    message: str


class FileAttachmentNotFoundErrorResponse(FileContractModel):
    error: FileAttachmentNotFoundError
