from __future__ import annotations

import importlib
import sys
import types

import pytest

from etl.fault_cases.src.traffic_precedents.precedent_search.newplusplus import db
from etl.fault_cases.src.traffic_precedents.precedent_search.newplusplus.errors import (
    SearchStageError,
)


def test_explicit_precedent_dsn_has_priority() -> None:
    dsn, kwargs = db.resolve_connection_target(
        {
            "PRECEDENT_NEWPLUSPLUS_DSN": "postgresql://explicit",
            "POSTGRES_HOST": "ignored.internal",
        }
    )

    assert dsn == "postgresql://explicit"
    assert kwargs == {}


def test_pilot_falls_back_to_existing_postgres_environment() -> None:
    dsn, kwargs = db.resolve_connection_target(
        {
            "POSTGRES_HOST": "db.internal",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "law_db",
            "POSTGRES_USER": "app_role",
            "POSTGRES_PASSWORD": "secret",
            "PGSSLMODE": "require",
        }
    )

    assert dsn is None
    assert kwargs == {
        "host": "db.internal",
        "port": 5432,
        "dbname": "law_db",
        "user": "app_role",
        "password": "secret",
        "sslmode": "require",
    }


def test_missing_database_environment_fails_closed() -> None:
    with pytest.raises(SearchStageError) as exc_info:
        db.resolve_connection_target({"POSTGRES_HOST": "db.internal"})

    assert exc_info.value.code == "DATABASE_NOT_READY"
    assert "db.internal" not in str(exc_info.value)


def test_database_readiness_is_scoped_to_the_active_seed(monkeypatch) -> None:
    active_seed_version = "sha256:" + "a" * 64
    statements: list[str] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

        def execute(self, sql):
            statements.append(" ".join(sql.split()))

        def fetchone(self):
            return (active_seed_version, 3339, 825, 2560, 2560)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(db, "connect_database", lambda: FakeConnection())

    result = db.database_readiness()

    assert "FROM precedent_newplusplus.blocks AS blocks" in statements[0]
    assert "CROSS JOIN precedent_newplusplus.active_seed AS active" in statements[0]
    assert "block_versions" not in statements[0]
    assert result == {
        "ready": True,
        "active_seed_version": active_seed_version,
        "blocks": 3339,
        "cases": 825,
        "vector_dims": 2560,
    }


def test_database_readiness_fails_closed_without_an_active_seed(monkeypatch) -> None:
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

        def execute(self, _sql):
            return None

        def fetchone(self):
            return None

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(db, "connect_database", lambda: FakeConnection())

    assert db.database_readiness() == {
        "ready": False,
        "active_seed_version": None,
        "blocks": 0,
        "cases": 0,
        "vector_dims": None,
    }


def test_connect_database_preserves_domain_errors_from_transaction_body(
    monkeypatch,
) -> None:
    service = importlib.import_module(
        "etl.fault_cases.src.traffic_precedents.precedent_db_loading.seed_integrity"
    )

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

    monkeypatch.setitem(
        sys.modules,
        "psycopg",
        types.SimpleNamespace(connect=lambda *args, **kwargs: FakeConnection()),
    )
    monkeypatch.setenv("PRECEDENT_NEWPLUSPLUS_DSN", "postgresql://explicit")

    with pytest.raises(service.SeedIntegrityError) as exc_info:
        with db.connect_database():
            raise service.SeedIntegrityError(
                "ACTIVE_SEED_CHANGED",
                "active seed changed before promotion",
            )

    assert exc_info.value.code == "ACTIVE_SEED_CHANGED"
