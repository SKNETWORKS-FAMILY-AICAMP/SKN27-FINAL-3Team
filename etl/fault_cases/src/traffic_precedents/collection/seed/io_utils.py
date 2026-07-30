"""JSON/JSONL 및 환경변수 입출력 유틸리티."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable


def load_dotenv(path: Path) -> None:
    """간단한 KEY=VALUE 형식의 .env를 기존 환경변수를 덮지 않고 읽습니다."""

    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            os.environ.setdefault(key, value)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """JSONL 파일을 UTF-8로 새로 씁니다."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    """JSONL 파일에 한 행을 추가합니다."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json(path: Path, value: Any) -> None:
    """들여쓴 JSON 파일을 UTF-8로 씁니다."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """JSONL 파일을 읽어 객체 리스트로 반환합니다."""

    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


