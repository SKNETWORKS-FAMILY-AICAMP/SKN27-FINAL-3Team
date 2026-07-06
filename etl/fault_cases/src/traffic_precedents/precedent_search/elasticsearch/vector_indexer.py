from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Any, Iterable

from elasticsearch import Elasticsearch, helpers
from psycopg2.extras import RealDictCursor

from etl.fault_cases.src.traffic_precedents.precedent_db_loading.db import get_connection

from .client import get_elasticsearch_client
from .bm25_indexer import bm25_nori_mapping
from ..search_config import (
    DATASET_SEARCH_CONFIGS,
    ELASTICSEARCH_SETTINGS,
    SEARCH_SETTINGS,
    ElasticsearchSettings,
    SearchSettings,
    ensure_parent,
)


def parse_pgvector_value(value: Any) -> list[float]:
    if value is None:
        return []
    if isinstance(value, list | tuple):
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
    exists = client.indices.exists(index=index_name)
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


def fetch_chunks_with_embeddings(
    db_name: str,
    case_table: str,
    chunk_table: str,
    embedding_table: str,
    search_settings: SearchSettings,
) -> Iterable[dict[str, Any]]:
    sql = f"""
        SELECT
            c.case_id,
            c.chunk_id,
            c.chunk_index,
            c.chunk_type,
            c.chunk_strategy,
            c.chunk_text,
            c.search_text,
            c.source_fields,
            c.metadata,
            p.case_name,
            p.case_number,
            p.court_name,
            p.decision_date::text AS decision_date,
            e.embedding_model,
            e.embedding_version,
            e.embedding_dim,
            e.embedding_vector
        FROM {chunk_table} c
        JOIN {case_table} p ON p.case_id = c.case_id
        JOIN {embedding_table} e ON e.chunk_id = c.chunk_id
        WHERE c.chunk_text IS NOT NULL
          AND btrim(c.chunk_text) <> ''
          AND e.embedding_model = %s
          AND e.embedding_version = %s
          AND e.embedding_dim = %s
          AND e.embedding_vector IS NOT NULL
        ORDER BY c.case_id, c.chunk_index
    """
    params = (
        search_settings.embedding_model,
        search_settings.embedding_version,
        search_settings.embedding_dim,
    )
    with get_connection(db_name) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            for row in cur:
                yield dict(row)


def build_action(
    dataset: str,
    index_name: str,
    index_version: str,
    row: dict[str, Any],
) -> dict[str, Any] | None:
    chunk_text = row.get("chunk_text") or ""
    search_text = row.get("search_text") or chunk_text
    embedding_vector = parse_pgvector_value(row.get("embedding_vector"))
    if not embedding_vector:
        return None
    source = {
        "dataset": dataset,
        "case_id": str(row["case_id"]),
        "chunk_id": row["chunk_id"],
        "chunk_index": row["chunk_index"],
        "chunk_type": row["chunk_type"],
        "chunk_strategy": row["chunk_strategy"],
        "case_name": row.get("case_name"),
        "case_number": row.get("case_number"),
        "court_name": row.get("court_name"),
        "decision_date": row.get("decision_date") or None,
        "chunk_text": chunk_text,
        "search_text": search_text,
        "chunk_text_standard": chunk_text,
        "search_text_standard": search_text,
        "metadata": row.get("metadata") or {},
        "source_fields": row.get("source_fields") or {},
        "embedding_model": row.get("embedding_model"),
        "embedding_version": row.get("embedding_version"),
        "embedding_dim": row.get("embedding_dim"),
        "embedding_vector": embedding_vector,
        "indexed_at": datetime.now().isoformat(timespec="seconds"),
        "index_version": index_version,
    }
    return {"_op_type": "index", "_index": index_name, "_id": row["chunk_id"], "_source": source}


def index_dataset(
    dataset: str,
    recreate: bool = False,
    limit: int | None = None,
    settings: ElasticsearchSettings = ELASTICSEARCH_SETTINGS,
    search_settings: SearchSettings = SEARCH_SETTINGS,
) -> dict[str, Any]:
    config = DATASET_SEARCH_CONFIGS[dataset]
    client = get_elasticsearch_client(settings)
    index_name = config["elasticsearch_vector_index"]
    index_status = ensure_vector_index(
        client=client,
        index_name=index_name,
        embedding_dim=search_settings.embedding_dim,
        recreate=recreate,
    )

    selected_count = 0
    skipped_count = 0

    def actions() -> Iterable[dict[str, Any]]:
        nonlocal selected_count, skipped_count
        rows = fetch_chunks_with_embeddings(
            db_name=config["db_name"],
            case_table=config["case_table"],
            chunk_table=config["chunk_table"],
            embedding_table=config["embedding_table"],
            search_settings=search_settings,
        )
        for row in rows:
            if limit is not None and selected_count >= limit:
                break
            action = build_action(
                dataset=dataset,
                index_name=index_name,
                index_version=settings.vector_index_version,
                row=row,
            )
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
        "dataset": dataset,
        "retriever": "elasticsearch_vector_cosine",
        "db_name": config["db_name"],
        "case_table": config["case_table"],
        "chunk_table": config["chunk_table"],
        "embedding_table": config["embedding_table"],
        "elasticsearch_host": settings.host,
        "elasticsearch_index": index_name,
        "index_version": settings.vector_index_version,
        "embedding_model": search_settings.embedding_model,
        "embedding_version": search_settings.embedding_version,
        "embedding_dim": search_settings.embedding_dim,
        "recreate": recreate,
        "limit": limit,
        "index_status": index_status,
        "selected_chunk_count": selected_count,
        "skipped_chunk_count": skipped_count,
        "bulk_success_count": int(success_count),
        "bulk_error_count": len(errors) if isinstance(errors, list) else 0,
        "indexed_document_count_after": indexed_count,
    }
    report_path = config["elasticsearch_vector_index_report_path"]
    ensure_parent(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create Elasticsearch dense_vector indexes from PostgreSQL embeddings.")
    parser.add_argument("--dataset", choices=["traffic", "fault_ratio", "all"], default="all")
    parser.add_argument("--recreate", action="store_true", help="Delete and recreate the target ES vector index first.")
    parser.add_argument("--limit", type=int, default=None, help="Index only N chunks for smoke testing.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    datasets = DATASET_SEARCH_CONFIGS.keys() if args.dataset == "all" else [args.dataset]
    reports = {
        dataset: index_dataset(dataset=dataset, recreate=args.recreate, limit=args.limit) for dataset in datasets
    }
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
