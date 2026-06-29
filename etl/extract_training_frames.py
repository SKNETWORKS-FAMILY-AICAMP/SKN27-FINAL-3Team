"""Extract representative training frames from sampled classification videos.

Reads a video-level manifest, extracts a fixed number of frames per video,
and writes a frame-level manifest that can be consumed by image classifiers.
"""
from pathlib import Path
import argparse
import math

import cv2

from utils import read_csv, safe_name, write_csv


DEFAULT_INPUT_PATH = Path(
    "storage/vision/datasets/classification/manifests/dryrun_download_manifest.csv"
)
DEFAULT_OUTPUT_PATH = Path(
    "storage/vision/datasets/classification/manifests/frame_manifest_dryrun.csv"
)
DEFAULT_FRAME_DIR = Path("storage/vision/datasets/classification/frames")
DEFAULT_LABEL_COLUMN = "coarse_label"
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTS


def selected_frame_indices(total_frames: int, frames_per_video: int) -> list[int]:
    if total_frames <= 0 or frames_per_video <= 0:
        return []
    if total_frames <= frames_per_video:
        return list(range(total_frames))

    step = total_frames / frames_per_video
    indices = []
    for idx in range(frames_per_video):
        frame_index = min(total_frames - 1, math.floor((idx + 0.5) * step))
        indices.append(frame_index)
    return sorted(set(indices))


def extract_frame(video: cv2.VideoCapture, frame_index: int, output_path: Path) -> bool:
    video.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, frame = video.read()
    if not ok or frame is None:
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # cv2.imwrite can fail on Windows paths that contain Korean labels.
    ok, encoded = cv2.imencode(output_path.suffix, frame)
    if not ok:
        return False
    output_path.write_bytes(encoded.tobytes())
    return output_path.exists() and output_path.stat().st_size > 0


def frame_output_path(
    frame_dir: Path,
    label: str,
    asset_id: str,
    frame_order: int,
    frame_index: int,
) -> Path:
    file_name = f"{safe_name(asset_id)}_frame_{frame_order:02d}_{frame_index:06d}.jpg"
    return frame_dir / safe_name(label) / safe_name(asset_id) / file_name


def extract_video_frames(
    row: dict,
    frame_dir: Path,
    label_column: str,
    frames_per_video: int,
    overwrite: bool,
) -> tuple[list[dict], dict]:
    video_path = Path(row.get("local_path") or row.get("file_path") or "")
    asset_id = row.get("asset_id") or video_path.stem
    label = row.get(label_column) or row.get("label") or "unknown"
    split = row.get("split") or "train"

    summary = {
        "asset_id": asset_id,
        "label": label,
        "split": split,
        "video_path": video_path.as_posix(),
        "frame_count": "0",
        "fps": "0",
        "duration_sec": "0",
        "extracted_frames": "0",
        "status": "planned",
    }

    if not video_path.exists() or not is_video(video_path):
        summary["status"] = "missing_or_not_video"
        return [], summary

    video = cv2.VideoCapture(str(video_path))
    if not video.isOpened():
        summary["status"] = "unreadable_video"
        return [], summary

    total_frames = int(video.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = float(video.get(cv2.CAP_PROP_FPS) or 0)
    duration_sec = total_frames / fps if fps > 0 else 0
    indices = selected_frame_indices(total_frames, frames_per_video)

    summary["frame_count"] = str(total_frames)
    summary["fps"] = f"{fps:.3f}"
    summary["duration_sec"] = f"{duration_sec:.3f}"

    frame_rows = []
    for frame_order, frame_index in enumerate(indices, start=1):
        output_path = frame_output_path(frame_dir, label, asset_id, frame_order, frame_index)
        extracted = output_path.exists() and not overwrite
        if not extracted:
            extracted = extract_frame(video, frame_index, output_path)

        timestamp_sec = frame_index / fps if fps > 0 else 0
        frame_rows.append(
            {
                "frame_id": f"{asset_id}_frame_{frame_order:02d}",
                "asset_id": asset_id,
                "source_video_path": video_path.as_posix(),
                "frame_path": output_path.as_posix(),
                "frame_order": str(frame_order),
                "frame_index": str(frame_index),
                "timestamp_sec": f"{timestamp_sec:.3f}",
                "frame_role": "classification_sample",
                "label": row.get("label", ""),
                "coarse_label": row.get("coarse_label", ""),
                "split": split,
                "frame_exists": str(output_path.exists()),
                "extract_status": "extracted" if extracted else "failed",
                "planned_use": "classification_training",
            }
        )

    video.release()
    summary["extracted_frames"] = str(sum(row["extract_status"] == "extracted" for row in frame_rows))
    summary["status"] = "ok" if summary["extracted_frames"] != "0" else "no_frames_extracted"
    return frame_rows, summary


def write_summary(summary_rows: list[dict], output_path: Path) -> Path:
    summary_path = output_path.with_name(output_path.stem + "_summary.csv")
    fields = [
        "asset_id",
        "label",
        "split",
        "video_path",
        "frame_count",
        "fps",
        "duration_sec",
        "extracted_frames",
        "status",
    ]
    write_csv(summary_rows, summary_path, fields)
    return summary_path


def print_summary(frame_rows: list[dict], summary_rows: list[dict], output_path: Path, summary_path: Path) -> None:
    label_counts: dict[str, int] = {}
    split_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}

    for row in frame_rows:
        label = row.get("coarse_label") or row.get("label") or "unknown"
        split = row.get("split") or "unknown"
        status = row.get("extract_status") or "unknown"
        label_counts[label] = label_counts.get(label, 0) + 1
        split_counts[split] = split_counts.get(split, 0) + 1
        status_counts[status] = status_counts.get(status, 0) + 1

    print(f"output_path: {output_path}")
    print(f"summary_path: {summary_path}")
    print(f"video_rows: {len(summary_rows)}")
    print(f"frame_rows: {len(frame_rows)}")
    print(f"label_counts: {label_counts}")
    print(f"split_counts: {split_counts}")
    print(f"extract_status_counts: {status_counts}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract frame-level classification samples from videos.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--frame-dir", type=Path, default=DEFAULT_FRAME_DIR)
    parser.add_argument("--label-column", default=DEFAULT_LABEL_COLUMN)
    parser.add_argument("--frames-per-video", type=int, default=5)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = read_csv(args.input)
    if not rows:
        raise ValueError(f"No rows found in {args.input}")

    frame_rows = []
    summary_rows = []
    for row in rows:
        extracted_rows, summary = extract_video_frames(
            row=row,
            frame_dir=args.frame_dir,
            label_column=args.label_column,
            frames_per_video=args.frames_per_video,
            overwrite=args.overwrite,
        )
        frame_rows.extend(extracted_rows)
        summary_rows.append(summary)
        print(f"{summary['status']}: {summary['asset_id']} extracted={summary['extracted_frames']}")

    fields = [
        "frame_id",
        "asset_id",
        "source_video_path",
        "frame_path",
        "frame_order",
        "frame_index",
        "timestamp_sec",
        "frame_role",
        "label",
        "coarse_label",
        "split",
        "frame_exists",
        "extract_status",
        "planned_use",
    ]
    write_csv(frame_rows, args.output, fields)
    summary_path = write_summary(summary_rows, args.output)
    print_summary(frame_rows, summary_rows, args.output, summary_path)


if __name__ == "__main__":
    main()

