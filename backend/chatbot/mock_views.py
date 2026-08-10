"""Explicit Mock HTTP entrypoints, absent from canonical URL configuration."""

from __future__ import annotations

import json

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from app.mock_runtime import attachments as mock_attachments
from app.mock_runtime import history as mock_history
from app.mock_runtime.agent_execution import execute_mock_plan
from app.mock_runtime.analysis_jobs import create_analysis_job, get_analysis_job


def _body(request: HttpRequest) -> dict:
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return body if isinstance(body, dict) else {}


@require_http_methods(["GET", "POST"])
def attachments(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        return JsonResponse({"attachments": mock_attachments.list_attachments(request.GET.get("session_id"))})
    return JsonResponse({"attachment": mock_attachments.register_attachment(_body(request), request.FILES.get("file"))})


@require_http_methods(["GET", "POST"])
def analysis_jobs(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        job_id = str(request.GET.get("job_id") or "")
        job = get_analysis_job(job_id) if job_id else None
        return JsonResponse({"job": job} if job else {"jobs": []})
    return JsonResponse({"job": create_analysis_job(_body(request))})


@require_http_methods(["GET"])
def history(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"events": mock_history.list_history_events(session_id=request.GET.get("session_id"))})


@require_http_methods(["POST"])
def agent_plan(request: HttpRequest) -> JsonResponse:
    payload = _body(request)
    plan = payload.get("analysis_plan") if isinstance(payload.get("analysis_plan"), dict) else {}
    return JsonResponse({"node_execution": execute_mock_plan(plan, payload)})
