"""검증된 Qwen 4B 결과를 세 PostgreSQL DB의 staging에 적재·승격한다.

기존 `rag_qwen4`에는 append하지 않는다. 코퍼스별 새 staging 스키마를 만든 뒤 문서·청크와
벡터 연결을 검증하고, 세 DB가 모두 통과한 경우에만 활성 스키마를 교체한다.
"""

from __future__ import annotations

import argparse  # staging·승격 하위 명령과 DB 연결 인자를 정의한다.
import json  # 수신 검증·artifact·metadata manifest를 읽고 적재 보고서를 쓴다.
import math  # 벡터 차원·NaN·Inf·L2 norm을 적재 직전에 다시 검사한다.
import os  # DB 비밀번호를 환경변수에서만 읽는다.
import re  # 동적 PostgreSQL schema 이름을 안전한 문자로 제한한다.
import sys  # 비밀 없는 오류 메시지와 종료 코드를 반환한다.
from dataclasses import dataclass  # 코퍼스 DB·검색 단위 계약을 불변 구조로 묶는다.
from datetime import datetime, timezone  # 적재·승격 시각을 UTC로 기록한다.
from pathlib import Path  # 결과·마이그레이션·보고서 경로를 안전하게 조합한다.
from typing import Any, Iterator, Sequence  # 함수 입출력 계약을 명시한다.

import psycopg  # 세 운영 PostgreSQL DB의 staging 트랜잭션을 실행한다.
from psycopg import sql  # schema·table 식별자를 문자열 삽입 없이 안전하게 조합한다.

from .config import (  # 입력 빌더·RunPod 실행기와 동일한 승인 계약을 사용한다.
    EXPECTED_COUNTS,
    FAULT_CASES_ROOT,
    MODEL_DIMENSION,
    MODEL_NAME,
    MODEL_REVISION,
    NORMALIZATION,
)
from .run_qwen4_three_corpora import CORPUS_OUTPUT_NAMES, read_json, sha256_file, utc_now


# 현재 단계 5에서 생성한 운영 스키마 정의를 staging에도 동일하게 적용한다.
MIGRATION_PATH = FAULT_CASES_ROOT / "rag_runtime" / "database" / "migrations" / "001_rag_qwen4.sql"


@dataclass(frozen=True)
class CorpusDatabase:
    """한 코퍼스의 DB·검색 단위·기본 적재 예상 건수를 정의한다."""

    key: str
    database: str
    target_type: str
    document_count: int
    chunk_count: int
    embedding_count: int


# 법률 DB는 목록에 넣지 않아 이 도구가 실수로 법률 데이터를 변경할 수 없게 한다.
CORPUS_DATABASES = (
    CorpusDatabase("fault_standard", "fault_standard_db", "document", 277, 0, 277),
    CorpusDatabase("review_case", "review_case_db", "chunk", 226, 904, 904),
    CorpusDatabase("precedent", "precedent_db", "chunk", 987, 8334, 8334),
)


def load_env_file(path: Path) -> None:
    """루트 `.env`의 단순 KEY=VALUE를 현재 프로세스에만 안전하게 설정한다."""

    # 파일이 없으면 기존 환경변수를 사용할 수 있으므로 조용히 반환한다.
    if not path.is_file():
        return
    # 비밀번호 값을 출력하지 않고 UTF-8 한 줄씩만 해석한다.
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        # 주석·빈 줄·등호 없는 줄은 환경변수로 처리하지 않는다.
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        # 사용자가 이미 지정한 환경변수는 `.env` 값으로 덮어쓰지 않는다.
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def password_from_env(name: str) -> str:
    """필수 DB 비밀번호를 지정 환경변수에서 읽되 값을 출력하지 않는다."""

    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"필수 DB 비밀번호 환경변수가 없습니다: {name}")
    return value


def connect(args: argparse.Namespace, database: str) -> psycopg.Connection[Any]:
    """허용된 코퍼스 DB에만 psycopg 연결을 생성한다."""

    # 법률 DB나 임의 DB 이름이 호출 경로에 들어오면 연결 자체를 거부한다.
    allowed = {item.database for item in CORPUS_DATABASES}
    if database not in allowed:
        raise ValueError(f"허용되지 않은 데이터베이스입니다: {database}")
    return psycopg.connect(
        host=args.host,
        port=args.port,
        user=args.user,
        password=password_from_env(args.password_env),
        dbname=database,
        connect_timeout=15,
    )


def safe_schema_name(value: str) -> str:
    """PostgreSQL staging·backup schema 이름을 영문 소문자·숫자·밑줄로 제한한다."""

    # PostgreSQL 식별자 길이 63자를 넘거나 허용 문자 외 값이 있으면 중단한다.
    if not value or len(value) > 63 or re.fullmatch(r"[a-z][a-z0-9_]*", value) is None:
        raise ValueError(f"안전하지 않은 PostgreSQL schema 이름입니다: {value}")
    return value


def schema_suffix(run_id: str, archive_sha256: str) -> str:
    """실행 ID 날짜 부분과 압축 해시로 충돌 가능성이 낮은 schema 접미사를 만든다."""

    # 실행 ID의 영숫자만 남기고 길이를 제한해 PostgreSQL 식별자 상한을 지킨다.
    compact = "".join(char.lower() for char in run_id if char.isalnum())[-20:]
    return f"{compact}_{archive_sha256[:8]}"


def schema_exists(connection: psycopg.Connection[Any], schema_name: str) -> bool:
    """현재 DB에 지정 schema가 존재하는지 읽기 전용으로 확인한다."""

    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema_name,))
        return cursor.fetchone() is not None


def transformed_migration(schema_name: str) -> str:
    """기존 rag_qwen4 마이그레이션을 검증된 staging schema용으로 변환한다."""

    # schema 이름은 앞서 제한된 문자열만 허용되므로 단순 치환 결과도 안전하다.
    safe_schema_name(schema_name)
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    # 기존 운영 스키마 이름만 staging으로 바꾸고 테이블·제약·인덱스 정의는 동일하게 유지한다.
    return source.replace("rag_qwen4", schema_name)


def validate_receipt(result_root: Path, run_id: str) -> dict[str, Any]:
    """수신 검증 PASS JSON과 RunPod COMPLETE manifest를 적재 전 다시 확인한다."""

    # 로컬 수신 검증기가 만든 파일 없이는 tar.gz 내용을 직접 추측해 적재하지 않는다.
    receipt_path = result_root / "local_receipt_validation.json"
    if not receipt_path.is_file():
        raise FileNotFoundError("local_receipt_validation.json이 없습니다. 수신 검증을 먼저 실행하세요.")
    receipt = read_json(receipt_path)
    if receipt.get("status") != "PASS" or receipt.get("next_gate") != "STAGING_LOAD_ALLOWED":
        raise ValueError("RunPod 수신 검증이 staging 적재 허용 상태가 아닙니다.")
    if receipt.get("run_id") != run_id or receipt.get("database_mutated") is not False:
        raise ValueError("수신 검증 run_id 또는 DB 변경 상태가 올바르지 않습니다.")
    run_manifest = read_json(result_root / "run_manifest.json")
    expected = {
        "status": "COMPLETE",
        "run_id": run_id,
        "model_name": MODEL_NAME,
        "model_revision": MODEL_REVISION,
        "dimension": MODEL_DIMENSION,
        "dtype": "float32",
        "normalization": NORMALIZATION,
    }
    for key, value in expected.items():
        if run_manifest.get(key) != value:
            raise ValueError(f"RunPod run_manifest 적재 계약 불일치: {key}")
    return receipt


def vector_literal(values: Sequence[float]) -> str:
    """float32 벡터를 pgvector 문자열로 변환하며 차원·유한값·norm을 다시 검사한다."""

    # 고정 차원이 아니면 DB vector(2560) 컬럼에 적재하지 않는다.
    if len(values) != MODEL_DIMENSION:
        raise ValueError(f"벡터 차원이 {MODEL_DIMENSION}이 아닙니다: {len(values)}")
    numeric = [float(value) for value in values]
    if any(not math.isfinite(value) for value in numeric):
        raise ValueError("벡터에 NaN 또는 Inf가 있습니다.")
    norm = math.sqrt(sum(value * value for value in numeric))
    if not math.isclose(norm, 1.0, rel_tol=1e-3, abs_tol=1e-3):
        raise ValueError(f"벡터 L2 norm이 1이 아닙니다: {norm}")
    # float32 정밀도를 보존하기에 충분한 9자리 문자열로 직렬화한다.
    return "[" + ",".join(format(value, ".9g") for value in numeric) + "]"


def iter_embedding_rows(path: Path, spec: CorpusDatabase, run_id: str) -> Iterator[tuple[Any, ...]]:
    """Parquet을 32행씩 읽어 embeddings COPY 행을 스트리밍한다."""

    import pyarrow as pa  # Parquet vector 열의 고정 길이와 dtype을 검사한다.
    import pyarrow.parquet as pq  # 대형 판례 벡터를 batch 단위로 읽는다.

    parquet = pq.ParquetFile(path)
    vector_type = parquet.schema_arrow.field("vector").type
    if not pa.types.is_fixed_size_list(vector_type) or vector_type.list_size != MODEL_DIMENSION:
        raise ValueError(f"{spec.key}: vector 열이 고정 2560차원이 아닙니다: {vector_type}")
    if not pa.types.is_float32(vector_type.value_type):
        raise ValueError(f"{spec.key}: vector dtype이 float32가 아닙니다: {vector_type.value_type}")
    # 메모리와 COPY 문자열 크기를 제한하기 위해 32행씩 변환한다.
    for batch in parquet.iter_batches(
        batch_size=32,
        columns=["id", "embedding_input_sha256", "metadata_json", "vector"],
    ):
        for row in batch.to_pylist():
            metadata_wrapper = json.loads(str(row["metadata_json"]))
            target_id = str(row["id"])
            if str(metadata_wrapper.get("target_id") or "") != target_id:
                raise ValueError(f"{spec.key}: metadata target_id 불일치: {target_id}")
            document_id = str(metadata_wrapper.get("document_id") or "")
            if not document_id:
                raise ValueError(f"{spec.key}: 상위 document_id가 없습니다: {target_id}")
            chunk_id = target_id if spec.target_type == "chunk" else None
            source_sha256 = str(metadata_wrapper.get("source_sha256") or "")
            input_sha256 = str(row["embedding_input_sha256"])
            if len(source_sha256) != 64 or len(input_sha256) != 64:
                raise ValueError(f"{spec.key}: SHA-256 길이가 올바르지 않습니다: {target_id}")
            yield (
                target_id,
                spec.target_type,
                document_id,
                chunk_id,
                vector_literal(row["vector"]),
                MODEL_NAME,
                MODEL_REVISION,
                NORMALIZATION,
                source_sha256,
                input_sha256,
                run_id,
                run_id,
            )


def inspect_active_base(connection: psycopg.Connection[Any], spec: CorpusDatabase) -> dict[str, int]:
    """현재 활성 스키마의 원본·청크 건수와 고아 관계를 적재 전에 확인한다."""

    # 기존 시험 벡터는 복사하지 않지만 원본·청크가 단계 5 건수와 맞는지 확인한다.
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                (SELECT count(*) FROM rag_qwen4.documents),
                (SELECT count(*) FROM rag_qwen4.chunks),
                (SELECT count(*) FROM rag_qwen4.chunks c LEFT JOIN rag_qwen4.documents d ON d.document_id=c.document_id WHERE d.document_id IS NULL)
            """
        )
        documents, chunks, orphan_chunks = (int(value) for value in cursor.fetchone())
    if documents != spec.document_count or chunks != spec.chunk_count or orphan_chunks != 0:
        raise ValueError(
            f"{spec.key}: 활성 기본 적재 불일치, documents={documents}, chunks={chunks}, orphan={orphan_chunks}"
        )
    return {"documents": documents, "chunks": chunks, "orphan_chunks": orphan_chunks}


def create_and_load_staging(
    args: argparse.Namespace,
    spec: CorpusDatabase,
    result_root: Path,
    schema_name: str,
    run_id: str,
    archive_sha256: str,
) -> dict[str, Any]:
    """한 DB에 새 staging schema를 만들고 기본 데이터·새 벡터를 트랜잭션으로 적재한다."""

    # 코퍼스별 최종 문서 또는 청크 Parquet 경로를 고정한다.
    vector_path = result_root / spec.key / CORPUS_OUTPUT_NAMES[spec.key]
    artifact = read_json(result_root / spec.key / "artifact_manifest.json")
    if artifact.get("output_sha256") != sha256_file(vector_path):
        raise ValueError(f"{spec.key}: 적재 직전 Parquet SHA-256 불일치")
    with connect(args, spec.database) as connection:
        # schema 존재 여부와 활성 기본 데이터는 변경 전에 검사한다.
        if schema_exists(connection, schema_name):
            # 작업 프로세스가 중단된 뒤 재개한 경우에는 같은 실행 ID의 완전한 staging만 재사용한다.
            # 다른 실행 결과를 실수로 승격하지 않도록 run ID·압축 해시·모델 계약을 DB 안의 기록과 대조한다.
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        "SELECT run_id, archive_sha256, model_name, model_revision FROM {}.stage_load_manifest"
                    ).format(sql.Identifier(schema_name))
                )
                manifest_rows = cursor.fetchall()
            expected_manifest = [(run_id, archive_sha256, MODEL_NAME, MODEL_REVISION)]
            if manifest_rows != expected_manifest:
                raise ValueError(
                    f"{spec.database}: 기존 staging 실행 계약이 달라 재사용할 수 없습니다: {schema_name}"
                )
            # 재개 전에도 활성 기본 문서·청크가 원래 감사 건수와 같은지 다시 읽기 전용으로 확인한다.
            base_audit = inspect_active_base(connection, spec)
            return {
                "database": spec.database,
                "schema": schema_name,
                "base": base_audit,
                "vector_file": str(vector_path),
                "reused_complete_staging": True,
            }
        base_audit = inspect_active_base(connection, spec)
        try:
            with connection.cursor() as cursor:
                # 현재 운영 schema와 동일한 테이블·제약·인덱스를 staging에 만든다.
                cursor.execute(transformed_migration(schema_name))
                # 시험 벡터는 제외하고 검증된 문서·청크 기본 데이터만 복사한다.
                cursor.execute(
                    sql.SQL("INSERT INTO {}.documents SELECT * FROM rag_qwen4.documents").format(
                        sql.Identifier(schema_name)
                    )
                )
                cursor.execute(
                    sql.SQL("INSERT INTO {}.chunks SELECT * FROM rag_qwen4.chunks").format(
                        sql.Identifier(schema_name)
                    )
                )
                # staging 실행 증거를 schema 내부 테이블에 보존한다.
                cursor.execute(
                    sql.SQL(
                        "CREATE TABLE {}.stage_load_manifest (run_id text PRIMARY KEY, archive_sha256 char(64) NOT NULL, "
                        "model_name text NOT NULL, model_revision text NOT NULL, created_at timestamptz NOT NULL DEFAULT now())"
                    ).format(sql.Identifier(schema_name))
                )
                cursor.execute(
                    sql.SQL(
                        "INSERT INTO {}.stage_load_manifest (run_id, archive_sha256, model_name, model_revision) VALUES (%s,%s,%s,%s)"
                    ).format(sql.Identifier(schema_name)),
                    (run_id, archive_sha256, MODEL_NAME, MODEL_REVISION),
                )
                # psycopg COPY를 사용해 8,334개 2560차원 벡터를 행 단위로 안전하게 스트리밍한다.
                copy_sql = sql.SQL(
                    "COPY {}.embeddings (target_id,target_type,document_id,chunk_id,embedding,model_name,model_revision,"
                    "normalization,source_sha256,embedding_input_sha256,index_version,loaded_run_id) FROM STDIN"
                ).format(sql.Identifier(schema_name))
                with cursor.copy(copy_sql) as copy:
                    for row in iter_embedding_rows(vector_path, spec, run_id):
                        copy.write_row(row)
            # schema 생성부터 벡터 COPY까지 모두 성공한 경우에만 한 번에 commit한다.
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {"database": spec.database, "schema": schema_name, "base": base_audit, "vector_file": str(vector_path)}


def validate_staging(args: argparse.Namespace, spec: CorpusDatabase, schema_name: str) -> dict[str, Any]:
    """한 staging schema의 건수·관계·차원·모델·입력 해시를 SQL로 전수 검사한다."""

    with connect(args, spec.database) as connection:
        if not schema_exists(connection, schema_name):
            raise FileNotFoundError(f"{spec.database}: staging schema가 없습니다: {schema_name}")
        with connection.cursor() as cursor:
            # 동적 schema만 Identifier로 조합하고 값은 모두 SQL 상수로 유지한다.
            query = sql.SQL(
                """
                SELECT
                    (SELECT count(*) FROM {s}.documents),
                    (SELECT count(*) FROM {s}.chunks),
                    (SELECT count(*) FROM {s}.embeddings),
                    (SELECT count(*) FROM {s}.embeddings WHERE vector_dims(embedding) <> 2560),
                    (SELECT count(*) FROM {s}.embeddings WHERE model_name <> %s OR model_revision <> %s OR normalization <> %s),
                    (SELECT count(*) FROM {s}.embeddings e LEFT JOIN {s}.documents d ON d.document_id=e.document_id WHERE d.document_id IS NULL),
                    (SELECT count(*) FROM {s}.embeddings e LEFT JOIN {s}.chunks c ON c.chunk_id=e.chunk_id WHERE e.target_type='chunk' AND c.chunk_id IS NULL),
                    (SELECT count(*) FROM {s}.embeddings e JOIN {s}.documents d ON e.target_type='document' AND d.document_id=e.document_id WHERE e.embedding_input_sha256<>d.embedding_input_sha256),
                    (SELECT count(*) FROM {s}.embeddings e JOIN {s}.chunks c ON e.target_type='chunk' AND c.chunk_id=e.chunk_id WHERE e.embedding_input_sha256<>c.embedding_input_sha256)
                """
            ).format(s=sql.Identifier(schema_name))
            cursor.execute(query, (MODEL_NAME, MODEL_REVISION, NORMALIZATION))
            values = [int(value) for value in cursor.fetchone()]
    keys = (
        "documents",
        "chunks",
        "embeddings",
        "invalid_dimensions",
        "invalid_model_contract",
        "orphan_documents",
        "orphan_chunks",
        "document_input_hash_mismatches",
        "chunk_input_hash_mismatches",
    )
    audit = dict(zip(keys, values, strict=True))
    expected = (spec.document_count, spec.chunk_count, spec.embedding_count)
    if tuple(values[:3]) != expected or any(value != 0 for value in values[3:]):
        raise ValueError(f"{spec.key}: staging 검증 실패: {audit}")
    return {"database": spec.database, "schema": schema_name, "status": "PASS", **audit}


def first_query_vector(result_root: Path, corpus_key: str) -> list[float]:
    """코퍼스별 공통 50 질문 Parquet의 첫 벡터를 검색 스모크 테스트용으로 반환한다."""

    import pyarrow.parquet as pq  # 첫 질문 벡터 한 행만 읽는다.

    path = result_root / "evaluation_queries" / "common50" / corpus_key / "query_embeddings.parquet"
    table = pq.read_table(path, columns=["vector"])
    if table.num_rows != 50:
        raise ValueError(f"{corpus_key}: 공통 질문 벡터가 50행이 아닙니다.")
    return [float(value) for value in table.column("vector")[0].as_py()]


def smoke_search(args: argparse.Namespace, spec: CorpusDatabase, result_root: Path) -> dict[str, Any]:
    """승격된 활성 schema에서 첫 질문으로 Top-10 검색을 수행한다."""

    literal = vector_literal(first_query_vector(result_root, spec.key))
    # 소규모 인정기준은 vector exact, 청크 코퍼스는 운영과 같은 halfvec cosine 정렬을 사용한다.
    if spec.key == "fault_standard":
        distance = "embedding <=> %s::vector"
    else:
        distance = "embedding::halfvec(2560) <=> %s::halfvec(2560)"
    query = f"SELECT target_id, 1 - ({distance}) AS cosine FROM rag_qwen4.embeddings ORDER BY {distance}, target_id LIMIT 10"
    with connect(args, spec.database) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, (literal, literal))
            rows = cursor.fetchall()
    if len(rows) != 10 or any(not math.isfinite(float(row[1])) for row in rows):
        raise ValueError(f"{spec.key}: 승격 후 Top-10 검색 스모크 테스트 실패")
    return {"database": spec.database, "result_count": 10, "top1_target_id": str(rows[0][0]), "top1_cosine": float(rows[0][1])}


def stage_all(args: argparse.Namespace, result_root: Path, run_id: str, receipt: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """세 DB의 staging을 모두 적재·검증하고 schema 이름과 결과를 반환한다."""

    # 같은 실행·압축 결과가 세 DB에서 같은 staging schema 이름을 쓰게 한다.
    schema_name = safe_schema_name(f"rag_qwen4_stage_{schema_suffix(run_id, receipt['archive_sha256'])}")
    results: list[dict[str, Any]] = []
    # 세 DB를 순차 적재하되 어느 DB도 활성 schema로 전환하지 않는다.
    for spec in CORPUS_DATABASES:
        load_result = create_and_load_staging(
            args,
            spec,
            result_root,
            schema_name,
            run_id,
            str(receipt["archive_sha256"]),
        )
        validation = validate_staging(args, spec, schema_name)
        results.append({**load_result, "validation": validation})
        print(f"staging 적재·검증 PASS: {spec.key}/{spec.database}/{schema_name}", flush=True)
    return schema_name, results


def rollback_promotions(
    args: argparse.Namespace,
    promoted: Sequence[CorpusDatabase],
    backup_schema: str,
    failed_schema: str,
) -> None:
    """이미 승격된 DB를 이전 활성 schema로 역순 복구한다."""

    # 마지막에 바뀐 DB부터 역순으로 원복해 부분 전환 상태를 줄인다.
    for spec in reversed(promoted):
        with connect(args, spec.database) as connection:
            with connection.cursor() as cursor:
                if schema_exists(connection, failed_schema):
                    raise RuntimeError(f"{spec.database}: 롤백 보존 schema가 이미 존재합니다: {failed_schema}")
                cursor.execute(
                    sql.SQL("ALTER SCHEMA rag_qwen4 RENAME TO {}").format(sql.Identifier(failed_schema))
                )
                cursor.execute(
                    sql.SQL("ALTER SCHEMA {} RENAME TO rag_qwen4").format(sql.Identifier(backup_schema))
                )
            connection.commit()
        print(f"승격 롤백 완료: {spec.database}", flush=True)


def promote_all(
    args: argparse.Namespace,
    result_root: Path,
    schema_name: str,
    run_id: str,
    archive_sha256: str,
) -> tuple[str, list[dict[str, Any]]]:
    """세 staging 검증 후 활성 schema를 교체하고 검색 실패 시 전부 원복한다."""

    # 이전 활성 schema와 실패한 신규 schema를 고유 접미사로 보존한다.
    suffix = schema_suffix(run_id, archive_sha256)
    backup_schema = safe_schema_name(f"rag_qwen4_prev_{suffix}")
    failed_schema = safe_schema_name(f"rag_qwen4_failed_{suffix}")
    # 승격 전 세 DB staging 상태와 backup 충돌을 모두 읽기 전용으로 확인한다.
    for spec in CORPUS_DATABASES:
        validate_staging(args, spec, schema_name)
        with connect(args, spec.database) as connection:
            if not schema_exists(connection, "rag_qwen4"):
                raise FileNotFoundError(f"{spec.database}: 현재 활성 rag_qwen4 schema가 없습니다.")
            if schema_exists(connection, backup_schema) or schema_exists(connection, failed_schema):
                raise FileExistsError(f"{spec.database}: backup 또는 failed schema 이름이 이미 존재합니다.")
    promoted: list[CorpusDatabase] = []
    try:
        # 각 DB 안에서는 두 schema rename을 하나의 트랜잭션으로 수행한다.
        for spec in CORPUS_DATABASES:
            with connect(args, spec.database) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("ALTER SCHEMA rag_qwen4 RENAME TO {}").format(sql.Identifier(backup_schema))
                    )
                    cursor.execute(
                        sql.SQL("ALTER SCHEMA {} RENAME TO rag_qwen4").format(sql.Identifier(schema_name))
                    )
                connection.commit()
            promoted.append(spec)
            print(f"활성 schema 승격: {spec.key}/{spec.database}", flush=True)
        # 세 DB가 모두 바뀐 뒤 실제 Top-10 검색을 수행한다.
        smoke_results = [smoke_search(args, spec, result_root) for spec in CORPUS_DATABASES]
    except Exception:
        # 어느 단계든 실패하면 이미 전환한 모든 DB를 이전 활성 schema로 되돌린다.
        if promoted:
            rollback_promotions(args, promoted, backup_schema, failed_schema)
        raise
    return backup_schema, smoke_results


def write_report(
    run_id: str,
    receipt: dict[str, Any],
    schema_name: str,
    stage_results: Sequence[dict[str, Any]],
    backup_schema: str | None,
    smoke_results: Sequence[dict[str, Any]] | None,
) -> Path:
    """staging 또는 승격 결과를 한국어 Markdown과 JSON으로 기록한다."""

    # 단계 6 실행 증거를 기존 재구조화 이관관리 문서와 같은 폴더에 둔다.
    report_dir = FAULT_CASES_ROOT / "Fault_cases_MD" / "재구조화_이관관리"
    report_dir.mkdir(parents=True, exist_ok=True)
    status = "PROMOTED" if backup_schema else "STAGING_VALIDATED"
    data = {
        "generated_at": utc_now(),
        "status": status,
        "run_id": run_id,
        "archive_sha256": receipt["archive_sha256"],
        "staging_schema": schema_name,
        "backup_schema": backup_schema,
        "stage_results": list(stage_results),
        "smoke_results": list(smoke_results or []),
    }
    json_path = report_dir / "06_Qwen4_운영재색인_DB적재검증.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rows = []
    for item in stage_results:
        validation = item["validation"]
        rows.append(
            f"| {item['database']} | {validation['documents']:,} | {validation['chunks']:,} | "
            f"{validation['embeddings']:,} | {validation['status']} |"
        )
    markdown = "\n".join(
        [
            "# 단계 6 Qwen 4B 운영 재색인 DB 적재 검증",
            "",
            f"- 실행 ID: `{run_id}`",
            f"- 결과 압축 SHA-256: `{receipt['archive_sha256']}`",
            f"- 상태: **{status}**",
            f"- staging schema: `{schema_name}`",
            f"- 이전 활성 schema: `{backup_schema or '아직 전환하지 않음'}`",
            "",
            "| DB | 문서 | 청크 | 새 벡터 | 판정 |",
            "|---|---:|---:|---:|---|",
            *rows,
            "",
            "기존 시험 벡터에는 append하지 않았으며, 세 DB staging이 모두 통과한 경우에만 활성 schema를 전환한다.",
            "",
        ]
    )
    markdown_path = report_dir / "06_Qwen4_운영재색인_DB적재검증.md"
    markdown_path.write_text(markdown, encoding="utf-8", newline="\n")
    return markdown_path


def execute(args: argparse.Namespace) -> None:
    """검증된 결과를 staging 적재하고 요청 시 세 DB를 승격한다."""

    # 루트 `.env`는 비밀번호 값 노출 없이 현재 프로세스에만 로드한다.
    load_env_file(Path(args.env_file).resolve())
    result_root = Path(args.result_root).resolve()
    run_id = args.run_id
    receipt = validate_receipt(result_root, run_id)
    # stage-and-promote는 새 staging을 만들고 검증한 뒤 즉시 안전 승격한다.
    if args.command in ("stage", "stage-and-promote"):
        schema_name, stage_results = stage_all(args, result_root, run_id, receipt)
    else:
        schema_name = safe_schema_name(args.staging_schema)
        stage_results = [
            {"database": spec.database, "validation": validate_staging(args, spec, schema_name)}
            for spec in CORPUS_DATABASES
        ]
    # stage 명령은 운영 활성 schema를 건드리지 않고 검증 보고서만 기록한다.
    if args.command == "stage":
        report_path = write_report(run_id, receipt, schema_name, stage_results, None, None)
        print(f"세 DB staging 적재·검증 완료: {schema_name}")
        print(f"DB 적재 검증 보고서: {report_path}")
        return
    # promote 또는 stage-and-promote는 전체 검증 후 schema를 전환하고 검색까지 확인한다.
    backup_schema, smoke_results = promote_all(
        args,
        result_root,
        schema_name,
        run_id,
        str(receipt["archive_sha256"]),
    )
    report_path = write_report(run_id, receipt, schema_name, stage_results, backup_schema, smoke_results)
    print(f"세 DB 활성 인덱스 승격·검색 검증 완료: 이전={backup_schema}")
    print(f"DB 적재 검증 보고서: {report_path}")


def add_common_arguments(command: argparse.ArgumentParser) -> None:
    """세 하위 명령이 공유하는 결과·DB 연결 인자를 추가한다."""

    command.add_argument("--result-root", required=True)
    command.add_argument("--run-id", required=True)
    command.add_argument("--env-file", default=str(FAULT_CASES_ROOT.parents[1] / ".env"))
    command.add_argument("--host", default=os.environ.get("POSTGRES_HOST", "127.0.0.1"))
    command.add_argument("--port", type=int, default=int(os.environ.get("POSTGRES_PORT", "5432")))
    command.add_argument("--user", default=os.environ.get("POSTGRES_USER", "postgres"))
    command.add_argument("--password-env", default="POSTGRES_PASSWORD")


def parser() -> argparse.ArgumentParser:
    """staging·승격 명령행 계약을 반환한다."""

    root = argparse.ArgumentParser(description="검증된 Qwen 4B 결과를 세 운영 DB에 안전 적재합니다.")
    subparsers = root.add_subparsers(dest="command", required=True)
    stage = subparsers.add_parser("stage", help="세 DB staging 적재·검증만 수행")
    add_common_arguments(stage)
    stage.set_defaults(func=execute)
    promote = subparsers.add_parser("promote", help="이미 검증된 staging을 활성 schema로 승격")
    add_common_arguments(promote)
    promote.add_argument("--staging-schema", required=True)
    promote.set_defaults(func=execute)
    combined = subparsers.add_parser("stage-and-promote", help="staging 적재·검증·승격·검색을 한 번에 수행")
    add_common_arguments(combined)
    combined.set_defaults(func=execute)
    return root


def main() -> int:
    """선택 명령을 실행하고 비밀번호를 포함하지 않는 오류 메시지를 반환한다."""

    try:
        args = parser().parse_args()
        args.func(args)
    except Exception as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    # 모듈 직접 실행 시 main의 성공·실패 코드를 운영체제에 반환한다.
    raise SystemExit(main())
