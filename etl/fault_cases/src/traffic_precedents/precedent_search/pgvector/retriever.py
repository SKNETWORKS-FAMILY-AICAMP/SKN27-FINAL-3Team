from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Any

from psycopg2.extras import RealDictCursor

from etl.fault_cases.src.traffic_precedents.precedent_db_loading.db import get_connection
from etl.fault_cases.src.traffic_precedents.precedent_embedding.before_embedding.openai_embedder import (
    OpenAIEmbedder,
)
from etl.fault_cases.src.traffic_precedents.precedent_embedding.before_embedding.store_embeddings_common import (
    vector_literal,
)

from ..search_config import DATASET_SEARCH_CONFIGS, SEARCH_SETTINGS, SearchSettings


@dataclass(frozen=True)
class SearchResult:
    dataset: str
    rank: int
    case_id: str
    chunk_id: str
    chunk_index: int
    chunk_type: str
    chunk_strategy: str
    case_name: str
    case_number: str | None
    court_name: str | None
    decision_date: str | None
    cosine_distance: float
    cosine_similarity: float
    chunk_text: str
    search_text: str
    metadata: dict[str, Any]


def embed_query(query: str) -> list[float]:
    result = OpenAIEmbedder().embed_texts([query])
    if not result.vectors:
        raise RuntimeError("Query embedding API returned no vector")
    return result.vectors[0]


def search_by_vector(
    dataset: str,
    query_vector: list[float],
    top_k: int | None = None,
    settings: SearchSettings = SEARCH_SETTINGS,
) -> list[dict[str, Any]]:
    config = DATASET_SEARCH_CONFIGS[dataset]
    db_name = config["db_name"]
    case_table = config["case_table"]
    chunk_table = config["chunk_table"]
    embedding_table = config["embedding_table"]
    limit = top_k or settings.default_top_k
    vector_text = vector_literal(query_vector)

    sql = f"""
        SELECT
            c.case_id,
            c.chunk_id,
            c.chunk_index,
            c.chunk_type,
            c.chunk_strategy,
            c.chunk_text,
            c.search_text,
            c.metadata,
            p.case_name,
            p.case_number,
            p.court_name,
            p.decision_date::text AS decision_date,
            e.embedding_vector <=> %s::vector AS cosine_distance,
            1 - (e.embedding_vector <=> %s::vector) AS cosine_similarity
        FROM {embedding_table} e
        JOIN {chunk_table} c ON c.chunk_id = e.chunk_id
        JOIN {case_table} p ON p.case_id = c.case_id
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
        settings.embedding_model,
        settings.embedding_version,
        settings.embedding_dim,
        vector_text,
        limit,
    )

    with get_connection(db_name) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = [dict(row) for row in cur.fetchall()]

    results = []
    for index, row in enumerate(rows, start=1):
        row["dataset"] = dataset
        row["rank"] = index
        row["cosine_distance"] = float(row["cosine_distance"])
        row["cosine_similarity"] = float(row["cosine_similarity"])
        row["metadata"] = row.get("metadata") or {}
        results.append(row)
    return results


def search_query(dataset: str, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
    return search_by_vector(dataset=dataset, query_vector=embed_query(query), top_k=top_k)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run pgvector cosine search for precedent chunks.")
    parser.add_argument("--dataset", choices=["traffic", "fault_ratio"], required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=SEARCH_SETTINGS.default_top_k)
    parser.add_argument("--include-text", action="store_true", help="Print full chunk_text in JSON output.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    results = search_query(dataset=args.dataset, query=args.query, top_k=args.top_k)
    if not args.include_text:
        for row in results:
            row["chunk_text"] = row["chunk_text"][:300]
            row["search_text"] = row["search_text"][:300]
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
