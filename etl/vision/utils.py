"""Small shared helpers for Vision ETL scripts."""
from pathlib import Path
import csv


UNSAFE_FILENAME_CHARS = '/\\:*?"<>| '


def read_csv(path: Path) -> list[dict]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(rows: list[dict], output_path: Path, fields: list[str]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def safe_name(value: str) -> str:
    return "".join("_" if char in UNSAFE_FILENAME_CHARS else char for char in value)
