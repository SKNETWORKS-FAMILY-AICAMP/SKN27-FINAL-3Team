from __future__ import annotations

import importlib
import importlib.util


MODULE_NAME = "backend.chatbot.management.commands.verify_pgvector_rag_readiness"


def test_pgvector_readiness_reports_all_three_domains(monkeypatch) -> None:
    assert importlib.util.find_spec(MODULE_NAME) is not None, (
        "pgvector readiness command must exist before ES readiness is removed"
    )
    command = importlib.import_module(MODULE_NAME)
    monkeypatch.setattr(
        command,
        "_verify_legal",
        lambda: {"status": "ready", "embedding_count": 3, "hnsw_index": True},
    )
    monkeypatch.setattr(
        command,
        "_verify_review_case",
        lambda: {"status": "ready", "embedding_count": 5, "hnsw_index": True},
    )
    monkeypatch.setattr(
        command,
        "_verify_fault_ratio_precedent",
        lambda: {"status": "ready", "embedding_count": 7, "hnsw_index": True},
    )

    result = command.verify_pgvector_rag_readiness()

    assert result["contract_version"] == "pgvector_rag_readiness.v1"
    assert result["status"] == "ready"
    assert result["domains"] == {
        "legal": {"status": "ready", "embedding_count": 3, "hnsw_index": True},
        "review_case": {"status": "ready", "embedding_count": 5, "hnsw_index": True},
        "fault_ratio_precedent": {"status": "ready", "embedding_count": 7, "hnsw_index": True},
    }


def test_pgvector_readiness_fails_when_a_domain_is_not_ready(monkeypatch) -> None:
    assert importlib.util.find_spec(MODULE_NAME) is not None, (
        "pgvector readiness command must exist before ES readiness is removed"
    )
    command = importlib.import_module(MODULE_NAME)
    monkeypatch.setattr(
        command,
        "_verify_legal",
        lambda: {"status": "ready", "embedding_count": 3, "hnsw_index": True},
    )
    monkeypatch.setattr(
        command,
        "_verify_review_case",
        lambda: {"status": "unavailable", "error_code": "database_unavailable"},
    )
    monkeypatch.setattr(
        command,
        "_verify_fault_ratio_precedent",
        lambda: {"status": "ready", "embedding_count": 7, "hnsw_index": True},
    )

    result = command.verify_pgvector_rag_readiness()

    assert result["status"] == "fail"
    assert result["domains"]["review_case"]["error_code"] == "database_unavailable"


def test_text_ml_smoke_exposes_pgvector_requirement_flag() -> None:
    from backend.chatbot.management.commands import smoke_text_ml_case_search

    class RecordingParser:
        def __init__(self) -> None:
            self.arguments: list[tuple[tuple, dict]] = []

        def add_argument(self, *args, **kwargs):
            self.arguments.append((args, kwargs))

    parser = RecordingParser()
    smoke_text_ml_case_search.Command().add_arguments(parser)

    assert any("--require-pgvector" in args for args, _kwargs in parser.arguments)
    assert not any("--require-es" in args for args, _kwargs in parser.arguments)
