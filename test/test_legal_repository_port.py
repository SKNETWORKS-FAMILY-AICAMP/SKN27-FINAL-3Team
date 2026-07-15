from __future__ import annotations

import psycopg2
import pytest
from unittest.mock import Mock

from ai.agents.appeal_decision_flow.guide import guide_generation_node
from ai.agents.appeal_decision_flow.law_refs import get_merit_context
from ai.agents.appeal_decision_flow.merit_gate import merit_classification_node
from etl.legal.search import _connect_law_db


def test_offline_law_context_fails_closed_without_opening_database(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def unexpected_lookup(source_name: str, article_no: str) -> None:
        calls.append((source_name, article_no))
        return None

    monkeypatch.delenv("LEGAL_PROVISION_DB_ENABLED", raising=False)
    monkeypatch.setattr("etl.legal.search.get_provision_text", unexpected_lookup)

    with pytest.raises(RuntimeError, match="legal_provision_db_disabled"):
        get_merit_context("사전통지")

    assert calls == []


def test_merit_context_uses_db_article_160_and_explicit_provenance(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def provision_lookup(source_name: str, article_no: str) -> str:
        calls.append((source_name, article_no))
        if (source_name, article_no) == ("도로교통법", "제160조"):
            return "제160조 제4항 제1호 도난 또는 그 밖의 부득이한 사유"
        return f"{source_name} {article_no} database provision"

    monkeypatch.setenv("LEGAL_PROVISION_DB_ENABLED", "1")
    monkeypatch.setattr("etl.legal.search.get_provision_text", provision_lookup)

    context = get_merit_context("사전통지")

    assert ("도로교통법", "제160조") in calls
    assert "제160조 제4항 제1호 도난 또는 그 밖의 부득이한 사유" in context
    assert "source=도로교통법; article=제160조; provenance=legal_provision_db" in context
    assert context.count("provenance=legal_provision_db") == 6


def test_merit_context_db_miss_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_PROVISION_DB_ENABLED", "1")
    monkeypatch.setattr("etl.legal.search.get_provision_text", lambda *_args: None)

    with pytest.raises(RuntimeError, match="legal_provision_not_found"):
        get_merit_context("사전통지")


def test_article_160_without_required_paragraph_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_PROVISION_DB_ENABLED", "1")
    monkeypatch.setattr(
        "etl.legal.search.get_provision_text",
        lambda *_args: "제160조의 다른 항만 조회됨",
    )

    with pytest.raises(RuntimeError, match="legal_provision_incomplete"):
        get_merit_context("사전통지")


def test_merit_node_does_not_call_llm_when_legal_evidence_lookup_fails(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_PROVISION_DB_ENABLED", "1")

    def fail_lookup(*_args):
        raise RuntimeError("database password=very-sensitive")

    llm_call = Mock(side_effect=AssertionError("LLM must not receive fallback law text"))
    monkeypatch.setattr("etl.legal.search.get_provision_text", fail_lookup)
    monkeypatch.setattr(
        "ai.agents.appeal_decision_flow.merit_gate._call_llm_merit",
        llm_call,
    )

    result = merit_classification_node(
        {
            "user_appeal_reason": "응급환자를 이송했습니다.",
            "notice_stage": "사전통지",
        }
    )

    assert result["legal_evidence_status"] == "unavailable"
    assert result["legal_evidence_reason"] == "legal_provision_lookup_failed"
    assert result["merit_judgment_failed"] is True
    assert "very-sensitive" not in str(result)
    llm_call.assert_not_called()


def test_appeal_guide_marks_legal_evidence_unavailable_result_partial() -> None:
    result = guide_generation_node(
        {
            "fine_type": "과태료",
            "notice_stage": "사전통지",
            "judgment_status": "failed",
            "legal_evidence_status": "unavailable",
            "legal_evidence_reason": "legal_provision_not_found",
            "agent_results": {},
        }
    )

    envelope = result["agent_results"]["appeal_judgment"]
    assert envelope["status"] == "partial"
    assert envelope["evidence"] == []
    assert envelope["structured_result"]["judgment_status"] == "failed"
    assert envelope["structured_result"]["legal_evidence_status"] == "unavailable"
    assert "legal_provision_not_found" in envelope["limitations"]


def test_law_database_connection_has_bounded_timeout(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def capture_connect(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(psycopg2, "connect", capture_connect)
    monkeypatch.setenv("LEGAL_DB_CONNECT_TIMEOUT_SECONDS", "3")

    _connect_law_db()

    assert captured["connect_timeout"] == 3
    assert captured["application_name"] == "skn27-legal-search"
