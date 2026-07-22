from pathlib import Path

from etl.fault_cases.rag_runtime.evaluation import evaluate_fault_standard_complete30


def test_complete30_root_is_official_evaluation_directory() -> None:
    expected = (
        Path(evaluate_fault_standard_complete30.__file__).resolve().parents[2]
        / "evaluation/fault_standard/complete30_v9/v1"
    )

    assert evaluate_fault_standard_complete30.COMPLETE30_ROOT == expected
