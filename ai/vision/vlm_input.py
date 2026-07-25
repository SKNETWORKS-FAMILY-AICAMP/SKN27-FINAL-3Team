"""Build the shared YOLO evidence input sent to vision-language models."""

import json
from pathlib import Path


def build_qwen_content(frame_paths, frame_metadata, prompt, max_frames):
    if max_frames < 1:
        raise ValueError("vlm_input_contract:max_frames")
    if not frame_paths:
        raise ValueError("vlm_input_contract:empty")
    if len(frame_paths) != len(frame_metadata):
        raise ValueError("vlm_input_contract:count_mismatch")

    frames = []
    content = []
    for path, metadata in list(zip(frame_paths, frame_metadata))[:max_frames]:
        if not {"frame_order", "timestamp_sec", "objects"}.issubset(metadata):
            raise ValueError("vlm_input_contract:missing_frame_field")
        objects = []
        for obj in metadata["objects"]:
            if not {"class_name", "confidence", "bbox_xyxy"}.issubset(obj):
                raise ValueError("vlm_input_contract:missing_object_field")
            if not isinstance(obj["bbox_xyxy"], (list, tuple)) or len(obj["bbox_xyxy"]) != 4:
                raise ValueError("vlm_input_contract:invalid_bbox")
            objects.append({
                key: obj[key]
                for key in ("class_name", "confidence", "bbox_xyxy")
            })
        frames.append({
            "frame_order": metadata["frame_order"],
            "timestamp_sec": metadata["timestamp_sec"],
            "image_name": Path(path).name,
            "objects": objects,
        })
        content.append({
            "type": "image",
            "image": str(Path(path).resolve()),
            "max_pixels": 640 * 360,
        })

    evidence = json.dumps(
        {
            "instruction": "frames[i] describes images[i]",
            "frames": frames,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    content.append({"type": "text", "text": f"{evidence}\n{prompt}"})
    return content
