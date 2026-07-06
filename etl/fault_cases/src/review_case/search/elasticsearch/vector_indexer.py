from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Any, Iterable

from elasticsearch import Elasticsearch, helpers
from psycopg2.extras import RealDictCursor

from etl.fault_cases.src.review_case.db_loading.db_config import (
    ELASTICSEARCH_EXPORT_ROOT,
    ELASTICSEARCH_SETTINGS,
    EMBEDDING_SETTINGS,
    SETTINGS,
    ElasticsearchSettings,
)
from etl.fault_cases.src.review_case.db_loading.db_connection import get_connection

from .bm25_indexer import bm25_nori_mapping
from .client import get_elasticsearch_client


def parse_pgvector_value(value: Any) -> list[float]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [float(item) for item in value]
    text = str(value).strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    if not text:
        return []
    return [float(item) for item in text.split(",")]


def vector_hybrid_mapping(embedding_dim: int) -> dict[str, Any]:
    mapping = bm25_nori_mapping()
    mapping["mappings"]["properties"]["embedding_vector"] = {
        "type": "dense_vector",
        "dims": embedding_dim,
        "index": True,
        "similarity": "cosine",
    }
    mapping["mappings"]["properties"]["embedding_model"] = {"type": "keyword"}
    mapping["mappings"]["properties"]["embedding_version"] = {"type": "keyword"}
    mapping["mappings"]["properties"]["embedding_dim"] = {"type": "integer"}
    return mapping


def ensure_vector_index(
    client: Elasticsearch,
    index_name: str,
    embedding_dim: int,
    recreate: bool = False,
) -> dict[str, Any]:
    exists = bool(client.indices.exists(index=index_name))
    deleted_for_recreate = False
    if exists and recreate:
        client.indices.delete(index=index_name)
        exists = False
        deleted_for_recreate = True

    created = False
    if not exists:
        client.indices.create(index=index_name, **vector_hybrid_mapping(embedding_dim))
        created = True

    return {"index_name": index_name, "created": created, "recreated": deleted_for_recreate}


def fetch_chunks_with_embeddings() -> Iterable[dict[str, Any]]:
    query = """
        SELECT
            c.review_case_id,
            c.review_no,
            c.chunk_id,
            c.chunk_type,
            c.part_index,
            c.sequence_no,
            c.chunk_text,
            c.search_text,
            c.party_type,
            c.case_title,
            c.reference_chart_key,
            c.standard_scenario_keywords,
            c.decision_fault_ratio,
            c.claimant_final_ratio,
            c.respondent_final_ratio,
            c.source_type,
            c.source_reliability_score,
            c.quality_flags,
            c.raw_json,
            d.header_accident_group,
            d.header_road_context,
            d.signal_condition,
            d.road_feature,
            d.standard_a_behavior,
            d.standard_b_behavior,
            e.embedding_model,
            e.embedding_version,
            e.embedding_dim,
            e.embedding_vector
        FROM review_case_chunks c
        JOIN review_case_documents d ON d.review_case_id = c.review_case_id
        JOIN review_case_chunk_embeddings e ON e.chunk_id = c.chunk_id
        WHERE c.search_text IS NOT NULL
          AND btrim(c.search_text) <> ''
          AND e.embedding_model = %s
          AND e.embedding_version = %s
          AND e.embedding_dim = %s
          AND e.embedding_vector IS NOT NULL
        ORDER BY c.review_case_id, c.sequence_no, c.chunk_type
    """
    params = (EMBEDDING_SETTINGS.model, EMBEDDING_SETTINGS.version, EMBEDDING_SETTINGS.dim)
    with get_connection(SETTINGS.review_case_db) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            for row in cur:
                yield dict(row)


def build_action(index_name: str, index_version: str, row: dict[str, Any]) -> dict[str, Any] | None:
    embedding_vector = parse_pgvector_value(row.get("embedding_vector"))
    if not embedding_vector:
        return None
    chunk_text = row.get("chunk_text") or ""
    search_text = row.get("search_text") or chunk_text
    source = {
        "source_type": row.get("source_type") or "review_case",
        "review_case_id": row.get("review_case_id"),
        "review_no": row.get("review_no"),
        "chunk_id": row.get("chunk_id"),
        "chunk_type": row.get("chunk_type"),
        "part_index": row.get("part_index"),
        "sequence_no": row.get("sequence_no"),
        "party_type": row.get("party_type"),
        "case_title": row.get("case_title"),
        "reference_chart_key": row.get("reference_chart_key"),
        "decision_fault_ratio": row.get("decision_fault_ratio"),
        "claimant_final_ratio": row.get("claimant_final_ratio"),
        "respondent_final_ratio": row.get("respondent_final_ratio"),
        "signal_condition": row.get("signal_condition"),
        "road_feature": row.get("road_feature"),
        "standard_a_behavior": row.get("standard_a_behavior"),
        "standard_b_behavior": row.get("standard_b_behavior"),
        "header_accident_group": row.get("header_accident_group"),
        "header_road_context": row.get("header_road_context"),
        "chunk_text": chunk_text,
        "search_text": search_text,
        "chunk_text_standard": chunk_text,
        "search_text_standard": search_text,
        "standard_scenario_keywords": row.get("standard_scenario_keywords") or [],
        "quality_flags": row.get("quality_flags") or [],
        "source_reliability_score": row.get("source_reliability_score"),
        "raw_json": row.get("raw_json") or {},
        "embedding_model": row.get("embedding_model"),
        "embedding_version": row.get("embedding_version"),
        "embedding_dim": row.get("embedding_dim"),
        "embedding_vector": embedding_vector,
        "indexed_at": datetime.now().isoformat(timespec="seconds"),
        "index_version": index_version,
    }
    return {"_op_type": "index", "_index": index_name, "_id": row["chunk_id"], "_source": source}


def index_review_case_vectors(
    recreate: bool = False,
    limit: int | None = None,
    settings: ElasticsearchSettings = ELASTICSEARCH_SETTINGS,
) -> dict[str, Any]:
    client = get_elasticsearch_client(settings)
    index_name = settings.vector_index_name
    index_status = ensure_vector_index(
        client=client,
        index_name=index_name,
        embedding_dim=EMBEDDING_SETTINGS.dim,
        recreate=recreate,
    )

    selected_count = 0
    skipped_count = 0

    def actions() -> Iterable[dict[str, Any]]:
        nonlocal selected_count, skipped_count
        for row in fetch_chunks_with_embeddings():
            if limit is not None and selected_count >= limit:
                break
            action = build_action(index_name=index_name, index_version=settings.vector_index_version, row=row)
            if action is None:
                skipped_count += 1
                continue
            selected_count += 1
            yield action

    success_count, errors = helpers.bulk(
        client.options(request_timeout=settings.request_timeout),
        actions(),
        chunk_size=settings.bulk_chunk_size,
        raise_on_error=False,
    )
    client.indices.refresh(index=index_name)
    indexed_count = int(client.count(index=index_name)["count"])

    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "db_name": SETTINGS.review_case_db,
        "retriever": "elasticsearch_vector_cosine",
        "embedding_table": "review_case_chunk_embeddings",
        "elasticsearch_host": settings.host,
        "elasticsearch_index": index_name,
        "index_version": settings.vector_index_version,
        "embedding_model": EMBEDDING_SETTINGS.model,
        "embedding_version": EMBEDDING_SETTINGS.version,
        "embedding_dim": EMBEDDING_SETTINGS.dim,
        "recreate": recreate,
        "limit": limit,
        "index_status": index_status,
        "selected_chunk_count": selected_count,
        "skipped_chunk_count": skipped_count,
        "bulk_success_count": int(success_count),
        "bulk_error_count": len(errors) if isinstance(errors, list) else 0,
        "indexed_document_count_after": indexed_count,
    }
    report_path = ELASTICSEARCH_EXPORT_ROOT / settings.vector_index_report_name
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create Elasticsearch dense_vector index for review case chunks.")
    parser.add_argument("--recreate", action="store_true", help="Delete and recreate the target ES vector index first.")
    parser.add_argument("--limit", type=int, default=None, help="Index only N chunks for smoke testing.")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    print(json.dumps(index_review_case_vectors(recreate=args.recreate, limit=args.limit), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
