"""Qwen 4B 운영 인덱스의 DB 행·ID·차원·모델 메타데이터를 검증한다."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg


EXPECTED = {
    "fault_standard": {"database": "fault_standard_db", "documents": 277, "chunks": 0, "embeddings": 277},
    "review_case": {"database": "review_case_db", "documents": 226, "chunks": 904, "embeddings": 904},
    "precedent": {"database": "precedent_db", "documents": 987, "chunks": 8334, "embeddings": 8334},
}


def password_from_env(name: str) -> str:
    """비밀번호를 환경변수에서만 읽고 보고서에는 저장하지 않는다."""

    value = os.environ.get(name)
    if not value:
        raise ValueError(f"필수 비밀번호 환경변수가 없습니다: {name}")
    return value


def inspect_database(args: argparse.Namespace, corpus: str, spec: dict[str, Any]) -> dict[str, Any]:
    """한 코퍼스 DB의 적재 불변식을 읽기 전용 SQL로 점검한다."""

    with psycopg.connect(
        host=args.host,
        port=args.port,
        user=args.user,
        password=password_from_env(args.password_env),
        dbname=str(spec["database"]),
    ) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    (SELECT count(*) FROM rag_qwen4.documents),
                    (SELECT count(*) FROM rag_qwen4.chunks),
                    (SELECT count(*) FROM rag_qwen4.embeddings),
                    (SELECT count(*) FROM rag_qwen4.embeddings WHERE embedding IS NULL OR vector_dims(embedding) <> 2560),
                    (SELECT count(*) FROM rag_qwen4.chunks c LEFT JOIN rag_qwen4.documents d ON d.document_id=c.document_id WHERE d.document_id IS NULL),
                    (SELECT count(*) FROM rag_qwen4.embeddings e LEFT JOIN rag_qwen4.documents d ON d.document_id=e.document_id WHERE d.document_id IS NULL),
                    (SELECT count(*) FROM rag_qwen4.embeddings e LEFT JOIN rag_qwen4.chunks c ON c.chunk_id=e.chunk_id WHERE e.target_type='chunk' AND c.chunk_id IS NULL),
                    (SELECT count(*) FROM rag_qwen4.embeddings WHERE model_name IS NULL OR model_revision IS NULL OR source_sha256 IS NULL OR embedding_input_sha256 IS NULL),
                    (SELECT count(*) FROM rag_qwen4.embeddings WHERE model_revision LIKE 'legacy_unpinned%')
                """
            )
            row = cursor.fetchone()
    keys = (
        "documents",
        "chunks",
        "embeddings",
        "invalid_vectors",
        "orphan_chunks",
        "orphan_embedding_documents",
        "orphan_embedding_chunks",
        "missing_metadata",
        "legacy_unpinned_revision_rows",
    )
    actual = dict(zip(keys, row, strict=True))
    expected_match = all(actual[key] == spec[key] for key in ("documents", "chunks", "embeddings"))
    integrity_clean = all(actual[key] == 0 for key in keys[3:8])
    return {
        "corpus": corpus,
        "database": spec["database"],
        "expected": {key: spec[key] for key in ("documents", "chunks", "embeddings")},
        "actual": actual,
        "status": "PASS" if expected_match and integrity_clean else "FAIL",
        "model_revision_status": "LEGACY_UNPINNED_WARNING" if actual["legacy_unpinned_revision_rows"] else "PINNED",
    }


def main() -> None:
    """세 운영 코퍼스를 검증하고 JSON 결과를 기록한다."""

    parser = argparse.ArgumentParser(description="Qwen 4B 운영 인덱스 검증")
    parser.add_argument("--host", default=os.environ.get("POSTGRES_HOST", "127.0.0.1"))
    parser.add_argument("--port", default=int(os.environ.get("POSTGRES_PORT", "5432")), type=int)
    parser.add_argument("--user", default=os.environ.get("POSTGRES_USER", "postgres"))
    parser.add_argument("--password-env", default="POSTGRES_PASSWORD")
    parser.add_argument("--report-path", required=True)
    args = parser.parse_args()

    results = [inspect_database(args, corpus, spec) for corpus, spec in EXPECTED.items()]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
        "overall_status": "PASS" if all(row["status"] == "PASS" for row in results) else "FAIL",
        "release_note": "AB artifact에는 Hugging Face commit revision이 기록되지 않았으므로, legacy_unpinned 표시는 운영 재임베딩 전까지 남긴다.",
    }
    output = Path(args.report_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for row in results:
        print(f"{row['corpus']}: {row['status']}, revision={row['model_revision_status']}")
    if report["overall_status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

