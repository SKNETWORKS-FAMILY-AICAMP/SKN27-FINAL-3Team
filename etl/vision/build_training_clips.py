"""Build accident-centered clips for VideoMAE training.

Long videos are re-encoded to a centered clip. Short videos keep the original
file as local_path, with clip_start/end set to the full file duration.
"""
from pathlib import Path
from functools import lru_cache
import argparse
import csv
import math

import cv2

from utils import read_csv, safe_name, write_csv


DEFAULT_INPUT = Path("storage/vision/datasets/classification/manifests/train_700_download_manifest.csv")
DEFAULT_OUTPUT = Path("storage/vision/datasets/classification/manifests/train_700_clip_manifest_5s.csv")
DEFAULT_CLIP_DIR = Path("storage/vision/datasets/classification/clips_5s")
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
ACCIDENT_CLASSES = {"car", "truck", "bus", "motorcycle", "bicycle", "person"}
PAIR_WEIGHTS = {
    frozenset(("car", "person")): 1.0,
    frozenset(("truck", "person")): 1.0,
    frozenset(("bus", "person")): 1.0,
    frozenset(("car", "motorcycle")): 0.9,
    frozenset(("truck", "motorcycle")): 0.9,
    frozenset(("bus", "motorcycle")): 0.9,
    frozenset(("car", "bicycle")): 0.9,
    frozenset(("truck", "bicycle")): 0.9,
    frozenset(("bus", "bicycle")): 0.9,
    frozenset(("car", "car")): 0.7,
    frozenset(("car", "truck")): 0.7,
    frozenset(("car", "bus")): 0.7,
}


def video_info(path: Path) -> tuple[int, float, float]:
    cap = cv2.VideoCapture(path.as_posix())
    if not cap.isOpened():
        return 0, 0.0, 0.0
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    cap.release()
    duration = frames / fps if frames > 0 and fps > 0 else 0.0
    return frames, fps, duration


def centered_window(duration: float, center_sec: float, clip_sec: float) -> tuple[float, float]:
    if duration <= clip_sec:
        return 0.0, duration
    start = max(0.0, center_sec - clip_sec / 2)
    end = min(duration, start + clip_sec)
    start = max(0.0, end - clip_sec)
    return start, end


def bbox_area(box: list[float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def bbox_iou(a: list[float], b: list[float]) -> float:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = bbox_area(a) + bbox_area(b) - inter
    return inter / union if union > 0 else 0.0


def bbox_union(a: list[float], b: list[float]) -> list[float]:
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def padded_crop_rect(bbox: list[float], width: int, height: int, padding_ratio: float) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = bbox
    bw = max(1.0, x2 - x1)
    bh = max(1.0, y2 - y1)
    pad = max(bw, bh) * padding_ratio
    left = max(0, int(math.floor(x1 - pad)))
    top = max(0, int(math.floor(y1 - pad)))
    right = min(width, int(math.ceil(x2 + pad)))
    bottom = min(height, int(math.ceil(y2 + pad)))
    if right - left < 2 or bottom - top < 2:
        return 0, 0, width, height
    return left, top, right, bottom


def center_distance(a: list[float], b: list[float]) -> float:
    ax = (a[0] + a[2]) / 2
    ay = (a[1] + a[3]) / 2
    bx = (b[0] + b[2]) / 2
    by = (b[1] + b[3]) / 2
    return math.hypot(ax - bx, ay - by)


def normalize_distance(distance_px: float, width: float, height: float) -> float:
    diag = math.hypot(width, height)
    return distance_px / diag if diag > 0 else 1.0


def pair_score(a: dict, b: dict, width: float, height: float) -> dict:
    pair = frozenset((a["class_name"], b["class_name"]))
    weight = PAIR_WEIGHTS.get(pair, 0.2)
    iou = bbox_iou(a["bbox"], b["bbox"])
    distance_px = center_distance(a["bbox"], b["bbox"])
    distance_norm = normalize_distance(distance_px, width, height)
    distance_score = max(0.0, 1.0 - min(distance_norm / 0.35, 1.0))
    score = weight * (0.7 * iou + 0.3 * distance_score)
    return {
        "score": score,
        "iou": iou,
        "center_distance_px": distance_px,
        "object_pair": f"{a['class_name']}-{b['class_name']}",
        "track_pair": f"{a.get('track_id', '')}-{b.get('track_id', '')}",
        "bbox_xyxy": bbox_union(a["bbox"], b["bbox"]),
    }


@lru_cache(maxsize=4)
def load_yolo_model(model_name: str):
    from ultralytics import YOLO

    return YOLO(model_name)


def estimate_accident(video_path: Path, duration: float, source: str, model_name: str) -> dict:
    base = {
        "time_sec": duration / 2,
        "basis": "center",
        "score": 0.0,
        "max_iou": 0.0,
        "min_center_distance_px": "",
        "object_pair": "",
        "track_pair": "",
        "bbox_xyxy": "",
    }
    if source == "center":
        return base

    # ponytail: This is a cheap heuristic, not accident truth; replace with labeled event data if available.
    try:
        model = load_yolo_model(model_name)
        previous_count = None
        best = dict(base, basis="yolo_bytetrack_bbox_overlap")
        for frame_idx, result in enumerate(model.track(source=video_path.as_posix(), tracker="bytetrack.yaml", stream=True, verbose=False, persist=True)):
            boxes = result.boxes
            names = result.names
            width = float(result.orig_shape[1]) if result.orig_shape else 0.0
            height = float(result.orig_shape[0]) if result.orig_shape else 0.0
            detections = []
            if boxes is not None and boxes.xyxy is not None and len(boxes.xyxy) > 0:
                xyxy = boxes.xyxy.detach().cpu().numpy().tolist()
                cls = boxes.cls.detach().cpu().numpy().astype(int).tolist() if boxes.cls is not None else [None] * len(xyxy)
                ids = boxes.id.detach().cpu().numpy().astype(int).tolist() if boxes.id is not None else [""] * len(xyxy)
                for bbox, class_id, track_id in zip(xyxy, cls, ids):
                    class_name = names.get(class_id, str(class_id)) if class_id is not None else ""
                    if class_name in ACCIDENT_CLASSES:
                        detections.append({"bbox": bbox, "class_name": class_name, "track_id": track_id})

            best_frame_score = None
            for i, first in enumerate(detections):
                for second in detections[i + 1:]:
                    candidate = pair_score(first, second, width, height)
                    if best_frame_score is None or candidate["score"] > best_frame_score["score"]:
                        best_frame_score = candidate

            count_change = abs(len(detections) - previous_count) if previous_count is not None else 0
            if best_frame_score:
                combined = best_frame_score["score"] + min(count_change, 3) * 0.03
                if combined > best["score"]:
                    frames, fps, _ = video_info(video_path)
                    best.update(
                        {
                            "time_sec": min(duration, frame_idx / fps) if fps > 0 and frames > 0 else duration / 2,
                            "score": combined,
                            "max_iou": best_frame_score["iou"],
                            "min_center_distance_px": best_frame_score["center_distance_px"],
                            "object_pair": best_frame_score["object_pair"],
                            "track_pair": best_frame_score["track_pair"],
                            "bbox_xyxy": best_frame_score.get("bbox_xyxy", ""),
                        }
                    )
            previous_count = len(detections)
        return best
    except Exception as exc:
        print(f"track_fallback_center: {video_path} reason={exc}")
    return dict(base, basis="center_fallback")


def write_clip(
    video_path: Path,
    output_path: Path,
    start_sec: float,
    end_sec: float,
    crop_bbox: list[float] | None = None,
    crop_padding_ratio: float = 0.35,
) -> bool:
    cap = cv2.VideoCapture(video_path.as_posix())
    if not cap.isOpened():
        return False
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if fps <= 0 or width <= 0 or height <= 0:
        cap.release()
        return False

    crop_rect = padded_crop_rect(crop_bbox, width, height, crop_padding_ratio) if crop_bbox else None
    if crop_rect:
        left, top, right, bottom = crop_rect
        out_width, out_height = right - left, bottom - top
    else:
        out_width, out_height = width, height

    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(output_path.as_posix(), cv2.VideoWriter_fourcc(*"mp4v"), fps, (out_width, out_height))
    start_frame = max(0, math.floor(start_sec * fps))
    end_frame = max(start_frame + 1, math.ceil(end_sec * fps))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    written = 0
    for _ in range(start_frame, end_frame):
        ok, frame = cap.read()
        if not ok:
            break
        if crop_rect:
            left, top, right, bottom = crop_rect
            frame = frame[top:bottom, left:right]
        writer.write(frame)
        written += 1
    cap.release()
    writer.release()
    return written > 0 and output_path.exists() and output_path.stat().st_size > 0


def build_training_clips(args: argparse.Namespace) -> None:
    rows = read_csv(args.input)
    output_rows = []
    for row in rows:
        src = Path(row.get("local_path") or row.get("file_path") or "")
        if not src.exists() or src.suffix.lower() not in VIDEO_EXTS:
            copied = dict(row)
            copied.update({"clip_status": "missing_video", "file_exists": "False"})
            output_rows.append(copied)
            continue

        _, _, duration = video_info(src)
        if duration <= 0:
            copied = dict(row)
            copied.update({
                "source_video_path": src.as_posix(),
                "local_path": src.as_posix(),
                "clip_start_sec": "0.000",
                "clip_end_sec": "0.000",
                "clip_duration_sec": "0.000",
                "clip_basis": "invalid_video_duration",
                "clip_status": "invalid_video",
                "file_exists": str(src.exists()),
            })
            output_rows.append(copied)
            continue

        accident = estimate_accident(src, duration, args.accident_source, args.model_name)
        accident_sec = accident["time_sec"]
        basis = accident["basis"]
        start_sec, end_sec = centered_window(duration, accident_sec, args.clip_sec)
        label = row.get(args.label_column) or row.get("label") or "unknown"
        asset_id = row.get("asset_id") or src.stem
        crop_bbox = accident["bbox_xyxy"] if args.crop_mode == "bbox" and accident["bbox_xyxy"] else None
        crop_suffix = "_bboxcrop" if crop_bbox else ""
        if duration <= args.short_video_sec and args.crop_mode == "none":
            # ponytail: short videos already contain full context; keep metadata aligned with the actual file.
            start_sec, end_sec = 0.0, duration
            clip_path = src
            ok = True
            basis = f"{basis}_short_video_full_context"
        else:
            if duration <= args.short_video_sec:
                start_sec, end_sec = 0.0, duration
                basis = f"{basis}_short_video_full_context"
            clip_path = args.clip_dir / safe_name(label) / f"{safe_name(asset_id)}_clip5s{crop_suffix}.mp4"
            ok = clip_path.exists() and not args.overwrite
            if not ok:
                ok = write_clip(src, clip_path, start_sec, end_sec, crop_bbox, args.crop_padding_ratio)
            if crop_bbox:
                basis = f"{basis}_bbox_crop"

        bbox_value = accident["bbox_xyxy"]
        bbox_text = ",".join(f"{value:.3f}" for value in bbox_value) if bbox_value else ""
        copied = dict(row)
        copied.update(
            {
                "source_video_path": src.as_posix(),
                "local_path": clip_path.as_posix(),
                "clip_start_sec": f"{start_sec:.3f}",
                "clip_end_sec": f"{end_sec:.3f}",
                "clip_duration_sec": f"{end_sec - start_sec:.3f}",
                "accident_candidate_sec": f"{accident_sec:.3f}",
                "accident_candidate_score": f"{accident['score']:.6f}",
                "accident_candidate_iou": f"{accident['max_iou']:.6f}",
                "accident_candidate_center_distance_px": f"{accident['min_center_distance_px']:.3f}" if accident["min_center_distance_px"] != "" else "",
                "accident_candidate_object_pair": accident["object_pair"],
                "accident_candidate_track_pair": accident["track_pair"],
                "accident_candidate_bbox_xyxy": bbox_text,
                "clip_basis": basis,
                "clip_status": "ok" if ok else "failed",
                "file_exists": str(clip_path.exists()),
                "planned_use": "videomae_training_clip_or_short_full_context",
            }
        )
        output_rows.append(copied)
        print(f"{copied['clip_status']}: {asset_id} {start_sec:.2f}~{end_sec:.2f}s score={copied['accident_candidate_score']} basis={basis}")

    fields = list(dict.fromkeys([key for row in output_rows for key in row.keys()]))
    write_csv(output_rows, args.output, fields)
    print(f"output_path: {args.output}")
    print(f"rows: {len(output_rows)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build accident-centered training clips from downloaded videos.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--clip-dir", type=Path, default=DEFAULT_CLIP_DIR)
    parser.add_argument("--label-column", default="coarse_label")
    parser.add_argument("--clip-sec", type=float, default=5.0)
    parser.add_argument("--short-video-sec", type=float, default=10.0)
    parser.add_argument("--accident-source", choices=["center", "yolo_track"], default="center")
    parser.add_argument("--model-name", default="yolov8n.pt")
    parser.add_argument("--crop-mode", choices=["none", "bbox"], default="none")
    parser.add_argument("--crop-padding-ratio", type=float, default=0.35)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    build_training_clips(parse_args())
