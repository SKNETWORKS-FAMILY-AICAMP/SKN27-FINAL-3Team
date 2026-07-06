from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from psycopg2.extras import Json, RealDictCursor, execute_values

from etl.fault_cases.src.traffic_precedents.precedent_db_loading.config import POSTGRES_EXPORT_ROOT
from etl.fault_cases.src.traffic_precedents.precedent_db_loading.db import get_connection

from .chunk_config import DEFAULT_CHUNK_CONFIG, ChunkConfig
from .text_builder import build_chunks


DATASET_DB_CONFIG = {
    "traffic": {
        "case_table": "traffic_precedent_cases",
        "chunk_table": "traffic_precedent_chunks",
        "report_path": POSTGRES_EXPORT_ROOT / "traffic" / "traffic_chunks_load_report.json",
    },
    "fault_ratio": {
        "case_table": "fault_ratio_precedent_cases",
        "chunk_table": "fault_ratio_precedent_chunks",
        "report_path": POSTGRES_EXPORT_ROOT / "fault_ratio" / "fault_ratio_chunks_load_report.json",
    },
}


def iter_cases(db_name: str, case_table: str):
    with get_connection(db_name) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"SELECT * FROM {case_table} ORDER BY decision_date DESC NULLS LAST, case_id")
            yield from cur.fetchall()


def estimate_tokens(text: str) -> int:
    # Lightweight approximation for reporting/index budgeting.
    return max(1, len(text) // 3)


def chunk_id_for(case_id: str, strategy: str, chunk_index: int) -> str:
    return f"{case_id}:{strategy}:{chunk_index:04d}"


def to_chunk_values(row: dict[str, Any], dataset: str, config: ChunkConfig):
    chunks = build_chunks(row, dataset=dataset, config=config)
    case_id = str(row["case_id"])
    values = []
    for index, chunk in enumerate(chunks):
        text_hash = hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
        metadata = {
            "dataset": dataset,
            "case_id": case_id,
            "case_name": row.get("case_name"),
            "case_number": row.get("case_number"),
            "court_name": row.get("court_name"),
            "decision_date": str(row.get("decision_date") or ""),
            "case_category": row.get("case_category"),
        }
        values.append(
            (
                chunk_id_for(case_id, config.strategy, index),
                case_id,
                index,
                chunk.chunk_type,
                config.strategy,
                chunk.text,
                chunk.text,
                len(chunk.text),
                estimate_tokens(chunk.text),
                text_hash,
                Json(chunk.source_fields, dumps=lambda obj: json.dumps(obj, ensure_ascii=False)),
                Json(metadata, dumps=lambda obj: json.dumps(obj, ensure_ascii=False)),
            )
        )
    return values


def upsert_chunks(db_name: str, chunk_table: str, chunk_values: list[tuple[Any, ...]], batch_size: int = 500) -> int:
    if not chunk_values:
        return 0

    base_columns = [
        "chunk_id",
        "case_id",
        "chunk_index",
        "chunk_type",
        "chunk_strategy",
        "chunk_text",
        "search_text",
        "char_count",
        "token_count",
        "text_hash",
        "source_fields",
        "metadata",
    ]
    optional_columns = []
    if chunk_table == "fault_ratio_precedent_chunks":
        optional_columns = ["contains_fault_ratio_terms", "contains_damage_terms", "contains_duty_terms"]
        expanded_values = []
        for value in chunk_values:
            chunk_text = str(value[5])
            expanded_values.append(
                value
                + (
                    any(term in chunk_text for term in ["과실", "책임비율", "과실상계", "구상금"]),
                    any(term in chunk_text for term in ["손해배상", "보험", "구상금", "손해"]),
                    any(term in chunk_text for term in ["주의의무", "전방주시", "안전운전", "신호위반"]),
                )
            )
        chunk_values = expanded_values

    columns = base_columns + optional_columns
    update_columns = [column for column in columns if column != "chunk_id"]
    column_sql = ", ".join(columns)
    update_sql = ", ".join(f"{column} = EXCLUDED.{column}" for column in update_columns)
    sql = f"""
        INSERT INTO {chunk_table} ({column_sql})
        VALUES %s
        ON CONFLICT (chunk_id) DO UPDATE SET
            {update_sql},
            embedding_status = CASE
                WHEN {chunk_table}.text_hash IS DISTINCT FROM EXCLUDED.text_hash THEN 'pending'
                ELSE {chunk_table}.embedding_status
            END,
            updated_at = now()
    """

    total = 0
    with get_connection(db_name) as conn:
        with conn.cursor() as cur:
            for start in range(0, len(chunk_values), batch_size):
                batch = chunk_values[start : start + batch_size]
                execute_values(cur, sql, batch, page_size=batch_size)
                total += len(batch)
    return total


def clear_existing_chunks(db_name: str, chunk_table: str) -> int:
    with get_connection(db_name) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {chunk_table}")
            return int(cur.rowcount)


def create_chunks(db_name: str, dataset: str, config: ChunkConfig = DEFAULT_CHUNK_CONFIG) -> dict[str, Any]:
    dataset_config = DATASET_DB_CONFIG[dataset]
    all_values = []
    case_count = 0
    chunk_type_counts: dict[str, int] = {}

    for row in iter_cases(db_name, dataset_config["case_table"]):
        case_count += 1
        values = to_chunk_values(dict(row), dataset=dataset, config=config)
        all_values.extend(values)
        for value in values:
            chunk_type_counts[value[3]] = chunk_type_counts.get(value[3], 0) + 1

    deleted_existing_chunks = clear_existing_chunks(db_name, dataset_config["chunk_table"])
    inserted_or_updated = upsert_chunks(db_name, dataset_config["chunk_table"], all_values)
    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": dataset,
        "db_name": db_name,
        "case_table": dataset_config["case_table"],
        "chunk_table": dataset_config["chunk_table"],
        "chunk_strategy": config.strategy,
        "chunk_size_chars": config.chunk_size_chars,
        "chunk_overlap_chars": config.chunk_overlap_chars,
        "case_count": case_count,
        "chunk_count": len(all_values),
        "deleted_existing_chunks": deleted_existing_chunks,
        "inserted_or_updated_chunks": inserted_or_updated,
        "chunk_type_counts": chunk_type_counts,
    }

    report_path = dataset_config["report_path"]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
