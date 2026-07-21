"""판례 Qwen 4B·pgvector+B-4 운영 검색기.

B-4는 질문 원문에서 확인되는 사고 조건만 보강한다. Query ID, 정답 판례 ID,
qrels, 과거 순위, 과실비율은 규칙 입력과 보강문에 사용하지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .query_expander import (
    detect_concepts,
    evaluate_variant,
)
from etl.fault_cases.rag_runtime.contracts import DomainSearchResult, RagRequest
from etl.fault_cases.rag_runtime.shared.qwen4_retrieval import (
    FAULT_CASES_ROOT,
    encode_live_query,
    precomputed_query_vectors,
    search_by_vector,
    validate_vector,
)


# 승인된 B-1·B-4 사전은 코드와 분리된 JSON으로 고정한다.
CONFIG_ROOT = Path(__file__).resolve().parent / "configs"
B1_SELECTED_PATH = CONFIG_ROOT / "keyword_rules_v1_selected.json"
B1_DRAFT_PATH = CONFIG_ROOT / "keyword_rules_v1_draft.json"
B4_PATH = CONFIG_ROOT / "keyword_rules_b4_all_top10_failures.json"


def _load_json(path: Path) -> dict[str, Any]:
    """승인된 키워드 JSON을 UTF-8로 읽고 형식 오류를 초기에 드러낸다."""

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("rules"), list):
        raise ValueError(f"키워드 사전 형식이 올바르지 않습니다: {path}")
    return value


def _b1_rules() -> list[dict[str, Any]]:
    """선택된 B-1 variant와 원본 조건을 결합한 실행 규칙을 만든다."""

    variants = {str(row["rule_id"]): row for row in _load_json(B1_DRAFT_PATH)["rules"]}
    output: list[dict[str, Any]] = []
    for row in _load_json(B1_SELECTED_PATH)["rules"]:
        rule_id, variant = str(row["rule_id"]), str(row["selected_variant"])
        source = variants.get(rule_id)
        condition = source.get("variants", {}).get(variant) if source else None
        if not isinstance(condition, dict):
            raise ValueError(f"B-1 규칙 조건을 찾지 못했습니다: {rule_id}/{variant}")
        if row.get("enabled"):
            output.append({**row, "condition": condition})
    return output


def enrich_query(query_text: str) -> dict[str, Any]:
    """질문 원문만으로 B-1과 B-4의 보강문을 순서대로 붙인다.

    동일 단계에서 복수 규칙이 발동하면 특정 판례로 쏠릴 가능성이 있으므로 해당
    단계 보강을 적용하지 않고 오류를 반환한다. 조용한 임의 선택은 하지 않는다.
    """

    if not query_text.strip():
        raise ValueError("판례 검색 질문이 비어 있습니다.")
    concepts, evidence = detect_concepts(query_text)
    b1_fired = [rule for rule in _b1_rules() if evaluate_variant(concepts, rule["condition"])["fired"]]
    b4_fired = [
        rule
        for rule in _load_json(B4_PATH)["rules"]
        if rule.get("enabled") and evaluate_variant(concepts, dict(rule.get("condition") or {}))["fired"]
    ]
    if len(b1_fired) > 1 or len(b4_fired) > 1:
        raise ValueError("한 단계에 복수 키워드 규칙이 발동했습니다. 보강을 중단하고 규칙을 검토해야 합니다.")
    b1 = b1_fired[0] if b1_fired else None
    b4 = b4_fired[0] if b4_fired else None
    text = query_text
    if b1:
        text += f"\n검색 상황 보강: {b1['expansion']}"
    if b4:
        text += f"\n세부 사고상황 보강: {b4['expansion']}"
    return {
        "enriched_query_text": text,
        "b1_rule_id": str(b1["rule_id"]) if b1 else "",
        "b4_rule_id": str(b4["rule_id"]) if b4 else "",
        "detected_concepts": sorted(concepts),
        "concept_evidence": evidence,
    }


def _resolve_vector(request: RagRequest) -> tuple[list[float], dict[str, Any]]:
    """내부 평가 또는 운영 원문 질의의 벡터와 B-4 감사 정보를 반환한다."""

    supplied = request.get("query_vector")
    if supplied is not None:
        values = [float(value) for value in supplied]
        validate_vector(values)
        return values, {"mode": "supplied_vector", "b1_rule_id": "", "b4_rule_id": ""}
    evaluation_query_id = request.get("evaluation_query_id")
    if evaluation_query_id:
        return precomputed_query_vectors("precedent", "b4")[str(evaluation_query_id)], {
            "mode": "precomputed_b4_evaluation_vector",
            "b1_rule_id": "artifact_inherited",
            "b4_rule_id": "artifact_checked",
        }
    enriched = enrich_query(str(request.get("query_text") or request.get("raw_user_text") or ""))
    return encode_live_query(str(enriched["enriched_query_text"])), {"mode": "live_b4", **enriched}


def _evidence(row: dict[str, Any]) -> dict[str, Any]:
    """판례 DB의 사건 단위 후보를 슈퍼바이저 근거 JSON으로 변환한다."""

    return {
        "source_type": "precedent",
        "source_reference": str(row["source_reference"]),
        "title": str(row.get("title") or row["document_id"]),
        "chunk_id": str(row.get("chunk_id") or row["target_id"]),
        "chunk_text": str(row.get("evidence_text") or ""),
        "rank": int(row["rank"]),
        "similarity_score": float(row["cosine_similarity"]),
        "retrieval_score": float(row["cosine_similarity"]),
        "score_type": "qwen3_4b_cosine_similarity_after_b4_query_expansion",
        "confidence": "not_calibrated",
        "metadata": dict(row.get("metadata") or {}),
        "limitations": ["B-4는 검색어 보강이며 특정 정답 판례를 직접 지정하지 않습니다.", "코사인 유사도는 정답 확률이 아닙니다."],
    }


def search_precedent(request: RagRequest) -> DomainSearchResult:
    """B-4 보강 질의로 판례 전용 DB의 고유 판례 Top-10을 검색한다."""

    try:
        vector, audit = _resolve_vector(request)
        rows = search_by_vector("precedent", vector, top_k=10, candidate_k=300)
    except (KeyError, RuntimeError, ValueError, OSError) as error:
        return {
            "contract_version": request.get("contract_version", "v1"),
            "domain": "precedent",
            "status": "failed",
            "evidence": [],
            "limitations": [f"판례 B-4 검색을 실행하지 못했습니다: {error}"],
            "missing_fields": [],
        }
    return {
        "contract_version": request.get("contract_version", "v1"),
        "domain": "precedent",
        "status": "success" if rows else "partial",
        "evidence": [_evidence(row) for row in rows],
        "calculation_result": None,
        "limitations": [
            "B-4는 질문 원문 조건만 사용하며 Query ID·정답 판례 ID·qrels·기존 순위·과실비율을 사용하지 않습니다.",
            f"키워드 발동 감사: B-1={audit.get('b1_rule_id', '') or '없음'}, B-4={audit.get('b4_rule_id', '') or '없음'}",
        ],
        "missing_fields": [],
    }
