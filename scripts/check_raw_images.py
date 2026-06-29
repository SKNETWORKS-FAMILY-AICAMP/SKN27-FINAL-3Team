"""Check whether raw sample image files can be opened.

Used at the first ingestion stage after Google Drive download.
"""
from pathlib import Path
from PIL import Image

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
RAW_DIR = Path("storage/vision/raw")
MAX_CHECK = 20


def is_image(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS


def check_image(path: Path) -> tuple[bool, str]:
    try:
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            return True, f"{img.width}x{img.height} {img.mode}"
    except Exception as exc:
        return False, str(exc)


def main() -> int:
    if not RAW_DIR.exists():
        print(f"RAW directory not found: {RAW_DIR}")
        return 1

    image_paths = sorted(path for path in RAW_DIR.rglob("*") if is_image(path))
    print(f"raw_dir: {RAW_DIR}")
    print(f"found_images: {len(image_paths)}")

    if not image_paths:
        print("No image files found. Put 10 sample images under storage/vision/raw first.")
        return 1

    checked = image_paths[:MAX_CHECK]
    failures = 0

    for path in checked:
        ok, detail = check_image(path)
        status = "OK" if ok else "FAIL"
        if not ok:
            failures += 1
        print(f"{status:<4} {path.as_posix()} | {detail}")

    print(f"checked_images: {len(checked)}")
    print(f"failed_images: {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
