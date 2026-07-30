from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

import numpy as np

from etl.fault_cases.src.traffic_precedents.precedent_embedding.archive import (
    select_source_vectors,
)
from etl.fault_cases.src.traffic_precedents.precedent_embedding.build_bootstrap import (
    build_bootstrap_package,
)


def test_source_vector_selection_is_bitwise_and_rag_ordered() -> None:
    source = np.arange(12, dtype=np.float32).reshape(3, 4)
    metadata = [
        {"block_id": "b2", "enabled_in_general_accident_search": True},
        {"block_id": "unused", "enabled_in_general_accident_search": False},
        {"block_id": "b1", "enabled_in_general_accident_search": True},
    ]
    selected, row_map = select_source_vectors(
        source,
        metadata,
        [{"block_id": "b1"}, {"block_id": "b2"}],
    )
    assert np.array_equal(selected[0], source[2])
    assert np.array_equal(selected[1], source[0])
    assert row_map == [
        {"new_index": 0, "source_index": 2, "block_id": "b1"},
        {"new_index": 1, "source_index": 0, "block_id": "b2"},
    ]


def test_bootstrap_package_contains_aligned_subset() -> None:
    temp_dir = Path.cwd() / "tmp" / f"precedent-test-{uuid4().hex}"
    temp_dir.mkdir(parents=True)
    try:
        source_path = temp_dir / "source.npy"
        metadata_path = temp_dir / "metadata.jsonl"
        manifest_path = temp_dir / "source_manifest.json"
        output_path = temp_dir / "bootstrap.tar.gz"
        np.save(source_path, np.eye(3, 4, dtype=np.float32))
        metadata_path.write_text(
            "\n".join(
                [
                    '{"block_id":"b1","record_id":"c1","internal_grade":"GENERAL_READY_DIRECT","semantic_role":"ACCIDENT_FACT","text":"a","validator_status":"PASSED","enabled_in_general_accident_search":true}',
                    '{"block_id":"b2","record_id":"c2","internal_grade":"GENERAL_READY_LEGAL_SUPPORT","semantic_role":"GENERAL_LEGAL_PRINCIPLE","text":"b","validator_status":"PASSED","enabled_in_general_accident_search":false}',
                    '{"block_id":"b3","record_id":"c3","internal_grade":"SEED_READY","semantic_role":"FAULT_DECISION","text":"c","validator_status":"PASSED","enabled_in_general_accident_search":true}',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        manifest_path.write_text(
            '{"model_name":"test","model_revision":"r1","embedding_dimension":4,'
            '"normalize_embeddings":true}',
            encoding="utf-8",
        )
        report = build_bootstrap_package(
            source_embeddings=source_path,
            source_metadata=metadata_path,
            source_manifest=manifest_path,
            output_path=output_path,
            expected_blocks=2,
            expected_cases=2,
            expected_dimension=4,
            enforce_source_hashes=False,
        )
        assert output_path.is_file()
        assert report["block_count"] == 2
        assert report["case_count"] == 2
    finally:
        for path in temp_dir.iterdir():
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink()
        temp_dir.rmdir()
