from __future__ import annotations

import importlib.util


def test_review_case_reranker_config_module_exists() -> None:
    spec = importlib.util.find_spec(
        "etl.fault_cases.rag_runtime.review_case.config"
    )

    assert spec is not None


def test_default_config_freezes_top_five_and_bge_revision() -> None:
    from etl.fault_cases.rag_runtime.review_case.config import load_config

    config = load_config({})

    assert config.candidate_chunk_k == 200
    assert config.unique_case_k == 5
    assert config.reranker_input_k == 5
    assert config.final_output_k == 5
    assert config.reranker_model_name == "BAAI/bge-reranker-v2-m3"
    assert config.reranker_revision == (
        "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
    )
    assert config.reranker_max_length == 4096
    assert config.reranker_device == "cuda"
    assert config.reranker_batch_size == 4
    assert not hasattr(config, "reranker_enabled")


def test_config_allows_only_device_and_positive_batch_size_override() -> None:
    from etl.fault_cases.rag_runtime.review_case.config import load_config

    config = load_config(
        {
            "REVIEW_CASE_RERANKER_DEVICE": "cuda:1",
            "REVIEW_CASE_RERANKER_BATCH_SIZE": "2",
            "REVIEW_CASE_RERANKER_ENABLED": "false",
        }
    )

    assert config.reranker_device == "cuda:1"
    assert config.reranker_batch_size == 2
    assert not hasattr(config, "reranker_enabled")
