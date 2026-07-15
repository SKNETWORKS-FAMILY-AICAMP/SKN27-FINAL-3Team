from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[5]


def load_dotenv_if_available() -> None:
    """Load the repo-root .env into os.environ (non-destructive; existing values win).

    Only call this from a standalone script's `if __name__ == "__main__":` guard.
    This module is also imported as a library dependency (by
    ai/agents/text_ml_case_search/agent.py, which is production code, not an ETL
    script), so it must never run this as an import-time side effect — doing so
    would leak repo secrets (OPENAI_API_KEY, DB credentials, ...) into the env of
    whatever process happens to import this module, bypassing the opt-in dotenv
    gate that backend/config/env_loader.py deliberately enforces for the Django app.
    """
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


NODE_CODE = "text_ml_case_search"
CONTRACT_VERSION = "text_ml_case_search_v1"
CONTRACT_VERSION_V2 = "text_ml_case_search_v2"

BM25_TOP_K = int(os.getenv("TEXT_ML_CASE_SEARCH_BM25_TOP_K", "5"))
BM25_CANDIDATE_K = int(os.getenv("TEXT_ML_CASE_SEARCH_BM25_CANDIDATE_K", "10"))

REVIEW_CASE_INDEX = os.getenv(
    "REVIEW_CASE_ES_BM25_INDEX",
    "review_case_chunks_bm25_nori_v1",
)
FAULT_RATIO_PRECEDENT_INDEX = os.getenv(
    "FAULT_RATIO_PRECEDENT_ES_BM25_INDEX",
    "precedent_fault_ratio_chunks_bm25_nori_v1",
)

EVIDENCE_INDEX_NAMES = [REVIEW_CASE_INDEX]
V2_ACTIVE_SOURCE_TYPES = ["review_case", "fault_ratio_precedent"]
V2_STANDBY_SOURCE_TYPES = ["traffic_precedent"]
V2_EXCLUDED_SOURCE_TYPES = ["standard"]
V2_EVIDENCE_INDEX_NAMES = [REVIEW_CASE_INDEX, FAULT_RATIO_PRECEDENT_INDEX]

BM25_SEARCH_FIELDS = [
    "search_text^4",
    "chunk_text^2",
    "case_title^2",
    "header_road_context^1.5",
    "search_text_standard",
    "chunk_text_standard",
]
FAULT_RATIO_PRECEDENT_BM25_FIELDS = [
    "search_text^4",
    "chunk_text^2",
    "case_name^1.5",
    "search_text_standard",
    "chunk_text_standard",
]

V2_REVIEW_CASE_QUOTA = int(os.getenv("TEXT_ML_CASE_SEARCH_V2_REVIEW_CASE_QUOTA", "5"))
V2_FAULT_RATIO_PRECEDENT_QUOTA = int(
    os.getenv("TEXT_ML_CASE_SEARCH_V2_FAULT_RATIO_PRECEDENT_QUOTA", "5")
)
V2_FINAL_TOP_K = int(os.getenv("TEXT_ML_CASE_SEARCH_V2_FINAL_TOP_K", "10"))
V2_MERGE_STRATEGY = "source_quota"

MIN_CHUNK_TEXT_LEN = int(os.getenv("TEXT_ML_CASE_SEARCH_MIN_CHUNK_TEXT_LEN", "50"))

ELASTICSEARCH_HOST = os.getenv(
    "TEXT_ML_CASE_SEARCH_ELASTICSEARCH_HOST",
    os.getenv("ELASTICSEARCH_HOST", f"http://localhost:{os.getenv('ELASTICSEARCH_PORT', '9200')}"),
)
ELASTICSEARCH_USER = os.getenv(
    "TEXT_ML_CASE_SEARCH_ELASTICSEARCH_USER",
    os.getenv("ELASTICSEARCH_USER", "elastic"),
)
ELASTICSEARCH_PASSWORD = os.getenv(
    "TEXT_ML_CASE_SEARCH_ELASTICSEARCH_PASSWORD",
    os.getenv("ELASTIC_PASSWORD", ""),
)
ELASTICSEARCH_REQUEST_TIMEOUT = int(
    os.getenv(
        "TEXT_ML_CASE_SEARCH_ELASTICSEARCH_REQUEST_TIMEOUT",
        os.getenv("ELASTICSEARCH_REQUEST_TIMEOUT", "120"),
    )
)

ENABLE_PRECEDENT_RETRIEVER = False
ENABLE_FAULT_RATIO_PRECEDENT_RETRIEVER = True
ENABLE_METADATA_CONTEXT_ENRICHER = False
ENABLE_RERANKER = False
