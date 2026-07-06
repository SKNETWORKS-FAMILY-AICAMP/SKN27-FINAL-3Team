from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..models import LoaderReport, PageText
from .cleaner import clean_text


def _book_page_no(text: str) -> int | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines[:5] + lines[-5:]:
        match = re.fullmatch(r"[-\s]*(\d{1,4})[-\s]*", line)
        if match:
            return int(match.group(1))
    return None


def _load_with_pymupdf(pdf_path: Path) -> tuple[list[PageText], LoaderReport]:
    import fitz  # type: ignore

    doc = fitz.open(pdf_path)
    pages: list[PageText] = []
    for index, page in enumerate(doc, start=1):
        raw_text = page.get_text("text") or ""
        words: list[dict[str, Any]] = []
        for word in page.get_text("words") or []:
            if len(word) >= 5:
                words.append(
                    {
                        "x0": float(word[0]),
                        "y0": float(word[1]),
                        "x1": float(word[2]),
                        "y1": float(word[3]),
                        "text": str(word[4]),
                    }
                )
        pages.append(
            PageText(
                page_no=index,
                raw_text=raw_text,
                clean_text=clean_text(raw_text),
                extractor="pymupdf",
                book_page_no=_book_page_no(raw_text),
                raw_words=words,
            )
        )
    report = LoaderReport("pymupdf", len(doc), len(pages), {}, {"pdf_path": str(pdf_path)})
    doc.close()
    return pages, report


def _load_with_pypdf(pdf_path: Path, error: Exception) -> tuple[list[PageText], LoaderReport]:
    from pypdf import PdfReader  # type: ignore

    reader = PdfReader(str(pdf_path))
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        raw_text = page.extract_text() or ""
        pages.append(
            PageText(
                page_no=index,
                raw_text=raw_text,
                clean_text=clean_text(raw_text),
                extractor="pypdf",
                book_page_no=_book_page_no(raw_text),
            )
        )
    return pages, LoaderReport("pypdf", len(reader.pages), len(pages), {"pymupdf": str(error)}, {"pdf_path": str(pdf_path)})


def load_pdf_pages(pdf_path: Path) -> tuple[list[PageText], LoaderReport]:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    try:
        return _load_with_pymupdf(pdf_path)
    except Exception as error:
        return _load_with_pypdf(pdf_path, error)
