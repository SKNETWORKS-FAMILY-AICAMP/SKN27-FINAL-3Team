from __future__ import annotations

import pytest

from etl.fault_cases.rag_runtime.fault_standard.graph_schema import (
    OPERATIONAL_LABEL,
    node_pattern,
)


def test_operational_label_is_stable() -> None:
    assert OPERATIONAL_LABEL == "FaultStandardOperational"
    assert node_pattern("r", "Rule") == "(r:FaultStandardOperational:Rule)"


def test_node_pattern_rejects_unsafe_identifiers() -> None:
    with pytest.raises(ValueError, match="identifier"):
        node_pattern("r`, MATCH (x)", "Rule")

    with pytest.raises(ValueError, match="identifier"):
        node_pattern("r", "Rule` MATCH (x)")
