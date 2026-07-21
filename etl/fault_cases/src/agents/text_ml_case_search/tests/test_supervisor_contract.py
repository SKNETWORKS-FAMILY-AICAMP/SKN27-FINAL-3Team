from __future__ import annotations

from etl.fault_cases.src.agents.text_ml_case_search.agent import run_text_ml_case_search
from etl.fault_cases.src.agents.text_ml_case_search.config import CONTRACT_VERSION, NODE_CODE


def test_agent_output_contains_supervisor_contract_fields() -> None:
    result = run_text_ml_case_search(
        {
            "session_id": "s1",
            "message_id": "m1",
            "job_id": "j1",
            "node_code": NODE_CODE,
            "query_text": "signal intersection crash",
        }
    )

    structured = result["structured_result"]

    assert result["contract_version"] == CONTRACT_VERSION
    assert result["node_code"] == NODE_CODE
    assert result["status"] in {"success", "partial", "failed"}
    assert "normalized_description" in structured
    assert "issue_tags" in structured
    assert "recommended_evidence" in structured
    assert "similar_cases" in structured
    assert "ratio_range_label" in structured
    assert "display_evidence" in structured
    assert "search_text" in structured
    assert "rag_debug" in structured
    assert isinstance(result["evidence"], list)
    assert isinstance(result["next_actions"], list)
    assert isinstance(result["limitations"], list)
    assert isinstance(result["missing_fields"], list)
