from __future__ import annotations

import argparse
import json
import sys
from typing import Any

def verify_bm25_alignment(*, query: str, top_k: int) -> dict[str, Any]:
    from etl.fault_cases.src.agents.text_ml_case_search.rag.bm25_nori_retriever import (
        search_bm25_nori,
    )
    from etl.fault_cases.src.agents.text_ml_case_search.rag.es_client import (
        get_elasticsearch_client,
    )
    from etl.fault_cases.src.review_case.search.elasticsearch.bm25_retriever import (
        search_bm25 as search_legacy_bm25,
    )

    es_client = get_elasticsearch_client()
    legacy_results = search_legacy_bm25(query=query, top_k=top_k)
    agent_results = search_bm25_nori(es=es_client, search_text=query, top_k=top_k)

    legacy_chunk_ids = [_chunk_id(row) for row in legacy_results]
    agent_chunk_ids = [_chunk_id(row) for row in agent_results]

    return {
        "query": query,
        "top_k": top_k,
        "is_aligned": legacy_chunk_ids == agent_chunk_ids,
        "legacy_chunk_ids": legacy_chunk_ids,
        "agent_chunk_ids": agent_chunk_ids,
        "mismatch_positions": _mismatch_positions(
            legacy_chunk_ids=legacy_chunk_ids,
            agent_chunk_ids=agent_chunk_ids,
        ),
        "legacy_results": [_compact_legacy(row) for row in legacy_results],
        "agent_results": [_compact_agent(row) for row in agent_results],
    }


def _chunk_id(row: dict[str, Any]) -> str:
    return str(row.get("chunk_id") or "")


def _mismatch_positions(
    *,
    legacy_chunk_ids: list[str],
    agent_chunk_ids: list[str],
) -> list[dict[str, Any]]:
    max_len = max(len(legacy_chunk_ids), len(agent_chunk_ids))
    mismatches: list[dict[str, Any]] = []
    for index in range(max_len):
        legacy_value = legacy_chunk_ids[index] if index < len(legacy_chunk_ids) else None
        agent_value = agent_chunk_ids[index] if index < len(agent_chunk_ids) else None
        if legacy_value != agent_value:
            mismatches.append(
                {
                    "rank": index + 1,
                    "legacy_chunk_id": legacy_value,
                    "agent_chunk_id": agent_value,
                }
            )
    return mismatches


def _compact_legacy(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": row.get("rank"),
        "chunk_id": row.get("chunk_id"),
        "review_case_id": row.get("review_case_id"),
        "review_no": row.get("review_no"),
        "case_title": row.get("case_title"),
        "score": row.get("bm25_score"),
    }


def _compact_agent(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": row.get("rank"),
        "chunk_id": row.get("chunk_id"),
        "review_case_id": row.get("review_case_id"),
        "review_no": row.get("review_no"),
        "case_title": row.get("case_title"),
        "score": row.get("retriever_score"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare legacy review_case BM25 results with Agent BM25 results.",
    )
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    report = verify_bm25_alignment(query=args.query, top_k=args.top_k)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
