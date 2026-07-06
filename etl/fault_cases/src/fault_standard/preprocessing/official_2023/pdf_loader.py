# -*- coding: utf-8 -*-
"""PDF Loader 모듈입니다."""

from pathlib import Path
from typing import Any, Dict, List, Tuple

from .cleaners import clean_pdf_text
from .models import PageText


def load_pdf_pages(pdf_path: Path) -> Tuple[List[PageText], Dict[str, Any]]:
    """PDF 전체 페이지를 읽고, 실패 시 다른 Loader로 fallback합니다."""

    # 600페이지짜리 대용량 PDF라서 PyMuPDF를 먼저 사용합니다.
    try:
        return load_with_pymupdf(pdf_path)

    # PyMuPDF가 실패하면 pdfplumber로 다시 읽습니다.
    except Exception as first_error:
        pages, report = load_with_pdfplumber(pdf_path)
        report["fallback_reason"] = str(first_error)
        return pages, report


def load_with_pdfplumber(pdf_path: Path) -> Tuple[List[PageText], Dict[str, Any]]:
    """pdfplumber로 페이지 텍스트를 추출합니다."""

    # pdfplumber는 표 기반 PDF에서 텍스트 순서가 비교적 안정적입니다.
    import pdfplumber

    # 페이지 결과를 저장할 리스트입니다.
    pages: List[PageText] = []

    # PDF 파일을 엽니다.
    with pdfplumber.open(str(pdf_path)) as pdf:
        # 실제 PDF 페이지 수입니다.
        expected_page_count = len(pdf.pages)

        # 페이지를 1번부터 순서대로 읽습니다.
        for idx, page in enumerate(pdf.pages, start=1):
            try:
                # 표 내부 텍스트가 붙지 않도록 tolerance를 조절합니다.
                raw = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
                error = None

            except Exception as exc:
                # 특정 페이지 실패 시에도 전체 처리를 멈추지 않습니다.
                raw = ""
                error = str(exc)

            # 원문과 클린 텍스트를 함께 저장합니다.
            pages.append(
                PageText(
                    page_no=idx,
                    raw_text=raw,
                    clean_text=clean_pdf_text(raw),
                    extractor="pdfplumber",
                    error=error,
                )
            )

    # Loader 실행 리포트입니다.
    report = {
        "extractor": "pdfplumber",
        "expected_page_count": expected_page_count,
    }

    # 페이지와 리포트를 반환합니다.
    return pages, report


def load_with_pymupdf(pdf_path: Path) -> Tuple[List[PageText], Dict[str, Any]]:
    """PyMuPDF로 페이지 텍스트를 추출합니다."""

    # PyMuPDF는 빠르고 fallback용으로 안정적입니다.
    import fitz

    # 결과를 저장할 리스트입니다.
    pages: List[PageText] = []

    # PDF 문서를 엽니다.
    doc = fitz.open(str(pdf_path))

    # 전체 페이지 수입니다.
    expected_page_count = doc.page_count

    # PyMuPDF는 0부터 페이지를 세므로 변환합니다.
    for zero_idx in range(expected_page_count):
        page_no = zero_idx + 1

        try:
            # 해당 페이지를 불러옵니다.
            page = doc.load_page(zero_idx)

            # 텍스트를 추출합니다.
            raw = page.get_text("text") or ""
            error = None

        except Exception as exc:
            # 페이지 단위 오류를 저장합니다.
            raw = ""
            error = str(exc)

        # 페이지 결과를 저장합니다.
        pages.append(
            PageText(
                page_no=page_no,
                raw_text=raw,
                clean_text=clean_pdf_text(raw),
                extractor="pymupdf",
                error=error,
            )
        )

    # 문서를 닫습니다.
    doc.close()

    # Loader 실행 리포트입니다.
    report = {
        "extractor": "pymupdf",
        "expected_page_count": expected_page_count,
    }

    # 페이지와 리포트를 반환합니다.
    return pages, report


def build_page_coverage(pages: List[PageText], expected_page_count: int) -> Dict[str, Any]:
    """읽은 페이지 수와 실제 PDF 페이지 수를 비교합니다."""

    # 실제 읽은 페이지 번호 목록입니다.
    read_page_numbers = [page.page_no for page in pages]

    # 기대되는 페이지 번호 집합입니다.
    expected_numbers = set(range(1, expected_page_count + 1))

    # 실제 읽은 페이지 번호 집합입니다.
    read_numbers = set(read_page_numbers)

    # 페이지 커버리지 리포트를 반환합니다.
    return {
        "expected_page_count": expected_page_count,
        "read_page_count": len(read_page_numbers),
        "missing_pages": sorted(expected_numbers - read_numbers),
        "duplicated_pages": sorted({n for n in read_page_numbers if read_page_numbers.count(n) > 1}),
        "status": "success" if expected_numbers == read_numbers else "review_required",
    }
