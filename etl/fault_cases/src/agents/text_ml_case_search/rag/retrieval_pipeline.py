from __future__ import annotations

from typing import Any

from etl.fault_cases.src.agents.text_ml_case_search.config import (
    BM25_TOP_K,
    EVIDENCE_INDEX_NAMES,
    MIN_CHUNK_TEXT_LEN,
)
from etl.fault_cases.src.agents.text_ml_case_search.rag.bm25_nori_retriever import (
    ElasticsearchLike,
    search_bm25_nori,
)
from etl.fault_cases.src.agents.text_ml_case_search.rag.evidence_mapper import (
    map_review_case_hits_to_evidence,
)
from etl.fault_cases.src.agents.text_ml_case_search.rag.evidence_validator import (
    build_evidence_validation_report,
    validate_evidence,
)


DEFAULT_SEARCH_VARIANT = "schema_search_text"
SEARCH_VARIANT_FALLBACKS = (
    "schema_search_text",
    "full_optional_context",
    "normalized_description",
    "natural_query_text",
)


def run_review_case_bm25_pipeline(
    *,
    es: ElasticsearchLike,
    search_text: dict[str, Any],
    search_variant: str = DEFAULT_SEARCH_VARIANT,
    index_names: list[str] | None = None,
    top_k: int = BM25_TOP_K,
    min_text_len: int = MIN_CHUNK_TEXT_LEN,
) -> dict[str, Any]:
    """Run Agent V1 review-case BM25 retrieval and evidence validation.

    Flow:
      search_text_builder output
      -> Agent-owned BM25/Nori retriever
      -> review-case evidence mapper
      -> evidence quality validator
    """

    selected = select_search_text(search_text=search_text, search_variant=search_variant)
    selected_text = selected["search_text"]
    if not selected_text:
        return _empty_pipeline_result(
            search_variant=selected["search_variant"],
            requested_search_variant=search_variant,
            search_text=selected_text,
            top_k=top_k,
            min_text_len=min_text_len,
        )

    raw_hits = search_bm25_nori(
        es=es,
        search_text=selected_text,
        index_names=index_names or EVIDENCE_INDEX_NAMES,
        top_k=top_k,
    )
    mapped_evidence = map_review_case_hits_to_evidence(raw_hits)
    valid_evidence = validate_evidence(
        evidence=mapped_evidence,
        min_text_len=min_text_len,
    )
    validation_report = build_evidence_validation_report(
        evidence=mapped_evidence,
        min_text_len=min_text_len,
    )

    return {
        "retriever": "bm25_nori",
        "source_type": "review_case",
        "requested_search_variant": search_variant,
        "search_variant": selected["search_variant"],
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


def select_search_text(
    *,
    search_text: dict[str, Any],
    search_variant: str = DEFAULT_SEARCH_VARIANT,
) -> dict[str, str]:
    """Select the requested search text variant with stable fallbacks."""

    requested = _clean(search_text.get(search_variant))
    if requested:
        return {
            "search_variant": search_variant,
            "search_text": requested,
        }

    for variant in SEARCH_VARIANT_FALLBACKS:
        value = _clean(search_text.get(variant))
        if value:
            return {
                "search_variant": variant,
                "search_text": value,
            }

    return {
        "search_variant": search_variant,
        "search_text": "",
    }


def _empty_pipeline_result(
    *,
    search_variant: str,
    requested_search_variant: str,
    search_text: str,
    top_k: int,
    min_text_len: int,
) -> dict[str, Any]:
    return {
        "retriever": "bm25_nori",
        "source_type": "review_case",
        "requested_search_variant": requested_search_variant,
        "search_variant": search_variant,
        "search_text": search_text,
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


def _clean(value: Any) -> str:
    return str(value or "").strip()
