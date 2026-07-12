"""Privacy-first Vision v2 request builder and result validator."""

from __future__ import annotations

import json
import os
from typing import Any


VISION_CONTRACT_VERSION = "vision_media_result.v2"
DEFAULT_MODEL = "gpt-5.6-terra"
MAX_VIDEO_BYTES = 50 * 1024 * 1024
ALLOWED_DETAIL_LEVELS = {"high", "original"}
DETAIL_POLICIES = {
    "standard": {"detail": "high"},
    "spatial": {"detail": "original"},
}
DETECTOR_POLICY = {
    "scene_detector": "RT-DETRv2-S",
    "object_detector": "YOLO26n",
}


VISION_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "contract_version": {"type": "string", "const": VISION_CONTRACT_VERSION},
        "status": {"type": "string", "enum": ["success", "partial", "failed"]},
        "media_summary": {"type": "string"},
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "timestamp_ms": {"type": "integer", "minimum": 0},
                    "description": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["timestamp_ms", "description", "confidence"],
            },
        },
        "object_detections": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "label": {"type": "string"},
                    "frame_index": {"type": "integer", "minimum": 0},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["label", "frame_index", "confidence"],
            },
        },
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "source_type": {"type": "string"},
                    "source_ref": {"type": "string"},
                    "summary": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["source_type", "source_ref", "summary", "confidence"],
            },
        },
        "limitations": {"type": "array", "items": {"type": "string"}},
        "preprocessing": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "redacted": {"type": "boolean", "const": True},
                "audio_removed": {"type": "boolean"},
                "selected_frame_count": {"type": "integer", "minimum": 1},
            },
            "required": ["redacted", "audio_removed", "selected_frame_count"],
        },
    },
    "required": [
        "contract_version",
        "status",
        "media_summary",
        "events",
        "object_detections",
        "evidence",
        "limitations",
        "preprocessing",
    ],
}


def build_vision_request(
    payload: dict[str, Any],
    *,
    model: str | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    """Build a Responses API request from redacted frames only."""

    media_type = str(payload.get("media_type") or "image")
    byte_size = int(payload.get("byte_size") or 0)
    if media_type == "video" and byte_size > MAX_VIDEO_BYTES:
        raise ValueError("video_too_large")
    if media_type == "video" and payload.get("audio_removed") is not True:
        raise ValueError("audio_not_removed")

    selected_redacted_frames = payload.get("selected_redacted_frames")
    if not isinstance(selected_redacted_frames, list) or not selected_redacted_frames:
        raise ValueError("selected_redacted_frames_required")

    image_parts = []
    selected_detail = str(
        detail or os.environ.get("VISION_PIPELINE_DETAIL") or "high"
    ).lower()
    if selected_detail not in ALLOWED_DETAIL_LEVELS:
        raise ValueError("unsupported_image_detail")

    for frame in selected_redacted_frames:
        if not isinstance(frame, dict) or frame.get("redacted") is not True:
            raise ValueError("redacted_frames_only")
        image_url = str(frame.get("image_url") or "").strip()
        if not image_url:
            raise ValueError("redacted_frame_image_url_required")
        image_parts.append(
            {
                "type": "input_image",
                "image_url": image_url,
                "detail": selected_detail,
            }
        )

    request = {
        "model": str(model or os.environ.get("VISION_PIPELINE_MODEL") or DEFAULT_MODEL),
        "store": False,
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "분쟁 사실을 확인할 수 있는 관찰 내용만 구조화하세요. "
                            "신원 추정이나 법적 과실 확정은 하지 말고, 불확실성은 "
                            "limitations에 기록하세요."
                        ),
                    },
                    *image_parts,
                ],
            }
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "vision_media_result_v2",
                "strict": True,
                "schema": VISION_RESULT_SCHEMA,
            }
        },
    }
    return request


def analyze_vision_media(
    payload: dict[str, Any],
    *,
    client: Any | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    """Run Vision v2 when enabled and validate the strict result envelope."""

    is_enabled = _truthy(os.environ.get("VISION_PIPELINE_ENABLED", "0")) if enabled is None else enabled
    if not is_enabled:
        return {
            "contract_version": VISION_CONTRACT_VERSION,
            "status": "partial",
            "media_summary": "Vision 분석 기능이 비활성화되어 있습니다.",
            "events": [],
            "object_detections": [],
            "evidence": [],
            "limitations": ["VISION_PIPELINE_ENABLED is off"],
            "preprocessing": {
                "redacted": True,
                "audio_removed": bool(payload.get("audio_removed", True)),
                "selected_frame_count": len(payload.get("selected_redacted_frames") or []),
            },
        }

    if client is None:
        client = _openai_client()
    request = build_vision_request(payload)
    response = client.responses.create(**request)
    output_text = str(getattr(response, "output_text", "") or "").strip()
    if not output_text:
        raise RuntimeError("empty_vision_response")
    try:
        result = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_vision_json") from exc
    _validate_result(result)
    return result


def _openai_client() -> Any:
    try:
        from openai import OpenAI
    except Exception as exc:  # pragma: no cover - depends on runtime package
        raise RuntimeError("openai_sdk_unavailable") from exc

    kwargs: dict[str, Any] = {
        "api_key": os.environ.get("VISION_PIPELINE_API_KEY")
        or os.environ.get("OPENAI_API_KEY"),
        "timeout": int(os.environ.get("VISION_PIPELINE_TIMEOUT_SECONDS", "45")),
    }
    base_url = str(os.environ.get("VISION_PIPELINE_BASE_URL") or "").strip()
    if base_url:
        kwargs["base_url"] = base_url
    if not kwargs["api_key"]:
        raise RuntimeError("vision_api_key_missing")
    return OpenAI(**kwargs)


def _validate_result(result: Any) -> None:
    if not isinstance(result, dict):
        raise ValueError("invalid_vision_contract")
    required = VISION_RESULT_SCHEMA["required"]
    missing = [field for field in required if field not in result]
    if missing:
        raise ValueError("missing_vision_fields:" + ",".join(missing))
    if result.get("contract_version") != VISION_CONTRACT_VERSION:
        raise ValueError("invalid_vision_contract_version")
    if result.get("status") not in {"success", "partial", "failed"}:
        raise ValueError("invalid_vision_status")
    preprocessing = result.get("preprocessing")
    if not isinstance(preprocessing, dict) or preprocessing.get("redacted") is not True:
        raise ValueError("invalid_vision_preprocessing")


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
