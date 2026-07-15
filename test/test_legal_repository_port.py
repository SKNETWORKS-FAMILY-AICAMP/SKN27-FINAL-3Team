from __future__ import annotations

import psycopg2
import pytest
from unittest.mock import Mock

from ai.agents.appeal_decision_flow.guide import guide_generation_node
from ai.agents.appeal_decision_flow.law_refs import (
    LegalProvisionEvidenceUnavailable,
    _fetch_provision_text,
    get_merit_context,
)
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


def test_article_160_uses_only_verified_pinned_snapshot(monkeypatch) -> None:
    resolved_sources: list[str] = []

    def confident_match(source_name: str, _golden_text: str) -> dict[str, object]:
        resolved_sources.append(source_name)
        return {
            "source_name": source_name,
            "provision_text": "RAG에서 검증된 조문 원문",
            "score": 0.95,
        }

    monkeypatch.setenv("LEGAL_PROVISION_DB_ENABLED", "1")
    monkeypatch.setattr(
        "ai.agents.appeal_decision_flow.law_refs._resolve_provision_match",
        confident_match,
    )

    context = get_merit_context("사전통지")

    assert "제160조제4항제1호" in context
    assert "provenance=pinned_verified_snapshot" in context
    assert "도로교통법" not in resolved_sources
    assert resolved_sources == [
        "도로교통법 시행규칙",
        "질서위반행위규제법",
        "질서위반행위규제법",
        "질서위반행위규제법",
        "질서위반행위규제법",
    ]


def test_required_rag_rejects_whitespace_only_provision_text(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_PROVISION_DB_ENABLED", "1")
    monkeypatch.setattr(
        "ai.agents.appeal_decision_flow.law_refs._resolve_provision_match",
        lambda _source_name, _golden_text: {"provision_text": " \t\n "},
    )

    with pytest.raises(LegalProvisionEvidenceUnavailable) as exc_info:
        _fetch_provision_text("도로교통법 시행규칙", "검증 기준 원문")

    assert exc_info.value.reason_code == "legal_provision_not_found"


def test_merit_node_does_not_call_llm_when_required_rag_lookup_fails(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_PROVISION_DB_ENABLED", "1")
    monkeypatch.setattr(
        "ai.agents.appeal_decision_flow.law_refs._resolve_provision_match",
        Mock(side_effect=ConnectionError("DB 연결 실패")),
    )
    llm_call = Mock(return_value={"merit": "강함", "merit_basis": "검증되지 않은 판정"})
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
    llm_call.assert_not_called()


def test_appeal_guide_marks_required_rag_unavailable_result_partial() -> None:
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
