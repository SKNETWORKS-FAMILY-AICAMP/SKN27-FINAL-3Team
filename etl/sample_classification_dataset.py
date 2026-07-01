"""Sample the classification manifest into coarse accident labels.

The current training plan uses four top-level labels and a fixed split so the
same sample can be reused across experiments.
"""
from pathlib import Path
import argparse
import random
from collections import defaultdict

from utils import read_csv, write_csv


DEFAULT_INPUT_PATH = Path(
    "storage/vision/datasets/classification/manifests/classification_manifest.csv"
)
DEFAULT_OUTPUT_PATH = Path(
    "storage/vision/datasets/classification/manifests/sample_700_coarse_manifest.csv"
)
DEFAULT_LABEL_COLUMN = "coarse_label"


def group_by_label(rows: list[dict], label_column: str) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        label = row.get(label_column, "") or "unknown"
        grouped[label].append(row)
    return grouped


def split_rows(
    rows: list[dict],
    train_ratio: float,
    val_ratio: float,
) -> list[dict]:
    total = len(rows)
    train_count = int(total * train_ratio)
    val_count = int(total * val_ratio)

    split_rows_out = []
    for idx, row in enumerate(rows):
        copied = dict(row)
        if idx < train_count:
            copied["split"] = "train"
        elif idx < train_count + val_count:
            copied["split"] = "val"
        else:
            copied["split"] = "test"
        split_rows_out.append(copied)

    return split_rows_out


def sample_by_label(
    rows: list[dict],
    label_column: str,
    per_label: int,
    seed: int,
    train_ratio: float,
    val_ratio: float,
) -> tuple[list[dict], list[dict]]:
    rng = random.Random(seed)
    grouped = group_by_label(rows, label_column)
    sampled_rows = []
    summary_rows = []

    for label in sorted(grouped):
        label_rows = list(grouped[label])
        original_count = len(label_rows)
        rng.shuffle(label_rows)
        selected = label_rows[:per_label]
        sampled_count = len(selected)

        selected = split_rows(selected, train_ratio, val_ratio)
        category_counts: dict[str, int] = {}

        for idx, row in enumerate(selected, start=1):
            row["sample_group"] = f"sample_{per_label}_per_{label_column}"
            row["sample_label_column"] = label_column
            row["sample_rank_in_label"] = str(idx)
            category = row.get("category", "unknown")
            category_counts[category] = category_counts.get(category, 0) + 1
            sampled_rows.append(row)

        split_counts = {"train": 0, "val": 0, "test": 0}
        for row in selected:
            split_counts[row["split"]] += 1

        summary_rows.append(
            {
                "label_column": label_column,
                "sample_label": label,
                "original_count": original_count,
                "sampled_count": sampled_count,
                "train_count": split_counts["train"],
                "val_count": split_counts["val"],
                "test_count": split_counts["test"],
                "sample_policy": "all" if original_count <= per_label else "random_sample",
                "category_count": len(category_counts),
                "category_distribution": jsonish(category_counts),
            }
        )

    return sampled_rows, summary_rows


def jsonish(values: dict[str, int]) -> str:
    return "; ".join(f"{key}:{values[key]}" for key in sorted(values))


def write_summary(summary_rows: list[dict], output_path: Path) -> Path:
    summary_path = output_path.with_name(output_path.stem + "_summary.csv")
    fields = [
        "label_column",
        "sample_label",
        "original_count",
        "sampled_count",
        "train_count",
        "val_count",
        "test_count",
        "sample_policy",
        "category_count",
        "category_distribution",
    ]
    write_csv(summary_rows, summary_path, fields)
    return summary_path


def print_summary(sampled_rows: list[dict], summary_rows: list[dict], output_path: Path, summary_path: Path) -> None:
    split_counts = {"train": 0, "val": 0, "test": 0}
    for row in sampled_rows:
        split_counts[row["split"]] += 1

    print(f"output_path: {output_path}")
    print(f"summary_path: {summary_path}")
    print(f"sampled_rows: {len(sampled_rows)}")
    print(f"label_count: {len(summary_rows)}")
    print(f"split_counts: {split_counts}")
    print("label_summary:")
    for row in summary_rows:
        print(
            f"  original={row['original_count']} "
            f"sampled={row['sampled_count']} "
            f"train={row['train_count']} "
            f"val={row['val_count']} "
            f"test={row['test_count']} "
            f"label={row['sample_label']}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sample classification manifest by coarse label.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--label-column", default=DEFAULT_LABEL_COLUMN)
    parser.add_argument("--per-label", type=int, default=700)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-ratio", type=float, default=0.7)
    parser.add_argument("--val-ratio", type=float, default=0.2)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = read_csv(args.input)
    if not rows:
        raise ValueError(f"No rows found in {args.input}")
    if args.label_column not in rows[0]:
        raise ValueError(f"Label column not found: {args.label_column}")

    sampled_rows, summary_rows = sample_by_label(
        rows=rows,
        label_column=args.label_column,
        per_label=args.per_label,
        seed=args.seed,
        train_ratio=args.train_ratio,
        val_ratio=args.val_ratio,
    )

    fields = list(rows[0].keys())
    for field in ["sample_label_column", "sample_rank_in_label"]:
        if field not in fields:
            fields.append(field)

    write_csv(sampled_rows, args.output, fields)
    summary_path = write_summary(summary_rows, args.output)
    print_summary(sampled_rows, summary_rows, args.output, summary_path)


if __name__ == "__main__":
    main()

