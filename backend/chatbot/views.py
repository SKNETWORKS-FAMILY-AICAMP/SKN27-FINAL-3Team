"""Django views that expose the mid-demo mock chatbot service."""

from __future__ import annotations

from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
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
from app.services.google_auth_service import (
    create_google_code_login as _create_google_code_login,
    create_google_login as _create_google_login,
    create_logout as _create_logout,
    create_token_refresh as _create_token_refresh,
)
from app.services.chatbot_mock_service import (
    create_session,
    list_demo_personas,
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
from chatbot.file_scan_service import apply_attachment_scan_gate, scan_uploaded_file
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
    conversation_save_state_from_payload,
    get_chat_session_access_metadata,
    get_mycase_summary,
    get_report_download_metadata,
    get_uploaded_file_access_metadata,
    get_uploaded_file,
    history_operating_policy,
    list_history_event_records,
    list_uploaded_files,
    mark_conversation_save_state,
    enqueue_analysis_job_work,
    process_agent_work_items,
    persist_current_auth_subject,
    persist_auth_logout,
    persist_auth_token_refresh,
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
from chatbot.models import GuestIdentity, GuestIdentityStatus, UploadedFile
from chatbot.progress_cache import read_analysis_job_progress, read_chat_session_state


@require_http_methods(["GET", "OPTIONS"])
def health_check(_request: HttpRequest) -> JsonResponse:
    return JsonResponse(
        {
            "ok": True,
            "service": "SKN27 demo backend",
            "available_scenarios": list_demo_scenarios(),
            "available_personas": list_demo_personas(),
        }
    )


@require_http_methods(["GET", "OPTIONS"])
def demo_scenarios(_request: HttpRequest) -> JsonResponse:
    return JsonResponse({"scenarios": list_demo_scenarios(), "personas": list_demo_personas()})


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


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def auth_login(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    status, payload = _create_google_login(body)
    if status < 400:
        payload["persistence"] = persist_current_auth_subject(
            payload,
            session_id=body.get("session_id"),
        )
    _record_history_safely(
        request,
        event_type="auth_login_completed",
        status="success" if status < 400 else "failed",
        summary="Google login boundary was processed.",
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
def auth_google_code(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    status, payload = _create_google_code_login(
        body,
        request_headers=dict(request.headers.items()),
    )
    if status < 400:
        payload["persistence"] = persist_current_auth_subject(
            payload,
            session_id=body.get("session_id"),
        )
    _strip_private_oauth_payload(payload)
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


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def auth_refresh(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    status, payload = _create_token_refresh(
        authorization_header=request.headers.get("Authorization"),
        payload=body,
    )
    if status < 400:
        payload["persistence"] = persist_auth_token_refresh(
            payload,
            session_id=body.get("session_id"),
        )
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
    upload_file = _first_upload_file(request)
    if _is_canonical_mock_request(request):
        identity_payload = _payload_with_request_identity(request, payload)
        policy_response = _canonical_guest_identity_policy_response(request, identity_payload)
        if policy_response is not None:
            return policy_response
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
@require_http_methods(["POST", "OPTIONS"])
def process_file_scan(request: HttpRequest, attachment_id: str) -> JsonResponse:
    body = _json_body(request)
    identity_payload = _request_access_payload(request, session_id=body.get("session_id"))
    access_metadata = get_uploaded_file_access_metadata(attachment_id)
    if access_metadata is not None:
        access = authorize_resource_access(access_metadata, identity_payload)
        if not access["allowed"]:
            return _object_access_denied_response(request, access)

    uploaded_file = UploadedFile.objects.filter(attachment_id=attachment_id).first()
    if uploaded_file is None:
        return _json_response(
            request,
            {
                "error": {
                    "code": "attachment_not_found",
                    "message": "?붿껌??attachment metadata瑜?李얠쓣 ???놁뒿?덈떎.",
                }
            },
            status=404,
        )

    scan_result = scan_uploaded_file(uploaded_file)
    return _json_response(
        request,
        {
            "contract_version": "file_scan_endpoint.v1",
            "file_scan": scan_result,
            "attachment": get_uploaded_file(attachment_id),
        },
    )


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
        identity_body = apply_attachment_scan_gate(identity_body)
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
        policy_response = _canonical_guest_identity_policy_response(request, identity_body)
        if policy_response is not None:
            return policy_response
        usage = record_usage_event(identity_body, scope="chat_message")
        if not usage["allowed"]:
            return _rate_limit_response(request, usage)
        identity_body = apply_attachment_scan_gate(identity_body)
    chat_response = submit_message(identity_body)
    conversation_save_state = conversation_save_state_from_payload(identity_body)
    node_execution = None
    if _is_canonical_mock_request(request):
        execution_payload = {
            **identity_body,
            "session_id": chat_response.get("session_id"),
            "message_id": chat_response.get("message_id"),
            "attachments": chat_response.get("attachments", []),
            "context": {
                **(
                    identity_body.get("context")
                    if isinstance(identity_body.get("context"), dict)
                    else {}
                ),
                "supervisor_handoff": chat_response.get("supervisor_state", {}),
            },
        }
        if _uses_async_worker(identity_body):
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
            persistence = enqueue_analysis_job_work(execution_payload, job_payload)
            conversation_save_state = conversation_save_state_from_payload(identity_body)
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
            chat_response["status"] = "queued"
        else:
            persistence_seed = persist_chat_message_analysis_boundary(identity_body, chat_response)
            execution_payload["job_id"] = persistence_seed["job_id"]
            node_execution = execute_mock_plan(chat_response.get("analysis_plan") or {}, execution_payload)
            persistence = persist_chat_message_analysis_boundary(
                identity_body,
                chat_response,
                node_execution=node_execution,
            )
            conversation_save_state = persistence["conversation_save_state"]
            chat_response["persistence"] = persistence
            chat_response["supervisor_execution"] = _supervisor_execution_response(
                node_execution,
                persistence=persistence,
            )
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
    return _json_response(request, chat_response)


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
                message="상담을 내 사건으로 저장하려면 로그인이 필요합니다.",
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
        if _uses_async_worker(execution_payload):
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

        response["node_execution"] = execute_mock_plan(analysis_plan, execution_payload)
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
        response["node_execution"] = execute_mock_plan(analysis_plan, execution_payload)
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
@require_http_methods(["POST", "OPTIONS"])
def report_action(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    identity_body = _payload_with_request_identity(request, body) if _is_canonical_mock_request(request) else body
    subject = access_subject_from_payload(identity_body)["subject"]
    action = str(body.get("action") or identity_body.get("action") or "save").lower()
    usage = None
    if _is_canonical_mock_request(request):
        guest_violation = _guest_identity_policy_violation(subject)
        if guest_violation:
            return _guest_identity_policy_response(request, guest_violation)
        if action in {"save", "download"} and subject.get("subject_type") != "user":
            return _login_required_response(
                request,
                action=f"report_{action}",
                reason=f"guest_report_{action}_requires_login",
                message="리포트를 저장하거나 다운로드하려면 로그인이 필요합니다.",
                policy_version="report_action_policy.v1",
                subject=subject,
            )
        usage = record_usage_event(identity_body, scope="report_action")
        if not usage["allowed"]:
            return _rate_limit_response(request, usage)
    report = perform_report_action(identity_body)
    if _is_canonical_mock_request(request):
        report = _canonicalize_mock_paths(report)
        if action in {"preview", "prepare"}:
            report["persistence"] = {
                "backend": "postgresql",
                "table": "reports",
                "status": "skipped",
                "reason": "preview_not_persisted",
                "policy_version": "report_action_policy.v1",
            }
            report["object_storage"] = None
        else:
            report["persistence"] = persist_report_action(identity_body, report)
            report["object_storage"] = report["persistence"].get("object_storage")
        report["usage"] = usage
    _record_history_safely(
        request,
        event_type=_report_history_event_type(action),
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
                message="리포트를 다운로드하려면 로그인이 필요합니다.",
                policy_version="report_action_policy.v1",
                subject=subject,
            )
        download = get_report_download_metadata(report_id)
        if download is not None:
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
            response["X-Report-Object-Key"] = download["object_key"]
            response["X-Report-Object-Policy"] = download["object_storage"].get("policy_version", "")
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
                "message": "비회원 세션이 만료되었거나 사용할 수 없습니다.",
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
                "message": "리포트 다운로드 권한이 없습니다.",
                "required_action": "login_or_owner_match",
                "access": access,
            }
        },
        status=403,
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
    }


def _uses_async_worker(body: dict[str, object]) -> bool:
    return body.get("execution_mode") == "async_worker" or body.get("async_worker") is True


def _analysis_plan_active_node(analysis_plan: object) -> str:
    if not isinstance(analysis_plan, dict):
        return ""
    steps = analysis_plan.get("steps") if isinstance(analysis_plan.get("steps"), list) else []
    for step in steps:
        if isinstance(step, dict) and step.get("node_code"):
            return str(step["node_code"])
    return ""


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
    return {
        "execution_mode": "async_worker",
        "status": "queued",
        "job_id": job_id,
        "plan_id": plan_id,
        "session_id": chat_response.get("session_id") or body.get("session_id"),
        "message_id": message_id,
        "executions": [],
        "status_counts": {"queued": 1},
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

