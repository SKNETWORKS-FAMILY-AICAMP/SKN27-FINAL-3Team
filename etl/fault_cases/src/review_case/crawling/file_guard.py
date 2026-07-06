"""
수집 파일 정리와 중복 다운로드 방지 파일.

역할:
1. raw/source_files 폴더의 실패 파일(.part)을 삭제한다.
2. _001, _002 같은 중복 PDF 후보를 삭제한다.
3. 기준 PDF가 이미 있으면 다운로드를 생략하게 한다.
4. 기준 PDF가 없고 중복 후보 중 정상 파일이 있으면 가장 큰 파일을 기준 PDF로 승격한다.
"""

# Python 3.10 이하에서도 타입 힌트를 안전하게 쓰기 위해 annotations를 활성화한다.
from __future__ import annotations

# dataclass는 정리 계획을 구조화하기 위해 사용한다.
from dataclasses import dataclass

# Path는 파일 경로 처리에 사용한다.
from pathlib import Path

# 설정 모델을 가져온다.
from ..config import CollectionConfig

# raw PDF 경로 함수를 가져온다.
from ..paths import raw_pdf_dir

# 공통 로그와 해시 함수를 가져온다.
from .utils import log, sha256_file


@dataclass
class CleanupResult:
    """정리 실행 결과를 담는 구조다."""

    # 기준 PDF 경로다.
    canonical_pdf: Path

    # 삭제한 part 파일 목록이다.
    deleted_part_files: list[Path]

    # 삭제한 중복 PDF 목록이다.
    deleted_duplicate_pdfs: list[Path]

    # 기준 파일로 승격한 파일 경로다.
    promoted_pdf: Path | None


def canonical_pdf_path(config: CollectionConfig) -> Path:
    """최종 기준 PDF 경로를 반환한다."""

    # output_name을 기준으로 raw/source_files 아래 경로를 만든다.
    return raw_pdf_dir(config.output_root) / config.output_name


def is_duplicate_pdf(path: Path, canonical: Path) -> bool:
    """_001, _002 같은 중복 PDF 후보인지 확인한다."""

    # 확장자가 pdf가 아니면 중복 PDF가 아니다.
    if path.suffix.lower() != ".pdf":
        return False

    # 기준 파일 자체는 중복이 아니다.
    if path.name == canonical.name:
        return False

    # 기준 파일 stem 뒤에 _가 붙으면 중복 후보로 본다.
    return path.stem.startswith(canonical.stem + "_")


def list_duplicate_pdfs(config: CollectionConfig) -> list[Path]:
    """중복 PDF 후보 목록을 반환한다."""

    # 기준 PDF 경로를 만든다.
    canonical = canonical_pdf_path(config)

    # source_files 폴더 경로를 만든다.
    source_dir = raw_pdf_dir(config.output_root)

    # 폴더가 없으면 빈 목록을 반환한다.
    if not source_dir.exists():
        return []

    # 모든 PDF 중 중복 후보만 필터링한다.
    return sorted(path for path in source_dir.glob("*.pdf") if is_duplicate_pdf(path, canonical))


def list_part_files(config: CollectionConfig) -> list[Path]:
    """실패한 .part 파일 목록을 반환한다."""

    # source_files 폴더 경로를 만든다.
    source_dir = raw_pdf_dir(config.output_root)

    # 폴더가 없으면 빈 목록을 반환한다.
    if not source_dir.exists():
        return []

    # .part 파일 목록을 반환한다.
    return sorted(source_dir.glob("*.part"))


def candidate_complete_pdfs(config: CollectionConfig) -> list[Path]:
    """정상 PDF 후보 목록을 반환한다."""

    # source_files 폴더 경로를 만든다.
    source_dir = raw_pdf_dir(config.output_root)

    # 폴더가 없으면 빈 목록을 반환한다.
    if not source_dir.exists():
        return []

    # 최소 크기 이상인 PDF만 정상 후보로 본다.
    return sorted(
        path
        for path in source_dir.glob("*.pdf")
        if path.is_file() and path.stat().st_size >= config.min_valid_pdf_bytes
    )


def promote_largest_candidate_if_needed(config: CollectionConfig) -> Path | None:
    """기준 PDF가 없으면 가장 큰 정상 후보를 기준 파일명으로 승격한다."""

    # 기준 PDF 경로를 만든다.
    canonical = canonical_pdf_path(config)

    # 기준 PDF가 이미 있으면 승격할 필요가 없다.
    if canonical.exists() and canonical.stat().st_size >= config.min_valid_pdf_bytes:
        return None

    # 정상 PDF 후보를 찾는다.
    candidates = candidate_complete_pdfs(config)

    # 후보가 없으면 승격하지 않는다.
    if not candidates:
        return None

    # 가장 큰 파일을 선택한다.
    largest = max(candidates, key=lambda path: path.stat().st_size)

    # 가장 큰 파일이 이미 canonical이면 승격하지 않는다.
    if largest == canonical:
        return None

    # canonical 부모 폴더를 만든다.
    canonical.parent.mkdir(parents=True, exist_ok=True)

    # canonical이 불완전하게 있으면 삭제한다.
    canonical.unlink(missing_ok=True)

    # 가장 큰 후보를 canonical 이름으로 변경한다.
    largest.replace(canonical)

    # 승격 로그를 출력한다.
    log(f"[정리] 정상 후보를 기준 PDF로 승격: {largest.name} -> {canonical.name}")

    # 승격된 canonical 경로를 반환한다.
    return canonical


def cleanup_source_files(config: CollectionConfig) -> CleanupResult:
    """source_files 폴더를 정리하고 기준 PDF 1개만 남기도록 만든다."""

    # source_files 폴더를 만든다.
    raw_pdf_dir(config.output_root).mkdir(parents=True, exist_ok=True)

    # 기준 PDF 경로를 만든다.
    canonical = canonical_pdf_path(config)

    # 먼저 정상 후보를 기준 PDF로 승격한다.
    promoted = promote_largest_candidate_if_needed(config)

    # 삭제한 part 파일 목록을 담는다.
    deleted_part_files: list[Path] = []

    # 삭제한 중복 PDF 목록을 담는다.
    deleted_duplicate_pdfs: list[Path] = []

    # .part 파일을 삭제한다.
    for part_file in list_part_files(config):
        # 파일을 삭제한다.
        part_file.unlink(missing_ok=True)

        # 삭제 목록에 넣는다.
        deleted_part_files.append(part_file)

        # 로그를 출력한다.
        log(f"[정리] 실패 part 파일 삭제: {part_file.name}")

    # 중복 PDF 후보를 삭제한다.
    for duplicate_pdf in list_duplicate_pdfs(config):
        # 기준 PDF가 아닌 중복 후보를 삭제한다.
        duplicate_pdf.unlink(missing_ok=True)

        # 삭제 목록에 넣는다.
        deleted_duplicate_pdfs.append(duplicate_pdf)

        # 로그를 출력한다.
        log(f"[정리] 중복 PDF 삭제: {duplicate_pdf.name}")

    # 정리 결과를 반환한다.
    return CleanupResult(
        canonical_pdf=canonical,
        deleted_part_files=deleted_part_files,
        deleted_duplicate_pdfs=deleted_duplicate_pdfs,
        promoted_pdf=promoted,
    )


def has_valid_canonical_pdf(config: CollectionConfig) -> bool:
    """기준 PDF가 정상 크기로 존재하는지 확인한다."""

    # 기준 PDF 경로를 만든다.
    path = canonical_pdf_path(config)

    # 파일이 없으면 False다.
    if not path.exists():
        return False

    # 파일이 아니면 False다.
    if not path.is_file():
        return False

    # 최소 크기보다 작으면 False다.
    if path.stat().st_size < config.min_valid_pdf_bytes:
        return False

    # 여기까지 통과하면 정상 기준 PDF로 본다.
    return True


def log_canonical_pdf(config: CollectionConfig) -> None:
    """기준 PDF 정보를 로그로 출력한다."""

    # 기준 PDF 경로를 만든다.
    path = canonical_pdf_path(config)

    # 기준 PDF가 없으면 로그만 출력한다.
    if not path.exists():
        log(f"[상태] 기준 PDF 없음: {path}")
        return

    # 파일 크기를 MB로 계산한다.
    size_mb = path.stat().st_size / 1024 / 1024

    # 해시 앞 12자리를 계산한다.
    short_hash = sha256_file(path)[:12]

    # 상태 로그를 출력한다.
    log(f"[상태] 기준 PDF 존재: {path} / {size_mb:.1f}MB / sha256={short_hash}...")

