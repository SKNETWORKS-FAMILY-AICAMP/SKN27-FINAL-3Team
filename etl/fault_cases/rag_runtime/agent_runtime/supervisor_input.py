"""에이전트 입력 파서 및 검증기."""

from __future__ import annotations
from typing import Any
from etl.fault_cases.rag_runtime.contracts import RagRequest

SUPPORTED_DOMAINS = {"fault_standard", "precedent", "review_case"}

def parse_input(raw: dict[str, Any]) -> RagRequest:
    """Supervisor Input을 검증하고 내부 통신 규격인 RagRequest로 변환한다."""
    if "case_id" not in raw and "message_id" not in raw:
        raise ValueError("입력에 식별자(case_id/message_id)가 없습니다.")
    if "query_text" not in raw and "raw_user_text" not in raw:
        raise ValueError("입력에 텍스트 질의(query_text)가 없습니다.")

    accident_facts = raw.get("accident_facts")
    if accident_facts is None:
        accident_facts = raw.get("structured_facts") or {}
    if not isinstance(accident_facts, dict):
        raise ValueError("accident_facts must be an object.")

    required_domains = raw.get("required_domains")
    if required_domains is not None:
        if not isinstance(required_domains, list) or not required_domains:
            raise ValueError("required_domains must be a non-empty list.")
        invalid_domains = set(required_domains) - SUPPORTED_DOMAINS
        if invalid_domains:
            raise ValueError("required_domains contains an unsupported domain.")

    return {
        "contract_version": "v1",
        "message_id": str(raw.get("case_id") or raw.get("message_id")),
        "evaluation_query_id": str(raw.get("case_id") or raw.get("evaluation_query_id") or ""),
        "query_text": str(raw.get("query_text") or raw.get("raw_user_text") or ""),
        "accident_facts": accident_facts,
        "required_domains": required_domains,
        "query_vector": raw.get("query_vector")
    }
