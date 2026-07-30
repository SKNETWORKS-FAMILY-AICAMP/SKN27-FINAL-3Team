"""BGE 리랭커에 전달할 판례별 사고·판단 문맥."""

from __future__ import annotations

import hashlib
from typing import Any

import numpy as np

from .candidate_retriever import vector_literal
from .db import connect_database
from .errors import SearchStageError


def build_case_context(
    case_number: str, case_name: str, accident_fact: str, fault_decision: str
) -> str:
    return "\n\n".join(
        (
            "[사건 정보]\n"
            f"사건번호: {case_number or '[정보 없음]'}\n"
            f"사건명: {case_name or '[정보 없음]'}",
            f"[사고 사실]\n{accident_fact or '[해당 블록 없음]'}",
            f"[법원 과실·책임 판단]\n{fault_decision or '[해당 블록 없음]'}",
        )
    )


CONTEXT_SQL = """
WITH wanted(record_id) AS (SELECT unnest(%s::text[])),
ranked AS (
  SELECT b.record_id, b.block_type, b.block_id, b.block_text,
         row_number() OVER (
           PARTITION BY b.record_id, b.block_type
           ORDER BY (b.embedding <=> %s::vector) ASC, b.block_id ASC
         ) AS rn
  FROM precedent_newplusplus.blocks b
  JOIN wanted w USING(record_id)
  WHERE b.block_type IN ('ACCIDENT_FACT', 'FAULT_DECISION')
)
SELECT record_id, block_type, block_text FROM ranked WHERE rn = 1
"""


class CaseContextBuilder:
    def __init__(self, connection_factory=connect_database):
        self.connection_factory = connection_factory

    def build_many(
        self, query_vector: np.ndarray, candidates: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        ids = [str(row["record_id"]) for row in candidates]
        try:
            with self.connection_factory() as connection, connection.cursor() as cursor:
                cursor.execute(CONTEXT_SQL, (ids, vector_literal(query_vector)))
                role_rows = cursor.fetchall()
        except Exception as exc:
            raise SearchStageError(
                "CONTEXT_FAILED", "판례 의미 문맥 구성에 실패했습니다.", "context", True
            ) from exc
        roles: dict[tuple[str, str], str] = {
            (str(record_id), str(block_type)): str(text)
            for record_id, block_type, text in role_rows
        }
        result = []
        for candidate in candidates:
            record_id = str(candidate["record_id"])
            context = build_case_context(
                candidate.get("case_number", ""),
                candidate.get("case_name", ""),
                roles.get((record_id, "ACCIDENT_FACT"), ""),
                roles.get((record_id, "FAULT_DECISION"), ""),
            )
            row = dict(candidate)
            row["reranker_text"] = context
            row["input_sha256"] = hashlib.sha256(
                context.encode("utf-8")
            ).hexdigest()
            result.append(row)
        return result
