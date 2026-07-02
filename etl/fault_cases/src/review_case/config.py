"""
심의사례 수집/전처리 설정 파일.

설계 원칙:
- 절대 경로 하드코딩 금지
- URL, 파일명, 폴더명, timeout, chunk 크기는 CLI 또는 REVIEW_CASE_* 환경변수로 덮어쓰기 가능
- 기본 산출물 위치는 패키지가 놓인 프로젝트 구조를 기준으로 자동 추론
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ENV_PREFIX = "REVIEW_CASE_"


def _env_key(name: str) -> str:
    return f"{ENV_PREFIX}{name}"


def _env_str(name: str, default: str) -> str:
    value = os.getenv(_env_key(name))
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _env_int(name: str, default: int) -> int:
    value = os.getenv(_env_key(name))
    if value is None or value.strip() == "":
        return default
    try:
        return int(value.replace("_", ""))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(_env_key(name))
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_path(name: str, default: Path) -> Path:
    return Path(_env_str(name, str(default))).expanduser()


def _env_str_list(name: str, default: list[str]) -> list[str]:
    value = os.getenv(_env_key(name))
    if value is None or value.strip() == "":
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]


def _env_path_list(name: str, default: list[Path]) -> list[Path]:
    value = os.getenv(_env_key(name))
    if value is None or value.strip() == "":
        return [path.expanduser() for path in default]
    return [Path(item).expanduser() for item in value.split(os.pathsep) if item.strip()]


def infer_project_root() -> Path:
    """패키지 위치를 기준으로 etl/fault_cases root를 추론한다.

    예상 배치:
        etl/fault_cases/src/review_case/config.py
    따라서 config.py 기준 parents[2]가 etl/fault_cases다.
    구조가 달라져도 REVIEW_CASE_OUTPUT_ROOT로 언제든 덮어쓸 수 있다.
    """

    current_file = Path(__file__).resolve()
    parents = list(current_file.parents)

    # review_case/config.py -> review_case -> src -> fault_cases
    if len(parents) >= 3 and parents[1].name == "src":
        return parents[2]

    # 패키지가 다른 방식으로 복사된 경우 실행 위치를 fallback으로 둔다.
    return Path.cwd()


def infer_default_output_root() -> Path:
    return infer_project_root() / "artifacts" / "review_case_output"


DEFAULT_REVIEW_CASE_PDF_NAME = "(최종)과실비율심의사례_(54MB).pdf"
DEFAULT_SOURCE_TYPE = "review_case"
DEFAULT_SOURCE_RELIABILITY_SCORE = 3
DEFAULT_CHUNK_SIZE = 1200
DEFAULT_CHUNK_OVERLAP = 150
DEFAULT_SOURCE_CHUNK_SIZE = 1800
DEFAULT_SOURCE_CHUNK_OVERLAP = 200
DEFAULT_TOC_MAX_PAGES = 12
DEFAULT_MIN_TOC_ITEMS = 50
DEFAULT_MIN_ACCIDENT_CONTENT_LEN = 20
DEFAULT_MIN_CHUNK_COUNT = 1
DEFAULT_MAX_CASE_PAGE_SPAN = 6
DEFAULT_UNKNOWN_REVIEW_PREFIX = "unknown_review_case"
DEFAULT_WRITE_SOURCE_CHUNKS = True
DEFAULT_REQUIRED_DOCUMENT_FIELDS = [
    "review_case_id",
    "review_no",
    "case_title",
    "reference_chart_key",
    "standard_scenario_keywords",
    "decision_fault_ratio",
    "a_role",
    "b_role",
    "claimant_final_ratio",
    "respondent_final_ratio",
    "accident_content",
    "claimant_argument",
    "respondent_argument",
    "evidence_text",
    "main_issue",
    "decision_basis",
    "decision_reason",
]
DEFAULT_SEED_URL = "https://accident.knia.or.kr/research"
DEFAULT_DETAIL_URL = "https://accident.knia.or.kr/research-content?index=87957"
DEFAULT_DOWNLOAD_URL_PART = "https://www.knia.or.kr/file-manager/103389"
DEFAULT_OUTPUT_NAME = DEFAULT_REVIEW_CASE_PDF_NAME
DEFAULT_MIN_VALID_PDF_BYTES = 10 * 1024 * 1024
DEFAULT_POST_INCLUDE_KEYWORDS = ["심의사례", "과실비율", "분쟁 심의"]
DEFAULT_POST_EXCLUDE_KEYWORDS = ["인정기준", "보도자료", "통계"]
DEFAULT_PDF_INCLUDE_KEYWORDS = ["과실비율심의사례", "심의사례", "과실비율"]
DEFAULT_PDF_EXCLUDE_KEYWORDS = ["인정기준", "해설", "별표"]
DEFAULT_PAGE_TIMEOUT_MS = 60_000
DEFAULT_DOWNLOAD_TIMEOUT_MS = 600_000
DEFAULT_FALLBACK_WAIT_SECONDS = 1200
DEFAULT_FALLBACK_POLL_SECONDS = 3
DEFAULT_BROWSER_DOWNLOAD_DIRS = [Path.home() / "Downloads", Path.home() / "다운로드"]
DEFAULT_COLLECTION_ID_PREFIX = "review_case_pdf"


def default_output_root() -> Path:
    return _env_path("OUTPUT_ROOT", infer_default_output_root())


def default_review_case_pdf_name() -> str:
    return _env_str("REVIEW_CASE_PDF_NAME", DEFAULT_REVIEW_CASE_PDF_NAME)


def default_output_name() -> str:
    return _env_str("OUTPUT_NAME", default_review_case_pdf_name())


def default_browser_download_dirs() -> list[Path]:
    return _env_path_list("BROWSER_DOWNLOAD_DIRS", DEFAULT_BROWSER_DOWNLOAD_DIRS)


@dataclass
class CollectionConfig:
    """심의사례 PDF 수집 단계 설정값."""

    seed_url: str = field(default_factory=lambda: _env_str("SEED_URL", DEFAULT_SEED_URL))
    detail_url: str = field(default_factory=lambda: _env_str("DETAIL_URL", DEFAULT_DETAIL_URL))
    download_url_part: str = field(default_factory=lambda: _env_str("DOWNLOAD_URL_PART", DEFAULT_DOWNLOAD_URL_PART))
    output_root: Path = field(default_factory=default_output_root)
    output_name: str = field(default_factory=default_output_name)
    source_type: str = field(default_factory=lambda: _env_str("SOURCE_TYPE", DEFAULT_SOURCE_TYPE))
    source_reliability_score: int = field(default_factory=lambda: _env_int("SOURCE_RELIABILITY_SCORE", DEFAULT_SOURCE_RELIABILITY_SCORE))
    headed: bool = False
    force_download: bool = False
    cleanup_only: bool = False
    validate_after_collect: bool = True
    rewrite_reports: bool = True
    min_valid_pdf_bytes: int = field(default_factory=lambda: _env_int("MIN_VALID_PDF_BYTES", DEFAULT_MIN_VALID_PDF_BYTES))
    post_include_keywords: list[str] = field(default_factory=lambda: _env_str_list("POST_INCLUDE_KEYWORDS", DEFAULT_POST_INCLUDE_KEYWORDS))
    post_exclude_keywords: list[str] = field(default_factory=lambda: _env_str_list("POST_EXCLUDE_KEYWORDS", DEFAULT_POST_EXCLUDE_KEYWORDS))
    pdf_include_keywords: list[str] = field(default_factory=lambda: _env_str_list("PDF_INCLUDE_KEYWORDS", DEFAULT_PDF_INCLUDE_KEYWORDS))
    pdf_exclude_keywords: list[str] = field(default_factory=lambda: _env_str_list("PDF_EXCLUDE_KEYWORDS", DEFAULT_PDF_EXCLUDE_KEYWORDS))
    page_timeout_ms: int = field(default_factory=lambda: _env_int("PAGE_TIMEOUT_MS", DEFAULT_PAGE_TIMEOUT_MS))
    download_timeout_ms: int = field(default_factory=lambda: _env_int("DOWNLOAD_TIMEOUT_MS", DEFAULT_DOWNLOAD_TIMEOUT_MS))
    fallback_wait_seconds: int = field(default_factory=lambda: _env_int("FALLBACK_WAIT_SECONDS", DEFAULT_FALLBACK_WAIT_SECONDS))
    fallback_poll_seconds: int = field(default_factory=lambda: _env_int("FALLBACK_POLL_SECONDS", DEFAULT_FALLBACK_POLL_SECONDS))
    browser_download_dirs: list[Path] = field(default_factory=default_browser_download_dirs)
    collection_id_prefix: str = field(default_factory=lambda: _env_str("COLLECTION_ID_PREFIX", DEFAULT_COLLECTION_ID_PREFIX))


@dataclass
class PipelineConfig:
    """심의사례 PDF 전처리 단계 설정값."""

    output_root: Path = field(default_factory=default_output_root)
    review_case_pdf_name: str = field(default_factory=default_review_case_pdf_name)
    source_type: str = field(default_factory=lambda: _env_str("SOURCE_TYPE", DEFAULT_SOURCE_TYPE))
    source_reliability_score: int = field(default_factory=lambda: _env_int("SOURCE_RELIABILITY_SCORE", DEFAULT_SOURCE_RELIABILITY_SCORE))
    chunk_size: int = field(default_factory=lambda: _env_int("CHUNK_SIZE", DEFAULT_CHUNK_SIZE))
    chunk_overlap: int = field(default_factory=lambda: _env_int("CHUNK_OVERLAP", DEFAULT_CHUNK_OVERLAP))
    source_chunk_size: int = field(default_factory=lambda: _env_int("SOURCE_CHUNK_SIZE", DEFAULT_SOURCE_CHUNK_SIZE))
    source_chunk_overlap: int = field(default_factory=lambda: _env_int("SOURCE_CHUNK_OVERLAP", DEFAULT_SOURCE_CHUNK_OVERLAP))
    required_document_fields: list[str] = field(default_factory=lambda: _env_str_list("REQUIRED_DOCUMENT_FIELDS", DEFAULT_REQUIRED_DOCUMENT_FIELDS))
    write_source_chunks: bool = field(default_factory=lambda: _env_bool("WRITE_SOURCE_CHUNKS", DEFAULT_WRITE_SOURCE_CHUNKS))
    write_case_json_files: bool = field(default_factory=lambda: _env_bool("WRITE_CASE_JSON_FILES", False))
    toc_max_pages: int = field(default_factory=lambda: _env_int("TOC_MAX_PAGES", DEFAULT_TOC_MAX_PAGES))
    min_toc_items: int = field(default_factory=lambda: _env_int("MIN_TOC_ITEMS", DEFAULT_MIN_TOC_ITEMS))
    min_accident_content_len: int = field(default_factory=lambda: _env_int("MIN_ACCIDENT_CONTENT_LEN", DEFAULT_MIN_ACCIDENT_CONTENT_LEN))
    min_chunk_count: int = field(default_factory=lambda: _env_int("MIN_CHUNK_COUNT", DEFAULT_MIN_CHUNK_COUNT))
    max_case_page_span: int = field(default_factory=lambda: _env_int("MAX_CASE_PAGE_SPAN", DEFAULT_MAX_CASE_PAGE_SPAN))
    unknown_review_prefix: str = field(default_factory=lambda: _env_str("UNKNOWN_REVIEW_PREFIX", DEFAULT_UNKNOWN_REVIEW_PREFIX))
