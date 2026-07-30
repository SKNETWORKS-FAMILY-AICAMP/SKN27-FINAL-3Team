"""Build the shared YOLO evidence input sent to vision-language models."""

import json
from pathlib import Path


def build_qwen_content(
    frame_paths, frame_metadata, prompt, max_frames, classification_context
):
    if max_frames < 1:
        raise ValueError("vlm_input_contract:max_frames")
    if not frame_paths:
        raise ValueError("vlm_input_contract:empty")
    if len(frame_paths) != len(frame_metadata):
        raise ValueError("vlm_input_contract:count_mismatch")
    if not isinstance(classification_context, dict) or not classification_context.get(
        "canonical_label"
    ):
        raise ValueError("vlm_input_contract:classification_context")

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
            "frame_ref": f"frame_{int(metadata['frame_order']):02d}",
            "frame_order": metadata["frame_order"],
            "timestamp_sec": metadata["timestamp_sec"],
            "role": metadata.get("role", "event_evidence"),
            "selection_reason": metadata.get("selection_reason", "selected_by_event_evidence"),
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
            "classification_context": classification_context,
            "evidence_context": {
                "instruction": "frames[i] describes images[i]",
                "frames": frames,
            },
            "task": {
                "instruction": (
                    "Explain the locked VideoMAE classification using only visible "
                    "evidence. Do not change or re-predict the canonical label."
                )
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    content.append({"type": "text", "text": f"{evidence}\n{prompt}"})
    return content
