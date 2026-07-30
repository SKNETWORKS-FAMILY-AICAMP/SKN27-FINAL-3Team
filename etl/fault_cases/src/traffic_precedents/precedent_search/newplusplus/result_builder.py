"""리랭크 결과를 외부 Top5 계약으로 축약."""

from __future__ import annotations

import math
from typing import Any


def build_top5(
    scored_candidates: list[dict[str, Any]], *, final_top_k: int = 5
) -> list[dict[str, Any]]:
    ids = [str(row["record_id"]) for row in scored_candidates]
    if len(ids) != len(set(ids)):
        raise ValueError("중복 판례가 있습니다.")
    if len(scored_candidates) < final_top_k:
        raise ValueError(f"결과가 {final_top_k}건보다 적습니다.")
    for row in scored_candidates:
        if not math.isfinite(float(row["rerank_score"])):
            raise ValueError("리랭커 점수가 유효하지 않습니다.")
    ordered = sorted(
        scored_candidates,
        key=lambda row: (
            -float(row["rerank_score"]),
            int(row["candidate_rank"]),
            str(row["record_id"]),
        ),
    )[:final_top_k]
    fields = (
        "record_id",
        "case_number",
        "case_name",
        "court_name",
        "decision_date",
        "candidate_block_id",
        "candidate_block_type",
        "evidence_text",
        "retrieval_score",
        "rerank_score",
    )
    return [
        {"rank": rank, **{field: row.get(field, "") for field in fields}}
        for rank, row in enumerate(ordered, 1)
    ]

