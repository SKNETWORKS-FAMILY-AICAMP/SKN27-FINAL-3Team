from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Any, Iterable

from elasticsearch import Elasticsearch, helpers
from psycopg2.extras import Json, RealDictCursor

from etl.fault_cases.src.review_case.db_loading.db_config import (
    ELASTICSEARCH_EXPORT_ROOT,
    ELASTICSEARCH_SETTINGS,
    SETTINGS,
    ElasticsearchSettings,
)
from etl.fault_cases.src.review_case.db_loading.db_connection import get_connection

from .client import get_elasticsearch_client


def bm25_nori_mapping(settings: ElasticsearchSettings = ELASTICSEARCH_SETTINGS) -> dict[str, Any]:
    analyzer_name = settings.analyzer_name
    return {
        "settings": {
            "analysis": {
                "analyzer": {
                    analyzer_name: {
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
                "source_type": {"type": "keyword"},
                "review_case_id": {"type": "keyword"},
                "review_no": {"type": "keyword"},
                "chunk_id": {"type": "keyword"},
                "chunk_type": {"type": "keyword"},
                "part_index": {"type": "integer"},
                "sequence_no": {"type": "integer"},
                "party_type": {"type": "keyword"},
                "case_title": {
                    "type": "text",
                    "analyzer": analyzer_name,
                    "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                },
                "reference_chart_key": {"type": "keyword"},
                "decision_fault_ratio": {"type": "keyword"},
                "claimant_final_ratio": {"type": "integer"},
                "respondent_final_ratio": {"type": "integer"},
                "signal_condition": {"type": "keyword"},
                "road_feature": {"type": "keyword"},
                "standard_a_behavior": {"type": "keyword"},
                "standard_b_behavior": {"type": "keyword"},
                "header_accident_group": {"type": "keyword"},
                "header_road_context": {"type": "text", "analyzer": analyzer_name},
                "chunk_text": {"type": "text", "analyzer": analyzer_name},
                "search_text": {"type": "text", "analyzer": analyzer_name},
                "chunk_text_standard": {"type": "text", "analyzer": "standard"},
                "search_text_standard": {"type": "text", "analyzer": "standard"},
                "standard_scenario_keywords": {"type": "keyword"},
                "quality_flags": {"type": "keyword"},
                "source_reliability_score": {"type": "integer"},
                "raw_json": {"type": "object", "enabled": False},
                "indexed_at": {"type": "date"},
                "index_version": {"type": "keyword"},
            },
        },
    }


def ensure_index(client: Elasticsearch, index_name: str, recreate: bool = False) -> dict[str, Any]:
    exists = bool(client.indices.exists(index=index_name))
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


def fetch_chunks() -> Iterable[dict[str, Any]]:
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
            d.standard_b_behavior
        FROM review_case_chunks c
        JOIN review_case_documents d ON d.review_case_id = c.review_case_id
        WHERE c.search_text IS NOT NULL
          AND btrim(c.search_text) <> ''
        ORDER BY c.review_case_id, c.sequence_no, c.chunk_type
    """
    with get_connection(SETTINGS.review_case_db) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query)
            for row in cur:
                yield dict(row)


def build_action(index_name: str, index_version: str, row: dict[str, Any]) -> dict[str, Any]:
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
        "indexed_at": datetime.now().isoformat(timespec="seconds"),
        "index_version": index_version,
    }
    return {"_op_type": "index", "_index": index_name, "_id": row["chunk_id"], "_source": source}


def start_index_job(index_name: str, analyzer: str, target_count: int) -> str:
    job_id = "review_case_es_bm25_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    with get_connection(SETTINGS.review_case_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO review_case_elasticsearch_index_jobs (
                    index_job_id, index_name, index_mode, analyzer, target_chunk_count,
                    indexed_chunk_count, failed_count, status, started_at
                )
                VALUES (%s, %s, %s, %s, %s, 0, 0, 'running', now())
                """,
                (job_id, index_name, "bm25_nori", analyzer, target_count),
            )
    return job_id


def finish_index_job(job_id: str, indexed_count: int, failed_count: int, status: str, error_summary: dict[str, Any]) -> None:
    with get_connection(SETTINGS.review_case_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE review_case_elasticsearch_index_jobs
                SET indexed_chunk_count = %s,
                    failed_count = %s,
                    status = %s,
                    error_summary = %s,
                    finished_at = now()
                WHERE index_job_id = %s
                """,
                (indexed_count, failed_count, status, Json(error_summary), job_id),
            )


def mark_chunks_indexed(index_name: str, chunk_ids: list[str]) -> None:
    if not chunk_ids:
        return
    with get_connection(SETTINGS.review_case_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE review_case_chunks
                SET indexed_to_elasticsearch = true,
                    elasticsearch_index_name = %s,
                    updated_at = now()
                WHERE chunk_id = ANY(%s)
                """,
                (index_name, chunk_ids),
            )


def count_source_chunks() -> int:
    with get_connection(SETTINGS.review_case_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM review_case_chunks
                WHERE search_text IS NOT NULL
                  AND btrim(search_text) <> ''
                """
            )
            return int(cur.fetchone()[0])


def index_review_case_chunks(
    recreate: bool = False,
    limit: int | None = None,
    settings: ElasticsearchSettings = ELASTICSEARCH_SETTINGS,
) -> dict[str, Any]:
    client = get_elasticsearch_client(settings)
    index_name = settings.bm25_index_name
    index_status = ensure_index(client=client, index_name=index_name, recreate=recreate)
    target_count = count_source_chunks()
    job_id = start_index_job(index_name=index_name, analyzer=settings.analyzer_name, target_count=target_count)

    selected_count = 0
    selected_chunk_ids: list[str] = []

    def actions() -> Iterable[dict[str, Any]]:
        nonlocal selected_count
        for row in fetch_chunks():
            if limit is not None and selected_count >= limit:
                break
            selected_count += 1
            selected_chunk_ids.append(row["chunk_id"])
            yield build_action(index_name=index_name, index_version=settings.bm25_index_version, row=row)

    success_count, errors = helpers.bulk(
        client.options(request_timeout=settings.request_timeout),
        actions(),
        chunk_size=settings.bulk_chunk_size,
        raise_on_error=False,
    )
    client.indices.refresh(index=index_name)
    indexed_count = int(client.count(index=index_name)["count"])
    failed_count = len(errors) if isinstance(errors, list) else 0
    status = "success" if failed_count == 0 else "partial_failed"
    mark_chunks_indexed(index_name=index_name, chunk_ids=selected_chunk_ids)
    finish_index_job(
        job_id=job_id,
        indexed_count=int(success_count),
        failed_count=failed_count,
        status=status,
        error_summary={"errors": errors[:5] if isinstance(errors, list) else errors},
    )

    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "db_name": SETTINGS.review_case_db,
        "retriever": "elasticsearch_bm25_nori",
        "index_job_id": job_id,
        "elasticsearch_host": settings.host,
        "elasticsearch_index": index_name,
        "index_version": settings.bm25_index_version,
        "analyzer": settings.analyzer_name,
        "source_field": "search_text",
        "recreate": recreate,
        "limit": limit,
        "index_status": index_status,
        "target_chunk_count": target_count,
        "selected_chunk_count": selected_count,
        "bulk_success_count": int(success_count),
        "bulk_error_count": failed_count,
        "indexed_document_count_after": indexed_count,
    }
    report_path = ELASTICSEARCH_EXPORT_ROOT / settings.bm25_index_report_name
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create Elasticsearch BM25/Nori index for review case chunks.")
    parser.add_argument("--recreate", action="store_true", help="Delete and recreate the target ES index first.")
    parser.add_argument("--limit", type=int, default=None, help="Index only N chunks for smoke testing.")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    print(json.dumps(index_review_case_chunks(recreate=args.recreate, limit=args.limit), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
