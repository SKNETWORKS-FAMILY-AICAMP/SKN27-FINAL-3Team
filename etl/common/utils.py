"""Common utility functions for the ETL pipeline."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Generator, Iterable

def read_jsonl(path: Path | str) -> list[dict]:
    """Reads a JSONL file and returns a list of dictionaries."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"JSONL file not found: {p}")
    return [
        json.loads(line)
        for line in p.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]

def read_jsonl_iter(path: Path | str) -> Generator[dict, None, None]:
    """Reads a JSONL file lazily and yields dictionaries."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"JSONL file not found: {p}")
    with p.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)

def batched(iterable: Iterable, n: int) -> Generator[list, None, None]:
    """Batch data into lists of length n. The last batch may be shorter."""
    # ponytail: use itertools.batched on Python 3.12+, fallback to manual slicing for compat
    import itertools
    if hasattr(itertools, "batched"):
        yield from itertools.batched(iterable, n)
        return
    it = iter(iterable)
    while batch := list(itertools.islice(it, n)):
        yield batch

def load_env_file(path: Path | str) -> None:
    """Loads environment variables from a .env file."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

def normalize_l2(vector: list[float]) -> list[float]:
    """Normalizes a float vector using L2 norm."""
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return vector
    return [float(v / norm) for v in vector]
