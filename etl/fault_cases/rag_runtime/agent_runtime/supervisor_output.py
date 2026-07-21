"""에이전트 출력 포매터."""

from __future__ import annotations

from typing import Any

from etl.fault_cases.rag_runtime.contracts import DomainSearchResult


def format_output(message_id: str, results: dict[str, DomainSearchResult]) -> dict[str, Any]:
    """선택된 RAG 결과를 Supervisor Output 규격으로 병합한다."""
    statuses = [result.get("status") for result in results.values()]
    if statuses and all(status == "success" for status in statuses):
        status = "success"
    elif statuses and all(status == "failed" for status in statuses):
        status = "failed"
    else:
        status = "partial"

    return {
        "message_id": message_id,
        "contract_version": "v1",
        "status": status,
        "domains": results,
    }


def format_failed_output(message_id: str) -> dict[str, Any]:
    """유효하지 않은 요청을 계약 호환 실패 응답으로 반환한다."""
    return {
        "message_id": message_id,
        "contract_version": "v1",
        "status": "failed",
        "domains": {},
    }
