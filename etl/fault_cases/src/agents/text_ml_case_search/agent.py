from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from etl.fault_cases.src.agents.text_ml_case_search.builders.output_builder import (
    build_failed_output,
    build_output,
)
from etl.fault_cases.src.agents.text_ml_case_search.builders.insurer_claim_review_builder import (
    build_insurer_claim_review,
)
from etl.fault_cases.src.agents.text_ml_case_search.builders.evidence_display_builder import (
    build_display_evidence,
)
from etl.fault_cases.src.agents.text_ml_case_search.builders.recommended_evidence_builder import (
    build_recommended_evidence,
)
from etl.fault_cases.src.agents.text_ml_case_search.builders.ratio_range_builder import (
    build_ratio_range_label,
)
from etl.fault_cases.src.agents.text_ml_case_search.builders.similar_case_builder import (
    build_similar_cases,
)
from etl.fault_cases.src.agents.text_ml_case_search.config import CONTRACT_VERSION_V2
from etl.fault_cases.src.agents.text_ml_case_search.input.context_builder import build_context
from etl.fault_cases.src.agents.text_ml_case_search.input.issue_tagger import extract_issue_tags
from etl.fault_cases.src.agents.text_ml_case_search.input.normalizer import normalize_accident
from etl.fault_cases.src.agents.text_ml_case_search.input.validator import validate_input
from etl.fault_cases.src.agents.text_ml_case_search.rag.search_text_builder import build_search_text
from etl.fault_cases.src.agents.text_ml_case_search.rag.bm25_nori_retriever import (
    ElasticsearchLike,
)
from etl.fault_cases.src.agents.text_ml_case_search.rag.retrieval_pipeline import (
    DEFAULT_SEARCH_VARIANT,
)
from etl.fault_cases.src.agents.text_ml_case_search.rag.unified_retriever import (
    run_unified_rag_pipeline,
)
from etl.fault_cases.src.agents.text_ml_case_search.schemas import AgentOutput


def run_text_ml_case_search(
    agent_input: dict[str, Any],
    *,
    mock_evidence: list[dict[str, Any]] | None = None,
    es_client: ElasticsearchLike | None = None,
    search_variant: str = DEFAULT_SEARCH_VARIANT,
) -> AgentOutput:
    contract_version = CONTRACT_VERSION_V2 if es_client is not None else None
    validation = validate_input(agent_input)
    if not validation["ok"]:
        failed_kwargs: dict[str, Any] = {
            "missing_fields": validation["missing_fields"],
            "errors": validation["errors"],
        }
        if contract_version:
            failed_kwargs["contract_version"] = contract_version
        return build_failed_output(**failed_kwargs)

    context = build_context(agent_input)
    normalized = normalize_accident(context)
    issue_tags = extract_issue_tags(context, normalized)
    search_text = build_search_text(
        context=context,
        normalized=normalized,
        issue_tags=issue_tags,
    )
    rag_debug: dict[str, Any] = {}
    source_summary: dict[str, Any] = {}
    evidence = mock_evidence or []
    if mock_evidence is None and es_client is not None:
        rag_result = run_unified_rag_pipeline(
            es=es_client,
            search_text=search_text,
            search_variant=search_variant,
        )
        evidence = rag_result["evidence"]
        rag_debug = {
            "retriever": rag_result["retriever"],
            "requested_search_variant": rag_result["requested_search_variant"],
            "search_variant": rag_result["search_variant"],
            "top_k": rag_result["top_k"],
            "final_top_k": rag_result["final_top_k"],
            "active_sources": rag_result["active_sources"],
            "standby_sources": rag_result["standby_sources"],
            "excluded_sources": rag_result["excluded_sources"],
            "source_results": {
                source_type: {
                    "retriever": source_result.get("retriever"),
                    "source_type": source_result.get("source_type"),
                    "raw_hit_count": source_result.get("raw_hit_count"),
                    "mapped_evidence_count": source_result.get("mapped_evidence_count"),
                    "valid_evidence_count": source_result.get("valid_evidence_count"),
                    "validation_report": source_result.get("validation_report"),
                }
                for source_type, source_result in rag_result["source_results"].items()
            },
            "merge_result": {
                "merge_strategy": rag_result["merge_result"]["merge_strategy"],
                "review_case_quota": rag_result["merge_result"]["review_case_quota"],
                "fault_ratio_precedent_quota": rag_result["merge_result"][
                    "fault_ratio_precedent_quota"
                ],
                "final_top_k": rag_result["merge_result"]["final_top_k"],
                "source_counts": rag_result["merge_result"]["source_counts"],
                "input_counts": rag_result["merge_result"]["input_counts"],
                "output_count": rag_result["merge_result"]["output_count"],
            },
        }
        source_summary = rag_result["source_summary"]

    limitations: list[str] = []
    next_actions: list[str] = []
    similar_cases = build_similar_cases(evidence=evidence)
    ratio_range_label = build_ratio_range_label(evidence=evidence)
    display_evidence = build_display_evidence(evidence=evidence)

    if not evidence:
        limitations.append("아직 RAG 검색이 연결되지 않아 유사 근거는 반환하지 않습니다.")
        next_actions.append("BM25+Nori RAG 연결 후 유사 심의사례 근거를 확인해야 합니다.")

    recommended_evidence = build_recommended_evidence(
        context=context,
        issue_tags=issue_tags,
        evidence=evidence,
    )
    if recommended_evidence:
        next_actions.append("쟁점 확인을 위해 추가 증거자료를 준비해야 합니다.")

    insurer_claim_review = build_insurer_claim_review(
        insurer_claim=context.get("insurer_claim"),
        issue_tags=issue_tags,
        evidence=evidence,
        ratio_range_label=ratio_range_label,
    )
    if insurer_claim_review and not evidence:
        limitations.append("보험사 주장은 입력되었지만, 비교할 RAG 근거가 아직 없습니다.")

    return build_output(
        status="success" if evidence else "partial",
        normalized_description=normalized["normalized_description"],
        accident_type_candidates=normalized["accident_type_candidates"],
        issue_tags=issue_tags,
        evidence_tags=[item["type"] for item in recommended_evidence],
        recommended_evidence=recommended_evidence,
        insurer_claim_review=insurer_claim_review,
        similar_cases=similar_cases,
        ratio_range_label=ratio_range_label,
        display_evidence=display_evidence,
        evidence=evidence,
        next_actions=next_actions,
        limitations=limitations,
        missing_fields=[],
        search_text=search_text,
        rag_debug=rag_debug,
        source_summary=source_summary,
        **({"contract_version": contract_version} if contract_version else {}),
    )


def build_sample_agent_input() -> dict[str, Any]:
    return {
        "session_id": "sample_session",
        "message_id": "sample_message",
        "job_id": "sample_job",
        "node_code": "text_ml_case_search",
        "raw_user_text": "신호 없는 교차로에서 저는 직진 중이었고 상대 차량은 오른쪽에서 진입했습니다.",
        "query_text": "신호 없는 교차로 직진 차량과 우측 진입 차량 충돌 사고",
        "vision_evidence": None,
        "ocr_evidence": None,
        "insurer_claim": {
            "claimed_ratio": "사용자 70 : 상대 30",
            "reason_text": "보험사는 우측 차량 진입 상황 때문에 사용자 과실이 높다고 설명했습니다.",
            "source_type": "user_text",
            "source_text": "보험사는 제 과실을 70이라고 합니다.",
            "source_reference": None,
        },
        "required_outputs": [
            "normalized_description",
            "issue_tags",
            "similar_cases",
            "evidence",
            "ratio_range_label",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run text_ml_case_search skeleton with mock evidence.")
    parser.add_argument("--sample", action="store_true", help="Run with a built-in sample input.")
    parser.add_argument("--input-json", help="Path to a JSON file containing agent_input.")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = parse_args()
    if args.sample:
        agent_input = build_sample_agent_input()
    elif args.input_json:
        with open(args.input_json, encoding="utf-8") as file:
            payload = json.load(file)
        agent_input = payload.get("agent_input", payload)
    else:
        raise SystemExit("Use --sample or --input-json.")

    result = run_text_ml_case_search(agent_input)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    from etl.fault_cases.src.agents.text_ml_case_search.config import load_dotenv_if_available

    load_dotenv_if_available()
    main()
