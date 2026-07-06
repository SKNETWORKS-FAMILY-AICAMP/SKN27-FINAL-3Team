from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from psycopg2.extras import RealDictCursor, execute_batch

from .db_config import POSTGRES_EXPORT_ROOT, SETTINGS
from .db_connection import get_connection
from .search_text_builder import build_search_text
from .search_text_config import COMMON_EXTRA_LABELS


def fetch_documents() -> dict[str, dict[str, Any]]:
    with get_connection(SETTINGS.review_case_db) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM review_case_documents")
            return {str(row["review_case_id"]): dict(row) for row in cur.fetchall()}


def fetch_chunks() -> list[dict[str, Any]]:
    with get_connection(SETTINGS.review_case_db) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT chunk_id, review_case_id, review_no, chunk_type, chunk_text,
                       reference_chart_key, decision_fault_ratio
                FROM review_case_chunks
                ORDER BY review_no, sequence_no
                """
            )
            return [dict(row) for row in cur.fetchall()]


def marker_counts(chunks: list[dict[str, Any]], documents: dict[str, dict[str, Any]], built: dict[str, str]) -> dict:
    counters = Counter()
    by_type: dict[str, Counter] = {}
    for chunk in chunks:
        doc = documents.get(chunk["review_case_id"], {})
        text = built[chunk["chunk_id"]]
        chunk_type = chunk.get("chunk_type") or "unknown"
        by_type.setdefault(chunk_type, Counter())
        checks = {
            "has_search_text": bool(text.strip()),
            "has_review_no": bool(chunk.get("review_no") and str(chunk["review_no"]) in text),
            "has_reference_chart_key": bool(chunk.get("reference_chart_key") and str(chunk["reference_chart_key"]) in text),
            "has_decision_fault_ratio": bool(chunk.get("decision_fault_ratio") and str(chunk["decision_fault_ratio"]) in text),
            "has_standard_keywords": bool(
                doc.get("standard_scenario_keywords")
                and f"{COMMON_EXTRA_LABELS['standard_scenario_keywords']}:" in text
            ),
            "has_chunk_text": bool(chunk.get("chunk_text") and str(chunk["chunk_text"])[:30] in text),
        }
        for key, ok in checks.items():
            if ok:
                counters[key] += 1
                by_type[chunk_type][key] += 1
    return {
        "overall": dict(counters),
        "by_chunk_type": {chunk_type: dict(counter) for chunk_type, counter in sorted(by_type.items())},
    }


def rebuild(dry_run: bool = False) -> dict:
    documents = fetch_documents()
    chunks = fetch_chunks()
    built = {
        chunk["chunk_id"]: build_search_text(chunk, documents.get(chunk["review_case_id"], {}))
        for chunk in chunks
    }
    lengths = [len(value) for value in built.values()]
    type_counts = Counter(chunk.get("chunk_type") or "unknown" for chunk in chunks)
    markers = marker_counts(chunks, documents, built)

    if not dry_run:
        rows = [(search_text, len(search_text), chunk_id) for chunk_id, search_text in built.items()]
        with get_connection(SETTINGS.review_case_db) as conn:
            with conn.cursor() as cur:
                execute_batch(
                    cur,
                    """
                    UPDATE review_case_chunks
                    SET search_text = %s,
                        char_count = %s,
                        updated_at = now()
                    WHERE chunk_id = %s
                    """,
                    rows,
                    page_size=500,
                )

    samples = []
    for chunk in chunks[:8]:
        text = built[chunk["chunk_id"]]
        samples.append(
            {
                "chunk_id": chunk["chunk_id"],
                "review_no": chunk["review_no"],
                "chunk_type": chunk["chunk_type"],
                "search_text_preview": text[:700],
            }
        )

    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "db_name": SETTINGS.review_case_db,
        "dry_run": dry_run,
        "chunk_count": len(chunks),
        "document_count": len(documents),
        "chunk_type_counts": dict(sorted(type_counts.items())),
        "search_text_length": {
            "min": min(lengths) if lengths else 0,
            "max": max(lengths) if lengths else 0,
            "avg": int(sum(lengths) / len(lengths)) if lengths else 0,
        },
        "marker_counts": markers,
        "samples": samples,
    }
    report_path = POSTGRES_EXPORT_ROOT / "review_case_search_text_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild review_case_chunks.search_text.")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    report = rebuild(dry_run=parse_args().dry_run)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
