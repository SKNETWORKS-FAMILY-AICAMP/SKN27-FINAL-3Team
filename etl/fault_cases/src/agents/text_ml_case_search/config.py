from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[5]


def load_dotenv_if_available() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv_if_available()


NODE_CODE = "text_ml_case_search"
CONTRACT_VERSION = "text_ml_case_search_v1"
CONTRACT_VERSION_V2 = "text_ml_case_search_v2"

V2_ACTIVE_SOURCE_TYPES = ["review_case", "fault_ratio_precedent"]
V2_STANDBY_SOURCE_TYPES = ["traffic_precedent"]
V2_EXCLUDED_SOURCE_TYPES = ["standard"]
PGVECTOR_SOURCE_TOP_K = int(os.getenv("TEXT_ML_CASE_SEARCH_PGVECTOR_TOP_K", "5"))

V2_REVIEW_CASE_QUOTA = int(os.getenv("TEXT_ML_CASE_SEARCH_V2_REVIEW_CASE_QUOTA", "5"))
V2_FAULT_RATIO_PRECEDENT_QUOTA = int(
    os.getenv("TEXT_ML_CASE_SEARCH_V2_FAULT_RATIO_PRECEDENT_QUOTA", "5")
)
V2_FINAL_TOP_K = int(os.getenv("TEXT_ML_CASE_SEARCH_V2_FINAL_TOP_K", "10"))
V2_MERGE_STRATEGY = "source_quota"

MIN_CHUNK_TEXT_LEN = int(os.getenv("TEXT_ML_CASE_SEARCH_MIN_CHUNK_TEXT_LEN", "50"))
