"""Audit cached category results against the fixed 100-video YOLO set."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from ai.vision.category_vlm_config import BEST_YOLO_MODELS


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def is_true(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def missing_rows(root: Path, category: str) -> list[dict[str, str]]:
    directory = root / category
    yolo_rows = read_csv(directory / "yolo_summary.csv")
    qwen_rows = read_csv(directory / "qwen_yolo_compare_results.csv")
    exact_by_asset = {
        row.get("asset_id", ""): row
        for row in qwen_rows
        if row.get("yolo_model") == BEST_YOLO_MODELS[category]
    }
    missing = []
    for row in yolo_rows:
        asset_id = row.get("asset_id", "")
        result = exact_by_asset.get(asset_id)
        if result and is_true(result.get("qwen_json_valid")):
            continue
        missing.append({
            "category": category,
            "asset_id": asset_id,
            "local_path": row.get("local_path", ""),
            "yolo_model": BEST_YOLO_MODELS[category],
            "reason": "qwen_json_invalid" if result else "missing_selected_yolo_result",
        })
    return missing


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["category", "asset_id", "local_path", "yolo_model", "reason"]
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def audit_category(root: Path, category: str) -> dict[str, object]:
    directory = root / category
    yolo_rows = read_csv(directory / "yolo_summary.csv")
    qwen_rows = read_csv(directory / "qwen_yolo_compare_results.csv")
    expected_model = BEST_YOLO_MODELS[category]
    yolo_by_asset = {row.get("asset_id", ""): row.get("yolo_model", "") for row in yolo_rows}
    exact = [
        row for row in qwen_rows
        if row.get("asset_id") in yolo_by_asset
        and row.get("yolo_model") == yolo_by_asset[row["asset_id"]]
    ]
    valid_assets = {
        row["asset_id"] for row in exact
        if row.get("asset_id") and is_true(row.get("qwen_json_valid"))
    }
    target_assets = set(yolo_by_asset)
    return {
        "category": category,
        "expected_yolo_model": expected_model,
        "yolo_rows": len(yolo_rows),
        "yolo_unique_assets": len(target_assets),
        "qwen_rows": len(qwen_rows),
        "qwen_exact_model_rows": len(exact),
        "qwen_valid_assets": len(valid_assets),
        "qwen_remaining_assets": len(target_assets - valid_assets),
        "complete": len(target_assets) == 100 and target_assets == valid_assets,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("storage/vision/outputs/category_yolo_qwen_compare"),
    )
    parser.add_argument("--write-missing-dir", type=Path)
    args = parser.parse_args()
    result = [audit_category(args.root, category) for category in BEST_YOLO_MODELS]
    if args.write_missing_dir:
        for category in BEST_YOLO_MODELS:
            write_csv(
                args.write_missing_dir / f"qwen_remaining_{category}.csv",
                missing_rows(args.root, category),
            )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not all(row["complete"] for row in result):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
