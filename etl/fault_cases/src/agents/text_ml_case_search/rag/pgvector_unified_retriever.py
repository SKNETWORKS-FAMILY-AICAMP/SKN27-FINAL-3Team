from __future__ import annotations

from typing import Any, Callable

from openai import OpenAIError
from psycopg2 import Error as PsycopgError

from etl.fault_cases.src.agents.text_ml_case_search.config import (
    MIN_CHUNK_TEXT_LEN,
    PGVECTOR_SOURCE_TOP_K,
    V2_ACTIVE_SOURCE_TYPES,
    V2_EXCLUDED_SOURCE_TYPES,
    V2_FINAL_TOP_K,
    V2_MERGE_STRATEGY,
    V2_STANDBY_SOURCE_TYPES,
)
from etl.fault_cases.src.agents.text_ml_case_search.rag.evidence_mapper import (
    map_review_case_hits_to_evidence,
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
from etl.fault_cases.src.review_case.search.pgvector.retriever import (
    search_query as search_review_case_pgvector,
)
from etl.fault_cases.src.traffic_precedents.precedent_search.pgvector.retriever import (
    search_query as search_fault_ratio_precedent_pgvector,
)


DEFAULT_SEARCH_VARIANT = "schema_search_text"
SEARCH_VARIANT_FALLBACKS = (
    "schema_search_text",
    "full_optional_context",
    "normalized_description",
    "natural_query_text",
)


def run_unified_pgvector_pipeline(
    *,
    search_text: dict[str, Any],
    search_variant: str = DEFAULT_SEARCH_VARIANT,
    top_k: int = PGVECTOR_SOURCE_TOP_K,
    min_text_len: int = MIN_CHUNK_TEXT_LEN,
) -> dict[str, Any]:
    """Retrieve and quota-merge evidence from the two active pgvector stores."""

    selected = select_search_text(
        search_text=search_text,
        search_variant=search_variant,
    )
    selected_text = selected["search_text"]
    review_result = _run_source(
        source_type="review_case",
        retriever="review_case_pgvector",
        query=selected_text,
        requested_search_variant=search_variant,
        selected_search_variant=selected["search_variant"],
        top_k=top_k,
        min_text_len=min_text_len,
        retrieve=lambda: search_review_case_pgvector(selected_text, top_k),
        map_evidence=map_review_case_hits_to_evidence,
    )
    precedent_result = _run_source(
        source_type="fault_ratio_precedent",
        retriever="fault_ratio_precedent_pgvector",
        query=selected_text,
        requested_search_variant=search_variant,
        selected_search_variant=selected["search_variant"],
        top_k=top_k,
        min_text_len=min_text_len,
        retrieve=lambda: search_fault_ratio_precedent_pgvector(
            "fault_ratio",
            selected_text,
            top_k,
        ),
        map_evidence=map_fault_ratio_precedent_hits_to_evidence,
    )
    merge_result = merge_evidence_by_source_quota(
        review_case_evidence=review_result["evidence"],
        fault_ratio_precedent_evidence=precedent_result["evidence"],
    )
    source_results = {
        "review_case": review_result,
        "fault_ratio_precedent": precedent_result,
    }

    return {
        "status": _pipeline_status(source_results=source_results, evidence=merge_result["evidence"]),
        "retriever": "unified_pgvector",
        "requested_search_variant": search_variant,
        "search_variant": selected["search_variant"],
        "search_text": selected_text,
        "top_k": top_k,
        "final_top_k": V2_FINAL_TOP_K,
        "active_sources": V2_ACTIVE_SOURCE_TYPES,
        "standby_sources": V2_STANDBY_SOURCE_TYPES,
        "excluded_sources": V2_EXCLUDED_SOURCE_TYPES,
        "source_summary": _build_source_summary(
            merge_result=merge_result,
            source_results=source_results,
        ),
        "source_results": source_results,
        "merge_result": merge_result,
        "evidence": merge_result["evidence"],
    }


def select_search_text(
    *,
    search_text: dict[str, Any],
    search_variant: str = DEFAULT_SEARCH_VARIANT,
) -> dict[str, str]:
    """Select a non-empty query text using the established variant fallbacks."""

    requested = _clean(search_text.get(search_variant))
    if requested:
        return {"search_variant": search_variant, "search_text": requested}

    for variant in SEARCH_VARIANT_FALLBACKS:
        value = _clean(search_text.get(variant))
        if value:
            return {"search_variant": variant, "search_text": value}
    return {"search_variant": search_variant, "search_text": ""}


def _run_source(
    *,
    source_type: str,
    retriever: str,
    query: str,
    requested_search_variant: str,
    selected_search_variant: str,
    top_k: int,
    min_text_len: int,
    retrieve: Callable[[], list[dict[str, Any]]],
    map_evidence: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
) -> dict[str, Any]:
    if not query:
        return _empty_source_result(
            source_type=source_type,
            retriever=retriever,
            requested_search_variant=requested_search_variant,
            selected_search_variant=selected_search_variant,
            query=query,
            top_k=top_k,
            min_text_len=min_text_len,
        )

    try:
        raw_rows = retrieve()
    except (OSError, OpenAIError, PsycopgError, RuntimeError) as exc:
        return _unavailable_source_result(
            source_type=source_type,
            retriever=retriever,
            requested_search_variant=requested_search_variant,
            selected_search_variant=selected_search_variant,
            query=query,
            top_k=top_k,
            min_text_len=min_text_len,
            exception=exc,
        )

    normalized_rows = [_normalize_pgvector_row(row, retriever=retriever) for row in raw_rows]
    mapped_evidence = map_evidence(normalized_rows)
    valid_evidence = validate_evidence(
        evidence=mapped_evidence,
        min_text_len=min_text_len,
    )
    validation_report = build_evidence_validation_report(
        evidence=mapped_evidence,
        min_text_len=min_text_len,
    )
    return {
        "status": "ready" if valid_evidence else "empty",
        "retriever": retriever,
        "source_type": source_type,
        "requested_search_variant": requested_search_variant,
        "search_variant": selected_search_variant,
        "search_text": query,
        "top_k": top_k,
        "raw_hit_count": len(raw_rows),
        "mapped_evidence_count": len(mapped_evidence),
        "valid_evidence_count": len(valid_evidence),
        "validation_report": validation_report,
        "raw_hits": normalized_rows,
        "mapped_evidence": mapped_evidence,
        "evidence": valid_evidence,
    }


def _normalize_pgvector_row(row: dict[str, Any], *, retriever: str) -> dict[str, Any]:
    return {
        **row,
        "retriever": retriever,
        "retriever_score": row.get("cosine_similarity"),
        "score_type": "cosine_similarity",
        "index": None,
        "highlight": {},
    }


def _empty_source_result(
    *,
    source_type: str,
    retriever: str,
    requested_search_variant: str,
    selected_search_variant: str,
    query: str,
    top_k: int,
    min_text_len: int,
) -> dict[str, Any]:
    return {
        "status": "empty",
        "retriever": retriever,
        "source_type": source_type,
        "requested_search_variant": requested_search_variant,
        "search_variant": selected_search_variant,
        "search_text": query,
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


def _unavailable_source_result(
    *,
    source_type: str,
    retriever: str,
    requested_search_variant: str,
    selected_search_variant: str,
    query: str,
    top_k: int,
    min_text_len: int,
    exception: Exception,
) -> dict[str, Any]:
    result = _empty_source_result(
        source_type=source_type,
        retriever=retriever,
        requested_search_variant=requested_search_variant,
        selected_search_variant=selected_search_variant,
        query=query,
        top_k=top_k,
        min_text_len=min_text_len,
    )
    result.update(
        {
            "status": "unavailable",
            "error_code": "pgvector_unavailable",
            "error_class": exception.__class__.__name__,
        }
    )
    return result


def _pipeline_status(
    *,
    source_results: dict[str, dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> str:
    if any(result["status"] == "unavailable" for result in source_results.values()):
        return "partial" if evidence else "unavailable"
    return "ready" if evidence else "empty"


def _build_source_summary(
    *,
    merge_result: dict[str, Any],
    source_results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "active_sources": V2_ACTIVE_SOURCE_TYPES,
        "standby_sources": V2_STANDBY_SOURCE_TYPES,
        "excluded_sources": V2_EXCLUDED_SOURCE_TYPES,
        "source_counts": merge_result["source_counts"],
        "input_counts": merge_result["input_counts"],
        "final_top_k": V2_FINAL_TOP_K,
        "merge_strategy": V2_MERGE_STRATEGY,
        "source_statuses": {
            source_type: result["status"]
            for source_type, result in source_results.items()
        },
    }


def _clean(value: Any) -> str:
    return str(value or "").strip()
