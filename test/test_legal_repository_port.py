from __future__ import annotations

import psycopg2

from ai.agents.appeal_decision_flow.law_refs import get_merit_context
from etl.legal.search import _connect_law_db


def test_offline_law_context_uses_fallback_without_opening_database(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def unexpected_lookup(source_name: str, article_no: str) -> None:
        calls.append((source_name, article_no))
        return None

    monkeypatch.delenv("LEGAL_PROVISION_DB_ENABLED", raising=False)
    monkeypatch.setattr("etl.legal.search.get_provision_text", unexpected_lookup)

    context = get_merit_context("사전통지")

    assert "질서위반행위규제법 제7조" in context
    assert calls == []


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
