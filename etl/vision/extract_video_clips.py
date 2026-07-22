"""Cut event candidate clips from the source accident video.

The clip manifest records exact time ranges and output paths for later frame
sampling or manual review.
"""
from pathlib import Path
import argparse
import json

import cv2


CLIP_CANDIDATE_DIR = Path("storage/vision/outputs/clip_candidates")
CLIP_OUTPUT_DIR = Path("storage/vision/processed/clips")


def find_latest_clip_candidates() -> Path:
    outputs = sorted(CLIP_CANDIDATE_DIR.glob("clip_candidates_*.json"))
    if not outputs:
        raise FileNotFoundError(f"No clip candidate JSON found under {CLIP_CANDIDATE_DIR}")
    return outputs[-1]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_path(path_text: str, root_dir: Path) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else root_dir / path


def write_clip(source_video: Path, output_path: Path, start_sec: float, end_sec: float) -> dict:
    cap = cv2.VideoCapture(str(source_video))
    if not cap.isOpened():
        return {"status": "failed", "message": f"Could not open video: {source_video}"}

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    duration_sec = total_frames / fps if fps > 0 else 0.0

    if fps <= 0 or total_frames <= 0 or width <= 0 or height <= 0:
        cap.release()
        return {"status": "failed", "message": "Invalid video metadata"}

    start_sec = max(0.0, min(start_sec, duration_sec))
    end_sec = max(start_sec, min(end_sec, duration_sec))
    start_frame = int(round(start_sec * fps))
    end_frame = min(total_frames - 1, int(round(end_sec * fps)))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(output_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )

    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    written = 0
    for _frame_index in range(start_frame, end_frame + 1):
        ok, frame = cap.read()
        if not ok or frame is None:
            break
        writer.write(frame)
        written += 1

    writer.release()
    cap.release()

    if written == 0 or not output_path.exists() or output_path.stat().st_size == 0:
        return {"status": "failed", "message": "No frames written"}

    return {
        "status": "ok",
        "fps": round(fps, 3),
        "source_duration_sec": round(duration_sec, 3),
        "clip_start_sec": round(start_sec, 3),
        "clip_end_sec": round(end_sec, 3),
        "written_frames": written,
        "clip_path": output_path.as_posix(),
    }


def extract_clips(candidate_path: Path, output_dir: Path, root_dir: Path, overwrite: bool) -> tuple[Path, dict]:
    data = load_json(candidate_path)
    source_video = resolve_path(data["source_video"], root_dir)
    source_stem = source_video.stem
    results = []

    for item in data.get("clip_candidates", []):
        clip_id = item["clip_id"]
        output_path = output_dir / f"{source_stem}_{clip_id}.mp4"
        if output_path.exists() and output_path.stat().st_size > 0 and not overwrite:
            extraction = {"status": "exists", "clip_path": output_path.as_posix()}
        else:
            extraction = write_clip(source_video, output_path, item["clip_start_sec"], item["clip_end_sec"])

        copied = dict(item)
        copied.update(extraction)
        if copied.get("clip_start_sec") is not None and copied.get("clip_end_sec") is not None:
            copied["clip_duration_sec"] = round(float(copied["clip_end_sec"]) - float(copied["clip_start_sec"]), 3)
        results.append(copied)

    output = {
        "source_clip_candidates": candidate_path.as_posix(),
        "source_video": source_video.as_posix(),
        "schema_version": "extracted-clips-v1",
        "clip_count": len(results),
        "clips": results,
    }
    output_path = output_dir / f"extracted_clips_{source_stem}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path, output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract mp4 clips from clip candidate JSON.")
    parser.add_argument("--clip-candidates", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=CLIP_OUTPUT_DIR)
    parser.add_argument("--root-dir", type=Path, default=Path("."))
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    candidate_path = args.clip_candidates or find_latest_clip_candidates()
    output_path, output = extract_clips(candidate_path, args.output_dir, args.root_dir, args.overwrite)

    print(f"clip_candidates_path: {candidate_path}")
    print(f"extracted_clips_path: {output_path}")
    print(f"clip_count: {output['clip_count']}")
    for item in output["clips"]:
        print(f"{item['status']} {item['clip_id']} -> {item.get('clip_path')} frames={item.get('written_frames', '')}")


if __name__ == "__main__":
    main()



