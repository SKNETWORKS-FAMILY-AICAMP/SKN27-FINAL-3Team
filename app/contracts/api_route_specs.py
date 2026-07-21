"""Shadow API route registry for executable contract drift checks.

The registry describes existing Django behavior. It does not generate or
replace ``urlpatterns`` while the contract is in ``shadow`` status.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from app.contracts.auth_session import (
    AuthErrorResponse,
    AuthLogoutRequest,
    AuthLogoutResponse,
    AuthSubjectResponse,
    AuthTokenRefreshRequest,
    AuthTokenRefreshResponse,
    GoogleAuthorizationCodeRequest,
    GoogleAuthorizationCodeResponse,
    GuestSessionRequest,
    GuestSessionResponse,
    RateLimitErrorResponse,
)
from app.contracts.analysis_job import (
    AnalysisJobAcceptedResponse,
    AnalysisJobDetailResponse,
    AnalysisJobErrorResponse,
    AnalysisJobListResponse,
    AnalysisJobRequest,
    AnalysisResultResponse,
)
from app.contracts.consultation_case import (
    CaseApiErrorCode,
    CaseApiErrorResponse,
    ConfirmCaseFactsRequest,
    ConfirmCaseFactsResponse,
    ConsultationCaseListResponse,
    ConsultationCaseWorkspaceResponse,
    CreateConsultationCaseRequest,
    CreateConsultationCaseResponse,
    StartCaseAnalysisRequest,
    StartCaseAnalysisResponse,
)
from app.contracts.chat_session import (
    ChatApiErrorResponse,
    ChatMessageRequest,
    ChatMessageResponse,
    ChatSaveStateRequest,
    ChatSaveStateResponse,
    ChatSessionCreateRequest,
    ChatSessionCreateResponse,
)
from app.contracts.file_attachment import (
    FileAttachmentDetailResponse,
    FileAttachmentListResponse,
    FileAttachmentNotFoundErrorResponse,
    FileAttachmentResponse,
    FileGuestSessionErrorResponse,
    FileObjectAccessErrorResponse,
    FileRateLimitErrorResponse,
    FileUploadRequest,
    FileUploadStorageErrorResponse,
    FileUploadTooLargeErrorResponse,
    FileUploadValidationErrorResponse,
)
from app.contracts.mypage import MyPageSummaryResponse
from app.contracts.history import HistoryApiErrorResponse, HistoryListResponse
from app.contracts.report import (
    ConfirmReportDocumentRequest,
    ConfirmReportDocumentResponse,
    ReportApiErrorResponse,
    ReportDetailResponse,
    ReportListResponse,
)


HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
ContractStatus = Literal["shadow", "generated"]
RequestMediaType = Literal["application/json", "multipart/form-data"]
SecurityRequirement = dict[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class PathParameterSpec:
    name: str
    description: str
    min_length: int = 1
    max_length: int = 64

    def __post_init__(self) -> None:
        if not self.name or self.min_length < 1 or self.max_length < self.min_length:
            raise ValueError("invalid path parameter contract")


@dataclass(frozen=True, slots=True)
class RouteErrorSpec:
    status: int
    codes: tuple[str, ...]
    response_model: type[BaseModel]


@dataclass(frozen=True, slots=True)
class ResponseContentSpec:
    """One explicit success response body representation."""

    media_type: str
    response_model: type[BaseModel] | None = None
    schema: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.media_type.strip():
            raise ValueError("response media type is required")
        if (self.response_model is None) == (self.schema is None):
            raise ValueError("response content requires exactly one model or schema")


@dataclass(frozen=True, slots=True)
class ResponseHeaderSpec:
    """One declared public header on a successful response."""

    name: str
    description: str
    schema: dict[str, Any]
    required: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.schema:
            raise ValueError("response header name and schema are required")


@dataclass(frozen=True, slots=True)
class RouteSpec:
    operation_id: str
    method: HttpMethod
    path: str
    route_name: str
    view_name: str
    request_model: type[BaseModel] | None
    response_model: type[BaseModel] | None
    success_status: int
    errors: tuple[RouteErrorSpec, ...]
    auth_required: bool
    contract_status: ContractStatus
    tags: tuple[str, ...]
    summary: str
    path_parameters: tuple[PathParameterSpec, ...] = ()
    request_parameters: tuple["RequestParameterSpec", ...] = ()
    request_body_required: bool = True
    request_media_types: tuple[RequestMediaType, ...] = ("application/json",)
    auth_optional: bool = False
    success_statuses: tuple[int, ...] = ()
    success_content: tuple[ResponseContentSpec, ...] = ()
    success_headers: tuple[ResponseHeaderSpec, ...] = ()
    security_requirements: tuple[SecurityRequirement, ...] = ()

    def __post_init__(self) -> None:
        placeholders = tuple(re.findall(r"\{([^{}]+)\}", self.path))
        parameters = tuple(parameter.name for parameter in self.path_parameters)
        if placeholders != parameters:
            raise ValueError(
                f"path parameter drift for {self.method} {self.path}: "
                f"placeholders={placeholders!r}, specs={parameters!r}"
            )
        if self.auth_required and self.auth_optional:
            raise ValueError("a route cannot require and optionally accept Bearer auth")
        if self.security_requirements and (self.auth_required or self.auth_optional):
            raise ValueError("explicit security cannot combine with legacy auth flags")
        if any(not requirement for requirement in self.security_requirements):
            raise ValueError("explicit security requirements cannot be anonymous")
        if self.response_model is None and not self.success_content:
            raise ValueError("route requires a JSON response model or explicit success content")
        if self.response_model is not None and self.success_content:
            raise ValueError("route cannot combine a response model with explicit success content")
        if len({content.media_type for content in self.success_content}) != len(
            self.success_content
        ):
            raise ValueError("success response media types must be unique")
        if len({header.name.lower() for header in self.success_headers}) != len(
            self.success_headers
        ):
            raise ValueError("success response headers must be unique")
        if not self.request_media_types or len(set(self.request_media_types)) != len(
            self.request_media_types
        ):
            raise ValueError("route request media types must be non-empty and unique")
        if self.success_statuses and (
            self.success_status not in self.success_statuses
            or len(set(self.success_statuses)) != len(self.success_statuses)
        ):
            raise ValueError("success status codes must include the primary status and be unique")


@dataclass(frozen=True, slots=True)
class RequestParameterSpec:
    name: str
    location: Literal["header", "query"]
    description: str
    required: bool = False
    format: str | None = None
    allowed_values: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("request parameter name is required")


@dataclass(frozen=True, slots=True)
class DeferredRouteSpec:
    method: HttpMethod
    path: str
    route_name: str
    view_name: str
    reason: str
    contract_status: Literal["deferred"] = "deferred"


def _case_errors(
    *entries: tuple[int, tuple[CaseApiErrorCode, ...]],
) -> tuple[RouteErrorSpec, ...]:
    return tuple(
        RouteErrorSpec(
            status=status,
            codes=codes,
            response_model=CaseApiErrorResponse,
        )
        for status, codes in entries
    )


def _auth_errors(
    *entries: tuple[int, tuple[str, ...]],
    response_model: type[BaseModel] = AuthErrorResponse,
) -> tuple[RouteErrorSpec, ...]:
    return tuple(
        RouteErrorSpec(status=status, codes=codes, response_model=response_model)
        for status, codes in entries
    )


def _file_errors(
    *entries: tuple[int, tuple[str, ...], type[BaseModel]],
) -> tuple[RouteErrorSpec, ...]:
    return tuple(
        RouteErrorSpec(status=status, codes=codes, response_model=response_model)
        for status, codes, response_model in entries
    )


def _analysis_job_errors(
    *entries: tuple[int, tuple[str, ...]],
) -> tuple[RouteErrorSpec, ...]:
    return tuple(
        RouteErrorSpec(
            status=status,
            codes=codes,
            response_model=AnalysisJobErrorResponse,
        )
        for status, codes in entries
    )


def _report_errors(
    *entries: tuple[int, tuple[str, ...]],
) -> tuple[RouteErrorSpec, ...]:
    return tuple(
        RouteErrorSpec(
            status=status,
            codes=codes,
            response_model=ReportApiErrorResponse,
        )
        for status, codes in entries
    )


CASE_ID_PATH_PARAMETER = PathParameterSpec(
    name="case_id",
    description="Canonical consultation Case identifier",
    max_length=64,
)


CASE_API_ROUTE_SPECS: tuple[RouteSpec, ...] = (
    RouteSpec(
        operation_id="listConsultationCases",
        method="GET",
        path="/api/cases/",
        route_name="canonical-consultation-cases",
        view_name="consultation_cases",
        request_model=None,
        response_model=ConsultationCaseListResponse,
        success_status=200,
        errors=_case_errors((403, ("login_required",))),
        auth_required=True,
        contract_status="shadow",
        tags=("Cases",),
        summary="List consultation cases owned by the authenticated user",
    ),
    RouteSpec(
        operation_id="createConsultationCase",
        method="POST",
        path="/api/cases/",
        route_name="canonical-consultation-cases",
        view_name="consultation_cases",
        request_model=CreateConsultationCaseRequest,
        response_model=CreateConsultationCaseResponse,
        success_status=201,
        errors=_case_errors(
            (403, ("login_required", "case_owner_mismatch")),
            (404, ("case_not_found",)),
            (409, ("case_conflict",)),
            (422, ("validation_error",)),
        ),
        auth_required=True,
        contract_status="shadow",
        tags=("Cases",),
        summary="Promote an authenticated consultation session to a Case",
    ),
    RouteSpec(
        operation_id="getConsultationCaseWorkspace",
        method="GET",
        path="/api/cases/{case_id}/workspace/",
        route_name="canonical-consultation-case-workspace",
        view_name="consultation_case_workspace",
        request_model=None,
        response_model=ConsultationCaseWorkspaceResponse,
        success_status=200,
        errors=_case_errors(
            (403, ("login_required", "object_access_denied")),
            (404, ("case_not_found",)),
        ),
        auth_required=True,
        contract_status="shadow",
        tags=("Cases",),
        summary="Read the authenticated owner's Case workspace",
        path_parameters=(CASE_ID_PATH_PARAMETER,),
    ),
    RouteSpec(
        operation_id="confirmConsultationCaseFacts",
        method="POST",
        path="/api/cases/{case_id}/facts/confirm/",
        route_name="canonical-consultation-case-fact-confirmation",
        view_name="consultation_case_fact_confirmation",
        request_model=ConfirmCaseFactsRequest,
        response_model=ConfirmCaseFactsResponse,
        success_status=201,
        errors=_case_errors(
            (
                403,
                (
                    "login_required",
                    "object_access_denied",
                    "case_owner_mismatch",
                ),
            ),
            (404, ("case_not_found",)),
            (409, ("case_conflict",)),
            (422, ("validation_error",)),
        ),
        auth_required=True,
        contract_status="shadow",
        tags=("Cases",),
        summary="Create an immutable confirmed-facts version for a Case",
        path_parameters=(CASE_ID_PATH_PARAMETER,),
    ),
    RouteSpec(
        operation_id="startConsultationCaseAnalysis",
        method="POST",
        path="/api/cases/{case_id}/analysis/jobs/",
        route_name="canonical-consultation-case-analysis-jobs",
        view_name="consultation_case_analysis_jobs",
        request_model=StartCaseAnalysisRequest,
        response_model=StartCaseAnalysisResponse,
        success_status=202,
        errors=_case_errors(
            (
                403,
                (
                    "login_required",
                    "object_access_denied",
                    "case_owner_mismatch",
                ),
            ),
            (404, ("case_not_found",)),
            (
                409,
                (
                    "case_conflict",
                    "confirmed_facts_required",
                    "fact_readiness_not_met",
                ),
            ),
            (422, ("validation_error",)),
        ),
        auth_required=True,
        contract_status="shadow",
        tags=("Cases",),
        summary="Queue analysis from an authenticated owner's confirmed facts",
        path_parameters=(CASE_ID_PATH_PARAMETER,),
    ),
)


GOOGLE_CODE_PARAMETERS: tuple[RequestParameterSpec, ...] = (
    RequestParameterSpec(
        name="Origin",
        location="header",
        description="Exact frontend origin configured for Google code exchange.",
        required=True,
        format="uri",
    ),
    RequestParameterSpec(
        name="X-Requested-With",
        location="header",
        description="Browser request marker required before Google provider exchange.",
        required=True,
        allowed_values=("XmlHttpRequest",),
    ),
)


GUEST_ID_HEADER_PARAMETER = RequestParameterSpec(
    name="X-Guest-Id",
    location="header",
    description="Optional guest identifier. It is not valid identity proof without X-Guest-Credential.",
)


GUEST_CREDENTIAL_HEADER_PARAMETER = RequestParameterSpec(
    name="X-Guest-Credential",
    location="header",
    description="Signed guest credential required to prove a supplied guest identity.",
)


GUEST_FILE_REQUEST_PARAMETERS: tuple[RequestParameterSpec, ...] = (
    GUEST_CREDENTIAL_HEADER_PARAMETER,
    GUEST_ID_HEADER_PARAMETER,
)


CHAT_SESSION_REQUEST_PARAMETERS: tuple[RequestParameterSpec, ...] = (
    GUEST_CREDENTIAL_HEADER_PARAMETER,
    GUEST_ID_HEADER_PARAMETER,
)


MYPAGE_SUMMARY_REQUEST_PARAMETERS: tuple[RequestParameterSpec, ...] = (
    RequestParameterSpec(
        name="session_id",
        location="query",
        description="Optional chat session identifier used to scope the summary and session cache.",
    ),
    RequestParameterSpec(
        name="owner_id",
        location="query",
        description="Optional owner identifier. When supplied, it takes precedence over user_id.",
    ),
    RequestParameterSpec(
        name="user_id",
        location="query",
        description="Legacy owner alias used only when owner_id is absent.",
    ),
    RequestParameterSpec(
        name="limit",
        location="query",
        description="Optional positive integer with a default of 10; invalid values fall back to that default.",
    ),
)


HISTORY_API_REQUEST_PARAMETERS: tuple[RequestParameterSpec, ...] = (
    GUEST_CREDENTIAL_HEADER_PARAMETER,
    GUEST_ID_HEADER_PARAMETER,
    RequestParameterSpec(
        name="session_id",
        location="query",
        description="Optional chat session identifier; the server verifies session ownership.",
    ),
    RequestParameterSpec(
        name="user_id",
        location="query",
        description="Optional user identifier; the server verifies owner access.",
    ),
    RequestParameterSpec(
        name="guest_id",
        location="query",
        description="Optional guest identifier; the server verifies guest access.",
    ),
    RequestParameterSpec(
        name="job_id",
        location="query",
        description="Optional analysis job identifier; the server verifies its session owner.",
    ),
    RequestParameterSpec(
        name="event_type",
        location="query",
        description="Optional history event type filter.",
    ),
    RequestParameterSpec(
        name="limit",
        location="query",
        description="Optional positive integer; invalid or non-positive values fall back and the default is 100.",
    ),
)


def _chat_errors(*entries: tuple[int, tuple[str, ...]]) -> tuple[RouteErrorSpec, ...]:
    return tuple(
        RouteErrorSpec(
            status=status,
            codes=codes,
            response_model=ChatApiErrorResponse,
        )
        for status, codes in entries
    )


FILE_LIST_REQUEST_PARAMETERS: tuple[RequestParameterSpec, ...] = (
    *GUEST_FILE_REQUEST_PARAMETERS,
    RequestParameterSpec(
        name="session_id",
        location="query",
        description="Optional chat session identifier used to scope file listing.",
    ),
)


ATTACHMENT_ID_PATH_PARAMETER = PathParameterSpec(
    name="attachment_id",
    description="Canonical uploaded-file identifier",
    max_length=128,
)


ANALYSIS_JOB_ID_PATH_PARAMETER = PathParameterSpec(
    name="job_id",
    description="Canonical asynchronous analysis job identifier",
    max_length=128,
)


ANALYSIS_JOB_REQUEST_PARAMETERS: tuple[RequestParameterSpec, ...] = (
    GUEST_CREDENTIAL_HEADER_PARAMETER,
    GUEST_ID_HEADER_PARAMETER,
)


ANALYSIS_JOB_LIST_REQUEST_PARAMETERS: tuple[RequestParameterSpec, ...] = (
    *ANALYSIS_JOB_REQUEST_PARAMETERS,
    RequestParameterSpec(
        name="session_id",
        location="query",
        description="Optional chat session identifier used to scope analysis job listing.",
    ),
)


AUTH_SESSION_API_ROUTE_SPECS: tuple[RouteSpec, ...] = (
    RouteSpec(
        operation_id="createGuestSession",
        method="POST",
        path="/api/auth/guest-session/",
        route_name="auth-guest-session",
        view_name="guest_session",
        request_model=GuestSessionRequest,
        response_model=GuestSessionResponse,
        success_status=200,
        errors=(),
        auth_required=False,
        contract_status="shadow",
        tags=("Auth",),
        summary="Issue or refresh a guest identity",
        request_parameters=(GUEST_CREDENTIAL_HEADER_PARAMETER,),
        request_body_required=False,
    ),
    RouteSpec(
        operation_id="exchangeGoogleAuthorizationCode",
        method="POST",
        path="/api/auth/google/code/",
        route_name="auth-google-code",
        view_name="auth_google_code",
        request_model=GoogleAuthorizationCodeRequest,
        response_model=GoogleAuthorizationCodeResponse,
        success_status=200,
        errors=(
            *_auth_errors(
                (401, ("token_invalid",)),
                (403, ("forbidden",)),
                (503, ("provider_unavailable",)),
            ),
            *_auth_errors(
                (429, ("rate_limit_exceeded",)),
                response_model=RateLimitErrorResponse,
            ),
        ),
        auth_required=False,
        contract_status="shadow",
        tags=("Auth",),
        summary="Exchange a one-time Google authorization code for an app Bearer token",
        request_parameters=(*GOOGLE_CODE_PARAMETERS, GUEST_CREDENTIAL_HEADER_PARAMETER),
    ),
    RouteSpec(
        operation_id="refreshAuthToken",
        method="POST",
        path="/api/auth/refresh/",
        route_name="auth-refresh",
        view_name="auth_refresh",
        request_model=AuthTokenRefreshRequest,
        response_model=AuthTokenRefreshResponse,
        success_status=200,
        errors=_auth_errors(
            (401, ("auth_required", "token_invalid", "token_expired")),
        ),
        auth_required=False,
        auth_optional=True,
        contract_status="shadow",
        tags=("Auth",),
        summary="Rotate a valid app Bearer token",
        request_body_required=False,
    ),
    RouteSpec(
        operation_id="logoutAuthSession",
        method="POST",
        path="/api/auth/logout/",
        route_name="auth-logout",
        view_name="auth_logout",
        request_model=AuthLogoutRequest,
        response_model=AuthLogoutResponse,
        success_status=200,
        errors=_auth_errors(
            (401, ("auth_required", "token_invalid", "token_expired")),
        ),
        auth_required=False,
        auth_optional=True,
        contract_status="shadow",
        tags=("Auth",),
        summary="Revoke the current auth session and clear client auth state",
        request_body_required=False,
    ),
    RouteSpec(
        operation_id="getCurrentAuthSubject",
        method="GET",
        path="/api/auth/me/",
        route_name="auth-me",
        view_name="auth_me",
        request_model=None,
        response_model=AuthSubjectResponse,
        success_status=200,
        errors=_auth_errors((401, ("token_invalid", "token_expired"))),
        auth_required=False,
        auth_optional=True,
        contract_status="shadow",
        tags=("Auth",),
        summary="Inspect current anonymous, guest, or authenticated subject",
        request_parameters=(
            GUEST_CREDENTIAL_HEADER_PARAMETER,
            RequestParameterSpec(
                name="X-Guest-Id",
                location="header",
                description="Optional guest identifier. It is not valid identity proof without X-Guest-Credential.",
            ),
            RequestParameterSpec(
                name="guest_id",
                location="query",
                description="Optional query fallback for the guest identity.",
            ),
            RequestParameterSpec(
                name="session_id",
                location="query",
                description="Optional chat session binding identifier.",
            ),
        ),
    ),
)


CHAT_SESSION_API_ROUTE_SPECS: tuple[RouteSpec, ...] = (
    RouteSpec(
        operation_id="issueChatSessionDraft",
        method="POST",
        path="/api/chat/sessions/",
        route_name="canonical-create-chat-session",
        view_name="create_chat_session",
        request_model=ChatSessionCreateRequest,
        response_model=ChatSessionCreateResponse,
        success_status=200,
        errors=_chat_errors(
            (401, ("auth_required", "token_invalid", "token_expired", "guest_session_invalid")),
        ),
        auth_required=False,
        auth_optional=True,
        contract_status="shadow",
        tags=("Chat",),
        summary="Issue a draft chat session identifier; persistence occurs during message or save-state processing",
        request_parameters=CHAT_SESSION_REQUEST_PARAMETERS,
        request_body_required=False,
    ),
    RouteSpec(
        operation_id="submitChatMessage",
        method="POST",
        path="/api/chat/messages/",
        route_name="canonical-submit-chat-message",
        view_name="submit_chat_message",
        request_model=ChatMessageRequest,
        response_model=ChatMessageResponse,
        success_status=200,
        success_statuses=(200, 202, 503),
        errors=_chat_errors(
            (400, ("chat_input_rejected",)),
            (401, ("auth_required", "token_invalid", "token_expired", "guest_session_invalid")),
            (403, ("object_access_denied",)),
            (429, ("rate_limit_exceeded",)),
        ),
        auth_required=False,
        auth_optional=True,
        contract_status="shadow",
        tags=("Chat",),
        summary="Submit a chat turn and return immediate guidance, an asynchronous Worker receipt, or supervisor-unavailable state",
        request_parameters=CHAT_SESSION_REQUEST_PARAMETERS,
    ),
    RouteSpec(
        operation_id="updateChatSaveState",
        method="POST",
        path="/api/chat/save-state/",
        route_name="canonical-chat-save-state",
        view_name="update_chat_save_state",
        request_model=ChatSaveStateRequest,
        response_model=ChatSaveStateResponse,
        success_status=200,
        errors=_chat_errors(
            (401, ("auth_required", "token_invalid", "token_expired", "guest_session_invalid")),
            (403, ("login_required", "object_access_denied")),
        ),
        auth_required=False,
        auth_optional=True,
        contract_status="shadow",
        tags=("Chat",),
        summary="Update a conversation save preference; an unknown session returns 200 with skipped state",
        request_parameters=CHAT_SESSION_REQUEST_PARAMETERS,
    ),
)


MYPAGE_API_ROUTE_SPECS: tuple[RouteSpec, ...] = (
    RouteSpec(
        operation_id="getMyPageSummary",
        method="GET",
        path="/api/mypage/summary/",
        route_name="canonical-mypage-summary",
        view_name="mypage_summary",
        request_model=None,
        response_model=MyPageSummaryResponse,
        success_status=200,
        errors=_auth_errors(
            (401, ("auth_required", "token_invalid", "token_expired")),
            (403, ("object_access_denied",)),
        ),
        auth_required=True,
        contract_status="shadow",
        tags=("MyPage",),
        summary="Read the authenticated user's summary after owner or session authorization",
        request_parameters=MYPAGE_SUMMARY_REQUEST_PARAMETERS,
    ),
)


HISTORY_API_ROUTE_SPECS: tuple[RouteSpec, ...] = (
    RouteSpec(
        operation_id="listHistoryEvents",
        method="GET",
        path="/api/history/",
        route_name="canonical-history-events",
        view_name="history_events",
        request_model=None,
        response_model=HistoryListResponse,
        success_status=200,
        errors=(
            RouteErrorSpec(
                status=401,
                codes=("auth_required", "token_invalid", "token_expired"),
                response_model=HistoryApiErrorResponse,
            ),
            RouteErrorSpec(
                status=403,
                codes=("object_access_denied",),
                response_model=HistoryApiErrorResponse,
            ),
        ),
        auth_required=False,
        contract_status="shadow",
        tags=("History",),
        summary="List the current subject's standard-light history events with owner-scoped filters",
        request_parameters=HISTORY_API_REQUEST_PARAMETERS,
        security_requirements=(
            {"bearerAuth": ()},
            {"guestCredentialAuth": ()},
        ),
    ),
)


FILE_API_ROUTE_SPECS: tuple[RouteSpec, ...] = (
    RouteSpec(
        operation_id="listFileAttachments",
        method="GET",
        path="/api/files/",
        route_name="canonical-files",
        view_name="attachments",
        request_model=None,
        response_model=FileAttachmentListResponse,
        success_status=200,
        errors=_file_errors(
            (401, ("guest_session_invalid",), FileGuestSessionErrorResponse),
            (403, ("object_access_denied",), FileObjectAccessErrorResponse),
        ),
        auth_required=False,
        auth_optional=True,
        contract_status="shadow",
        tags=("Files",),
        summary="List canonical file attachments visible to the current subject",
        request_parameters=FILE_LIST_REQUEST_PARAMETERS,
    ),
    RouteSpec(
        operation_id="uploadFileAttachment",
        method="POST",
        path="/api/files/",
        route_name="canonical-files",
        view_name="attachments",
        request_model=FileUploadRequest,
        response_model=FileAttachmentResponse,
        success_status=200,
        errors=_file_errors(
            (400, ("session_id_required",), FileUploadValidationErrorResponse),
            (401, ("guest_session_invalid",), FileGuestSessionErrorResponse),
            (403, ("object_access_denied",), FileObjectAccessErrorResponse),
            (413, ("file_too_large",), FileUploadTooLargeErrorResponse),
            (429, ("rate_limit_exceeded",), FileRateLimitErrorResponse),
            (503, ("upload_storage_unavailable",), FileUploadStorageErrorResponse),
        ),
        auth_required=False,
        auth_optional=True,
        contract_status="shadow",
        tags=("Files",),
        summary="Upload or register a file attachment through the quarantine boundary",
        request_parameters=GUEST_FILE_REQUEST_PARAMETERS,
        request_media_types=("application/json", "multipart/form-data"),
    ),
    RouteSpec(
        operation_id="getFileAttachment",
        method="GET",
        path="/api/files/{attachment_id}/",
        route_name="canonical-file-detail",
        view_name="attachment_detail",
        request_model=None,
        response_model=FileAttachmentDetailResponse,
        success_status=200,
        errors=_file_errors(
            (401, ("guest_session_invalid",), FileGuestSessionErrorResponse),
            (403, ("object_access_denied",), FileObjectAccessErrorResponse),
            (404, ("attachment_not_found",), FileAttachmentNotFoundErrorResponse),
        ),
        auth_required=False,
        auth_optional=True,
        contract_status="shadow",
        tags=("Files",),
        summary="Read one canonical file attachment after owner authorization",
        path_parameters=(ATTACHMENT_ID_PATH_PARAMETER,),
        request_parameters=FILE_LIST_REQUEST_PARAMETERS,
    ),
)


ANALYSIS_JOB_API_ROUTE_SPECS: tuple[RouteSpec, ...] = (
    RouteSpec(
        operation_id="listAnalysisJobs",
        method="GET",
        path="/api/analysis/jobs/",
        route_name="canonical-analysis-jobs",
        view_name="analysis_jobs",
        request_model=None,
        response_model=AnalysisJobListResponse,
        success_status=200,
        errors=_analysis_job_errors(
            (403, ("object_access_denied",)),
        ),
        auth_required=False,
        auth_optional=True,
        contract_status="shadow",
        tags=("Analysis",),
        summary="List analysis jobs visible to the current subject",
        request_parameters=ANALYSIS_JOB_LIST_REQUEST_PARAMETERS,
    ),
    RouteSpec(
        operation_id="queueAnalysisJob",
        method="POST",
        path="/api/analysis/jobs/",
        route_name="canonical-analysis-jobs",
        view_name="analysis_jobs",
        request_model=AnalysisJobRequest,
        response_model=AnalysisJobAcceptedResponse,
        success_status=202,
        errors=_analysis_job_errors(
            (400, ("analysis_job_session_required", "chat_input_rejected")),
            (403, ("object_access_denied",)),
            (
                409,
                (
                    "analysis_plan_not_executable",
                    "attachment_scan_blocked",
                    "analysis_job_id_conflict",
                    "analysis_job_reservation_pending",
                ),
            ),
            (429, ("rate_limit_exceeded",)),
            (503, ("analysis_job_unavailable",)),
        ),
        auth_required=False,
        auth_optional=True,
        contract_status="shadow",
        tags=("Analysis",),
        summary="Queue an owner-scoped Supervisor analysis plan for asynchronous execution",
        request_parameters=ANALYSIS_JOB_REQUEST_PARAMETERS,
        request_body_required=False,
    ),
    RouteSpec(
        operation_id="getAnalysisJob",
        method="GET",
        path="/api/analysis/jobs/{job_id}/",
        route_name="canonical-analysis-job-detail",
        view_name="analysis_job_detail",
        request_model=None,
        response_model=AnalysisJobDetailResponse,
        success_status=200,
        errors=_analysis_job_errors(
            (401, ("guest_session_invalid",)),
            (403, ("object_access_denied",)),
            (404, ("analysis_job_not_found",)),
        ),
        auth_required=False,
        auth_optional=True,
        contract_status="shadow",
        tags=("Analysis",),
        summary="Read one asynchronous analysis job after owner authorization",
        path_parameters=(ANALYSIS_JOB_ID_PATH_PARAMETER,),
        request_parameters=ANALYSIS_JOB_REQUEST_PARAMETERS,
    ),
    RouteSpec(
        operation_id="getAnalysisResult",
        method="GET",
        path="/api/analysis/results/{job_id}/",
        route_name="canonical-analysis-result",
        view_name="analysis_result",
        request_model=None,
        response_model=AnalysisResultResponse,
        success_status=200,
        success_statuses=(200, 202),
        errors=_analysis_job_errors(
            (401, ("guest_session_invalid",)),
            (403, ("object_access_denied",)),
            (404, ("analysis_result_not_found",)),
        ),
        auth_required=False,
        auth_optional=True,
        contract_status="shadow",
        tags=("Analysis",),
        summary="Read a completed result or pending state for an authorized analysis job",
        path_parameters=(ANALYSIS_JOB_ID_PATH_PARAMETER,),
        request_parameters=ANALYSIS_JOB_REQUEST_PARAMETERS,
    ),
)


REPORT_ID_PATH_PARAMETER = PathParameterSpec(
    name="report_id",
    description="Canonical report identifier",
    max_length=64,
)

REPORT_GUEST_ID_HEADER_PARAMETER = RequestParameterSpec(
    name="X-Guest-Id",
    location="header",
    description=(
        "Optional guest identifier. It is not identity proof without "
        "X-Guest-Credential and does not authorize report reads."
    ),
)


REPORT_LIST_REQUEST_PARAMETERS: tuple[RequestParameterSpec, ...] = (
    GUEST_CREDENTIAL_HEADER_PARAMETER,
    REPORT_GUEST_ID_HEADER_PARAMETER,
    RequestParameterSpec(
        name="session_id",
        location="query",
        description="Optional chat session identifier used to filter the report collection.",
    ),
)


REPORT_DETAIL_REQUEST_PARAMETERS: tuple[RequestParameterSpec, ...] = (
    GUEST_CREDENTIAL_HEADER_PARAMETER,
    REPORT_GUEST_ID_HEADER_PARAMETER,
    RequestParameterSpec(
        name="session_id",
        location="query",
        description="Optional chat session context associated with this report read.",
    ),
)

REPORT_DOWNLOAD_REQUEST_PARAMETERS: tuple[RequestParameterSpec, ...] = (
    *REPORT_DETAIL_REQUEST_PARAMETERS,
    RequestParameterSpec(
        name="document_type",
        location="query",
        description="Official document type. Only the objection-form DOCX is downloadable.",
    ),
)

REPORT_DOCUMENT_SUCCESS_HEADERS: tuple[ResponseHeaderSpec, ...] = (
    ResponseHeaderSpec(
        name="Content-Disposition",
        description="Attachment filename for the rendered report document.",
        schema={"type": "string"},
        required=True,
    ),
    ResponseHeaderSpec(
        name="X-API-Surface",
        description="Public API surface label for the rendered report.",
        schema={"type": "string"},
        required=True,
    ),
    ResponseHeaderSpec(
        name="X-Execution-Mode",
        description="Public execution mode label for the rendered report.",
        schema={"type": "string"},
        required=True,
    ),
    ResponseHeaderSpec(
        name="X-Report-Document-Type",
        description="Normalized document type rendered into the DOCX.",
        schema={"type": "string"},
        required=True,
    ),
)

REPORT_API_ROUTE_SPECS: tuple[RouteSpec, ...] = (
    RouteSpec(
        operation_id="listReports",
        method="GET",
        path="/api/reports/",
        route_name="canonical-report-action",
        view_name="report_action",
        request_model=None,
        response_model=ReportListResponse,
        success_status=200,
        errors=_report_errors(
            (
                401,
                (
                    "auth_required",
                    "token_invalid",
                    "token_expired",
                    "guest_session_invalid",
                ),
            ),
            (403, ("login_required",)),
        ),
        auth_required=True,
        contract_status="shadow",
        tags=("Reports",),
        summary="List reports owned by the authenticated user",
        request_parameters=REPORT_LIST_REQUEST_PARAMETERS,
    ),
    RouteSpec(
        operation_id="getReportDetail",
        method="GET",
        path="/api/reports/{report_id}/",
        route_name="canonical-report-detail",
        view_name="report_detail",
        request_model=None,
        response_model=ReportDetailResponse,
        success_status=200,
        errors=_report_errors(
            (
                401,
                (
                    "auth_required",
                    "token_invalid",
                    "token_expired",
                    "guest_session_invalid",
                ),
            ),
            (403, ("login_required", "object_access_denied")),
            (404, ("report_not_found",)),
        ),
        auth_required=True,
        contract_status="shadow",
        tags=("Reports",),
        summary="Read one report owned by the authenticated user",
        path_parameters=(REPORT_ID_PATH_PARAMETER,),
        request_parameters=REPORT_DETAIL_REQUEST_PARAMETERS,
    ),
    RouteSpec(
        operation_id="downloadReportDocument",
        method="GET",
        path="/api/reports/{report_id}/download/",
        route_name="canonical-download-report",
        view_name="download_report",
        request_model=None,
        response_model=None,
        success_status=200,
        errors=_report_errors(
            (
                401,
                (
                    "auth_required",
                    "token_invalid",
                    "token_expired",
                    "guest_session_invalid",
                ),
            ),
            (403, ("login_required", "object_access_denied")),
            (404, ("report_not_found",)),
            (
                409,
                (
                    "report_not_ready",
                    "document_download_not_available",
                    "document_confirmation_required",
                    "appeal_gate_blocked",
                ),
            ),
        ),
        auth_required=True,
        contract_status="shadow",
        tags=("Reports",),
        summary="Download an authorized report as a DOCX document",
        path_parameters=(REPORT_ID_PATH_PARAMETER,),
        request_parameters=REPORT_DOWNLOAD_REQUEST_PARAMETERS,
        success_content=(
            ResponseContentSpec(
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                schema={"type": "string", "format": "binary"},
            ),
        ),
        success_headers=REPORT_DOCUMENT_SUCCESS_HEADERS,
    ),
    RouteSpec(
        operation_id="confirmReportDocument",
        method="POST",
        path="/api/reports/{report_id}/document-confirmation/",
        route_name="canonical-report-document-confirmation",
        view_name="report_document_confirmation",
        request_model=ConfirmReportDocumentRequest,
        response_model=ConfirmReportDocumentResponse,
        success_status=201,
        errors=_report_errors(
            (
                401,
                (
                    "auth_required",
                    "token_invalid",
                    "token_expired",
                    "guest_session_invalid",
                ),
            ),
            (403, ("login_required", "object_access_denied")),
            (404, ("report_not_found",)),
            (409, ("appeal_gate_blocked",)),
            (422, ("validation_error",)),
        ),
        auth_required=True,
        contract_status="shadow",
        tags=("Reports",),
        summary="Record the owner's final confirmation before official DOCX download",
        path_parameters=(REPORT_ID_PATH_PARAMETER,),
        request_parameters=REPORT_DETAIL_REQUEST_PARAMETERS,
    ),
)


API_ROUTE_SPECS: tuple[RouteSpec, ...] = (
    CASE_API_ROUTE_SPECS
    + AUTH_SESSION_API_ROUTE_SPECS
    + CHAT_SESSION_API_ROUTE_SPECS
    + MYPAGE_API_ROUTE_SPECS
    + HISTORY_API_ROUTE_SPECS
    + FILE_API_ROUTE_SPECS
    + ANALYSIS_JOB_API_ROUTE_SPECS
    + REPORT_API_ROUTE_SPECS
)


DEFERRED_ROUTE_SPECS: tuple[DeferredRouteSpec, ...] = (
    DeferredRouteSpec(
        method="GET",
        path="/api/health/",
        route_name="health-check",
        view_name="health_check",
        reason="Basic health response DTO is pending.",
    ),
    DeferredRouteSpec(
        method="GET",
        path="/api/health/live/",
        route_name="health-live",
        view_name="health_live",
        reason="Liveness response DTO is pending.",
    ),
    DeferredRouteSpec(
        method="GET",
        path="/api/health/ready/",
        route_name="health-ready",
        view_name="health_ready",
        reason="Readiness success and dependency-failure DTOs are pending.",
    ),
    DeferredRouteSpec(
        method="GET",
        path="/api/capabilities/",
        route_name="capabilities",
        view_name="capabilities",
        reason="Capability DTO exists in runtime data but is not registered as a route contract.",
    ),
    DeferredRouteSpec(
        method="GET",
        path="/api/agents/nodes/",
        route_name="canonical-agent-nodes",
        view_name="agent_nodes",
        reason="Typed node DTO exists but route request/error contracts are pending.",
    ),
    DeferredRouteSpec(
        method="POST",
        path="/api/reports/",
        route_name="canonical-report-action",
        view_name="report_action",
        reason="Report generation still contains legacy runtime behavior.",
    ),
)
