import json
from importlib import import_module

import pytest


class _FakeResponses:
    def __init__(self):
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return type(
            "Response",
            (),
            {
                "output_text": json.dumps(
                    {
                        "contract_version": "vision_media_result.v2",
                        "status": "success",
                        "media_summary": "교차로에서 두 차량의 진행 장면이 확인됩니다.",
                        "events": [],
                        "object_detections": [],
                        "evidence": [],
                        "limitations": ["영상만으로 법적 과실을 확정하지 않습니다."],
                        "preprocessing": {
                            "redacted": True,
                            "audio_removed": True,
                            "selected_frame_count": 1,
                        },
                    },
                    ensure_ascii=False,
                )
            },
        )()


class _FakeClient:
    def __init__(self):
        self.responses = _FakeResponses()


def _vision_module():
    return import_module("app.services.vision_pipeline_service")


def _payload(max_video_bytes):
    return {
        "media_type": "video",
        "byte_size": max_video_bytes,
        "selected_redacted_frames": [
            {
                "image_url": "data:image/jpeg;base64,cmVkYWN0ZWQ=",
                "redacted": True,
                "timestamp_ms": 1200,
            }
        ],
        "audio_removed": True,
    }


def test_build_request_sends_only_redacted_frames_with_strict_schema():
    vision = _vision_module()
    request = vision.build_vision_request(
        _payload(vision.MAX_VIDEO_BYTES), detail="original"
    )

    assert request["store"] is False
    assert request["model"] == "gpt-5.6-terra"
    assert request["text"]["format"]["strict"] is True
    image_parts = request["input"][0]["content"][1:]
    assert image_parts == [
        {
            "type": "input_image",
            "image_url": "data:image/jpeg;base64,cmVkYWN0ZWQ=",
            "detail": "original",
        }
    ]


def test_build_request_rejects_unredacted_frames_and_oversized_video():
    vision = _vision_module()
    payload = _payload(vision.MAX_VIDEO_BYTES)
    payload["selected_redacted_frames"][0]["redacted"] = False
    with pytest.raises(ValueError, match="redacted"):
        vision.build_vision_request(payload)

    payload = _payload(vision.MAX_VIDEO_BYTES)
    payload["byte_size"] = vision.MAX_VIDEO_BYTES + 1
    with pytest.raises(ValueError, match="video_too_large"):
        vision.build_vision_request(payload)


def test_analyze_vision_media_uses_responses_api_and_validates_contract():
    vision = _vision_module()
    client = _FakeClient()

    result = vision.analyze_vision_media(
        _payload(vision.MAX_VIDEO_BYTES), client=client, enabled=True
    )

    assert result["contract_version"] == "vision_media_result.v2"
    assert result["preprocessing"]["redacted"] is True
    assert len(client.responses.requests) == 1


def test_strict_schema_closes_every_nested_object():
    schema = _vision_module().VISION_RESULT_SCHEMA

    def assert_closed(value):
        if not isinstance(value, dict):
            return
        if value.get("type") == "object":
            assert value.get("additionalProperties") is False
        for child in (value.get("properties") or {}).values():
            assert_closed(child)
        assert_closed(value.get("items"))

    assert_closed(schema)
