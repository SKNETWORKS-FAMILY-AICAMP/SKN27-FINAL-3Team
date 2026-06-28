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
from app.services.chatbot_mock_service import (
    create_session,
    list_demo_scenarios,
    perform_report_action,
    submit_message,
)
from chatbot.api_response import (
    is_canonical_mock_request as _is_canonical_mock_request,
    json_response as _json_response,
)
from chatbot.request_parsing import (
    first_upload_file as _first_upload_file,
    json_body as _json_body,
    request_payload as _request_payload,
)
from chatbot.repositories import (
    get_uploaded_file,
    list_uploaded_files,
    persist_chat_message_analysis_boundary,
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
    return _json_response(request, {"result": result})


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def create_chat_session(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    return _json_response(request, create_session(user_id=body.get("user_id")))


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def submit_chat_message(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    chat_response = submit_message(body)
    if _is_canonical_mock_request(request):
        persist_chat_message_analysis_boundary(body, chat_response)
    return _json_response(request, chat_response)


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

