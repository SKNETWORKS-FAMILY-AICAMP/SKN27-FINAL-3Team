"""에이전트 입력 파서 및 검증기."""

from __future__ import annotations
from typing import Any
from etl.fault_cases.rag_runtime.contracts import RagRequest

def parse_input(raw: dict[str, Any]) -> RagRequest:
    """Supervisor Input을 검증하고 내부 통신 규격인 RagRequest로 변환한다."""
    if "case_id" not in raw and "message_id" not in raw:
        raise ValueError("입력에 식별자(case_id/message_id)가 없습니다.")
    if "query_text" not in raw and "raw_user_text" not in raw:
        raise ValueError("입력에 텍스트 질의(query_text)가 없습니다.")

    return {
        "contract_version": "v1",
        "message_id": str(raw.get("case_id") or raw.get("message_id")),
        "evaluation_query_id": str(raw.get("case_id") or raw.get("evaluation_query_id") or ""),
        "query_text": str(raw.get("query_text") or raw.get("raw_user_text") or ""),
        "structured_facts": raw.get("structured_facts") or {},
        "query_vector": raw.get("query_vector")
    }
