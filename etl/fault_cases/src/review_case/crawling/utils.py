"""
수집 공통 유틸 파일.

역할:
- 로그 출력
- 현재 시각 생성
- 문자열 정리
- 키워드 매칭
- 파일명 정리
- SHA-256 계산
- JSONL 쓰기/읽기
"""

# Python 3.10 이하에서도 타입 힌트를 안전하게 쓰기 위해 annotations를 활성화한다.
from __future__ import annotations

# hashlib는 SHA-256 해시 계산에 사용한다.
import hashlib

# json은 JSONL 저장과 읽기에 사용한다.
import json

# re는 정규식 기반 문자열 정리에 사용한다.
import re

# asdict와 is_dataclass는 dataclass를 JSON 저장 가능한 dict로 바꾸기 위해 사용한다.
from dataclasses import asdict, is_dataclass

# datetime은 현재 시각 기록에 사용한다.
from datetime import datetime, timezone

# Path는 파일 경로 처리에 사용한다.
from pathlib import Path

# unquote는 URL 인코딩된 한글 복구에 사용한다.
from urllib.parse import unquote


def log(message: str) -> None:
    """콘솔에 즉시 로그를 출력한다."""

    # flush=True를 사용해 PowerShell 출력이 밀리지 않게 한다.
    print(message, flush=True)


def now_iso() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""

    # timezone.utc를 포함해 시간대가 명확한 문자열을 만든다.
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_text(value: str | None) -> str:
    """문자열의 URL 인코딩과 공백을 정리한다."""

    # None이면 빈 문자열로 바꾼다.
    text = str(value or "")

    # URL 인코딩된 한글을 복구한다.
    text = unquote(text)

    # HTML non-breaking space를 일반 공백으로 바꾼다.
    text = text.replace("\xa0", " ")

    # 여러 공백을 하나로 줄인다.
    text = re.sub(r"\s+", " ", text)

    # 앞뒤 공백을 제거한다.
    return text.strip()


def compact_text(value: str | None) -> str:
    """키워드 비교용으로 공백 없는 문자열을 만든다."""

    # 정규화 후 공백을 제거한다.
    return re.sub(r"\s+", "", normalize_text(value))


def contains_any(text: str, keywords: list[str]) -> bool:
    """텍스트에 키워드가 하나라도 포함되는지 확인한다."""

    # 비교 대상 문자열을 만든다.
    target = compact_text(text)

    # 키워드 중 하나라도 포함되면 True를 반환한다.
    return any(compact_text(keyword) in target for keyword in keywords)


def matched_keywords(text: str, keywords: list[str]) -> list[str]:
    """텍스트에 실제 포함된 키워드 목록을 반환한다."""

    # 비교 대상 문자열을 만든다.
    target = compact_text(text)

    # 결과 리스트를 만든다.
    result: list[str] = []

    # 키워드를 하나씩 검사한다.
    for keyword in keywords:
        # 키워드가 포함되면 결과에 추가한다.
        if compact_text(keyword) in target:
            result.append(keyword)

    # 결과를 반환한다.
    return result


def safe_filename(filename: str, fallback: str) -> str:
    """Windows 파일명으로 안전하게 쓸 수 있도록 정리한다."""

    # 파일명이 비어 있으면 fallback을 사용한다.
    text = normalize_text(filename) or fallback

    # URL/경로 형태가 들어오면 마지막 이름만 사용한다.
    if "/" in text or "\\" in text:
        text = Path(text).name

    # Windows 금지 문자를 밑줄로 바꾼다.
    text = re.sub(r'[<>:"/\\|?*]+', "_", text)

    # 공백을 다시 정리한다.
    text = normalize_text(text)

    # 확장자가 없으면 .pdf를 붙인다.
    if not text.lower().endswith(".pdf"):
        text = f"{text}.pdf"

    # 파일명이 너무 길어지지 않게 stem을 제한한다.
    stem = Path(text).stem[:140]

    # 최종 파일명을 반환한다.
    return f"{stem}.pdf"


def sha256_file(path: Path) -> str:
    """파일의 SHA-256 해시를 계산한다."""

    # 해시 객체를 만든다.
    hasher = hashlib.sha256()

    # 파일을 binary 모드로 연다.
    with path.open("rb") as file:
        # 파일을 1MB씩 읽는다.
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            # chunk를 해시에 반영한다.
            hasher.update(chunk)

    # 최종 해시 문자열을 반환한다.
    return hasher.hexdigest()


def write_jsonl(path: Path, row: object, append: bool = True) -> None:
    """객체를 JSONL 한 줄로 저장한다."""

    # 부모 폴더가 없으면 만든다.
    path.parent.mkdir(parents=True, exist_ok=True)

    # dataclass면 dict로 바꾼다.
    if is_dataclass(row):
        data = asdict(row)
    else:
        data = row

    # append 여부에 따라 파일 모드를 결정한다.
    mode = "a" if append else "w"

    # 파일을 연다.
    with path.open(mode, encoding="utf-8") as file:
        # 한글이 깨지지 않게 ensure_ascii=False를 사용한다.
        file.write(json.dumps(data, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    """JSONL 파일을 읽어 dict 목록으로 반환한다."""

    # 파일이 없으면 빈 목록을 반환한다.
    if not path.exists():
        return []

    # 결과 리스트를 만든다.
    rows: list[dict] = []

    # 파일을 읽기 모드로 연다.
    with path.open("r", encoding="utf-8") as file:
        # 한 줄씩 읽는다.
        for line in file:
            # 빈 줄은 건너뛴다.
            if not line.strip():
                continue

            # JSON 문자열을 dict로 바꿔 추가한다.
            rows.append(json.loads(line))

    # 결과를 반환한다.
    return rows

