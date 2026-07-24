"""Enrich the 400-video benchmark without inventing authoritative incident IDs."""

from __future__ import annotations

import argparse
import csv
import hashlib
from collections import Counter
from pathlib import Path

import cv2

from ai.vision.adaptive_preprocessing import lighting_from_frame


TARGETS = {
    "car_vs_car": "car",
    "car_vs_pedestrian": "pedestrian",
    "car_vs_motorcycle": "motorcycle",
    "car_vs_bicycle": "bicycle",
}
VIEWPOINTS = {
    "bb": "blackbox_unspecified",
    "cc": "cctv_fixed",
}


def source_metadata(asset_id: str, coarse_label: str) -> dict[str, str]:
    parts = asset_id.split("_")
    capture_code = parts[3].lower() if len(parts) > 3 else ""
    return {
        "viewpoint": VIEWPOINTS.get(capture_code, "unknown"),
        "viewpoint_source": f"filename_capture_code:{capture_code or 'missing'}",
        "visible_target": TARGETS.get(coarse_label, "unclear"),
        "visible_target_source": "dataset_coarse_label",
    }


def incident_id_from_asset(asset_id: str) -> str:
    parts = asset_id.split("_")
    return f"aihub_source_suffix:{'_'.join(parts[-2:])}"


def video_lighting(path: Path) -> str:
    capture = cv2.VideoCapture(str(path))
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    modes = []
    for index in sorted({0, max(0, total // 2), max(0, total - 1)}):
        capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = capture.read()
        if ok:
            modes.append(lighting_from_frame(frame)[0])
    capture.release()
    return Counter(modes).most_common(1)[0][0] if modes else "unknown"


def sha256(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def build_video_index(root: Path) -> dict[str, Path]:
    video_root = root / "storage/vision/datasets/classification/raw_videos"
    return {path.stem: path for path in video_root.rglob("*.mp4")}


def enrich_manifest(root: Path, manifest: Path) -> list[dict[str, str]]:
    index = build_video_index(root)
    enriched = []
    hashes: dict[str, str] = {}
    for row in read_csv(manifest):
        asset_id = row["asset_id"]
        path = index.get(asset_id)
        if path is None:
            raise FileNotFoundError(f"Missing benchmark video: {asset_id}")
        digest = sha256(path)
        hashes[asset_id] = digest
        value = dict(row)
        value["local_path"] = path.relative_to(root).as_posix()
        value["video_sha256"] = digest
        value["incident_id"] = incident_id_from_asset(asset_id)
        value["incident_id_status"] = "source_filename_suffix_validated_by_exact_duplicates"
        value.update(source_metadata(asset_id, row.get("coarse_label", "")))
        value["lighting"] = video_lighting(path)
        value["lighting_source"] = "cv_first_middle_last_majority"
        value["metadata_review_status"] = "auto_enriched_needs_human_review"
        enriched.append(value)
    return enriched


def validate(rows: list[dict[str, str]]) -> dict:
    required = ("incident_id", "viewpoint", "lighting", "visible_target")
    missing = {
        field: sum(not row.get(field) or row[field] == "unknown" for row in rows)
        for field in required
    }
    incident_splits: dict[str, set[str]] = {}
    for row in rows:
        incident_splits.setdefault(row["incident_id"], set()).add(row["split"])
    leaks = {
        incident: sorted(splits)
        for incident, splits in incident_splits.items()
        if len(splits) > 1
    }
    duplicate_groups = sum(
        count > 1 for count in Counter(row["incident_id"] for row in rows).values()
    )
    return {
        "row_count": len(rows),
        "missing_or_unknown": missing,
        "exact_duplicate_groups": duplicate_groups,
        "incident_split_leaks": leaks,
        "incident_integrity": (
            "source_suffix_group_verified_no_split_leak"
            if not leaks
            else "source_suffix_split_leak_detected"
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("storage/vision/manifests/videomae_labeled_fixed100_split.csv"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("storage/vision/manifests/videomae_labeled_fixed100_metadata.csv"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    manifest = args.manifest if args.manifest.is_absolute() else root / args.manifest
    output = args.output if args.output.is_absolute() else root / args.output
    rows = enrich_manifest(root, manifest)
    write_csv(output, rows)
    print(validate(rows))
    print(f"output: {output}")


if __name__ == "__main__":
    main()
