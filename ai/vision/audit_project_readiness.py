"""Audit local Vision artifacts and experiment readiness."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path


METADATA_FIELDS = ("incident_id", "viewpoint", "lighting", "visible_target")
EXP4 = Path(
    "storage/vision/models/videomae_raw_video/"
    "per_label_100_exp4_32frames_adaptive_labeled/videomae_cls_20260722_145601"
)
SPLIT = Path("storage/vision/manifests/videomae_labeled_fixed100_split.csv")
METADATA_SPLIT = Path("storage/vision/manifests/videomae_labeled_fixed100_metadata.csv")
CHECKPOINT_FILES = (
    "config.json",
    "preprocessor_config.json",
    "class_mapping.json",
    "run_config.json",
    "training_history.csv",
    "evaluation/test_metrics.json",
    "evaluation/test_predictions.csv",
    "evaluation/confusion_matrix.csv",
    "evaluation/confusion_matrix.png",
    "evaluation/misclassified_videos.csv",
)


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def audit_artifacts(paths: list[Path]) -> list[dict]:
    result = []
    for path in paths:
        item = {"path": path.as_posix(), "exists": path.is_file()}
        if item["exists"]:
            with path.open("rb") as file:
                item.update(size_bytes=path.stat().st_size, sha256=hashlib.file_digest(file, "sha256").hexdigest())
        result.append(item)
    return result


def audit_manifest(path: Path) -> dict:
    rows = read_csv(path)
    missing = {
        field: sum(not row.get(field, "").strip() or row.get(field, "").strip().lower() == "unknown" for row in rows)
        for field in METADATA_FIELDS
    }
    incident_splits: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        incident = row.get("incident_id", "").strip()
        split = row.get("split", "").strip()
        if incident and split:
            incident_splits[incident].add(split)
    leaks = {
        incident: sorted(splits)
        for incident, splits in incident_splits.items()
        if len(splits) > 1
    }
    integrity = (
        "unverifiable"
        if missing["incident_id"]
        else "leak_detected"
        if leaks
        else "verified_no_split_leak"
    )
    return {
        "path": path.as_posix(),
        "row_count": len(rows),
        "missing_or_unknown": missing,
        "incident_split_leaks": leaks,
        "incident_integrity": integrity,
    }


def audit_qwen_results(paths: list[Path]) -> dict:
    rows = [row for path in paths for row in read_csv(path)]
    frame_counts = sorted(
        {
            int(value)
            for row in rows
            if (value := row.get("qwen_input_frame_count", "").strip()).isdigit()
        }
    )
    return {
        "row_count": len(rows),
        "input_frame_counts": frame_counts,
        "files": [path.as_posix() for path in paths],
    }


def build_readiness_report(root: Path) -> dict:
    root = root.resolve()
    checkpoint = root / EXP4
    split = root / SPLIT
    manifest_path = root / METADATA_SPLIT if (root / METADATA_SPLIT).is_file() else split
    required = [checkpoint / name for name in CHECKPOINT_FILES]
    weights = [checkpoint / "model.safetensors", checkpoint / "pytorch_model.bin"]
    artifacts = audit_artifacts([split, *required, *weights])
    qwen_files = sorted(
        (
            root
            / "storage/vision/outputs/category_yolo_qwen_compare"
        ).rglob("qwen_yolo_compare_results.csv")
    )
    qwen_files = [path for path in qwen_files if "32frames" in path.as_posix()]
    llava_files = sorted(
        path
        for path in (
            root / "storage/vision/outputs/category_yolo_qwen_compare"
        ).rglob("llava_yolo_compare_results.csv")
        if "32frames" in path.as_posix()
    )
    qwen = audit_qwen_results(qwen_files)
    llava = audit_qwen_results(llava_files)
    manifest = audit_manifest(manifest_path) if manifest_path.is_file() else {
        "path": manifest_path.as_posix(),
        "row_count": 0,
        "missing_or_unknown": {},
        "incident_split_leaks": {},
        "error": "missing",
    }
    checkpoint_ready = all(path.is_file() for path in required) and any(path.is_file() for path in weights)
    metadata_ready = bool(manifest["row_count"]) and not any(manifest["missing_or_unknown"].values())
    return {
        "root": root.as_posix(),
        "frame_count": 32,
        "artifacts": artifacts,
        "manifest": manifest,
        "qwen": qwen,
        "llava": llava,
        "readiness": {
            "exp4_checkpoint": checkpoint_ready,
            "fixed_split": split.is_file(),
            "metadata_complete": metadata_ready,
            "incident_split_isolated": manifest.get("incident_integrity") == "verified_no_split_leak",
            "qwen_32_frame_results": qwen["row_count"] == 400 and 32 in qwen["input_frame_counts"],
            "llava_32_frame_results": llava["row_count"] == 400 and 32 in llava["input_frame_counts"],
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("storage/vision/reports/vision_readiness_20260723.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_readiness_report(args.root)
    output = args.output if args.output.is_absolute() else args.root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["readiness"], ensure_ascii=False, indent=2))
    print(f"output: {output}")


if __name__ == "__main__":
    main()
