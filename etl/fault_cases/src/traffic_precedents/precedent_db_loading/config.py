from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[5]
ARTIFACT_ROOT = PROJECT_ROOT / "etl" / "fault_cases" / "artifacts" / "traffic_precedents_output"
SCHEMA_PATH = PROJECT_ROOT / "storage" / "schemas" / "precedent_db_schema.sql"

TRAFFIC_JSONL = ARTIFACT_ROOT / "traffic_prec_reclass_verified" / "01_confirmed_traffic_cases.jsonl"
FAULT_RATIO_JSONL = ARTIFACT_ROOT / "traffic_prec_fault_ratio_verified" / "01_fault_ratio_confirmed_cases.jsonl"
POSTGRES_EXPORT_ROOT = ARTIFACT_ROOT / "postgres_exports"


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


@dataclass(frozen=True)
class PostgresSettings:
    host: str = os.getenv("POSTGRES_HOST", "localhost")
    port: int = int(os.getenv("POSTGRES_PORT", "5432"))
    user: str = os.getenv("POSTGRES_USER", "postgres")
    password: str = os.getenv("POSTGRES_PASSWORD", "change-me")
    maintenance_db: str = os.getenv("POSTGRES_DB", "law_db")
    traffic_db: str = os.getenv("TRAFFIC_PRECEDENT_DB", "traffic_precedent_db")
    fault_ratio_db: str = os.getenv("FAULT_RATIO_PRECEDENT_DB", "fault_ratio_precedent_db")


SETTINGS = PostgresSettings()


DATASET_CONFIGS = {
    "traffic": {
        "db_name": SETTINGS.traffic_db,
        "input_path": TRAFFIC_JSONL,
        "table": "traffic_precedent_cases",
        "report_path": POSTGRES_EXPORT_ROOT / "traffic" / "traffic_cases_load_report.json",
    },
    "fault_ratio": {
        "db_name": SETTINGS.fault_ratio_db,
        "input_path": FAULT_RATIO_JSONL,
        "table": "fault_ratio_precedent_cases",
        "report_path": POSTGRES_EXPORT_ROOT / "fault_ratio" / "fault_ratio_cases_load_report.json",
    },
}
