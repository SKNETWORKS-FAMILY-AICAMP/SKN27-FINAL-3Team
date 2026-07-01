"""Build the full classification candidate manifest from Drive listing JSON.

This turns nested AI-Hub Drive metadata into flat rows that can be sampled and
used by the training pipeline.
"""
from pathlib import Path
import argparse
import json
import re

from utils import write_csv


DEFAULT_LISTING_PATH = Path("storage/vision/manifests/drive_listing_aihub.json")
DEFAULT_OUTPUT_PATH = Path(
    "storage/vision/datasets/classification/manifests/classification_manifest.csv"
)
TARGET_PREFIX = "Ai_Hub/Train/"
MEDIA_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
COARSE_LABELS = ("차대차", "차대보행자", "차대이륜차", "차대자전거")


def normalize_path(path: str) -> str:
    return path.replace("\\", "/").strip()


def fine_label(category: str) -> str:
    label = category
    if label.startswith("TS_"):
        label = label[3:]
    label = label.replace("영상_", "")
    label = re.sub(r"\s+", "_", label)
    return label


def coarse_label(category: str) -> str:
    for label in COARSE_LABELS:
        if label in category:
            return label
    return "unknown"


def infer_input_type(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    return "unknown"


def is_supported_media(path: str) -> bool:
    return Path(path).suffix.lower() in MEDIA_EXTENSIONS


def parse_aihub_train_item(item: dict) -> dict | None:
    source_path = normalize_path(item.get("path", ""))
    if not source_path.startswith(TARGET_PREFIX):
        return None
    if not is_supported_media(source_path):
        return None

    parts = source_path.split("/")
    if len(parts) < 4:
        return None

    category = parts[2]
    file_name = parts[-1]
    input_type = infer_input_type(source_path)

    return {
        "dataset_name": "Ai_Hub",
        "source_dataset": "Ai_Hub/Train",
        "category": category,
        "label": fine_label(category),
        "coarse_label": coarse_label(category),
        "input_type": input_type,
        "source_path": source_path,
        "drive_url": item.get("url", ""),
        "file_name": file_name,
        "file_ext": Path(file_name).suffix.lower(),
        "local_path": "",
        "sample_group": "full_candidate",
        "split": "",
        "file_exists": "",
        "media_readable": "",
        "planned_use": "classification_frame_extraction",
    }


def build_manifest(listing_path: Path) -> list[dict]:
    items = json.loads(listing_path.read_text(encoding="utf-8-sig"))
    rows = []

    for item in items:
        row = parse_aihub_train_item(item)
        if row is None:
            continue
        row["asset_id"] = f"aihub_train_{len(rows) + 1:08d}"
        rows.append(row)

    return rows


MANIFEST_FIELDS = [
    "asset_id",
    "dataset_name",
    "source_dataset",
    "category",
    "label",
    "coarse_label",
    "input_type",
    "source_path",
    "drive_url",
    "file_name",
    "file_ext",
    "local_path",
    "sample_group",
    "split",
    "file_exists",
    "media_readable",
    "planned_use",
]


def print_summary(rows: list[dict], output_path: Path) -> None:
    category_counts: dict[str, int] = {}
    coarse_counts: dict[str, int] = {}
    input_type_counts: dict[str, int] = {}

    for row in rows:
        category_counts[row["category"]] = category_counts.get(row["category"], 0) + 1
        coarse_counts[row["coarse_label"]] = coarse_counts.get(row["coarse_label"], 0) + 1
        input_type_counts[row["input_type"]] = input_type_counts.get(row["input_type"], 0) + 1

    print(f"output_path: {output_path}")
    print(f"total_rows: {len(rows)}")
    print(f"input_type_counts: {input_type_counts}")
    print("coarse_label_counts:")
    for label, count in sorted(coarse_counts.items()):
        print(f"  {count}\t{label}")
    print("category_counts:")
    for category, count in sorted(category_counts.items()):
        print(f"  {count}\t{category}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build AI-Hub classification candidate manifest from gdown listing JSON.")
    parser.add_argument("--listing", type=Path, default=DEFAULT_LISTING_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = build_manifest(args.listing)
    write_csv(rows, args.output, MANIFEST_FIELDS)
    print_summary(rows, args.output)


if __name__ == "__main__":
    main()


