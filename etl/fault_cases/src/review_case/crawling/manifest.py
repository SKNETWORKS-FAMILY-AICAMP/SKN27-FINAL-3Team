"""
수집 manifest 저장 파일.

역할:
- crawling_manifest.jsonl 저장
- crawling_quality_report.jsonl 저장
- 원클릭 실행에서는 기본적으로 파일을 깨끗하게 rewrite한다.
"""

# Python 3.10 이하에서도 타입 힌트를 안전하게 쓰기 위해 annotations를 활성화한다.
from __future__ import annotations

# Path는 경로 타입 처리에 사용한다.
from pathlib import Path

# 경로 생성 함수를 가져온다.
from ..paths import collection_manifest_path, collection_quality_report_path

# 데이터 모델을 가져온다.
from ..models import CollectionManifestRow, CollectionQualityRow

# JSONL 쓰기 유틸을 가져온다.
from .utils import write_jsonl


def write_collection_manifest(output_root: Path, row: CollectionManifestRow, rewrite: bool = True) -> Path:
    """crawling_manifest.jsonl에 수집 row를 저장한다."""

    # manifest 경로를 만든다.
    path = collection_manifest_path(output_root)

    # rewrite=True면 기존 파일을 덮어쓰고, False면 append한다.
    write_jsonl(path, row, append=not rewrite)

    # 저장 경로를 반환한다.
    return path


def write_collection_quality(output_root: Path, row: CollectionQualityRow, rewrite: bool = True) -> Path:
    """crawling_quality_report.jsonl에 검증 row를 저장한다."""

    # quality report 경로를 만든다.
    path = collection_quality_report_path(output_root)

    # rewrite=True면 기존 파일을 덮어쓰고, False면 append한다.
    write_jsonl(path, row, append=not rewrite)

    # 저장 경로를 반환한다.
    return path

