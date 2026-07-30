"""Qwen cosine 유사도로 판례별 최고 의미 블록 Top200 회수."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .config import ServiceSettings
from .db import connect_database
from .errors import SearchStageError


CANDIDATE_SQL = """
WITH scored AS (
    SELECT block_id, record_id, block_type, block_text, case_number,
           case_name, court_name, decision_date, source_metadata,
           1 - (embedding <=> %s::vector) AS score
    FROM precedent_newplusplus.blocks
),
best_per_case AS (
    SELECT DISTINCT ON (record_id) *
    FROM scored
    ORDER BY record_id, score DESC, block_id ASC
)
SELECT block_id, record_id, block_type, block_text, case_number,
       case_name, court_name, decision_date, source_metadata, score
FROM best_per_case
ORDER BY score DESC, record_id ASC, block_id ASC
LIMIT %s
"""


def vector_literal(vector: np.ndarray) -> str:
    return "[" + ",".join(f"{float(value):.9g}" for value in vector) + "]"


class CandidateRetriever:
    def __init__(self, connection_factory=connect_database, *, top_k: int | None = None):
        self.connection_factory = connection_factory
        self.top_k = top_k or ServiceSettings().candidate_top_k

    def search(self, query_vector: np.ndarray) -> list[dict[str, Any]]:
        vector = np.asarray(query_vector, dtype=np.float32)
        settings = ServiceSettings()
        if (
            vector.shape != (settings.embedding_dimension,)
            or not np.isfinite(vector).all()
        ):
            raise SearchStageError(
                "RETRIEVAL_FAILED", "질문 벡터 형식이 잘못됐습니다.", "retrieval"
            )
        try:
            with self.connection_factory() as connection, connection.cursor() as cursor:
                cursor.execute(CANDIDATE_SQL, (vector_literal(vector), self.top_k))
                columns = [column.name for column in cursor.description]
                rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        except SearchStageError:
            raise
        except Exception as exc:
            raise SearchStageError(
                "RETRIEVAL_FAILED", "판례 후보 검색에 실패했습니다.", "retrieval", True
            ) from exc
        if len(rows) != self.top_k:
            raise SearchStageError(
                "RETRIEVAL_FAILED",
                f"후보가 {self.top_k}건이 아닙니다: {len(rows)}",
                "retrieval",
            )
        ids = [str(row["record_id"]) for row in rows]
        if len(ids) != len(set(ids)):
            raise SearchStageError(
                "RETRIEVAL_FAILED", "후보 판례 ID가 중복됐습니다.", "retrieval"
            )
        for rank, row in enumerate(rows, 1):
            score = float(row.pop("score"))
            if not math.isfinite(score):
                raise SearchStageError(
                    "RETRIEVAL_FAILED", "유사도 점수가 유효하지 않습니다.", "retrieval"
                )
            row["retrieval_score"] = score
            row["candidate_rank"] = rank
            row["candidate_block_id"] = row["block_id"]
            row["candidate_block_type"] = row["block_type"]
            row["evidence_text"] = row["block_text"]
        return rows
