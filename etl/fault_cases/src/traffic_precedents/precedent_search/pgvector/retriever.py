from __future__ import annotations

from functools import lru_cache
from typing import Any
from uuid import uuid4

from ..newplusplus.result_adapter import to_agent_row
from ..newplusplus.result_builder import build_top5
from ..newplusplus.search_service import PrecedentSearchService


@lru_cache(maxsize=1)
def _service() -> PrecedentSearchService:
    return PrecedentSearchService()


def search_query(
    dataset: str,
    query: str,
    top_k: int | None = None,
) -> list[dict[str, Any]]:
    if dataset != "fault_ratio":
        raise ValueError("NEW++ precedent search supports dataset='fault_ratio'")
    requested_top_k = top_k or 5
    if requested_top_k <= 0 or requested_top_k > 200:
        raise ValueError("top_k must be between 1 and 200")
    execution = _service().rank(
        {
            "contract_version": "precedent-newplusplus-v1",
            "request_id": str(uuid4()),
            "query_text": query,
        }
    )
    ranked = build_top5(
        execution["ranked_candidates"], final_top_k=requested_top_k
    )
    return [to_agent_row(case, rank) for rank, case in enumerate(ranked, 1)]
