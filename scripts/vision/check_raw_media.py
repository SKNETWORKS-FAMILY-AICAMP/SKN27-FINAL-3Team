"""Validate raw image and video readability before running Vision steps.

Use this first on RunPod/local storage to catch missing files or broken media.
"""
from pathlib import Path

import cv2
from PIL import Image


RAW_DIR = Path("storage/vision/raw")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}


def check_image(path: Path):
    try:
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            return True, f"image {img.width}x{img.height} {img.mode}"
    except Exception as exc:
        return False, str(exc)


def check_video(path: Path):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return False, "video open failed"

    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    ok, frame = cap.read()
    cap.release()

    if not ok or frame is None:
        return False, "first frame read failed"

    return True, f"video {width}x{height} fps={fps:.2f} frames={frame_count}"


def main():
    media_paths = sorted(
        p
        for p in RAW_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
    )

    print(f"raw_dir: {RAW_DIR}")
    print(f"found_media: {len(media_paths)}")

    failures = 0

    for path in media_paths:
        suffix = path.suffix.lower()

        if suffix in IMAGE_EXTENSIONS:
            ok, detail = check_image(path)
        elif suffix in VIDEO_EXTENSIONS:
            ok, detail = check_video(path)
        else:
            continue

        status = "OK" if ok else "FAIL"
        if not ok:
            failures += 1

        print(f"{status:<4} {path.as_posix()} | {detail}")

    print(f"failed_media: {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

