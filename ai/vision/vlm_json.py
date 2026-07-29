"""Compact, validated JSON contract shared by Vision language models."""

from __future__ import annotations

import json
from typing import Any


VLM_JSON_PROMPT = """Explain the locked VideoMAE accident classification using only visible evidence.
The canonical label is read-only. Do not change it, re-predict it, or emit any accident-type label field.
Do not use Markdown or add text outside JSON. Write all descriptions in concise English.
Do not infer fault ratio, liable parties, violations, or facts that are not visible.

Required keys:
schema_version, narrative, evidence_sentences, conflict, conflict_reason, uncertainties

schema_version must be "vision-qwen-explanation-v1".
evidence_sentences must contain at most 5 items. Each item must contain frame_refs and sentence.
Every frame_refs value must name a provided frame. uncertainties must contain at most 3 short strings.
conflict_reason must be a short string only when conflict is true; otherwise it must be null."""

VLM_JSON_RETRY_PROMPT = (
    VLM_JSON_PROMPT
    + "\nYour previous response was invalid or incomplete. Retry once with shorter strings."
)

REQUIRED = (
    "schema_version", "narrative", "evidence_sentences", "conflict",
    "conflict_reason", "uncertainties",
)


def completed_vlm_asset_ids(rows: list[dict[str, Any]]) -> set[str]:
    """Resume after every persisted result; invalid rows stay available for review."""
    return {row["asset_id"] for row in rows}


def adaptive_retry_prompt(error: str) -> str:
    instruction = "Return the complete JSON object again."
    if error.startswith("schema_invalid:missing:"):
        instruction = f"Include the missing required field {error.removeprefix('schema_invalid:missing:')}."
    elif error.startswith("json_incomplete:"):
        instruction = "Use short strings, double quotes, and close every array and object."
    return f"{VLM_JSON_PROMPT}\nPrevious validation error: {error}\n{instruction}"


def retry_token_limit(error: str) -> int:
    return 1024 if error.startswith("json_incomplete:") else 512


def _schema_error(value: Any, allowed_frame_refs: set[str] | None = None) -> str:
    if not isinstance(value, dict):
        return "schema_invalid:not_object"
    for field in REQUIRED:
        if field not in value:
            return f"schema_invalid:missing:{field}"
    if value["schema_version"] != "vision-qwen-explanation-v1":
        return "schema_invalid:schema_version"
    if not isinstance(value["narrative"], str) or len(value["narrative"]) > 800:
        return "schema_invalid:type_or_length:narrative"
    if not isinstance(value["evidence_sentences"], list):
        return "schema_invalid:type:evidence_sentences"
    if len(value["evidence_sentences"]) > 5:
        return "schema_invalid:max_items:evidence_sentences"
    if not isinstance(value["uncertainties"], list):
        return "schema_invalid:type:uncertainties"
    if len(value["uncertainties"]) > 3:
        return "schema_invalid:max_items:uncertainties"
    if not isinstance(value["conflict"], bool):
        return "schema_invalid:type:conflict"
    reason = value["conflict_reason"]
    if (value["conflict"] and not isinstance(reason, str)) or (
        not value["conflict"] and reason is not None
    ):
        return "schema_invalid:conflict_reason"
    for item in value["evidence_sentences"]:
        if not isinstance(item, dict) or set(item) != {"frame_refs", "sentence"}:
            return "schema_invalid:evidence_sentence"
        if not isinstance(item["frame_refs"], list) or not item["frame_refs"]:
            return "schema_invalid:frame_refs"
        if not isinstance(item["sentence"], str) or len(item["sentence"]) > 300:
            return "schema_invalid:type_or_length:sentence"
        if allowed_frame_refs is not None:
            for frame_ref in item["frame_refs"]:
                if frame_ref not in allowed_frame_refs:
                    return f"schema_invalid:frame_ref:{frame_ref}"
    if any(not isinstance(item, str) or len(item) > 200 for item in value["uncertainties"]):
        return "schema_invalid:type_or_length:uncertainties"
    return ""


def parse_vlm_json(
    text: str, allowed_frame_refs: set[str] | None = None
) -> tuple[dict[str, Any], bool, str]:
    """Read the first complete JSON object and validate the handoff schema."""
    start = text.find("{")
    if start < 0:
        return {}, False, "json_incomplete:no_object"
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        return {}, False, f"json_incomplete:{exc.msg}"
    error = _schema_error(value, allowed_frame_refs)
    if error:
        return {}, False, error
    return value, True, ""
