from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from psycopg2.extras import Json, execute_values

from .db_config import SETTINGS
from .db_connection import get_connection
from .search_text_builder import build_search_text


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            row.setdefault("_jsonl_line_no", line_no)
            yield row


def as_json(value: Any, default: Any = None) -> Json:
    if value is None:
        value = [] if default is None else default
    return Json(value, dumps=lambda obj: json.dumps(obj, ensure_ascii=False))


def text_hash(value: str | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def make_search_text(row: dict[str, Any], document_by_id: dict[str, dict[str, Any]]) -> str:
    doc = document_by_id.get(row.get("review_case_id") or "", {})
    return build_search_text(row, doc)


def execute_upsert(
    table_name: str,
    columns: list[str],
    values: Iterable[tuple[Any, ...]],
    conflict_columns: list[str],
    batch_size: int = 500,
) -> int:
    update_columns = [column for column in columns if column not in conflict_columns]
    column_sql = ", ".join(columns)
    conflict_sql = ", ".join(conflict_columns)
    update_sql = ", ".join(f"{column} = EXCLUDED.{column}" for column in update_columns)
    sql = f"""
        INSERT INTO {table_name} ({column_sql})
        VALUES %s
        ON CONFLICT ({conflict_sql}) DO UPDATE SET
            {update_sql},
            updated_at = now()
    """
    total = 0
    batch: list[tuple[Any, ...]] = []
    with get_connection(SETTINGS.review_case_db) as conn:
        with conn.cursor() as cur:
            for value in values:
                batch.append(value)
                if len(batch) >= batch_size:
                    execute_values(cur, sql, batch, page_size=batch_size)
                    total += len(batch)
                    batch.clear()
            if batch:
                execute_values(cur, sql, batch, page_size=batch_size)
                total += len(batch)
    return total


def execute_insert_replace(
    table_name: str,
    columns: list[str],
    values: Iterable[tuple[Any, ...]],
    batch_size: int = 500,
) -> int:
    column_sql = ", ".join(columns)
    sql = f"INSERT INTO {table_name} ({column_sql}) VALUES %s"
    total = 0
    batch: list[tuple[Any, ...]] = []
    with get_connection(SETTINGS.review_case_db) as conn:
        with conn.cursor() as cur:
            cur.execute(f"TRUNCATE TABLE {table_name} CASCADE")
            for value in values:
                batch.append(value)
                if len(batch) >= batch_size:
                    execute_values(cur, sql, batch, page_size=batch_size)
                    total += len(batch)
                    batch.clear()
            if batch:
                execute_values(cur, sql, batch, page_size=batch_size)
                total += len(batch)
    return total
