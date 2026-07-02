"""Promote validated fault-standard staging rows into PostgreSQL core tables."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..staging_schema import table_ref as staging_table_ref
from .schema import CORE_TABLES_IN_DELETE_ORDER, create_core_schema, table_ref as core_table_ref


@dataclass(frozen=True)
class CoreBatch:
    """A selected staging batch that will become the active core dataset."""

    batch_id: int
    batch_name: str
    source_root_path: str | None
    preprocess_version: str | None


BLOCKING_VALIDATION_KEYS = (
    "rule_count",
    "party_count_not_two",
    "base_fault_missing",
    "adjustment_target_invalid",
    "variant_required_missing",
    "lane_step_path_invalid",
    "json_parse_error_rows",
)


def resolve_staging_batch(conn, batch_id: int | None = None, batch_name: str | None = None) -> CoreBatch:
    """Find the staging batch to promote.

    batch_id is exact. batch_name is convenient for repeatable local loads. If
    neither is supplied, the newest staging batch is used.
    """
    with conn.cursor() as cur:
        if batch_id is not None:
            cur.execute(
                f"""
                SELECT batch_id, batch_name, source_root_path, preprocess_version
                FROM {staging_table_ref("preprocess_batches")}
                WHERE batch_id = %s;
                """,
                (batch_id,),
            )
        elif batch_name:
            cur.execute(
                f"""
                SELECT batch_id, batch_name, source_root_path, preprocess_version
                FROM {staging_table_ref("preprocess_batches")}
                WHERE batch_name = %s
                ORDER BY created_at DESC
                LIMIT 1;
                """,
                (batch_name,),
            )
        else:
            cur.execute(
                f"""
                SELECT batch_id, batch_name, source_root_path, preprocess_version
                FROM {staging_table_ref("preprocess_batches")}
                ORDER BY created_at DESC
                LIMIT 1;
                """
            )
        row = cur.fetchone()

    if not row:
        selector = f"batch_id={batch_id}" if batch_id is not None else f"batch_name={batch_name!r}"
        raise ValueError(f"staging batch not found: {selector}")

    return CoreBatch(
        batch_id=int(row[0]),
        batch_name=str(row[1]),
        source_root_path=row[2],
        preprocess_version=row[3],
    )


def validate_staging_batch(conn, batch: CoreBatch) -> dict[str, int]:
    """Run core-promotion integrity checks against one staging batch."""
    batch_id = batch.batch_id
    checks: dict[str, int] = {}

    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {staging_table_ref('stg_rules')} WHERE batch_id = %s;", (batch_id,))
        checks["rule_count"] = int(cur.fetchone()[0])

        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM (
                SELECT r.rule_id, COUNT(p.party_id) AS party_count
                FROM {staging_table_ref("stg_rules")} r
                LEFT JOIN {staging_table_ref("stg_rule_parties")} p
                  ON p.batch_id = r.batch_id
                 AND p.rule_id = r.rule_id
                WHERE r.batch_id = %s
                GROUP BY r.rule_id
                HAVING COUNT(p.party_id) <> 2
            ) issue;
            """,
            (batch_id,),
        )
        checks["party_count_not_two"] = int(cur.fetchone()[0])

        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM {staging_table_ref("stg_rules")} r
            LEFT JOIN {staging_table_ref("stg_base_faults")} b
              ON b.batch_id = r.batch_id
             AND b.rule_id = r.rule_id
            WHERE r.batch_id = %s
              AND b.base_fault_id IS NULL;
            """,
            (batch_id,),
        )
        checks["base_fault_missing"] = int(cur.fetchone()[0])

        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM {staging_table_ref("stg_adjustment_factors")} a
            LEFT JOIN {staging_table_ref("stg_rule_parties")} p
              ON p.batch_id = a.batch_id
             AND p.rule_id = a.rule_id
             AND p.party_key = a.target_party_key
            WHERE a.batch_id = %s
              AND COALESCE(a.exclude_from_auto_calculation, FALSE) = FALSE
              AND (a.target_party_key IS NULL OR p.party_id IS NULL);
            """,
            (batch_id,),
        )
        checks["adjustment_target_invalid"] = int(cur.fetchone()[0])

        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM (
                SELECT r.rule_id
                FROM {staging_table_ref("stg_rules")} r
                LEFT JOIN {staging_table_ref("stg_variants")} v
                  ON v.batch_id = r.batch_id
                 AND v.rule_id = r.rule_id
                LEFT JOIN {staging_table_ref("stg_rule_scenarios")} s
                  ON s.batch_id = r.batch_id
                 AND s.rule_id = r.rule_id
                WHERE r.batch_id = %s
                  AND COALESCE(r.variants_required, FALSE) = TRUE
                GROUP BY r.rule_id
                HAVING COUNT(v.variant_id) + COUNT(s.scenario_id) = 0
            ) issue;
            """,
            (batch_id,),
        )
        checks["variant_required_missing"] = int(cur.fetchone()[0])

        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM {staging_table_ref("stg_lane_steps")} s
            LEFT JOIN {staging_table_ref("stg_lane_paths")} lp
              ON lp.batch_id = s.batch_id
             AND lp.rule_id = s.rule_id
             AND lp.party_key = s.party_key
            WHERE s.batch_id = %s
              AND s.rule_id IS NOT NULL
              AND s.party_key IS NOT NULL
              AND lp.lane_path_id IS NULL;
            """,
            (batch_id,),
        )
        checks["lane_step_path_invalid"] = int(cur.fetchone()[0])

        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM {staging_table_ref("stg_parse_quality_report")}
            WHERE batch_id = %s
              AND LOWER(COALESCE(parse_status, '')) IN ('json_error', 'invalid_json', 'parse_error');
            """,
            (batch_id,),
        )
        checks["json_parse_error_rows"] = int(cur.fetchone()[0])

    return checks


def blocking_validation_errors(checks: dict[str, int]) -> dict[str, int]:
    """Return only validation failures that must stop core promotion."""
    return {
        key: value
        for key, value in checks.items()
        if key in BLOCKING_VALIDATION_KEYS and (key != "rule_count" and value > 0 or key == "rule_count" and value == 0)
    }


def truncate_core_tables(conn) -> None:
    """Remove the current active core dataset while preserving core_loads history."""
    table_refs = ", ".join(core_table_ref(table_name) for table_name in CORE_TABLES_IN_DELETE_ORDER)
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE {table_refs} CASCADE;")


def insert_core_load(conn, batch: CoreBatch, mode: str, description: str | None) -> int:
    """Record a core promotion event and return its load id."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {core_table_ref("core_loads")} (
                source_batch_id,
                source_batch_name,
                load_mode,
                description
            )
            VALUES (%s, %s, %s, %s)
            RETURNING load_id;
            """,
            (batch.batch_id, batch.batch_name, mode, description),
        )
        return int(cur.fetchone()[0])


def insert_rulebooks(conn, batch: CoreBatch) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {core_table_ref("rulebooks")} (
                rulebook_id, source_batch_id, rulebook_name, source_type, source_subtype,
                source_file, published_year, source_reliability, attributes, raw_json
            )
            SELECT
                rulebook_id, batch_id, rulebook_name, source_type, source_subtype,
                source_file, published_year, source_reliability, attributes, raw_json
            FROM {staging_table_ref("stg_rulebooks")}
            WHERE batch_id = %s;
            """,
            (batch.batch_id,),
        )


def insert_rules(conn, batch: CoreBatch) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {core_table_ref("rules")} (
                rule_id, source_batch_id, rulebook_id, rule_code, rule_no, rule_title,
                rule_type, accident_group, accident_subgroup, normalized_ratio,
                party_a_ratio, party_b_ratio, base_fault_type, calculation_source,
                scenario_required, variants_required, auto_calculation_eligible,
                page_start, page_end, parse_status, attributes, raw_json
            )
            SELECT
                rule_id, batch_id, rulebook_id, rule_code, rule_no, rule_title,
                rule_type, accident_group, accident_subgroup, normalized_ratio,
                party_a_ratio, party_b_ratio, base_fault_type, calculation_source,
                scenario_required, variants_required, auto_calculation_eligible,
                page_start, page_end, parse_status, attributes, raw_json
            FROM {staging_table_ref("stg_rules")}
            WHERE batch_id = %s;
            """,
            (batch.batch_id,),
        )


def insert_rule_parties(conn, batch: CoreBatch) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {core_table_ref("rule_parties")} (
                party_id, source_batch_id, rule_id, rulebook_id, party_key, party_label,
                party_type, movement, road_position, signal_state, entry_timing,
                violation_type, raw_text, attributes, raw_json
            )
            SELECT
                party_id, batch_id, rule_id, rulebook_id, party_key, party_label,
                party_type, movement, road_position, signal_state, entry_timing,
                violation_type, raw_text, attributes, raw_json
            FROM {staging_table_ref("stg_rule_parties")}
            WHERE batch_id = %s;
            """,
            (batch.batch_id,),
        )


def insert_base_faults(conn, batch: CoreBatch) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {core_table_ref("base_faults")} (
                base_fault_id, source_batch_id, rule_id, rulebook_id, base_fault_type,
                calculation_source, party_a_ratio, party_b_ratio, normalized_ratio,
                scenario_required, variants_required, auto_calculation_eligible,
                is_one_sided_fault, is_equal_fault, raw_text, quality_flags,
                attributes, raw_json
            )
            SELECT
                base_fault_id, batch_id, rule_id, rulebook_id, base_fault_type,
                calculation_source, party_a_ratio, party_b_ratio, normalized_ratio,
                scenario_required, variants_required, auto_calculation_eligible,
                is_one_sided_fault, is_equal_fault, raw_text, quality_flags,
                attributes, raw_json
            FROM {staging_table_ref("stg_base_faults")}
            WHERE batch_id = %s;
            """,
            (batch.batch_id,),
        )


def insert_variants(conn, batch: CoreBatch) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {core_table_ref("variants")} (
                variant_id, source_batch_id, rule_id, rulebook_id, variant_key,
                variant_title, scenario_text, party_a_ratio, party_b_ratio,
                single_party_key, single_party_ratio, single_party_type,
                ratio_interpretation, needs_review, raw_text, attributes, raw_json
            )
            SELECT
                variant_id, batch_id, rule_id, rulebook_id, variant_key,
                variant_title, scenario_text, party_a_ratio, party_b_ratio,
                single_party_key, single_party_ratio, single_party_type,
                ratio_interpretation, needs_review, raw_text, attributes, raw_json
            FROM {staging_table_ref("stg_variants")}
            WHERE batch_id = %s;
            """,
            (batch.batch_id,),
        )


def insert_rule_scenarios(conn, batch: CoreBatch) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {core_table_ref("rule_scenarios")} (
                scenario_id, source_batch_id, rule_id, rulebook_id, scenario_key,
                scenario_title, scenario_text, party_a_ratio, party_b_ratio,
                single_party_key, single_party_ratio, single_party_type,
                raw_text, attributes, raw_json
            )
            SELECT
                scenario_id, batch_id, rule_id, rulebook_id, scenario_key,
                scenario_title, scenario_text, party_a_ratio, party_b_ratio,
                single_party_key, single_party_ratio, single_party_type,
                raw_text, attributes, raw_json
            FROM {staging_table_ref("stg_rule_scenarios")}
            WHERE batch_id = %s;
            """,
            (batch.batch_id,),
        )


def insert_adjustment_factors(conn, batch: CoreBatch) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {core_table_ref("adjustment_factors")} (
                adjustment_id, source_batch_id, rule_id, rulebook_id,
                target_party_key, target_party_type, target_party_id,
                factor_name, factor_category, delta, delta_direction, raw_delta,
                condition_text, explanation_text, raw_text, is_applicable,
                auto_calculation_eligible, exclude_from_auto_calculation,
                attributes, raw_json
            )
            SELECT
                a.adjustment_id, a.batch_id, a.rule_id, a.rulebook_id,
                a.target_party_key, a.target_party_type, p.party_id,
                a.factor_name, a.factor_category, a.delta, a.delta_direction, a.raw_delta,
                a.condition_text, a.explanation_text, a.raw_text, a.is_applicable,
                a.auto_calculation_eligible, a.exclude_from_auto_calculation,
                a.attributes, a.raw_json
            FROM {staging_table_ref("stg_adjustment_factors")} a
            LEFT JOIN {staging_table_ref("stg_rule_parties")} p
              ON p.batch_id = a.batch_id
             AND p.rule_id = a.rule_id
             AND p.party_key = a.target_party_key
            WHERE a.batch_id = %s;
            """,
            (batch.batch_id,),
        )


def insert_evidence_chunks(conn, batch: CoreBatch) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {core_table_ref("evidence_chunks")} (
                chunk_id, source_batch_id, rule_id, rulebook_id, block_id, chunk_type,
                chunk_text, rule_title, accident_group, accident_subgroup,
                accident_tags, source_reliability, metadata, attributes, raw_json
            )
            SELECT
                chunk_id, batch_id, NULLIF(rule_id, ''), rulebook_id, block_id, chunk_type,
                chunk_text, rule_title, accident_group, accident_subgroup,
                accident_tags, source_reliability, metadata, attributes, raw_json
            FROM {staging_table_ref("stg_evidence_chunks")}
            WHERE batch_id = %s;
            """,
            (batch.batch_id,),
        )


def insert_law_refs(conn, batch: CoreBatch) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {core_table_ref("law_refs")} (
                law_ref_id, source_batch_id, rule_id, rulebook_id,
                law_name, article, clause, raw_text, attributes, raw_json
            )
            SELECT
                law_ref_id, batch_id, NULLIF(rule_id, ''), rulebook_id,
                law_name, article, clause, raw_text, attributes, raw_json
            FROM {staging_table_ref("stg_law_refs")}
            WHERE batch_id = %s;
            """,
            (batch.batch_id,),
        )


def insert_reference_cases(conn, batch: CoreBatch) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {core_table_ref("reference_cases")} (
                case_id, source_batch_id, rule_id, rulebook_id, case_type,
                case_title, claim_ratio, respondent_ratio, fault_ratio_in_case,
                raw_text, attributes, raw_json
            )
            SELECT
                case_id, batch_id, NULLIF(rule_id, ''), rulebook_id, case_type,
                case_title, claim_ratio, respondent_ratio, fault_ratio_in_case,
                raw_text, attributes, raw_json
            FROM {staging_table_ref("stg_reference_cases")}
            WHERE batch_id = %s;
            """,
            (batch.batch_id,),
        )


def insert_usage_notes(conn, batch: CoreBatch) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {core_table_ref("usage_notes")} (
                usage_note_id, source_batch_id, rule_id, rulebook_id,
                note_type, note_text, raw_text, attributes, raw_json
            )
            SELECT
                usage_note_id, batch_id, NULLIF(rule_id, ''), rulebook_id,
                note_type, note_text, raw_text, attributes, raw_json
            FROM {staging_table_ref("stg_usage_notes")}
            WHERE batch_id = %s;
            """,
            (batch.batch_id,),
        )


def insert_contexts(conn, batch: CoreBatch) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {core_table_ref("contexts")} (
                context_id, source_batch_id, rule_id, rulebook_id,
                context_type, road_area, signal_type, raw_text,
                attributes, raw_json
            )
            SELECT
                context_id, batch_id, NULLIF(rule_id, ''), rulebook_id,
                context_type, road_area, signal_type, raw_text,
                attributes, raw_json
            FROM {staging_table_ref("stg_contexts")}
            WHERE batch_id = %s;
            """,
            (batch.batch_id,),
        )


def insert_shared_rule_group_rows(conn, batch: CoreBatch) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {core_table_ref("shared_rule_group_rows")} (
                shared_row_id, source_batch_id, rulebook_id, source_table,
                shared_group_id, rule_id, member_rule_id, block_id, chunk_id,
                law_ref_id, text, metadata, attributes, raw_json
            )
            SELECT
                shared_row_id, batch_id, rulebook_id, source_table,
                shared_group_id, NULLIF(rule_id, ''), member_rule_id, block_id,
                chunk_id, law_ref_id, text, metadata, attributes, raw_json
            FROM {staging_table_ref("stg_shared_rule_group_rows")}
            WHERE batch_id = %s;
            """,
            (batch.batch_id,),
        )


def insert_lane_paths(conn, batch: CoreBatch) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {core_table_ref("lane_paths")} (
                lane_path_id, source_batch_id, rule_id, rulebook_id, party_key,
                party_id, entry_direction, exit_direction, entry_lane, circulation_lane,
                exit_lane, is_lane_changing, is_exiting, raw_text,
                attributes, raw_json
            )
            SELECT
                lp.lane_path_id, lp.batch_id, NULLIF(lp.rule_id, ''), lp.rulebook_id, lp.party_key,
                p.party_id,
                lp.entry_direction, lp.exit_direction, lp.entry_lane, lp.circulation_lane,
                lp.exit_lane, lp.is_lane_changing, lp.is_exiting, lp.raw_text,
                lp.attributes, lp.raw_json
            FROM {staging_table_ref("stg_lane_paths")} lp
            LEFT JOIN {staging_table_ref("stg_rule_parties")} p
              ON p.batch_id = lp.batch_id
             AND p.rule_id = lp.rule_id
             AND p.party_key = lp.party_key
            WHERE lp.batch_id = %s;
            """,
            (batch.batch_id,),
        )


def insert_lane_steps(conn, batch: CoreBatch) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {core_table_ref("lane_steps")} (
                lane_step_id, source_batch_id, rule_id, rulebook_id, party_key,
                party_id, lane_path_id, seq, movement, lane, direction, source, source_text,
                confidence, attributes, raw_json
            )
            SELECT
                s.lane_step_id, s.batch_id, NULLIF(s.rule_id, ''), s.rulebook_id, s.party_key,
                p.party_id,
                lp.lane_path_id,
                s.seq, s.movement, s.lane, s.direction, s.source, s.source_text,
                s.confidence, s.attributes, s.raw_json
            FROM {staging_table_ref("stg_lane_steps")} s
            LEFT JOIN {staging_table_ref("stg_rule_parties")} p
              ON p.batch_id = s.batch_id
             AND p.rule_id = s.rule_id
             AND p.party_key = s.party_key
            LEFT JOIN LATERAL (
                SELECT lane_path_id
                FROM {staging_table_ref("stg_lane_paths")} lp
                WHERE lp.batch_id = s.batch_id
                  AND lp.rule_id = s.rule_id
                  AND lp.party_key = s.party_key
                ORDER BY lane_path_id
                LIMIT 1
            ) lp ON TRUE
            WHERE s.batch_id = %s;
            """,
            (batch.batch_id,),
        )


CORE_INSERT_STEPS = (
    insert_rulebooks,
    insert_rules,
    insert_rule_parties,
    insert_base_faults,
    insert_variants,
    insert_rule_scenarios,
    insert_adjustment_factors,
    insert_evidence_chunks,
    insert_law_refs,
    insert_reference_cases,
    insert_usage_notes,
    insert_contexts,
    insert_shared_rule_group_rows,
    insert_lane_paths,
    insert_lane_steps,
)


def core_table_counts(conn) -> dict[str, int]:
    """Return row counts for the service-facing core tables."""
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        for table_name in reversed(CORE_TABLES_IN_DELETE_ORDER):
            cur.execute(f"SELECT COUNT(*) FROM {core_table_ref(table_name)};")
            counts[table_name] = int(cur.fetchone()[0])
    return counts


def promote_staging_to_core(
    conn,
    batch_id: int | None = None,
    batch_name: str | None = None,
    mode: str = "replace-core",
    description: str | None = None,
    allow_validation_issues: bool = False,
) -> dict[str, Any]:
    """Create core schema and promote one validated staging batch into core."""
    if mode != "replace-core":
        raise ValueError("Only replace-core mode is supported for the active core dataset.")

    create_core_schema(conn)
    batch = resolve_staging_batch(conn, batch_id=batch_id, batch_name=batch_name)
    checks = validate_staging_batch(conn, batch)
    failures = blocking_validation_errors(checks)
    if failures and not allow_validation_issues:
        raise ValueError(f"core promotion validation failed: {failures}")

    truncate_core_tables(conn)
    load_id = insert_core_load(conn, batch, mode=mode, description=description)
    for step in CORE_INSERT_STEPS:
        step(conn, batch)

    conn.commit()

    return {
        "load_id": load_id,
        "batch_id": batch.batch_id,
        "batch_name": batch.batch_name,
        "mode": mode,
        "validation": checks,
        "validation_failures": failures,
        "core_counts": core_table_counts(conn),
    }
