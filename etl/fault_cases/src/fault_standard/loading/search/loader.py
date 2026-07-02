"""Build PostgreSQL search documents from fault-standard core tables."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.schema import table_ref as core_table_ref
from .schema import create_search_schema, table_ref as search_table_ref


DEFAULT_DOCUMENT_STRATEGY = "rule_summary_plus_evidence"


@dataclass(frozen=True)
class SearchSource:
    """The core dataset selected as the source for search documents."""

    source_batch_id: int
    source_core_load_id: int | None
    source_batch_name: str | None


def resolve_search_source(
    conn,
    source_batch_id: int | None = None,
    source_core_load_id: int | None = None,
) -> SearchSource:
    """Resolve the core batch used to build search documents."""
    with conn.cursor() as cur:
        if source_batch_id is not None:
            cur.execute(
                f"""
                SELECT MAX(load_id), MAX(source_batch_name)
                FROM {core_table_ref("core_loads")}
                WHERE source_batch_id = %s;
                """,
                (source_batch_id,),
            )
            row = cur.fetchone()
            return SearchSource(
                source_batch_id=source_batch_id,
                source_core_load_id=row[0],
                source_batch_name=row[1],
            )

        if source_core_load_id is not None:
            cur.execute(
                f"""
                SELECT source_batch_id, source_batch_name
                FROM {core_table_ref("core_loads")}
                WHERE load_id = %s;
                """,
                (source_core_load_id,),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"core load not found: {source_core_load_id}")
            return SearchSource(
                source_batch_id=int(row[0]),
                source_core_load_id=source_core_load_id,
                source_batch_name=row[1],
            )

        cur.execute(
            f"""
            SELECT load_id, source_batch_id, source_batch_name
            FROM {core_table_ref("core_loads")}
            ORDER BY created_at DESC, load_id DESC
            LIMIT 1;
            """
        )
        row = cur.fetchone()
        if row:
            return SearchSource(
                source_core_load_id=int(row[0]),
                source_batch_id=int(row[1]),
                source_batch_name=row[2],
            )

        cur.execute(f"SELECT source_batch_id FROM {core_table_ref('rules')} ORDER BY source_batch_id DESC LIMIT 1;")
        row = cur.fetchone()
        if not row:
            raise ValueError("core rules are empty. Run core promotion before building search documents.")
        return SearchSource(source_batch_id=int(row[0]), source_core_load_id=None, source_batch_name=None)


def validate_core_source(conn, source: SearchSource) -> dict[str, int]:
    """Validate that core has enough data to build useful search documents."""
    checks: dict[str, int] = {}
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {core_table_ref('rules')} WHERE source_batch_id = %s;", (source.source_batch_id,))
        checks["core_rule_count"] = int(cur.fetchone()[0])

        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM (
                SELECT r.rule_id
                FROM {core_table_ref("rules")} r
                LEFT JOIN {core_table_ref("rule_parties")} p
                  ON p.rule_id = r.rule_id
                WHERE r.source_batch_id = %s
                GROUP BY r.rule_id
                HAVING COUNT(p.party_id) = 0
            ) issue;
            """,
            (source.source_batch_id,),
        )
        checks["rules_without_parties"] = int(cur.fetchone()[0])

        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM {core_table_ref("rules")} r
            LEFT JOIN {core_table_ref("base_faults")} b
              ON b.rule_id = r.rule_id
            WHERE r.source_batch_id = %s
              AND b.base_fault_id IS NULL;
            """,
            (source.source_batch_id,),
        )
        checks["rules_without_base_fault"] = int(cur.fetchone()[0])
    return checks


def validation_failures(checks: dict[str, int]) -> dict[str, int]:
    """Return validation failures that should block search document generation."""
    failures: dict[str, int] = {}
    if checks.get("core_rule_count", 0) == 0:
        failures["core_rule_count"] = 0
    for key in ("rules_without_parties", "rules_without_base_fault"):
        if checks.get(key, 0) > 0:
            failures[key] = checks[key]
    return failures


def truncate_search_documents(conn) -> None:
    """Clear active search documents while keeping load history and query logs."""
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE {search_table_ref('rule_search_documents')} CASCADE;")


def insert_search_load(
    conn,
    source: SearchSource,
    mode: str,
    document_strategy: str,
    embedding_model: str | None,
    description: str | None,
) -> int:
    """Record a search-document build event."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {search_table_ref("search_loads")} (
                source_batch_id,
                source_core_load_id,
                load_mode,
                document_strategy,
                embedding_model,
                description
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING search_load_id;
            """,
            (
                source.source_batch_id,
                source.source_core_load_id,
                mode,
                document_strategy,
                embedding_model,
                description,
            ),
        )
        return int(cur.fetchone()[0])


def insert_rule_summary_documents(conn, source: SearchSource, search_load_id: int, embedding_model: str | None) -> None:
    """Create one summary search document per core rule."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            WITH party_summary AS (
                SELECT
                    rule_id,
                    string_agg(
                        concat_ws(' ',
                            party_key,
                            party_label,
                            party_type,
                            movement,
                            road_position,
                            signal_state,
                            entry_timing,
                            violation_type,
                            raw_text
                        ),
                        ' / '
                        ORDER BY party_key
                    ) AS text
                FROM {core_table_ref("rule_parties")}
                GROUP BY rule_id
            ),
            adjustment_summary AS (
                SELECT
                    rule_id,
                    string_agg(
                        concat_ws(' ',
                            target_party_key,
                            factor_name,
                            factor_category,
                            delta,
                            delta_direction,
                            condition_text,
                            explanation_text
                        ),
                        ' / '
                        ORDER BY adjustment_id
                    ) AS text
                FROM {core_table_ref("adjustment_factors")}
                GROUP BY rule_id
            ),
            variant_summary AS (
                SELECT
                    rule_id,
                    string_agg(
                        concat_ws(' ',
                            variant_key,
                            variant_title,
                            scenario_text,
                            party_a_ratio,
                            party_b_ratio,
                            single_party_key,
                            single_party_ratio
                        ),
                        ' / '
                        ORDER BY variant_id
                    ) AS text
                FROM {core_table_ref("variants")}
                GROUP BY rule_id
            ),
            scenario_summary AS (
                SELECT
                    rule_id,
                    string_agg(
                        concat_ws(' ',
                            scenario_key,
                            scenario_title,
                            scenario_text,
                            party_a_ratio,
                            party_b_ratio,
                            single_party_key,
                            single_party_ratio
                        ),
                        ' / '
                        ORDER BY scenario_id
                    ) AS text
                FROM {core_table_ref("rule_scenarios")}
                GROUP BY rule_id
            ),
            context_summary AS (
                SELECT
                    rule_id,
                    string_agg(
                        concat_ws(' ', context_type, road_area, signal_type, raw_text),
                        ' / '
                        ORDER BY context_id
                    ) AS text
                FROM {core_table_ref("contexts")}
                GROUP BY rule_id
            )
            INSERT INTO {search_table_ref("rule_search_documents")} (
                document_id,
                search_load_id,
                source_batch_id,
                rulebook_id,
                rule_id,
                document_type,
                document_scope,
                title,
                search_text,
                metadata,
                embedding_model
            )
            SELECT
                'rule:' || r.rule_id AS document_id,
                %s AS search_load_id,
                r.source_batch_id,
                r.rulebook_id,
                r.rule_id,
                'rule_summary' AS document_type,
                'rule' AS document_scope,
                concat_ws(' ', r.rule_code, r.rule_no, r.rule_title) AS title,
                concat_ws(E'\n',
                    '기준서: ' || coalesce(rb.rulebook_name, r.rulebook_id),
                    '기준: ' || concat_ws(' ', r.rule_code, r.rule_no, r.rule_title),
                    '사고분류: ' || concat_ws(' / ', r.accident_group, r.accident_subgroup),
                    '기본과실: ' || concat_ws(' ', r.normalized_ratio, bf.normalized_ratio, bf.party_a_ratio, bf.party_b_ratio),
                    '당사자: ' || coalesce(ps.text, ''),
                    '수정요소: ' || coalesce(adj.text, ''),
                    '시나리오: ' || coalesce(vs.text, ss.text, ''),
                    '상황정보: ' || coalesce(cs.text, '')
                ) AS search_text,
                jsonb_build_object(
                    'source', 'core.rules',
                    'rulebook_id', r.rulebook_id,
                    'rule_type', r.rule_type,
                    'accident_group', r.accident_group,
                    'accident_subgroup', r.accident_subgroup,
                    'base_fault_type', r.base_fault_type,
                    'calculation_source', r.calculation_source,
                    'scenario_required', r.scenario_required,
                    'variants_required', r.variants_required,
                    'auto_calculation_eligible', r.auto_calculation_eligible
                ) AS metadata,
                %s AS embedding_model
            FROM {core_table_ref("rules")} r
            LEFT JOIN {core_table_ref("rulebooks")} rb ON rb.rulebook_id = r.rulebook_id
            LEFT JOIN {core_table_ref("base_faults")} bf ON bf.rule_id = r.rule_id
            LEFT JOIN party_summary ps ON ps.rule_id = r.rule_id
            LEFT JOIN adjustment_summary adj ON adj.rule_id = r.rule_id
            LEFT JOIN variant_summary vs ON vs.rule_id = r.rule_id
            LEFT JOIN scenario_summary ss ON ss.rule_id = r.rule_id
            LEFT JOIN context_summary cs ON cs.rule_id = r.rule_id
            WHERE r.source_batch_id = %s;
            """,
            (search_load_id, embedding_model, source.source_batch_id),
        )


def insert_evidence_documents(conn, source: SearchSource, search_load_id: int, embedding_model: str | None) -> None:
    """Create search documents from evidence chunks."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {search_table_ref("rule_search_documents")} (
                document_id,
                search_load_id,
                source_batch_id,
                rulebook_id,
                rule_id,
                document_type,
                document_scope,
                title,
                search_text,
                metadata,
                embedding_model
            )
            SELECT
                'chunk:' || c.chunk_id AS document_id,
                %s AS search_load_id,
                c.source_batch_id,
                c.rulebook_id,
                c.rule_id,
                'evidence_chunk' AS document_type,
                c.chunk_type AS document_scope,
                concat_ws(' ', c.rule_title, c.chunk_type) AS title,
                concat_ws(E'\n',
                    '기준: ' || coalesce(c.rule_title, r.rule_title, c.rule_id),
                    '사고분류: ' || concat_ws(' / ', c.accident_group, c.accident_subgroup),
                    '근거문단: ' || c.chunk_text
                ) AS search_text,
                jsonb_build_object(
                    'source', 'core.evidence_chunks',
                    'chunk_id', c.chunk_id,
                    'block_id', c.block_id,
                    'chunk_type', c.chunk_type,
                    'source_reliability', c.source_reliability,
                    'chunk_metadata', c.metadata
                ) AS metadata,
                %s AS embedding_model
            FROM {core_table_ref("evidence_chunks")} c
            LEFT JOIN {core_table_ref("rules")} r ON r.rule_id = c.rule_id
            WHERE c.source_batch_id = %s
              AND c.rule_id IS NOT NULL
              AND NULLIF(c.chunk_text, '') IS NOT NULL;
            """,
            (search_load_id, embedding_model, source.source_batch_id),
        )


def insert_reference_documents(conn, source: SearchSource, search_load_id: int, embedding_model: str | None) -> None:
    """Create supplemental search documents from laws, cases, and usage notes."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {search_table_ref("rule_search_documents")} (
                document_id,
                search_load_id,
                source_batch_id,
                rulebook_id,
                rule_id,
                document_type,
                document_scope,
                title,
                search_text,
                metadata,
                embedding_model
            )
            SELECT
                'law:' || law_ref_id,
                %s,
                source_batch_id,
                rulebook_id,
                rule_id,
                'law_ref',
                law_name,
                concat_ws(' ', law_name, article, clause),
                concat_ws(E'\n', '관련법규: ' || concat_ws(' ', law_name, article, clause), raw_text),
                jsonb_build_object('source', 'core.law_refs', 'law_ref_id', law_ref_id),
                %s
            FROM {core_table_ref("law_refs")}
            WHERE source_batch_id = %s
              AND rule_id IS NOT NULL
              AND NULLIF(raw_text, '') IS NOT NULL
            UNION ALL
            SELECT
                'case:' || case_id,
                %s,
                source_batch_id,
                rulebook_id,
                rule_id,
                'reference_case',
                case_type,
                case_title,
                concat_ws(E'\n', '참고사례: ' || coalesce(case_title, case_id), raw_text, fault_ratio_in_case),
                jsonb_build_object('source', 'core.reference_cases', 'case_id', case_id, 'case_type', case_type),
                %s
            FROM {core_table_ref("reference_cases")}
            WHERE source_batch_id = %s
              AND rule_id IS NOT NULL
              AND NULLIF(raw_text, '') IS NOT NULL
            UNION ALL
            SELECT
                'note:' || usage_note_id,
                %s,
                source_batch_id,
                rulebook_id,
                rule_id,
                'usage_note',
                note_type,
                note_type,
                concat_ws(E'\n', '적용설명: ' || coalesce(note_type, usage_note_id), note_text, raw_text),
                jsonb_build_object('source', 'core.usage_notes', 'usage_note_id', usage_note_id, 'note_type', note_type),
                %s
            FROM {core_table_ref("usage_notes")}
            WHERE source_batch_id = %s
              AND rule_id IS NOT NULL
              AND (NULLIF(note_text, '') IS NOT NULL OR NULLIF(raw_text, '') IS NOT NULL);
            """,
            (
                search_load_id,
                embedding_model,
                source.source_batch_id,
                search_load_id,
                embedding_model,
                source.source_batch_id,
                search_load_id,
                embedding_model,
                source.source_batch_id,
            ),
        )


def search_document_counts(conn) -> dict[str, int]:
    """Return search document counts by document type."""
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT document_type, COUNT(*)
            FROM {search_table_ref("rule_search_documents")}
            GROUP BY document_type
            ORDER BY document_type;
            """
        )
        for document_type, count in cur.fetchall():
            counts[str(document_type)] = int(count)
        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM {search_table_ref("rule_search_documents")}
            WHERE embedding IS NULL;
            """
        )
        counts["missing_embedding"] = int(cur.fetchone()[0])
    return counts


def build_search_documents(
    conn,
    source_batch_id: int | None = None,
    source_core_load_id: int | None = None,
    mode: str = "replace-search",
    document_strategy: str = DEFAULT_DOCUMENT_STRATEGY,
    embedding_model: str | None = None,
    description: str | None = None,
    allow_validation_issues: bool = False,
) -> dict[str, Any]:
    """Build search documents from the selected core dataset."""
    if mode != "replace-search":
        raise ValueError("Only replace-search mode is supported for active search documents.")

    create_search_schema(conn)
    source = resolve_search_source(conn, source_batch_id=source_batch_id, source_core_load_id=source_core_load_id)
    checks = validate_core_source(conn, source)
    failures = validation_failures(checks)
    if failures and not allow_validation_issues:
        raise ValueError(f"search document validation failed: {failures}")

    truncate_search_documents(conn)
    search_load_id = insert_search_load(
        conn,
        source=source,
        mode=mode,
        document_strategy=document_strategy,
        embedding_model=embedding_model,
        description=description,
    )
    insert_rule_summary_documents(conn, source, search_load_id, embedding_model)
    insert_evidence_documents(conn, source, search_load_id, embedding_model)
    insert_reference_documents(conn, source, search_load_id, embedding_model)
    conn.commit()

    return {
        "search_load_id": search_load_id,
        "source_batch_id": source.source_batch_id,
        "source_core_load_id": source.source_core_load_id,
        "source_batch_name": source.source_batch_name,
        "mode": mode,
        "document_strategy": document_strategy,
        "validation": checks,
        "validation_failures": failures,
        "document_counts": search_document_counts(conn),
    }
