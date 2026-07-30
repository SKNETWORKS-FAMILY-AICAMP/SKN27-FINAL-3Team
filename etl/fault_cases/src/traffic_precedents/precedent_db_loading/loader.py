from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np

from ..config import QWEN_DIMENSION
from ..contracts import read_jsonl
from ..precedent_embedding.archive import select_source_vectors
from ..precedent_embedding.build_bootstrap import (
    SOURCE_METADATA_SHA256,
    SOURCE_NPY_SHA256,
)
from ..precedent_embedding.archive import sha256_file
from ..rag_records.validator import validate_rag_records


def vector_literal(vector: np.ndarray) -> str:
    return "[" + ",".join(f"{float(value):.9g}" for value in vector) + "]"


def load_bootstrap_pair(
    embeddings_path: Path,
    metadata_path: Path,
) -> tuple[list[dict[str, Any]], np.ndarray]:
    if sha256_file(embeddings_path) != SOURCE_NPY_SHA256:
        raise ValueError("bootstrap NPY SHA-256 mismatch")
    if sha256_file(metadata_path) != SOURCE_METADATA_SHA256:
        raise ValueError("bootstrap metadata SHA-256 mismatch")
    source_vectors = np.load(embeddings_path, mmap_mode="r")
    metadata = read_jsonl(metadata_path)
    records = [
        row
        for row in metadata
        if row.get("enabled_in_general_accident_search") is True
    ]
    vectors, _ = select_source_vectors(source_vectors, metadata, records)
    validate_load_inputs(
        records,
        vectors,
        expected_blocks=3339,
        expected_cases=825,
    )
    return records, vectors


def validate_load_inputs(
    records: Iterable[dict[str, Any]],
    embeddings: np.ndarray,
    *,
    expected_blocks: int,
    expected_cases: int,
) -> list[dict[str, Any]]:
    rows = list(records)
    report = validate_rag_records(
        rows, expected_blocks=expected_blocks, expected_cases=expected_cases
    )
    if report["status"] != "PASSED":
        raise ValueError(f"invalid RAG records: {report['errors']}")
    if embeddings.shape != (expected_blocks, QWEN_DIMENSION):
        raise ValueError(f"invalid embedding shape: {embeddings.shape}")
    if embeddings.dtype != np.float32 or not np.isfinite(embeddings).all():
        raise ValueError("embeddings must be finite float32")
    return rows


def load_records(
    records: Iterable[dict[str, Any]],
    embeddings: np.ndarray,
    *,
    connection_factory: Callable[[], Any],
    expected_blocks: int,
    expected_cases: int,
) -> int:
    rows = validate_load_inputs(
        records,
        embeddings,
        expected_blocks=expected_blocks,
        expected_cases=expected_cases,
    )
    statement = """
    INSERT INTO precedent_newplusplus.blocks (
      block_id, record_id, block_type, semantic_role, block_text,
      case_number, case_name, court_name, decision_date, internal_grade,
      source_metadata, embedding
    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::vector)
    ON CONFLICT (block_id) DO UPDATE SET
      record_id=EXCLUDED.record_id, block_type=EXCLUDED.block_type,
      semantic_role=EXCLUDED.semantic_role, block_text=EXCLUDED.block_text,
      case_number=EXCLUDED.case_number, case_name=EXCLUDED.case_name,
      court_name=EXCLUDED.court_name, decision_date=EXCLUDED.decision_date,
      internal_grade=EXCLUDED.internal_grade,
      source_metadata=EXCLUDED.source_metadata, embedding=EXCLUDED.embedding
    """
    with connection_factory() as connection, connection.cursor() as cursor:
        for row, vector in zip(rows, embeddings, strict=True):
            cursor.execute(
                statement,
                (
                    row["block_id"],
                    row["record_id"],
                    row.get("block_type") or row.get("semantic_role"),
                    row["semantic_role"],
                    row["text"],
                    row.get("case_number"),
                    row.get("case_name"),
                    row.get("court_name"),
                    row.get("decision_date"),
                    row["internal_grade"],
                    json.dumps(row, ensure_ascii=False),
                    vector_literal(vector),
                ),
            )
    return len(rows)
