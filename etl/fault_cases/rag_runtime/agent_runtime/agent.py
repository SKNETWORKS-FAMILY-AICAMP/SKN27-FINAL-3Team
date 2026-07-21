"""통합 RAG 에이전트.

세 RAG 서비스를 호출하고 결과를 취합한다.
"""

from __future__ import annotations
from typing import Any

from etl.fault_cases.rag_runtime.contracts import RagRequest
from etl.fault_cases.rag_runtime.fault_standard.service import handle_request as fs_handle
from etl.fault_cases.rag_runtime.precedent.service import handle_request as pr_handle
from etl.fault_cases.rag_runtime.review_case.service import handle_request as rc_handle
from .supervisor_input import parse_input
from .supervisor_output import format_output

def invoke_agent(raw_input: dict[str, Any]) -> dict[str, Any]:
    """외부 요청(Supervisor)을 받아 파싱 후 3개 RAG를 실행하고 결과를 묶어 반환한다."""
    try:
        req = parse_input(raw_input)
    except ValueError as e:
        return {"status": "error", "message": str(e)}

    # TODO: 비동기 병렬 처리(asyncio)로 전환 가능
    fs_result = fs_handle(req)
    pr_result = pr_handle(req)
    rc_result = rc_handle(req)

    results = {
        "fault_standard": fs_result,
        "precedent": pr_result,
        "review_case": rc_result
    }

    return format_output(req["message_id"], results)
