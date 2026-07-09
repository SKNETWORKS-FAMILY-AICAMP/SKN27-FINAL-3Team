from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import uuid

from .constants import OUTPUT_STATUS_UNKNOWN
from .state import TrafficAccidentConfirmationOCRState


NODE_NAME = "교통사고사실확인원 OCR 노드"
NODE_CODE = "traffic_accident_confirmation_ocr"
DEFAULT_OUTPUT_DIR = Path("etl/fault_cases/artifacts/OCR_output")
SENSITIVE_OUTPUT_KEYS = {"document_image"}


def make_envelope(
    status: str,
    structured: dict,
    missing: list[str],
    next_actions: list[str],
    summary: str = "",
    limitations: list[str] | None = None,
    evidence: list[dict] | None = None,
    failure_reason: str | None = None,
    message: str | None = None,
) -> dict:
    envelope = {
        "node_name": NODE_NAME,
        "node_code": NODE_CODE,
        "status": status,
        "summary": summary,
        "structured_result": structured,
        "evidence": evidence or [],
        "missing_fields": missing,
        "next_actions": next_actions,
        "limitations": limitations or [],
    }

    if failure_reason is not None:
        envelope["failure_reason"] = failure_reason
    if message is not None:
        envelope["message"] = message

    return envelope


def update_agent_results(
    state: TrafficAccidentConfirmationOCRState,
    envelope: dict,
) -> dict:
    results = dict(state.get("agent_results") or {})
    results[NODE_CODE] = envelope
    return results


def _safe_source_stem(source_filename: str | None) -> str:
    source_stem = Path(source_filename or "unknown").stem
    safe_chars = []

    for char in source_stem:
        if char.isalnum() or char in {"-", "_", "."}:
            safe_chars.append(char)
        else:
            safe_chars.append("_")

    safe_name = "".join(safe_chars).strip("._")
    return safe_name or "unknown"


def _strip_sensitive_keys(value):
    if isinstance(value, dict):
        return {
            key: _strip_sensitive_keys(item)
            for key, item in value.items()
            if key not in SENSITIVE_OUTPUT_KEYS
        }
    if isinstance(value, list):
        return [_strip_sensitive_keys(item) for item in value]
    return value


def save_ocr_output(
    result: dict,
    source_filename: str | None = None,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> str:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    source_stem = _safe_source_stem(source_filename)
    status = str(result.get("status") or OUTPUT_STATUS_UNKNOWN)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    short_id = uuid.uuid4().hex[:8]
    file_path = output_path / f"{timestamp}_{source_stem}_{status}_{short_id}.json"

    safe_result = _strip_sensitive_keys(result)
    file_path.write_text(
        json.dumps(safe_result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return str(file_path)
