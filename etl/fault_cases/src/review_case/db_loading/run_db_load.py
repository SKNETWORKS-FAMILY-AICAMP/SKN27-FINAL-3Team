from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from psycopg2.extras import Json, execute_values

from .db_config import POSTGRES_EXPORT_ROOT, PREPROCESSED_DIR, SETTINGS
from .db_connection import get_connection
from .load_common import as_json, make_search_text, read_json, read_jsonl, text_hash


DOCUMENT_COLUMNS = [
    "review_case_id", "review_no", "run_id", "source_ref", "party_type",
    "header_title_raw", "header_accident_group", "header_road_context", "header_parse_method",
    "case_title", "case_condition", "fault_type", "reference_chart_key", "reference_chart_no",
    "reference_chart_sub_no", "standard_scenario_raw", "standard_scenario_keywords",
    "signal_condition", "road_feature", "standard_a_behavior", "standard_b_behavior",
    "decision_fault_ratio", "a_role", "b_role", "a_ratio", "b_ratio",
    "claimant_final_ratio", "respondent_final_ratio", "claimant_standard_behavior",
    "respondent_standard_behavior", "accident_content", "reference_standard_no",
    "reference_standard_text", "base_fault_ratio_text", "claimant_argument",
    "respondent_argument", "evidence_text", "main_issue", "decision_basis",
    "decision_reason", "final_ratio_text", "toc_item_id", "toc_chart_key",
    "toc_case_title", "toc_case_condition", "toc_chapter_title", "toc_large_category",
    "toc_middle_category", "toc_fault_type", "metadata_source", "metadata_enrichment_flags",
    "pdf_page_start", "pdf_page_end", "book_page_start", "book_page_end", "raw_text",
    "clean_text", "source_type", "source_reliability_score", "parse_status",
    "quality_flags", "raw_json",
]

SOURCE_CHUNK_COLUMNS = [
    "source_chunk_id", "review_case_id", "review_no", "run_id", "sequence_no",
    "chunk_text", "clean_text", "page_start", "page_end", "pdf_page_start", "pdf_page_end",
    "book_page_start", "book_page_end", "char_count", "source_ref", "source_type",
    "source_reliability_score", "raw_json",
]

CHUNK_COLUMNS = [
    "chunk_id", "review_case_id", "review_no", "run_id", "chunk_type", "parent_chunk_id",
    "part_index", "sequence_no", "chunk_text", "search_text", "char_count", "token_count",
    "text_hash", "party_type", "case_title", "reference_chart_key",
    "standard_scenario_keywords", "decision_fault_ratio", "claimant_final_ratio",
    "respondent_final_ratio", "source_ref", "source_type", "source_reliability_score",
    "parse_status", "quality_flags", "raw_json",
]

QUALITY_COLUMNS = [
    "quality_report_id", "review_case_id", "review_no", "run_id", "parse_status",
    "chunk_count", "fatal_flags", "warning_flags", "missing_fields", "quality_flags",
    "source_ref", "memo", "raw_json", "validated_at",
]

TOC_ITEM_COLUMNS = [
    "toc_item_id", "run_id", "toc_order", "reference_chart_key", "chart_no",
    "chart_sub_no", "toc_title", "chapter_title", "large_category", "middle_category",
    "case_title", "case_condition", "fault_type", "book_page_no", "toc_pdf_page_no",
    "source_type", "parse_status", "quality_flags", "raw_json",
]

TOC_LINK_COLUMNS = [
    "toc_case_link_id", "run_id", "toc_item_id", "review_case_id", "review_no",
    "reference_chart_key", "chart_key", "document_reference_chart_key", "toc_chart_key",
    "toc_case_title", "toc_case_condition", "chart_key_relation", "toc_book_page_no",
    "case_book_page_start", "link_method", "match_status", "match_reason",
    "mismatch_reason", "quality_flags", "raw_json",
]

JSON_COLUMNS = {
    "standard_scenario_keywords",
    "metadata_enrichment_flags",
    "quality_flags",
    "fatal_flags",
    "warning_flags",
    "missing_fields",
    "raw_json",
}


def json_value(column: str, value: Any, raw: dict[str, Any]) -> Any:
    if column == "raw_json":
        return as_json(raw, default={})
    if column in JSON_COLUMNS:
        return as_json(value)
    return value


def upsert_rows(table: str, columns: list[str], rows: list[tuple[Any, ...]], conflict_column: str) -> int:
    if not rows:
        return 0
    update_columns = [column for column in columns if column != conflict_column]
    sql = f"""
        INSERT INTO {table} ({", ".join(columns)})
        VALUES %s
        ON CONFLICT ({conflict_column}) DO UPDATE SET
            {", ".join(f"{column} = EXCLUDED.{column}" for column in update_columns)}
    """
    if "updated_at" in table:
        pass
    with get_connection(SETTINGS.review_case_db) as conn:
        with conn.cursor() as cur:
            execute_values(cur, sql, rows, page_size=500)
    return len(rows)


def truncate_loaded_tables() -> None:
    tables = [
        "review_case_toc_case_links",
        "review_case_toc_items",
        "review_case_quality_reports",
        "review_case_chunks",
        "review_case_source_chunks",
        "review_case_documents",
        "review_case_preprocess_runs",
    ]
    with get_connection(SETTINGS.review_case_db) as conn:
        with conn.cursor() as cur:
            for table in tables:
                cur.execute(f"TRUNCATE TABLE {table} CASCADE")


def insert_preprocess_run(preprocessed_dir: Path, run_id: str) -> None:
    summary = read_json(preprocessed_dir / "preprocessing_summary.json")
    loader_report = read_json(preprocessed_dir / "loader_report.json")
    page_coverage = read_json(preprocessed_dir / "page_coverage.json")
    sql = """
        INSERT INTO review_case_preprocess_runs (
            run_id, source_pdf_name, source_pdf_path, preprocessed_artifact_path,
            document_count, source_chunk_count, rag_chunk_count, quality_report_count,
            toc_item_count, toc_case_link_count, valid_document_count,
            review_required_document_count, fatal_flag_counts, warning_flag_counts,
            loader_report, page_coverage, preprocessing_summary
        )
        VALUES %s
        ON CONFLICT (run_id) DO UPDATE SET
            preprocessing_summary = EXCLUDED.preprocessing_summary
    """
    value = (
        run_id,
        Path(summary.get("pdf_path", "")).name if summary.get("pdf_path") else None,
        summary.get("pdf_path"),
        str(preprocessed_dir),
        summary.get("document_count"),
        summary.get("source_chunk_count"),
        summary.get("chunk_count"),
        summary.get("quality_report_count"),
        summary.get("toc_item_count"),
        summary.get("toc_case_link_count"),
        summary.get("valid_document_count"),
        summary.get("review_required_document_count"),
        Json(summary.get("fatal_flag_counts") or {}),
        Json(summary.get("warning_flag_counts") or {}),
        Json(loader_report),
        Json(page_coverage),
        Json(summary),
    )
    with get_connection(SETTINGS.review_case_db) as conn:
        with conn.cursor() as cur:
            execute_values(cur, sql, [value])


def load_documents(preprocessed_dir: Path, run_id: str) -> tuple[int, dict[str, dict[str, Any]], dict[str, str]]:
    rows = []
    document_by_id = {}
    review_id_by_no = {}
    for raw in read_jsonl(preprocessed_dir / "review_case_documents.jsonl"):
        row = dict(raw)
        row["run_id"] = run_id
        document_by_id[row["review_case_id"]] = row
        review_id_by_no[row["review_no"]] = row["review_case_id"]
        rows.append(tuple(json_value(column, row.get(column), raw) for column in DOCUMENT_COLUMNS))
    return upsert_rows("review_case_documents", DOCUMENT_COLUMNS, rows, "review_case_id"), document_by_id, review_id_by_no


def load_source_chunks(preprocessed_dir: Path, run_id: str, review_id_by_no: dict[str, str]) -> int:
    rows = []
    for raw in read_jsonl(preprocessed_dir / "review_case_source_chunks.jsonl"):
        row = dict(raw)
        row["run_id"] = run_id
        row["review_case_id"] = review_id_by_no.get(row.get("review_no"))
        row["char_count"] = len(row.get("chunk_text") or "")
        row.setdefault("clean_text", row.get("chunk_text"))
        rows.append(tuple(json_value(column, row.get(column), raw) for column in SOURCE_CHUNK_COLUMNS))
    return upsert_rows("review_case_source_chunks", SOURCE_CHUNK_COLUMNS, rows, "source_chunk_id")


def load_chunks(preprocessed_dir: Path, run_id: str, document_by_id: dict[str, dict[str, Any]]) -> int:
    rows = []
    for raw in read_jsonl(preprocessed_dir / "review_case_chunks.jsonl"):
        row = dict(raw)
        doc = document_by_id.get(row.get("review_case_id") or "", {})
        row["run_id"] = run_id
        row["parent_chunk_id"] = row.get("parent_chunk_id")
        row["part_index"] = row.get("part_index", 0)
        row["search_text"] = row.get("search_text") or make_search_text(row, document_by_id)
        row["char_count"] = len(row.get("chunk_text") or "")
        row["text_hash"] = text_hash(row.get("chunk_text"))
        row["party_type"] = row.get("party_type") or doc.get("party_type")
        row["case_title"] = row.get("case_title") or doc.get("case_title")
        row["standard_scenario_keywords"] = row.get("standard_scenario_keywords") or doc.get("standard_scenario_keywords")
        row["claimant_final_ratio"] = row.get("claimant_final_ratio") or doc.get("claimant_final_ratio")
        row["respondent_final_ratio"] = row.get("respondent_final_ratio") or doc.get("respondent_final_ratio")
        rows.append(tuple(json_value(column, row.get(column), raw) for column in CHUNK_COLUMNS))
    return upsert_rows("review_case_chunks", CHUNK_COLUMNS, rows, "chunk_id")


def load_quality_reports(preprocessed_dir: Path, run_id: str) -> int:
    rows = []
    for raw in read_jsonl(preprocessed_dir / "quality_report.jsonl"):
        row = dict(raw)
        row["run_id"] = run_id
        row["quality_report_id"] = f"quality_{row.get('review_case_id') or row.get('review_no')}"
        rows.append(tuple(json_value(column, row.get(column), raw) for column in QUALITY_COLUMNS))
    return upsert_rows("review_case_quality_reports", QUALITY_COLUMNS, rows, "quality_report_id")


def load_toc_items(preprocessed_dir: Path, run_id: str) -> int:
    rows = []
    for index, raw in enumerate(read_jsonl(preprocessed_dir / "toc" / "review_case_toc_items.jsonl"), start=1):
        row = dict(raw)
        row["run_id"] = run_id
        row["toc_order"] = index
        row["reference_chart_key"] = row.get("chart_key")
        row["toc_title"] = row.get("case_title")
        rows.append(tuple(json_value(column, row.get(column), raw) for column in TOC_ITEM_COLUMNS))
    return upsert_rows("review_case_toc_items", TOC_ITEM_COLUMNS, rows, "toc_item_id")


def load_toc_case_links(preprocessed_dir: Path, run_id: str) -> int:
    rows = []
    for raw in read_jsonl(preprocessed_dir / "toc" / "review_case_toc_case_links.jsonl"):
        row = dict(raw)
        row["run_id"] = run_id
        row["toc_case_link_id"] = row.get("link_id")
        row["reference_chart_key"] = row.get("chart_key")
        rows.append(tuple(json_value(column, row.get(column), raw) for column in TOC_LINK_COLUMNS))
    return upsert_rows("review_case_toc_case_links", TOC_LINK_COLUMNS, rows, "toc_case_link_id")


def run_load(preprocessed_dir: Path, reset: bool = True) -> dict:
    run_id = "review_case_preprocessed_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    if reset:
        truncate_loaded_tables()
    insert_preprocess_run(preprocessed_dir, run_id)
    document_count, document_by_id, review_id_by_no = load_documents(preprocessed_dir, run_id)
    counts = {
        "review_case_documents": document_count,
        "review_case_source_chunks": load_source_chunks(preprocessed_dir, run_id, review_id_by_no),
        "review_case_chunks": load_chunks(preprocessed_dir, run_id, document_by_id),
        "review_case_quality_reports": load_quality_reports(preprocessed_dir, run_id),
        "review_case_toc_items": load_toc_items(preprocessed_dir, run_id),
        "review_case_toc_case_links": load_toc_case_links(preprocessed_dir, run_id),
    }
    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "run_id": run_id,
        "db_name": SETTINGS.review_case_db,
        "preprocessed_dir": str(preprocessed_dir),
        "reset_before_load": reset,
        "loaded_counts": counts,
    }
    report_path = POSTGRES_EXPORT_ROOT / "review_case_db_load_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load review case preprocessing artifacts into PostgreSQL.")
    parser.add_argument("--preprocessed-dir", type=Path, default=PREPROCESSED_DIR)
    parser.add_argument("--no-reset", action="store_true", help="Do not truncate review_case load tables before loading.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_load(args.preprocessed_dir, reset=not args.no_reset)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

