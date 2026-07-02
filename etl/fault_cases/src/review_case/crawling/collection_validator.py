"""
수집 PDF 검증 파일.

역할:
- 기준 PDF가 존재하는지 확인한다.
- 0 byte가 아닌지 확인한다.
- 확장자가 .pdf인지 확인한다.
- SHA-256을 계산한다.
- PyMuPDF로 열리는지 확인한다.
- 페이지 수와 샘플 텍스트를 확인한다.
"""

# Python 3.10 이하에서도 타입 힌트를 안전하게 쓰기 위해 annotations를 활성화한다.
from __future__ import annotations

# Path는 파일 경로 처리에 사용한다.
from pathlib import Path

# 설정 모델을 가져온다.
from ..config import CollectionConfig

# quality row 모델을 가져온다.
from ..models import CollectionQualityRow

# file_guard에서 기준 PDF 경로 함수를 가져온다.
from .file_guard import canonical_pdf_path

# 유틸 함수를 가져온다.
from .utils import log, now_iso, sha256_file


def validate_pdf_with_pymupdf(pdf_path: Path) -> tuple[bool, int | None, bool, list[str]]:
    """PyMuPDF로 PDF 열림 여부, 페이지 수, 샘플 텍스트 여부를 확인한다."""

    # 품질 플래그 목록을 만든다.
    flags: list[str] = []

    # PyMuPDF import를 시도한다.
    try:
        import fitz
    except ImportError:
        # PyMuPDF가 없으면 내부 검증을 수행할 수 없다.
        flags.append("pymupdf_not_installed")
        return False, None, False, flags

    # PDF 열기를 시도한다.
    try:
        # PDF를 연다.
        doc = fitz.open(str(pdf_path))

        # 페이지 수를 계산한다.
        page_count = len(doc)

        # 페이지가 없으면 실패로 본다.
        if page_count <= 0:
            flags.append("empty_pdf_pages")
            doc.close()
            return False, page_count, False, flags

        # 첫 페이지 텍스트를 추출한다.
        sample_text = doc[0].get_text("text") or ""

        # 문서를 닫는다.
        doc.close()

        # 샘플 텍스트가 있는지 확인한다.
        sample_text_ok = bool(sample_text.strip())

        # 샘플 텍스트가 없으면 플래그를 추가한다.
        if not sample_text_ok:
            flags.append("sample_text_empty")

        # 검증 결과를 반환한다.
        return True, page_count, sample_text_ok, flags

    except Exception as error:
        # 예외 유형을 플래그로 남긴다.
        flags.append(f"pdf_open_failed:{type(error).__name__}")

        # 실패 결과를 반환한다.
        return False, None, False, flags


def validate_canonical_pdf(config: CollectionConfig) -> CollectionQualityRow:
    """기준 PDF 1개를 검증하고 quality row를 반환한다."""

    # 기준 PDF 경로를 만든다.
    pdf_path = canonical_pdf_path(config)

    # 품질 플래그 목록을 만든다.
    flags: list[str] = []

    # 파일 존재 여부를 확인한다.
    file_exists = pdf_path.exists()

    # 파일이 없으면 플래그를 추가한다.
    if not file_exists:
        flags.append("file_missing")

    # 파일 크기를 확인한다.
    file_size = pdf_path.stat().st_size if file_exists else 0

    # 0 byte면 플래그를 추가한다.
    if file_exists and file_size <= 0:
        flags.append("zero_byte_file")

    # 확장자가 PDF인지 확인한다.
    is_pdf_extension = pdf_path.suffix.lower() == ".pdf"

    # PDF 확장자가 아니면 플래그를 추가한다.
    if file_exists and not is_pdf_extension:
        flags.append("not_pdf_extension")

    # 해시는 파일이 있을 때만 계산한다.
    sha256 = sha256_file(pdf_path) if file_exists and file_size > 0 else None

    # PDF 내부 검증 기본값을 잡는다.
    pdf_open_ok = False

    # 페이지 수 기본값을 잡는다.
    page_count: int | None = None

    # 샘플 텍스트 여부 기본값을 잡는다.
    sample_text_ok = False

    # 파일이 정상적으로 있으면 PyMuPDF 검증을 수행한다.
    if file_exists and file_size > 0 and is_pdf_extension:
        pdf_open_ok, page_count, sample_text_ok, pdf_flags = validate_pdf_with_pymupdf(pdf_path)
        flags.extend(pdf_flags)

    # 전체 검증 상태를 결정한다.
    if file_exists and file_size > 0 and is_pdf_extension and pdf_open_ok:
        validation_status = "valid"
    else:
        validation_status = "invalid"

    # collection_id를 만든다.
    collection_id = f"{config.collection_id_prefix}_{sha256[:12]}" if sha256 else f"{config.collection_id_prefix}_missing"

    # quality row를 반환한다.
    return CollectionQualityRow(
        collection_id=collection_id,
        saved_path=str(pdf_path),
        file_exists=file_exists,
        file_size=file_size,
        is_pdf_extension=is_pdf_extension,
        sha256=sha256,
        pdf_open_ok=pdf_open_ok,
        page_count=page_count,
        sample_text_ok=sample_text_ok,
        validation_status=validation_status,
        quality_flags=flags,
        validated_at=now_iso(),
    )


def log_validation_result(row: CollectionQualityRow) -> None:
    """검증 결과를 콘솔에 출력한다."""

    # 검증 결과를 출력한다.
    log(f"[검증] {row.validation_status}: {row.saved_path}")

    # 파일 크기를 출력한다.
    log(f"[검증] file_size={row.file_size / 1024 / 1024:.1f}MB")

    # 페이지 수를 출력한다.
    log(f"[검증] page_count={row.page_count}")

    # quality flags를 출력한다.
    log(f"[검증] flags={row.quality_flags}")

