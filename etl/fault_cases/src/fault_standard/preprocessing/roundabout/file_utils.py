# -*- coding: utf-8 -*-
"""파일 저장, 해시 계산, 파일명 정리 유틸입니다."""

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable


def ensure_dir(path: Path) -> None:
    """폴더가 없으면 생성합니다."""

    # parents=True는 중간 폴더까지 함께 만듭니다.
    path.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    """현재 시각을 ISO 문자열로 반환합니다."""

    # 초 단위까지만 남겨 결과 파일을 보기 쉽게 합니다.
    return datetime.now().isoformat(timespec="seconds")


def write_json(path: Path, data: Dict[str, Any]) -> None:
    """딕셔너리를 JSON 파일로 저장합니다."""

    # 저장할 파일의 부모 폴더를 먼저 만듭니다.
    ensure_dir(path.parent)

    # 한글이 깨지지 않도록 ensure_ascii=False를 사용합니다.
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    """여러 딕셔너리를 JSONL 파일로 저장합니다."""

    # 저장할 파일의 부모 폴더를 먼저 만듭니다.
    ensure_dir(path.parent)

    # row 하나를 한 줄 JSON으로 저장합니다.
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def sha256_file(path: Path) -> str:
    """원본 PDF 동일성 확인을 위해 SHA256 해시를 계산합니다."""

    # 해시 계산기를 준비합니다.
    hasher = hashlib.sha256()

    # 큰 파일도 처리할 수 있게 1MB 단위로 읽습니다.
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)

    # 16진수 문자열로 반환합니다.
    return hasher.hexdigest()


def safe_filename(text: str, max_len: int = 28) -> str:
    """제목을 파일명으로 사용할 수 있게 정리합니다."""

    # 앞뒤 공백을 제거합니다.
    text = text.strip()

    # 공백은 파일명에서 제거합니다.
    text = text.replace(" ", "")

    # 파일 경로 구분자는 언더스코어로 바꿉니다.
    text = text.replace("/", "_").replace("\\", "_").replace(":", "_")

    # 한글, 영문, 숫자, 괄호, 하이픈, 점 정도만 남깁니다.
    text = re.sub(r"[^\w가-힣().\-]+", "_", text)

    # 중복 언더스코어를 하나로 줄입니다.
    text = re.sub(r"_+", "_", text).strip("_")

    # 너무 긴 파일명은 Windows 경로 길이를 넘지 않도록 줄이고 해시로 충돌을 피합니다.
    if len(text) > max_len:
        suffix = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
        text = f"{text[: max_len - 9]}_{suffix}"

    return text or "untitled"


def dedupe_rows(rows: Iterable[Dict[str, Any]], key_fields: list[str]) -> list[Dict[str, Any]]:
    """지정한 컬럼 조합을 기준으로 중복 row를 제거합니다."""

    # 이미 본 key를 저장합니다.
    seen = set()

    # 중복 제거 후 남길 결과입니다.
    result: list[Dict[str, Any]] = []

    # row를 순서대로 확인합니다.
    for row in rows:
        # 지정한 필드값을 튜플로 묶어 key를 만듭니다.
        key = tuple(str(row.get(field)) for field in key_fields)

        # 이미 같은 key가 있으면 건너뜁니다.
        if key in seen:
            continue

        # 처음 본 key는 기록합니다.
        seen.add(key)

        # 결과에 추가합니다.
        result.append(row)

    # 중복 제거된 결과를 반환합니다.
    return result
