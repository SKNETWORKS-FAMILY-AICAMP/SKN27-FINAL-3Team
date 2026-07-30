from __future__ import annotations

from etl.fault_cases.src.traffic_precedents.run_pipeline import (
    CLI_STAGES,
    PIPELINE_STAGES,
)


EXPECTED_STAGES = (
    "collect",
    "validate-collection",
    "preprocess",
    "semantic-blocks",
    "classify",
    "validate-classification",
    "build-rag-records",
    "embed",
    "load",
)


def test_pipeline_stage_order_is_fixed() -> None:
    assert PIPELINE_STAGES == EXPECTED_STAGES
    assert CLI_STAGES == (*EXPECTED_STAGES, "all")
