from pathlib import Path

from etl.fault_cases.rag_runtime import evaluate_all


def test_evaluate_all_uses_repository_relative_dataset_and_runtime_facts() -> None:
    dataset_path = evaluate_all.default_dataset_path()
    request = evaluate_all.request_from_question(
        {
            "case_id": "complete30-1",
            "query_text": "fault-standard evaluation",
            "structured_facts": {"road_type": "intersection"},
        }
    )

    assert dataset_path == (
        Path(evaluate_all.__file__).resolve().parent
        / "evaluation/fault_standard/complete30_v9/v1/complete30_consumer_questions_v1.jsonl"
    )
    assert request["accident_facts"] == {
        "structured_facts": {"road_type": "intersection"}
    }
    assert "structured_facts" not in request
