"""인정기준 PDF 페이지에서 판례 사건번호를 추출합니다."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import fitz

from .case_number import CaseNumberMatch, extract_case_numbers


def _context(text: str, match: CaseNumberMatch, window: int = 180) -> str:
    start = max(0, match.start - window)
    end = min(len(text), match.end + window)
    return " ".join(text[start:end].split())


def extract_pdf_citations(
    pdf_paths: list[Path],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """PDF별 판례번호 발생 기록과 페이지 경고를 반환합니다."""

    occurrences: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for pdf_path in pdf_paths:
        if not pdf_path.exists():
            warnings.append(
                {
                    "stage": "pdf_open",
                    "pdf_path": str(pdf_path),
                    "warning": "file_not_found",
                }
            )
            continue

        try:
            document = fitz.open(pdf_path)
        except Exception as error:  # noqa: BLE001
            warnings.append(
                {
                    "stage": "pdf_open",
                    "pdf_path": str(pdf_path),
                    "warning": "open_failed",
                    "error": repr(error),
                }
            )
            continue

        with document:
            for page_index in range(document.page_count):
                page = document.load_page(page_index)
                text = page.get_text("text") or ""
                page_number = page_index + 1

                if not text.strip():
                    warnings.append(
                        {
                            "stage": "pdf_text",
                            "pdf_path": str(pdf_path),
                            "pdf_name": pdf_path.name,
                            "page": page_number,
                            "warning": "empty_text_ocr_may_be_required",
                        }
                    )
                    continue

                for match in extract_case_numbers(text):
                    occurrences.append(
                        {
                            "pdf_name": pdf_path.name,
                            "pdf_path": str(pdf_path.resolve()),
                            "page": page_number,
                            "case_number": match.normalized,
                            "raw_case_number": match.raw,
                            "expanded_from_merged": match.expanded_from_merged,
                            "context": _context(text, match),
                        }
                    )

    unique_occurrences: dict[tuple[str, int, str], dict[str, Any]] = {}
    for row in occurrences:
        key = (row["pdf_name"], row["page"], row["case_number"])
        unique_occurrences.setdefault(key, row)

    return list(unique_occurrences.values()), warnings


def build_unique_targets(
    occurrences: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """발생 기록을 사건번호별 수집 대상으로 묶습니다."""

    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"source_pdfs": set(), "source_pages": defaultdict(set)}
    )

    for row in occurrences:
        case_number = row["case_number"]
        grouped[case_number]["source_pdfs"].add(row["pdf_name"])
        grouped[case_number]["source_pages"][row["pdf_name"]].add(row["page"])

    targets: list[dict[str, Any]] = []
    for case_number in sorted(grouped):
        item = grouped[case_number]
        targets.append(
            {
                "case_number": case_number,
                "source_pdfs": sorted(item["source_pdfs"]),
                "source_pages": {
                    pdf_name: sorted(pages)
                    for pdf_name, pages in sorted(item["source_pages"].items())
                },
                "inclusion_route": "official_fault_standard_citation",
                "force_ready": True,
            }
        )
    return targets

