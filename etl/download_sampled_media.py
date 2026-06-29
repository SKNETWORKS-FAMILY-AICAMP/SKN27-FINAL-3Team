"""Download a small subset of sampled Drive media for local dry-run validation.

Reads sample_500_coarse_manifest.csv and downloads only N items per coarse_label.
Use this before downloading thousands of videos on RunPod.
"""
from pathlib import Path
import argparse

from urllib.request import urlopen, Request
from urllib.parse import parse_qs, urlparse
import shutil

from utils import read_csv, safe_name, write_csv


DEFAULT_INPUT_PATH = Path(
    "storage/vision/datasets/classification/manifests/sample_500_coarse_manifest.csv"
)
DEFAULT_OUTPUT_PATH = Path(
    "storage/vision/datasets/classification/manifests/dryrun_download_manifest.csv"
)
DEFAULT_DOWNLOAD_DIR = Path("storage/vision/datasets/classification/raw_videos")
DEFAULT_LABEL_COLUMN = "coarse_label"


def select_per_label(rows: list[dict], label_column: str, per_label: int, split: str | None) -> list[dict]:
    selected = []
    counts: dict[str, int] = {}

    for row in rows:
        if split and row.get("split") != split:
            continue

        label = row.get(label_column, "unknown") or "unknown"
        if counts.get(label, 0) >= per_label:
            continue

        selected.append(dict(row))
        counts[label] = counts.get(label, 0) + 1

    return selected


def local_video_path(row: dict, download_dir: Path, label_column: str) -> Path:
    label = safe_name(row.get(label_column, "unknown") or "unknown")
    asset_id = row.get("asset_id", "asset")
    file_name = safe_name(row.get("file_name", f"{asset_id}.mp4"))
    return download_dir / label / f"{asset_id}_{file_name}"


def direct_download_url(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    file_id = query.get("id", [""])[0]
    if file_id:
        return f"https://drive.google.com/uc?export=download&id={file_id}"
    return url


def download_file(url: str, output_path: Path) -> None:
    request = Request(direct_download_url(url), headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=120) as response, output_path.open("wb") as f:
        shutil.copyfileobj(response, f)


def download_rows(rows: list[dict], download_dir: Path, label_column: str, no_download: bool) -> list[dict]:
    results = []

    for row in rows:
        output_path = local_video_path(row, download_dir, label_column)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        copied = dict(row)
        copied["local_path"] = output_path.as_posix()
        copied["download_status"] = "planned"

        if no_download:
            results.append(copied)
            continue

        if output_path.exists() and output_path.stat().st_size > 0:
            copied["download_status"] = "exists"
            copied["file_exists"] = "True"
            results.append(copied)
            print(f"exists: {output_path}")
            continue

        url = row.get("drive_url", "")
        if not url:
            copied["download_status"] = "missing_url"
            copied["file_exists"] = "False"
            results.append(copied)
            print(f"missing_url: {row.get('asset_id')}")
            continue

        print(f"download: {row.get('asset_id')} {row.get(label_column)} -> {output_path}")
        try:
            download_file(url, output_path)
            copied["download_status"] = "downloaded"
            copied["file_exists"] = str(output_path.exists())
        except Exception as exc:
            copied["download_status"] = f"failed: {exc}"
            copied["file_exists"] = str(output_path.exists())

        results.append(copied)

    return results


def print_summary(rows: list[dict], output_path: Path, label_column: str) -> None:
    counts: dict[str, int] = {}
    statuses: dict[str, int] = {}

    for row in rows:
        label = row.get(label_column, "unknown") or "unknown"
        status = row.get("download_status", "unknown")
        counts[label] = counts.get(label, 0) + 1
        statuses[status] = statuses.get(status, 0) + 1

    print(f"output_path: {output_path}")
    print(f"download_rows: {len(rows)}")
    print(f"label_counts: {counts}")
    print(f"download_status_counts: {statuses}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download a small sampled media subset by coarse label.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--download-dir", type=Path, default=DEFAULT_DOWNLOAD_DIR)
    parser.add_argument("--label-column", default=DEFAULT_LABEL_COLUMN)
    parser.add_argument("--per-label", type=int, default=1)
    parser.add_argument("--split", default="train", help="Set empty string to use all splits.")
    parser.add_argument("--no-download", action="store_true", help="Only write planned local paths without downloading.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    split = args.split or None
    rows = read_csv(args.input)
    selected = select_per_label(rows, args.label_column, args.per_label, split)
    downloaded_rows = download_rows(selected, args.download_dir, args.label_column, args.no_download)

    fields = list(rows[0].keys())
    for field in ["download_status"]:
        if field not in fields:
            fields.append(field)

    write_csv(downloaded_rows, args.output, fields)
    print_summary(downloaded_rows, args.output, args.label_column)


if __name__ == "__main__":
    main()

