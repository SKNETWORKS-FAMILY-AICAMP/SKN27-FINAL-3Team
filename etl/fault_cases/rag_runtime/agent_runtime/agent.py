"""통합 RAG 에이전트.

요청된 RAG 서비스를 호출하고 결과를 취합한다.
"""

from __future__ import annotations

from typing import Any

from etl.fault_cases.rag_runtime.fault_standard.service import handle_request as fs_handle
from etl.fault_cases.rag_runtime.precedent.service import handle_request as pr_handle
from etl.fault_cases.rag_runtime.review_case.service import handle_request as rc_handle

from .supervisor_input import parse_input
from .supervisor_output import format_failed_output, format_output


def _message_id_from_raw(raw_input: Any) -> str:
    if not isinstance(raw_input, dict):
        return ""
    return str(raw_input.get("case_id") or raw_input.get("message_id") or "")


def invoke_agent(raw_input: dict[str, Any]) -> dict[str, Any]:
    """요청된 RAG 도메인만 실행하고 결과를 Supervisor 형식으로 반환한다."""
    try:
        request = parse_input(raw_input)
    except (AttributeError, TypeError, ValueError):
        return format_failed_output(_message_id_from_raw(raw_input))

    handlers = {
        "fault_standard": fs_handle,
        "precedent": pr_handle,
        "review_case": rc_handle,
    }
    requested_domains = request.get("required_domains") or list(handlers)
    results = {
        domain: handlers[domain](request)
        for domain in requested_domains
    }
    return format_output(request["message_id"], results)
