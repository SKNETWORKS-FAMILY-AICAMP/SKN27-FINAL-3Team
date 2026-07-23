from __future__ import annotations


def test_empty_query_keeps_review_case_retrieval_metadata(monkeypatch) -> None:
    from ai.agents.text_ml_case_search import agent

    monkeypatch.setattr(
        agent,
        "_run_fault_ratio_knowledge_agent",
        lambda **_kwargs: None,
    )

    output = agent.run_text_ml_case_search(
        {
            "session_id": "ses_empty_text_ml",
            "message_id": "msg_empty_text_ml",
            "job_id": "job_empty_text_ml",
        },
        {},
    )

    assert output["status"] == "failed"
    assert output["structured_result"]["retrieval"]["source_type"] == "review_case"
    assert output["structured_result"]["retrieval"]["fallback_used"] is False
