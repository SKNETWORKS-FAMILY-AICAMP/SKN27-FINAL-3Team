# -*- coding: utf-8 -*-
"""검색/RAG용 chunk를 생성합니다."""

from typing import Any, Dict, List

from .config import SOURCE_RELIABILITY


def build_chunks(
    rule_id: str,
    rule_code: str,
    section: Dict[str, Any],
    blocks: List[Dict[str, Any]],
    base_fault: Dict[str, Any],
    accident_classification: Dict[str, Any],
    road_context: Dict[str, Any],
    priority_context: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """block 단위로 검색용 chunk를 생성합니다."""

    # chunk 결과 목록입니다.
    chunks: List[Dict[str, Any]] = []

    # block마다 chunk를 만듭니다.
    for block in blocks:
        # 긴 block은 recursive 방식으로 분리합니다.
        texts = split_recursive(block["structured_text"], chunk_size=1200, overlap=120)

        # 분리된 text마다 chunk row를 만듭니다.
        for text in texts:
            chunks.append(
                {
                    "chunk_id": f"chunk_{rule_id}_{len(chunks)+1:03d}",
                    "rule_id": rule_id,
                    "block_id": block["block_id"],
                    "chunk_type": block["block_type"],
                    "chunk_text": text,
                    "rule_no": section["rule_no"],
                    "rule_code": rule_code,
                    "rule_title": section["rule_title"],
                    "party_a_ratio": base_fault.get("party_a_ratio"),
                    "party_b_ratio": base_fault.get("party_b_ratio"),
                    "accident_group": accident_classification.get("accident_group"),
                    "road_environment": road_context.get("road_area"),
                    "priority_basis": priority_context.get("priority_basis"),
                    "accident_tags": build_accident_tags(accident_classification, road_context),
                    "source_reliability": SOURCE_RELIABILITY,
                }
            )

    # chunk 목록을 반환합니다.
    return chunks


def split_recursive(text: str, chunk_size: int, overlap: int) -> List[str]:
    """RecursiveCharacterTextSplitter 방식처럼 구조를 우선 보존해 chunk를 나눕니다."""

    # 구분자 우선순위입니다.
    separators = ["\n\n", "\n", ". ", " "]

    # 실제 분할을 수행합니다.
    chunks = recursive_split(text.strip(), separators, chunk_size)

    # chunk가 없으면 빈 리스트입니다.
    if not chunks:
        return []

    # overlap이 필요 없으면 그대로 반환합니다.
    if overlap <= 0:
        return chunks

    # 첫 chunk는 그대로 둡니다.
    result = [chunks[0]]

    # 이후 chunk에는 앞 chunk 끝부분을 겹쳐 붙입니다.
    for idx in range(1, len(chunks)):
        result.append(f"{chunks[idx - 1][-overlap:]}\n{chunks[idx]}".strip())

    # overlap이 반영된 chunk를 반환합니다.
    return result


def recursive_split(text: str, separators: List[str], chunk_size: int) -> List[str]:
    """구분자를 단계적으로 낮춰가며 텍스트를 분리합니다."""

    # 빈 텍스트면 빈 리스트입니다.
    if not text:
        return []

    # 기준 길이 이하면 그대로 반환합니다.
    if len(text) <= chunk_size:
        return [text]

    # 더 이상 구분자가 없으면 길이 기준으로 자릅니다.
    if not separators:
        return [text[i:i + chunk_size].strip() for i in range(0, len(text), chunk_size)]

    # 현재 사용할 구분자입니다.
    sep = separators[0]

    # 현재 구분자로 나눕니다.
    parts = text.split(sep)

    # 나눠지지 않으면 다음 구분자로 넘어갑니다.
    if len(parts) == 1:
        return recursive_split(text, separators[1:], chunk_size)

    # 결과 chunk입니다.
    chunks: List[str] = []

    # 현재 누적 중인 문자열입니다.
    current = ""

    # 조각을 순서대로 합칩니다.
    for part in parts:
        # 공백을 정리합니다.
        part = part.strip()

        # 빈 조각은 건너뜁니다.
        if not part:
            continue

        # current에 붙였을 때의 후보입니다.
        candidate = f"{current}{sep}{part}".strip() if current else part

        # 길이가 괜찮으면 누적합니다.
        if len(candidate) <= chunk_size:
            current = candidate

        # 길이가 넘으면 current를 확정합니다.
        else:
            if current:
                chunks.extend(recursive_split(current, separators[1:], chunk_size))
            current = part

    # 마지막 current를 추가합니다.
    if current:
        chunks.extend(recursive_split(current, separators[1:], chunk_size))

    # chunk 목록을 반환합니다.
    return chunks


def build_accident_tags(accident_classification: Dict[str, Any], road_context: Dict[str, Any]) -> List[str]:
    """검색에 사용할 사고 태그를 생성합니다."""

    # 태그 후보입니다.
    values = [
        accident_classification.get("accident_group"),
        accident_classification.get("accident_subgroup"),
        accident_classification.get("collision_pattern"),
        road_context.get("road_area"),
    ]

    # None을 제외하고 문자열 태그로 반환합니다.
    return [str(value) for value in values if value]
