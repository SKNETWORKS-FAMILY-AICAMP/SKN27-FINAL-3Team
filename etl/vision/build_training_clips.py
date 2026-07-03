"""Build 5-second accident-centered clips for VideoMAE training.

Input is the downloaded video manifest. Output is another CSV with local_path
pointing to the generated 5-second clip, so train_videomae_classifier.py can
read it without knowing how clips were built.
"""
from pathlib import Path
import argparse
import csv
import math

import cv2

from utils import read_csv, safe_name, write_csv


DEFAULT_INPUT = Path("storage/vision/datasets/classification/manifests/train_700_download_manifest.csv")
DEFAULT_OUTPUT = Path("storage/vision/datasets/classification/manifests/train_700_clip_manifest_5s.csv")
DEFAULT_CLIP_DIR = Path("storage/vision/datasets/classification/clips_5s")
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}


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


def estimate_accident_sec(video_path: Path, duration: float, source: str, model_name: str) -> tuple[float, str]:
    if source == "center":
        return duration / 2, "center"

    # ponytail: ByteTrack is optional here; fall back to center if ultralytics/tracker fails.
    try:
        from ultralytics import YOLO

        model = YOLO(model_name)
        previous = None
        best_score = -1.0
        best_frame = 0
        for frame_idx, result in enumerate(model.track(source=video_path.as_posix(), tracker="bytetrack.yaml", stream=True, verbose=False, persist=True)):
            boxes = result.boxes
            if boxes is None or boxes.xyxy is None or len(boxes.xyxy) == 0:
                current = []
            else:
                current = boxes.xyxy.detach().cpu().numpy().tolist()
            if previous is not None:
                score = abs(len(current) - len(previous))
                score += sum(abs((b[2] - b[0]) * (b[3] - b[1])) for b in current) / 1_000_000
                if score > best_score:
                    best_score = score
                    best_frame = frame_idx
            previous = current
        frames, fps, _ = video_info(video_path)
        if fps > 0 and frames > 0:
            return min(duration, best_frame / fps), "yolo_bytetrack_bbox_change"
    except Exception as exc:
        print(f"track_fallback_center: {video_path} reason={exc}")
    return duration / 2, "center_fallback"


def write_clip(video_path: Path, output_path: Path, start_sec: float, end_sec: float) -> bool:
    cap = cv2.VideoCapture(video_path.as_posix())
    if not cap.isOpened():
        return False
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if fps <= 0 or width <= 0 or height <= 0:
        cap.release()
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(output_path.as_posix(), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    start_frame = max(0, math.floor(start_sec * fps))
    end_frame = max(start_frame + 1, math.ceil(end_sec * fps))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    written = 0
    for _ in range(start_frame, end_frame):
        ok, frame = cap.read()
        if not ok:
            break
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
        accident_sec, basis = estimate_accident_sec(src, duration, args.accident_source, args.model_name)
        start_sec, end_sec = centered_window(duration, accident_sec, args.clip_sec)
        label = row.get(args.label_column) or row.get("label") or "unknown"
        asset_id = row.get("asset_id") or src.stem
        clip_path = args.clip_dir / safe_name(label) / f"{safe_name(asset_id)}_clip5s.mp4"
        ok = clip_path.exists() and not args.overwrite
        if not ok:
            ok = write_clip(src, clip_path, start_sec, end_sec)

        copied = dict(row)
        copied.update(
            {
                "source_video_path": src.as_posix(),
                "local_path": clip_path.as_posix(),
                "clip_start_sec": f"{start_sec:.3f}",
                "clip_end_sec": f"{end_sec:.3f}",
                "clip_duration_sec": f"{end_sec - start_sec:.3f}",
                "accident_candidate_sec": f"{accident_sec:.3f}",
                "clip_basis": basis,
                "clip_status": "ok" if ok else "failed",
                "file_exists": str(clip_path.exists()),
                "planned_use": "videomae_training_clip_5s",
            }
        )
        output_rows.append(copied)
        print(f"{copied['clip_status']}: {asset_id} {start_sec:.2f}~{end_sec:.2f}s basis={basis}")

    fields = list(dict.fromkeys([key for row in output_rows for key in row.keys()]))
    write_csv(output_rows, args.output, fields)
    print(f"output_path: {args.output}")
    print(f"rows: {len(output_rows)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build 5-second training clips from downloaded videos.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--clip-dir", type=Path, default=DEFAULT_CLIP_DIR)
    parser.add_argument("--label-column", default="coarse_label")
    parser.add_argument("--clip-sec", type=float, default=5.0)
    parser.add_argument("--accident-source", choices=["center", "yolo_track"], default="center")
    parser.add_argument("--model-name", default="yolov8n.pt")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    build_training_clips(parse_args())
