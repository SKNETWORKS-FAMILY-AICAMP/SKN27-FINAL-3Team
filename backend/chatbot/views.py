"""Django views that expose the mid-demo mock chatbot service."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
from uuid import uuid4

from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from pydantic import BaseModel, ValidationError

from app.security.chat_input_privacy import ChatInputRejected, protect_chat_input_payload
from app.contracts.consultation_case import (
    ConfirmCaseFactsResponse,
    ConfirmCaseFactsRequest,
    ConsultationCaseListResponse,
    ConsultationCaseWorkspaceResponse,
    CreateConsultationCaseRequest,
    CreateConsultationCaseResponse,
    StartCaseAnalysisRequest,
    StartCaseAnalysisResponse,
)
from app.services.agent_node_service import (
    executable_analysis_plan_steps,
    execute_agent_plan,
    execute_agent_node,
    list_public_agent_nodes,
)
from app.services.analysis_job_mock_service import create_analysis_job
from app.services.analysis_job_query_service import (
    load_analysis_job_detail,
    load_analysis_result,
)
from app.services.attachment_mock_service import (
    UploadTooLargeError,
    get_attachment as get_mock_attachment,
    list_attachments as list_mock_attachments,
    register_attachment as register_mock_attachment,
)
from app.services.auth_session_service import (
    create_guest_session as _create_guest_session,
    get_current_auth_subject as _get_current_auth_subject,
)
from app.services.auth_error_contract import build_auth_error, build_www_authenticate_header
from app.services.capability_catalog import capability_catalog_payload
from app.services.chat_orchestration_service import (
    compose_agent_response,
    create_session,
    submit_message,
)
from app.services.google_auth_service import (
    create_google_code_login as _create_google_code_login,
    create_logout as _create_logout,
    create_token_refresh as _create_token_refresh,
    validate_google_code_request_boundary as _validate_google_code_request_boundary,
)
from app.services.history_event_mock_service import (
    HISTORY_EVENT_VERSION,
    actor_from_payload,
    list_history_events as list_sidecar_history_events,
    record_agent_execution_events as record_sidecar_agent_execution_events,
    record_history_event as record_sidecar_history_event,
    source_from_request,
    subject_from_payload,
)
from chatbot.api_response import (
    is_canonical_mock_request as _is_canonical_mock_request,
    json_response as _json_response,
)
from chatbot.case_repository import (
    CaseRepositoryError,
    confirm_case_facts,
    create_case,
    get_case_access_metadata,
    get_case_workspace,
    list_cases,
    start_case_analysis,
)
from chatbot.file_scan_service import apply_attachment_scan_gate
from chatbot.request_parsing import (
    first_upload_file as _first_upload_file,
    json_body as _json_body,
    request_payload as _request_payload,
)
from chatbot.runtime_health import build_runtime_health
from chatbot.repositories import (
    AuthSessionStateError,
    SessionBindingError,
    UploadStorageUnavailableError,
    UploadValidationError,
    access_subject_from_payload,
    authorize_resource_access,
    authorize_report_download_metadata,
    build_report_download_pdf_body,
    build_history_after_service_summary,
    conversation_save_state_from_payload,
    get_analysis_job_access_metadata,
    get_analysis_job_record,
    get_chat_session_access_metadata,
    get_mycase_summary,
    get_report_access_metadata,
    get_report_download_metadata,
    get_report_record_detail,
    get_uploaded_file_access_metadata,
    get_uploaded_file,
    history_operating_policy,
    list_analysis_job_records,
    list_history_event_records,
    list_report_records,
    list_uploaded_files,
    mark_conversation_save_state,
    enqueue_analysis_job_work,
    process_agent_work_items,
    persist_current_auth_subject,
    persist_auth_logout,
    persist_auth_token_refresh,
    persist_analysis_job_execution,
    persist_guest_session_identity,
    record_agent_history_event_records,
    record_history_event_record,
    record_usage_event,
    refund_usage_event,
    register_uploaded_file,
    release_analysis_job_reservation,
    renew_analysis_job_reservation,
    reserve_analysis_job_request,
)
from chatbot.models import GuestIdentity, GuestIdentityStatus
from chatbot.progress_cache import read_analysis_job_progress, read_chat_session_state


logger = logging.getLogger(__name__)


@require_http_methods(["GET", "OPTIONS"])
def health_check(_request: HttpRequest) -> JsonResponse:
    return JsonResponse({"ok": True, "service": "skn27-api"})


@require_http_methods(["GET", "OPTIONS"])
def health_live(_request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "live", "service": "skn27-api"})


@require_http_methods(["GET", "OPTIONS"])
def health_ready(_request: HttpRequest) -> JsonResponse:
    payload = build_runtime_health()
    status = 200 if payload["status"] == "ready" else 503
    return JsonResponse(payload, status=status)


@require_http_methods(["GET", "OPTIONS"])
def capabilities(_request: HttpRequest) -> JsonResponse:
    return JsonResponse(capability_catalog_payload())


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def guest_session(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    payload = _create_guest_session(body)
    payload["persistence"] = persist_guest_session_identity(payload, raw_payload=body)
    _record_history_safely(
        request,
        event_type="guest_session_created",
        status="success",
        summary="??? guest session? mock ??????.",
        actor={
            "guest_id": payload.get("guest", {}).get("guest_id"),
            "auth_state": "guest",
        },
        subject=subject_from_payload(body, session_id=payload.get("session_binding", {}).get("session_id")),
        source=_history_source(request),
        metadata={
            "ttl_seconds": payload.get("guest", {}).get("ttl_seconds"),
            "rate_limit_keys": payload.get("rate_limit", {}).get("keys", []),
            "merge_policy": payload.get("merge_policy", {}),
        },
    )
    return _json_response(request, payload)


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def auth_google_code(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    request_error = _validate_google_code_request_boundary(
        body,
        request_headers=dict(request.headers.items()),
    )
    if request_error is not None:
        status, payload = request_error
        response = _json_response(request, payload, status=status)
        if status in {401, 403} and isinstance(payload.get("error"), dict):
            response["WWW-Authenticate"] = build_www_authenticate_header(payload)
        return response
    try:
        binding_error = _google_code_session_binding_error(body)
    except DatabaseError:
        payload = build_auth_error(
            "provider_unavailable",
            reason="google_login_session_store_unavailable",
        )
        return _json_response(request, payload, status=503)
    if binding_error:
        payload = build_auth_error("forbidden", reason=binding_error)
        response = _json_response(request, payload, status=403)
        response["WWW-Authenticate"] = build_www_authenticate_header(payload)
        return response
    rate_subject = _google_oauth_rate_limit_subject(request)
    cached_block = _get_cached_google_oauth_block(rate_subject)
    if cached_block is not None:
        return _google_oauth_rate_limit_response(request, cached_block)
    try:
        usage = record_usage_event(
            rate_subject,
            scope="google_oauth_code_exchange",
            record_blocked_event=False,
        )
    except DatabaseError:
        payload = build_auth_error(
            "provider_unavailable",
            reason="google_oauth_rate_limit_store_unavailable",
        )
        return _json_response(request, payload, status=503)
    if not usage["allowed"]:
        _cache_google_oauth_block(rate_subject, usage)
        return _google_oauth_rate_limit_response(request, usage)
    status, payload = _create_google_code_login(
        body,
        request_headers=dict(request.headers.items()),
    )
    _strip_private_oauth_payload(payload)
    if status < 400:
        try:
            payload["persistence"] = persist_current_auth_subject(
                payload,
                session_id=body.get("session_id"),
            )
        except AuthSessionStateError as exc:
            status = 401
            payload = build_auth_error("token_invalid", reason=exc.reason)
        except SessionBindingError as exc:
            status = 403
            payload = build_auth_error("forbidden", reason=exc.reason)
        except DatabaseError:
            status = 503
            payload = build_auth_error(
                "provider_unavailable",
                reason="google_login_persistence_unavailable",
            )
    _record_history_safely(
        request,
        event_type="auth_google_code_completed",
        status="success" if status < 400 else "failed",
        summary="Google Authorization Code Flow boundary was processed.",
        actor=_actor_from_auth_me_payload(request, payload),
        subject=subject_from_payload({"session_id": body.get("session_id")}),
        source=_history_source(request),
        metadata={
            "http_status": status,
            "provider": payload.get("provider"),
            "auth_mode": payload.get("auth_mode"),
            "google": payload.get("google") or {},
            "error_code": (payload.get("error") or {}).get("code")
            if isinstance(payload.get("error"), dict)
            else None,
        },
    )
    response = _json_response(request, payload, status=status)
    if status in {401, 403} and isinstance(payload.get("error"), dict):
        response["WWW-Authenticate"] = build_www_authenticate_header(payload)
    return response


def _google_code_session_binding_error(body: dict) -> str:
    session_id = str(body.get("session_id") or "").strip()
    if not session_id:
        return ""
    session_access = get_chat_session_access_metadata(session_id)
    if session_access is None:
        return ""
    if str(session_access.get("owner_id") or "").strip():
        return "google_session_already_owned"

    expected_guest_id = _normalized_guest_id_for_binding(session_access.get("guest_id"))
    request_guest_id = _normalized_guest_id_for_binding(body.get("guest_id"))
    if not expected_guest_id:
        return "google_session_unbound"
    if request_guest_id != expected_guest_id:
        return "google_guest_session_mismatch"
    return ""


def _normalized_guest_id_for_binding(value: object) -> str:
    guest_id = str(value or "").strip()
    if not guest_id:
        return ""
    return guest_id if guest_id.startswith("gst_") else f"gst_{guest_id}"


def _google_oauth_rate_limit_subject(request: HttpRequest) -> dict[str, str]:
    client_ip = _google_oauth_client_ip(request)
    secret = str(settings.APP_JWT_SECRET or settings.SECRET_KEY).encode("utf-8")
    digest = hmac.new(
        secret,
        f"google_oauth_code_exchange.v1:{client_ip}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]
    return {"guest_id": f"oauth_{digest}"}


def _google_oauth_block_cache_key(subject: dict[str, str]) -> str:
    return f"google_oauth_code_exchange:block:{subject['guest_id']}"


def _get_cached_google_oauth_block(
    subject: dict[str, str],
) -> dict[str, object] | None:
    try:
        cached = cache.get(_google_oauth_block_cache_key(subject))
    except Exception as exc:  # pragma: no cover - cache backend failure boundary.
        logger.warning(
            "Google OAuth block cache read failed error_type=%s",
            exc.__class__.__name__,
        )
        return None
    return dict(cached) if isinstance(cached, dict) else None


def _cache_google_oauth_block(
    subject: dict[str, str],
    usage: dict[str, object],
) -> None:
    public_usage = {
        key: usage.get(key)
        for key in (
            "scope",
            "limit_count",
            "used_count",
            "remaining_count",
            "reset_at",
        )
        if key in usage
    }
    try:
        cache.set(
            _google_oauth_block_cache_key(subject),
            public_usage,
            timeout=300,
        )
    except Exception as exc:  # pragma: no cover - cache backend failure boundary.
        logger.warning(
            "Google OAuth block cache write failed error_type=%s",
            exc.__class__.__name__,
        )


def _google_oauth_client_ip(request: HttpRequest) -> str:
    remote_ip = _normalized_ip_address(request.META.get("REMOTE_ADDR"))
    if not remote_ip:
        return "unknown"

    trusted_networks = _google_oauth_trusted_proxy_networks()
    if not _ip_is_in_networks(remote_ip, trusted_networks):
        return remote_ip

    forwarded_values = [
        _normalized_ip_address(value)
        for value in str(request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")
        if value.strip()
    ]
    if not forwarded_values or any(not value for value in forwarded_values):
        return remote_ip

    current_ip = remote_ip
    for forwarded_ip in reversed(forwarded_values):
        if not _ip_is_in_networks(current_ip, trusted_networks):
            break
        current_ip = forwarded_ip
    return current_ip


def _google_oauth_trusted_proxy_networks() -> tuple[
    ipaddress.IPv4Network | ipaddress.IPv6Network,
    ...,
]:
    configured = settings.GOOGLE_OAUTH_TRUSTED_PROXY_CIDRS
    values = configured.split(",") if isinstance(configured, str) else configured
    networks = []
    for value in values:
        try:
            networks.append(ipaddress.ip_network(str(value).strip(), strict=False))
        except ValueError:
            continue
    return tuple(networks)


def _normalized_ip_address(value: object) -> str:
    try:
        return ipaddress.ip_address(str(value or "").strip()).compressed
    except ValueError:
        return ""


def _ip_is_in_networks(
    value: str,
    networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return any(
        address.version == network.version and address in network
        for network in networks
    )


def _google_oauth_rate_limit_response(
    request: HttpRequest,
    usage: dict[str, object],
) -> JsonResponse:
    public_usage = {
        key: usage.get(key)
        for key in (
            "scope",
            "limit_count",
            "used_count",
            "remaining_count",
            "reset_at",
        )
        if key in usage
    }
    return _json_response(
        request,
        {
            "error": {
                "contract_version": "rate_limit.v1",
                "type": "rate_limit",
                "code": "rate_limit_exceeded",
                "status": 429,
                "message": "Google 로그인 요청 한도를 초과했습니다.",
                "required_action": "wait_then_restart_google_login",
                "usage": public_usage,
            }
        },
        status=429,
    )


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def auth_refresh(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    status, payload = _create_token_refresh(
        authorization_header=request.headers.get("Authorization"),
        payload=body,
    )
    if status < 400:
        try:
            payload["persistence"] = persist_auth_token_refresh(
                payload,
                session_id=body.get("session_id"),
            )
        except AuthSessionStateError as exc:
            status = 401
            payload = build_auth_error("token_invalid", reason=exc.reason)
    _record_history_safely(
        request,
        event_type="auth_token_refreshed",
        status="success" if status < 400 else "failed",
        summary="App auth token refresh boundary was processed.",
        actor=_actor_from_auth_me_payload(request, payload),
        subject=subject_from_payload({"session_id": body.get("session_id")}),
        source=_history_source(request),
        metadata={
            "http_status": status,
            "provider": payload.get("provider"),
            "subject_type": (payload.get("subject") or {}).get("subject_type")
            if isinstance(payload.get("subject"), dict)
            else None,
            "error_code": (payload.get("error") or {}).get("code")
            if isinstance(payload.get("error"), dict)
            else None,
        },
    )
    response = _json_response(request, payload, status=status)
    if status in {401, 403} and isinstance(payload.get("error"), dict):
        response["WWW-Authenticate"] = build_www_authenticate_header(payload)
    return response


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def auth_logout(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    status, payload = _create_logout(
        authorization_header=request.headers.get("Authorization"),
        payload=body,
    )
    if status < 400:
        payload["persistence"] = persist_auth_logout(
            payload,
            session_id=body.get("session_id"),
        )
    _record_history_safely(
        request,
        event_type="auth_logout_completed",
        status="success" if status < 400 else "failed",
        summary="App auth logout boundary was processed.",
        actor=_actor_from_auth_me_payload(request, payload),
        subject=subject_from_payload({"session_id": body.get("session_id")}),
        source=_history_source(request),
        metadata={
            "http_status": status,
            "provider": payload.get("provider"),
            "subject_type": (payload.get("subject") or {}).get("subject_type")
            if isinstance(payload.get("subject"), dict)
            else None,
            "error_code": (payload.get("error") or {}).get("code")
            if isinstance(payload.get("error"), dict)
            else None,
        },
    )
    response = _json_response(request, payload, status=status)
    if status in {401, 403} and isinstance(payload.get("error"), dict):
        response["WWW-Authenticate"] = build_www_authenticate_header(payload)
    return response


@require_http_methods(["GET", "OPTIONS"])
def auth_me(request: HttpRequest) -> JsonResponse:
    status, payload = _get_current_auth_subject(
        authorization_header=request.headers.get("Authorization"),
        guest_id=request.headers.get("X-Guest-Id") or request.GET.get("guest_id"),
        session_id=request.GET.get("session_id"),
    )
    if status < 400:
        try:
            payload["persistence"] = persist_current_auth_subject(
                payload,
                session_id=request.GET.get("session_id"),
            )
        except AuthSessionStateError as exc:
            status = 401
            payload = build_auth_error("token_invalid", reason=exc.reason)
    _record_history_safely(
        request,
        event_type="auth_me_checked",
        status="success" if status < 400 else "failed",
        summary="?? ?? subject? mock ??????.",
        actor=_actor_from_auth_me_payload(request, payload),
        subject=subject_from_payload({"session_id": request.GET.get("session_id")}),
        source=_history_source(request),
        metadata={
            "http_status": status,
            "auth_state": payload.get("auth_state"),
            "subject_type": (payload.get("subject") or {}).get("subject_type"),
            "is_authenticated": (payload.get("subject") or {}).get("is_authenticated"),
            "error_code": (payload.get("error") or {}).get("code"),
        },
    )
    response = _json_response(request, payload, status=status)
    if status in {401, 403} and isinstance(payload.get("error"), dict):
        response["WWW-Authenticate"] = build_www_authenticate_header(payload)
    return response


@require_http_methods(["GET", "OPTIONS"])
def history_events(request: HttpRequest) -> JsonResponse:
    identity_payload = _request_access_payload(request, session_id=request.GET.get("session_id"))
    if _is_canonical_mock_request(request):
        access = _authorize_history_query(request, identity_payload)
        if not access["allowed"]:
            return _object_access_denied_response(request, access)

    subject = access_subject_from_payload(identity_payload)["subject"]
    filters = {
        "session_id": request.GET.get("session_id"),
        "user_id": request.GET.get("user_id"),
        "guest_id": request.GET.get("guest_id"),
        "job_id": request.GET.get("job_id"),
        "event_type": request.GET.get("event_type"),
        "limit": _positive_int(request.GET.get("limit"), default=100),
    }
    if _is_canonical_mock_request(request):
        if not any(filters.get(key) for key in ("session_id", "user_id", "guest_id", "job_id")):
            if subject.get("user_id"):
                filters["user_id"] = subject["user_id"]
            elif subject.get("guest_id"):
                filters["guest_id"] = subject["guest_id"]
        filters["subject_type"] = subject.get("subject_type")
        events = list_history_event_records(**filters)
        storage = {
            "backend": "postgresql",
            "policy": "standard_light",
            "table": "history_events",
        }
        policy = history_operating_policy(subject.get("subject_type"))
    else:
        events = list_sidecar_history_events(**filters)
        storage = {
            "backend": "mock_sidecar_json",
            "policy": "standard_light",
        }
        policy = history_operating_policy("anonymous")
    after_service_summary = build_history_after_service_summary(events)
    return _json_response(
        request,
        {
            "history_contract": HISTORY_EVENT_VERSION,
            "storage": storage,
            "history_policy": policy,
            "after_service_summary": after_service_summary,
            "count": len(events),
            "events": events,
            "limitations": [
                "?? ??, OCR ??, Agent reasoning ??? standard-light history? ?????.",
                "?? ??? DB table ??? ??? ?? ???? ?? ?????.",
            ],
        },
    )


@require_http_methods(["GET", "OPTIONS"])
def mypage_summary(request: HttpRequest) -> JsonResponse:
    identity_payload = _request_access_payload(request, session_id=request.GET.get("session_id"))
    if _is_canonical_mock_request(request):
        access = _authorize_mypage_query(request, identity_payload)
        if not access["allowed"]:
            return _object_access_denied_response(request, access)

    subject = access_subject_from_payload(identity_payload)["subject"]
    owner_id = request.GET.get("owner_id") or request.GET.get("user_id") or subject.get("user_id")
    summary = get_mycase_summary(
        session_id=request.GET.get("session_id"),
        owner_id=owner_id,
        limit=_positive_int(request.GET.get("limit"), default=10),
    )
    if _is_canonical_mock_request(request) and request.GET.get("session_id"):
        summary["session_cache"] = read_chat_session_state(request.GET["session_id"])
    return _json_response(request, summary)


@require_http_methods(["GET", "OPTIONS"])
def agent_nodes(request: HttpRequest) -> JsonResponse:
    return _json_response(
        request,
        {
            "contract_version": "agent_capability_catalog.v1",
            "nodes": list_public_agent_nodes(),
        },
    )


@csrf_exempt
@require_http_methods(["GET", "POST", "OPTIONS"])
def attachments(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        if _is_canonical_mock_request(request):
            identity_payload = _request_access_payload(request, session_id=request.GET.get("session_id"))
            policy_response = _canonical_guest_identity_policy_response(request, identity_payload)
            if policy_response is not None:
                return policy_response
            access = _authorize_session_query(request.GET.get("session_id"), identity_payload, resource_type="uploaded_file_list")
            if not access["allowed"]:
                return _object_access_denied_response(request, access)
            subject = access_subject_from_payload(identity_payload)["subject"]
            owner_id = subject.get("user_id")
            attachments_payload = list_uploaded_files(
                session_id=request.GET.get("session_id"),
                owner_id=owner_id if owner_id else None,
            )
        else:
            attachments_payload = list_mock_attachments(session_id=request.GET.get("session_id"))
        return _json_response(request, {"attachments": attachments_payload})

    payload = _request_payload(request)
    upload_limit_violation = getattr(request, "file_upload_limit_violation", None)
    if isinstance(upload_limit_violation, dict):
        return _file_upload_too_large_response(
            request,
            UploadTooLargeError(
                size_bytes=int(upload_limit_violation.get("size_bytes") or 0),
                limit_bytes=int(upload_limit_violation.get("limit_bytes") or 0),
            ),
        )
    upload_file = _first_upload_file(request)
    if _is_canonical_mock_request(request):
        identity_payload = _payload_with_request_identity(request, payload)
        policy_response = _canonical_guest_identity_policy_response(request, identity_payload)
        if policy_response is not None:
            return policy_response
        usage = record_usage_event(identity_payload, scope="file_upload")
        if not usage["allowed"]:
            return _rate_limit_response(request, usage)
        try:
            attachment = register_uploaded_file(identity_payload, upload_file=upload_file)
        except UploadValidationError as exc:
            _refund_usage_safely(usage, reason="file_upload_invalid")
            return _file_upload_validation_response(request, reason=exc.reason)
        except UploadTooLargeError as exc:
            _refund_usage_safely(usage, reason="file_upload_too_large")
            return _file_upload_too_large_response(request, exc)
        except UploadStorageUnavailableError:
            _refund_usage_safely(usage, reason="file_upload_storage_failed")
            return _file_upload_storage_unavailable_response(request)
        except PermissionError:
            _refund_usage_safely(usage, reason="file_upload_access_denied")
            return _persistence_access_denied_response(request)
        attachment["usage"] = usage
    else:
        attachment = register_mock_attachment(payload, upload_file=upload_file)
    return _json_response(request, {"attachment": attachment})


@require_http_methods(["GET", "OPTIONS"])
def attachment_detail(request: HttpRequest, attachment_id: str) -> JsonResponse:
    if _is_canonical_mock_request(request):
        identity_payload = _request_access_payload(request, session_id=request.GET.get("session_id"))
        access_metadata = get_uploaded_file_access_metadata(attachment_id)
        if access_metadata is not None:
            access = authorize_resource_access(access_metadata, identity_payload)
            if not access["allowed"]:
                return _object_access_denied_response(request, access)
        attachment = get_uploaded_file(attachment_id)
    else:
        attachment = get_mock_attachment(attachment_id)
    if not attachment:
        return _json_response(
            request,
            {
                "error": {
                    "code": "attachment_not_found",
                    "message": "??? attachment metadata? ?? ? ????.",
                }
            },
            status=404,
        )
    return _json_response(request, {"attachment": attachment})


@csrf_exempt
@require_http_methods(["GET", "POST", "OPTIONS"])
def analysis_jobs(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        session_id = request.GET.get("session_id")
        identity_payload = _request_access_payload(request, session_id=session_id)
        subject = access_subject_from_payload(identity_payload)["subject"]
        if session_id:
            session_access = get_chat_session_access_metadata(session_id)
            if session_access is None:
                return _object_access_denied_response(
                    request,
                    {
                        "contract_version": "object_access.v1",
                        "allowed": False,
                        "reason": "not_found_or_forbidden",
                        "resource": {"type": "chat_session"},
                    },
                )
            access = authorize_resource_access(session_access, identity_payload)
            if not access["allowed"]:
                return _object_access_denied_response(request, access)
        return _json_response(
            request,
            {
                "jobs": list_analysis_job_records(
                    owner_id=str(subject.get("user_id") or ""),
                    session_id=session_id,
                )
            },
        )

    body = _json_body(request)
    identity_body = _payload_with_request_identity(request, body) if _is_canonical_mock_request(request) else body
    usage = None
    if _is_canonical_mock_request(request):
        try:
            identity_body = protect_chat_input_payload(identity_body)
        except ChatInputRejected as exc:
            return _analysis_job_chat_input_rejected_response(request, exc)
        requested_session_id = str(identity_body.get("session_id") or "")
        if requested_session_id:
            session_access = get_chat_session_access_metadata(requested_session_id)
            if session_access is not None:
                access = authorize_resource_access(session_access, identity_body)
                if not access["allowed"]:
                    return _object_access_denied_response(request, access)
        requested_job_id = str(identity_body.get("job_id") or "")
        request_fingerprint = ""
        reservation_token = ""
        reservation_generation: object = None
        reservation_acquired = False
        if requested_job_id:
            if not requested_session_id:
                return _analysis_job_request_error_response(
                    request,
                    code="analysis_job_session_required",
                    message="session_id is required when a client supplies job_id.",
                )
            request_fingerprint = _analysis_job_request_fingerprint(identity_body)
            try:
                reservation = reserve_analysis_job_request(
                    identity_body,
                    job_id=requested_job_id,
                    request_fingerprint=request_fingerprint,
                )
            except PermissionError:
                return _object_access_denied_response(
                    request,
                    {
                        "contract_version": "object_access.v1",
                        "allowed": False,
                        "reason": "not_found_or_forbidden",
                        "resource": {"type": "analysis_job"},
                    },
                )
            except ValueError:
                return _analysis_job_conflict_response(request)
            except Exception as exc:  # pragma: no cover - infrastructure failure boundary.
                logger.warning(
                    "analysis job reservation failed error_type=%s",
                    exc.__class__.__name__,
                )
                return _analysis_job_unavailable_response(request)
            reservation_acquired = bool(reservation.get("acquired"))
            reservation_token = str(reservation.get("reservation_token") or "")
            reservation_generation = reservation.get("reservation_generation")
            if not reservation_acquired:
                try:
                    existing_job = get_analysis_job_record(requested_job_id)
                except Exception as exc:  # pragma: no cover - infrastructure failure boundary.
                    logger.warning(
                        "analysis job replay lookup failed error_type=%s",
                        exc.__class__.__name__,
                    )
                    return _analysis_job_unavailable_response(request)
                if existing_job is None:
                    return _analysis_job_unavailable_response(request)
                existing_metadata = (
                    existing_job.get("metadata")
                    if isinstance(existing_job.get("metadata"), dict)
                    else {}
                )
                if existing_metadata.get("source") == "canonical_analysis_job_reservation":
                    return _analysis_job_reservation_pending_response(request)
                replay_job = _analysis_job_replay_payload(existing_job)
                replay_status = 202 if replay_job["status"] in {"queued", "running"} else 200
                return _json_response(
                    request,
                    {"job": replay_job},
                    status=replay_status,
                )

        identity_body = apply_attachment_scan_gate(identity_body)
        if _has_blocked_attachments(identity_body):
            blocked_response = _scan_blocked_chat_response_from_payload(identity_body)
            _release_analysis_job_reservation_safely(
                job_id=requested_job_id,
                request_fingerprint=request_fingerprint,
                reservation_token=reservation_token,
                acquired=reservation_acquired,
            )
            return _analysis_scan_blocked_response(request, blocked_response)

        if reservation_acquired:
            try:
                reservation_is_current = renew_analysis_job_reservation(
                    job_id=requested_job_id,
                    request_fingerprint=request_fingerprint,
                    reservation_token=reservation_token,
                )
            except Exception as exc:  # pragma: no cover - infrastructure failure boundary.
                logger.warning(
                    "analysis job reservation renewal failed error_type=%s",
                    exc.__class__.__name__,
                )
                return _analysis_job_unavailable_response(request)
            if not reservation_is_current:
                return _analysis_job_conflict_response(request)

        usage = record_usage_event(identity_body, scope="agent_run")
        if not usage["allowed"]:
            _release_analysis_job_reservation_safely(
                job_id=requested_job_id,
                request_fingerprint=request_fingerprint,
                reservation_token=reservation_token,
                acquired=reservation_acquired,
            )
            return _rate_limit_response(request, usage)

        try:
            chat_response = submit_message(identity_body)
        except Exception as exc:  # pragma: no cover - provider failures are integration-tested.
            _refund_usage_safely(usage, reason="analysis_planning_failed")
            _release_analysis_job_reservation_safely(
                job_id=requested_job_id,
                request_fingerprint=request_fingerprint,
                reservation_token=reservation_token,
                acquired=reservation_acquired,
            )
            logger.warning(
                "analysis job planning failed error_type=%s",
                exc.__class__.__name__,
            )
            return _analysis_job_unavailable_response(request)
        if _has_blocked_attachments(chat_response):
            blocked_response = _scan_blocked_chat_response(chat_response)
            _refund_usage_safely(usage, reason="attachment_scan_blocked")
            _release_analysis_job_reservation_safely(
                job_id=requested_job_id,
                request_fingerprint=request_fingerprint,
                reservation_token=reservation_token,
                acquired=reservation_acquired,
            )
            return _analysis_scan_blocked_response(request, blocked_response)
        analysis_plan = chat_response.get("analysis_plan") or {}
        active_node = _analysis_plan_active_node(analysis_plan)
        if not active_node:
            _refund_usage_safely(usage, reason="analysis_plan_not_executable")
            _release_analysis_job_reservation_safely(
                job_id=requested_job_id,
                request_fingerprint=request_fingerprint,
                reservation_token=reservation_token,
                acquired=reservation_acquired,
            )
            return _json_response(
                request,
                {
                    "error": {
                        "contract_version": "analysis_job_error.v1",
                        "type": "conflict",
                        "code": "analysis_plan_not_executable",
                        "status": 409,
                        "message": "The analysis plan requires more input before it can be queued.",
                    },
                    "analysis": {
                        "status": chat_response.get("status") or "needs_input",
                        "assistant_message": chat_response.get("assistant_message"),
                        "consultation_state": chat_response.get("consultation_state"),
                        "case_status": chat_response.get("case_status"),
                        "pending_questions": chat_response.get("pending_questions") or [],
                    },
                },
                status=409,
            )
        node_execution = _queued_node_execution_placeholder(
            identity_body,
            analysis_plan=analysis_plan,
            chat_response=chat_response,
        )
        job_payload = _agent_plan_job_payload(
            identity_body,
            {
                "analysis_plan": analysis_plan,
                "chat_response": chat_response,
                "node_execution": node_execution,
            },
        )
        job_payload["status"] = "queued"
        job_payload["active_node"] = active_node
        job_payload["progress_message"] = "Analysis job queued for agent worker."
        job_payload["node_execution"] = node_execution
        if request_fingerprint:
            job_payload["idempotency"] = {
                "contract_version": "analysis_job_idempotency.v1",
                "request_fingerprint": request_fingerprint,
                "reservation_token": reservation_token,
                "reservation_generation": reservation_generation,
                "state": "queued",
            }
        if reservation_acquired:
            try:
                reservation_is_current = renew_analysis_job_reservation(
                    job_id=requested_job_id,
                    request_fingerprint=request_fingerprint,
                    reservation_token=reservation_token,
                )
            except Exception as exc:  # pragma: no cover - infrastructure failure boundary.
                _refund_usage_safely(usage, reason="analysis_reservation_renewal_failed")
                _release_analysis_job_reservation_safely(
                    job_id=requested_job_id,
                    request_fingerprint=request_fingerprint,
                    reservation_token=reservation_token,
                    acquired=reservation_acquired,
                )
                logger.warning(
                    "analysis job reservation renewal failed error_type=%s",
                    exc.__class__.__name__,
                )
                return _analysis_job_unavailable_response(request)
            if not reservation_is_current:
                _refund_usage_safely(usage, reason="analysis_reservation_lost")
                return _analysis_job_conflict_response(request)
        try:
            persistence = enqueue_analysis_job_work(identity_body, job_payload)
        except PermissionError:
            _refund_usage_safely(usage, reason="analysis_queue_access_denied")
            _release_analysis_job_reservation_safely(
                job_id=requested_job_id,
                request_fingerprint=request_fingerprint,
                reservation_token=reservation_token,
                acquired=reservation_acquired,
            )
            return _object_access_denied_response(
                request,
                {
                    "contract_version": "object_access.v1",
                    "allowed": False,
                    "reason": "not_found_or_forbidden",
                    "resource": {"type": "analysis_job"},
                },
            )
        except ValueError:
            _refund_usage_safely(usage, reason="analysis_queue_conflict")
            _release_analysis_job_reservation_safely(
                job_id=requested_job_id,
                request_fingerprint=request_fingerprint,
                reservation_token=reservation_token,
                acquired=reservation_acquired,
            )
            return _analysis_job_conflict_response(request)
        except Exception as exc:  # pragma: no cover - infrastructure failure boundary.
            _refund_usage_safely(usage, reason="analysis_queue_failed")
            _release_analysis_job_reservation_safely(
                job_id=requested_job_id,
                request_fingerprint=request_fingerprint,
                reservation_token=reservation_token,
                acquired=reservation_acquired,
            )
            logger.warning(
                "analysis job queue persistence failed error_type=%s",
                exc.__class__.__name__,
            )
            return _analysis_job_unavailable_response(request)
        work_item = {
            "contract_version": "agent_worker_queue.v1",
            "work_item_id": persistence["work_item_id"],
            "status": persistence["work_item_status"],
            "job_id": persistence["job_id"],
        }
        job = {
            "contract_version": "analysis_job_accepted.v1",
            "job_id": job_payload.get("job_id"),
            "session_id": job_payload.get("session_id"),
            "message_id": job_payload.get("message_id"),
            "routing_intent": job_payload.get("routing_intent"),
            "status": "queued",
            "active_node": active_node,
            "progress_message": job_payload["progress_message"],
            "analysis_plan_id": job_payload.get("analysis_plan_id"),
            "analysis_plan": {
                "plan_id": analysis_plan.get("plan_id") if isinstance(analysis_plan, dict) else None,
                "node_codes": _analysis_plan_executable_node_codes(analysis_plan),
            },
            "node_execution": node_execution,
            "status_counts": node_execution.get("status_counts") or {"queued": 1},
            "execution_mode": "async_worker",
            "persistence": persistence,
            "work_item": work_item,
            "usage": usage,
        }
    else:
        job = create_analysis_job(identity_body)
    actor = _history_actor(request, body)
    source = _history_source(request)
    subject = subject_from_payload(
        body,
        session_id=job.get("session_id"),
        message_id=job.get("message_id"),
        job_id=job.get("job_id"),
    )
    _record_history_safely(
        request,
        event_type="analysis_job_created",
        status=job.get("status") or "success",
        summary="?? job? mock ??????.",
        actor=actor,
        subject=subject,
        source=source,
        metadata={
            "routing_intent": job.get("routing_intent"),
            "mock_scenario": job.get("mock_scenario"),
            "active_node": job.get("active_node"),
            "analysis_plan_id": job.get("analysis_plan_id"),
            "status_counts": job.get("status_counts", {}),
        },
    )
    executions = job.get("node_execution", {}).get("executions", [])
    if executions:
        _record_agent_events_safely(
            request,
            executions,
            actor=actor,
            source=source,
            subject=subject,
        )
    response_status = 202 if job.get("execution_mode") == "async_worker" else 200
    return _json_response(request, {"job": job}, status=response_status)


@require_http_methods(["GET", "OPTIONS"])
def analysis_job_detail(request: HttpRequest, job_id: str) -> JsonResponse:
    access_response = _analysis_job_access_response(request, job_id)
    if access_response is not None:
        return access_response
    outcome = load_analysis_job_detail(
        job_id,
        load_job=get_analysis_job_record,
        load_progress=read_analysis_job_progress,
    )
    if outcome.kind == "not_found":
        return _json_response(
            request,
            {
                "error": {
                    "code": "analysis_job_not_found",
                    "message": "??? analysis job? ?? ? ????.",
                }
            },
            status=404,
        )
    return _json_response(request, {"job": outcome.payload})


@require_http_methods(["GET", "OPTIONS"])
def analysis_result(request: HttpRequest, job_id: str) -> JsonResponse:
    access_response = _analysis_job_access_response(request, job_id)
    if access_response is not None:
        return access_response
    outcome = load_analysis_result(
        job_id,
        load_job=get_analysis_job_record,
        compose_response=compose_agent_response,
    )
    if outcome.kind == "not_found":
        return _json_response(
            request,
            {
                "error": {
                    "code": "analysis_result_not_found",
                    "message": "Requested analysis result was not found.",
                }
            },
            status=404,
        )
    status = 202 if outcome.kind == "pending" else 200
    return _json_response(request, {"result": outcome.payload}, status=status)


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def create_chat_session(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    payload = create_session(user_id=body.get("user_id"))
    _record_history_safely(
        request,
        event_type="chat_session_created",
        status="success",
        summary="?? session? mock ??????.",
        actor=_history_actor(request, body),
        subject=subject_from_payload(body, session_id=payload.get("session_id")),
        source=_history_source(request),
        metadata={"session_status": payload.get("status")},
    )
    return _json_response(request, payload)


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def submit_chat_message(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    identity_body = _payload_with_request_identity(request, body)
    policy_response = _canonical_guest_identity_policy_response(request, identity_body)
    if policy_response is not None:
        return policy_response
    requested_session_id = str(identity_body.get("session_id") or "")
    if requested_session_id:
        session_access = get_chat_session_access_metadata(requested_session_id)
        if session_access is not None:
            access = authorize_resource_access(session_access, identity_body)
            if not access["allowed"]:
                return _object_access_denied_response(request, access)
    identity_body = apply_attachment_scan_gate(identity_body)
    if _has_blocked_attachments(identity_body):
        return _chat_scan_blocked_response(
            request,
            chat_response=_scan_blocked_chat_response_from_payload(identity_body),
        )

    usage = record_usage_event(identity_body, scope="chat_message")
    if not usage["allowed"]:
        return _rate_limit_response(request, usage)
    try:
        chat_response = submit_message(identity_body)
    except Exception:
        _refund_usage_safely(usage, reason="chat_planning_failed")
        raise
    conversation_save_state = conversation_save_state_from_payload(identity_body)

    if _has_blocked_attachments(chat_response):
        _refund_usage_safely(usage, reason="attachment_scan_blocked")
        return _chat_scan_blocked_response(
            request,
            chat_response=chat_response,
        )

    if chat_response["status"] == "supervisor_unavailable":
        _refund_usage_safely(usage, reason="supervisor_unavailable")
        chat_response["usage"] = usage
        chat_response["execution_mode"] = "planning_blocked"
        return _json_response(request, chat_response, status=503)

    if chat_response["status"] in {"needs_input", "high_risk_handoff", "case_ready"}:
        chat_response["usage"] = usage
        execution_modes = {
            "needs_input": "input_collection",
            "high_risk_handoff": "expert_handoff",
            "case_ready": "case_creation_required",
        }
        chat_response["execution_mode"] = execution_modes[chat_response["status"]]
        return _json_response(request, chat_response)

    execution_payload = {
        **identity_body,
        "session_id": chat_response.get("session_id"),
        "message_id": chat_response.get("message_id"),
        "attachments": chat_response.get("attachments", []),
        "execution_mode": "sync",
        "context": {
            **(
                identity_body.get("context")
                if isinstance(identity_body.get("context"), dict)
                else {}
            ),
            "supervisor_handoff": chat_response.get("supervisor_state", {}),
        },
    }

    node_execution = _queued_node_execution_placeholder(
        execution_payload,
        analysis_plan=chat_response.get("analysis_plan") or {},
        chat_response=chat_response,
    )
    job_payload = _agent_plan_job_payload(
        execution_payload,
        {
            "analysis_plan": chat_response.get("analysis_plan") or {},
            "chat_response": chat_response,
            "node_execution": node_execution,
        },
    )
    job_payload["status"] = "queued"
    job_payload["active_node"] = _analysis_plan_active_node(chat_response.get("analysis_plan") or {})
    job_payload["progress_message"] = "Supervisor chat plan queued for agent worker."
    job_payload["node_execution"] = {}
    try:
        persistence = enqueue_analysis_job_work(execution_payload, job_payload)
    except Exception:
        _refund_usage_safely(usage, reason="chat_queue_failed")
        raise
    chat_response["persistence"] = persistence
    chat_response["node_execution"] = node_execution
    chat_response["work_item"] = {
        "contract_version": "agent_worker_queue.v1",
        "work_item_id": persistence["work_item_id"],
        "status": persistence["work_item_status"],
        "job_id": persistence["job_id"],
    }
    chat_response["supervisor_execution"] = _supervisor_execution_response(
        node_execution,
        persistence=persistence,
    )
    chat_response["usage"] = usage
    chat_response["execution_mode"] = "async_worker"
    _record_history_safely(
        request,
        event_type="chat_message_created",
        status=chat_response.get("status") or "success",
        summary="Chat message was accepted and queued for Agent execution.",
        actor=_history_actor(request, body),
        subject=subject_from_payload(
            body,
            session_id=chat_response.get("session_id"),
            message_id=chat_response.get("message_id"),
        ),
        source=_history_source(request),
        metadata={
            "routing_intent": chat_response.get("routing_intent"),
            "response_status": chat_response.get("status"),
            "conversation_save_state": conversation_save_state,
            "conversation_save_policy": "conversation_save_policy.v1",
            "attachment_count": len(chat_response.get("attachments", [])),
            "card_count": len(chat_response.get("cards", [])),
            "pending_fields": [
                item.get("field")
                for item in chat_response.get("pending_questions", [])
                if isinstance(item, dict)
            ],
        },
        privacy={"risk_level": "medium"},
    )
    return _json_response(request, chat_response, status=202)


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def update_chat_save_state(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    identity_body = _payload_with_request_identity(request, body) if _is_canonical_mock_request(request) else body
    session_id = str(body.get("session_id") or identity_body.get("session_id") or "")

    if _is_canonical_mock_request(request):
        access = _authorize_session_query(session_id, identity_body, resource_type="chat_save_state")
        if not access["allowed"]:
            return _object_access_denied_response(request, access)

    subject = access_subject_from_payload(identity_body)["subject"]
    save_state = conversation_save_state_from_payload(body, default="pending")
    if _is_canonical_mock_request(request):
        guest_violation = _guest_identity_policy_violation(subject)
        if guest_violation:
            return _guest_identity_policy_response(request, guest_violation)
        if save_state == "saved" and subject.get("subject_type") != "user":
            return _login_required_response(
                request,
                action="conversation_save",
                reason="saved_requires_authenticated_user",
                message="??? ?? ??? ????? ???? ?????.",
                policy_version="conversation_save_policy.v1",
                subject=subject,
            )
    result = mark_conversation_save_state(
        session_id=session_id,
        save_state=save_state,
        owner_id=str(subject.get("user_id") or ""),
        guest_id=str(subject.get("guest_id") or ""),
        raw_payload=body,
    )
    if result.get("conversation_save_state") == "saved":
        _record_history_safely(
            request,
            event_type="conversation_saved",
            status="success",
            summary="Conversation was promoted to My Page history after user consent.",
            actor=_history_actor(request, body),
            subject=subject_from_payload(body, session_id=session_id),
            source=_history_source(request),
            metadata={
                "conversation_save_state": "saved",
                "conversation_save_policy": "conversation_save_policy.v1",
            },
        )
    return _json_response(request, {"conversation_save": result})


@csrf_exempt
@require_http_methods(["GET", "POST", "OPTIONS"])
def consultation_cases(request: HttpRequest) -> JsonResponse:
    body = _json_body(request) if request.method == "POST" else {}
    identity_payload = _payload_with_request_identity(request, body)
    subject = access_subject_from_payload(identity_payload)["subject"]
    login_response = _case_login_required_response(request, subject, action="case_access")
    if login_response is not None:
        return login_response
    owner_id = str(subject.get("user_id") or "")

    if request.method == "GET":
        response_payload = _serialize_response_dto(
            ConsultationCaseListResponse,
            {
                "contract_version": "consultation_case_list.v2",
                "cases": list_cases(owner_id=owner_id),
            },
        )
        return _json_response(
            request,
            response_payload,
        )

    validated, validation_response = _validate_request_dto(
        request,
        CreateConsultationCaseRequest,
        body,
    )
    if validation_response is not None:
        return validation_response
    try:
        case = create_case(
            owner_id=owner_id,
            guest_id=str(subject.get("guest_id") or ""),
            payload=validated,
        )
    except CaseRepositoryError as exc:
        return _case_repository_error_response(request, exc)
    response_payload = _serialize_response_dto(
        CreateConsultationCaseResponse,
        {"contract_version": "consultation_case.v2", "case": case},
    )
    return _json_response(request, response_payload, status=201)


@csrf_exempt
@require_http_methods(["GET", "OPTIONS"])
def consultation_case_workspace(request: HttpRequest, case_id: str) -> JsonResponse:
    identity_payload = _request_access_payload(request)
    subject = access_subject_from_payload(identity_payload)["subject"]
    login_response = _case_login_required_response(request, subject, action="case_workspace")
    if login_response is not None:
        return login_response
    access = authorize_resource_access(
        get_case_access_metadata(case_id) or {"type": "case", "case_id": case_id},
        identity_payload,
    )
    if not access["allowed"]:
        return _object_access_denied_response(request, access)
    try:
        workspace = get_case_workspace(case_id)
    except CaseRepositoryError as exc:
        return _case_repository_error_response(request, exc)
    response_payload = _serialize_response_dto(
        ConsultationCaseWorkspaceResponse,
        {"workspace": workspace},
    )
    return _json_response(request, response_payload)


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def consultation_case_fact_confirmation(request: HttpRequest, case_id: str) -> JsonResponse:
    body = _json_body(request)
    identity_payload = _payload_with_request_identity(request, body)
    subject = access_subject_from_payload(identity_payload)["subject"]
    login_response = _case_login_required_response(request, subject, action="case_fact_confirmation")
    if login_response is not None:
        return login_response
    access = authorize_resource_access(
        get_case_access_metadata(case_id) or {"type": "case", "case_id": case_id},
        identity_payload,
    )
    if not access["allowed"]:
        return _object_access_denied_response(request, access)
    validated, validation_response = _validate_request_dto(
        request,
        ConfirmCaseFactsRequest,
        body,
    )
    if validation_response is not None:
        return validation_response
    try:
        fact_version = confirm_case_facts(
            case_id,
            owner_id=str(subject.get("user_id") or ""),
            payload=validated,
        )
    except CaseRepositoryError as exc:
        return _case_repository_error_response(request, exc)
    response_payload = _serialize_response_dto(
        ConfirmCaseFactsResponse,
        {"contract_version": "confirmed_facts.v1", "fact_version": fact_version},
    )
    return _json_response(request, response_payload, status=201)


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def consultation_case_analysis_jobs(request: HttpRequest, case_id: str) -> JsonResponse:
    body = _json_body(request)
    identity_payload = _payload_with_request_identity(request, body)
    subject = access_subject_from_payload(identity_payload)["subject"]
    login_response = _case_login_required_response(request, subject, action="case_analysis")
    if login_response is not None:
        return login_response
    access = authorize_resource_access(
        get_case_access_metadata(case_id) or {"type": "case", "case_id": case_id},
        identity_payload,
    )
    if not access["allowed"]:
        return _object_access_denied_response(request, access)
    validated, validation_response = _validate_request_dto(
        request,
        StartCaseAnalysisRequest,
        body,
    )
    if validation_response is not None:
        return validation_response
    try:
        result = start_case_analysis(
            case_id,
            owner_id=str(subject.get("user_id") or ""),
            payload=validated,
        )
    except CaseRepositoryError as exc:
        return _case_repository_error_response(request, exc)
    response_payload = _serialize_response_dto(StartCaseAnalysisResponse, result)
    return _json_response(request, response_payload, status=202)


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def run_agent_node(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    node_execution = execute_agent_node(body)
    agent_output = node_execution.get("agent_output") or {}
    _record_agent_events_safely(
        request,
        [node_execution],
        actor=_history_actor(request, body),
        source=_history_source(request, node_code=node_execution.get("node_code")),
        subject=subject_from_payload(
            body,
            session_id=agent_output.get("session_id"),
            message_id=agent_output.get("message_id"),
            job_id=agent_output.get("job_id"),
        ),
    )
    return _json_response(request, node_execution)


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def run_agent_plan(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    execution_payload = _payload_with_request_identity(request, body) if _is_canonical_mock_request(request) else body
    if _is_canonical_mock_request(request):
        execution_payload = apply_attachment_scan_gate(execution_payload)
    chat_response = None
    analysis_plan = execution_payload.get("analysis_plan")
    if not analysis_plan:
        chat_response = submit_message(execution_payload)
        analysis_plan = chat_response["analysis_plan"]

    response = {"analysis_plan": analysis_plan}
    if chat_response:
        response["chat_response"] = chat_response
    if _is_canonical_mock_request(request):
        if _uses_async_worker(execution_payload) or _analysis_plan_requires_persisted_reporting(
            analysis_plan
        ):
            response["node_execution"] = _queued_node_execution_placeholder(
                execution_payload,
                analysis_plan=analysis_plan,
                chat_response=chat_response,
            )
            job_payload = _agent_plan_job_payload(execution_payload, response)
            job_payload["status"] = "queued"
            job_payload["active_node"] = _analysis_plan_active_node(analysis_plan)
            job_payload["progress_message"] = "Supervisor plan queued for agent worker."
            job_payload["node_execution"] = {}
            if job_payload.get("session_id"):
                persistence = enqueue_analysis_job_work(execution_payload, job_payload)
                response["persistence"] = persistence
                response["work_item"] = {
                    "contract_version": "agent_worker_queue.v1",
                    "work_item_id": persistence["work_item_id"],
                    "status": persistence["work_item_status"],
                    "job_id": persistence["job_id"],
                }
            else:
                response["persistence"] = {
                    "backend": "postgresql",
                    "status": "skipped",
                    "reason": "missing_session_id",
                }
            return _json_response(request, response)

        response["node_execution"] = execute_agent_plan(analysis_plan, execution_payload)
        job_payload = _agent_plan_job_payload(execution_payload, response)
        if job_payload.get("session_id"):
            response["persistence"] = persist_analysis_job_execution(execution_payload, job_payload)
        else:
            response["persistence"] = {
                "backend": "postgresql",
                "status": "skipped",
                "reason": "missing_session_id",
            }
    else:
        response["node_execution"] = execute_agent_plan(analysis_plan, execution_payload)
    _record_agent_events_safely(
        request,
        response["node_execution"].get("executions", []),
        actor=_history_actor(request, body),
        source=_history_source(request),
        subject=subject_from_payload(
            body,
            session_id=response["node_execution"].get("session_id"),
            message_id=response["node_execution"].get("message_id"),
            job_id=response["node_execution"].get("job_id"),
        ),
    )
    return _json_response(request, response)


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def process_agent_work_items_once(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    result = process_agent_work_items(limit=_positive_int(body.get("limit"), default=1))
    return _json_response(request, result)


@csrf_exempt
@require_http_methods(["GET", "POST", "OPTIONS"])
def report_action(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        identity_payload = _request_access_payload(request, session_id=request.GET.get("session_id"))
        subject = access_subject_from_payload(identity_payload)["subject"]
        if _is_canonical_mock_request(request):
            guest_violation = _guest_identity_policy_violation(subject)
            if guest_violation:
                return _guest_identity_policy_response(request, guest_violation)
            if subject.get("subject_type") != "user":
                return _login_required_response(
                    request,
                    action="report_list",
                    reason="report_list_requires_authenticated_user",
                    message="??? ??? ????? ???? ?????.",
                    policy_version="report_action_policy.v1",
                    subject=subject,
                )
        reports = list_report_records(
            session_id=request.GET.get("session_id"),
            owner_id=str(subject.get("user_id") or "") if _is_canonical_mock_request(request) else request.GET.get("owner_id"),
        )
        has_worker_reports = any(
            report.get("source") == "analysis_worker_reporting"
            for report in reports
        )
        return _json_response(
            request,
            {
                "api_surface": (
                    "canonical"
                    if _is_canonical_mock_request(request) and has_worker_reports
                    else "canonical_mock"
                    if _is_canonical_mock_request(request)
                    else "mock"
                ),
                "reports": reports,
            },
        )

    body = _json_body(request)
    identity_body = _payload_with_request_identity(request, body) if _is_canonical_mock_request(request) else body
    subject = access_subject_from_payload(identity_body)["subject"]
    action = str(body.get("action") or identity_body.get("action") or "save").lower()
    if _is_canonical_mock_request(request):
        guest_violation = _guest_identity_policy_violation(subject)
        if guest_violation:
            return _guest_identity_policy_response(request, guest_violation)
        if action in {"save", "download"} and subject.get("subject_type") != "user":
            return _login_required_response(
                request,
                action=f"report_{action}",
                reason=f"guest_report_{action}_requires_login",
                message="???? ????? ??????? ???? ?????.",
                policy_version="report_action_policy.v1",
                subject=subject,
            )
        access_response = _canonical_report_action_access_response(
            request,
            identity_body,
        )
        if access_response is not None:
            return access_response
        return _worker_report_action_required_response(request)
    return _worker_report_action_required_response(request)


@require_http_methods(["GET", "OPTIONS"])
def report_detail(request: HttpRequest, report_id: str) -> JsonResponse:
    access_metadata = None
    if _is_canonical_mock_request(request):
        identity_payload = _request_access_payload(request, session_id=request.GET.get("session_id"))
        subject = access_subject_from_payload(identity_payload)["subject"]
        guest_violation = _guest_identity_policy_violation(subject)
        if guest_violation:
            return _guest_identity_policy_response(request, guest_violation)
        if subject.get("subject_type") != "user":
            return _login_required_response(
                request,
                action="report_detail",
                reason="report_detail_requires_authenticated_user",
                message="??? ??? ????? ???? ?????.",
                policy_version="report_action_policy.v1",
                subject=subject,
            )
        access_metadata = get_report_access_metadata(report_id)
        if access_metadata is not None:
            access = authorize_report_download_metadata(access_metadata, identity_payload)
            if not access["allowed"]:
                return _object_access_denied_response(request, access)

    report = get_report_record_detail(report_id)
    if report is None:
        return _json_response(
            request,
            {
                "error": {
                    "code": "report_not_found",
                    "message": "Requested report was not found.",
                }
            },
            status=404,
        )
    return _json_response(
        request,
        {
            "api_surface": (
                "canonical"
                if _is_canonical_mock_request(request)
                and report.get("source") == "analysis_worker_reporting"
                else "canonical_mock"
                if _is_canonical_mock_request(request)
                else "mock"
            ),
            "execution_mode": (
                "async_worker"
                if report.get("source") == "analysis_worker_reporting"
                else "mock"
            ),
            "report": report,
        },
    )


@require_http_methods(["GET", "OPTIONS"])
def download_report(request: HttpRequest, report_id: str) -> HttpResponse:
    if _is_canonical_mock_request(request):
        identity_payload = _request_access_payload(request, session_id=request.GET.get("session_id"))
        subject = access_subject_from_payload(identity_payload)["subject"]
        guest_violation = _guest_identity_policy_violation(subject)
        if guest_violation:
            return _guest_identity_policy_response(request, guest_violation)
        if subject.get("subject_type") != "user":
            return _login_required_response(
                request,
                action="report_download",
                reason="report_download_requires_authenticated_user",
                message="???? ??????? ???? ?????.",
                policy_version="report_action_policy.v1",
                subject=subject,
            )
        access_metadata = get_report_access_metadata(report_id)
        if access_metadata is None:
            return _json_response(
                request,
                {
                    "error": {
                        "code": "report_not_found",
                        "message": "Requested report was not found.",
                    }
                },
                status=404,
            )
        access = authorize_report_download_metadata(access_metadata, identity_payload)
        if not access["allowed"]:
            return _object_access_denied_response(request, access)
        if (
            access_metadata.get("source") == "analysis_worker_reporting"
            and access_metadata.get("status") != "ready"
        ):
            return _json_response(
                request,
                {
                    "error": {
                        "contract_version": "report_download.v1",
                        "code": "report_not_ready",
                        "message": "Draft analysis reports are preview-only until the Reporting gate is ready.",
                        "report_id": report_id,
                        "status": access_metadata.get("status"),
                    }
                },
                status=409,
            )
        document_type = request.GET.get("document_type")
        download = get_report_download_metadata(report_id, document_type=document_type)
        if download is not None:
            is_worker_report = access_metadata.get("source") == "analysis_worker_reporting"
            response = HttpResponse(
                download["body"],
                content_type=download["content_type"],
            )
            response["Content-Disposition"] = f'attachment; filename="{download["filename"]}"'
            response["X-API-Surface"] = "canonical" if is_worker_report else "canonical_mock"
            response["X-Execution-Mode"] = "async_worker" if is_worker_report else "mock"
            response["X-Report-Persistence"] = "postgresql"
            response["X-Report-Storage-Backend"] = download["storage_backend"]
            response["X-Report-Storage-URI"] = download["storage_uri"]
            response["X-Report-Object-Key"] = download["object_key"]
            response["X-Report-Object-Policy"] = download["object_storage"].get("policy_version", "")
            response["X-Report-Access-Decision"] = access["reason"]
            response["X-Report-Document-Type"] = download.get("document_type", "")
            return response

    response = HttpResponse(
        build_report_download_pdf_body(
            report_id=report_id,
            title="Mock report download",
            body_text=f"Mock report download for {report_id}\n",
        ),
        content_type="application/pdf",
    )
    response["Content-Disposition"] = f'attachment; filename="{report_id}.pdf"'
    if _is_canonical_mock_request(request):
        response["X-API-Surface"] = "canonical_mock"
        response["X-Execution-Mode"] = "mock"
    return response


def _history_actor(request: HttpRequest, payload: dict[str, object] | None = None) -> dict[str, object]:
    return actor_from_payload(
        payload,
        authorization_header=request.headers.get("Authorization"),
        guest_id_header=request.headers.get("X-Guest-Id"),
        auth_session_id_header=request.headers.get("X-Auth-Session-Id"),
    )


def _payload_with_request_identity(
    request: HttpRequest,
    payload: dict[str, object],
) -> dict[str, object]:
    enriched = dict(payload)
    untrusted_auth_context = (
        dict(payload.get("auth_context"))
        if isinstance(payload.get("auth_context"), dict)
        else {}
    )
    identity_keys = {
        "auth_session_id",
        "guest_id",
        "owner_id",
        "subject_id",
        "subject_type",
        "user_id",
    }
    for key in identity_keys:
        enriched.pop(key, None)
    auth_context = {
        key: value
        for key, value in untrusted_auth_context.items()
        if key not in identity_keys
    }
    status, auth_payload = _get_current_auth_subject(
        authorization_header=request.headers.get("Authorization"),
        guest_id=(
            request.headers.get("X-Guest-Id")
            or untrusted_auth_context.get("guest_id")
            or payload.get("guest_id")
        ),
        session_id=(
            enriched.get("session_id")
            or untrusted_auth_context.get("session_id")
        ),
    )
    if status < 400:
        subject = auth_payload.get("subject") if isinstance(auth_payload.get("subject"), dict) else {}
        for key in ("subject_id", "subject_type", "user_id", "guest_id", "auth_session_id"):
            value = subject.get(key)
            if value:
                auth_context[key] = value
        if subject.get("user_id"):
            authenticated_user_id = str(subject["user_id"])
            auth_context["subject_id"] = f"user:{authenticated_user_id}"
            auth_context["subject_type"] = "user"
            auth_context["user_id"] = authenticated_user_id
            if subject.get("auth_session_id"):
                auth_context["auth_session_id"] = subject["auth_session_id"]
            enriched["owner_id"] = authenticated_user_id
            enriched["user_id"] = authenticated_user_id
    elif request.headers.get("X-Guest-Id"):
        auth_context["subject_id"] = f"guest:{request.headers['X-Guest-Id']}"
        auth_context["subject_type"] = "guest"
        auth_context["guest_id"] = request.headers["X-Guest-Id"]
    if auth_context:
        enriched["auth_context"] = auth_context
    else:
        enriched.pop("auth_context", None)
    return enriched


def _request_access_payload(
    request: HttpRequest,
    *,
    session_id: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {}
    if session_id:
        payload["session_id"] = session_id
    return _payload_with_request_identity(request, payload)


def _authorize_mypage_query(
    request: HttpRequest,
    identity_payload: dict[str, object],
) -> dict[str, object]:
    requested_owner = request.GET.get("owner_id") or request.GET.get("user_id")
    if requested_owner:
        return authorize_resource_access(
            {"type": "mypage", "owner_id": requested_owner},
            identity_payload,
        )
    return _authorize_session_query(request.GET.get("session_id"), identity_payload, resource_type="mypage")


def _authorize_history_query(
    request: HttpRequest,
    identity_payload: dict[str, object],
) -> dict[str, object]:
    subject = access_subject_from_payload(identity_payload)["subject"]
    requested_user_id = request.GET.get("user_id")
    if requested_user_id:
        return authorize_resource_access(
            {"type": "history", "owner_id": requested_user_id},
            identity_payload,
        )

    requested_guest_id = request.GET.get("guest_id")
    if requested_guest_id:
        return authorize_resource_access(
            {"type": "history", "guest_id": requested_guest_id},
            identity_payload,
        )

    session_access = _authorize_session_query(
        request.GET.get("session_id"),
        identity_payload,
        resource_type="history",
    )
    if not session_access["allowed"]:
        return session_access

    if not any(request.GET.get(key) for key in ("session_id", "job_id", "event_type")):
        if subject.get("user_id") or subject.get("guest_id"):
            return session_access
        return authorize_resource_access({"type": "history", "owner_id": "__authenticated_subject_required__"}, identity_payload)
    return session_access


def _authorize_session_query(
    session_id: str | None,
    identity_payload: dict[str, object],
    *,
    resource_type: str,
) -> dict[str, object]:
    if not session_id:
        return authorize_resource_access({"type": resource_type}, identity_payload)
    session_access = get_chat_session_access_metadata(session_id)
    if session_access is None:
        return authorize_resource_access({"type": resource_type, "session_id": session_id}, identity_payload)
    session_access["type"] = resource_type
    return authorize_resource_access(session_access, identity_payload)


def _rate_limit_response(request: HttpRequest, usage: dict[str, object]) -> JsonResponse:
    required_action = "login" if usage.get("subject_type") in {"anonymous", "guest"} else "wait_or_upgrade"
    return _json_response(
        request,
        {
            "error": {
                "contract_version": "rate_limit.v1",
                "type": "rate_limit",
                "code": "rate_limit_exceeded",
                "status": 429,
                "message": "?? ??? ??????.",
                "required_action": required_action,
                "usage": usage,
            }
        },
        status=429,
    )


def _login_required_response(
    request: HttpRequest,
    *,
    action: str,
    reason: str,
    message: str,
    policy_version: str,
    subject: dict[str, object] | None = None,
    status: int = 403,
) -> JsonResponse:
    return _json_response(
        request,
        {
            "error": {
                "contract_version": "login_required.v1",
                "type": "authorization",
                "code": "login_required",
                "status": status,
                "message": message,
                "required_action": "login",
                "action": action,
                "reason": reason,
                "policy_version": policy_version,
                "subject": {
                    key: value
                    for key, value in (subject or {}).items()
                    if key in {"subject_id", "subject_type", "user_id", "guest_id", "auth_session_id"}
                    and value is not None
                },
            }
        },
        status=status,
    )


def _case_login_required_response(
    request: HttpRequest,
    subject: dict[str, object],
    *,
    action: str,
) -> JsonResponse | None:
    if subject.get("subject_type") == "user" and subject.get("user_id"):
        return None
    return _login_required_response(
        request,
        action=action,
        reason="case_requires_authenticated_user",
        message="사건 저장과 분석은 로그인 후 이용할 수 있습니다.",
        policy_version="consultation_case_policy.v2",
        subject=subject,
    )


def _validate_request_dto(
    request: HttpRequest,
    dto_type: type[BaseModel],
    payload: dict[str, object],
) -> tuple[dict[str, object], JsonResponse | None]:
    try:
        dto = dto_type.model_validate(payload)
    except ValidationError as exc:
        details = [
            {
                "field": ".".join(str(part) for part in error["loc"]),
                "type": error["type"],
                "message": error["msg"],
            }
            for error in exc.errors(include_url=False, include_input=False)
        ]
        return {}, _json_response(
            request,
            {
                "error": {
                    "contract_version": "request_validation_error.v1",
                    "type": "validation",
                    "code": "validation_error",
                    "status": 422,
                    "message": "요청 필드를 확인해 주세요.",
                    "details": details,
                }
            },
            status=422,
        )
    return dto.model_dump(mode="python"), None


def _serialize_response_dto(
    dto_type: type[BaseModel],
    payload: dict[str, object],
) -> dict[str, object]:
    """Validate internal output before it crosses the public API boundary."""

    return dto_type.model_validate(payload).model_dump(mode="json")


def _case_repository_error_response(
    request: HttpRequest,
    error: CaseRepositoryError,
) -> JsonResponse:
    payload = {
        "error": {
            "contract_version": "consultation_case_error.v2",
            "type": "case",
            "code": error.code,
            "status": error.status,
            "message": str(error),
        }
    }
    if error.details:
        payload["error"]["details"] = error.details
    return _json_response(
        request,
        payload,
        status=error.status,
    )


def _guest_identity_policy_violation(subject: dict[str, object]) -> dict[str, object] | None:
    if subject.get("subject_type") != "guest":
        return None
    guest_id = str(subject.get("guest_id") or "")
    if not guest_id:
        return None
    try:
        guest = GuestIdentity.objects.filter(guest_id=guest_id).first()
    except DatabaseError:
        return None
    if guest is None:
        return None
    if guest.status != GuestIdentityStatus.ACTIVE:
        return {"guest_id": guest_id, "reason": "guest_inactive", "status": guest.status}
    if guest.expires_at and guest.expires_at <= timezone.now():
        return {"guest_id": guest_id, "reason": "guest_expired", "status": guest.status}
    return None


def _guest_identity_policy_response(
    request: HttpRequest,
    violation: dict[str, object],
) -> JsonResponse:
    return _json_response(
        request,
        {
            "error": {
                "contract_version": "guest_identity_policy.v1",
                "type": "authorization",
                "code": "guest_session_invalid",
                "status": 401,
                "message": "??? ??? ???? ??? ???????.",
                "required_action": "refresh_guest_session",
                "reason": violation.get("reason"),
                "guest_id": violation.get("guest_id"),
                "guest_status": violation.get("status"),
            }
        },
        status=401,
    )


def _canonical_guest_identity_policy_response(
    request: HttpRequest,
    payload: dict[str, object],
) -> JsonResponse | None:
    if not _is_canonical_mock_request(request):
        return None
    subject = access_subject_from_payload(payload)["subject"]
    violation = _guest_identity_policy_violation(subject)
    if not violation:
        return None
    return _guest_identity_policy_response(request, violation)


def _report_history_event_type(action: str) -> str:
    if action == "download":
        return "report_downloaded"
    if action in {"preview", "prepare"}:
        return "report_previewed"
    return "report_saved"


def _object_access_denied_response(request: HttpRequest, access: dict[str, object]) -> JsonResponse:
    return _json_response(
        request,
        {
            "error": {
                "contract_version": "object_access.v1",
                "type": "object_access",
                "code": "object_access_denied",
                "status": 403,
                "message": "요청한 데이터에 접근할 권한이 없습니다.",
                "required_action": "login_or_owner_match",
                "access": access,
            }
        },
        status=403,
    )


def _analysis_job_access_response(
    request: HttpRequest,
    job_id: str,
) -> JsonResponse | None:
    identity_payload = _request_access_payload(request)
    policy_response = _canonical_guest_identity_policy_response(request, identity_payload)
    if policy_response is not None:
        return policy_response
    metadata = get_analysis_job_access_metadata(job_id)
    if metadata is None:
        return None
    session_id = str(metadata.get("session_id") or "").strip()
    access = (
        _authorize_session_query(
            session_id,
            identity_payload,
            resource_type="analysis_result",
        )
        if session_id
        else authorize_resource_access(metadata, identity_payload)
    )
    if access["allowed"]:
        return None
    return _object_access_denied_response(request, access)


def _persistence_access_denied_response(request: HttpRequest) -> JsonResponse:
    return _object_access_denied_response(
        request,
        {
            "allowed": False,
            "decision": "owner_mismatch",
            "policy_version": "case_persistence.v1",
        },
    )


def _file_upload_too_large_response(
    request: HttpRequest,
    error: UploadTooLargeError,
) -> JsonResponse:
    return _json_response(
        request,
        {
            "error": {
                "contract_version": "file_upload_error.v1",
                "type": "validation",
                "code": "file_too_large",
                "status": 413,
                "message": "The uploaded file exceeds the configured size limit.",
                "size_bytes": error.size_bytes,
                "limit_bytes": error.limit_bytes,
                "required_action": "select_smaller_file",
            }
        },
        status=413,
    )


def _file_upload_validation_response(
    request: HttpRequest,
    *,
    reason: str,
) -> JsonResponse:
    return _json_response(
        request,
        {
            "error": {
                "contract_version": "file_upload_error.v1",
                "type": "validation",
                "code": reason,
                "status": 400,
                "message": "A bound chat session is required for file uploads.",
                "required_action": "create_or_select_session",
            }
        },
        status=400,
    )


def _file_upload_storage_unavailable_response(request: HttpRequest) -> JsonResponse:
    response = _json_response(
        request,
        {
            "error": {
                "contract_version": "file_upload_error.v1",
                "type": "service_unavailable",
                "code": "upload_storage_unavailable",
                "status": 503,
                "message": "The upload could not be stored safely. Retry the upload.",
                "required_action": "retry_upload",
                "retryable": True,
            }
        },
        status=503,
    )
    response["Retry-After"] = "5"
    return response


def _report_reference_conflict_response(request: HttpRequest, reason: str) -> JsonResponse:
    return _json_response(
        request,
        {
            "error": {
                "contract_version": "consultation_report_error.v2",
                "type": "report",
                "code": "invalid_report_reference",
                "status": 409,
                "message": "리포트의 사건·분석·확정 사실 연결을 확인해 주세요.",
                "reason": reason,
            }
        },
        status=409,
    )


def _strip_private_oauth_payload(payload: dict[str, object]) -> None:
    payload.pop("_private_oauth_tokens", None)


def _actor_from_auth_me_payload(request: HttpRequest, payload: dict[str, object]) -> dict[str, object]:
    subject = payload.get("subject") if isinstance(payload.get("subject"), dict) else {}
    actor = _history_actor(request, {"guest_id": request.GET.get("guest_id")})
    if subject:
        actor.update(
            {
                "user_id": subject.get("user_id"),
                "guest_id": subject.get("guest_id"),
                "auth_session_id": subject.get("auth_session_id"),
                "auth_state": payload.get("auth_state"),
            }
        )
    return actor


def _history_source(request: HttpRequest, node_code: str | None = None) -> dict[str, object]:
    execution_mode = "canonical_mock" if _is_canonical_mock_request(request) else "mock"
    return source_from_request(
        api_path=request.path,
        execution_mode=execution_mode,
        node_code=node_code,
    )


def _has_blocked_attachments(chat_response: dict[str, object]) -> bool:
    blocked = chat_response.get("blocked_attachments")
    return isinstance(blocked, list) and bool(blocked)


def _scan_blocked_chat_response(chat_response: dict[str, object]) -> dict[str, object]:
    response = dict(chat_response)
    blocked = response.get("blocked_attachments") if isinstance(response.get("blocked_attachments"), list) else []
    waiting = [
        item for item in blocked
        if isinstance(item, dict) and item.get("required_action") == "wait_for_file_scan"
    ]
    rejected = [
        item for item in blocked
        if isinstance(item, dict) and item.get("required_action") == "replace_file"
    ]
    response["status"] = "partial"
    progress = dict(response.get("progress") or {})
    progress.update(
        {
            "status": "partial",
            "active_node": "input_context_validation",
            "message": "Attachment scan gate blocked agent execution.",
        }
    )
    response["progress"] = progress
    response["work_item"] = None
    response.setdefault("limitations", [])
    if waiting:
        response["limitations"].append("Some attachments are still waiting for file scan before agent execution.")
    if rejected:
        response["limitations"].append("Rejected attachments were excluded from agent execution and must be replaced.")
    response["scan_gate"] = {
        "contract_version": "attachment_scan_gate.v1",
        "status": "blocked",
        "blocked_count": len(blocked),
        "waiting_count": len(waiting),
        "rejected_count": len(rejected),
        "worker_action": "not_queued",
    }
    return response


def _scan_blocked_chat_response_from_payload(payload: dict[str, object]) -> dict[str, object]:
    return _scan_blocked_chat_response(
        {
            "contract_version": "chat_message_accepted.v2",
            "session_id": str(payload.get("session_id") or f"ses_{uuid4().hex[:12]}"),
            "message_id": f"msg_{uuid4().hex[:12]}",
            "routing_intent": payload.get("routing_intent"),
            "status": "partial",
            "progress": {},
            "analysis_plan": {
                "contract_version": "analysis_plan.v2",
                "plan_id": f"plan_{uuid4().hex[:12]}",
                "steps": [],
            },
            "attachments": payload.get("attachments") or [],
            "blocked_attachments": payload.get("blocked_attachments") or [],
            "attachment_scan_policy": payload.get("attachment_scan_policy") or {},
            "limitations": [],
        }
    )


def _chat_scan_blocked_response(
    request: HttpRequest,
    *,
    chat_response: dict[str, object],
) -> JsonResponse:
    blocked_response = _scan_blocked_chat_response(chat_response)
    blocked_response["persistence"] = {
        "backend": "none",
        "status": "skipped",
        "reason": "attachment_scan_blocked",
    }
    blocked_response["usage"] = {
        "allowed": True,
        "consumed": False,
        "scope": "chat_message",
        "reason": "attachment_scan_blocked",
    }
    blocked_response["execution_mode"] = "scan_blocked"
    return _json_response(request, blocked_response, status=409)


def _analysis_scan_blocked_response(
    request: HttpRequest,
    blocked_response: dict[str, object],
) -> JsonResponse:
    return _json_response(
        request,
        {
            "error": {
                "contract_version": "analysis_job_error.v1",
                "type": "conflict",
                "code": "attachment_scan_blocked",
                "status": 409,
                "message": "Attachments must pass file scanning before analysis can be queued.",
            },
            "analysis": {
                "status": blocked_response["status"],
                "assistant_message": blocked_response.get("assistant_message"),
                "consultation_state": blocked_response.get("consultation_state"),
                "case_status": blocked_response.get("case_status"),
                "pending_questions": blocked_response.get("pending_questions") or [],
                "scan_gate": blocked_response["scan_gate"],
                "limitations": blocked_response["limitations"],
            },
        },
        status=409,
    )


def _scan_blocked_node_execution(
    body: dict[str, object],
    chat_response: dict[str, object],
) -> dict[str, object]:
    message_id = str(chat_response.get("message_id") or body.get("message_id") or "")
    job_id = str(body.get("job_id") or "")
    if not job_id and message_id.startswith("msg_"):
        job_id = f"job_{message_id.removeprefix('msg_')}"
    return {
        "execution_mode": "async_worker",
        "status": "partial",
        "job_id": job_id,
        "plan_id": (chat_response.get("analysis_plan") or {}).get("plan_id")
        if isinstance(chat_response.get("analysis_plan"), dict)
        else None,
        "session_id": chat_response.get("session_id") or body.get("session_id"),
        "message_id": message_id,
        "executions": [],
        "status_counts": {"blocked": 1},
        "completed_node_codes": [],
    }


def _analysis_job_request_fingerprint(payload: dict[str, object]) -> str:
    excluded_identity_fields = {
        "job_id",
        "owner_id",
        "user_id",
        "auth_context",
        "safe_user_text",
        "privacy_gateway",
    }
    request_contract = {
        "contract_version": "analysis_job_request_fingerprint.v1",
        "planner_input": {
            key: value
            for key, value in payload.items()
            if key not in excluded_identity_fields
        },
    }
    serialized = json.dumps(
        request_contract,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _release_analysis_job_reservation_safely(
    *,
    job_id: str,
    request_fingerprint: str,
    reservation_token: str,
    acquired: bool,
) -> None:
    if not acquired or not job_id or not request_fingerprint or not reservation_token:
        return
    try:
        release_analysis_job_reservation(
            job_id=job_id,
            request_fingerprint=request_fingerprint,
            reservation_token=reservation_token,
        )
    except (DatabaseError, OSError):
        logger.warning("analysis job reservation release failed")


def _refund_usage_safely(usage: dict[str, object] | None, *, reason: str) -> None:
    if not usage or not usage.get("allowed"):
        return
    try:
        refund_usage_event(usage, reason=reason)
    except (DatabaseError, OSError):
        logger.warning("usage refund failed reason=%s", reason)


def _analysis_job_request_error_response(
    request: HttpRequest,
    *,
    code: str,
    message: str,
) -> JsonResponse:
    return _json_response(
        request,
        {
            "error": {
                "contract_version": "analysis_job_error.v1",
                "type": "validation",
                "code": code,
                "status": 400,
                "message": message,
            }
        },
        status=400,
    )


def _analysis_job_chat_input_rejected_response(
    request: HttpRequest,
    error: ChatInputRejected,
) -> JsonResponse:
    return _json_response(
        request,
        {
            "error": {
                "contract_version": "chat_input_privacy.v1",
                "type": "validation",
                "code": "chat_input_rejected",
                "status": 400,
                "message": error.decision.message,
                "required_action": "remove_sensitive_input",
                "privacy_gateway": error.decision.public_metadata(),
            }
        },
        status=400,
    )


def _analysis_job_conflict_response(request: HttpRequest) -> JsonResponse:
    return _json_response(
        request,
        {
            "error": {
                "contract_version": "analysis_job_error.v1",
                "type": "conflict",
                "code": "analysis_job_id_conflict",
                "status": 409,
                "message": "The analysis job id is already bound to another request.",
            }
        },
        status=409,
    )


def _analysis_job_reservation_pending_response(request: HttpRequest) -> JsonResponse:
    response = _json_response(
        request,
        {
            "error": {
                "contract_version": "analysis_job_error.v1",
                "type": "conflict",
                "code": "analysis_job_reservation_pending",
                "status": 409,
                "message": "The same analysis request is still being prepared. Please retry.",
                "retryable": True,
            }
        },
        status=409,
    )
    response["Retry-After"] = "1"
    return response


def _analysis_job_unavailable_response(request: HttpRequest) -> JsonResponse:
    return _json_response(
        request,
        {
            "error": {
                "contract_version": "analysis_job_error.v1",
                "type": "service_unavailable",
                "code": "analysis_job_unavailable",
                "status": 503,
                "message": "The analysis job could not be queued. Please retry.",
            }
        },
        status=503,
    )


def _analysis_job_replay_payload(job_record: dict[str, object]) -> dict[str, object]:
    analysis_plan = (
        job_record.get("analysis_plan")
        if isinstance(job_record.get("analysis_plan"), dict)
        else {}
    )
    source_work_item = (
        job_record.get("work_item")
        if isinstance(job_record.get("work_item"), dict)
        else {}
    )
    work_item = {
        "contract_version": "agent_worker_queue.v1",
        "work_item_id": source_work_item.get("work_item_id"),
        "status": source_work_item.get("status"),
        "job_id": job_record.get("job_id"),
    }
    status = str(job_record.get("status") or "queued")
    status_counts = (
        job_record.get("status_counts")
        if isinstance(job_record.get("status_counts"), dict)
        else {}
    )
    return {
        "contract_version": "analysis_job_accepted.v1",
        "job_id": job_record.get("job_id"),
        "session_id": job_record.get("session_id"),
        "message_id": job_record.get("message_id"),
        "routing_intent": job_record.get("routing_intent"),
        "status": status,
        "active_node": job_record.get("active_node"),
        "progress_message": job_record.get("progress_message"),
        "analysis_plan_id": job_record.get("analysis_plan_id"),
        "analysis_plan": {
            "plan_id": analysis_plan.get("plan_id"),
            "node_codes": _analysis_plan_executable_node_codes(analysis_plan),
        },
        "node_execution": {
            "execution_mode": "async_worker",
            "status": status,
            "job_id": job_record.get("job_id"),
            "plan_id": job_record.get("analysis_plan_id"),
            "session_id": job_record.get("session_id"),
            "message_id": job_record.get("message_id"),
            "executions": [],
            "status_counts": status_counts,
            "completed_node_codes": [],
        },
        "status_counts": status_counts,
        "execution_mode": "async_worker",
        "persistence": {
            "backend": "postgresql",
            "status": "existing",
            "job_id": job_record.get("job_id"),
            "work_item_id": source_work_item.get("work_item_id"),
            "work_item_status": source_work_item.get("status"),
        },
        "work_item": work_item,
        "usage": {"allowed": True, "replayed": True},
        "idempotent_replay": True,
    }


def _agent_plan_job_payload(body: dict[str, object], response: dict[str, object]) -> dict[str, object]:
    node_execution = response.get("node_execution") if isinstance(response.get("node_execution"), dict) else {}
    chat_response = response.get("chat_response") if isinstance(response.get("chat_response"), dict) else {}
    analysis_plan = response.get("analysis_plan") if isinstance(response.get("analysis_plan"), dict) else {}
    message_id = str(node_execution.get("message_id") or chat_response.get("message_id") or body.get("message_id") or "")
    plan_id = str(node_execution.get("plan_id") or analysis_plan.get("plan_id") or body.get("analysis_plan_id") or "")
    job_id = str(body.get("job_id") or "")
    if not job_id and message_id.startswith("msg_"):
        job_id = f"job_{message_id.removeprefix('msg_')}"
    if not job_id and plan_id.startswith("plan_"):
        job_id = f"job_{plan_id.removeprefix('plan_')}"
    if not job_id:
        job_id = "job_agent_plan"

    progress = chat_response.get("progress") if isinstance(chat_response.get("progress"), dict) else {}
    status = str(chat_response.get("status") or progress.get("status") or "success")
    return {
        **body,
        "job_id": job_id,
        "session_id": node_execution.get("session_id") or chat_response.get("session_id") or body.get("session_id"),
        "message_id": message_id,
        "routing_intent": chat_response.get("routing_intent") or analysis_plan.get("routing_intent"),
        "mock_scenario": chat_response.get("mock_scenario") or body.get("mock_scenario"),
        "status": status,
        "active_node": progress.get("active_node") or "agent_result_validation",
        "progress_message": progress.get("message") or "Supervisor plan execution completed.",
        "analysis_plan_id": plan_id,
        "analysis_plan": analysis_plan,
        "chat_response": chat_response,
        "node_execution": node_execution,
        "status_counts": node_execution.get("status_counts") or {},
        "attachments": chat_response.get("attachments") or body.get("attachments") or [],
        "blocked_attachments": chat_response.get("blocked_attachments") or body.get("blocked_attachments") or [],
        "attachment_scan_policy": chat_response.get("attachment_scan_policy") or body.get("attachment_scan_policy") or {},
        "attachment_resolution": chat_response.get("attachment_resolution") or body.get("attachment_resolution") or {},
        "scan_gate": chat_response.get("scan_gate") or body.get("scan_gate") or {},
        "limitations": chat_response.get("limitations") or [],
    }


def _uses_async_worker(body: dict[str, object]) -> bool:
    return body.get("execution_mode") == "async_worker" or body.get("async_worker") is True


def _analysis_plan_requires_persisted_reporting(analysis_plan: object) -> bool:
    return "objection_report_generation" in _analysis_plan_executable_node_codes(
        analysis_plan
    )


def _worker_report_action_required_response(request: HttpRequest) -> JsonResponse:
    return _json_response(
        request,
        {
            "error": {
                "contract_version": "consultation_report_error.v2",
                "type": "report",
                "code": "worker_report_action_required",
                "status": 409,
                "message": "분석 워커가 생성한 리포트의 조회 또는 다운로드 API를 사용해 주세요.",
                "required_action": "use_persisted_worker_report",
            }
        },
        status=409,
    )


def _canonical_report_action_access_response(
    request: HttpRequest,
    payload: dict[str, object],
) -> JsonResponse | None:
    """Preserve object-level authorization even though POST generation is disabled."""

    resource_checks = (
        (get_report_access_metadata(str(payload.get("report_id") or "")), True),
        (get_analysis_job_access_metadata(str(payload.get("job_id") or "")), False),
        (get_case_access_metadata(str(payload.get("case_id") or "")), False),
        (get_chat_session_access_metadata(str(payload.get("session_id") or "")), False),
    )
    for resource, is_report in resource_checks:
        if resource is None:
            continue
        access = (
            authorize_report_download_metadata(resource, payload)
            if is_report
            else authorize_resource_access(resource, payload)
        )
        if not access["allowed"]:
            return _object_access_denied_response(request, access)
    return None


def _analysis_plan_active_node(analysis_plan: object) -> str:
    node_codes = _analysis_plan_executable_node_codes(analysis_plan)
    return node_codes[0] if node_codes else ""


def _analysis_plan_executable_node_codes(analysis_plan: object) -> list[str]:
    if not isinstance(analysis_plan, dict):
        return []
    return [
        str(step["node_code"])
        for step in executable_analysis_plan_steps(analysis_plan)
        if step.get("node_code")
    ]


def _queued_node_execution_placeholder(
    body: dict[str, object],
    *,
    analysis_plan: object,
    chat_response: dict[str, object] | None,
) -> dict[str, object]:
    chat_response = chat_response or {}
    plan_id = analysis_plan.get("plan_id") if isinstance(analysis_plan, dict) else body.get("analysis_plan_id")
    message_id = str(chat_response.get("message_id") or body.get("message_id") or "")
    job_id = str(body.get("job_id") or "")
    if not job_id and message_id.startswith("msg_"):
        job_id = f"job_{message_id.removeprefix('msg_')}"
    if not job_id and isinstance(plan_id, str) and plan_id.startswith("plan_"):
        job_id = f"job_{plan_id.removeprefix('plan_')}"
    if not job_id:
        job_id = "job_agent_plan"
    queued_node_codes = _analysis_plan_executable_node_codes(analysis_plan)
    return {
        "execution_mode": "async_worker",
        "status": "queued",
        "job_id": job_id,
        "plan_id": plan_id,
        "session_id": chat_response.get("session_id") or body.get("session_id"),
        "message_id": message_id,
        "executions": [],
        "status_counts": {"queued": len(queued_node_codes)},
        "completed_node_codes": [],
    }


def _supervisor_execution_response(
    node_execution: dict[str, object] | None,
    *,
    persistence: dict[str, object],
) -> dict[str, object]:
    node_execution = node_execution or {}
    node_results = []
    for execution in node_execution.get("executions", []):
        if not isinstance(execution, dict):
            continue
        agent_output = execution.get("agent_output") if isinstance(execution.get("agent_output"), dict) else {}
        adapter_context = execution.get("adapter_context") if isinstance(execution.get("adapter_context"), dict) else {}
        node = execution.get("node") if isinstance(execution.get("node"), dict) else {}
        plan_step = execution.get("plan_step") if isinstance(execution.get("plan_step"), dict) else {}
        node_results.append(
            {
                "execution_id": execution.get("execution_id"),
                "node_code": agent_output.get("node_code") or execution.get("node_code"),
                "node_name": agent_output.get("node_name"),
                "node_type": agent_output.get("node_type"),
                "owner": agent_output.get("owner"),
                "execution_mode": execution.get("execution_mode") or adapter_context.get("execution_mode") or "mock",
                "adapter_execution_mode": adapter_context.get("execution_mode") or execution.get("execution_mode") or "mock",
                "adapter_modes": node.get("adapter_modes") or ["mock"],
                "plan_step": {
                    "order": plan_step.get("order"),
                    "status": plan_step.get("status"),
                    "fallback": plan_step.get("fallback"),
                    "depends_on": plan_step.get("depends_on") or [],
                },
                "status": agent_output.get("status"),
                "summary": agent_output.get("summary"),
                "structured_result": agent_output.get("structured_result") or {},
                "evidence": agent_output.get("evidence") or [],
                "next_actions": agent_output.get("next_actions") or [],
                "limitations": agent_output.get("limitations") or [],
            }
        )

    return {
        "contract_version": "supervisor_execution.v1",
        "orchestration_mode": "background_session",
        "execution_mode": node_execution.get("execution_mode") or "mock",
        "job_id": persistence.get("job_id") or node_execution.get("job_id"),
        "ai_session_id": persistence.get("ai_session_id"),
        "plan_id": node_execution.get("plan_id"),
        "session_id": node_execution.get("session_id"),
        "message_id": node_execution.get("message_id"),
        "status_counts": node_execution.get("status_counts") or {},
        "agent_results_saved": persistence.get("agent_results_saved", 0),
        "agent_invocations_saved": persistence.get("agent_invocations_saved", 0),
        "work_item": (
            {
                "contract_version": "agent_worker_queue.v1",
                "work_item_id": persistence.get("work_item_id"),
                "status": persistence.get("work_item_status") or persistence.get("status"),
                "job_id": persistence.get("job_id") or node_execution.get("job_id"),
            }
            if persistence.get("work_item_id")
            else None
        ),
        "node_results": node_results,
    }


def _record_history_safely(request: HttpRequest, **kwargs: object) -> dict[str, object] | None:
    try:
        if _is_canonical_mock_request(request):
            metadata = kwargs.get("metadata")
            if isinstance(metadata, dict) and metadata.get("conversation_save_state") in {"pending", "session_only"}:
                return None
            return record_history_event_record(**kwargs)
        return record_sidecar_history_event(**kwargs)
    except (DatabaseError, OSError):
        return None


def _record_agent_events_safely(
    request: HttpRequest,
    executions: list[dict[str, object]],
    *,
    actor: dict[str, object],
    source: dict[str, object],
    subject: dict[str, object],
) -> None:
    try:
        if _is_canonical_mock_request(request):
            record_agent_history_event_records(executions, actor=actor, source=source, subject=subject)
        else:
            record_sidecar_agent_execution_events(executions, actor=actor, source=source, subject=subject)
    except (DatabaseError, OSError):
        return


def _positive_int(value: object, *, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default

