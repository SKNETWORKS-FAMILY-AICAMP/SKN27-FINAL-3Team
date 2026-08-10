from __future__ import annotations

from unittest.mock import patch

import pytest


def test_explicit_mock_agent_dispatch_is_owned_by_mock_runtime() -> None:
    from app.mock_runtime.agent_execution import (
        SUPPORTED_EXPLICIT_MOCK_NODE_CODES,
        execute_mock_node,
        execute_mock_plan,
    )

    assert isinstance(SUPPORTED_EXPLICIT_MOCK_NODE_CODES, frozenset)
    assert callable(execute_mock_node)
    assert callable(execute_mock_plan)


def test_unsupported_explicit_mock_node_fails_without_calling_canonical_agent() -> None:
    from app.mock_runtime import agent_execution

    with patch.object(
        agent_execution,
        "execute_agent_node",
        side_effect=AssertionError("Canonical Agent must not run from Explicit Mock"),
        create=True,
    ) as canonical_executor:
        with pytest.raises(ValueError, match="unsupported_explicit_mock_node"):
            agent_execution.execute_mock_node({"node_code": "provider_capable_node"})

    canonical_executor.assert_not_called()
