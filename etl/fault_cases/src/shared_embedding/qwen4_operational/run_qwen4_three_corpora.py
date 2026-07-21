"""RunPod에서 세 코퍼스와 평가 질문을 Qwen 4B로 한 번에 임베딩한다.

문서·청크 결과는 코퍼스별로 분리하고, 고정 크기 shard를 사용해 중단 후 재개한다.
세 코퍼스 전체 검증이 끝나야 COMPLETE manifest와 최종 tar.gz를 만들 수 있다.
"""

from __future__ import annotations

import argparse  # 실행·패키징 하위 명령과 경로·배치 인자를 정의한다.
import hashlib  # 입력·출력 파일과 실제 모델 입력 문자열의 SHA-256을 계산한다.
import json  # manifest와 JSONL 입력을 읽고 쓴다.
import math  # 벡터 유한값과 L2 norm을 검증한다.
import os  # CUDA 메모리 설정과 런타임 환경 정보를 읽는다.
import platform  # Python·운영체제 정보를 실행 manifest에 기록한다.
import shutil  # 완료 후 임시 파일을 정리하지 않고 디스크 여유만 검사하는 데 사용한다.
import sys  # 안전한 오류 메시지와 종료 코드를 반환한다.
import tarfile  # 검증 완료 결과를 단일 tar.gz로 패키징한다.
import time  # 코퍼스별 처리 시간과 배치 지연을 측정한다.
from datetime import datetime, timezone  # 모든 실행 시각을 UTC로 통일한다.
from pathlib import Path, PurePosixPath  # 로컬 경로와 manifest용 POSIX 경로를 분리한다.
from typing import Any, Iterable, Iterator, Sequence  # 함수 입출력 계약을 명시한다.

from .config import (  # 로컬 빌더와 동일한 승인 모델·건수·질의 지시문을 사용한다.
    EXPECTED_COUNTS,
    MODEL_DIMENSION,
    MODEL_NAME,
    MODEL_REVISION,
    NORMALIZATION,
    QUERY_INSTRUCTIONS,
)


# 세 코퍼스는 운영 검색 단위와 출력 파일 이름을 서로 다르게 유지한다.
CORPUS_OUTPUT_NAMES = {
    "fault_standard": "document_embeddings.parquet",
    "review_case": "chunk_embeddings.parquet",
    "precedent": "chunk_embeddings.parquet",
}


def utc_now() -> str:
    """현재 UTC 시각을 ISO-8601 문자열로 반환한다."""

    # RunPod 지역과 로컬 한국 시간의 혼동을 없애기 위해 UTC만 사용한다.
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_text(value: str) -> str:
    """UTF-8 문자열의 SHA-256을 반환한다."""

    # 모델에 실제로 전달한 지시문 포함 문자열을 해시로 고정한다.
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    """파일 전체를 1MiB 블록으로 읽어 SHA-256을 반환한다."""

    # 대형 Parquet도 메모리에 모두 적재하지 않도록 누적 해시를 준비한다.
    digest = hashlib.sha256()
    # 줄바꿈 변환이 없는 바이너리 모드로 파일을 읽는다.
    with path.open("rb") as handle:
        # 파일 끝까지 1MiB 단위로 해시를 갱신한다.
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    """키 순서와 공백이 고정된 JSON 문자열을 반환한다."""

    # metadata_json과 manifest 비교가 실행마다 달라지지 않도록 키를 정렬한다.
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_json(path: Path) -> dict[str, Any]:
    """UTF-8 JSON 파일을 객체로 읽고 형식을 검증한다."""

    # manifest가 없으면 다른 입력을 추측하지 않고 즉시 중단한다.
    if not path.is_file():
        raise FileNotFoundError(f"JSON 파일이 없습니다: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    # 최상위 배열은 현재 manifest 계약이 아니므로 거부한다.
    if not isinstance(value, dict):
        raise ValueError(f"JSON 최상위 값이 객체가 아닙니다: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    """한국어를 보존한 들여쓰기 JSON 파일을 기록한다."""

    # 중첩 결과 폴더를 먼저 준비한다.
    path.parent.mkdir(parents=True, exist_ok=True)
    # 사람이 직접 검수할 수 있도록 UTF-8·키 정렬·들여쓰기 형식을 사용한다.
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """UTF-8 JSONL 전체를 행 순서를 유지해 읽는다."""

    # RunPod 입력 ZIP이 불완전하면 모델을 다운로드하기 전에 중단한다.
    if not path.is_file():
        raise FileNotFoundError(f"JSONL 파일이 없습니다: {path}")
    rows: list[dict[str, Any]] = []
    # 한국어 텍스트를 손상시키지 않도록 UTF-8로 읽는다.
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            # 빈 줄은 입력 행으로 세지 않는다.
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"JSONL 파싱 실패: {path}, {line_number}행") from error
            if not isinstance(value, dict):
                raise ValueError(f"JSONL 행이 객체가 아닙니다: {path}, {line_number}행")
            rows.append(value)
    return rows


def validate_run_id(value: str) -> str:
    """실행 ID가 안전한 파일명 문자만 갖는지 확인한다."""

    # 셸·경로 주입을 막기 위해 영문·숫자·밑줄·하이픈만 허용한다.
    if not value or any(not (char.isalnum() or char in "_-") for char in value):
        raise ValueError("run-id는 영문·숫자·밑줄·하이픈만 사용할 수 있습니다.")
    return value


def verify_checksum_file(input_root: Path) -> dict[str, str]:
    """입력 CHECKSUMS 파일의 모든 항목을 실제 파일과 대조한다."""

    # 빌더가 만든 체크섬 파일을 유일한 입력 무결성 목록으로 사용한다.
    checksum_path = input_root / "CHECKSUMS_SHA256.txt"
    if not checksum_path.is_file():
        raise FileNotFoundError("입력 CHECKSUMS_SHA256.txt가 없습니다.")
    results: dict[str, str] = {}
    # 각 줄은 64자리 해시, 두 칸, POSIX 상대 경로 계약을 사용한다.
    for line_number, line in enumerate(checksum_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            expected, relative = line.split("  ", 1)
        except ValueError as error:
            raise ValueError(f"입력 체크섬 형식 오류: {line_number}행") from error
        pure = PurePosixPath(relative)
        # 절대경로와 상위 경로 이동 항목은 ZIP 경로 탈출 위험이 있으므로 차단한다.
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError(f"입력 체크섬에 안전하지 않은 경로가 있습니다: {relative}")
        path = input_root.joinpath(*pure.parts)
        if not path.is_file():
            raise FileNotFoundError(f"체크섬 대상 파일이 없습니다: {relative}")
        actual = sha256_file(path)
        if actual != expected:
            raise ValueError(f"입력 SHA-256 불일치: {relative}")
        results[relative] = actual
    return results


def validate_input_manifest(input_root: Path, run_id: str) -> dict[str, Any]:
    """입력 manifest의 실행 ID·모델·건수와 실제 JSONL을 검사한다."""

    # 체크섬을 먼저 확인해 손상된 manifest를 신뢰하지 않는다.
    verify_checksum_file(input_root)
    manifest = read_json(input_root / "input_manifest.json")
    if manifest.get("run_id") != run_id:
        raise ValueError(f"입력 manifest run_id가 다릅니다: {manifest.get('run_id')}")
    model = manifest.get("model") or {}
    # 모델 이름·commit·차원·정규화가 하나라도 다르면 새 실행 ID로 다시 만들어야 한다.
    expected_model = {
        "name": MODEL_NAME,
        "revision": MODEL_REVISION,
        "dimension": MODEL_DIMENSION,
        "normalization": NORMALIZATION,
    }
    if any(model.get(key) != value for key, value in expected_model.items()):
        raise ValueError(f"입력 manifest 모델 계약이 다릅니다: {model}")
    # 각 코퍼스 표준 입력의 행 수·ID·본문 해시를 모델 로드 전에 검사한다.
    for corpus_key, expected in EXPECTED_COUNTS.items():
        rows = read_jsonl(input_root / corpus_key / "embedding_units.jsonl")
        if len(rows) != expected["embedding_units"]:
            raise ValueError(f"{corpus_key}: 입력 행 수가 예상과 다릅니다: {len(rows)}")
        ids = [str(row.get("target_id") or "") for row in rows]
        if not all(ids) or len(set(ids)) != len(ids):
            raise ValueError(f"{corpus_key}: 비어 있거나 중복된 target_id가 있습니다.")
        for row in rows:
            text = str(row.get("embedding_text") or "")
            if not text.strip() or sha256_text(text) != row.get("embedding_input_sha256"):
                raise ValueError(f"{corpus_key}: 입력 텍스트 해시 오류: {row.get('target_id')}")
    # 질문지 건수와 텍스트 해시도 별도로 확인한다.
    query_contracts = (
        ("common50", input_root / "evaluation_queries" / "common_queries_50.jsonl", 50),
        ("complete30", input_root / "evaluation_queries" / "fault_standard_complete30_queries.jsonl", 30),
    )
    for label, path, expected_count in query_contracts:
        rows = read_jsonl(path)
        if len(rows) != expected_count:
            raise ValueError(f"{label}: 질문 행 수가 예상과 다릅니다: {len(rows)}")
        ids = [str(row.get("query_id") or "") for row in rows]
        if not all(ids) or len(set(ids)) != len(ids):
            raise ValueError(f"{label}: 비어 있거나 중복된 query_id가 있습니다.")
        if any(sha256_text(str(row.get("query_text") or "").strip()) != row.get("query_text_sha256") for row in rows):
            raise ValueError(f"{label}: 질문 텍스트 SHA-256 불일치가 있습니다.")
    return manifest


def version_tuple(value: str) -> tuple[int, ...]:
    """패키지 버전 문자열 앞부분을 비교 가능한 정수 튜플로 변환한다."""

    # `2.7.1+cu126`처럼 접미사가 있는 버전에서 숫자 부분만 안전하게 읽는다.
    numbers: list[int] = []
    for token in value.split("+")[0].split("."):
        digits = "".join(char for char in token if char.isdigit())
        if not digits:
            break
        numbers.append(int(digits))
    return tuple(numbers)


def collect_environment() -> dict[str, Any]:
    """GPU·Python·핵심 라이브러리 상태를 검사하고 비밀 없는 환경 정보를 반환한다."""

    # 대형 라이브러리는 RunPod 의존성 설치가 끝난 실행 시점에 가져온다.
    import pyarrow  # type: ignore
    import sentence_transformers  # type: ignore
    import torch  # type: ignore
    import transformers  # type: ignore

    # torch.load 보안 기준과 모델 호환성을 위해 2.6 미만은 실행하지 않는다.
    if version_tuple(torch.__version__) < (2, 6):
        raise RuntimeError(f"PyTorch 2.6 이상이 필요합니다: {torch.__version__}")
    # CPU로 수 시간 실행되는 실수를 막기 위해 CUDA 사용 가능 여부를 강제한다.
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU를 사용할 수 없습니다. RunPod GPU Pod에서 실행하세요.")
    # 현재 GPU의 총 VRAM을 bytes에서 GiB로 변환해 비용·OOM 분석에 남긴다.
    properties = torch.cuda.get_device_properties(0)
    total_vram_gib = float(properties.total_memory) / (1024**3)
    # 모델 캐시·입력·결과를 위한 여유 공간이 부족하면 다운로드 전에 중단한다.
    free_disk_gib = shutil.disk_usage("/workspace").free / (1024**3)
    if free_disk_gib < 20:
        raise RuntimeError(f"/workspace 여유 공간이 20GiB 미만입니다: {free_disk_gib:.2f}GiB")
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "sentence_transformers": sentence_transformers.__version__,
        "pyarrow": pyarrow.__version__,
        "cuda_runtime": torch.version.cuda,
        "gpu_name": torch.cuda.get_device_name(0),
        "gpu_total_vram_gib": round(total_vram_gib, 3),
        "workspace_free_disk_gib_before": round(free_disk_gib, 3),
        "pytorch_cuda_alloc_conf": os.environ.get("PYTORCH_CUDA_ALLOC_CONF", ""),
    }


def load_model() -> Any:
    """고정된 Hugging Face commit을 확인하고 Qwen 4B 모델을 CUDA에 로드한다."""

    # API 조회로 이름이 같은 이동 태그가 아니라 정확한 commit SHA인지 확인한다.
    from huggingface_hub import HfApi  # type: ignore
    from sentence_transformers import SentenceTransformer  # type: ignore

    model_info = HfApi().model_info(MODEL_NAME, revision=MODEL_REVISION)
    if str(model_info.sha) != MODEL_REVISION:
        raise RuntimeError(f"Hugging Face 모델 리비전이 다릅니다: {model_info.sha}")
    # revision과 원격 모델 코드를 고정해 동일한 가중치·pooling 구현을 로드한다.
    model = SentenceTransformer(
        MODEL_NAME,
        revision=MODEL_REVISION,
        trust_remote_code=True,
        device="cuda",
    )
    # 차원 축소 옵션 없이 모델 기본 출력이 2560인지 직접 확인한다.
    dimension = int(model.get_sentence_embedding_dimension() or 0)
    if dimension != MODEL_DIMENSION:
        raise RuntimeError(f"모델 출력 차원이 {MODEL_DIMENSION}이 아닙니다: {dimension}")
    return model


def audit_token_lengths(model: Any, jobs: Sequence[tuple[str, Sequence[str]]]) -> dict[str, Any]:
    """모든 실제 모델 입력을 truncation 없이 token화해 길이 초과를 차단한다."""

    # SentenceTransformer가 현재 모델에 적용하는 최대 입력 token 수를 읽는다.
    maximum = int(model.max_seq_length)
    if maximum <= 0:
        raise RuntimeError(f"모델 max_seq_length가 올바르지 않습니다: {maximum}")
    audit: dict[str, Any] = {"model_max_seq_length": maximum, "jobs": {}}
    # 대형 판례 입력도 128개씩 token화해 CPU 메모리 사용량을 제한한다.
    for label, texts in jobs:
        lengths: list[int] = []
        for start in range(0, len(texts), 128):
            encoded = model.tokenizer(
                list(texts[start : start + 128]),
                add_special_tokens=True,
                truncation=False,
                padding=False,
                return_length=True,
            )
            lengths.extend(int(value) for value in encoded["length"])
        # 단 한 건이라도 상한을 넘으면 조용한 truncation 대신 ID 단위 실행을 중단한다.
        over_limit = [index for index, length in enumerate(lengths) if length > maximum]
        if over_limit:
            raise ValueError(f"{label}: tokenizer 상한 {maximum}을 넘는 입력이 {len(over_limit)}건 있습니다.")
        ordered = sorted(lengths)
        audit["jobs"][label] = {
            "count": len(lengths),
            "maximum_tokens": max(lengths),
            "p95_tokens": ordered[min(len(ordered) - 1, int((len(ordered) - 1) * 0.95))],
            "over_limit_count": 0,
        }
    return audit


def prepare_document_rows(rows: Sequence[dict[str, Any]]) -> tuple[list[str], list[str], list[str], list[str]]:
    """문서·청크 입력에서 ID·텍스트·해시·metadata를 분리한다."""

    # 문서에는 질의 지시문을 붙이지 않고 동결된 embedding_text를 그대로 사용한다.
    ids = [str(row["target_id"]) for row in rows]
    texts = [str(row["embedding_text"]) for row in rows]
    hashes = [str(row["embedding_input_sha256"]) for row in rows]
    metadata = [canonical_json(row) for row in rows]
    return ids, texts, hashes, metadata


def prepare_query_rows(
    rows: Sequence[dict[str, Any]], corpus_key: str
) -> tuple[list[str], list[str], list[str], list[str]]:
    """질문 텍스트에 코퍼스별 Qwen 지시문을 붙여 실제 모델 입력을 만든다."""

    # 같은 질문도 검색 목적이 다르므로 코퍼스별 고정 instruction을 적용한다.
    prefix = QUERY_INSTRUCTIONS[corpus_key]
    ids = [str(row["query_id"]) for row in rows]
    texts = [prefix + str(row["query_text"]).strip() for row in rows]
    hashes = [sha256_text(text) for text in texts]
    metadata = [canonical_json({**row, "corpus_key": corpus_key, "query_instruction": prefix}) for row in rows]
    return ids, texts, hashes, metadata


def is_cuda_oom(error: BaseException) -> bool:
    """예외가 CUDA 메모리 부족 오류인지 문자열과 자료형으로 판정한다."""

    # 라이브러리 버전에 따라 RuntimeError 또는 OutOfMemoryError가 오므로 메시지도 함께 본다.
    return "cuda" in str(error).lower() and "out of memory" in str(error).lower()


def encode_with_fallback(model: Any, texts: Sequence[str], initial_batch_size: int) -> tuple[list[list[float]], int, float]:
    """OOM 시 batch를 절반으로 낮춰 L2 정규화 벡터를 생성한다."""

    import torch  # type: ignore

    # 사용자가 지정한 batch를 최대 32로 제한하고 최소 8까지 낮출 수 있게 한다.
    batch_size = min(32, max(8, int(initial_batch_size)))
    while True:
        started = time.perf_counter()
        try:
            # 차원 축소 없이 float32·정규화된 numpy 배열을 생성한다.
            encoded = model.encode(
                list(texts),
                batch_size=batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            vectors = [[float(value) for value in vector] for vector in encoded]
            return vectors, batch_size, elapsed_ms
        except BaseException as error:
            # OOM이 아닌 오류는 원인을 숨기지 않고 즉시 호출자에게 전달한다.
            if not is_cuda_oom(error):
                raise
            # batch 8에서도 실패하면 다른 데이터로 넘어가지 않고 명확히 중단한다.
            if batch_size <= 8:
                raise RuntimeError("CUDA OOM: batch 8에서도 임베딩할 수 없습니다.") from error
            # 실패 텐서를 해제하고 allocator cache를 비운 뒤 절반 batch로 같은 shard를 재시도한다.
            torch.cuda.empty_cache()
            batch_size = max(8, batch_size // 2)
            print(f"CUDA OOM 감지: batch를 {batch_size}로 낮춰 같은 shard를 재시도합니다.", flush=True)


def validate_vectors(vectors: Sequence[Sequence[float]], label: str) -> dict[str, float]:
    """벡터 차원·유한값·L2 norm을 검사하고 norm 범위를 반환한다."""

    # 빈 출력은 저장하지 않고 모델 실행 실패로 처리한다.
    if not vectors:
        raise ValueError(f"{label}: 벡터가 비어 있습니다.")
    norms: list[float] = []
    for vector in vectors:
        if len(vector) != MODEL_DIMENSION:
            raise ValueError(f"{label}: 벡터 차원이 다릅니다: {len(vector)}")
        if any(not math.isfinite(float(value)) for value in vector):
            raise ValueError(f"{label}: NaN 또는 Inf가 있습니다.")
        norm = math.sqrt(sum(float(value) * float(value) for value in vector))
        if not math.isclose(norm, 1.0, rel_tol=1e-3, abs_tol=1e-3):
            raise ValueError(f"{label}: L2 norm이 1이 아닙니다: {norm}")
        norms.append(norm)
    return {"minimum_norm": min(norms), "maximum_norm": max(norms)}


def shard_matches(path: Path, expected_ids: Sequence[str], expected_hashes: Sequence[str]) -> bool:
    """기존 shard가 현재 입력 ID·해시·차원과 완전히 같을 때만 재사용한다."""

    # 파일이 없으면 정상적인 미완료 상태로 보고 새로 생성한다.
    if not path.is_file():
        return False
    try:
        import pyarrow.parquet as pq  # type: ignore

        table = pq.read_table(path, columns=["id", "embedding_input_sha256", "vector"])
        rows = table.to_pylist()
        if [str(row["id"]) for row in rows] != list(expected_ids):
            return False
        if [str(row["embedding_input_sha256"]) for row in rows] != list(expected_hashes):
            return False
        validate_vectors([row["vector"] for row in rows], f"재개 shard {path.name}")
        return True
    except Exception:
        # 부분 기록·CRC 오류가 있으면 완료로 간주하지 않고 같은 경로를 다시 쓴다.
        return False


def write_shard(
    path: Path,
    ids: Sequence[str],
    hashes: Sequence[str],
    metadata_json: Sequence[str],
    vectors: Sequence[Sequence[float]],
) -> None:
    """한 고정 입력 shard를 임시 파일 후 원자적 교체 방식으로 저장한다."""

    import pyarrow as pa  # type: ignore
    import pyarrow.parquet as pq  # type: ignore

    # 저장 전 벡터 계약을 다시 검사해 손상된 shard를 남기지 않는다.
    validate_vectors(vectors, path.name)
    # 고정 길이 float32 list로 저장해 차원 검증과 DB 로딩을 단순화한다.
    vector_type = pa.list_(pa.float32(), MODEL_DIMENSION)
    table = pa.table(
        {
            "id": pa.array(list(ids), type=pa.string()),
            "embedding_input_sha256": pa.array(list(hashes), type=pa.string()),
            "metadata_json": pa.array(list(metadata_json), type=pa.string()),
            "vector": pa.array(list(vectors), type=vector_type),
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    # 먼저 임시 파일을 완전히 쓴 뒤 rename해 인터럽트된 파일을 정상 shard로 오인하지 않게 한다.
    pq.write_table(table, temporary, compression="zstd")
    temporary.replace(path)


def consolidate_shards(shard_paths: Sequence[Path], output_path: Path) -> None:
    """검증된 shard를 입력 순서대로 하나의 최종 Parquet으로 합친다."""

    import pyarrow as pa  # type: ignore
    import pyarrow.parquet as pq  # type: ignore

    # 모든 shard를 읽고 입력 순서를 보존해 concat한다.
    tables = [pq.read_table(path) for path in shard_paths]
    combined = pa.concat_tables(tables)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    # 최종 파일도 임시 경로 후 교체하여 중간 종료 시 완성 파일을 남기지 않는다.
    pq.write_table(combined, temporary, compression="zstd")
    temporary.replace(output_path)


def embed_job(
    model: Any,
    label: str,
    ids: Sequence[str],
    texts: Sequence[str],
    hashes: Sequence[str],
    metadata_json: Sequence[str],
    output_path: Path,
    work_dir: Path,
    initial_batch_size: int,
    shard_size: int,
) -> dict[str, Any]:
    """한 문서 또는 질문 묶음을 shard 단위로 재개·검증·통합한다."""

    # 네 병렬 목록의 행 수가 다르면 잘못된 벡터-ID 연결이므로 즉시 중단한다.
    if not (len(ids) == len(texts) == len(hashes) == len(metadata_json)):
        raise ValueError(f"{label}: 입력 목록 길이가 서로 다릅니다.")
    started = time.perf_counter()
    shard_paths: list[Path] = []
    used_batches: list[int] = []
    latencies: list[float] = []
    # 고정 shard_size로 범위를 나눠 batch 감소 후에도 같은 shard 경로를 유지한다.
    for shard_index, start in enumerate(range(0, len(ids), shard_size)):
        end = min(len(ids), start + shard_size)
        shard_path = work_dir / label / f"part_{shard_index:05d}.parquet"
        shard_paths.append(shard_path)
        # ID·입력 해시·벡터가 모두 맞는 기존 shard만 재사용한다.
        if shard_matches(shard_path, ids[start:end], hashes[start:end]):
            print(f"재개: {label} shard {shard_index + 1}/{math.ceil(len(ids) / shard_size)} 건너뜀", flush=True)
            continue
        # 현재 shard만 모델에 전달하고 OOM이면 내부에서 batch를 낮춘다.
        vectors, used_batch, elapsed_ms = encode_with_fallback(model, texts[start:end], initial_batch_size)
        write_shard(shard_path, ids[start:end], hashes[start:end], metadata_json[start:end], vectors)
        used_batches.append(used_batch)
        latencies.append(elapsed_ms)
        print(
            f"임베딩 진행: {label} shard {shard_index + 1}/{math.ceil(len(ids) / shard_size)}, {end}/{len(ids)}행",
            flush=True,
        )
    # 모든 shard가 현재 입력과 맞는지 다시 확인한 뒤 하나의 최종 Parquet을 만든다.
    for shard_index, start in enumerate(range(0, len(ids), shard_size)):
        end = min(len(ids), start + shard_size)
        if not shard_matches(shard_paths[shard_index], ids[start:end], hashes[start:end]):
            raise ValueError(f"{label}: 완료 후 shard 검증 실패: {shard_paths[shard_index].name}")
    consolidate_shards(shard_paths, output_path)
    # 최종 Parquet의 전체 행·ID·해시·벡터를 다시 확인한다.
    validation = validate_parquet(output_path, ids, hashes, label)
    validation.update(
        {
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "new_shard_batch_sizes": sorted(set(used_batches)),
            "new_shard_p95_latency_ms": (
                sorted(latencies)[min(len(latencies) - 1, int((len(latencies) - 1) * 0.95))] if latencies else 0.0
            ),
            "parquet_sha256": sha256_file(output_path),
        }
    )
    return validation


def validate_parquet(path: Path, expected_ids: Sequence[str], expected_hashes: Sequence[str], label: str) -> dict[str, Any]:
    """최종 Parquet의 행·ID·해시·벡터 계약을 전수 검사한다."""

    import pyarrow as pa  # type: ignore
    import pyarrow.parquet as pq  # type: ignore

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
            metadata = json.loads(str(row["metadata_json"]))
            metadata_id = str(metadata.get("target_id") or metadata.get("query_id") or "")
            if metadata_id != str(row["id"]):
                raise ValueError(f"{label}: metadata_json ID가 결과 ID와 다릅니다: {row['id']}")
        vector_audit = validate_vectors([row["vector"] for row in rows], label)
        minimum_norm = min(minimum_norm, vector_audit["minimum_norm"])
        maximum_norm = max(maximum_norm, vector_audit["maximum_norm"])
    if len(ids) != len(expected_ids):
        raise ValueError(f"{label}: 최종 Parquet 행 수 불일치: {len(ids)}")
    if ids != list(expected_ids):
        raise ValueError(f"{label}: 최종 Parquet ID 순서·집합 불일치")
    if hashes != list(expected_hashes):
        raise ValueError(f"{label}: 최종 Parquet 입력 해시 불일치")
    return {
        "row_count": len(ids),
        "dimension": MODEL_DIMENSION,
        "minimum_norm": minimum_norm,
        "maximum_norm": maximum_norm,
    }


def build_jobs(input_root: Path) -> tuple[dict[str, tuple[list[str], list[str], list[str], list[str]]], dict[str, Any]]:
    """세 문서 코퍼스와 코퍼스별 평가 질문 실행 목록을 만든다."""

    jobs: dict[str, tuple[list[str], list[str], list[str], list[str]]] = {}
    # 세 운영 검색 단위를 각각 문서 작업으로 구성한다.
    for corpus_key in ("fault_standard", "review_case", "precedent"):
        rows = read_jsonl(input_root / corpus_key / "embedding_units.jsonl")
        jobs[f"documents/{corpus_key}"] = prepare_document_rows(rows)
    # 공통 50문항은 코퍼스별 지시문이 다르므로 세 별도 질문 벡터를 만든다.
    common_rows = read_jsonl(input_root / "evaluation_queries" / "common_queries_50.jsonl")
    for corpus_key in ("fault_standard", "review_case", "precedent"):
        jobs[f"queries/common50/{corpus_key}"] = prepare_query_rows(common_rows, corpus_key)
    # Complete30은 인정기준 검색 평가에만 사용한다.
    complete30_rows = read_jsonl(input_root / "evaluation_queries" / "fault_standard_complete30_queries.jsonl")
    jobs["queries/complete30/fault_standard"] = prepare_query_rows(complete30_rows, "fault_standard")
    # manifest 작성에 필요한 원본 질문 건수만 비밀 없는 요약으로 반환한다.
    return jobs, {"common50_count": len(common_rows), "complete30_count": len(complete30_rows)}


def output_path_for_job(output_root: Path, label: str) -> Path:
    """작업 라벨을 최종 결과 디렉터리와 파일명으로 변환한다."""

    # 문서 작업은 코퍼스별 운영 검색 결과 디렉터리에 저장한다.
    if label.startswith("documents/"):
        corpus_key = label.split("/", 1)[1]
        return output_root / corpus_key / CORPUS_OUTPUT_NAMES[corpus_key]
    # 평가 질문은 문서 결과와 섞이지 않는 별도 영역에 저장한다.
    _, dataset, corpus_key = label.split("/")
    return output_root / "evaluation_queries" / dataset / corpus_key / "query_embeddings.parquet"


def run_embeddings(args: argparse.Namespace) -> None:
    """RunPod 입력 검증부터 세 코퍼스·평가 질문 임베딩 완료까지 실행한다."""

    # 같은 실행의 경로가 바뀌지 않도록 run_id와 절대 경로를 초기에 고정한다.
    run_id = validate_run_id(args.run_id)
    input_root = Path(args.input_root).resolve()
    output_root = Path(args.output_root).resolve()
    work_root = Path(args.work_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)
    # 모델 다운로드 전에 ZIP 입력과 manifest 전체를 검증한다.
    input_manifest = validate_input_manifest(input_root, run_id)
    environment = collect_environment()
    print(f"입력 검증 완료: {run_id}", flush=True)
    print(f"GPU: {environment['gpu_name']} / {environment['gpu_total_vram_gib']} GiB", flush=True)
    # 고정 commit 모델을 한 번만 GPU에 로드해 모든 작업에서 재사용한다.
    model = load_model()
    print(f"모델 로드 완료: {MODEL_NAME}@{MODEL_REVISION}", flush=True)
    # 실제 모델 입력 문자열과 작업 목록을 만든다.
    jobs, query_summary = build_jobs(input_root)
    # truncation이 발생하지 않도록 모든 문서·질문 입력의 token 길이를 먼저 전수 검사한다.
    token_audit = audit_token_lengths(model, [(label, values[1]) for label, values in jobs.items()])
    write_json(output_root / "token_length_audit.json", token_audit)
    print("tokenizer 길이 전수검사 완료", flush=True)
    # 작업별 검증 결과를 모아 최종 manifest에 기록한다.
    job_results: dict[str, Any] = {}
    for label, (ids, texts, hashes, metadata_json) in jobs.items():
        output_path = output_path_for_job(output_root, label)
        job_results[label] = embed_job(
            model=model,
            label=label,
            ids=ids,
            texts=texts,
            hashes=hashes,
            metadata_json=metadata_json,
            output_path=output_path,
            work_dir=work_root,
            initial_batch_size=args.batch_size,
            shard_size=args.shard_size,
        )
        print(f"임베딩 완료: {label}", flush=True)
    # 코퍼스별 artifact manifest와 사람이 읽을 수 있는 검증 JSON을 만든다.
    for corpus_key in ("fault_standard", "review_case", "precedent"):
        document_label = f"documents/{corpus_key}"
        document_output = output_path_for_job(output_root, document_label)
        corpus_manifest = {
            "schema_version": "qwen4_operational_artifact_v1",
            "created_at": utc_now(),
            "run_id": run_id,
            "corpus_key": corpus_key,
            "target_type": "document" if corpus_key == "fault_standard" else "chunk",
            "model_name": MODEL_NAME,
            "model_revision": MODEL_REVISION,
            "native_dimension": MODEL_DIMENSION,
            "dtype": "float32",
            "normalization": NORMALIZATION,
            "input_manifest_sha256": sha256_file(input_root / "input_manifest.json"),
            "input_snapshot_sha256": input_manifest["corpora"][corpus_key]["embedding_unit_snapshot_sha256"],
            "output_file": document_output.name,
            "output_sha256": sha256_file(document_output),
            "output_count": job_results[document_label]["row_count"],
            "query_instruction": QUERY_INSTRUCTIONS[corpus_key],
            "environment": environment,
        }
        write_json(output_root / corpus_key / "artifact_manifest.json", corpus_manifest)
        write_json(output_root / corpus_key / "validation_report.json", job_results[document_label])
    # 전체 7개 작업이 검증된 경우에만 COMPLETE 상태를 기록한다.
    write_json(
        output_root / "run_manifest.json",
        {
            "schema_version": "qwen4_operational_run_v1",
            "status": "COMPLETE",
            "created_at": utc_now(),
            "run_id": run_id,
            "model_name": MODEL_NAME,
            "model_revision": MODEL_REVISION,
            "dimension": MODEL_DIMENSION,
            "dtype": "float32",
            "normalization": NORMALIZATION,
            "input_manifest_sha256": sha256_file(input_root / "input_manifest.json"),
            "environment": environment,
            "query_summary": query_summary,
            "token_length_audit_sha256": sha256_file(output_root / "token_length_audit.json"),
            "jobs": job_results,
        },
    )
    print(f"세 코퍼스 전체 임베딩·검증 완료: {output_root}", flush=True)


def validate_complete_output(output_root: Path, run_id: str) -> dict[str, Any]:
    """패키징 전에 COMPLETE manifest와 필수 산출물의 해시·건수를 확인한다."""

    # run manifest가 없거나 COMPLETE가 아니면 결과 압축을 정상 완료로 만들지 않는다.
    run_manifest = read_json(output_root / "run_manifest.json")
    if run_manifest.get("status") != "COMPLETE" or run_manifest.get("run_id") != run_id:
        raise ValueError("run_manifest가 현재 실행의 COMPLETE 상태가 아닙니다.")
    # 세 코퍼스 문서 결과와 artifact manifest를 각각 재검증한다.
    for corpus_key, expected in EXPECTED_COUNTS.items():
        output_path = output_root / corpus_key / CORPUS_OUTPUT_NAMES[corpus_key]
        artifact = read_json(output_root / corpus_key / "artifact_manifest.json")
        if artifact.get("output_count") != expected["embedding_units"]:
            raise ValueError(f"{corpus_key}: artifact 출력 건수가 다릅니다.")
        if artifact.get("output_sha256") != sha256_file(output_path):
            raise ValueError(f"{corpus_key}: artifact Parquet SHA-256이 다릅니다.")
        if (
            artifact.get("model_revision") != MODEL_REVISION
            or artifact.get("native_dimension") != MODEL_DIMENSION
            or artifact.get("dtype") != "float32"
        ):
            raise ValueError(f"{corpus_key}: 모델 리비전 또는 차원이 다릅니다.")
    # 평가 질문 결과 파일 4개가 모두 존재하는지 확인한다.
    required_queries = [
        output_root / "evaluation_queries" / "common50" / corpus / "query_embeddings.parquet"
        for corpus in ("fault_standard", "review_case", "precedent")
    ] + [output_root / "evaluation_queries" / "complete30" / "fault_standard" / "query_embeddings.parquet"]
    if any(not path.is_file() for path in required_queries):
        raise FileNotFoundError("평가 질문 벡터 결과가 모두 존재하지 않습니다.")
    return run_manifest


def write_result_checksums(output_root: Path) -> Path:
    """결과 파일 전체의 SHA-256 목록을 생성한다."""

    # 체크섬 파일 자신과 임시 파일은 목록에서 제외한다.
    checksum_path = output_root / "CHECKSUMS_SHA256.txt"
    targets = sorted(
        path
        for path in output_root.rglob("*")
        if path.is_file() and path != checksum_path and not path.name.endswith(".tmp")
    )
    lines = [f"{sha256_file(path)}  {path.relative_to(output_root).as_posix()}" for path in targets]
    checksum_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return checksum_path


def package_results(args: argparse.Namespace) -> Path:
    """검증 완료 결과를 모델 캐시·shard 없이 단일 tar.gz로 만든다."""

    # 현재 실행 ID와 결과 루트를 안전하게 고정한다.
    run_id = validate_run_id(args.run_id)
    output_root = Path(args.output_root).resolve()
    validate_complete_output(output_root, run_id)
    # 로그를 포함한 최종 파일 체크섬을 패키징 직전에 새로 만든다.
    write_result_checksums(output_root)
    archive_path = Path(args.archive_path).resolve()
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive_path.with_suffix(archive_path.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()
    # 결과 루트 이름을 고정해 로컬 안전 해제·검증기가 예상 구조를 찾을 수 있게 한다.
    archive_root_name = f"qwen4_three_corpus_operational_{run_id}"
    with tarfile.open(temporary, "w:gz") as archive:
        for path in sorted(item for item in output_root.rglob("*") if item.is_file()):
            relative = path.relative_to(output_root).as_posix()
            archive.add(path, arcname=f"{archive_root_name}/{relative}", recursive=False)
    # 완성 전 임시 파일을 최종 이름으로 원자적으로 교체한다.
    temporary.replace(archive_path)
    print(f"최종 결과 압축 생성: {archive_path}", flush=True)
    print(f"최종 결과 SHA-256: {sha256_file(archive_path)}", flush=True)
    return archive_path


def parser() -> argparse.ArgumentParser:
    """RunPod 실행기와 패키징기의 하위 명령 계약을 만든다."""

    # run과 package가 같은 모듈·run_id 계약을 사용하도록 하위 명령으로 구분한다.
    root = argparse.ArgumentParser(description="Qwen 4B 세 코퍼스 운영 재색인을 실행합니다.")
    subparsers = root.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="입력 검증·임베딩·결과 검증 실행")
    run_parser.add_argument("--run-id", required=True)
    run_parser.add_argument("--input-root", required=True)
    run_parser.add_argument("--output-root", required=True)
    run_parser.add_argument("--work-root", required=True)
    run_parser.add_argument("--batch-size", type=int, default=32)
    run_parser.add_argument("--shard-size", type=int, default=128)
    run_parser.set_defaults(func=run_embeddings)
    package_parser = subparsers.add_parser("package", help="검증 완료 결과를 tar.gz로 패키징")
    package_parser.add_argument("--run-id", required=True)
    package_parser.add_argument("--output-root", required=True)
    package_parser.add_argument("--archive-path", required=True)
    package_parser.set_defaults(func=package_results)
    return root


def main() -> int:
    """선택한 하위 명령을 실행하고 비밀 없는 오류 메시지와 종료 코드를 반환한다."""

    # 예상치 못한 오류도 API 키나 원문을 출력하지 않고 예외 메시지만 한 줄로 전달한다.
    try:
        args = parser().parse_args()
        args.func(args)
    except Exception as error:
        print(f"오류: {error}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    # 모듈 직접 실행 시 main의 성공·실패 코드를 운영체제에 반환한다.
    raise SystemExit(main())
