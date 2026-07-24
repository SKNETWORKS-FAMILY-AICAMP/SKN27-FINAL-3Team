"""Validated review-case source loading for the production RAG seed."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from psycopg2.extras import Json, execute_values

from etl.fault_cases.src.review_case.db_loading.db_config import SETTINGS
from etl.fault_cases.src.review_case.db_loading.db_connection import (
    get_connection,
)


MIN_CHUNK_TEXT_LENGTH = 20


class ReviewCaseSeedError(ValueError):
    """Raised before database work when a review-case seed is not safe to load."""


@dataclass(frozen=True)
class ReviewCaseSeedRow:
    review_case_id: str
    review_no: str
    chunk_id: str
    chunk_type: str
    chunk_text: str
    search_text: str
    sequence_no: int
    source_ref: str
    source_type: str
    source_reliability_score: int
    parse_status: str
    quality_flags: list[str]
    raw_json: dict[str, Any]


def read_review_case_seed_rows(path: Path) -> list[ReviewCaseSeedRow]:
    """Read and validate every row before any database connection is opened."""

    if not path.is_file():
        raise ReviewCaseSeedError(f"review-case seed file not found: {path}")

    rows: list[ReviewCaseSeedRow] = []
    chunk_ids: set[str] = set()
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ReviewCaseSeedError(
                    f"invalid JSON at {path}:{line_number}: {exc}"
                ) from exc
            if not isinstance(payload, dict):
                raise ReviewCaseSeedError(
                    f"row at {path}:{line_number} must be a JSON object"
                )

            row = _parse_row(payload, path=path, line_number=line_number)
            if row.chunk_id in chunk_ids:
                raise ReviewCaseSeedError(
                    f"duplicate chunk_id at {path}:{line_number}: {row.chunk_id}"
                )
            chunk_ids.add(row.chunk_id)
            rows.append(row)

    if not rows:
        raise ReviewCaseSeedError(f"review-case seed file is empty: {path}")
    return rows


def replace_and_upsert_review_case_rows(
    rows: Sequence[ReviewCaseSeedRow],
    *,
    replace: bool = False,
) -> dict[str, int]:
    """Upsert validated review-case source rows in one database transaction."""

    if not rows:
        raise ReviewCaseSeedError("review-case seed rows must not be empty")

    documents: dict[str, ReviewCaseSeedRow] = {}
    chunk_ids: set[str] = set()
    for row in rows:
        if row.chunk_id in chunk_ids:
            raise ReviewCaseSeedError(f"duplicate chunk_id: {row.chunk_id}")
        chunk_ids.add(row.chunk_id)
        existing = documents.get(row.review_case_id)
        if existing is not None and existing.review_no != row.review_no:
            raise ReviewCaseSeedError(
                "conflicting review_no values for review_case_id "
                f"{row.review_case_id}"
            )
        documents.setdefault(row.review_case_id, row)

    document_values = [
        (
            row.review_case_id,
            row.review_no,
            row.source_ref,
            row.source_type,
            row.source_reliability_score,
            row.parse_status,
            Json(row.quality_flags),
            Json(row.raw_json),
        )
        for row in documents.values()
    ]
    chunk_values = [
        (
            row.chunk_id,
            row.review_case_id,
            row.review_no,
            row.chunk_type,
            row.sequence_no,
            row.chunk_text,
            row.search_text,
            len(row.chunk_text),
            len(row.search_text.split()),
            hashlib.sha256(row.chunk_text.encode("utf-8")).hexdigest(),
            row.source_ref,
            row.source_type,
            row.source_reliability_score,
            row.parse_status,
            Json(row.quality_flags),
            Json(row.raw_json),
        )
        for row in rows
    ]

    document_sql = """
        INSERT INTO review_case_documents (
            review_case_id, review_no, source_ref, source_type,
            source_reliability_score, parse_status, quality_flags, raw_json
        ) VALUES %s
        ON CONFLICT (review_case_id) DO UPDATE SET
            review_no = EXCLUDED.review_no,
            source_ref = EXCLUDED.source_ref,
            source_type = EXCLUDED.source_type,
            source_reliability_score = EXCLUDED.source_reliability_score,
            parse_status = EXCLUDED.parse_status,
            quality_flags = EXCLUDED.quality_flags,
            raw_json = EXCLUDED.raw_json,
            updated_at = now()
    """
    chunk_sql = """
        INSERT INTO review_case_chunks (
            chunk_id, review_case_id, review_no, chunk_type, sequence_no,
            chunk_text, search_text, char_count, token_count, text_hash,
            source_ref, source_type, source_reliability_score,
            parse_status, quality_flags, raw_json
        ) VALUES %s
        ON CONFLICT (chunk_id) DO UPDATE SET
            review_case_id = EXCLUDED.review_case_id,
            review_no = EXCLUDED.review_no,
            chunk_type = EXCLUDED.chunk_type,
            sequence_no = EXCLUDED.sequence_no,
            chunk_text = EXCLUDED.chunk_text,
            search_text = EXCLUDED.search_text,
            char_count = EXCLUDED.char_count,
            token_count = EXCLUDED.token_count,
            embedding_status = CASE
                WHEN review_case_chunks.text_hash
                     IS DISTINCT FROM EXCLUDED.text_hash
                THEN 'pending'
                ELSE review_case_chunks.embedding_status
            END,
            text_hash = EXCLUDED.text_hash,
            source_ref = EXCLUDED.source_ref,
            source_type = EXCLUDED.source_type,
            source_reliability_score = EXCLUDED.source_reliability_score,
            parse_status = EXCLUDED.parse_status,
            quality_flags = EXCLUDED.quality_flags,
            raw_json = EXCLUDED.raw_json,
            updated_at = now()
    """

    with get_connection(SETTINGS.review_case_db) as conn:
        with conn.cursor() as cursor:
            if replace:
                cursor.execute(
                    """
                    DELETE FROM review_case_documents
                    WHERE source_type = %s
                    """,
                    ("review_case",),
                )
            execute_values(
                cursor,
                document_sql,
                document_values,
                page_size=500,
            )
            execute_values(
                cursor,
                chunk_sql,
                chunk_values,
                page_size=500,
            )

    return {
        "review_case_documents": len(document_values),
        "review_case_chunks": len(chunk_values),
    }


def _parse_row(
    payload: dict[str, Any],
    *,
    path: Path,
    line_number: int,
) -> ReviewCaseSeedRow:
    location = f"{path}:{line_number}"
    review_case_id = _required_text(payload, "review_case_id", location)
    review_no = _required_text(payload, "review_no", location)
    chunk_id = _required_text(payload, "chunk_id", location)
    chunk_text = _required_text(payload, "chunk_text", location)
    if len("".join(chunk_text.split())) < MIN_CHUNK_TEXT_LENGTH:
        raise ReviewCaseSeedError(
            f"chunk_text at {location} must contain at least "
            f"{MIN_CHUNK_TEXT_LENGTH} non-whitespace characters"
        )

    sequence_value = payload.get("sequence_no", 0)
    if isinstance(sequence_value, bool):
        raise ReviewCaseSeedError(
            f"sequence_no at {location} must be a non-negative integer"
        )
    try:
        sequence_no = int(sequence_value)
    except (TypeError, ValueError) as exc:
        raise ReviewCaseSeedError(
            f"sequence_no at {location} must be a non-negative integer"
        ) from exc
    if sequence_no < 0:
        raise ReviewCaseSeedError(
            f"sequence_no at {location} must be a non-negative integer"
        )

    quality_value = payload.get("quality_flags") or []
    if not isinstance(quality_value, list) or not all(
        isinstance(item, str) for item in quality_value
    ):
        raise ReviewCaseSeedError(
            f"quality_flags at {location} must be a list of strings"
        )

    reliability_value = payload.get("source_reliability_score", 3)
    if isinstance(reliability_value, bool):
        raise ReviewCaseSeedError(
            f"source_reliability_score at {location} must be an integer"
        )
    try:
        source_reliability_score = int(reliability_value)
    except (TypeError, ValueError) as exc:
        raise ReviewCaseSeedError(
            f"source_reliability_score at {location} must be an integer"
        ) from exc

    search_text = str(payload.get("search_text") or chunk_text).strip()
    return ReviewCaseSeedRow(
        review_case_id=review_case_id,
        review_no=review_no,
        chunk_id=chunk_id,
        chunk_type=str(payload.get("chunk_type") or "case_chunk").strip(),
        chunk_text=chunk_text,
        search_text=search_text,
        sequence_no=sequence_no,
        source_ref=str(
            payload.get("source_ref") or f"review_case:{review_no}"
        ).strip(),
        source_type=str(payload.get("source_type") or "review_case").strip(),
        source_reliability_score=source_reliability_score,
        parse_status=str(payload.get("parse_status") or "valid").strip(),
        quality_flags=list(quality_value),
        raw_json=dict(payload),
    )


def _required_text(
    payload: dict[str, Any],
    key: str,
    location: str,
) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ReviewCaseSeedError(
            f"missing required review-case seed field {key} at {location}"
        )
    return value
