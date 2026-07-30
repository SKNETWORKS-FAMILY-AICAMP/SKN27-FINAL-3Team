from __future__ import annotations

from typing import Any

from ..config import EXPECTED_RAG_BLOCKS, EXPECTED_RAG_CASES, QWEN_DIMENSION


def validate_loaded(connection: Any) -> dict[str, Any]:
    statement = """
    SELECT count(*)::int, count(DISTINCT record_id)::int,
           min(vector_dims(embedding))::int,
           max(vector_dims(embedding))::int
    FROM precedent_newplusplus.blocks
    """
    with connection.cursor() as cursor:
        cursor.execute(statement)
        blocks, cases, min_dims, max_dims = cursor.fetchone()
    passed = (
        blocks == EXPECTED_RAG_BLOCKS
        and cases == EXPECTED_RAG_CASES
        and min_dims == max_dims == QWEN_DIMENSION
    )
    return {
        "status": "PASSED" if passed else "FAILED",
        "block_count": blocks,
        "case_count": cases,
        "embedding_dimension": min_dims if min_dims == max_dims else None,
    }
