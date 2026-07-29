from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


class _Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def consume(self):
        return None

    def single(self):
        return self.rows[0] if self.rows else None


class _Session:
    def __init__(self, metadata_manifest_sha256: str):
        self.metadata_manifest_sha256 = metadata_manifest_sha256
        self.events: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def run(self, query, **_params):
        if "LegalGraphDataset" in query:
            self.events.append("metadata")
            return _Result(
                [
                    {
                        "dataset_version": "2026-07-28-law-v1",
                        "manifest_sha256": self.metadata_manifest_sha256,
                        "canonical_chunk_sha256": "c" * 64,
                        "legal_chunk_count": 2,
                    }
                ]
            )
        if "count(chunk) AS chunk_count" in query:
            return _Result([{"chunk_count": 2}])
        if "MATCH (c1:LawChunk" in query:
            return _Result([{"expanded": 1}])
        return _Result()


class _Driver:
    def __init__(self, session: _Session):
        self.session_instance = session
        self.connected = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def verify_connectivity(self):
        self.connected = True

    def session(self, **_kwargs):
        return self.session_instance


def test_graph_loader_writes_dataset_metadata_only_after_import(monkeypatch) -> None:
    from backend.chatbot.management.commands import load_legal_graph_seed as command

    seed = SimpleNamespace(
        dataset_version="2026-07-28-law-v1",
        manifest_sha256="a" * 64,
        canonical_chunk_sha256="c" * 64,
        chunks=({}, {}),
    )
    session = _Session(metadata_manifest_sha256="a" * 64)
    driver = _Driver(session)
    events: list[str] = []
    monkeypatch.setenv("NEO4J_URI", "bolt://law-neo4j:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "secret-not-in-output")
    monkeypatch.setenv("NEO4J_DATABASE", "neo4j")
    monkeypatch.setattr(command, "create_constraints", lambda _session: events.append("constraints"))
    monkeypatch.setattr(
        command,
        "import_law_graph_seed",
        lambda _session, _seed, *, batch_size: events.append(f"graph:{batch_size}")
        or {"law_chunks": 2},
    )
    monkeypatch.setattr(
        command,
        "import_hint_terms",
        lambda _session, _path: events.append("hints") or {"hint_terms": 1},
    )

    result = command.execute_legal_graph_seed_load(
        seed,
        batch_size=17,
        driver_factory=lambda *_args, **_kwargs: driver,
        hint_terms_path=Path("storage/rag/law_query_terms.yaml"),
    )

    assert driver.connected is True
    assert events == ["constraints", "graph:17", "hints"]
    assert session.events == ["metadata"]
    assert result["metadata"]["manifest_sha256"] == "a" * 64


def test_graph_readiness_rejects_manifest_mismatch(monkeypatch) -> None:
    from backend.chatbot.management.commands import verify_legal_graph_readiness as command

    session = _Session(metadata_manifest_sha256="b" * 64)
    driver = _Driver(session)
    monkeypatch.setenv("NEO4J_URI", "bolt://law-neo4j:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "secret-not-in-output")
    monkeypatch.setenv("NEO4J_DATABASE", "neo4j")
    monkeypatch.setenv("LEGAL_DATASET_VERSION", "2026-07-28-law-v1")
    monkeypatch.setenv("LEGAL_RAG_SEED_MANIFEST_SHA256", "a" * 64)
    monkeypatch.setattr(command.GraphDatabase, "driver", lambda *_args, **_kwargs: driver)

    result = command.verify_legal_graph_readiness()

    assert result["status"] == "fail"
    assert result["error_code"] == "manifest_sha256_mismatch"
    assert "secret-not-in-output" not in str(result)


def test_runtime_readiness_requires_verified_graph_when_enabled(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "backend"))
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from django.conf import settings
    from chatbot import readiness

    monkeypatch.setattr(settings, "LEGAL_RAG_VECTOR_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LAW_GROUND_SEARCH_ENABLE_NEO4J", "1", raising=False)
    monkeypatch.setattr(settings, "LAW_GRAPH_REQUIRED", "1", raising=False)
    monkeypatch.setattr(settings, "NEO4J_URI", "bolt://law-neo4j:7687", raising=False)
    monkeypatch.setattr(
        readiness,
        "verify_legal_graph_readiness",
        lambda: {"status": "fail", "error_code": "manifest_sha256_mismatch"},
    )

    result = readiness._law_ground_search_sync_check()

    assert result["status"] == "fail"
    assert result["metadata"]["legal_graph_status"] == "fail"
    assert "manifest_sha256_mismatch" not in str(result)
