from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[5]


def test_newplusplus_schema_is_versioned_and_runtime_view_is_read_only() -> None:
    schema = (
        ROOT
        / "etl/fault_cases/src/traffic_precedents/precedent_db_loading/schema.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS precedent_newplusplus.seed_releases" in schema
    assert "CREATE TABLE IF NOT EXISTS precedent_newplusplus.block_versions" in schema
    assert "PRIMARY KEY (seed_version, block_id)" in schema
    assert "CREATE TABLE IF NOT EXISTS precedent_newplusplus.active_seed" in schema
    assert "CHECK (singleton)" in schema
    assert "CREATE OR REPLACE VIEW precedent_newplusplus.blocks" in schema
    assert "JOIN precedent_newplusplus.active_seed" in schema
    assert "embedding vector(2560) NOT NULL" in schema
    assert "unexpected existing precedent_newplusplus.blocks relation" in schema


def test_local_newplusplus_init_matches_canonical_schema() -> None:
    canonical = (
        ROOT
        / "etl/fault_cases/src/traffic_precedents/precedent_db_loading/schema.sql"
    ).read_text(encoding="utf-8")
    local = (
        ROOT
        / "etl/fault_cases/src/traffic_precedents/precedent_search/newplusplus/01_init_pgvector.sql"
    ).read_text(encoding="utf-8")

    assert local == canonical
