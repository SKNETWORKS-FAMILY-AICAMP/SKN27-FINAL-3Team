"""Django views that expose the mid-demo mock chatbot service."""

from __future__ import annotations

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
    list_history_events,
    record_agent_execution_events,
    record_history_event,
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
    get_mycase_summary,
    get_report_download_metadata,
    get_uploaded_file,
    list_uploaded_files,
    persist_analysis_display_result,
    persist_analysis_job_execution,
    persist_chat_message_analysis_boundary,
    persist_report_action,
    register_uploaded_file,
)


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
    _record_history_safely(
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
    _record_history_safely(
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
    events = list_history_events(
        session_id=request.GET.get("session_id"),
        user_id=request.GET.get("user_id"),
        guest_id=request.GET.get("guest_id"),
        job_id=request.GET.get("job_id"),
        event_type=request.GET.get("event_type"),
        limit=_positive_int(request.GET.get("limit"), default=100),
    )
    return _json_response(
        request,
        {
            "history_contract": HISTORY_EVENT_VERSION,
            "storage": {
                "backend": "mock_sidecar_json",
                "policy": "standard_light",
            },
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
    owner_id = request.GET.get("owner_id") or request.GET.get("user_id")
    summary = get_mycase_summary(
        session_id=request.GET.get("session_id"),
        owner_id=owner_id,
        limit=_positive_int(request.GET.get("limit"), default=10),
    )
    return _json_response(request, summary)


@require_http_methods(["GET", "OPTIONS"])
def agent_nodes(request: HttpRequest) -> JsonResponse:
    return _json_response(request, {"nodes": list_agent_nodes()})


@csrf_exempt
@require_http_methods(["GET", "POST", "OPTIONS"])
def attachments(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        if _is_canonical_mock_request(request):
            attachments_payload = list_uploaded_files(session_id=request.GET.get("session_id"))
        else:
            attachments_payload = list_mock_attachments(session_id=request.GET.get("session_id"))
        return _json_response(request, {"attachments": attachments_payload})

    payload = _request_payload(request)
    upload_file = _first_upload_file(request)
    if _is_canonical_mock_request(request):
        attachment = register_uploaded_file(payload, upload_file=upload_file)
    else:
        attachment = register_mock_attachment(payload, upload_file=upload_file)
    return _json_response(request, {"attachment": attachment})


@require_http_methods(["GET", "OPTIONS"])
def attachment_detail(request: HttpRequest, attachment_id: str) -> JsonResponse:
    if _is_canonical_mock_request(request):
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
    job = create_analysis_job(body)
    if _is_canonical_mock_request(request):
        job["persistence"] = persist_analysis_job_execution(body, job)
    actor = _history_actor(request, body)
    source = _history_source(request)
    subject = subject_from_payload(
        body,
        session_id=job.get("session_id"),
        message_id=job.get("message_id"),
        job_id=job.get("job_id"),
    )
    _record_history_safely(
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
    chat_response = submit_message(body)
    if _is_canonical_mock_request(request):
        persist_chat_message_analysis_boundary(body, chat_response)
    _record_history_safely(
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
    report = perform_report_action(body)
    if _is_canonical_mock_request(request):
        report = _canonicalize_mock_paths(report)
        report["persistence"] = persist_report_action(body, report)
    _record_history_safely(
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


def _record_history_safely(**kwargs: object) -> dict[str, object] | None:
    try:
        return record_history_event(**kwargs)
    except OSError:
        return None


def _record_agent_events_safely(
    executions: list[dict[str, object]],
    *,
    actor: dict[str, object],
    source: dict[str, object],
    subject: dict[str, object],
) -> None:
    try:
        record_agent_execution_events(executions, actor=actor, source=source, subject=subject)
    except OSError:
        return


def _positive_int(value: object, *, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default

