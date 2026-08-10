from __future__ import annotations


def test_explicit_mock_agent_dispatch_is_owned_by_mock_runtime() -> None:
    from app.mock_runtime.agent_execution import (
        DL_MOCK_NODE_CODES,
        execute_mock_node,
        execute_mock_plan,
    )

    assert isinstance(DL_MOCK_NODE_CODES, set)
    assert callable(execute_mock_node)
    assert callable(execute_mock_plan)

