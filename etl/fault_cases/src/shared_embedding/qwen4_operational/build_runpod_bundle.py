"""세 코퍼스 운영 입력을 감사하고 RunPod 단일 실행 ZIP을 만든다.

이 도구는 원본·전처리·청크·평가 연결과 단계 5 PostgreSQL ID를 읽기 전용으로
검증한다. 검증된 최소 임베딩 입력만 별도 스냅샷으로 동결하며 정답지는 ZIP에 넣지 않는다.
"""

from __future__ import annotations

import argparse  # 실행 ID와 Docker 컨테이너 이름을 안전한 명령행 인자로 받는다.
import hashlib  # 원본·스냅샷·ZIP의 SHA-256을 계산한다.
import json  # JSON·JSONL 입력과 manifest를 읽고 쓴다.
import shutil  # 같은 실행 ID의 미완성 스냅샷을 새로 만들 때 폴더를 정리한다.
import subprocess  # Docker 내부 psql을 읽기 전용으로 호출해 단계 5 DB와 대조한다.
import sys  # 오류 메시지와 종료 코드를 운영체제에 반환한다.
import zipfile  # Linux 경로가 보장된 RunPod 업로드 ZIP을 만든다.
from collections import Counter  # 중복 ID와 상태별 건수를 계산한다.
from datetime import datetime, timezone  # manifest 생성 시각을 UTC로 통일한다.
from pathlib import Path  # 운영체제와 무관하게 파일 경로를 조합한다.
from statistics import median  # 임베딩 텍스트 길이 중앙값을 감사 보고서에 기록한다.
from typing import Any, Iterable, Iterator, Sequence  # 함수 입출력 계약을 명시한다.

from .config import (  # 모델·코퍼스·평가 경로의 고정 계약을 가져온다.
    COMMON_QUERY_PATH,
    COMPLETE30_ANSWER_PATH,
    COMPLETE30_QUERY_PATH,
    CORPUS_SOURCES,
    EXPECTED_COUNTS,
    FAULT_CASES_ROOT,
    MODEL_DIMENSION,
    MODEL_NAME,
    MODEL_REVISION,
    NORMALIZATION,
    PROJECT_ROOT,
    QUERY_INSTRUCTIONS,
    STAGE6_ARTIFACT_ROOT,
    CorpusSource,
)


def utc_now() -> str:
    """현재 UTC 시각을 ISO-8601 문자열로 반환한다."""

    # 컴퓨터 시간대와 관계없이 같은 의미를 갖도록 UTC 시각만 기록한다.
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(value: bytes) -> str:
    """메모리의 바이트 값에 대한 SHA-256 문자열을 반환한다."""

    # manifest와 원문 레코드의 변경 여부를 64자리 해시로 고정한다.
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    """UTF-8 텍스트의 SHA-256 문자열을 반환한다."""

    # 운영체제 기본 인코딩 차이를 제거한 뒤 바이트 해시 함수를 재사용한다.
    return sha256_bytes(value.encode("utf-8"))


def sha256_file(path: Path) -> str:
    """대형 파일을 1MiB씩 읽어 SHA-256 문자열을 반환한다."""

    # 판례 JSONL 전체를 메모리에 올리지 않도록 누적 해시 객체를 준비한다.
    digest = hashlib.sha256()
    # 바이너리 모드로 열어 Windows 줄바꿈 변환 없이 실제 파일 바이트를 읽는다.
    with path.open("rb") as handle:
        # 파일 끝까지 1MiB 단위로 반복해 메모리 사용량을 제한한다.
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    # 누적된 해시를 사람이 비교할 수 있는 16진 문자열로 반환한다.
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    """키 순서와 공백에 영향을 받지 않는 JSON 문자열을 반환한다."""

    # 원본 레코드 해시가 사전 키 순서에 따라 달라지지 않도록 정렬해 직렬화한다.
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """UTF-8 JSONL을 한 행씩 검증하며 반환한다."""

    # 입력이 없으면 빈 결과로 진행하지 않고 명확한 파일 오류를 발생시킨다.
    if not path.is_file():
        raise FileNotFoundError(f"입력 파일이 없습니다: {path}")
    # 한국어 원문을 보존하도록 UTF-8로 파일을 연다.
    with path.open("r", encoding="utf-8") as handle:
        # 실제 줄 번호를 유지해 손상된 행을 정확히 안내한다.
        for line_number, line in enumerate(handle, start=1):
            # 빈 줄은 데이터 행으로 계산하지 않는다.
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"JSONL 파싱 실패: {path}, {line_number}행") from error
            # 배열이나 문자열 행은 현재 입력 계약에 맞지 않으므로 차단한다.
            if not isinstance(row, dict):
                raise ValueError(f"JSONL 행이 객체가 아닙니다: {path}, {line_number}행")
            yield row


def write_json(path: Path, value: Any) -> None:
    """한국어를 보존한 들여쓰기 JSON 파일을 기록한다."""

    # 중첩 산출물 경로가 없어도 한 번에 만들도록 부모 폴더를 준비한다.
    path.parent.mkdir(parents=True, exist_ok=True)
    # 사람이 검수하기 쉬운 키 정렬·들여쓰기 형식으로 UTF-8 파일을 쓴다.
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    """객체 반복자를 UTF-8 JSONL로 기록하고 행 수를 반환한다."""

    # 파일 생성 전에 부모 디렉터리를 안전하게 준비한다.
    path.parent.mkdir(parents=True, exist_ok=True)
    # Windows에서도 Linux와 같은 LF 줄바꿈을 쓰도록 newline을 고정한다.
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        # 각 행을 한 줄 JSON으로 기록해 대형 입력도 스트리밍 가능하게 한다.
        for row in rows:
            handle.write(canonical_json(row) + "\n")
            count += 1
    # manifest 예상 건수와 대조할 수 있도록 실제 기록 행 수를 반환한다.
    return count


def require_unique(values: Sequence[str], label: str) -> None:
    """비어 있거나 중복된 식별자가 있으면 예외를 발생시킨다."""

    # 공백 ID는 DB 조인과 검색 결과 역추적을 불가능하게 하므로 금지한다.
    if any(not value.strip() for value in values):
        raise ValueError(f"{label}: 비어 있는 ID가 있습니다.")
    # 빈도 2 이상인 값을 소수 예시로 모아 원본 수정 위치를 찾기 쉽게 한다.
    duplicates = [key for key, count in Counter(values).items() if count > 1]
    if duplicates:
        raise ValueError(f"{label}: 중복 ID가 있습니다. 예: {duplicates[:5]}")


def percentile(values: Sequence[int], ratio: float) -> int:
    """정수 길이 목록에서 단순 nearest-rank 분위수를 반환한다."""

    # 빈 코퍼스는 정상 입력이 아니므로 분위수를 계산하지 않는다.
    if not values:
        raise ValueError("길이 통계를 계산할 입력이 비어 있습니다.")
    # 정렬 후 0부터 시작하는 안전한 인덱스로 비율 위치를 계산한다.
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * ratio)))
    return int(ordered[index])


def build_fault_standard_rows(source: CorpusSource) -> tuple[list[dict[str, Any]], set[str], dict[str, Any]]:
    """네 Rulebook을 인정기준 운영 검색문서 구조로 표준화한다."""

    # 네 원본 경로를 순서대로 읽어 하나의 검색문서 목록으로 합친다.
    raw_rows = [row for path in source.source_document_paths for row in read_jsonl(path)]
    # Rule ID는 원문·qrels·DB를 연결하는 공식 기본키다.
    rule_ids = [str(row.get("rule_id") or "").strip() for row in raw_rows]
    require_unique(rule_ids, "인정기준 Rule")
    # 파싱 실패 Rule을 운영 인덱스에 조용히 포함하지 않는다.
    invalid = [rule_id for rule_id, row in zip(rule_ids, raw_rows, strict=True) if row.get("parse_status") != "valid"]
    if invalid:
        raise ValueError(f"인정기준: parse_status가 valid가 아닌 Rule이 있습니다. 예: {invalid[:5]}")
    # 이전 모델 비교와 동일한 의미 단위를 유지하되 현재 원본에서 텍스트를 새로 구성한다.
    records: list[dict[str, Any]] = []
    for rule_id, row in zip(rule_ids, raw_rows, strict=True):
        # 제목·코드·기준비율을 줄 단위로 결합해 Rule 검색 입력을 자가 설명 가능하게 만든다.
        embedding_text = "\n".join(
            value
            for value in (
                str(row.get("rule_title") or "").strip(),
                str(row.get("rule_code") or "").strip(),
                str(row.get("normalized_ratio") or "").strip(),
            )
            if value
        )
        # 핵심 제목이 비면 잘못된 Rule을 임베딩하지 않고 즉시 중단한다.
        if not str(row.get("rule_title") or "").strip() or not embedding_text:
            raise ValueError(f"인정기준: 임베딩 텍스트가 불완전합니다: {rule_id}")
        # 원본 레코드와 임베딩 입력 해시를 각각 보존해 후속 DB 적재에서 대조한다.
        records.append(
            {
                "target_id": rule_id,
                "target_type": "document",
                "document_id": rule_id,
                "embedding_text": embedding_text,
                "embedding_input_sha256": sha256_text(embedding_text),
                "source_sha256": sha256_text(canonical_json(row)),
                "metadata": row,
            }
        )
    # 감사 보고서에 Rulebook별 행 수를 기록해 특정 파일 누락을 확인한다.
    per_source = {path.as_posix(): sum(1 for _ in read_jsonl(path)) for path in source.source_document_paths}
    return records, set(rule_ids), {"source_document_count": len(raw_rows), "per_source_count": per_source}


def build_review_case_rows(source: CorpusSource) -> tuple[list[dict[str, Any]], set[str], dict[str, Any]]:
    """심의사례 문서와 청크의 부모 관계를 검증하고 운영 검색 단위를 만든다."""

    # 확정 사례 문서를 읽어 부모 ID 집합을 구성한다.
    documents = list(read_jsonl(source.source_document_paths[0]))
    document_ids = [str(row.get("review_case_id") or "").strip() for row in documents]
    require_unique(document_ids, "심의사례 원본")
    # 운영 대상 문서는 모두 정상 파싱 상태여야 한다.
    invalid_documents = [
        document_id
        for document_id, row in zip(document_ids, documents, strict=True)
        if row.get("parse_status") != "valid"
    ]
    if invalid_documents:
        raise ValueError(f"심의사례: 원본 parse_status 오류가 있습니다. 예: {invalid_documents[:5]}")
    # 실제 임베딩 대상 청크를 읽고 고유 ID를 확인한다.
    assert source.embedding_unit_path is not None
    chunks = list(read_jsonl(source.embedding_unit_path))
    chunk_ids = [str(row.get("chunk_id") or "").strip() for row in chunks]
    require_unique(chunk_ids, "심의사례 청크")
    # 모든 청크가 현재 226개 원본 중 하나를 가리키는지 검사한다.
    document_id_set = set(document_ids)
    orphan_ids = [
        chunk_id
        for chunk_id, row in zip(chunk_ids, chunks, strict=True)
        if str(row.get("review_case_id") or "").strip() not in document_id_set
    ]
    if orphan_ids:
        raise ValueError(f"심의사례: 상위 문서가 없는 청크가 있습니다. 예: {orphan_ids[:5]}")
    # 청크 원문 자체를 임베딩 입력으로 사용해 기존 승인 검색 단위를 유지한다.
    records: list[dict[str, Any]] = []
    for chunk_id, row in zip(chunk_ids, chunks, strict=True):
        embedding_text = str(row.get("chunk_text") or "").strip()
        if not embedding_text or row.get("parse_status") != "valid":
            raise ValueError(f"심의사례: 비정상 또는 빈 청크입니다: {chunk_id}")
        records.append(
            {
                "target_id": chunk_id,
                "target_type": "chunk",
                "document_id": str(row["review_case_id"]),
                "embedding_text": embedding_text,
                "embedding_input_sha256": sha256_text(embedding_text),
                "source_sha256": sha256_text(canonical_json(row)),
                "metadata": row,
            }
        )
    # 부모별 청크가 최소 한 개 이상인지 검사한다.
    covered_documents = {row["document_id"] for row in records}
    without_chunk = sorted(document_id_set - covered_documents)
    if without_chunk:
        raise ValueError(f"심의사례: 검색 청크가 없는 원본 사례가 있습니다. 예: {without_chunk[:5]}")
    return records, document_id_set, {
        "source_document_count": len(documents),
        "embedding_unit_count": len(chunks),
        "documents_without_chunk": 0,
    }


def build_precedent_rows(source: CorpusSource) -> tuple[list[dict[str, Any]], set[str], dict[str, Any]]:
    """판례 원본과 청크 v2의 부모·본문 해시를 검증하고 운영 검색 단위를 만든다."""

    # RAG 적격 판례 987건을 읽고 사건 ID를 고유 문자열로 정규화한다.
    documents = list(read_jsonl(source.source_document_paths[0]))
    document_ids = [str(row.get("_case_id") or "").strip() for row in documents]
    require_unique(document_ids, "판례 원본")
    # ready가 아닌 판례가 공식 입력에 섞이면 검색 근거 품질이 달라지므로 중단한다.
    not_ready = [
        document_id
        for document_id, row in zip(document_ids, documents, strict=True)
        if row.get("rag_eligibility") != "ready"
    ]
    if not_ready:
        raise ValueError(f"판례: rag_eligibility가 ready가 아닌 원본이 있습니다. 예: {not_ready[:5]}")
    # 확정 청크 v2를 읽고 ID 중복과 상위 사건 연결을 검사한다.
    assert source.embedding_unit_path is not None
    chunks = list(read_jsonl(source.embedding_unit_path))
    chunk_ids = [str(row.get("chunk_id") or "").strip() for row in chunks]
    require_unique(chunk_ids, "판례 청크")
    document_id_set = set(document_ids)
    orphan_ids = [
        chunk_id
        for chunk_id, row in zip(chunk_ids, chunks, strict=True)
        if str(row.get("case_id") or "").strip() not in document_id_set
    ]
    if orphan_ids:
        raise ValueError(f"판례: 상위 판례가 없는 청크가 있습니다. 예: {orphan_ids[:5]}")
    # 저장된 text_hash가 현재 chunk_text와 같은지 전 행에서 확인한다.
    text_hash_errors = [
        chunk_id
        for chunk_id, row in zip(chunk_ids, chunks, strict=True)
        if str(row.get("text_hash") or "") != sha256_text(str(row.get("chunk_text") or ""))
    ]
    if text_hash_errors:
        raise ValueError(f"판례: 청크 본문 text_hash 불일치가 있습니다. 예: {text_hash_errors[:5]}")
    # 제목·사건 맥락이 포함된 확정 embedding_text를 실제 모델 입력으로 동결한다.
    records: list[dict[str, Any]] = []
    for chunk_id, row in zip(chunk_ids, chunks, strict=True):
        embedding_text = str(row.get("embedding_text") or "").strip()
        if not embedding_text:
            raise ValueError(f"판례: embedding_text가 비어 있습니다: {chunk_id}")
        records.append(
            {
                "target_id": chunk_id,
                "target_type": "chunk",
                "document_id": str(row["case_id"]),
                "embedding_text": embedding_text,
                "embedding_input_sha256": sha256_text(embedding_text),
                "source_sha256": sha256_text(canonical_json(row)),
                "metadata": row,
            }
        )
    # 모든 판례가 최소 한 청크를 갖는지 검사해 원본만 있고 검색되지 않는 사례를 막는다.
    covered_documents = {row["document_id"] for row in records}
    without_chunk = sorted(document_id_set - covered_documents)
    if without_chunk:
        raise ValueError(f"판례: 검색 청크가 없는 원본 판례가 있습니다. 예: {without_chunk[:5]}")
    return records, document_id_set, {
        "source_document_count": len(documents),
        "embedding_unit_count": len(chunks),
        "documents_without_chunk": 0,
        "chunk_text_hash_errors": 0,
    }


def load_db_rows(container: str, database: str, sql: str) -> list[tuple[str, ...]]:
    """Docker PostgreSQL에서 비밀정보 없이 읽기 전용 질의 결과를 반환한다."""

    # 컨테이너 내부 로컬 접속을 사용해 호스트 `.env` 비밀번호를 읽거나 출력하지 않는다.
    command = ["docker", "exec", container, "psql", "-U", "postgres", "-d", database, "-At", "-F", "\t", "-c", sql]
    completed = subprocess.run(command, check=False, capture_output=True, text=True, encoding="utf-8")
    # psql 실패는 DB 대조를 건너뛰지 않고 즉시 원인과 함께 중단한다.
    if completed.returncode != 0:
        safe_error = completed.stderr.strip().replace("\n", " ")
        raise RuntimeError(f"단계 5 DB 읽기 실패({database}): {safe_error}")
    # 빈 줄을 제외하고 탭 구분 열을 튜플로 변환한다.
    return [tuple(line.split("\t")) for line in completed.stdout.splitlines() if line.strip()]


def verify_stage5_database(
    source: CorpusSource,
    records: Sequence[dict[str, Any]],
    source_document_ids: set[str],
    container: str,
) -> dict[str, Any]:
    """단계 5 DB의 원본·검색 단위 ID와 임베딩 입력 해시를 현재 스냅샷과 대조한다."""

    # 원본 문서 ID는 세 코퍼스 모두 documents 테이블에서 읽는다.
    db_document_rows = load_db_rows(container, source.database, "SELECT document_id FROM rag_qwen4.documents ORDER BY 1")
    db_document_ids = {row[0] for row in db_document_rows}
    if db_document_ids != source_document_ids:
        missing = sorted(source_document_ids - db_document_ids)[:5]
        extra = sorted(db_document_ids - source_document_ids)[:5]
        raise ValueError(f"{source.key}: DB 원본문서 ID 불일치, 누락={missing}, 초과={extra}")
    # 인정기준은 documents, 나머지는 chunks에서 검색 단위 ID·입력 해시를 읽는다.
    if source.target_type == "document":
        sql = "SELECT document_id, COALESCE(embedding_input_sha256::text, '') FROM rag_qwen4.documents ORDER BY 1"
    else:
        sql = "SELECT chunk_id, COALESCE(embedding_input_sha256::text, '') FROM rag_qwen4.chunks ORDER BY 1"
    db_target_rows = load_db_rows(container, source.database, sql)
    db_hashes = {row[0]: row[1] for row in db_target_rows}
    snapshot_hashes = {str(row["target_id"]): str(row["embedding_input_sha256"]) for row in records}
    if set(db_hashes) != set(snapshot_hashes):
        missing = sorted(set(snapshot_hashes) - set(db_hashes))[:5]
        extra = sorted(set(db_hashes) - set(snapshot_hashes))[:5]
        raise ValueError(f"{source.key}: DB 검색단위 ID 불일치, 누락={missing}, 초과={extra}")
    # 단계 5의 입력 텍스트와 현재 동결 텍스트가 다르면 벡터-원문 연결이 달라지므로 중단한다.
    hash_mismatches = [target_id for target_id, value in snapshot_hashes.items() if db_hashes.get(target_id) != value]
    if hash_mismatches:
        raise ValueError(f"{source.key}: DB 임베딩 입력 SHA-256 불일치가 있습니다. 예: {hash_mismatches[:5]}")
    # 기존 시험 벡터 건수는 기록만 하며 운영 공식 입력으로 승인하지 않는다.
    embedding_count = int(load_db_rows(container, source.database, "SELECT count(*) FROM rag_qwen4.embeddings")[0][0])
    return {
        "database": source.database,
        "document_id_count": len(db_document_ids),
        "target_id_count": len(db_hashes),
        "embedding_input_hash_mismatch_count": 0,
        "existing_test_embedding_count": embedding_count,
        "existing_test_embeddings_approved_for_operation": False,
    }


def validate_common_queries() -> tuple[list[dict[str, Any]], set[str], dict[str, Any]]:
    """공통 질문지 50행의 승인 상태와 고유 ID를 검증한다."""

    # 승인 원본에서 질문을 읽고 정확한 50행인지 먼저 확인한다.
    queries = list(read_jsonl(COMMON_QUERY_PATH))
    if len(queries) != 50:
        raise ValueError(f"공통 질문지는 50행이어야 합니다: {len(queries)}")
    # query_id와 query_text는 RunPod 평가 벡터를 만드는 필수 필드다.
    query_ids = [str(row.get("query_id") or "").strip() for row in queries]
    require_unique(query_ids, "공통 질문")
    if any(row.get("annotation_status") != "approved" for row in queries):
        raise ValueError("공통 질문지에 approved가 아닌 질문이 있습니다.")
    if any(not str(row.get("query_text") or "").strip() for row in queries):
        raise ValueError("공통 질문지에 빈 query_text가 있습니다.")
    # 정답·과실비율 필드는 제외하고 임베딩에 필요한 최소 질문 정보만 복사한다.
    public_rows = [
        {
            "query_id": str(row["query_id"]),
            "query_text": str(row["query_text"]).strip(),
            "query_text_sha256": sha256_text(str(row["query_text"]).strip()),
            "annotation_status": "approved",
            "eval_set_version": row.get("eval_set_version"),
        }
        for row in queries
    ]
    return public_rows, set(query_ids), {"query_count": 50, "approved_count": 50}


def validate_complete30_queries() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Complete30 질문·정답 ID와 질문 해시를 검증하되 ZIP에는 질문만 반환한다."""

    # 질문과 정답을 로컬에서 각각 읽어 30행 계약을 확인한다.
    queries = list(read_jsonl(COMPLETE30_QUERY_PATH))
    answers = list(read_jsonl(COMPLETE30_ANSWER_PATH))
    if len(queries) != 30 or len(answers) != 30:
        raise ValueError(f"Complete30 행 수가 30이 아닙니다: 질문={len(queries)}, 정답={len(answers)}")
    # case_id가 양쪽에서 고유하고 정확히 같은 집합이어야 한다.
    query_ids = [str(row.get("case_id") or "").strip() for row in queries]
    answer_ids = [str(row.get("case_id") or "").strip() for row in answers]
    require_unique(query_ids, "Complete30 질문")
    require_unique(answer_ids, "Complete30 정답")
    if set(query_ids) != set(answer_ids):
        raise ValueError("Complete30 질문과 정답의 case_id 집합이 다릅니다.")
    # 각 질문 파일의 input_sha256은 해시 필드를 제외한 질문 JSON 전체의 canonical 해시다.
    hash_errors = [
        query_id
        for query_id, row in zip(query_ids, queries, strict=True)
        if str(row.get("input_sha256") or "")
        != sha256_text(canonical_json({key: value for key, value in row.items() if key != "input_sha256"}))
    ]
    if hash_errors:
        raise ValueError(f"Complete30 질문 input_sha256 불일치가 있습니다. 예: {hash_errors[:5]}")
    # RunPod에는 정답 설명·Rule ID·비율을 제외한 질문 텍스트만 복사한다.
    public_rows = [
        {
            "query_id": query_id,
            "query_text": str(row["query_text"]).strip(),
            "query_text_sha256": sha256_text(str(row["query_text"]).strip()),
            "source_record_sha256": str(row["input_sha256"]),
            "dataset_version": row.get("dataset_version"),
        }
        for query_id, row in zip(query_ids, queries, strict=True)
    ]
    return public_rows, {"query_count": 30, "answer_count": 30, "id_mismatch_count": 0, "hash_error_count": 0}


def validate_qrels(
    source: CorpusSource,
    common_query_ids: set[str],
    target_ids: set[str],
    source_document_ids: set[str],
) -> dict[str, Any]:
    """코퍼스별 qrels가 질문 50개와 실제 운영 검색 단위를 가리키는지 확인한다."""

    # 정답지는 로컬 검증에만 사용하고 반환 레코드는 ZIP에 복사하지 않는다.
    qrels = list(read_jsonl(source.qrels_path))
    qrel_query_ids = {str(row.get("query_id") or "").strip() for row in qrels}
    if qrel_query_ids != common_query_ids:
        raise ValueError(f"{source.key}: qrels가 공통 50문항을 정확히 덮지 않습니다.")
    # 양의 관련도 행에서 코퍼스별 상위 문서·사례 ID가 실제 원본에 있는지 검사한다.
    positive_rows = [
        row
        for row in qrels
        if row.get("judgment_status") != "no_relevant_document" and int(row.get("relevance") or 0) > 0
    ]
    missing_targets = sorted(
        {
            str(row.get(source.qrel_target_field) or "").strip()
            for row in positive_rows
            if str(row.get(source.qrel_target_field) or "").strip() not in source_document_ids
        }
    )
    if missing_targets:
        raise ValueError(f"{source.key}: qrels 상위 정답이 원본 문서에 없습니다. 예: {missing_targets[:5]}")
    # chunk_id가 명시된 정답은 현재 운영 청크 ID에도 존재해야 한다.
    missing_chunks = sorted(
        {
            str(row.get("chunk_id") or "").strip()
            for row in positive_rows
            if str(row.get("chunk_id") or "").strip() and str(row.get("chunk_id") or "").strip() not in target_ids
        }
    )
    if missing_chunks:
        raise ValueError(f"{source.key}: qrels 정답 청크가 현재 입력에 없습니다. 예: {missing_chunks[:5]}")
    # 무정답 질문 수와 양의 정답 행 수를 보고서에 남긴다.
    no_relevant = {str(row["query_id"]) for row in qrels if row.get("judgment_status") == "no_relevant_document"}
    return {
        "qrels_row_count": len(qrels),
        "covered_query_count": len(qrel_query_ids),
        "positive_row_count": len(positive_rows),
        "no_relevant_query_count": len(no_relevant),
        "missing_target_count": 0,
        "missing_chunk_count": 0,
        "qrels_sha256": sha256_file(source.qrels_path),
        "included_in_runpod_zip": False,
    }


def record_length_summary(records: Sequence[dict[str, Any]]) -> dict[str, int]:
    """코퍼스 임베딩 텍스트의 문자 길이 분포를 계산한다."""

    # 공백 제거 후 실제 모델 입력 문자열의 길이를 전 행에서 측정한다.
    lengths = [len(str(row["embedding_text"])) for row in records]
    return {
        "minimum_chars": min(lengths),
        "median_chars": int(median(lengths)),
        "p95_chars": percentile(lengths, 0.95),
        "maximum_chars": max(lengths),
    }


def safe_run_id(value: str) -> str:
    """실행 ID가 파일 경로를 탈출하지 않는 안전한 문자열인지 확인한다."""

    # 영문·숫자·밑줄·하이픈만 허용해 셸과 파일 경로 주입 위험을 차단한다.
    if not value or any(not (char.isalnum() or char in "_-") for char in value):
        raise ValueError("run-id는 영문·숫자·밑줄·하이픈만 사용할 수 있습니다.")
    return value


def add_zip_file(archive: zipfile.ZipFile, source: Path, archive_name: str, executable: bool = False) -> None:
    """파일을 `/` 경로와 Linux 권한을 지정해 ZIP에 추가한다."""

    # ZipInfo를 직접 만들어 Windows 역슬래시가 ZIP 내부 경로에 들어가지 않게 한다.
    info = zipfile.ZipInfo(archive_name.replace("\\", "/"))
    # 원본 수정 시각 대신 고정 시각을 써 같은 입력의 ZIP 재현성을 높인다.
    info.date_time = (2026, 7, 21, 0, 0, 0)
    # Linux에서 셸 파일은 실행 가능, 나머지는 읽기 가능한 일반 파일 권한을 부여한다.
    mode = 0o755 if executable else 0o644
    info.external_attr = (mode & 0xFFFF) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    # 파일 바이트를 그대로 읽어 경로 변환 외 내용 변경 없이 ZIP에 쓴다.
    archive.writestr(info, source.read_bytes())


def build_zip(snapshot_root: Path, run_id: str) -> Path:
    """검증된 입력과 실행 코드만 포함한 RunPod ZIP을 생성한다."""

    # 최종 사용자가 쉽게 찾도록 번들 전용 폴더와 버전 파일명을 만든다.
    bundle_dir = STAGE6_ARTIFACT_ROOT / "runpod_bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    zip_path = bundle_dir / f"qwen4_three_corpus_operational_bundle_{run_id}.zip"
    # 같은 이름의 과거 미완성 ZIP을 덮기 전에 현재 실행에서 새로 만든다.
    if zip_path.exists():
        zip_path.unlink()
    # 실행기에 필요한 모듈 파일을 명시적으로 열거해 불필요한 실험 코드가 섞이지 않게 한다.
    package_dir = Path(__file__).resolve().parent
    code_files = (
        package_dir.parent / "__init__.py",
        package_dir / "__init__.py",
        package_dir / "config.py",
        package_dir / "run_qwen4_three_corpora.py",
        package_dir / "requirements-runpod.txt",
        package_dir / "runpod_execute_qwen4_three_corpora.sh",
        package_dir / "실행안내.md",
    )
    # ZIP을 새로 열어 모든 내부 경로를 Linux POSIX 형식으로 기록한다.
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        # Python 패키지와 셸 실행 파일을 프로젝트 상대 경로로 넣는다.
        for source in code_files:
            if not source.is_file():
                raise FileNotFoundError(f"RunPod 코드 파일이 없습니다: {source}")
            relative = source.relative_to(PROJECT_ROOT).as_posix()
            add_zip_file(archive, source, relative, executable=source.suffix == ".sh")
        # 동결 입력은 ZIP 최상위 runpod_input 아래에 상대 구조를 유지한다.
        for source in sorted(path for path in snapshot_root.rglob("*") if path.is_file()):
            relative = source.relative_to(snapshot_root).as_posix()
            add_zip_file(archive, source, f"runpod_input/{relative}")
    # 생성 직후 Python 표준 검사를 실행해 중앙 디렉터리·CRC 오류를 차단한다.
    with zipfile.ZipFile(zip_path, "r") as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise ValueError(f"ZIP CRC 검사 실패: {bad_member}")
        names = archive.namelist()
        if any("\\" in name or name.startswith("/") or ".." in Path(name).parts for name in names):
            raise ValueError("ZIP 내부에 Linux 비호환 또는 경로 탈출 항목이 있습니다.")
    return zip_path


def build_markdown_report(run_id: str, manifest: dict[str, Any], zip_path: Path) -> str:
    """입력 감사 결과를 사용자가 확인할 수 있는 한국어 Markdown으로 만든다."""

    # 코퍼스별 핵심 건수와 해시 결과를 한눈에 볼 수 있는 표 행을 만든다.
    rows = []
    for key in ("fault_standard", "review_case", "precedent"):
        item = manifest["corpora"][key]
        rows.append(
            f"| {key} | {item['source_document_count']:,} | {item['embedding_unit_count']:,} | "
            f"{item['database_validation']['target_id_count']:,} | PASS |"
        )
    # 계획서와 같은 용어를 사용해 감사 범위·보안·다음 행동을 명시한다.
    return "\n".join(
        [
            "# 단계 6 Qwen 4B 운영 재색인 입력 검증",
            "",
            f"- 실행 ID: `{run_id}`",
            f"- 생성 시각(UTC): `{manifest['created_at']}`",
            f"- 모델: `{MODEL_NAME}`",
            f"- 리비전: `{MODEL_REVISION}`",
            f"- 차원: `{MODEL_DIMENSION}`",
            "- 판정: **RunPod 업로드 가능**",
            "",
            "## 코퍼스별 검증 결과",
            "",
            "| 코퍼스 | 상위 문서 | 임베딩 단위 | 단계 5 DB 검색 단위 | 판정 |",
            "|---|---:|---:|---:|---|",
            *rows,
            "",
            "## 평가자료",
            "",
            "- 공통 승인 질문 50개: ID·승인 상태·본문 검증 PASS",
            "- 인정기준 Complete30 질문·정답 30개: ID·입력 해시 검증 PASS",
            "- 세 코퍼스 qrels: 공통 질문 50개 coverage와 실제 문서·청크 연결 검증 PASS",
            "- qrels와 정답지는 RunPod ZIP에 포함하지 않음",
            "",
            "## RunPod 번들",
            "",
            f"- 파일: `{zip_path.name}`",
            f"- SHA-256: `{sha256_file(zip_path)}`",
            "- ZIP CRC·Linux `/` 경로·경로 탈출 검사 PASS",
            "- `.env`, API 키, DB 비밀번호 포함 없음",
            "",
            "## 다음 단계",
            "",
            "RunPod Jupyter의 `/workspace`에 ZIP을 업로드한 뒤 `실행안내.md`의 단일 명령을 실행한다. "
            "반환 tar.gz는 로컬 검증을 통과하기 전까지 운영 DB에 적재하지 않는다.",
            "",
        ]
    )


def execute(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    """전체 입력 감사·동결·ZIP 생성 절차를 실행하고 산출물 경로를 반환한다."""

    # 파일명과 manifest에 사용할 실행 ID를 먼저 검증한다.
    run_id = safe_run_id(args.run_id)
    # 같은 실행 ID의 미완성 입력이 섞이지 않도록 해당 실행 폴더만 새로 만든다.
    run_root = STAGE6_ARTIFACT_ROOT / f"run_{run_id}"
    snapshot_root = run_root / "00_frozen_input"
    if run_root.exists():
        shutil.rmtree(run_root)
    snapshot_root.mkdir(parents=True, exist_ok=True)
    # 정답을 제외한 두 질문 세트를 검증하고 스냅샷으로 기록한다.
    common_queries, common_query_ids, common_audit = validate_common_queries()
    complete30_queries, complete30_audit = validate_complete30_queries()
    write_jsonl(snapshot_root / "evaluation_queries" / "common_queries_50.jsonl", common_queries)
    write_jsonl(snapshot_root / "evaluation_queries" / "fault_standard_complete30_queries.jsonl", complete30_queries)
    # 전체 manifest에 모델 계약과 코퍼스별 감사 결과를 순서대로 채운다.
    manifest: dict[str, Any] = {
        "schema_version": "qwen4_operational_stage6_input_v1",
        "run_id": run_id,
        "created_at": utc_now(),
        "model": {
            "name": MODEL_NAME,
            "revision": MODEL_REVISION,
            "dimension": MODEL_DIMENSION,
            "normalization": NORMALIZATION,
        },
        "evaluation": {"common50": common_audit, "complete30": complete30_audit},
        "corpora": {},
        "contains_qrels_or_answers": False,
        "contains_secrets": False,
    }
    # 세 코퍼스를 각 전용 변환기로 감사하고 표준 검색 단위 JSONL을 만든다.
    for source in CORPUS_SOURCES:
        if source.key == "fault_standard":
            records, source_document_ids, audit = build_fault_standard_rows(source)
        elif source.key == "review_case":
            records, source_document_ids, audit = build_review_case_rows(source)
        elif source.key == "precedent":
            records, source_document_ids, audit = build_precedent_rows(source)
        else:
            raise ValueError(f"지원하지 않는 코퍼스입니다: {source.key}")
        # 계획서 고정 건수와 실제 상위 문서·검색 단위 건수를 엄격히 비교한다.
        expected = EXPECTED_COUNTS[source.key]
        if len(source_document_ids) != expected["source_documents"] or len(records) != expected["embedding_units"]:
            raise ValueError(
                f"{source.key}: 예상 건수 불일치, 문서={len(source_document_ids)}, 검색단위={len(records)}"
            )
        # qrels가 현재 운영 문서·청크에 연결되는지 로컬에서만 검증한다.
        qrels_audit = validate_qrels(
            source,
            common_query_ids,
            {str(row["target_id"]) for row in records},
            source_document_ids,
        )
        # 단계 5 DB의 ID와 임베딩 입력 해시가 현재 원본과 같은지 읽기 전용으로 대조한다.
        database_audit = verify_stage5_database(source, records, source_document_ids, args.postgres_container)
        # 표준 검색 단위를 코퍼스별 독립 디렉터리에 기록한다.
        target_path = snapshot_root / source.key / "embedding_units.jsonl"
        written = write_jsonl(target_path, records)
        if written != len(records):
            raise RuntimeError(f"{source.key}: 스냅샷 기록 행 수가 메모리 행 수와 다릅니다.")
        # 원본 파일 해시와 스냅샷 해시를 전체 manifest에 남긴다.
        manifest["corpora"][source.key] = {
            "target_type": source.target_type,
            "source_document_count": len(source_document_ids),
            "embedding_unit_count": len(records),
            "embedding_unit_snapshot": f"{source.key}/embedding_units.jsonl",
            "embedding_unit_snapshot_sha256": sha256_file(target_path),
            "source_files": {
                path.relative_to(PROJECT_ROOT).as_posix(): sha256_file(path)
                for path in (*source.source_document_paths, *((source.embedding_unit_path,) if source.embedding_unit_path else ()))
            },
            "query_instruction": QUERY_INSTRUCTIONS[source.key],
            "length_summary": record_length_summary(records),
            "upstream_audit": audit,
            "qrels_validation": qrels_audit,
            "database_validation": database_audit,
        }
    # 질문 스냅샷 해시를 별도 필드로 추가해 RunPod 결과와 직접 연결한다.
    manifest["evaluation"]["common50"]["snapshot_sha256"] = sha256_file(
        snapshot_root / "evaluation_queries" / "common_queries_50.jsonl"
    )
    manifest["evaluation"]["complete30"]["snapshot_sha256"] = sha256_file(
        snapshot_root / "evaluation_queries" / "fault_standard_complete30_queries.jsonl"
    )
    # manifest를 먼저 기록한 뒤 스냅샷 전체 체크섬 파일을 만든다.
    manifest_path = snapshot_root / "input_manifest.json"
    write_json(manifest_path, manifest)
    checksum_targets = sorted(path for path in snapshot_root.rglob("*") if path.is_file())
    checksum_lines = [f"{sha256_file(path)}  {path.relative_to(snapshot_root).as_posix()}" for path in checksum_targets]
    (snapshot_root / "CHECKSUMS_SHA256.txt").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8", newline="\n")
    # 코드와 입력이 모두 준비된 뒤 최종 RunPod ZIP을 만들고 감사 보고서를 기록한다.
    zip_path = build_zip(snapshot_root, run_id)
    report_path = (
        FAULT_CASES_ROOT
        / "Fault_cases_MD"
        / "재구조화_이관관리"
        / "06_Qwen4_운영재색인_입력검증.md"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(build_markdown_report(run_id, manifest, zip_path), encoding="utf-8", newline="\n")
    # ZIP 자체 해시와 경로를 로컬 run manifest에 추가로 기록한다.
    local_manifest_path = run_root / "01_bundle_manifest.json"
    write_json(
        local_manifest_path,
        {
            "run_id": run_id,
            "created_at": utc_now(),
            "input_manifest_sha256": sha256_file(manifest_path),
            "zip_path": zip_path.relative_to(FAULT_CASES_ROOT).as_posix(),
            "zip_sha256": sha256_file(zip_path),
            "zip_size_bytes": zip_path.stat().st_size,
            "report_path": report_path.relative_to(FAULT_CASES_ROOT).as_posix(),
            "status": "RUNPOD_UPLOAD_READY",
        },
    )
    return zip_path, report_path, local_manifest_path


def parser() -> argparse.ArgumentParser:
    """단계 6 입력 감사기의 명령행 계약을 반환한다."""

    # 사용자가 한 실행을 재현할 수 있도록 실행 ID를 필수 인자로 요구한다.
    command = argparse.ArgumentParser(description="Qwen 4B 운영 재색인 입력을 감사하고 RunPod ZIP을 생성합니다.")
    command.add_argument("--run-id", required=True, help="예: qwen4_operational_20260721_v1")
    command.add_argument(
        "--postgres-container",
        default="skn27-postgres",
        help="단계 5 DB 읽기 검증에 사용할 PostgreSQL 컨테이너 이름",
    )
    return command


def main() -> int:
    """명령행을 실행하고 성공 산출물 또는 안전한 오류를 출력한다."""

    # 예상 오류를 한국어 한 줄로 전달하고 비밀정보가 포함된 추적은 기본 출력하지 않는다.
    try:
        zip_path, report_path, manifest_path = execute(parser().parse_args())
    except Exception as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    # 사용자가 업로드할 파일과 검증 문서 위치를 명확히 출력한다.
    print(f"RunPod ZIP 생성 완료: {zip_path}")
    print(f"입력 검증 보고서: {report_path}")
    print(f"로컬 번들 manifest: {manifest_path}")
    print(f"ZIP SHA-256: {sha256_file(zip_path)}")
    return 0


if __name__ == "__main__":
    # 모듈 직접 실행 시 main의 성공·실패 코드를 운영체제에 전달한다.
    raise SystemExit(main())
