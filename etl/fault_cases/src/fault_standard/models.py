"""Data models used by the fault standard collection pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class StandardPostCandidate:
    post_title: str
    post_date: str | None
    source_page_url: str
    list_no: str | None = None
    page_no: int | None = None
    list_text: str = ""


@dataclass
class AttachmentCandidate:
    source_page_url: str
    post_title: str
    post_date: str | None
    attachment_url: str
    original_filename: str
    document_type_candidate: str | None
    document_type_confidence: float
    matched_keywords: list[str]


@dataclass
class DownloadResult:
    status: str
    download_method: str
    saved_path: str | None
    saved_filename: str | None
    file_size: int | None
    sha256: str | None
    error_message: str | None = None


@dataclass
class ManifestRow:
    collection_id: str
    source_type: str
    source_reliability_score: int
    seed_url: str
    source_page_url: str
    attachment_url: str
    post_title: str
    post_date: str | None
    original_filename: str
    saved_filename: str | None
    saved_path: str | None
    document_type_candidate: str | None
    document_type_confidence: float
    matched_keywords: list[str]
    download_method: str
    status: str
    file_size: int | None
    sha256: str | None
    collected_at: str
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

