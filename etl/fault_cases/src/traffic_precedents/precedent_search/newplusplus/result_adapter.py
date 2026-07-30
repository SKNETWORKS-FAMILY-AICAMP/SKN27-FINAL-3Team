from __future__ import annotations

from typing import Any


def to_agent_row(case: dict[str, Any], rank: int) -> dict[str, Any]:
    evidence_text = str(case.get("evidence_text") or case.get("reranker_text") or "")
    return {
        "case_id": str(case.get("record_id") or ""),
        "case_number": str(case.get("case_number") or ""),
        "chunk_id": str(case.get("candidate_block_id") or ""),
        "chunk_index": rank,
        "chunk_type": str(case.get("candidate_block_type") or ""),
        "chunk_strategy": "semantic_newplusplus_bge",
        "case_name": str(case.get("case_name") or ""),
        "court_name": str(case.get("court_name") or ""),
        "decision_date": str(case.get("decision_date") or ""),
        "chunk_text": evidence_text,
        "search_text": evidence_text,
        "cosine_similarity": float(case.get("retrieval_score") or 0.0),
        "rank": rank,
        "metadata": {
            "rerank_score": float(case.get("rerank_score") or 0.0),
            "candidate_rank": int(case.get("candidate_rank") or rank),
            "score_type": "qwen_cosine_then_bge_rerank",
        },
    }
