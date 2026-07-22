"""환경에 독립적인 논리 출처 참조 문자열을 만든다."""

from __future__ import annotations

from typing import Literal


SourceType = Literal["fault_standard", "precedent", "review_case", "law"]


def build_source_reference(source_type: SourceType, source_id: str, evidence_id: str) -> str:
    """도메인·원문·근거 ID로 논리 출처 참조를 만든다.

    물리 데이터베이스 이름, 테이블 이름, 호스트, 포트는 반환값에 포함하지 않는다.
    """

    if not source_id.strip() or not evidence_id.strip():
        raise ValueError("논리 출처 참조에는 비어 있지 않은 원문 ID와 근거 ID가 필요합니다.")
    return f"{source_type}:{source_id}#{evidence_id}"

