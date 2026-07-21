"""도메인 RAG 결과를 슈퍼바이저용 근거 묶음으로 결합한다."""

from __future__ import annotations

from typing import Any, Sequence

from etl.fault_cases.rag_runtime.contracts import DomainSearchResult


def build_result_bundle(results: Sequence[DomainSearchResult]) -> dict[str, Any]:
    """검색·계산 결과를 그대로 묶되 최종 법률 판단을 하지 않는다."""

    return {
        "domains": list(results),
        "limitations": [
            "이 결과 묶음은 근거 전달용입니다.",
            "최종 자연어 답변과 법률적 결론은 슈퍼바이저의 책임입니다.",
        ],
    }
