from __future__ import annotations

import json

from etl.fault_cases.src.agents.text_ml_case_search.config import NODE_CODE
from etl.fault_cases.src.agents.text_ml_case_search.run_agent_sample import (
    build_sample_agent_input,
    load_agent_input,
)


def test_build_sample_agent_input_uses_agent_node_code() -> None:
    agent_input = build_sample_agent_input()

    assert agent_input["node_code"] == NODE_CODE
    assert agent_input["query_text"]
    assert agent_input["required_outputs"]


def test_load_agent_input_reads_wrapped_payload(tmp_path) -> None:
    path = tmp_path / "input.json"
    path.write_text(
        json.dumps(
            {
                "agent_input": {
                    "session_id": "s1",
                    "message_id": "m1",
                    "job_id": "j1",
                    "node_code": NODE_CODE,
                    "query_text": "신호 없는 교차로 사고",
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    agent_input = load_agent_input(str(path))

    assert agent_input["session_id"] == "s1"
    assert agent_input["query_text"] == "신호 없는 교차로 사고"


def test_load_agent_input_reads_direct_payload(tmp_path) -> None:
    path = tmp_path / "input.json"
    path.write_text(
        json.dumps(
            {
                "session_id": "s1",
                "message_id": "m1",
                "job_id": "j1",
                "node_code": NODE_CODE,
                "query_text": "차로 변경 사고",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    agent_input = load_agent_input(str(path))

    assert agent_input["job_id"] == "j1"
    assert agent_input["query_text"] == "차로 변경 사고"
