from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from psycopg2.extras import RealDictCursor

from etl.fault_cases.src.review_case.db_loading.db_config import (
    EMBEDDING_SETTINGS,
    PGVECTOR_SEARCH_SETTINGS,
    SETTINGS,
)
from etl.fault_cases.src.review_case.db_loading.db_connection import get_connection
from etl.fault_cases.src.review_case.embedding.openai_embedder import OpenAIEmbedder
from etl.fault_cases.src.review_case.embedding.run_embedding import vector_literal


def embed_query(query: str) -> list[float]:
    result = OpenAIEmbedder().embed_texts([query])
    if not result.vectors:
        raise RuntimeError("Query embedding API returned no vector")
    return result.vectors[0]


def search_by_vector(query_vector: list[float], top_k: int | None = None) -> list[dict[str, Any]]:
    if len(query_vector) != EMBEDDING_SETTINGS.dim:
        raise RuntimeError("embedding_space_mismatch")
    limit = top_k or PGVECTOR_SEARCH_SETTINGS.default_top_k
    vector_text = vector_literal(query_vector)

    search_sql = """
        SELECT
            c.review_case_id,
            c.review_no,
            c.chunk_id,
            c.chunk_type,
            c.part_index,
            c.sequence_no,
            c.chunk_text,
            c.search_text,
            c.case_title,
            c.reference_chart_key,
            c.standard_scenario_keywords,
            c.decision_fault_ratio,
            c.claimant_final_ratio,
            c.respondent_final_ratio,
            c.party_type,
            c.quality_flags,
            d.header_accident_group,
            d.header_road_context,
            d.toc_large_category,
            d.toc_middle_category,
            d.signal_condition,
            d.road_feature,
            d.standard_a_behavior,
            d.standard_b_behavior,
            d.claimant_standard_behavior,
            d.respondent_standard_behavior,
            d.decision_reason,
            d.final_ratio_text,
            e.embedding_vector <=> %s::vector AS cosine_distance,
            1 - (e.embedding_vector <=> %s::vector) AS cosine_similarity
        FROM review_case_chunk_embeddings e
        JOIN review_case_chunks c ON c.chunk_id = e.chunk_id
        JOIN review_case_documents d ON d.review_case_id = c.review_case_id
        WHERE e.embedding_model = %s
          AND e.embedding_version = %s
          AND e.embedding_dim = %s
          AND e.embedding_vector IS NOT NULL
        ORDER BY e.embedding_vector <=> %s::vector
        LIMIT %s
    """
    params = (
        vector_text,
        vector_text,
        EMBEDDING_SETTINGS.model,
        EMBEDDING_SETTINGS.version,
        EMBEDDING_SETTINGS.dim,
        vector_text,
        limit,
    )

    with get_connection(SETTINGS.review_case_db) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(search_sql, params)
            rows = [dict(row) for row in cur.fetchall()]

    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
        row["cosine_distance"] = float(row["cosine_distance"])
        row["cosine_similarity"] = float(row["cosine_similarity"])
    return rows


def search_query(query: str, top_k: int | None = None) -> list[dict[str, Any]]:
    return search_by_vector(query_vector=embed_query(query), top_k=top_k)


def compact_result(row: dict[str, Any], include_text: bool = False) -> dict[str, Any]:
    result = {
        "rank": row["rank"],
        "review_case_id": row["review_case_id"],
        "review_no": row["review_no"],
        "chunk_id": row["chunk_id"],
        "chunk_type": row["chunk_type"],
        "case_title": row.get("case_title"),
        "reference_chart_key": row.get("reference_chart_key"),
        "decision_fault_ratio": row.get("decision_fault_ratio"),
        "claimant_final_ratio": row.get("claimant_final_ratio"),
        "respondent_final_ratio": row.get("respondent_final_ratio"),
        "header_accident_group": row.get("header_accident_group"),
        "header_road_context": row.get("header_road_context"),
        "toc_large_category": row.get("toc_large_category"),
        "toc_middle_category": row.get("toc_middle_category"),
        "signal_condition": row.get("signal_condition"),
        "road_feature": row.get("road_feature"),
        "standard_a_behavior": row.get("standard_a_behavior"),
        "standard_b_behavior": row.get("standard_b_behavior"),
        "cosine_similarity": row["cosine_similarity"],
        "cosine_distance": row["cosine_distance"],
        "chunk_preview": str(row.get("chunk_text") or "")[:500],
        "search_preview": str(row.get("search_text") or "")[:500],
    }
    if include_text:
        result["chunk_text"] = row.get("chunk_text")
        result["search_text"] = row.get("search_text")
        result["decision_reason"] = row.get("decision_reason")
        result["final_ratio_text"] = row.get("final_ratio_text")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run pgvector cosine search for review case chunks.")
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=PGVECTOR_SEARCH_SETTINGS.default_top_k)
    parser.add_argument("--include-text", action="store_true")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    results = search_query(query=args.query, top_k=args.top_k)
    print(
        json.dumps(
            [compact_result(row, include_text=args.include_text) for row in results],
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

