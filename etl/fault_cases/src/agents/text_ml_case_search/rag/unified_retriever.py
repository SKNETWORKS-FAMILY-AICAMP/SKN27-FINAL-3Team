from __future__ import annotations

from typing import Any

from etl.fault_cases.src.agents.text_ml_case_search.config import (
    BM25_TOP_K,
    MIN_CHUNK_TEXT_LEN,
    V2_ACTIVE_SOURCE_TYPES,
    V2_EXCLUDED_SOURCE_TYPES,
    V2_FINAL_TOP_K,
    V2_MERGE_STRATEGY,
    V2_STANDBY_SOURCE_TYPES,
)
from etl.fault_cases.src.agents.text_ml_case_search.rag.bm25_nori_retriever import (
    ElasticsearchLike,
)
from etl.fault_cases.src.agents.text_ml_case_search.rag.evidence_merger import (
    merge_evidence_by_source_quota,
)
from etl.fault_cases.src.agents.text_ml_case_search.rag.evidence_validator import (
    build_evidence_validation_report,
    validate_evidence,
)
from etl.fault_cases.src.agents.text_ml_case_search.rag.fault_ratio_precedent_evidence_mapper import (
    map_fault_ratio_precedent_hits_to_evidence,
)
from etl.fault_cases.src.agents.text_ml_case_search.rag.fault_ratio_precedent_retriever import (
    search_fault_ratio_precedent_bm25,
)
from etl.fault_cases.src.agents.text_ml_case_search.rag.retrieval_pipeline import (
    DEFAULT_SEARCH_VARIANT,
    run_review_case_bm25_pipeline,
    select_search_text,
)


def run_unified_rag_pipeline(
    *,
    es: ElasticsearchLike,
    search_text: dict[str, Any],
    search_variant: str = DEFAULT_SEARCH_VARIANT,
    top_k: int = BM25_TOP_K,
    min_text_len: int = MIN_CHUNK_TEXT_LEN,
) -> dict[str, Any]:
    selected = select_search_text(search_text=search_text, search_variant=search_variant)
    selected_text = selected["search_text"]

    review_result = run_review_case_bm25_pipeline(
        es=es,
        search_text=search_text,
        search_variant=search_variant,
        top_k=top_k,
        min_text_len=min_text_len,
    )
    precedent_result = _run_fault_ratio_precedent_pipeline(
        es=es,
        selected_text=selected_text,
        selected_variant=selected["search_variant"],
        requested_search_variant=search_variant,
        top_k=top_k,
        min_text_len=min_text_len,
    )

    merge_result = merge_evidence_by_source_quota(
        review_case_evidence=review_result["evidence"],
        fault_ratio_precedent_evidence=precedent_result["evidence"],
    )
    source_summary = _build_source_summary(merge_result=merge_result)

    return {
        "retriever": "unified_bm25_nori",
        "requested_search_variant": search_variant,
        "search_variant": selected["search_variant"],
        "search_text": selected_text,
        "top_k": top_k,
        "final_top_k": V2_FINAL_TOP_K,
        "active_sources": V2_ACTIVE_SOURCE_TYPES,
        "standby_sources": V2_STANDBY_SOURCE_TYPES,
        "excluded_sources": V2_EXCLUDED_SOURCE_TYPES,
        "source_summary": source_summary,
        "source_results": {
            "review_case": review_result,
            "fault_ratio_precedent": precedent_result,
        },
        "merge_result": merge_result,
        "evidence": merge_result["evidence"],
    }


def _run_fault_ratio_precedent_pipeline(
    *,
    es: ElasticsearchLike,
    selected_text: str,
    selected_variant: str,
    requested_search_variant: str,
    top_k: int,
    min_text_len: int,
) -> dict[str, Any]:
    if not selected_text:
        return _empty_fault_ratio_precedent_result(
            selected_variant=selected_variant,
            requested_search_variant=requested_search_variant,
            selected_text=selected_text,
            top_k=top_k,
            min_text_len=min_text_len,
        )

    raw_hits = search_fault_ratio_precedent_bm25(
        es=es,
        search_text=selected_text,
        top_k=top_k,
    )
    mapped_evidence = map_fault_ratio_precedent_hits_to_evidence(raw_hits)
    valid_evidence = validate_evidence(
        evidence=mapped_evidence,
        min_text_len=min_text_len,
    )
    validation_report = build_evidence_validation_report(
        evidence=mapped_evidence,
        min_text_len=min_text_len,
    )

    return {
        "retriever": "fault_ratio_precedent_bm25_nori",
        "source_type": "fault_ratio_precedent",
        "requested_search_variant": requested_search_variant,
        "search_variant": selected_variant,
        "search_text": selected_text,
        "top_k": top_k,
        "raw_hit_count": len(raw_hits),
        "mapped_evidence_count": len(mapped_evidence),
        "valid_evidence_count": len(valid_evidence),
        "validation_report": validation_report,
        "raw_hits": raw_hits,
        "mapped_evidence": mapped_evidence,
        "evidence": valid_evidence,
    }


def _empty_fault_ratio_precedent_result(
    *,
    selected_variant: str,
    requested_search_variant: str,
    selected_text: str,
    top_k: int,
    min_text_len: int,
) -> dict[str, Any]:
    return {
        "retriever": "fault_ratio_precedent_bm25_nori",
        "source_type": "fault_ratio_precedent",
        "requested_search_variant": requested_search_variant,
        "search_variant": selected_variant,
        "search_text": selected_text,
        "top_k": top_k,
        "raw_hit_count": 0,
        "mapped_evidence_count": 0,
        "valid_evidence_count": 0,
        "validation_report": {
            "input_count": 0,
            "valid_count": 0,
            "invalid_count": 0,
            "invalid_reason_counts": {},
            "min_text_len": min_text_len,
        },
        "raw_hits": [],
        "mapped_evidence": [],
        "evidence": [],
    }


def _build_source_summary(*, merge_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "active_sources": V2_ACTIVE_SOURCE_TYPES,
        "standby_sources": V2_STANDBY_SOURCE_TYPES,
        "excluded_sources": V2_EXCLUDED_SOURCE_TYPES,
        "source_counts": merge_result["source_counts"],
        "input_counts": merge_result["input_counts"],
        "final_top_k": V2_FINAL_TOP_K,
        "merge_strategy": V2_MERGE_STRATEGY,
    }
