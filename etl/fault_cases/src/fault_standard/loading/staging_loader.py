"""Load fault standard preprocessed JSONL outputs into PostgreSQL staging tables.

이 파일의 역할:
- preprocessed 폴더 아래의 모든 JSONL 파일을 찾는다.
- JSONL 파일명을 기준으로 어느 stg_* 테이블에 넣을지 결정한다.
- 각 JSON row에서 공통 컬럼을 뽑고, 나머지는 attributes/raw_json에 보존한다.
- PostgreSQL staging table에 batch 단위로 bulk insert한다.
"""

from __future__ import annotations

# dict/list 값을 JSON 문자열로 바꿀 때 사용한다.
import json
# 적재 건수 집계와 테이블별 pending row 묶음을 관리하기 위해 사용한다.
from collections import Counter, defaultdict
# JSONL source 정보를 가볍게 담는 immutable data class를 만들기 위해 사용한다.
from dataclasses import dataclass
# batch_name 기본값에 timestamp를 넣기 위해 사용한다.
from datetime import datetime
# JSONL 파일 경로를 다루기 위해 사용한다.
from pathlib import Path
# JSON row와 함수 인자 타입 힌트를 위해 사용한다.
from typing import Any, Iterable

# 큰 JSONL 파일도 한 줄씩 읽기 위해 lazy iterator를 사용한다.
from etl.common.utils import read_jsonl_iter

# schema spec과 테이블 생성 함수를 가져온다.
from .staging_schema import TableSpec, create_staging_schema, iter_column_specs, spec_by_source_name, table_ref

# 전처리 결과물 4개 기준서 폴더가 들어 있는 기본 루트다.
DEFAULT_PREPROCESSED_ROOT = Path("etl/fault_cases/artifacts/fault_standard_output/preprocessed")
# PostgreSQL bulk insert를 몇 row 단위로 나눌지 정하는 기본값이다.
DEFAULT_BATCH_SIZE = 500


@dataclass(frozen=True)
class JsonlSource:
    """하나의 JSONL 파일이 어느 rulebook/source_table/spec에 해당하는지 담는다."""

    # 실제 JSONL 파일의 절대/상대 Path 객체다.
    path: Path
    # preprocessed root 기준 상대 경로다. DB에 source_path로 저장된다.
    source_path: str
    # 첫 번째 폴더명이다. 예: 2023_official_auto_accident_rulebook
    rulebook_id: str
    # JSONL 파일명 stem이다. 예: rules, parties, adjustment_factors
    source_table: str
    # source_table을 어느 staging table로 넣을지 정의한 schema spec이다.
    spec: TableSpec


def discover_jsonl_sources(root: Path) -> list[JsonlSource]:
    """Find JSONL sources under the four preprocessed rulebook folders."""
    # 발견한 JSONL source 목록을 담는다.
    sources: list[JsonlSource] = []
    # root 아래 모든 .jsonl 파일을 정렬해서 찾는다. 정렬은 실행 결과를 안정화한다.
    for path in sorted(root.rglob("*.jsonl")):
        # DB에는 root 기준 상대 경로만 저장한다.
        relative = path.relative_to(root)
        # 첫 path segment를 rulebook_id로 사용한다.
        parts = relative.parts
        if not parts:
            continue
        # 예: 2023_official_auto_accident_rulebook
        rulebook_id = parts[0]
        # 예: rules.jsonl -> rules
        source_table = path.stem
        # 파일 하나를 JsonlSource 객체로 정리해서 목록에 추가한다.
        sources.append(
            JsonlSource(
                path=path,
                source_path=relative.as_posix(),
                rulebook_id=rulebook_id,
                source_table=source_table,
                spec=spec_by_source_name(source_table),
            )
        )
    # 전체 JSONL source 목록을 반환한다.
    return sources


def get_first(row: dict[str, Any], keys: Iterable[str]) -> Any:
    """여러 후보 key 중 JSON row에 실제로 존재하는 첫 값을 반환한다."""
    # source별 필드명이 조금씩 다르기 때문에 후보 key를 순서대로 확인한다.
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    # 후보 key가 모두 없거나 None이면 None을 반환한다.
    return None


def coerce_value(value: Any, sql_type: str) -> Any:
    """PostgreSQL column type에 맞게 Python 값을 변환한다."""
    # None은 DB NULL로 들어간다.
    if value is None:
        return None
    # INTEGER 컬럼은 빈 문자열을 NULL로 보고, 그 외에는 int로 변환한다.
    if sql_type.startswith("INTEGER"):
        if value == "":
            return None
        return int(value)
    # DOUBLE PRECISION 컬럼은 빈 문자열을 NULL로 보고, 그 외에는 float로 변환한다.
    if sql_type.startswith("DOUBLE"):
        if value == "":
            return None
        return float(value)
    # BOOLEAN 컬럼은 bool/string 값을 PostgreSQL bool로 들어갈 값으로 정리한다.
    if sql_type.startswith("BOOLEAN"):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "t", "yes", "y"}
        return bool(value)
    # JSONB 컬럼은 dict/list 구조를 유지한다. psycopg2 Json wrapper는 insert 단계에서 감싼다.
    if sql_type.startswith("JSONB"):
        return value if value is not None else {}
    # TEXT 컬럼에 dict/list가 들어오면 한글이 깨지지 않도록 JSON 문자열로 보존한다.
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    # 나머지는 문자열로 저장한다.
    return str(value)


def stable_row_id(source: JsonlSource, row: dict[str, Any], line_no: int) -> str:
    """Create a deterministic fallback row id without hardcoding rule ids."""
    # source별로 자주 쓰는 id 필드 후보를 순서대로 둔다.
    candidate_keys = (
        "rulebook_id",
        "rule_id",
        "party_id",
        "base_fault_id",
        "variant_id",
        "scenario_id",
        "adjustment_id",
        "chunk_id",
        "block_id",
        "law_ref_id",
        "reference_case_id",
        "review_case_id",
        "case_id",
        "usage_note_id",
        "note_id",
        "lane_path_id",
        "lane_step_id",
        "context_id",
        "section_id",
        "summary_row_id",
        "shared_row_id",
    )
    # 후보 id 필드 중 값이 있는 첫 key를 row id로 사용한다.
    for key in candidate_keys:
        value = row.get(key)
        if value:
            return str(value)
    # 어떤 id도 없으면 rulebook/source/rule/line 조합으로 안정적인 fallback id를 만든다.
    rule_id = row.get("rule_id") or "no_rule"
    return f"{source.rulebook_id}:{source.source_table}:{rule_id}:{line_no}"


def staging_row_id(source: JsonlSource, row: dict[str, Any], line_no: int) -> str:
    """Create a staging primary id unique within a table and batch."""
    # source가 매핑된 table spec을 가져온다.
    spec = source.spec
    # rulebooks는 JSON 내부 id보다 실제 폴더명을 rulebook_id로 쓰는 것이 안전하다.
    if spec.table_name == "stg_rulebooks":
        return source.rulebook_id

    # shared_rule_group_* 파일들은 여러 source가 한 테이블에 합쳐지므로 source_table까지 id에 넣는다.
    if spec.table_name == "stg_shared_rule_group_rows":
        # shared group row의 구체 대상 id를 최대한 찾아서 중복을 피한다.
        detail_id = (
            row.get("shared_row_id")
            or row.get("source_block_id")
            or row.get("block_id")
            or row.get("source_chunk_id")
            or row.get("chunk_id")
            or row.get("source_law_ref_id")
            or row.get("law_ref_id")
            or row.get("member_rule_id")
            or row.get("rule_id")
            or line_no
        )
        # shared group 자체 id를 찾고, 없으면 no_group으로 fallback한다.
        group_id = row.get("shared_group_id") or row.get("group_id") or "no_group"
        # source_table + group_id + detail_id 조합으로 같은 batch 안에서 unique하게 만든다.
        return f"{source.source_table}:{group_id}:{detail_id}"

    # table spec에 정의된 id key 후보에서 값을 찾고, 없으면 stable fallback id를 만든다.
    row_id = get_first(row, spec.id_keys) or stable_row_id(source, row, line_no)
    # 여러 JSONL source가 같은 staging table로 합쳐지면 source_table prefix로 충돌을 막는다.
    if len(spec.source_names) > 1:
        return f"{source.source_table}:{row_id}"
    # 단일 source table이면 원래 row id를 그대로 쓴다.
    return str(row_id)


def build_record(source: JsonlSource, row: dict[str, Any], line_no: int) -> dict[str, Any]:
    """Build a staging record for one JSONL row."""
    # 이 row가 들어갈 table spec을 가져온다.
    spec = source.spec
    # 모든 staging table에 공통으로 들어가는 source metadata다.
    record: dict[str, Any] = {
        "rulebook_id": source.rulebook_id,
        "source_table": source.source_table,
        "source_path": source.source_path,
    }

    # table별 primary id 값을 만든다.
    row_id = staging_row_id(source, row, line_no)
    # spec.id_column 이름에 맞춰 record에 id를 넣는다.
    record[spec.id_column] = str(row_id)

    # 컬럼으로 이미 뽑은 JSON key를 attributes에서 제외하기 위해 기록한다.
    extracted_keys: set[str] = {"rulebook_id"}
    # table spec에 정의된 컬럼들을 순회하며 row에서 값을 추출한다.
    for column in iter_column_specs(spec):
        # batch/source/raw_json 같은 시스템 컬럼은 여기서 추출하지 않는다.
        if column.name in {"batch_id", "rulebook_id", "source_table", "source_path", spec.id_column, "attributes", "raw_json", "created_at"}:
            continue
        # 컬럼에 연결된 후보 key 중 첫 값을 가져온다.
        value = get_first(row, column.keys)
        # 추출한 값을 record에 저장한다.
        record[column.name] = value
        # 후보 key들은 attributes 중복 저장 대상에서 제외한다.
        extracted_keys.update(column.keys)

    # context 계열 파일은 여러 source가 한 테이블에 들어가므로 source_table을 context_type으로 보강한다.
    if spec.table_name == "stg_contexts" and not record.get("context_type"):
        record["context_type"] = source.source_table
    # misc table은 row_key로 fallback id를 보존한다.
    if spec.table_name == "stg_misc_jsonl_rows":
        record["row_key"] = row_id

    # 명시 컬럼으로 빠지지 않은 나머지 원본 필드는 attributes에 보관한다.
    attributes = {key: value for key, value in row.items() if key not in extracted_keys}
    # attributes는 검색/검수용 보조 JSONB다.
    record["attributes"] = attributes
    # raw_json은 원본 row 전체를 그대로 보존하는 감사용 JSONB다.
    record["raw_json"] = row
    # insert_records에서 DB row로 변환할 record를 반환한다.
    return record


def insert_records(conn, spec: TableSpec, records: list[dict[str, Any]], batch_id: int, page_size: int) -> None:
    """같은 staging table로 들어갈 record 묶음을 bulk insert한다."""
    # Json은 dict/list를 PostgreSQL JSONB로 넣기 위한 psycopg2 helper다.
    from psycopg2.extras import Json, execute_values

    # 넣을 record가 없으면 아무 작업도 하지 않는다.
    if not records:
        return

    # created_at은 DB default now()를 쓰므로 insert column 목록에서 제외한다.
    columns = [column.name for column in iter_column_specs(spec) if column.name != "created_at"]
    # execute_values에 넘길 tuple row 목록이다.
    rows = []
    # 컬럼별 SQL type을 빠르게 찾기 위한 dict다.
    column_types = {column.name: column.sql_type for column in iter_column_specs(spec)}
    # record dict를 DB insert tuple로 변환한다.
    for record in records:
        values = []
        # 모든 staging row는 현재 batch_id에 연결된다.
        record["batch_id"] = batch_id
        # insert column 순서대로 값을 채운다.
        for column in columns:
            if column_types[column].startswith("JSONB"):
                # JSONB 컬럼은 psycopg2 Json wrapper로 감싼다.
                values.append(Json(record.get(column) or {}))
            else:
                # 나머지 컬럼은 SQL type에 맞춰 변환한다.
                values.append(coerce_value(record.get(column), column_types[column]))
        # 한 record의 values tuple을 rows에 추가한다.
        rows.append(tuple(values))

    # conflict 시 갱신할 컬럼 목록이다. PK 구성 컬럼은 갱신하지 않는다.
    update_columns = [column for column in columns if column not in {"batch_id", spec.id_column}]
    # ON CONFLICT DO UPDATE SET 절을 만든다.
    assignments = ", ".join(f"{column} = EXCLUDED.{column}" for column in update_columns)
    # batch_id + id_column이 같으면 같은 row로 보고 upsert한다.
    query = f"""
        INSERT INTO {table_ref(spec.table_name)} ({", ".join(columns)})
        VALUES %s
        ON CONFLICT (batch_id, {spec.id_column}) DO UPDATE SET
            {assignments}
    """
    # DB cursor를 열고 execute_values로 bulk insert한다.
    with conn.cursor() as cur:
        execute_values(cur, query, rows, page_size=page_size)


def create_batch(
    conn,
    batch_name: str,
    source_root_path: str,
    preprocess_version: str | None,
    description: str | None,
    replace_batch: bool,
) -> int:
    """preprocess_batches row를 만들고 batch_id를 반환한다."""
    # batch metadata를 저장하기 위해 cursor를 연다.
    with conn.cursor() as cur:
        # replace-batch 모드에서는 같은 batch_name의 기존 row를 먼저 지운다.
        if replace_batch:
            cur.execute(f"DELETE FROM {table_ref('preprocess_batches')} WHERE batch_name = %s;", (batch_name,))
        # batch row를 만들거나, 같은 이름이 있으면 metadata를 갱신한다.
        cur.execute(
            f"""
            INSERT INTO {table_ref("preprocess_batches")} (batch_name, source_root_path, preprocess_version, description)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (batch_name) DO UPDATE SET
                source_root_path = EXCLUDED.source_root_path,
                preprocess_version = EXCLUDED.preprocess_version,
                description = EXCLUDED.description
            RETURNING batch_id;
            """,
            (batch_name, source_root_path, preprocess_version, description),
        )
        # INSERT/UPDATE된 batch_id를 int로 반환한다.
        return int(cur.fetchone()[0])


def load_staging(
    conn,
    source_root: Path = DEFAULT_PREPROCESSED_ROOT,
    batch_name: str | None = None,
    preprocess_version: str | None = None,
    description: str | None = None,
    replace_batch: bool = True,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, Any]:
    """Create staging schema and load all discovered JSONL rows."""
    # source_root를 절대 경로로 고정해서 batch metadata에 명확히 남긴다.
    source_root = source_root.resolve()
    # 전처리 산출물 폴더가 없으면 적재를 중단한다.
    if not source_root.exists():
        raise FileNotFoundError(f"Preprocessed root not found: {source_root}")

    # staging table들이 없으면 생성한다.
    create_staging_schema(conn)
    # batch_name이 없으면 현재 시각 기반 이름을 만든다.
    if not batch_name:
        batch_name = f"fault_standard_preprocessed_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # preprocess_batches에 batch metadata를 저장한다.
    batch_id = create_batch(
        conn=conn,
        batch_name=batch_name,
        source_root_path=str(source_root),
        preprocess_version=preprocess_version,
        description=description,
        replace_batch=replace_batch,
    )

    # preprocessed 루트에서 모든 JSONL source를 찾는다.
    sources = discover_jsonl_sources(source_root)
    # rulebook/source_table별 읽은 row 수를 집계한다.
    file_counts: Counter[tuple[str, str]] = Counter()
    # staging table별 적재 예정 row 수를 집계한다.
    table_counts: Counter[str] = Counter()
    # table별로 아직 DB에 flush하지 않은 record를 모아둔다.
    pending: dict[str, list[dict[str, Any]]] = defaultdict(list)
    # 마지막 flush 때 table_name으로 spec을 찾기 위한 dict다.
    specs_by_table = {source.spec.table_name: source.spec for source in sources}

    # JSONL 파일을 하나씩 순회한다.
    for source in sources:
        # JSONL 파일을 한 줄씩 읽어서 메모리 사용량을 낮춘다.
        for line_no, row in enumerate(read_jsonl_iter(source.path), start=1):
            # 원본 JSON row를 staging record로 변환한다.
            record = build_record(source, row, line_no)
            # 같은 staging table에 들어갈 record를 pending에 모은다.
            pending[source.spec.table_name].append(record)
            # 파일별 row 수를 집계한다.
            file_counts[(source.rulebook_id, source.source_table)] += 1
            # 테이블별 row 수를 집계한다.
            table_counts[source.spec.table_name] += 1

            # pending record가 batch_size 이상 쌓이면 DB에 bulk insert한다.
            if len(pending[source.spec.table_name]) >= batch_size:
                insert_records(conn, source.spec, pending[source.spec.table_name], batch_id, batch_size)
                # insert가 끝난 pending list는 비운다.
                pending[source.spec.table_name].clear()

    # 파일 순회를 마친 뒤 table별로 남은 pending record를 모두 insert한다.
    for table_name, records in pending.items():
        insert_records(conn, specs_by_table[table_name], records, batch_id, batch_size)

    # 모든 insert가 성공했으므로 transaction을 commit한다.
    conn.commit()
    # 실제 DB에 들어간 row 수를 다시 조회해 검증용 summary를 만든다.
    db_counts = count_loaded_rows(conn, batch_id, table_counts.keys())
    # CLI에서 출력할 적재 결과 dict를 반환한다.
    return {
        "batch_id": batch_id,
        "batch_name": batch_name,
        "source_root": str(source_root),
        "file_count": len(sources),
        "file_counts": file_counts,
        "table_counts": table_counts,
        "db_counts": db_counts,
    }


def count_loaded_rows(conn, batch_id: int, table_names: Iterable[str]) -> dict[str, int]:
    """batch_id 기준으로 staging table별 실제 적재 row 수를 조회한다."""
    # 결과를 table_name -> count 형태로 담는다.
    counts: dict[str, int] = {}
    # count 쿼리를 실행하기 위해 cursor를 연다.
    with conn.cursor() as cur:
        # 중복 table_name을 제거하고 정렬해서 결과 순서를 안정화한다.
        for table_name in sorted(set(table_names)):
            # 해당 batch_id로 들어간 row 수를 센다.
            cur.execute(f"SELECT COUNT(*) FROM {table_ref(table_name)} WHERE batch_id = %s;", (batch_id,))
            # fetch 결과를 int로 변환해 저장한다.
            counts[table_name] = int(cur.fetchone()[0])
    # 테이블별 count dict를 반환한다.
    return counts
