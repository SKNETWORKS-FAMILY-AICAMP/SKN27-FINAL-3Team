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
def agent_nodes(_request: HttpRequest) -> JsonResponse:
    return JsonResponse({"nodes": list_agent_nodes()})


@csrf_exempt
@require_http_methods(["GET", "POST", "OPTIONS"])
def attachments(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        return JsonResponse({"attachments": list_attachments(session_id=request.GET.get("session_id"))})

    payload = _request_payload(request)
    upload_file = _first_upload_file(request)
    return JsonResponse({"attachment": register_attachment(payload, upload_file=upload_file)})


@require_http_methods(["GET", "OPTIONS"])
def attachment_detail(_request: HttpRequest, attachment_id: str) -> JsonResponse:
    attachment = get_attachment(attachment_id)
    if not attachment:
        return JsonResponse(
            {
                "error": {
                    "code": "attachment_not_found",
                    "message": "요청한 attachment metadata를 찾을 수 없습니다.",
                }
            },
            status=404,
        )
    return JsonResponse({"attachment": attachment})


@csrf_exempt
@require_http_methods(["GET", "POST", "OPTIONS"])
def analysis_jobs(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        return JsonResponse({"jobs": list_analysis_jobs(session_id=request.GET.get("session_id"))})

    body = _json_body(request)
    return JsonResponse({"job": create_analysis_job(body)})


@require_http_methods(["GET", "OPTIONS"])
def analysis_job_detail(_request: HttpRequest, job_id: str) -> JsonResponse:
    job = get_analysis_job(job_id)
    if not job:
        return JsonResponse(
            {
                "error": {
                    "code": "analysis_job_not_found",
                    "message": "요청한 analysis job을 찾을 수 없습니다.",
                }
            },
            status=404,
        )
    return JsonResponse({"job": job})


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def create_chat_session(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    return JsonResponse(create_session(user_id=body.get("user_id")))


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def submit_chat_message(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    return JsonResponse(submit_message(body))


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def run_agent_node(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    return JsonResponse(execute_mock_node(body))


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
    return JsonResponse(response)


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def report_action(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    return JsonResponse(perform_report_action(body))


@require_http_methods(["GET", "OPTIONS"])
def download_report(_request: HttpRequest, report_id: str) -> HttpResponse:
    response = HttpResponse(
        f"Mock report download for {report_id}\n",
        content_type="text/plain; charset=utf-8",
    )
    response["Content-Disposition"] = f'attachment; filename="{report_id}.txt"'
    return response


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

