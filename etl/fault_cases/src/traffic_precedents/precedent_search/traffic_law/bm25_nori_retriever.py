from __future__ import annotations

import argparse
import json
import re
from typing import Any

from elasticsearch import Elasticsearch

from etl.fault_cases.src.traffic_precedents.precedent_search.elasticsearch.client import (
    get_elasticsearch_client,
)
from etl.fault_cases.src.traffic_precedents.precedent_search.search_config import (
    DATASET_SEARCH_CONFIGS,
    ELASTICSEARCH_SETTINGS,
)


TRAFFIC_LAW_DATASET = "traffic"
TRAFFIC_LAW_INDEX_NAME = DATASET_SEARCH_CONFIGS[TRAFFIC_LAW_DATASET]["elasticsearch_index"]

TRAFFIC_LAW_BM25_FIELDS = [
    "search_text^4",
    "chunk_text^2",
    "case_name^1.5",
    "search_text_standard",
    "chunk_text_standard",
]

HIGHLIGHT_FIELDS = {
    "search_text": {"fragment_size": 180, "number_of_fragments": 2},
    "chunk_text": {"fragment_size": 180, "number_of_fragments": 2},
}

TAG_RE = re.compile(r"</?em>")


def strip_highlight_tags(value: str) -> str:
    return TAG_RE.sub("", value or "").strip()


def build_traffic_law_bm25_query(*, query: str, top_k: int) -> dict[str, Any]:
    return {
        "size": top_k,
        "query": {
            "multi_match": {
                "query": query,
                "fields": TRAFFIC_LAW_BM25_FIELDS,
                "type": "best_fields",
                "operator": "or",
            }
        },
        "highlight": {"fields": HIGHLIGHT_FIELDS},
    }


def _matched_snippets(highlight: dict[str, Any]) -> list[str]:
    snippets: list[str] = []
    for field_name in ("search_text", "chunk_text"):
        values = highlight.get(field_name) or []
        if not isinstance(values, list):
            continue
        for value in values:
            snippet = strip_highlight_tags(str(value))
            if snippet and snippet not in snippets:
                snippets.append(snippet)
    return snippets


def _preview(text: str, max_len: int = 300) -> str:
    value = " ".join((text or "").split())
    if len(value) <= max_len:
        return value
    return value[: max_len - 3].rstrip() + "..."


def _format_hit(*, rank: int, hit: dict[str, Any]) -> dict[str, Any]:
    source = hit.get("_source") or {}
    highlight = hit.get("highlight") or {}
    chunk_text = source.get("chunk_text") or ""
    search_text = source.get("search_text") or chunk_text

    return {
        "query_source": "traffic_law",
        "retriever": "traffic_law_bm25_nori",
        "source_type": "traffic_precedent",
        "rank": rank,
        "case_id": source.get("case_id") or "",
        "chunk_id": source.get("chunk_id") or "",
        "chunk_index": source.get("chunk_index"),
        "chunk_type": source.get("chunk_type") or "",
        "chunk_strategy": source.get("chunk_strategy") or "",
        "case_name": source.get("case_name") or "",
        "case_number": source.get("case_number") or "",
        "court_name": source.get("court_name") or "",
        "decision_date": source.get("decision_date") or "",
        "retriever_score": float(hit.get("_score") or 0.0),
        "score_type": "bm25_score",
        "index": hit.get("_index") or "",
        "source_reference": build_traffic_law_source_reference(
            case_id=source.get("case_id"),
            chunk_id=source.get("chunk_id"),
        ),
        "chunk_preview": _preview(chunk_text),
        "search_preview": _preview(search_text),
        "matched_snippets": _matched_snippets(highlight),
        "highlight": highlight,
        "metadata": source.get("metadata") or {},
    }


def build_traffic_law_source_reference(*, case_id: Any, chunk_id: Any) -> str:
    case_key = str(case_id or "unknown_case")
    chunk_key = str(chunk_id or "unknown_chunk")
    return f"precedent_traffic_db:{case_key}#{chunk_key}"


def search_traffic_law_bm25(
    *,
    query: str,
    top_k: int | None = None,
    es: Elasticsearch | None = None,
    index_name: str = TRAFFIC_LAW_INDEX_NAME,
) -> list[dict[str, Any]]:
    search_text = (query or "").strip()
    if not search_text:
        return []

    client = es or get_elasticsearch_client()
    limit = top_k or ELASTICSEARCH_SETTINGS.default_top_k
    body = build_traffic_law_bm25_query(query=search_text, top_k=limit)
    response = client.search(index=index_name, **body)
    hits = response.get("hits", {}).get("hits", [])

    return [_format_hit(rank=rank, hit=hit) for rank, hit in enumerate(hits, start=1)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run BM25/Nori search for traffic law precedents.")
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=ELASTICSEARCH_SETTINGS.default_top_k)
    parser.add_argument("--include-raw-highlight", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    results = search_traffic_law_bm25(query=args.query, top_k=args.top_k)
    if not args.include_raw_highlight:
        for row in results:
            row.pop("highlight", None)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

