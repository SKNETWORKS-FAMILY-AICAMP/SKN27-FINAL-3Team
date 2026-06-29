"""Run YOLO baseline detection on extracted key frames.

Outputs per-frame class, confidence, and bbox JSON for schema conversion.
"""
from pathlib import Path
import json

from ultralytics import YOLO


OUTPUT_DIR = Path("storage/vision/outputs")
DETECTION_DIR = OUTPUT_DIR / "detections"
DEFAULT_MODEL_NAME = "yolov8n.pt"


def find_latest_keyframe_output() -> Path:
    outputs = sorted(OUTPUT_DIR.glob("keyframes_*.json"))
    if not outputs:
        raise FileNotFoundError(
            f"No keyframe output JSON found under {OUTPUT_DIR}. "
            "Run ai/vision/pipeline.py first."
        )
    return outputs[-1]


def load_keyframe_output(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def detect_keyframes(
    keyframe_output_path: Path,
    model_name: str = DEFAULT_MODEL_NAME,
    confidence_threshold: float = 0.25,
) -> tuple[Path, dict]:
    DETECTION_DIR.mkdir(parents=True, exist_ok=True)

    keyframe_output = load_keyframe_output(keyframe_output_path)
    model = YOLO(model_name)
    detections = []

    for keyframe in keyframe_output.get("keyframes", []):
        frame_path = keyframe.get("frame_path")

        if keyframe.get("status") != "ok" or not frame_path:
            detections.append(
                {
                    "frame_order": keyframe.get("frame_order"),
                    "frame_index": keyframe.get("frame_index"),
                    "timestamp_sec": keyframe.get("timestamp_sec"),
                    "frame_path": frame_path,
                    "status": "skipped",
                    "objects": [],
                }
            )
            continue

        result = model.predict(
            source=frame_path,
            conf=confidence_threshold,
            save=False,
            verbose=False,
        )[0]

        objects = []
        names = result.names

        for box in result.boxes:
            class_id = int(box.cls[0].item())
            confidence = float(box.conf[0].item())
            xyxy = [float(value) for value in box.xyxy[0].tolist()]

            objects.append(
                {
                    "class_id": class_id,
                    "class_name": names.get(class_id, str(class_id)),
                    "confidence": round(confidence, 4),
                    "bbox_xyxy": [round(value, 2) for value in xyxy],
                }
            )

        detections.append(
            {
                "frame_order": keyframe.get("frame_order"),
                "frame_index": keyframe.get("frame_index"),
                "timestamp_sec": keyframe.get("timestamp_sec"),
                "frame_path": frame_path,
                "status": "ok",
                "object_count": len(objects),
                "objects": objects,
            }
        )

    output = {
        "source_video": keyframe_output.get("source_video"),
        "keyframe_output_path": keyframe_output_path.as_posix(),
        "model": {
            "name": model_name,
            "confidence_threshold": confidence_threshold,
        },
        "detections": detections,
    }

    source_stem = Path(keyframe_output.get("source_video", "video")).stem
    output_path = DETECTION_DIR / f"detections_{source_stem}.json"
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return output_path, output


def main():
    keyframe_output_path = find_latest_keyframe_output()
    output_path, output = detect_keyframes(keyframe_output_path)

    print(f"keyframe_output_path: {keyframe_output_path}")
    print(f"detection_output_path: {output_path}")
    print(f"detection_frame_count: {len(output['detections'])}")

    for item in output["detections"]:
        print(
            f"{item['status']} "
            f"frame_order={item['frame_order']} "
            f"frame_index={item['frame_index']} "
            f"object_count={item.get('object_count', 0)}"
        )


if __name__ == "__main__":
    main()

