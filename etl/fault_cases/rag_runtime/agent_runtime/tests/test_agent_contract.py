from __future__ import annotations

from typing import Any

import pytest

from etl.fault_cases.rag_runtime.agent_runtime import agent
from etl.fault_cases.rag_runtime.agent_runtime.supervisor_input import parse_input


def _result(domain: str, status: str) -> dict[str, Any]:
    return {"domain": domain, "status": status, "evidence": []}


def test_parse_input_normalizes_accident_facts_and_preserves_legacy_aliases() -> None:
    request = parse_input(
        {
            "case_id": "legacy-case-1",
            "raw_user_text": "후방 추돌 사고입니다.",
            "accident_facts": {"road_type": "intersection"},
            "required_domains": ["precedent"],
        }
    )

    assert request["message_id"] == "legacy-case-1"
    assert request["query_text"] == "후방 추돌 사고입니다."
    assert request["accident_facts"] == {"road_type": "intersection"}
    assert request["required_domains"] == ["precedent"]

    legacy_request = parse_input(
        {
            "message_id": "message-2",
            "query_text": "legacy facts",
            "structured_facts": {"weather": "rain"},
        }
    )

    assert legacy_request["message_id"] == "message-2"
    assert legacy_request["accident_facts"] == {"weather": "rain"}


def test_invoke_agent_dispatches_only_requested_domains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_handler(_: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("unrequested domain handler was called")

    def precedent_handler(request: dict[str, Any]) -> dict[str, Any]:
        assert request["accident_facts"] == {"vehicles": 2}
        return _result("precedent", "success")

    monkeypatch.setattr(agent, "fs_handle", unexpected_handler)
    monkeypatch.setattr(agent, "pr_handle", precedent_handler)
    monkeypatch.setattr(agent, "rc_handle", unexpected_handler)

    output = agent.invoke_agent(
        {
            "case_id": "case-3",
            "query_text": "precedent search",
            "accident_facts": {"vehicles": 2},
            "required_domains": ["precedent"],
        }
    )

    assert output["message_id"] == "case-3"
    assert output["status"] == "success"
    assert output["domains"] == {"precedent": _result("precedent", "success")}


def test_invoke_agent_returns_partial_for_mixed_selected_domain_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent, "fs_handle", lambda _: _result("fault_standard", "success"))
    monkeypatch.setattr(agent, "pr_handle", lambda _: _result("precedent", "failed"))
    monkeypatch.setattr(agent, "rc_handle", lambda _: _result("review_case", "success"))

    output = agent.invoke_agent(
        {
            "message_id": "message-4",
            "query_text": "mixed results",
            "required_domains": ["fault_standard", "precedent"],
        }
    )

    assert output["status"] == "partial"
    assert set(output["domains"]) == {"fault_standard", "precedent"}


def test_invoke_agent_isolates_handler_exception_as_sanitized_partial_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_precedent_handler(_: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("postgres password=secret unavailable")

    monkeypatch.setattr(agent, "fs_handle", lambda _: _result("fault_standard", "success"))
    monkeypatch.setattr(agent, "pr_handle", failing_precedent_handler)

    output = agent.invoke_agent(
        {
            "message_id": "message-handler-error",
            "query_text": "mixed execution",
            "required_domains": ["fault_standard", "precedent"],
        }
    )

    assert output["status"] == "partial"
    assert output["domains"]["fault_standard"] == _result("fault_standard", "success")
    failed = output["domains"]["precedent"]
    assert failed["domain"] == "precedent"
    assert failed["status"] == "failed"
    assert failed["evidence"] == []
    assert "secret" not in " ".join(failed["limitations"])


def test_invoke_agent_returns_failed_when_all_selected_domains_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent, "fs_handle", lambda _: _result("fault_standard", "failed"))
    monkeypatch.setattr(agent, "pr_handle", lambda _: _result("precedent", "failed"))
    monkeypatch.setattr(agent, "rc_handle", lambda _: _result("review_case", "failed"))

    output = agent.invoke_agent(
        {"message_id": "message-5", "query_text": "all failures"}
    )

    assert output["status"] == "failed"
    assert set(output["domains"]) == {"fault_standard", "precedent", "review_case"}


def test_invoke_agent_returns_contract_shaped_failure_for_invalid_input() -> None:
    output = agent.invoke_agent({"message_id": "message-6"})

    assert output["message_id"] == "message-6"
    assert output["contract_version"] == "v1"
    assert output["status"] == "failed"
    assert output["domains"] == {}
