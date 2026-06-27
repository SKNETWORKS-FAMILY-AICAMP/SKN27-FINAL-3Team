"""Django views that expose the mid-demo mock chatbot service."""

from __future__ import annotations

import json
from typing import Any

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
    list_analysis_jobs,
)
from app.services.attachment_mock_service import (
    get_attachment,
    list_attachments,
    register_attachment,
)
from app.services.chatbot_mock_service import (
    create_session,
    list_demo_scenarios,
    perform_report_action,
    submit_message,
)


MOCK_TO_CANONICAL_PATH_PREFIXES = (
    ("/api/mock/analysis/jobs/", "/api/analysis/jobs/"),
    ("/api/mock/agents/nodes/run/", "/api/agents/nodes/run/"),
    ("/api/mock/agents/plans/run/", "/api/agents/plans/run/"),
    ("/api/mock/attachments/", "/api/files/"),
    ("/api/mock/reports/", "/api/reports/"),
    ("/api/mock/chat/sessions/", "/api/chat/sessions/"),
    ("/api/mock/chat/messages/", "/api/chat/messages/"),
    ("/api/mock/analysis/jobs", "/api/analysis/jobs"),
    ("/api/mock/agents/nodes/run", "/api/agents/nodes/run"),
    ("/api/mock/agents/plans/run", "/api/agents/plans/run"),
    ("/api/mock/attachments", "/api/files"),
    ("/api/mock/reports", "/api/reports"),
    ("/api/mock/chat/sessions", "/api/chat/sessions"),
    ("/api/mock/chat/messages", "/api/chat/messages"),
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


@require_http_methods(["GET", "OPTIONS"])
def agent_nodes(request: HttpRequest) -> JsonResponse:
    return _json_response(request, {"nodes": list_agent_nodes()})


@csrf_exempt
@require_http_methods(["GET", "POST", "OPTIONS"])
def attachments(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        return _json_response(request, {"attachments": list_attachments(session_id=request.GET.get("session_id"))})

    payload = _request_payload(request)
    upload_file = _first_upload_file(request)
    return _json_response(request, {"attachment": register_attachment(payload, upload_file=upload_file)})


@require_http_methods(["GET", "OPTIONS"])
def attachment_detail(request: HttpRequest, attachment_id: str) -> JsonResponse:
    attachment = get_attachment(attachment_id)
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
    return _json_response(request, {"job": create_analysis_job(body)})


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


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def create_chat_session(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    return _json_response(request, create_session(user_id=body.get("user_id")))


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def submit_chat_message(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    return _json_response(request, submit_message(body))


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def run_agent_node(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    return _json_response(request, execute_mock_node(body))


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
    return _json_response(request, response)


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def report_action(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    return _json_response(request, perform_report_action(body))


@require_http_methods(["GET", "OPTIONS"])
def download_report(request: HttpRequest, report_id: str) -> HttpResponse:
    response = HttpResponse(
        f"Mock report download for {report_id}\n",
        content_type="text/plain; charset=utf-8",
    )
    response["Content-Disposition"] = f'attachment; filename="{report_id}.txt"'
    if _is_canonical_mock_request(request):
        response["X-API-Surface"] = "canonical_mock"
        response["X-Execution-Mode"] = "mock"
    return response


def _json_response(request: HttpRequest, data: dict[str, Any], status: int = 200) -> JsonResponse:
    response_data = dict(data)
    if _is_canonical_mock_request(request):
        response_data = _canonicalize_mock_paths(response_data)
        response_data.setdefault("api_surface", "canonical_mock")
        response_data.setdefault("execution_mode", "mock")
    return JsonResponse(response_data, status=status)


def _is_canonical_mock_request(request: HttpRequest) -> bool:
    return request.path.startswith("/api/") and not request.path.startswith("/api/mock/")


def _canonicalize_mock_paths(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonicalize_mock_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonicalize_mock_paths(item) for item in value]
    if isinstance(value, str):
        for mock_prefix, canonical_prefix in MOCK_TO_CANONICAL_PATH_PREFIXES:
            if value.startswith(mock_prefix):
                return value.replace(mock_prefix, canonical_prefix, 1)
    return value


def _json_body(request: HttpRequest) -> dict[str, Any]:
    raw_body = request.body or b"{}"
    try:
        return json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        return {}


def _request_payload(request: HttpRequest) -> dict[str, Any]:
    if request.content_type and request.content_type.startswith("multipart/"):
        return {key: request.POST.get(key) for key in request.POST}
    if request.content_type and request.content_type.startswith("application/x-www-form-urlencoded"):
        return {key: request.POST.get(key) for key in request.POST}
    return _json_body(request)


def _first_upload_file(request: HttpRequest) -> Any | None:
    if not request.FILES:
        return None
    return request.FILES.get("file") or next(iter(request.FILES.values()))

