"""Django views that expose the mid-demo mock chatbot service."""

from __future__ import annotations

from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from app.services.agent_node_service import (
    execute_mock_node,
    execute_mock_plan,
    list_agent_nodes,
)
from app.services.analysis_job_mock_service import (
    create_analysis_job,
    get_analysis_job,
    get_analysis_result,
    list_analysis_jobs,
)
from app.services.attachment_mock_service import (
    get_attachment as get_mock_attachment,
    list_attachments as list_mock_attachments,
    register_attachment as register_mock_attachment,
)
from app.services.auth_session_mock_service import (
    create_guest_session as _create_guest_session,
    get_current_auth_subject as _get_current_auth_subject,
)
from app.services.auth_error_contract import build_www_authenticate_header
from app.services.chatbot_mock_service import (
    create_session,
    list_demo_scenarios,
    perform_report_action,
    submit_message,
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
    canonicalize_mock_paths as _canonicalize_mock_paths,
    is_canonical_mock_request as _is_canonical_mock_request,
    json_response as _json_response,
)
from chatbot.request_parsing import (
    first_upload_file as _first_upload_file,
    json_body as _json_body,
    request_payload as _request_payload,
)
from chatbot.repositories import (
    access_subject_from_payload,
    authorize_resource_access,
    authorize_report_download_metadata,
    build_history_after_service_summary,
    get_chat_session_access_metadata,
    get_mycase_summary,
    get_report_download_metadata,
    get_uploaded_file_access_metadata,
    get_uploaded_file,
    history_operating_policy,
    list_history_event_records,
    list_uploaded_files,
    persist_current_auth_subject,
    persist_analysis_display_result,
    persist_analysis_job_execution,
    persist_chat_message_analysis_boundary,
    persist_guest_session_identity,
    record_agent_history_event_records,
    record_history_event_record,
    persist_report_action,
    record_usage_event,
    register_uploaded_file,
)
from chatbot.progress_cache import read_analysis_job_progress, read_chat_session_state


@require_http_methods(["GET", "OPTIONS"])
def health_check(_request: HttpRequest) -> JsonResponse:
    return JsonResponse(
        {
            "ok": True,
            "service": "SKN27 demo backend",
            "available_scenarios": list_demo_scenarios(),
        }
    )


@require_http_methods(["GET", "OPTIONS"])
def demo_scenarios(_request: HttpRequest) -> JsonResponse:
    return JsonResponse({"scenarios": list_demo_scenarios()})


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
        summary="비회원 guest session을 mock 발급했습니다.",
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


@require_http_methods(["GET", "OPTIONS"])
def auth_me(request: HttpRequest) -> JsonResponse:
    status, payload = _get_current_auth_subject(
        authorization_header=request.headers.get("Authorization"),
        guest_id=request.headers.get("X-Guest-Id") or request.GET.get("guest_id"),
        session_id=request.GET.get("session_id"),
    )
    if status < 400:
        payload["persistence"] = persist_current_auth_subject(
            payload,
            session_id=request.GET.get("session_id"),
        )
    _record_history_safely(
        request,
        event_type="auth_me_checked",
        status="success" if status < 400 else "failed",
        summary="현재 인증 subject를 mock 확인했습니다.",
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
                "사용자 원문, OCR 원문, Agent reasoning 전문은 standard-light history에 저장하지 않습니다.",
                "보관 기간과 DB table 전환은 사용자 컨펌 후 확정합니다.",
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
    return _json_response(request, {"nodes": list_agent_nodes()})


@csrf_exempt
@require_http_methods(["GET", "POST", "OPTIONS"])
def attachments(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        if _is_canonical_mock_request(request):
            identity_payload = _request_access_payload(request, session_id=request.GET.get("session_id"))
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
    upload_file = _first_upload_file(request)
    if _is_canonical_mock_request(request):
        identity_payload = _payload_with_request_identity(request, payload)
        usage = record_usage_event(identity_payload, scope="file_upload")
        if not usage["allowed"]:
            return _rate_limit_response(request, usage)
        attachment = register_uploaded_file(identity_payload, upload_file=upload_file)
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
                    "message": "요청한 attachment metadata를 찾을 수 없습니다.",
                }
            },
            status=404,
        )
    return _json_response(request, {"attachment": attachment})


@csrf_exempt
@require_http_methods(["GET", "POST", "OPTIONS"])
def analysis_jobs(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        return _json_response(request, {"jobs": list_analysis_jobs(session_id=request.GET.get("session_id"))})

    body = _json_body(request)
    identity_body = _payload_with_request_identity(request, body) if _is_canonical_mock_request(request) else body
    usage = None
    if _is_canonical_mock_request(request):
        usage = record_usage_event(identity_body, scope="agent_run")
        if not usage["allowed"]:
            return _rate_limit_response(request, usage)
    job = create_analysis_job(identity_body)
    if _is_canonical_mock_request(request):
        job["persistence"] = persist_analysis_job_execution(
            identity_body,
            job,
        )
        job["usage"] = usage
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
        summary="분석 job을 mock 생성했습니다.",
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
    _record_agent_events_safely(
        request,
        job.get("node_execution", {}).get("executions", []),
        actor=actor,
        source=source,
        subject=subject,
    )
    return _json_response(request, {"job": job})


@require_http_methods(["GET", "OPTIONS"])
def analysis_job_detail(request: HttpRequest, job_id: str) -> JsonResponse:
    job = get_analysis_job(job_id)
    if not job:
        return _json_response(
            request,
            {
                "error": {
                    "code": "analysis_job_not_found",
                    "message": "요청한 analysis job을 찾을 수 없습니다.",
                }
            },
            status=404,
        )
    if _is_canonical_mock_request(request):
        job["progress_cache"] = read_analysis_job_progress(job_id)
    return _json_response(request, {"job": job})


@require_http_methods(["GET", "OPTIONS"])
def analysis_result(request: HttpRequest, job_id: str) -> JsonResponse:
    result = get_analysis_result(job_id)
    if not result:
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
    if _is_canonical_mock_request(request):
        result = _canonicalize_mock_paths(result)
        result["persistence"] = persist_analysis_display_result(result)
    return _json_response(request, {"result": result})


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def create_chat_session(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    payload = create_session(user_id=body.get("user_id"))
    _record_history_safely(
        request,
        event_type="chat_session_created",
        status="success",
        summary="채팅 session을 mock 생성했습니다.",
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
    identity_body = _payload_with_request_identity(request, body) if _is_canonical_mock_request(request) else body
    usage = None
    if _is_canonical_mock_request(request):
        usage = record_usage_event(identity_body, scope="chat_message")
        if not usage["allowed"]:
            return _rate_limit_response(request, usage)
    chat_response = submit_message(identity_body)
    if _is_canonical_mock_request(request):
        persist_chat_message_analysis_boundary(identity_body, chat_response)
        chat_response["usage"] = usage
    _record_history_safely(
        request,
        event_type="chat_message_created",
        status=chat_response.get("status") or "success",
        summary="채팅 메시지를 mock 분석 응답으로 처리했습니다.",
        actor=_history_actor(request, body),
        subject=subject_from_payload(
            body,
            session_id=chat_response.get("session_id"),
            message_id=chat_response.get("message_id"),
        ),
        source=_history_source(request),
        metadata={
            "routing_intent": chat_response.get("routing_intent"),
            "mock_scenario": chat_response.get("mock_scenario"),
            "mock_status": body.get("mock_status"),
            "response_status": chat_response.get("status"),
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
    return _json_response(request, chat_response)


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def run_agent_node(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    node_execution = execute_mock_node(body)
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
    chat_response = None
    analysis_plan = body.get("analysis_plan")
    if not analysis_plan:
        chat_response = submit_message(body)
        analysis_plan = chat_response["analysis_plan"]

    response = {
        "analysis_plan": analysis_plan,
        "node_execution": execute_mock_plan(analysis_plan, body),
    }
    if chat_response:
        response["chat_response"] = chat_response
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
def report_action(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    identity_body = _payload_with_request_identity(request, body) if _is_canonical_mock_request(request) else body
    usage = None
    if _is_canonical_mock_request(request):
        usage = record_usage_event(identity_body, scope="report_action")
        if not usage["allowed"]:
            return _rate_limit_response(request, usage)
    report = perform_report_action(identity_body)
    if _is_canonical_mock_request(request):
        report = _canonicalize_mock_paths(report)
        report["persistence"] = persist_report_action(identity_body, report)
        report["usage"] = usage
    _record_history_safely(
        request,
        event_type="report_downloaded" if body.get("action") == "download" else "report_saved",
        status=report.get("status") or "success",
        summary="리포트 action을 mock 처리했습니다.",
        actor=_history_actor(request, body),
        subject=subject_from_payload(
            body,
            session_id=body.get("session_id"),
            job_id=body.get("job_id"),
            report_id=report.get("report_id"),
        ),
        source=_history_source(request),
        metadata={
            "action": body.get("action") or "save",
            "report_status": report.get("status"),
            "has_download_url": bool(report.get("download_url")),
        },
        privacy={"risk_level": "medium"},
    )
    return _json_response(request, report)


@require_http_methods(["GET", "OPTIONS"])
def download_report(request: HttpRequest, report_id: str) -> HttpResponse:
    if _is_canonical_mock_request(request):
        download = get_report_download_metadata(report_id)
        if download is not None:
            identity_payload = _request_access_payload(request, session_id=request.GET.get("session_id"))
            access = authorize_report_download_metadata(download, identity_payload)
            if not access["allowed"]:
                return _object_access_denied_response(request, access)
            response = HttpResponse(
                download["body"],
                content_type=download["content_type"],
            )
            response["Content-Disposition"] = f'attachment; filename="{download["filename"]}"'
            response["X-API-Surface"] = "canonical_mock"
            response["X-Execution-Mode"] = "mock"
            response["X-Report-Persistence"] = "postgresql"
            response["X-Report-Storage-Backend"] = download["storage_backend"]
            response["X-Report-Storage-URI"] = download["storage_uri"]
            response["X-Report-Access-Decision"] = access["reason"]
            return response

    response = HttpResponse(
        f"Mock report download for {report_id}\n",
        content_type="text/plain; charset=utf-8",
    )
    response["Content-Disposition"] = f'attachment; filename="{report_id}.txt"'
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
    auth_context = (
        dict(payload.get("auth_context"))
        if isinstance(payload.get("auth_context"), dict)
        else {}
    )
    status, auth_payload = _get_current_auth_subject(
        authorization_header=request.headers.get("Authorization"),
        guest_id=request.headers.get("X-Guest-Id") or auth_context.get("guest_id"),
        session_id=enriched.get("session_id") or auth_context.get("session_id"),
    )
    if status < 400:
        subject = auth_payload.get("subject") if isinstance(auth_payload.get("subject"), dict) else {}
        for key in ("subject_id", "subject_type", "user_id", "guest_id", "auth_session_id"):
            value = subject.get(key)
            if value:
                auth_context.setdefault(key, value)
        if subject.get("user_id") and not enriched.get("owner_id") and not enriched.get("user_id"):
            enriched["user_id"] = subject["user_id"]
    elif request.headers.get("X-Guest-Id"):
        auth_context.setdefault("guest_id", request.headers["X-Guest-Id"])

    if request.headers.get("X-Auth-Session-Id"):
        auth_context.setdefault("auth_session_id", request.headers["X-Auth-Session-Id"])
    if auth_context:
        enriched["auth_context"] = auth_context
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
                "message": "요청 한도를 초과했습니다.",
                "required_action": required_action,
                "usage": usage,
            }
        },
        status=429,
    )


def _object_access_denied_response(request: HttpRequest, access: dict[str, object]) -> JsonResponse:
    return _json_response(
        request,
        {
            "error": {
                "contract_version": "object_access.v1",
                "type": "object_access",
                "code": "object_access_denied",
                "status": 403,
                "message": "리포트 다운로드 권한이 없습니다.",
                "required_action": "login_or_owner_match",
                "access": access,
            }
        },
        status=403,
    )


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


def _record_history_safely(request: HttpRequest, **kwargs: object) -> dict[str, object] | None:
    try:
        if _is_canonical_mock_request(request):
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

