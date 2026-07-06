"""DDL definitions for fault standard PostgreSQL staging tables.

이 파일의 역할:
- JSONL 파일명을 어떤 PostgreSQL staging table에 넣을지 정의한다.
- 각 staging table의 컬럼명, SQL 타입, 원본 JSON key 후보를 정의한다.
- 정의된 스펙을 바탕으로 CREATE TABLE / INDEX DDL을 생성한다.
"""

from __future__ import annotations

# 테이블/컬럼 정의를 immutable spec 객체로 표현하기 위해 사용한다.
from dataclasses import dataclass
# column spec iterator의 반환 타입 힌트에 사용한다.
from typing import Iterable

# PostgreSQL에서 staging 테이블을 몰아넣을 schema 이름이다.
STAGING_SCHEMA = "staging"


@dataclass(frozen=True)
class ColumnSpec:
    """staging table 컬럼 하나의 정의."""

    # PostgreSQL에 생성될 컬럼명이다.
    name: str
    # PostgreSQL 컬럼 타입이다. 예: TEXT, INTEGER, JSONB
    sql_type: str
    # 원본 JSON row에서 이 컬럼 값을 찾을 후보 key 목록이다.
    keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class TableSpec:
    """JSONL source와 staging table 사이의 매핑 정의."""

    # 이 table spec으로 처리할 JSONL 파일명 stem 목록이다.
    source_names: tuple[str, ...]
    # 실제 PostgreSQL staging table 이름이다.
    table_name: str
    # batch_id와 함께 primary key를 구성할 id 컬럼명이다.
    id_column: str
    # 원본 JSON row에서 id 값을 찾을 후보 key 목록이다.
    id_keys: tuple[str, ...]
    # table별 고유 컬럼 목록이다. 공통 컬럼은 COMMON_PREFIX/SUFFIX에서 붙는다.
    columns: tuple[ColumnSpec, ...]


# 모든 staging table 앞쪽에 공통으로 붙는 source 추적 컬럼이다.
COMMON_PREFIX = (
    # 어떤 적재 batch에서 들어온 row인지 식별한다.
    ColumnSpec("batch_id", "BIGINT NOT NULL"),
    # 어느 기준서 폴더에서 온 row인지 식별한다.
    ColumnSpec("rulebook_id", "TEXT NOT NULL"),
    # 어떤 JSONL 파일명에서 온 row인지 식별한다.
    ColumnSpec("source_table", "TEXT NOT NULL"),
    # preprocessed root 기준 상대 경로다.
    ColumnSpec("source_path", "TEXT NOT NULL"),
)

# 모든 staging table 뒤쪽에 공통으로 붙는 원본 보존 컬럼이다.
COMMON_SUFFIX = (
    # 명시 컬럼으로 뽑지 않은 나머지 필드를 JSONB로 저장한다.
    ColumnSpec("attributes", "JSONB NOT NULL DEFAULT '{}'::jsonb"),
    # 원본 JSON row 전체를 감사/재처리용으로 그대로 저장한다.
    ColumnSpec("raw_json", "JSONB NOT NULL"),
    # DB row 생성 시각이다.
    ColumnSpec("created_at", "TIMESTAMP DEFAULT now()"),
)


def col(name: str, sql_type: str, *keys: str) -> ColumnSpec:
    """컬럼 정의를 짧게 쓰기 위한 helper."""
    # keys가 있으면 후보 key로 쓰고, 없으면 컬럼명 자체를 JSON key 후보로 쓴다.
    return ColumnSpec(name, sql_type, keys or (name,))


def table_ref(table_name: str) -> str:
    """staging schema가 붙은 PostgreSQL table reference를 만든다."""
    # table_name은 코드에 정의된 상수만 사용하므로 schema prefix만 붙인다.
    return f"{STAGING_SCHEMA}.{table_name}"


# JSONL 파일명별 staging table 매핑 목록이다.
TABLE_SPECS: tuple[TableSpec, ...] = (
    TableSpec(
        # rulebooks.jsonl은 기준서 metadata를 담는다.
        ("rulebooks",),
        "stg_rulebooks",
        "rulebook_id",
        ("rulebook_id", "document_type", "source_subtype"),
        (
            col("rulebook_name", "TEXT", "rulebook_name", "title", "document_title"),
            col("source_type", "TEXT"),
            col("source_subtype", "TEXT"),
            col("source_file", "TEXT"),
            col("published_year", "INTEGER"),
            col("source_reliability", "TEXT"),
        ),
    ),
    TableSpec(
        # rules.jsonl은 기준 rule의 대표 정보를 담는다.
        ("rules",),
        "stg_rules",
        "rule_id",
        ("rule_id",),
        (
            col("rule_id", "TEXT NOT NULL"),
            col("rule_code", "TEXT"),
            col("rule_no", "TEXT", "rule_no", "rule_number"),
            col("rule_title", "TEXT"),
            col("rule_type", "TEXT"),
            col("accident_group", "TEXT"),
            col("accident_subgroup", "TEXT"),
            col("normalized_ratio", "TEXT"),
            col("party_a_ratio", "INTEGER"),
            col("party_b_ratio", "INTEGER"),
            col("base_fault_type", "TEXT"),
            col("calculation_source", "TEXT"),
            col("scenario_required", "BOOLEAN"),
            col("variants_required", "BOOLEAN"),
            col("auto_calculation_eligible", "BOOLEAN"),
            col("page_start", "INTEGER"),
            col("page_end", "INTEGER"),
            col("parse_status", "TEXT"),
        ),
    ),
    TableSpec(
        # parties.jsonl은 rule별 A/B/보/차 당사자 정보를 담는다.
        ("parties",),
        "stg_rule_parties",
        "party_id",
        ("party_id",),
        (
            col("party_id", "TEXT NOT NULL"),
            col("rule_id", "TEXT NOT NULL"),
            col("party_key", "TEXT NOT NULL"),
            col("party_label", "TEXT"),
            col("party_type", "TEXT"),
            col("movement", "TEXT"),
            col("road_position", "TEXT"),
            col("signal_state", "TEXT"),
            col("entry_timing", "TEXT"),
            col("violation_type", "TEXT"),
            col("raw_text", "TEXT"),
        ),
    ),
    TableSpec(
        # base_faults.jsonl은 rule별 기본과실 정보를 담는다.
        ("base_faults",),
        "stg_base_faults",
        "base_fault_id",
        ("base_fault_id",),
        (
            col("base_fault_id", "TEXT NOT NULL"),
            col("rule_id", "TEXT NOT NULL"),
            col("base_fault_type", "TEXT"),
            col("calculation_source", "TEXT"),
            col("party_a_ratio", "INTEGER"),
            col("party_b_ratio", "INTEGER"),
            col("normalized_ratio", "TEXT"),
            col("scenario_required", "BOOLEAN"),
            col("variants_required", "BOOLEAN"),
            col("auto_calculation_eligible", "BOOLEAN"),
            col("is_one_sided_fault", "BOOLEAN"),
            col("is_equal_fault", "BOOLEAN"),
            col("raw_text", "TEXT"),
            col("quality_flags", "JSONB"),
        ),
    ),
    TableSpec(
        # variants.jsonl은 (가)/(나)/(다) 같은 세부 시나리오 비율을 담는다.
        ("variants",),
        "stg_variants",
        "variant_id",
        ("variant_id",),
        (
            col("variant_id", "TEXT NOT NULL"),
            col("rule_id", "TEXT NOT NULL"),
            col("variant_key", "TEXT"),
            col("variant_title", "TEXT"),
            col("scenario_text", "TEXT"),
            col("party_a_ratio", "INTEGER"),
            col("party_b_ratio", "INTEGER"),
            col("single_party_key", "TEXT"),
            col("single_party_ratio", "INTEGER"),
            col("single_party_type", "TEXT"),
            col("ratio_interpretation", "TEXT"),
            col("needs_review", "BOOLEAN"),
            col("raw_text", "TEXT"),
        ),
    ),
    TableSpec(
        # rule_scenarios.jsonl은 PM 등 일부 기준의 시나리오 구조를 담는다.
        ("rule_scenarios",),
        "stg_rule_scenarios",
        "scenario_id",
        ("scenario_id", "variant_id"),
        (
            col("scenario_id", "TEXT NOT NULL", "scenario_id", "variant_id"),
            col("rule_id", "TEXT NOT NULL"),
            col("scenario_key", "TEXT", "scenario_key", "variant_key"),
            col("scenario_title", "TEXT", "scenario_title", "variant_title"),
            col("scenario_text", "TEXT"),
            col("party_a_ratio", "INTEGER"),
            col("party_b_ratio", "INTEGER"),
            col("single_party_key", "TEXT"),
            col("single_party_ratio", "INTEGER"),
            col("single_party_type", "TEXT"),
            col("raw_text", "TEXT"),
        ),
    ),
    TableSpec(
        # adjustment_factors.jsonl은 가산/감산 수정요소를 담는다.
        ("adjustment_factors",),
        "stg_adjustment_factors",
        "adjustment_id",
        ("adjustment_id",),
        (
            col("adjustment_id", "TEXT NOT NULL"),
            col("rule_id", "TEXT NOT NULL"),
            col("target_party_key", "TEXT"),
            col("target_party_type", "TEXT"),
            col("factor_name", "TEXT"),
            col("factor_category", "TEXT"),
            col("delta", "INTEGER"),
            col("delta_direction", "TEXT"),
            col("raw_delta", "TEXT"),
            col("condition_text", "TEXT"),
            col("explanation_text", "TEXT"),
            col("raw_text", "TEXT"),
            col("is_applicable", "BOOLEAN"),
            col("auto_calculation_eligible", "BOOLEAN"),
            col("exclude_from_auto_calculation", "BOOLEAN"),
        ),
    ),
    TableSpec(
        # chunks.jsonl은 검색과 근거 제시에 사용할 문단 chunk를 담는다.
        ("chunks",),
        "stg_evidence_chunks",
        "chunk_id",
        ("chunk_id",),
        (
            col("chunk_id", "TEXT NOT NULL"),
            col("rule_id", "TEXT"),
            col("block_id", "TEXT"),
            col("chunk_type", "TEXT"),
            col("chunk_text", "TEXT", "chunk_text", "text"),
            col("rule_title", "TEXT"),
            col("accident_group", "TEXT"),
            col("accident_subgroup", "TEXT"),
            col("accident_tags", "JSONB"),
            col("source_reliability", "TEXT"),
            col("metadata", "JSONB"),
        ),
    ),
    TableSpec(
        # law_refs.jsonl은 rule에 연결된 법규 참조를 담는다.
        ("law_refs",),
        "stg_law_refs",
        "law_ref_id",
        ("law_ref_id", "ref_id"),
        (
            col("law_ref_id", "TEXT NOT NULL", "law_ref_id", "ref_id"),
            col("rule_id", "TEXT"),
            col("law_name", "TEXT"),
            col("article", "TEXT", "article", "article_no"),
            col("clause", "TEXT"),
            col("raw_text", "TEXT"),
        ),
    ),
    TableSpec(
        # reference_cases/review_cases는 판례/심의사례 계열 근거를 한 테이블에 모은다.
        ("reference_cases", "review_cases"),
        "stg_reference_cases",
        "case_id",
        ("case_id", "reference_case_id", "review_case_id"),
        (
            col("case_id", "TEXT NOT NULL", "case_id", "reference_case_id", "review_case_id"),
            col("rule_id", "TEXT"),
            col("case_type", "TEXT"),
            col("case_title", "TEXT", "case_title", "title"),
            col("claim_ratio", "INTEGER"),
            col("respondent_ratio", "INTEGER"),
            col("fault_ratio_in_case", "TEXT"),
            col("raw_text", "TEXT"),
        ),
    ),
    TableSpec(
        # usage_notes.jsonl은 기준 적용 설명/주의 문구를 담는다.
        ("usage_notes",),
        "stg_usage_notes",
        "usage_note_id",
        ("usage_note_id", "note_id"),
        (
            col("usage_note_id", "TEXT NOT NULL", "usage_note_id", "note_id"),
            col("rule_id", "TEXT"),
            col("note_type", "TEXT"),
            col("note_text", "TEXT", "note_text", "text"),
            col("raw_text", "TEXT"),
        ),
    ),
    TableSpec(
        # rule_blocks.jsonl은 rule 내부의 원문 block 단위를 담는다.
        ("rule_blocks",),
        "stg_rule_blocks",
        "block_id",
        ("block_id",),
        (
            col("block_id", "TEXT NOT NULL"),
            col("rule_id", "TEXT"),
            col("block_type", "TEXT"),
            col("block_title", "TEXT"),
            col("block_text", "TEXT", "block_text", "text"),
            col("page_start", "INTEGER"),
            col("page_end", "INTEGER"),
        ),
    ),
    TableSpec(
        # lane_paths.jsonl은 회전교차로 같은 차로 경로 요약을 담는다.
        ("lane_paths",),
        "stg_lane_paths",
        "lane_path_id",
        ("lane_path_id",),
        (
            col("lane_path_id", "TEXT NOT NULL"),
            col("rule_id", "TEXT"),
            col("party_key", "TEXT"),
            col("entry_direction", "TEXT"),
            col("exit_direction", "TEXT"),
            col("entry_lane", "TEXT"),
            col("circulation_lane", "TEXT"),
            col("exit_lane", "TEXT"),
            col("is_lane_changing", "BOOLEAN"),
            col("is_exiting", "BOOLEAN"),
            col("raw_text", "TEXT"),
        ),
    ),
    TableSpec(
        # lane_steps.jsonl은 회전교차로 경로를 단계별로 쪼갠 정보를 담는다.
        ("lane_steps",),
        "stg_lane_steps",
        "lane_step_id",
        ("lane_step_id",),
        (
            col("lane_step_id", "TEXT NOT NULL"),
            col("rule_id", "TEXT"),
            col("party_key", "TEXT"),
            col("seq", "INTEGER"),
            col("movement", "TEXT"),
            col("lane", "TEXT"),
            col("direction", "TEXT"),
            col("source", "TEXT"),
            col("source_text", "TEXT"),
            col("confidence", "DOUBLE PRECISION"),
        ),
    ),
    TableSpec(
        # 여러 context JSONL은 같은 형태로 검수하기 위해 stg_contexts에 모은다.
        ("road_contexts", "pm_contexts", "vehicle_contexts", "signal_contexts", "roundabout_contexts", "priority_contexts", "adjustment_condition_contexts"),
        "stg_contexts",
        "context_id",
        ("context_id", "road_context_id", "pm_context_id", "vehicle_context_id", "signal_context_id", "roundabout_context_id", "priority_context_id", "adjustment_condition_context_id"),
        (
            col("context_id", "TEXT NOT NULL", "context_id", "road_context_id", "pm_context_id", "vehicle_context_id", "signal_context_id", "roundabout_context_id", "priority_context_id", "adjustment_condition_context_id"),
            col("rule_id", "TEXT"),
            col("context_type", "TEXT"),
            col("road_area", "TEXT"),
            col("signal_type", "TEXT"),
            col("raw_text", "TEXT"),
        ),
    ),
    TableSpec(
        # parse_quality_report.jsonl은 전처리 품질 플래그를 담는다.
        ("parse_quality_report",),
        "stg_parse_quality_report",
        "quality_report_id",
        ("quality_report_id", "report_id"),
        (
            col("quality_report_id", "TEXT NOT NULL", "quality_report_id", "report_id"),
            col("rule_id", "TEXT"),
            col("parse_status", "TEXT"),
            col("quality_flags", "JSONB"),
            col("needs_review", "BOOLEAN"),
            col("review_reason", "TEXT"),
        ),
    ),
    TableSpec(
        # sections.jsonl은 문서 장/절 또는 section path 정보를 담는다.
        ("sections",),
        "stg_sections",
        "section_id",
        ("section_id",),
        (
            col("section_id", "TEXT NOT NULL"),
            col("rule_id", "TEXT"),
            col("section_title", "TEXT", "section_title", "title"),
            col("section_path", "JSONB"),
            col("page_start", "INTEGER"),
            col("page_end", "INTEGER"),
        ),
    ),
    TableSpec(
        # summary_table_rows.jsonl은 비정형 기준의 요약표 row를 담는다.
        ("summary_table_rows",),
        "stg_summary_table_rows",
        "summary_row_id",
        ("summary_row_id", "row_id"),
        (
            col("summary_row_id", "TEXT NOT NULL", "summary_row_id", "row_id"),
            col("rule_id", "TEXT"),
            col("summary_no", "TEXT", "summary_no", "no"),
            col("summary_title", "TEXT"),
            col("raw_text", "TEXT"),
        ),
    ),
    TableSpec(
        # shared_rule_group_* 파일들은 공통 해설/법규 그룹 정보를 한 테이블에 모은다.
        ("shared_rule_groups", "shared_rule_group_members", "shared_rule_group_blocks", "shared_rule_group_chunks", "shared_rule_group_law_refs"),
        "stg_shared_rule_group_rows",
        "shared_row_id",
        ("shared_row_id", "shared_group_id", "group_id", "member_id", "block_id", "chunk_id", "law_ref_id"),
        (
            col("shared_row_id", "TEXT NOT NULL", "shared_row_id", "shared_group_id", "group_id", "member_id", "block_id", "chunk_id", "law_ref_id"),
            col("shared_group_id", "TEXT", "shared_group_id", "group_id"),
            col("rule_id", "TEXT"),
            col("member_rule_id", "TEXT"),
            col("block_id", "TEXT"),
            col("chunk_id", "TEXT"),
            col("law_ref_id", "TEXT"),
            col("text", "TEXT"),
            col("metadata", "JSONB"),
        ),
    ),
)

# 위 목록에 없는 JSONL이 발견되면 원본 보존용 misc table로 들어간다.
MISC_TABLE_SPEC = TableSpec(
    tuple(),
    "stg_misc_jsonl_rows",
    "misc_row_id",
    ("misc_row_id",),
    (
        col("misc_row_id", "TEXT NOT NULL", "misc_row_id"),
        col("rule_id", "TEXT"),
        col("row_key", "TEXT"),
    ),
)


def all_table_specs() -> tuple[TableSpec, ...]:
    """명시 table spec 전체와 misc fallback spec을 함께 반환한다."""
    return TABLE_SPECS + (MISC_TABLE_SPEC,)


def spec_by_source_name(source_name: str) -> TableSpec:
    """JSONL 파일명 stem으로 사용할 TableSpec을 찾는다."""
    # 등록된 table spec 중 source_names에 source_name이 있는지 확인한다.
    for spec in TABLE_SPECS:
        if source_name in spec.source_names:
            return spec
    # 등록되지 않은 JSONL은 misc table로 보존한다.
    return MISC_TABLE_SPEC


def iter_column_specs(spec: TableSpec) -> Iterable[ColumnSpec]:
    """공통 컬럼 + id 컬럼 + table별 컬럼 + 공통 suffix 컬럼을 중복 없이 순회한다."""
    # 같은 컬럼명이 여러 번 정의될 수 있으므로 이미 yield한 이름을 기록한다.
    yielded = set()
    # 모든 table은 prefix, id column, spec columns, suffix 순서로 컬럼을 가진다.
    for column in (*COMMON_PREFIX, ColumnSpec(spec.id_column, "TEXT NOT NULL"), *spec.columns, *COMMON_SUFFIX):
        # 같은 이름의 컬럼은 최초 정의만 사용한다.
        if column.name in yielded:
            continue
        # 중복 방지를 위해 컬럼명을 기록한다.
        yielded.add(column.name)
        # 호출자에게 컬럼 정의를 하나씩 넘긴다.
        yield column


def create_staging_schema(conn) -> None:
    """Create fault standard staging tables and indexes."""
    # DDL 실행을 위해 cursor를 연다.
    with conn.cursor() as cur:
        # public에 stg_*가 길게 섞이지 않도록 staging schema를 먼저 만든다.
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {STAGING_SCHEMA};")

        # batch metadata table을 먼저 만든다. 모든 stg_* table이 이 batch_id를 참조한다.
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_ref("preprocess_batches")} (
                batch_id BIGSERIAL PRIMARY KEY,
                batch_name TEXT NOT NULL UNIQUE,
                source_root_path TEXT,
                preprocess_version TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT now()
            );
            """
        )

        # 정의된 모든 staging table spec을 순회하며 CREATE TABLE을 만든다.
        for spec in all_table_specs():
            # CREATE TABLE에 들어갈 컬럼 SQL 조각을 담는다.
            column_sql = []
            # index 생성 여부 확인을 위해 컬럼명 set을 만든다.
            column_names = set()
            # spec에서 최종 컬럼 목록을 얻는다.
            for column in iter_column_specs(spec):
                # 컬럼명과 SQL 타입을 DDL 조각으로 만든다.
                column_sql.append(f"{column.name} {column.sql_type}")
                # 뒤에서 rule_id/rulebook_id/source_table index 여부를 판단하기 위해 저장한다.
                column_names.add(column.name)
            # batch_id + id_column 조합을 staging table의 primary key로 사용한다.
            column_sql.append(f"PRIMARY KEY (batch_id, {spec.id_column})")
            # batch 삭제 시 해당 batch의 staging row도 같이 삭제되도록 cascade FK를 건다.
            column_sql.append(f"FOREIGN KEY (batch_id) REFERENCES {table_ref('preprocess_batches')}(batch_id) ON DELETE CASCADE")
            # table이 없을 때만 생성한다. 기존 table은 유지된다.
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table_ref(spec.table_name)} (
                    {", ".join(column_sql)}
                );
                """
            )
            # rule_id 검색/검증이 많으므로 rule_id 컬럼이 있으면 index를 만든다.
            if "rule_id" in column_names:
                cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{spec.table_name}_rule_id ON {table_ref(spec.table_name)} (rule_id);")
            # rulebook별 조회를 위해 rulebook_id index를 만든다.
            if "rulebook_id" in column_names:
                cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{spec.table_name}_rulebook_id ON {table_ref(spec.table_name)} (rulebook_id);")
            # 같은 staging table에 여러 source JSONL이 합쳐질 수 있어 source_table index를 만든다.
            if "source_table" in column_names:
                cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{spec.table_name}_source_table ON {table_ref(spec.table_name)} (source_table);")

    # DDL 작업을 commit한다.
    conn.commit()
