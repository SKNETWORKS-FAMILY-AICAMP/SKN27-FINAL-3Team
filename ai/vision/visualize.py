"""Draw detected object bounding boxes on key-frame images.

The generated images are for review, presentation, and evidence inspection;
they are not used as training inputs.
"""
from pathlib import Path
import json

import cv2


AGENT_OUTPUT_DIR = Path("storage/vision/outputs/agent_outputs")
VISUALIZATION_DIR = Path("storage/vision/outputs/visualizations")


CLASS_COLORS = {
    "person": (0, 80, 255),
    "car": (40, 180, 40),
    "truck": (180, 120, 40),
    "bus": (180, 120, 40),
    "motorcycle": (255, 120, 0),
    "bicycle": (255, 120, 0),
}
DEFAULT_COLOR = (240, 240, 240)


def find_latest_agent_output() -> Path:
    outputs = sorted(AGENT_OUTPUT_DIR.glob("agent_output_*.json"))
    if not outputs:
        raise FileNotFoundError(
            f"No agent output JSON found under {AGENT_OUTPUT_DIR}. "
            "Run ai/vision/schemas.py first."
        )
    return outputs[-1]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def grouped_objects_by_frame(agent_output: dict) -> dict[str, list[dict]]:
    structured_result = agent_output["agent_output"]["structured_result"]
    grouped: dict[str, list[dict]] = {}

    for obj in structured_result.get("detected_objects", []):
        source_ref = obj.get("source_ref")
        if not source_ref:
            continue
        grouped.setdefault(source_ref, []).append(obj)

    return grouped


def draw_label(image, text: str, x: int, y: int, color: tuple[int, int, int]):
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.6
    thickness = 2
    text_size, baseline = cv2.getTextSize(text, font, scale, thickness)
    text_width, text_height = text_size

    y_top = max(0, y - text_height - baseline - 8)
    x_right = min(image.shape[1] - 1, x + text_width + 8)

    cv2.rectangle(image, (x, y_top), (x_right, y), color, -1)
    cv2.putText(
        image,
        text,
        (x + 4, y - baseline - 4),
        font,
        scale,
        (0, 0, 0),
        thickness,
        cv2.LINE_AA,
    )


def draw_objects(frame_path: Path, objects: list[dict], output_path: Path):
    image = cv2.imread(str(frame_path))
    if image is None:
        raise RuntimeError(f"Could not read frame image: {frame_path}")

    height, width = image.shape[:2]

    for obj in objects:
        bbox = obj.get("bbox", {}).get("values")
        if not bbox or len(bbox) != 4:
            continue

        x1, y1, x2, y2 = [int(round(value)) for value in bbox]
        x1 = max(0, min(x1, width - 1))
        y1 = max(0, min(y1, height - 1))
        x2 = max(0, min(x2, width - 1))
        y2 = max(0, min(y2, height - 1))

        class_name = obj.get("class_name", "unknown")
        confidence = obj.get("confidence", 0.0)
        color = CLASS_COLORS.get(class_name, DEFAULT_COLOR)
        label = f"{class_name} {confidence:.2f}"

        cv2.rectangle(image, (x1, y1), (x2, y2), color, 3)
        draw_label(image, label, x1, y1, color)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), image)


def create_visualizations(agent_output_path: Path) -> tuple[Path, dict]:
    VISUALIZATION_DIR.mkdir(parents=True, exist_ok=True)

    agent_output = load_json(agent_output_path)
    structured_result = agent_output["agent_output"]["structured_result"]
    objects_by_frame = grouped_objects_by_frame(agent_output)

    visualization_records = []

    for frame in structured_result.get("key_frames", []):
        frame_id = frame.get("frame_id")
        frame_path = frame.get("frame_path")
        if not frame_id or not frame_path:
            continue

        source_path = Path(frame_path)
        output_path = VISUALIZATION_DIR / f"{source_path.stem}_bbox.jpg"
        objects = objects_by_frame.get(frame_id, [])

        draw_objects(source_path, objects, output_path)

        visualization_records.append(
            {
                "frame_id": frame_id,
                "frame_path": source_path.as_posix(),
                "visualization_path": output_path.as_posix(),
                "object_count": len(objects),
            }
        )

    visualized_output = {
        "agent_output_path": agent_output_path.as_posix(),
        "visualizations": visualization_records,
    }

    source_stem = agent_output_path.stem.replace("agent_output_", "")
    index_path = VISUALIZATION_DIR / f"visualizations_{source_stem}.json"
    index_path.write_text(
        json.dumps(visualized_output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return index_path, visualized_output


def main():
    agent_output_path = find_latest_agent_output()
    index_path, output = create_visualizations(agent_output_path)

    print(f"agent_output_path: {agent_output_path}")
    print(f"visualization_index_path: {index_path}")
    print(f"visualization_count: {len(output['visualizations'])}")

    for item in output["visualizations"]:
        print(
            f"{item['frame_id']} "
            f"objects={item['object_count']} "
            f"path={item['visualization_path']}"
        )


if __name__ == "__main__":
    main()

