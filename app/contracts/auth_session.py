"""Pydantic DTOs for the existing authentication session endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AuthRequest(BaseModel):
    """Document accepted request fields without changing Django body parsing."""

    model_config = ConfigDict(extra="allow")


class AuthResponse(BaseModel):
    """Shared response base for authentication boundary DTOs."""

    model_config = ConfigDict(extra="allow")


class GuestSessionRequest(AuthRequest):
    guest_id: str | None = Field(default=None, min_length=1, max_length=128)
    session_id: str | None = Field(default=None, min_length=1, max_length=128)


class GoogleAuthorizationCodeRequest(AuthRequest):
    auth_flow: Literal["google_authorization_code_popup"] = (
        "google_authorization_code_popup"
    )
    provider: Literal["google"] = "google"
    client_id: str = Field(min_length=1, max_length=256)
    code: str = Field(min_length=1, max_length=4096, json_schema_extra={"writeOnly": True})
    purpose: Literal["LOGIN"] = "LOGIN"
    scope: str | None = Field(default=None, max_length=512)
    guest_id: str | None = Field(default=None, min_length=1, max_length=128)
    session_id: str | None = Field(default=None, min_length=1, max_length=128)
    redirect_uri: str = Field(
        min_length=1,
        max_length=2048,
        json_schema_extra={"format": "uri"},
    )


class AuthTokenRefreshRequest(AuthRequest):
    guest_id: str | None = Field(default=None, min_length=1, max_length=128)
    session_id: str | None = Field(default=None, min_length=1, max_length=128)
    access_token: str | None = Field(default=None, min_length=1, max_length=8192)


class AuthLogoutRequest(AuthTokenRefreshRequest):
    pass


class GuestIdentity(AuthResponse):
    guest_id: str = Field(min_length=1, max_length=128)
    status: Literal["active"]
    issued_at: datetime | None = None
    expires_at: datetime | None = None
    ttl_seconds: int | None = Field(default=None, ge=1)
    policy_status: str


class AuthUser(AuthResponse):
    user_id: str = Field(min_length=1, max_length=128)
    email: str | None = None
    display_name: str | None = None
    picture: str | None = None
    status: str | None = None
    auth_provider: Literal["google"]
    provider_subject: str | None = None
    policy_status: str | None = None


class AuthSubject(AuthResponse):
    subject_id: str = Field(min_length=1, max_length=256)
    subject_type: Literal["anonymous", "guest", "user"]
    user_id: str | None = None
    guest_id: str | None = None
    auth_session_id: str | None = None
    is_authenticated: bool


class AuthSession(AuthResponse):
    auth_session_id: str = Field(min_length=1, max_length=128)
    jwt_jti: str = Field(min_length=1, max_length=128)
    status: Literal["active", "revoked", "expired"]
    verification: str = Field(min_length=1, max_length=128)
    provider: Literal["google"]


class SessionBinding(AuthResponse):
    session_id: str | None = None
    can_bind_to_chat_session: bool
    binding_policy: str | None = None


class RateLimitPolicy(AuthResponse):
    subject_id: str = Field(min_length=1, max_length=256)
    policy_status: str = Field(min_length=1, max_length=128)
    keys: list[str]
    notes: list[str]


class MergePolicy(AuthResponse):
    guest_to_user_merge: Literal["user_confirmation_required"]
    auto_merge: bool
    reason: str = Field(min_length=1)


class GuestSessionResponse(AuthResponse):
    auth_state: Literal["guest"]
    guest: GuestIdentity
    subject: AuthSubject
    session_binding: SessionBinding
    guest_credential: str = Field(min_length=1, max_length=8192)
    rate_limit: RateLimitPolicy
    merge_policy: MergePolicy
    limitations: list[str]
    persistence: dict[str, Any]


class AuthenticatedSessionResponse(AuthResponse):
    contract_version: str = Field(min_length=1, max_length=64)
    auth_state: Literal["authenticated"]
    provider: Literal["google"]
    access_token: str = Field(min_length=1, max_length=8192)
    token_type: Literal["Bearer"]
    expires_in: int = Field(ge=1)
    issued_at: datetime
    expires_at: datetime
    user: AuthUser
    guest: GuestIdentity | None
    subject: AuthSubject
    auth_session: AuthSession
    session_binding: SessionBinding
    rate_limit: RateLimitPolicy
    merge_policy: MergePolicy
    limitations: list[str]
    persistence: dict[str, Any]


class GoogleAuthorizationCodeResponse(AuthenticatedSessionResponse):
    contract_version: Literal["google_auth_code.v1"]
    auth_mode: Literal["authorization_code"]
    google: dict[str, Any]


class AuthTokenRefreshResponse(AuthenticatedSessionResponse):
    contract_version: Literal["auth_token_refresh.v1"]


class AuthClientAction(AuthResponse):
    clear_access_token: bool
    clear_google_profile: bool
    next_auth_state: Literal["anonymous", "guest"]


class AuthLogoutResponse(AuthResponse):
    contract_version: Literal["auth_logout.v1"]
    auth_state: Literal["anonymous"]
    provider: Literal["google"]
    revoked_at: datetime
    user: AuthUser
    guest: GuestIdentity | None
    subject: AuthSubject
    auth_session: AuthSession
    session_binding: SessionBinding
    client_action: AuthClientAction
    limitations: list[str]
    persistence: dict[str, Any]


class AuthSubjectResponse(AuthResponse):
    auth_state: Literal["anonymous", "guest", "authenticated"]
    user: AuthUser | None
    guest: GuestIdentity | None
    subject: AuthSubject
    auth_session: AuthSession | None = None
    session_binding: SessionBinding | None = None
    rate_limit: RateLimitPolicy
    merge_policy: MergePolicy
    limitations: list[str]
    persistence: dict[str, Any]


class ResumeManifestResponse(AuthResponse):
    contract_version: Literal["resume_manifest.v1"]
    has_resume: bool
    session: dict[str, Any] | None
    conversation_messages: list[dict[str, Any]]
    pending_questions: list[dict[str, str]]
    facts: dict[str, Any]
    fine_notice_intake: dict[str, Any] | None
    attachments: list[dict[str, Any]]
    latest_analysis: dict[str, Any] | None
    reports: list[dict[str, Any]]


class AuthErrorDetail(AuthResponse):
    contract_version: Literal["auth_error.v1"]
    type: Literal["auth"]
    code: Literal[
        "auth_required",
        "token_invalid",
        "token_expired",
        "forbidden",
        "provider_unavailable",
    ]
    message: str
    status: Literal[401, 403, 503]
    missing_fields: list[str]
    retryable: bool
    required_action: str
    auth: dict[str, str]


class AuthErrorResponse(AuthResponse):
    error: AuthErrorDetail


class RateLimitErrorDetail(AuthResponse):
    contract_version: Literal["rate_limit.v1"]
    type: Literal["rate_limit"]
    code: Literal["rate_limit_exceeded"]
    status: Literal[429]
    message: str
    required_action: str
    usage: dict[str, Any]


class RateLimitErrorResponse(AuthResponse):
    error: RateLimitErrorDetail
