import csv
from datetime import datetime
from pathlib import Path


ROOT = Path("/workspace/SKN27-FINAL-3Team/storage/vision/outputs/category_yolo_qwen_compare")
CATEGORIES = ("car_vs_car", "car_vs_pedestrian", "car_vs_motorcycle", "car_vs_bicycle")
TARGET_PER_CATEGORY = 300


def language_valid(text: str) -> bool:
    return not any(
        char.isalpha()
        and not (
            "A" <= char <= "Z"
            or "a" <= char <= "z"
            or "\u1100" <= char <= "\u11ff"
            or "\u3130" <= char <= "\u318f"
            or "\uac00" <= char <= "\ud7ff"
        )
        for char in text
    )


print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
print("[QWEN 32-frame · SCHEMA/LANGUAGE-VALID]")
total = 0
for category in CATEGORIES:
    path = ROOT / category / "known_label_adaptive_32frames/qwen_yolo_compare_results.csv"
    rows = []
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file))
    valid = {
        row["asset_id"]
        for row in rows
        if row.get("qwen_json_valid", "").lower() == "true"
        and row.get("qwen_input_frame_count") == "32"
        and language_valid(row.get("raw_output_text", ""))
    }
    total += len(valid)
    filled = min(20, len(valid) * 20 // TARGET_PER_CATEGORY)
    print(
        f"{category:22} |{'#' * filled}{'-' * (20 - filled)}| "
        f"{len(valid):3}/{TARGET_PER_CATEGORY}"
    )

target_total = TARGET_PER_CATEGORY * len(CATEGORIES)
filled = min(20, total * 20 // target_total)
print(
    f"{'TOTAL':22} |{'#' * filled}{'-' * (20 - filled)}| "
    f"{total:4}/{target_total} {total / target_total * 100:5.1f}%"
)
