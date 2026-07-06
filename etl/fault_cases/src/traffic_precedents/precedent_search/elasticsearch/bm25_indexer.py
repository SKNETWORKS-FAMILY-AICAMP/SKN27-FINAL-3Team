from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Any, Iterable

from elasticsearch import Elasticsearch, helpers
from psycopg2.extras import RealDictCursor

from etl.fault_cases.src.traffic_precedents.precedent_db_loading.db import get_connection

from .client import get_elasticsearch_client
from ..search_config import (
    DATASET_SEARCH_CONFIGS,
    ELASTICSEARCH_SETTINGS,
    ElasticsearchSettings,
    ensure_parent,
)


def bm25_nori_mapping() -> dict[str, Any]:
    return {
        "settings": {
            "analysis": {
                "analyzer": {
                    "precedent_nori": {
                        "type": "custom",
                        "tokenizer": "nori_tokenizer",
                        "filter": ["lowercase", "nori_part_of_speech"],
                    }
                }
            }
        },
        "mappings": {
            "dynamic": False,
            "properties": {
                "dataset": {"type": "keyword"},
                "case_id": {"type": "keyword"},
                "chunk_id": {"type": "keyword"},
                "chunk_index": {"type": "integer"},
                "chunk_type": {"type": "keyword"},
                "chunk_strategy": {"type": "keyword"},
                "case_name": {
                    "type": "text",
                    "analyzer": "precedent_nori",
                    "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                },
                "case_number": {"type": "keyword"},
                "court_name": {"type": "keyword"},
                "decision_date": {"type": "date", "ignore_malformed": True},
                "chunk_text": {"type": "text", "analyzer": "precedent_nori"},
                "search_text": {"type": "text", "analyzer": "precedent_nori"},
                "chunk_text_standard": {"type": "text", "analyzer": "standard"},
                "search_text_standard": {"type": "text", "analyzer": "standard"},
                "metadata": {"type": "object", "enabled": False},
                "source_fields": {"type": "object", "enabled": False},
                "indexed_at": {"type": "date"},
                "index_version": {"type": "keyword"},
            },
        },
    }


def ensure_index(
    client: Elasticsearch,
    index_name: str,
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
        client.indices.create(index=index_name, **bm25_nori_mapping())
        created = True

    return {"index_name": index_name, "created": created, "recreated": deleted_for_recreate}


def fetch_chunks(db_name: str, case_table: str, chunk_table: str) -> Iterable[dict[str, Any]]:
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
            p.decision_date::text AS decision_date
        FROM {chunk_table} c
        JOIN {case_table} p ON p.case_id = c.case_id
        WHERE c.chunk_text IS NOT NULL
          AND btrim(c.chunk_text) <> ''
        ORDER BY c.case_id, c.chunk_index
    """
    with get_connection(db_name) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql)
            for row in cur:
                yield dict(row)


def build_action(
    dataset: str,
    index_name: str,
    index_version: str,
    row: dict[str, Any],
) -> dict[str, Any]:
    chunk_text = row.get("chunk_text") or ""
    search_text = row.get("search_text") or chunk_text
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
        "indexed_at": datetime.now().isoformat(timespec="seconds"),
        "index_version": index_version,
    }
    return {"_op_type": "index", "_index": index_name, "_id": row["chunk_id"], "_source": source}


def index_dataset(
    dataset: str,
    recreate: bool = False,
    limit: int | None = None,
    settings: ElasticsearchSettings = ELASTICSEARCH_SETTINGS,
) -> dict[str, Any]:
    config = DATASET_SEARCH_CONFIGS[dataset]
    client = get_elasticsearch_client(settings)
    index_name = config["elasticsearch_index"]
    index_status = ensure_index(client=client, index_name=index_name, recreate=recreate)

    selected_count = 0

    def actions() -> Iterable[dict[str, Any]]:
        nonlocal selected_count
        rows = fetch_chunks(
            db_name=config["db_name"],
            case_table=config["case_table"],
            chunk_table=config["chunk_table"],
        )
        for row in rows:
            if limit is not None and selected_count >= limit:
                break
            selected_count += 1
            yield build_action(
                dataset=dataset,
                index_name=index_name,
                index_version=settings.bm25_index_version,
                row=row,
            )

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
        "retriever": "elasticsearch_bm25_nori",
        "db_name": config["db_name"],
        "case_table": config["case_table"],
        "chunk_table": config["chunk_table"],
        "elasticsearch_host": settings.host,
        "elasticsearch_index": index_name,
        "index_version": settings.bm25_index_version,
        "analyzer": "precedent_nori",
        "recreate": recreate,
        "limit": limit,
        "index_status": index_status,
        "selected_chunk_count": selected_count,
        "bulk_success_count": int(success_count),
        "bulk_error_count": len(errors) if isinstance(errors, list) else 0,
        "indexed_document_count_after": indexed_count,
    }
    report_path = config["elasticsearch_index_report_path"]
    ensure_parent(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create Elasticsearch BM25/Nori indexes for precedent chunks.")
    parser.add_argument("--dataset", choices=["traffic", "fault_ratio", "all"], default="all")
    parser.add_argument("--recreate", action="store_true", help="Delete and recreate the target ES index first.")
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
