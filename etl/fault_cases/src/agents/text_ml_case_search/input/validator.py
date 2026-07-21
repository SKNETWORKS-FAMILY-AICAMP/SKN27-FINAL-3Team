from __future__ import annotations

from typing import Any

from etl.fault_cases.src.agents.text_ml_case_search.config import NODE_CODE
from etl.fault_cases.src.agents.text_ml_case_search.schemas import ValidationResult


REQUIRED_FIELDS = [
    "session_id",
    "message_id",
    "job_id",
    "node_code",
    "query_text",
]


def validate_input(agent_input: dict[str, Any]) -> ValidationResult:
    missing_fields: list[str] = []
    errors: list[str] = []

    for field in REQUIRED_FIELDS:
        value = agent_input.get(field)
        if value is None or str(value).strip() == "":
            missing_fields.append(field)

    node_code = agent_input.get("node_code")
    if node_code and str(node_code).strip() != NODE_CODE:
        errors.append(f"node_code must be {NODE_CODE}")

    return {
        "ok": not missing_fields and not errors,
        "missing_fields": missing_fields,
        "errors": errors,
    }
