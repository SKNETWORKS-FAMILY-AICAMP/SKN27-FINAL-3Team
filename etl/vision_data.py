"""Create the first sample image manifest from storage/vision/raw.

This records file existence and image readability for ingestion POC.
"""
from pathlib import Path
import csv

from PIL import Image


RAW_DIR = Path("storage/vision/raw")
MANIFEST_PATH = Path("storage/vision/manifests/sample_manifest.csv")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def is_image(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS


def media_readable(path: Path) -> bool:
    try:
        with Image.open(path) as img:
            img.verify()
        return True
    except Exception:
        return False


def main():
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)

    image_paths = sorted(path for path in RAW_DIR.rglob("*") if is_image(path))

    fields = [
        "asset_id",
        "dataset_name",
        "input_type",
        "file_path",
        "label_path",
        "file_exists",
        "media_readable",
        "planned_use",
    ]

    with MANIFEST_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()

        for idx, path in enumerate(image_paths, start=1):
            writer.writerow(
                {
                    "asset_id": f"sample_{idx:06d}",
                    "dataset_name": "drive_sample_10",
                    "input_type": "image",
                    "file_path": path.as_posix(),
                    "label_path": "",
                    "file_exists": path.exists(),
                    "media_readable": media_readable(path),
                    "planned_use": "runpod_drive_ingestion_poc",
                }
            )

    print(f"manifest_path: {MANIFEST_PATH}")
    print(f"manifest_rows: {len(image_paths)}")


if __name__ == "__main__":
    main()

