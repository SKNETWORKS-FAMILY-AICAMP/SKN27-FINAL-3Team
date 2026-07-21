"""Qwen3-Embedding-4B 운영 인덱스를 새 `rag_qwen4` 스키마에 적재한다.

이 도구는 AB 실험의 repeat_01 입력 snapshot과 동일한 Parquet 벡터만 사용한다.
기존 `public`, `search`, 법률 DB 테이블은 수정하지 않으며, 판례는 새
`precedent_db`에만 적재한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

import pyarrow.parquet as pq
import psycopg


ROOT = Path(__file__).resolve().parents[3]
RUN_ROOT = ROOT / "artifacts/embedding_ab_shared/track_a_6models_native_3repeats/run_native7_20260718_v1/repeat_01"
MIGRATION_PATH = ROOT / "rag_runtime/database/migrations/001_rag_qwen4.sql"


@dataclass(frozen=True)
class CorpusSpec:
    """코퍼스별 공식 snapshot·원본·대상 DB 경로를 묶는다."""

    key: str
    database: str
    source_type: str
    raw_document_path: Path | None
    raw_document_id_key: str | None
    raw_document_title_key: str | None
    raw_document_text_key: str | None
    vector_target_type: str


SPECS = {
    "fault_standard": CorpusSpec(
        key="fault_standard",
        database="fault_standard_db",
        source_type="fault_standard",
        raw_document_path=None,
        raw_document_id_key=None,
        raw_document_title_key=None,
        raw_document_text_key=None,
        vector_target_type="document",
    ),
    "review_case": CorpusSpec(
        key="review_case",
        database="review_case_db",
        source_type="review_case",
        raw_document_path=ROOT / "artifacts/review_case_output/preprocessed/review_case_documents.jsonl",
        raw_document_id_key="review_case_id",
        raw_document_title_key="case_title",
        raw_document_text_key="clean_text",
        vector_target_type="chunk",
    ),
    "precedent": CorpusSpec(
        key="precedent",
        database="precedent_db",
        source_type="precedent",
        raw_document_path=ROOT / "artifacts/traffic_precedents_output/traffic_prec_fault_ratio_rag_verified/01_fault_ratio_rag_ready_cases.jsonl",
        raw_document_id_key="_case_id",
        raw_document_title_key="사건명",
        raw_document_text_key="판례내용",
        vector_target_type="chunk",
    ),
}


def sha256_text(value: str) -> str:
    """텍스트를 UTF-8 기준 SHA-256으로 고정한다."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_json(value: dict[str, Any]) -> str:
    """메타데이터 순서와 무관하게 JSON 레코드 해시를 만든다."""

    return sha256_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """JSONL을 한 행씩 읽어 대형 판례 파일도 메모리에 쌓지 않는다."""

    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"JSONL 형식 오류: {path}, {line_number}행") from error


def snapshot_document_path(spec: CorpusSpec) -> Path:
    """AB repeat_01에서 실제 임베딩에 사용한 동결 문서 snapshot 경로를 반환한다."""

    return RUN_ROOT / "00_input/corpora" / spec.key / "documents.jsonl"


def vector_path(spec: CorpusSpec) -> Path:
    """Qwen 4B repeat_01 문서 벡터 Parquet 경로를 반환한다."""

    return RUN_ROOT / "02_vectors/qwen3_4b_native_2560" / spec.key / "document_embeddings.parquet"


def vector_manifest_path(spec: CorpusSpec) -> Path:
    """Parquet 생성 조건을 담은 artifact manifest 경로를 반환한다."""

    return vector_path(spec).parent / "artifact_manifest.json"


def vector_literal(values: list[float]) -> str:
    """pgvector가 읽는 문자열 리터럴을 만들고 차원·유한값을 검증한다."""

    if len(values) != 2560:
        raise ValueError(f"Qwen 4B 벡터 차원이 2560이 아닙니다: {len(values)}")
    if not all(math.isfinite(float(value)) for value in values):
        raise ValueError("NaN 또는 Inf를 포함한 벡터는 적재할 수 없습니다.")
    return "[" + ",".join(format(float(value), ".9g") for value in values) + "]"


def vector_norm(values: list[float]) -> float:
    """정규화 검증을 위해 L2 norm을 계산한다."""

    return math.sqrt(sum(float(value) * float(value) for value in values))


def get_password(name: str) -> str:
    """비밀번호는 지정 환경변수에서만 읽고 출력하지 않는다."""

    value = os.environ.get(name)
    if not value:
        raise ValueError(f"필수 비밀번호 환경변수가 없습니다: {name}")
    return value


def connect_kwargs(args: argparse.Namespace, database: str) -> dict[str, Any]:
    """psycopg 연결 인자를 만들며 비밀번호는 로그에 넣지 않는다."""

    return {
        "host": args.host,
        "port": args.port,
        "user": args.user,
        "password": get_password(args.password_env),
        "dbname": database,
        "connect_timeout": 15,
    }


def ensure_database(args: argparse.Namespace, database: str) -> None:
    """판례 전용 DB처럼 없는 대상 DB만 생성한다. 기존 DB를 삭제하지 않는다."""

    with psycopg.connect(**connect_kwargs(args, "postgres"), autocommit=True) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,))
            if cursor.fetchone() is None:
                cursor.execute(f'CREATE DATABASE "{database}"')


def apply_schema(args: argparse.Namespace, database: str) -> None:
    """대상 DB의 새 `rag_qwen4` 스키마에만 마이그레이션을 적용한다."""

    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    with psycopg.connect(**connect_kwargs(args, database)) as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql)
        conn.commit()


def raw_document_rows(spec: CorpusSpec, run_id: str) -> list[tuple[Any, ...]]:
    """원본 문서를 documents 테이블 적재 형식으로 변환한다."""

    rows: list[tuple[Any, ...]] = []
    if spec.raw_document_path is None:
        for record in read_jsonl(snapshot_document_path(spec)):
            metadata = dict(record.get("metadata") or {})
            document_id = str(record["document_id"])
            title = str(metadata.get("rule_title") or document_id)
            text = str(record.get("embedding_text") or "")
            rows.append(
                (
                    document_id,
                    spec.source_type,
                    f"fault_standard:{document_id}#{document_id}",
                    title,
                    text,
                    text,
                    json.dumps(metadata, ensure_ascii=False),
                    sha256_json(record),
                    sha256_text(text),
                    run_id,
                )
            )
        return rows

    for record in read_jsonl(spec.raw_document_path):
        assert spec.raw_document_id_key and spec.raw_document_title_key and spec.raw_document_text_key
        raw_id = record.get(spec.raw_document_id_key)
        if raw_id is None:
            raise ValueError(f"{spec.key}: 원본 문서 ID가 없습니다: {spec.raw_document_id_key}")
        document_id = str(raw_id)
        title = str(record.get(spec.raw_document_title_key) or document_id)
        raw_text = str(record.get(spec.raw_document_text_key) or "")
        if not raw_text.strip():
            raw_text = title
        rows.append(
            (
                document_id,
                spec.source_type,
                f"{spec.source_type}:{document_id}#{document_id}",
                title,
                raw_text,
                None,
                json.dumps(record, ensure_ascii=False),
                sha256_json(record),
                None,
                run_id,
            )
        )
    return rows


def chunk_rows(spec: CorpusSpec, run_id: str) -> list[tuple[Any, ...]]:
    """snapshot의 검색 단위를 chunks 테이블 적재 형식으로 변환한다."""

    if spec.vector_target_type == "document":
        return []
    rows: list[tuple[Any, ...]] = []
    for record in read_jsonl(snapshot_document_path(spec)):
        metadata = dict(record.get("metadata") or {})
        chunk_id = str(record["document_id"])
        parent_id = str(metadata.get("review_case_id") if spec.key == "review_case" else metadata.get("case_id"))
        if not parent_id or parent_id == "None":
            raise ValueError(f"{spec.key}: {chunk_id}의 상위 문서 ID가 없습니다.")
        chunk_text = str(metadata.get("chunk_text") or record.get("embedding_text") or "")
        embedding_input = str(record.get("embedding_text") or "")
        if not chunk_text.strip() or not embedding_input.strip():
            raise ValueError(f"{spec.key}: {chunk_id}의 청크 또는 임베딩 입력이 비어 있습니다.")
        rows.append(
            (
                chunk_id,
                parent_id,
                int(metadata.get("chunk_index") or metadata.get("sequence_no") or 0),
                str(metadata.get("chunk_type") or "unknown"),
                chunk_text,
                embedding_input,
                json.dumps(metadata, ensure_ascii=False),
                sha256_json(record),
                sha256_text(embedding_input),
                run_id,
            )
        )
    return rows


def embedding_rows(spec: CorpusSpec, run_id: str) -> tuple[list[tuple[Any, ...]], dict[str, Any]]:
    """Parquet 벡터를 embeddings 테이블 적재 형식으로 변환하고 품질 지표를 수집한다."""

    manifest = json.loads(vector_manifest_path(spec).read_text(encoding="utf-8"))
    if manifest.get("model_name") != "Qwen/Qwen3-Embedding-4B":
        raise ValueError(f"{spec.key}: 승인 모델이 아닙니다: {manifest.get('model_name')}")
    if manifest.get("native_dimension") != 2560:
        raise ValueError(f"{spec.key}: 승인 차원이 아닙니다: {manifest.get('native_dimension')}")

    table = pq.read_table(vector_path(spec), columns=["id", "vector", "metadata_json"])
    rows: list[tuple[Any, ...]] = []
    norms: list[float] = []
    for record in table.to_pylist():
        target_id = str(record["id"])
        metadata_wrapper = json.loads(str(record["metadata_json"]))
        metadata = dict(metadata_wrapper.get("metadata") or {})
        values = [float(value) for value in record["vector"]]
        norms.append(vector_norm(values))
        if spec.vector_target_type == "document":
            document_id, chunk_id = target_id, None
        else:
            document_id = str(metadata.get("review_case_id") if spec.key == "review_case" else metadata.get("case_id"))
            chunk_id = target_id
        if not document_id or document_id == "None":
            raise ValueError(f"{spec.key}: {target_id}의 벡터 상위 문서 ID가 없습니다.")
        embedding_input = str(metadata_wrapper.get("embedding_text") or "")
        rows.append(
            (
                target_id,
                spec.vector_target_type,
                document_id,
                chunk_id,
                vector_literal(values),
                str(manifest["model_name"]),
                str(manifest.get("model_revision") or "legacy_unpinned_native7_20260718_v1"),
                "l2_normalized",
                sha256_json(metadata_wrapper),
                sha256_text(embedding_input),
                "qwen3_4b_native_2560_v1",
                run_id,
            )
        )
    quality = {
        "vector_count": len(rows),
        "dimension": 2560,
        "min_l2_norm": min(norms),
        "max_l2_norm": max(norms),
        "artifact_manifest": manifest,
        "model_revision_note": "원 AB artifact에 Hugging Face commit revision이 기록되지 않아 legacy_unpinned 식별자로 보존했습니다.",
    }
    return rows, quality


def upsert_rows(
    cursor: psycopg.Cursor[Any],
    sql: str,
    rows: Iterable[tuple[Any, ...]],
    batch_size: int = 100,
    after_batch: Callable[[], None] | None = None,
) -> int:
    """작은 배치로 upsert해 중단 뒤 재실행해도 같은 기본키를 갱신할 수 있게 한다."""

    buffered: list[tuple[Any, ...]] = []
    count = 0
    for row in rows:
        buffered.append(row)
        if len(buffered) >= batch_size:
            cursor.executemany(sql, buffered)
            count += len(buffered)
            buffered.clear()
            # 대형 판례 벡터는 배치마다 커밋해 시간 제한·중단 뒤에도 재개할 수 있게 한다.
            if after_batch is not None:
                after_batch()
    if buffered:
        cursor.executemany(sql, buffered)
        count += len(buffered)
        if after_batch is not None:
            after_batch()
    return count


def load_corpus(args: argparse.Namespace, spec: CorpusSpec) -> dict[str, Any]:
    """한 코퍼스의 기본 문서·청크·Qwen 벡터를 새 스키마에 적재한다."""

    run_id = args.run_id
    document_rows = raw_document_rows(spec, run_id)
    chunk_rows_value = chunk_rows(spec, run_id)
    embedding_rows_value, vector_quality = embedding_rows(spec, run_id)

    document_ids = {str(row[0]) for row in document_rows}
    chunk_ids = {str(row[0]) for row in chunk_rows_value}
    vector_ids = {str(row[0]) for row in embedding_rows_value}
    if spec.vector_target_type == "document" and vector_ids != document_ids:
        raise ValueError(f"{spec.key}: 문서 ID와 벡터 ID 집합이 일치하지 않습니다.")
    if spec.vector_target_type == "chunk" and vector_ids != chunk_ids:
        raise ValueError(f"{spec.key}: 청크 ID와 벡터 ID 집합이 일치하지 않습니다.")
    if spec.vector_target_type == "chunk" and any(str(row[1]) not in document_ids for row in chunk_rows_value):
        raise ValueError(f"{spec.key}: 청크의 상위 문서가 원본 문서에 없습니다.")

    result: dict[str, Any] = {
        "corpus": spec.key,
        "database": spec.database,
        "document_count": len(document_rows),
        "chunk_count": len(chunk_rows_value),
        "embedding_count": len(embedding_rows_value),
        "vector_quality": vector_quality,
        "applied": False,
    }
    if not args.apply:
        return result

    ensure_database(args, spec.database)
    apply_schema(args, spec.database)
    with psycopg.connect(**connect_kwargs(args, spec.database)) as conn:
        with conn.cursor() as cursor:
            document_sql = """
                INSERT INTO rag_qwen4.documents
                (document_id, source_type, source_reference, title, raw_text, embedding_input, metadata,
                 source_sha256, embedding_input_sha256, loaded_run_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)
                ON CONFLICT (document_id) DO UPDATE SET
                    source_type=EXCLUDED.source_type, source_reference=EXCLUDED.source_reference,
                    title=EXCLUDED.title, raw_text=EXCLUDED.raw_text, embedding_input=EXCLUDED.embedding_input,
                    metadata=EXCLUDED.metadata, source_sha256=EXCLUDED.source_sha256,
                    embedding_input_sha256=EXCLUDED.embedding_input_sha256, loaded_run_id=EXCLUDED.loaded_run_id
            """
            chunk_sql = """
                INSERT INTO rag_qwen4.chunks
                (chunk_id, document_id, chunk_index, chunk_type, chunk_text, embedding_input, metadata,
                 source_sha256, embedding_input_sha256, loaded_run_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)
                ON CONFLICT (chunk_id) DO UPDATE SET
                    document_id=EXCLUDED.document_id, chunk_index=EXCLUDED.chunk_index,
                    chunk_type=EXCLUDED.chunk_type, chunk_text=EXCLUDED.chunk_text,
                    embedding_input=EXCLUDED.embedding_input, metadata=EXCLUDED.metadata,
                    source_sha256=EXCLUDED.source_sha256,
                    embedding_input_sha256=EXCLUDED.embedding_input_sha256, loaded_run_id=EXCLUDED.loaded_run_id
            """
            embedding_sql = """
                INSERT INTO rag_qwen4.embeddings
                (target_id, target_type, document_id, chunk_id, embedding, model_name, model_revision,
                 normalization, source_sha256, embedding_input_sha256, index_version, loaded_run_id)
                VALUES (%s,%s,%s,%s,%s::vector,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (target_id) DO UPDATE SET
                    target_type=EXCLUDED.target_type, document_id=EXCLUDED.document_id, chunk_id=EXCLUDED.chunk_id,
                    embedding=EXCLUDED.embedding, model_name=EXCLUDED.model_name,
                    model_revision=EXCLUDED.model_revision, normalization=EXCLUDED.normalization,
                    source_sha256=EXCLUDED.source_sha256,
                    embedding_input_sha256=EXCLUDED.embedding_input_sha256,
                    index_version=EXCLUDED.index_version, loaded_run_id=EXCLUDED.loaded_run_id
            """
            result["documents_upserted"] = upsert_rows(cursor, document_sql, document_rows)
            conn.commit()
            result["chunks_upserted"] = upsert_rows(cursor, chunk_sql, chunk_rows_value)
            conn.commit()
            result["embeddings_upserted"] = upsert_rows(
                cursor,
                embedding_sql,
                embedding_rows_value,
                # 2,560차원 벡터는 행 하나가 크므로 더 작은 배치로 확정한다.
                batch_size=25,
                after_batch=conn.commit,
            )
    result["applied"] = True
    return result


def main() -> None:
    """입력 snapshot을 검사하고 선택한 코퍼스를 안전하게 적재한다."""

    parser = argparse.ArgumentParser(description="Qwen 4B 운영 인덱스 적재")
    parser.add_argument("--corpus", choices=[*SPECS, "all"], default="all")
    parser.add_argument("--host", default=os.environ.get("POSTGRES_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("POSTGRES_PORT", "5432")))
    parser.add_argument("--user", default=os.environ.get("POSTGRES_USER", "postgres"))
    parser.add_argument("--password-env", default="POSTGRES_PASSWORD")
    parser.add_argument("--run-id", default="qwen4_operational_20260721_v1")
    parser.add_argument("--apply", action="store_true", help="없으면 입력 검증만 수행한다.")
    parser.add_argument("--report-path", required=True)
    args = parser.parse_args()

    selected = list(SPECS.values()) if args.corpus == "all" else [SPECS[args.corpus]]
    results = [load_corpus(args, spec) for spec in selected]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": args.run_id,
        "mode": "apply" if args.apply else "validate_only",
        "safety_note": "기존 public/search 스키마와 법률 DB 테이블을 변경하지 않고 rag_qwen4 스키마만 사용합니다.",
        "results": results,
    }
    output = Path(args.report_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for result in results:
        print(
            f"{result['corpus']}: 문서={result['document_count']}, 청크={result['chunk_count']}, "
            f"벡터={result['embedding_count']}, 적용={result['applied']}"
        )


if __name__ == "__main__":
    main()
