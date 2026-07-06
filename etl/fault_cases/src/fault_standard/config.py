"""Configuration for the fault standard PDF collection pipeline."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_project_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def _config_dir() -> Path:
    return _default_project_dir() / "config"


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


PIPELINE_SETTINGS = _load_json(
    Path(os.getenv("FAULT_CASES_CRAWLING_SETTINGS", _config_dir() / "crawling_settings.json"))
)

SOURCE_TYPE = PIPELINE_SETTINGS["source"]["type"]
SOURCE_RELIABILITY_SCORE = PIPELINE_SETTINGS["source"]["reliability_score"]
COLLECTION_ID_PREFIX = PIPELINE_SETTINGS["collection"]["id_prefix"]
UNKNOWN_DOCUMENT_TYPE = PIPELINE_SETTINGS["collection"]["unknown_document_type"]
MAX_DOCUMENTS = PIPELINE_SETTINGS["collection"]["max_documents"]
DEFAULT_DOWNLOAD_FILENAME = PIPELINE_SETTINGS["download"]["default_filename"]
DEFAULT_STANDARD_FILENAME = PIPELINE_SETTINGS["download"]["default_standard_filename"]
REQUIRED_DOWNLOAD_SUFFIX = PIPELINE_SETTINGS["download"]["required_suffix"]
SCORING_CONFIG = PIPELINE_SETTINGS["scoring"]
POSITIVE_KEYWORD_SCORES = SCORING_CONFIG["positive_keywords"]
NEGATIVE_KEYWORD_SCORES = SCORING_CONFIG["negative_keywords"]


########## 전처리 관련 설정 ##########
def get_fault_cases_root() -> Path:
    return _default_project_dir()


def get_artifacts_dir() -> Path:
    return get_fault_cases_root() / PIPELINE_SETTINGS["paths"]["artifacts_dir"]


def get_crawled_dir() -> Path:
    return get_artifacts_dir() / PIPELINE_SETTINGS["paths"]["crawled_dir"]


def get_preprocessed_dir() -> Path:
    return get_artifacts_dir() / PIPELINE_SETTINGS["paths"]["preprocessed_dir"]


def get_raw_source_dir() -> Path:
    return get_crawled_dir() / PIPELINE_SETTINGS["paths"]["raw_source_dir"]


@dataclass
class PipelineConfig:
    """Runtime paths and browser settings for collection/validation."""

    project_dir: Path = field(default_factory=_default_project_dir)
    seed_url: str = field(default_factory=lambda: os.getenv("FAULT_CASES_SEED_URL", PIPELINE_SETTINGS["source"]["seed_url"]))
    headless: bool = True
    verbose: bool = True
    force_download: bool = False
    keep_duplicate_files: bool = False
    accept_downloads: bool = True
    timeout_ms: int = field(default_factory=lambda: PIPELINE_SETTINGS["browser"]["timeout_ms"])
    user_agent: str = field(default_factory=lambda: PIPELINE_SETTINGS["browser"]["user_agent"])

    @property
    def artifacts_dir(self) -> Path:
        return self.project_dir / PIPELINE_SETTINGS["paths"]["artifacts_dir"]

    @property
    def crawled_dir(self) -> Path:
        return self.artifacts_dir / PIPELINE_SETTINGS["paths"]["crawled_dir"]

    @property
    def raw_source_dir(self) -> Path:
        return self.crawled_dir / PIPELINE_SETTINGS["paths"]["raw_source_dir"]

    @property
    def logs_dir(self) -> Path:
        return self.crawled_dir / PIPELINE_SETTINGS["paths"]["logs_dir"]

    @property
    def manifest_path(self) -> Path:
        return self.crawled_dir / PIPELINE_SETTINGS["paths"]["manifest_filename"]

    @property
    def quality_report_path(self) -> Path:
        return self.crawled_dir / PIPELINE_SETTINGS["paths"]["quality_report_filename"]

    def ensure_dirs(self) -> None:
        self.raw_source_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.crawled_dir.mkdir(parents=True, exist_ok=True)
