"""독립 NEW++ pgvector 연결과 상태 점검."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

from .errors import SearchStageError


def database_dsn() -> str:
    value = os.environ.get("PRECEDENT_NEWPLUSPLUS_DSN", "").strip()
    if not value:
        raise SearchStageError(
            "DATABASE_NOT_READY",
            "PRECEDENT_NEWPLUSPLUS_DSN 환경변수가 필요합니다.",
            "database",
        )
    return value


@contextmanager
def connect_database() -> Iterator[Any]:
    try:
        import psycopg
    except ImportError as exc:
        raise SearchStageError(
            "DB_DRIVER_MISSING", "psycopg가 설치되지 않았습니다.", "database"
        ) from exc
    try:
        with psycopg.connect(database_dsn()) as connection:
            yield connection
    except SearchStageError:
        raise
    except Exception as exc:
        raise SearchStageError(
            "DATABASE_NOT_READY", "판례 테스트 DB에 연결할 수 없습니다.", "database", True
        ) from exc


def database_readiness() -> dict[str, Any]:
    sql = """
        SELECT
          count(*)::int AS blocks,
          count(DISTINCT record_id)::int AS cases,
          min(vector_dims(embedding))::int AS min_dims,
          max(vector_dims(embedding))::int AS max_dims
        FROM precedent_newplusplus.blocks
    """
    with connect_database() as connection, connection.cursor() as cursor:
        cursor.execute(sql)
        blocks, cases, min_dims, max_dims = cursor.fetchone()
    return {
        "ready": blocks == 3339 and cases == 825 and min_dims == max_dims == 2560,
        "blocks": blocks,
        "cases": cases,
        "vector_dims": min_dims if min_dims == max_dims else None,
    }
