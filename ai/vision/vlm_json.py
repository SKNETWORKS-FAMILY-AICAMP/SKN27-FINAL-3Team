"""Compact, validated JSON contract shared by Vision language models."""

from __future__ import annotations

import json
from typing import Any


VLM_JSON_PROMPT = """Analyze the accident-video frames and return exactly one compact JSON object.
Do not use Markdown or add text outside JSON. Write all descriptions in concise English.
Do not repeat bounding-box coordinates. visible_objects must contain at most 5 short label strings.
Do not infer facts that are not visible; use uncertain and explain why.

Required keys:
summary, visible_objects, predicted_accident_target, accident_target_evidence,
accident_visible, accident_visibility, collision_moment_visible, accident_situation,
bbox_helpfulness, bbox_quality, scene_conditions, uncertainties

Allowed enum values:
predicted_accident_target: car_vs_car | car_vs_pedestrian | car_vs_motorcycle | car_vs_bicycle | uncertain
accident_visible: true | false | uncertain
accident_visibility: clear | unclear | not_visible | uncertain
collision_moment_visible: true | false | uncertain
bbox_helpfulness: helpful | partially_helpful | not_helpful | uncertain
bbox_quality: good | fair | poor | uncertain

scene_conditions must contain weather, visibility, road_surface, lighting, evidence.
uncertainties must be an array of short strings."""

VLM_JSON_RETRY_PROMPT = (
    VLM_JSON_PROMPT
    + "\nYour previous response was invalid or incomplete. Retry once with shorter strings."
)

REQUIRED = (
    "summary", "visible_objects", "predicted_accident_target",
    "accident_target_evidence", "accident_visible", "accident_visibility",
    "collision_moment_visible", "accident_situation", "bbox_helpfulness",
    "bbox_quality", "scene_conditions", "uncertainties",
)
ENUMS = {
    "predicted_accident_target": {
        "car_vs_car", "car_vs_pedestrian", "car_vs_motorcycle",
        "car_vs_bicycle", "uncertain",
    },
    "accident_visible": {"true", "false", "uncertain"},
    "accident_visibility": {"clear", "unclear", "not_visible", "uncertain"},
    "collision_moment_visible": {"true", "false", "uncertain"},
    "bbox_helpfulness": {"helpful", "partially_helpful", "not_helpful", "uncertain"},
    "bbox_quality": {"good", "fair", "poor", "uncertain"},
}
SCENE_FIELDS = {"weather", "visibility", "road_surface", "lighting", "evidence"}


def completed_vlm_asset_ids(rows: list[dict[str, Any]]) -> set[str]:
    """Resume after every persisted result; invalid rows stay available for review."""
    return {row["asset_id"] for row in rows}


def adaptive_retry_prompt(error: str) -> str:
    instruction = "Return the complete JSON object again."
    if error.startswith("schema_invalid:missing:"):
        instruction = f"Include the missing required field {error.removeprefix('schema_invalid:missing:')}."
    elif error.startswith("schema_invalid:enum:"):
        field = error.removeprefix("schema_invalid:enum:")
        instruction = f"Use one allowed value for {field}: {' | '.join(sorted(ENUMS[field]))}."
    elif error.startswith("json_incomplete:"):
        instruction = "Use short strings, double quotes, and close every array and object."
    return f"{VLM_JSON_PROMPT}\nPrevious validation error: {error}\n{instruction}"


def retry_token_limit(error: str) -> int:
    return 1024 if error.startswith("json_incomplete:") else 512


def _schema_error(value: Any) -> str:
    if not isinstance(value, dict):
        return "schema_invalid:not_object"
    for field in REQUIRED:
        if field not in value:
            return f"schema_invalid:missing:{field}"
    if not isinstance(value["visible_objects"], list):
        return "schema_invalid:type:visible_objects"
    if not isinstance(value["uncertainties"], list):
        return "schema_invalid:type:uncertainties"
    if not isinstance(value["scene_conditions"], dict):
        return "schema_invalid:type:scene_conditions"
    missing_scene = sorted(SCENE_FIELDS - value["scene_conditions"].keys())
    if missing_scene:
        return f"schema_invalid:missing:scene_conditions.{missing_scene[0]}"
    for field, allowed in ENUMS.items():
        if str(value[field]).lower() not in allowed:
            return f"schema_invalid:enum:{field}"
    return ""


def parse_vlm_json(text: str) -> tuple[dict[str, Any], bool, str]:
    """Read the first complete JSON object and validate the handoff schema."""
    start = text.find("{")
    if start < 0:
        return {}, False, "json_incomplete:no_object"
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        return {}, False, f"json_incomplete:{exc.msg}"
    error = _schema_error(value)
    if error:
        return {}, False, error
    return value, True, ""
