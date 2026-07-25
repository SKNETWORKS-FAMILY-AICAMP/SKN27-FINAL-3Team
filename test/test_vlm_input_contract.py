import json

import pytest

from ai.vision.vlm_input import build_qwen_content
from ai.vision.run_to_supervisor import _qwen_evidence


def test_build_qwen_content_pairs_images_with_ordered_yolo_metadata():
    content = build_qwen_content(
        ["annotated_01.jpg"],
        [{
            "frame_order": 1,
            "timestamp_sec": 0.5,
            "objects": [{
                "class_name": "car",
                "confidence": 0.91,
                "bbox_xyxy": [1, 2, 30, 40],
            }],
        }],
        "Return JSON.",
        32,
    )

    assert content[0]["image"].endswith("annotated_01.jpg")
    evidence = json.loads(content[-1]["text"].split("\n", 1)[0])
    assert evidence["frames"][0]["objects"][0]["class_name"] == "car"
    assert evidence["frames"][0]["timestamp_sec"] == 0.5
    assert content[-1]["text"].endswith("Return JSON.")


def test_build_qwen_content_rejects_missing_metadata():
    with pytest.raises(ValueError, match="vlm_input_contract:count_mismatch"):
        build_qwen_content(["a.jpg"], [], "Return JSON.", 32)


def test_build_qwen_content_accepts_frame_without_detections():
    content = build_qwen_content(
        ["a.jpg"],
        [{"frame_order": 1, "timestamp_sec": 0.0, "objects": []}],
        "Return JSON.",
        32,
    )

    assert len(content) == 2


def test_service_pairs_visualizations_with_detection_metadata():
    agent_output = {"agent_output": {"structured_result": {
        "key_frames": [{
            "frame_id": "frame_01",
            "frame_order": 1,
            "timestamp_sec": 0.5,
        }],
        "detected_objects": [{
            "source_ref": "frame_01",
            "class_name": "car",
            "confidence": 0.91,
            "bbox": {"format": "xyxy", "values": [1, 2, 30, 40]},
        }],
    }}}
    visualizations = {"visualizations": [{
        "frame_id": "frame_01",
        "visualization_path": "frame_01_bbox.jpg",
    }]}

    paths, metadata = _qwen_evidence(agent_output, visualizations)

    assert paths == ["frame_01_bbox.jpg"]
    assert metadata[0]["objects"][0]["bbox_xyxy"] == [1, 2, 30, 40]
