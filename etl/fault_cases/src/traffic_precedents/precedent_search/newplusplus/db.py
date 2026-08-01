"""독립 NEW++ pgvector 연결과 상태 점검."""

from __future__ import annotations

import os
from collections.abc import Mapping
from contextlib import contextmanager
from typing import Any, Iterator

from .errors import SearchStageError


def resolve_connection_target(
    environ: Mapping[str, str] | None = None,
) -> tuple[str | None, dict[str, object]]:
    """Resolve an explicit NEW++ DSN or the existing Pilot PostgreSQL settings."""

    env = os.environ if environ is None else environ
    explicit = str(env.get("PRECEDENT_NEWPLUSPLUS_DSN") or "").strip()
    if explicit:
        return explicit, {}

    required = (
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
    )
    if any(not str(env.get(key) or "").strip() for key in required):
        raise SearchStageError(
            "DATABASE_NOT_READY",
            "판례 데이터베이스 연결 설정이 필요합니다.",
            "database",
        )

    return None, {
        "host": env["POSTGRES_HOST"],
        "port": int(env["POSTGRES_PORT"]),
        "dbname": env["POSTGRES_DB"],
        "user": env["POSTGRES_USER"],
        "password": env["POSTGRES_PASSWORD"],
        "sslmode": env.get("PGSSLMODE", "require"),
    }


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
        dsn, kwargs = resolve_connection_target()
        connection_context = (
            psycopg.connect(dsn) if dsn is not None else psycopg.connect(**kwargs)
        )
        with connection_context as connection:
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
          active.active_seed_version,
          count(blocks.block_id)::int AS blocks,
          count(DISTINCT blocks.record_id)::int AS cases,
          min(vector_dims(blocks.embedding))::int AS min_dims,
          max(vector_dims(blocks.embedding))::int AS max_dims
        FROM precedent_newplusplus.block_versions AS blocks
        JOIN precedent_newplusplus.active_seed AS active
          ON active.active_seed_version = blocks.seed_version
        WHERE active.singleton IS TRUE
        GROUP BY active.active_seed_version
    """
    with connect_database() as connection, connection.cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()
    if row is None:
        return {
            "ready": False,
            "active_seed_version": None,
            "blocks": 0,
            "cases": 0,
            "vector_dims": None,
        }
    active_seed_version, blocks, cases, min_dims, max_dims = row
    return {
        "ready": blocks == 3339 and cases == 825 and min_dims == max_dims == 2560,
        "active_seed_version": active_seed_version,
        "blocks": blocks,
        "cases": cases,
        "vector_dims": min_dims if min_dims == max_dims else None,
    }
