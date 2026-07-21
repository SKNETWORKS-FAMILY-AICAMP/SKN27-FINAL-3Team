"""에이전트 출력 포매터."""

from __future__ import annotations
from typing import Any
from etl.fault_cases.rag_runtime.contracts import DomainSearchResult

def format_output(message_id: str, results: dict[str, DomainSearchResult]) -> dict[str, Any]:
    """세 RAG의 검색/계산 결과를 Supervisor Output 규격으로 병합한다."""
    return {
        "message_id": message_id,
        "contract_version": "v1",
        "status": "success" if all(r.get("status") in {"success", "partial"} for r in results.values()) else "partial",
        "domains": results
    }
