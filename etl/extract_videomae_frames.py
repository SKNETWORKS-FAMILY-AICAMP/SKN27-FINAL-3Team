"""Sample 16 frames per extracted clip for VideoMAE inference.

The output manifest is the lightweight bridge between mp4 clips and the
pretrained VideoMAE model.
"""
from pathlib import Path
import argparse
import json
import math

import cv2


CLIP_DIR = Path("storage/vision/processed/clips")
OUTPUT_DIR = Path("storage/vision/processed/videomae_frames")
MANIFEST_DIR = Path("storage/vision/outputs/videomae_inputs")
DEFAULT_FRAME_COUNT = 16


def find_latest_extracted_clips() -> Path:
    manifests = sorted(CLIP_DIR.glob("extracted_clips_*.json"))
    if not manifests:
        raise FileNotFoundError(f"No extracted clip manifest found under {CLIP_DIR}")
    return manifests[-1]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def selected_indices(total_frames: int, target_count: int) -> list[int]:
    if total_frames <= 0 or target_count <= 0:
        return []
    if total_frames <= target_count:
        return list(range(total_frames))

    step = total_frames / target_count
    return [min(total_frames - 1, math.floor((idx + 0.5) * step)) for idx in range(target_count)]


def write_frame(frame, output_path: Path) -> bool:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(output_path.suffix, frame)
    if not ok:
        return False
    output_path.write_bytes(encoded.tobytes())
    return output_path.exists() and output_path.stat().st_size > 0


def sample_clip_frames(clip_path: Path, output_dir: Path, frame_count: int, overwrite: bool) -> tuple[list[dict], dict]:
    cap = cv2.VideoCapture(str(clip_path))
    if not cap.isOpened():
        return [], {"status": "failed", "message": f"Could not open clip: {clip_path}"}

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    indices = selected_indices(total_frames, frame_count)

    frame_rows = []
    clip_stem = clip_path.stem
    clip_frame_dir = output_dir / clip_stem

    for order, frame_index in enumerate(indices, start=1):
        out_path = clip_frame_dir / f"{clip_stem}_videomae_{order:02d}_{frame_index:06d}.jpg"
        ok = out_path.exists() and not overwrite
        if not ok:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            read_ok, frame = cap.read()
            ok = bool(read_ok and frame is not None and write_frame(frame, out_path))

        frame_rows.append(
            {
                "frame_order": order,
                "frame_index": frame_index,
                "timestamp_sec": round(frame_index / fps, 3) if fps > 0 else None,
                "frame_path": out_path.as_posix(),
                "frame_exists": out_path.exists(),
                "status": "ok" if ok else "failed",
            }
        )

    cap.release()
    summary = {
        "status": "ok" if frame_rows and all(row["status"] == "ok" for row in frame_rows) else "partial",
        "total_frames": total_frames,
        "fps": round(fps, 3),
        "width": width,
        "height": height,
        "sampled_frames": len(frame_rows),
        "target_frames": frame_count,
    }
    return frame_rows, summary


def build_videomae_inputs(
    extracted_clips_path: Path,
    output_dir: Path,
    manifest_dir: Path,
    frame_count: int,
    overwrite: bool,
) -> tuple[Path, dict]:
    data = load_json(extracted_clips_path)
    manifest_dir.mkdir(parents=True, exist_ok=True)

    clips = []
    for clip in data.get("clips", []):
        clip_path = Path(clip.get("clip_path", ""))
        frame_rows, summary = sample_clip_frames(clip_path, output_dir, frame_count, overwrite)
        clips.append(
            {
                "clip_id": clip.get("clip_id"),
                "source_video": clip.get("source_video"),
                "clip_path": clip_path.as_posix(),
                "clip_start_sec": clip.get("clip_start_sec"),
                "clip_end_sec": clip.get("clip_end_sec"),
                "clip_duration_sec": clip.get("clip_duration_sec"),
                "basis": clip.get("basis"),
                "planned_use": "videomae_comparison_poc",
                "videomae_input": {
                    "frame_count": frame_count,
                    "sampling": "uniform",
                    "frames": frame_rows,
                },
                "metadata": summary,
            }
        )
        print(f"{summary['status']} {clip.get('clip_id')} frames={len(frame_rows)} clip={clip_path}")

    output = {
        "schema_version": "videomae-input-manifest-v1",
        "source_extracted_clips": extracted_clips_path.as_posix(),
        "clip_count": len(clips),
        "target_frame_count": frame_count,
        "clips": clips,
    }

    source_stem = Path(data.get("source_video", "clips")).stem
    output_path = manifest_dir / f"videomae_clip_manifest_{source_stem}.json"
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path, output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract fixed frame sequences for VideoMAE POC input.")
    parser.add_argument("--extracted-clips", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--manifest-dir", type=Path, default=MANIFEST_DIR)
    parser.add_argument("--frame-count", type=int, default=DEFAULT_FRAME_COUNT)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    extracted_clips_path = args.extracted_clips or find_latest_extracted_clips()
    output_path, output = build_videomae_inputs(
        extracted_clips_path=extracted_clips_path,
        output_dir=args.output_dir,
        manifest_dir=args.manifest_dir,
        frame_count=args.frame_count,
        overwrite=args.overwrite,
    )

    print(f"extracted_clips_path: {extracted_clips_path}")
    print(f"videomae_manifest_path: {output_path}")
    print(f"clip_count: {output['clip_count']}")
    print(f"target_frame_count: {output['target_frame_count']}")


if __name__ == "__main__":
    main()
