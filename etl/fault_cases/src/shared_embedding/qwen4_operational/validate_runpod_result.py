"""RunPod에서 받은 Qwen 4B 결과 tar.gz를 DB 적재 전에 전수 검증한다.

압축 경로 안전성, 내부 체크섬, 고정 모델 계약, 입력 ID·해시, 벡터 차원·유한값·L2 norm을
검사한다. 이 모듈은 PostgreSQL을 연결하거나 변경하지 않는다.
"""

from __future__ import annotations

import argparse  # 결과 압축·실행 ID·동결 입력 경로를 명령행으로 받는다.
import json  # manifest와 JSONL·metadata_json을 읽고 보고서를 쓴다.
import shutil  # 안전 검증을 통과한 일반 파일을 격리 디렉터리로 복사한다.
import sys  # 오류 메시지와 종료 코드를 운영체제에 반환한다.
import tarfile  # tar.gz 멤버를 추출 전 검사하고 일반 파일만 해제한다.
from pathlib import Path, PurePosixPath  # 실제 경로와 tar 내부 POSIX 경로를 분리한다.
from typing import Any, Sequence  # 검증 함수의 입력 계약을 명시한다.

from .config import (  # 로컬 빌더·RunPod 실행기와 동일한 모델·건수 계약을 사용한다.
    EXPECTED_COUNTS,
    FAULT_CASES_ROOT,
    MODEL_DIMENSION,
    MODEL_NAME,
    MODEL_REVISION,
    NORMALIZATION,
    QUERY_INSTRUCTIONS,
    STAGE6_ARTIFACT_ROOT,
)
from .run_qwen4_three_corpora import (  # 이미 검증된 공통 해시·JSON·벡터 검사 함수를 재사용한다.
    CORPUS_OUTPUT_NAMES,
    read_json,
    read_jsonl,
    sha256_file,
    sha256_text,
    utc_now,
    validate_run_id,
    validate_vectors,
)


# 정상 결과보다 충분히 크되 압축 폭탄을 제한할 수 있는 전체 해제 상한이다.
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024
# 정상 결과 파일 수보다 넉넉한 상한으로 비정상 대량 파일 생성을 차단한다.
MAX_ARCHIVE_FILES = 2000


def safe_archive_members(archive: tarfile.TarFile, expected_root_name: str) -> list[tarfile.TarInfo]:
    """tar 멤버의 경로·유형·크기·최상위 폴더를 검사해 일반 파일 목록을 반환한다."""

    # 전체 멤버를 한 번만 읽어 이후 추출 대상이 검사 결과와 달라지지 않게 한다.
    members = archive.getmembers()
    if len(members) > MAX_ARCHIVE_FILES:
        raise ValueError(f"tar.gz 파일 항목이 너무 많습니다: {len(members)}")
    regular_files: list[tarfile.TarInfo] = []
    total_size = 0
    for member in members:
        pure = PurePosixPath(member.name)
        # 절대경로·상위 이동·빈 최상위 경로는 경로 탈출 위험이 있으므로 차단한다.
        if pure.is_absolute() or ".." in pure.parts or not pure.parts:
            raise ValueError(f"안전하지 않은 tar 경로입니다: {member.name}")
        if pure.parts[0] != expected_root_name:
            raise ValueError(f"예상하지 않은 tar 최상위 폴더입니다: {member.name}")
        # 심볼릭 링크·하드링크·장치 파일은 격리 디렉터리 밖을 덮을 수 있어 금지한다.
        if member.issym() or member.islnk() or member.isdev() or member.isfifo():
            raise ValueError(f"tar.gz에 허용하지 않는 파일 유형이 있습니다: {member.name}")
        # 일반 파일과 디렉터리 외의 특수 유형도 모두 차단한다.
        if not member.isfile() and not member.isdir():
            raise ValueError(f"tar.gz에 알 수 없는 파일 유형이 있습니다: {member.name}")
        if member.isfile():
            total_size += int(member.size)
            regular_files.append(member)
    if total_size > MAX_EXTRACTED_BYTES:
        raise ValueError(f"tar.gz 해제 예상 크기가 2GiB를 넘습니다: {total_size}")
    return regular_files


def extract_regular_files(archive_path: Path, target_root: Path, run_id: str) -> Path:
    """검사된 tar 일반 파일만 새 격리 디렉터리에 안전하게 추출한다."""

    # 같은 압축 파일은 해시 기반 디렉터리로 분리해 다른 결과와 섞이지 않게 한다.
    archive_hash = sha256_file(archive_path)
    receipt_root = target_root / archive_hash[:16]
    if receipt_root.exists():
        raise FileExistsError(f"동일 SHA 결과의 수신 폴더가 이미 있습니다: {receipt_root}")
    receipt_root.mkdir(parents=True, exist_ok=False)
    expected_root_name = f"qwen4_three_corpus_operational_{run_id}"
    # tar 스트림을 열고 모든 멤버가 안전한지 확인한 뒤 파일을 하나씩 복사한다.
    with tarfile.open(archive_path, "r:gz") as archive:
        members = safe_archive_members(archive, expected_root_name)
        for member in members:
            pure = PurePosixPath(member.name)
            destination = receipt_root.joinpath(*pure.parts)
            # resolve 결과가 수신 루트 안인지 재검사해 운영체제 경로 처리 차이를 차단한다.
            resolved_destination = destination.resolve()
            if receipt_root.resolve() not in resolved_destination.parents:
                raise ValueError(f"tar 추출 경로가 격리 루트를 벗어납니다: {member.name}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"tar 일반 파일 내용을 읽을 수 없습니다: {member.name}")
            # 파일 객체를 직접 복사하고 tarfile.extractall은 사용하지 않는다.
            with source, destination.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
    return receipt_root / expected_root_name


def verify_result_checksums(result_root: Path) -> dict[str, str]:
    """결과 CHECKSUMS_SHA256.txt의 모든 파일을 실제 바이트와 대조한다."""

    # 체크섬 파일은 RunPod 패키징 완료의 필수 증거다.
    checksum_path = result_root / "CHECKSUMS_SHA256.txt"
    if not checksum_path.is_file():
        raise FileNotFoundError("결과 CHECKSUMS_SHA256.txt가 없습니다.")
    verified: dict[str, str] = {}
    for line_number, line in enumerate(checksum_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            expected, relative = line.split("  ", 1)
        except ValueError as error:
            raise ValueError(f"결과 체크섬 형식 오류: {line_number}행") from error
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError(f"결과 체크섬에 안전하지 않은 경로가 있습니다: {relative}")
        path = result_root.joinpath(*pure.parts)
        if not path.is_file():
            raise FileNotFoundError(f"결과 체크섬 대상 파일이 없습니다: {relative}")
        actual = sha256_file(path)
        if actual != expected:
            raise ValueError(f"결과 파일 SHA-256 불일치: {relative}")
        verified[relative] = actual
    # 체크섬 목록에 없는 숨은 파일이 있으면 미검증 결과가 섞인 것이므로 차단한다.
    actual_files = {
        path.relative_to(result_root).as_posix()
        for path in result_root.rglob("*")
        if path.is_file() and path != checksum_path
    }
    if actual_files != set(verified):
        missing = sorted(actual_files - set(verified))[:5]
        extra = sorted(set(verified) - actual_files)[:5]
        raise ValueError(f"결과 체크섬 파일 목록 불일치, 미기록={missing}, 없는항목={extra}")
    return verified


def validate_parquet_against_expected(
    path: Path,
    expected_ids: Sequence[str],
    expected_hashes: Sequence[str],
    label: str,
) -> dict[str, Any]:
    """Parquet ID·입력 해시·벡터를 동결 입력과 전수 대조한다."""

    import pyarrow as pa  # Parquet vector 열의 고정 길이와 float32 dtype을 검사한다.
    import pyarrow.parquet as pq  # 결과를 row group 단위로 읽어 메모리 사용량을 제한한다.

    # 대형 판례 벡터를 Python 객체로 한꺼번에 펼치지 않고 128행씩 전수 검사한다.
    parquet = pq.ParquetFile(path)
    vector_type = parquet.schema_arrow.field("vector").type
    if not pa.types.is_fixed_size_list(vector_type) or vector_type.list_size != MODEL_DIMENSION:
        raise ValueError(f"{label}: vector 열이 고정 {MODEL_DIMENSION}차원 list가 아닙니다: {vector_type}")
    if not pa.types.is_float32(vector_type.value_type):
        raise ValueError(f"{label}: vector 값 dtype이 float32가 아닙니다: {vector_type.value_type}")
    ids: list[str] = []
    hashes: list[str] = []
    minimum_norm = float("inf")
    maximum_norm = 0.0
    for batch in parquet.iter_batches(
        batch_size=128,
        columns=["id", "embedding_input_sha256", "metadata_json", "vector"],
    ):
        rows = batch.to_pylist()
        ids.extend(str(row["id"]) for row in rows)
        hashes.extend(str(row["embedding_input_sha256"]) for row in rows)
        for row in rows:
            try:
                metadata = json.loads(str(row["metadata_json"]))
            except json.JSONDecodeError as error:
                raise ValueError(f"{label}: metadata_json 파싱 실패: {row['id']}") from error
            metadata_id = str(metadata.get("target_id") or metadata.get("query_id") or "")
            if metadata_id != str(row["id"]):
                raise ValueError(f"{label}: metadata_json ID가 결과 ID와 다릅니다: {row['id']}")
        vector_audit = validate_vectors([row["vector"] for row in rows], label)
        minimum_norm = min(minimum_norm, vector_audit["minimum_norm"])
        maximum_norm = max(maximum_norm, vector_audit["maximum_norm"])
    if ids != list(expected_ids) or len(set(ids)) != len(ids):
        raise ValueError(f"{label}: 결과 ID 순서·집합·중복 검증 실패")
    if hashes != list(expected_hashes):
        raise ValueError(f"{label}: 결과 임베딩 입력 SHA-256 불일치")
    return {
        "row_count": len(ids),
        "dimension": MODEL_DIMENSION,
        "minimum_norm": minimum_norm,
        "maximum_norm": maximum_norm,
        "parquet_sha256": sha256_file(path),
    }


def expected_document_contract(input_root: Path, corpus_key: str) -> tuple[list[str], list[str]]:
    """동결 문서·청크 입력에서 예상 ID와 입력 해시 목록을 반환한다."""

    # RunPod에 보낸 바로 그 snapshot만 정답으로 사용하고 현재 원본을 다시 추측하지 않는다.
    rows = read_jsonl(input_root / corpus_key / "embedding_units.jsonl")
    return (
        [str(row["target_id"]) for row in rows],
        [str(row["embedding_input_sha256"]) for row in rows],
    )


def expected_query_contract(input_root: Path, dataset: str, corpus_key: str) -> tuple[list[str], list[str]]:
    """동결 질문과 코퍼스별 instruction으로 예상 질의 ID·입력 해시를 재구성한다."""

    # 공통 50과 Complete30의 서로 다른 입력 파일을 명시적으로 선택한다.
    if dataset == "common50":
        path = input_root / "evaluation_queries" / "common_queries_50.jsonl"
    elif dataset == "complete30" and corpus_key == "fault_standard":
        path = input_root / "evaluation_queries" / "fault_standard_complete30_queries.jsonl"
    else:
        raise ValueError(f"지원하지 않는 질문 결과입니다: {dataset}/{corpus_key}")
    rows = read_jsonl(path)
    instruction = QUERY_INSTRUCTIONS[corpus_key]
    ids = [str(row["query_id"]) for row in rows]
    hashes = [sha256_text(instruction + str(row["query_text"]).strip()) for row in rows]
    return ids, hashes


def validate_result(
    archive_path: Path,
    run_id: str,
    input_root: Path,
    receipt_parent: Path,
) -> tuple[Path, dict[str, Any]]:
    """결과 압축을 안전 해제하고 모든 실행·입력·벡터 계약을 검증한다."""

    # 파일명과 경로가 안전한지 확인한 뒤 원본 압축 해시를 먼저 기록한다.
    validate_run_id(run_id)
    if not archive_path.is_file():
        raise FileNotFoundError(f"RunPod 결과 tar.gz가 없습니다: {archive_path}")
    archive_hash = sha256_file(archive_path)
    # 검사된 일반 파일만 해제한 뒤 내부 체크섬을 전수 대조한다.
    result_root = extract_regular_files(archive_path, receipt_parent, run_id)
    verified_checksums = verify_result_checksums(result_root)
    # 로컬 동결 입력 manifest와 RunPod 실행 manifest를 같은 해시로 연결한다.
    local_input_manifest = read_json(input_root / "input_manifest.json")
    local_input_manifest_hash = sha256_file(input_root / "input_manifest.json")
    run_manifest = read_json(result_root / "run_manifest.json")
    expected_run = {
        "status": "COMPLETE",
        "run_id": run_id,
        "model_name": MODEL_NAME,
        "model_revision": MODEL_REVISION,
        "dimension": MODEL_DIMENSION,
        "normalization": NORMALIZATION,
        "input_manifest_sha256": local_input_manifest_hash,
    }
    for key, expected in expected_run.items():
        if run_manifest.get(key) != expected:
            raise ValueError(f"run_manifest 계약 불일치: {key}={run_manifest.get(key)!r}, 예상={expected!r}")
    # 세 코퍼스 운영 문서·청크 Parquet을 동결 입력과 대조한다.
    corpus_results: dict[str, Any] = {}
    for corpus_key, expected_count in EXPECTED_COUNTS.items():
        ids, hashes = expected_document_contract(input_root, corpus_key)
        path = result_root / corpus_key / CORPUS_OUTPUT_NAMES[corpus_key]
        audit = validate_parquet_against_expected(path, ids, hashes, f"문서/{corpus_key}")
        if audit["row_count"] != expected_count["embedding_units"]:
            raise ValueError(f"{corpus_key}: 예상 운영 벡터 건수와 다릅니다.")
        artifact = read_json(result_root / corpus_key / "artifact_manifest.json")
        if artifact.get("output_sha256") != audit["parquet_sha256"]:
            raise ValueError(f"{corpus_key}: artifact manifest의 Parquet SHA-256이 다릅니다.")
        if (
            artifact.get("model_revision") != MODEL_REVISION
            or artifact.get("native_dimension") != MODEL_DIMENSION
            or artifact.get("dtype") != "float32"
        ):
            raise ValueError(f"{corpus_key}: artifact 모델 계약이 다릅니다.")
        corpus_results[corpus_key] = audit
    # 공통 50의 코퍼스별 세 결과와 Complete30 인정기준 결과를 각각 검사한다.
    query_results: dict[str, Any] = {}
    for corpus_key in ("fault_standard", "review_case", "precedent"):
        ids, hashes = expected_query_contract(input_root, "common50", corpus_key)
        path = result_root / "evaluation_queries" / "common50" / corpus_key / "query_embeddings.parquet"
        query_results[f"common50/{corpus_key}"] = validate_parquet_against_expected(
            path, ids, hashes, f"질문/common50/{corpus_key}"
        )
    complete_ids, complete_hashes = expected_query_contract(input_root, "complete30", "fault_standard")
    complete_path = (
        result_root / "evaluation_queries" / "complete30" / "fault_standard" / "query_embeddings.parquet"
    )
    query_results["complete30/fault_standard"] = validate_parquet_against_expected(
        complete_path, complete_ids, complete_hashes, "질문/complete30/fault_standard"
    )
    # DB 적재 승인 판단에 필요한 핵심 결과를 기계 판독 가능한 객체로 만든다.
    audit = {
        "schema_version": "qwen4_operational_receipt_validation_v1",
        "validated_at": utc_now(),
        "status": "PASS",
        "database_mutated": False,
        "run_id": run_id,
        "archive_path": str(archive_path),
        "archive_sha256": archive_hash,
        "result_root": str(result_root),
        "input_manifest_sha256": local_input_manifest_hash,
        "model": local_input_manifest["model"],
        "verified_file_count": len(verified_checksums),
        "corpora": corpus_results,
        "evaluation_queries": query_results,
        "next_gate": "STAGING_LOAD_ALLOWED",
    }
    return result_root, audit


def markdown_report(audit: dict[str, Any]) -> str:
    """RunPod 수신 검증 결과를 한국어 Markdown으로 반환한다."""

    # 세 코퍼스의 건수·차원·norm을 표 행으로 구성한다.
    rows = []
    for corpus_key in ("fault_standard", "review_case", "precedent"):
        item = audit["corpora"][corpus_key]
        rows.append(
            f"| {corpus_key} | {item['row_count']:,} | {item['dimension']} | "
            f"{item['minimum_norm']:.6f}~{item['maximum_norm']:.6f} | PASS |"
        )
    return "\n".join(
        [
            "# 단계 6 RunPod Qwen 4B 결과 수신 검증",
            "",
            f"- 실행 ID: `{audit['run_id']}`",
            f"- 결과 압축 SHA-256: `{audit['archive_sha256']}`",
            f"- 검증 파일 수: `{audit['verified_file_count']}`",
            "- 운영 DB 변경: **없음**",
            "- 판정: **PASS — staging 적재 가능**",
            "",
            "| 코퍼스 | 벡터 수 | 차원 | L2 norm 범위 | 판정 |",
            "|---|---:|---:|---:|---|",
            *rows,
            "",
            "공통 50문항의 코퍼스별 질문 벡터 3종과 인정기준 Complete30 질문 벡터도 "
            "동결 입력 ID·instruction 포함 입력 해시 기준으로 전수 검증했다.",
            "",
        ]
    )


def parser() -> argparse.ArgumentParser:
    """RunPod 결과 수신 검증기의 명령행 계약을 반환한다."""

    # 결과 압축과 정확히 대응하는 로컬 동결 입력을 필수 인자로 받는다.
    command = argparse.ArgumentParser(description="RunPod Qwen 4B 결과 tar.gz를 DB 적재 전에 전수 검증합니다.")
    command.add_argument("--archive", required=True)
    command.add_argument("--run-id", required=True)
    command.add_argument("--input-root", required=True)
    command.add_argument(
        "--receipt-parent",
        default=str(STAGE6_ARTIFACT_ROOT / "received"),
        help="안전검사 후 결과를 해제할 격리 상위 폴더",
    )
    return command


def main() -> int:
    """결과를 검증하고 JSON·Markdown 감사 산출물을 기록한다."""

    # 오류 시 DB를 건드리지 않았음을 유지하고 비밀 없는 메시지만 출력한다.
    try:
        args = parser().parse_args()
        result_root, audit = validate_result(
            Path(args.archive).resolve(),
            args.run_id,
            Path(args.input_root).resolve(),
            Path(args.receipt_parent).resolve(),
        )
        # 수신 결과 루트와 공식 단계 6 문서 폴더에 각각 감사 결과를 기록한다.
        json_path = result_root / "local_receipt_validation.json"
        json_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        report_path = (
            FAULT_CASES_ROOT
            / "Fault_cases_MD"
            / "재구조화_이관관리"
            / "06_Qwen4_운영재색인_RunPod결과검증.md"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(markdown_report(audit), encoding="utf-8", newline="\n")
    except Exception as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    print(f"RunPod 결과 검증 PASS: {result_root}")
    print(f"수신 검증 JSON: {json_path}")
    print(f"수신 검증 보고서: {report_path}")
    print("다음 단계: 세 운영 DB staging 적재 가능")
    return 0


if __name__ == "__main__":
    # 모듈 직접 실행 시 main의 성공·실패 코드를 운영체제에 반환한다.
    raise SystemExit(main())
