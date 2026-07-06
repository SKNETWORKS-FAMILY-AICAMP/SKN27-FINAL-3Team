"""Path and filename helpers for the fault cases ETL package."""

from __future__ import annotations

import re
from pathlib import Path

from .config import DEFAULT_DOWNLOAD_FILENAME, DEFAULT_STANDARD_FILENAME, REQUIRED_DOWNLOAD_SUFFIX

WINDOWS_RESERVED_CHARS = r'<>:"/\|?*'


def safe_filename(filename: str, fallback: str = DEFAULT_DOWNLOAD_FILENAME) -> str:
    name = (filename or fallback).strip() or fallback
    name = name.replace("\x00", "")
    for char in WINDOWS_RESERVED_CHARS:
        name = name.replace(char, "_")
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"_+", "_", name).strip(" ._")
    if not name:
        name = fallback
    if Path(name).suffix.lower() != REQUIRED_DOWNLOAD_SUFFIX:
        name = f"{name}{REQUIRED_DOWNLOAD_SUFFIX}"
    return name


def looks_like_numeric_pdf_name(filename: str | None) -> bool:
    if not filename:
        return False
    return re.fullmatch(r"\d+\.pdf", Path(filename).name.strip(), flags=re.IGNORECASE) is not None


def canonical_filename_for_document_type(
    document_type: str | None,
    original_filename: str | None,
    fallback_title: str | None = None,
) -> str:
    if original_filename and not looks_like_numeric_pdf_name(original_filename):
        return safe_filename(original_filename)
    if fallback_title:
        return safe_filename(fallback_title)
    return safe_filename(original_filename or DEFAULT_STANDARD_FILENAME)


def ensure_unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    index = 2
    while True:
        candidate = parent / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1
