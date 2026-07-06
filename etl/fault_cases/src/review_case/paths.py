"""
심의사례 수집/전처리 경로 관리 파일.

새 프로젝트 구조 기본값:
- artifacts/review_case_output/crawled
- artifacts/review_case_output/preprocessed

모든 폴더명/파일명은 REVIEW_CASE_* 환경변수로 덮어쓸 수 있다.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_PREFIX = "REVIEW_CASE_"

DEFAULT_CRAWLED_DIR_NAME = "crawled"
DEFAULT_PREPROCESSED_DIR_NAME = "preprocessed"
DEFAULT_TOC_DIR_NAME = "toc"
DEFAULT_CASE_JSON_DIR_NAME = "cases_json"

DEFAULT_COLLECTION_MANIFEST_FILENAME = "crawling_manifest.jsonl"
DEFAULT_COLLECTION_QUALITY_FILENAME = "crawling_quality_report.jsonl"
DEFAULT_DOCUMENTS_FILENAME = "review_case_documents.jsonl"
DEFAULT_SOURCE_CHUNKS_FILENAME = "review_case_source_chunks.jsonl"
DEFAULT_CHUNKS_FILENAME = "review_case_chunks.jsonl"
DEFAULT_QUALITY_REPORT_FILENAME = "quality_report.jsonl"
DEFAULT_PREPROCESSING_SUMMARY_FILENAME = "preprocessing_summary.json"
DEFAULT_LOADER_REPORT_FILENAME = "loader_report.json"
DEFAULT_PAGE_COVERAGE_FILENAME = "page_coverage.json"
DEFAULT_TOC_ITEMS_FILENAME = "review_case_toc_items.jsonl"
DEFAULT_TOC_CASE_LINKS_FILENAME = "review_case_toc_case_links.jsonl"


def _env_str(name: str, default: str) -> str:
    value = os.getenv(f"{ENV_PREFIX}{name}")
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _path_part(name: str, default: str) -> str:
    return _env_str(name, default)


def crawled_dir(output_root: Path) -> Path:
    return output_root / _path_part("CRAWLED_DIR_NAME", DEFAULT_CRAWLED_DIR_NAME)


def raw_pdf_dir(output_root: Path) -> Path:
    """기존 코드 호환용 이름. 실제 새 구조에서는 crawled 폴더를 의미한다."""

    return crawled_dir(output_root)


def collection_dir(output_root: Path) -> Path:
    """기존 코드 호환용 이름. 실제 새 구조에서는 crawled 폴더를 의미한다."""

    return crawled_dir(output_root)


def collection_manifest_path(output_root: Path) -> Path:
    return collection_dir(output_root) / _path_part("COLLECTION_MANIFEST_FILENAME", DEFAULT_COLLECTION_MANIFEST_FILENAME)


def collection_quality_report_path(output_root: Path) -> Path:
    return collection_dir(output_root) / _path_part("COLLECTION_QUALITY_FILENAME", DEFAULT_COLLECTION_QUALITY_FILENAME)


def processed_dir(output_root: Path) -> Path:
    return output_root / _path_part("PREPROCESSED_DIR_NAME", DEFAULT_PREPROCESSED_DIR_NAME)


def toc_dir(output_root: Path) -> Path:
    return processed_dir(output_root) / _path_part("TOC_DIR_NAME", DEFAULT_TOC_DIR_NAME)


def case_json_dir(output_root: Path) -> Path:
    return processed_dir(output_root) / _path_part("CASE_JSON_DIR_NAME", DEFAULT_CASE_JSON_DIR_NAME)


def documents_path(output_root: Path) -> Path:
    return processed_dir(output_root) / _path_part("DOCUMENTS_FILENAME", DEFAULT_DOCUMENTS_FILENAME)


def source_chunks_path(output_root: Path) -> Path:
    return processed_dir(output_root) / _path_part("SOURCE_CHUNKS_FILENAME", DEFAULT_SOURCE_CHUNKS_FILENAME)


def chunks_path(output_root: Path) -> Path:
    return processed_dir(output_root) / _path_part("CHUNKS_FILENAME", DEFAULT_CHUNKS_FILENAME)


def quality_report_path(output_root: Path) -> Path:
    return processed_dir(output_root) / _path_part("QUALITY_REPORT_FILENAME", DEFAULT_QUALITY_REPORT_FILENAME)


def preprocessing_summary_path(output_root: Path) -> Path:
    return processed_dir(output_root) / _path_part("PREPROCESSING_SUMMARY_FILENAME", DEFAULT_PREPROCESSING_SUMMARY_FILENAME)


def loader_report_path(output_root: Path) -> Path:
    return processed_dir(output_root) / _path_part("LOADER_REPORT_FILENAME", DEFAULT_LOADER_REPORT_FILENAME)


def page_coverage_path(output_root: Path) -> Path:
    return processed_dir(output_root) / _path_part("PAGE_COVERAGE_FILENAME", DEFAULT_PAGE_COVERAGE_FILENAME)


def toc_items_path(output_root: Path) -> Path:
    return toc_dir(output_root) / _path_part("TOC_ITEMS_FILENAME", DEFAULT_TOC_ITEMS_FILENAME)


def toc_case_links_path(output_root: Path) -> Path:
    return toc_dir(output_root) / _path_part("TOC_CASE_LINKS_FILENAME", DEFAULT_TOC_CASE_LINKS_FILENAME)


def ensure_preprocessing_dirs(output_root: Path, include_case_json: bool = False) -> None:
    raw_pdf_dir(output_root).mkdir(parents=True, exist_ok=True)
    processed_dir(output_root).mkdir(parents=True, exist_ok=True)
    toc_dir(output_root).mkdir(parents=True, exist_ok=True)
    if include_case_json:
        case_json_dir(output_root).mkdir(parents=True, exist_ok=True)


def ensure_all_pipeline_dirs(output_root: Path) -> None:
    raw_pdf_dir(output_root).mkdir(parents=True, exist_ok=True)
    collection_dir(output_root).mkdir(parents=True, exist_ok=True)
    processed_dir(output_root).mkdir(parents=True, exist_ok=True)
    toc_dir(output_root).mkdir(parents=True, exist_ok=True)
