from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from psycopg2.extras import Json, execute_values

from .db import get_connection


JSON_FIELDS = {
    "matched_keywords",
    "quality_flags",
    "missing_fields",
    "traffic_verification_decision_reasons",
    "traffic_reclass_reasons",
    "traffic_evidence_terms",
    "traffic_signal_groups",
    "traffic_terms_for_count",
    "traffic_direct_terms",
    "traffic_legal_terms",
    "traffic_actor_terms",
    "traffic_action_terms",
    "traffic_situation_terms",
    "traffic_fault_terms",
    "fault_ratio_verification_decision_reasons",
    "fault_ratio_reclass_reasons",
    "fault_ratio_evidence_terms",
    "fault_ratio_signal_groups",
    "fault_ratio_explicit_terms",
    "fault_ratio_party_fault_terms",
    "fault_ratio_damage_terms",
    "fault_ratio_duty_terms",
    "fault_ratio_no_fault_terms",
    "fault_ratio_number_examples",
    "raw_json",
}


TRAFFIC_COLUMNS = [
    "case_id",
    "raw_case_id",
    "case_name",
    "case_number",
    "court_name",
    "court_type_code",
    "decision_date",
    "decision_date_raw",
    "decision_date_parse_ok",
    "decision_label",
    "case_category",
    "case_category_code",
    "judgment_type",
    "holding",
    "summary",
    "main_text",
    "full_text",
    "referenced_laws",
    "referenced_cases",
    "source_reference",
    "source_provider",
    "source_type",
    "source_bucket",
    "same_case_key",
    "matched_keywords",
    "quality_flags",
    "missing_fields",
    "traffic_label",
    "traffic_label_before_verification",
    "traffic_verification_source_label",
    "traffic_verification_final_label",
    "traffic_verification_decision_reasons",
    "traffic_relevance_score",
    "traffic_reclass_reasons",
    "traffic_evidence_terms",
    "traffic_signal_groups",
    "traffic_signal_group_count",
    "traffic_term_count",
    "traffic_terms_for_count",
    "traffic_direct_terms",
    "traffic_legal_terms",
    "traffic_actor_terms",
    "traffic_action_terms",
    "traffic_situation_terms",
    "traffic_fault_terms",
    "has_core_accident_context",
    "has_traffic_legal_plus_accident_context",
    "case_category_disallowed_for_confirmed",
    "duplicate_group_status",
    "duplicate_removed_count",
    "text_length",
    "main_text_length",
    "summary_length",
    "holding_length",
    "referenced_laws_length",
    "referenced_cases_length",
    "raw_json",
]


FAULT_RATIO_EXTRA_COLUMNS = [
    "traffic_case_id",
    "fault_ratio_label",
    "fault_ratio_label_before_verification",
    "fault_ratio_verification_source_label",
    "fault_ratio_verification_final_label",
    "fault_ratio_verification_decision_reasons",
    "fault_ratio_score",
    "fault_ratio_reclass_reasons",
    "fault_ratio_evidence_terms",
    "fault_ratio_signal_groups",
    "fault_ratio_signal_group_count",
    "fault_ratio_explicit_terms",
    "fault_ratio_party_fault_terms",
    "fault_ratio_damage_terms",
    "fault_ratio_duty_terms",
    "fault_ratio_no_fault_terms",
    "fault_ratio_number_examples",
    "has_core_fault_ratio_context",
    "has_damage_or_insurance_context",
    "no_fault_context_without_core",
]


FAULT_RATIO_COLUMNS = (
    TRAFFIC_COLUMNS[:1]
    + ["traffic_case_id"]
    + TRAFFIC_COLUMNS[1:-1]
    + FAULT_RATIO_EXTRA_COLUMNS[1:]
    + ["raw_json"]
)


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            row.setdefault("_jsonl_line_no", line_no)
            yield row


def normalize_date(value: Any) -> Any:
    if not value:
        return None
    if isinstance(value, str):
        return value[:10]
    return value


def as_json(value: Any) -> Json:
    if value is None:
        value = []
    return Json(value, dumps=lambda obj: json.dumps(obj, ensure_ascii=False))


def row_to_values(row: dict[str, Any], columns: list[str], dataset: str) -> tuple[Any, ...]:
    raw = dict(row)
    if dataset == "fault_ratio":
        row = dict(row)
        row.setdefault("traffic_case_id", row.get("case_id"))

    values = []
    for column in columns:
        if column == "raw_json":
            values.append(as_json(raw))
        elif column == "decision_date":
            values.append(normalize_date(row.get(column)))
        elif column in JSON_FIELDS:
            values.append(as_json(row.get(column)))
        else:
            values.append(row.get(column))
    return tuple(values)


def upsert_rows(
    db_name: str,
    table_name: str,
    columns: list[str],
    rows: Iterable[dict[str, Any]],
    dataset: str,
    batch_size: int = 500,
) -> int:
    update_columns = [column for column in columns if column != "case_id"]
    column_sql = ", ".join(columns)
    update_sql = ", ".join(f"{column} = EXCLUDED.{column}" for column in update_columns)
    sql = f"""
        INSERT INTO {table_name} ({column_sql})
        VALUES %s
        ON CONFLICT (case_id) DO UPDATE SET
            {update_sql},
            updated_at = now()
    """

    total = 0
    batch: list[tuple[Any, ...]] = []
    with get_connection(db_name) as conn:
        with conn.cursor() as cur:
            for row in rows:
                batch.append(row_to_values(row, columns, dataset))
                if len(batch) >= batch_size:
                    execute_values(cur, sql, batch, page_size=batch_size)
                    total += len(batch)
                    batch.clear()
            if batch:
                execute_values(cur, sql, batch, page_size=batch_size)
                total += len(batch)
    return total


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {"created_at": datetime.now().isoformat(timespec="seconds"), **report}
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
