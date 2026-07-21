"""Extract representative key frames from a raw accident video.

This is the first Vision POC step: read one video, sample frames, and write
metadata for later detection/schema conversion.
"""
from pathlib import Path
import json

import cv2


RAW_DIR = Path("storage/vision/raw")
FRAME_DIR = Path("storage/vision/processed/frames")
OUTPUT_DIR = Path("storage/vision/outputs")

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}


def find_first_video() -> Path:
    videos = sorted(
        path
        for path in RAW_DIR.rglob("*")
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    )
    if not videos:
        raise FileNotFoundError(f"No video files found under {RAW_DIR}")
    return videos[0]


def extract_keyframes(video_path: Path, frame_count_target: int = 5):
    FRAME_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if total_frames <= 0:
        raise RuntimeError(f"Invalid frame count: {video_path}")

    if frame_count_target <= 1:
        target_indices = [0]
    else:
        target_indices = [
            round(i * (total_frames - 1) / (frame_count_target - 1))
            for i in range(frame_count_target)
        ]

    video_stem = video_path.stem
    records = []

    for order, frame_index in enumerate(target_indices, start=1):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()

        if not ok or frame is None:
            records.append(
                {
                    "frame_order": order,
                    "frame_index": frame_index,
                    "timestamp_sec": None,
                    "frame_role": "sample_keyframe",
                    "frame_path": None,
                    "status": "failed",
                }
            )
            continue

        timestamp_sec = frame_index / fps if fps > 0 else None
        frame_name = f"{video_stem}_frame_{order:02d}_{frame_index:06d}.jpg"
        frame_path = FRAME_DIR / frame_name

        cv2.imwrite(str(frame_path), frame)

        records.append(
            {
                "frame_order": order,
                "frame_index": frame_index,
                "timestamp_sec": round(timestamp_sec, 3)
                if timestamp_sec is not None
                else None,
                "frame_role": "sample_keyframe",
                "frame_path": frame_path.as_posix(),
                "status": "ok",
            }
        )

    cap.release()

    output = {
        "source_video": video_path.as_posix(),
        "video_metadata": {
            "total_frames": total_frames,
            "fps": fps,
            "width": width,
            "height": height,
        },
        "keyframes": records,
    }

    output_path = OUTPUT_DIR / f"keyframes_{video_stem}.json"
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return output_path, output


def main():
    video_path = find_first_video()
    output_path, output = extract_keyframes(video_path, frame_count_target=5)

    print(f"source_video: {output['source_video']}")
    print(f"total_frames: {output['video_metadata']['total_frames']}")
    print(f"fps: {output['video_metadata']['fps']}")
    print(f"keyframe_count: {len(output['keyframes'])}")
    print(f"output_path: {output_path}")

    for item in output["keyframes"]:
        print(
            f"{item['status']} "
            f"frame_index={item['frame_index']} "
            f"timestamp_sec={item['timestamp_sec']} "
            f"path={item['frame_path']}"
        )


if __name__ == "__main__":
    main()
