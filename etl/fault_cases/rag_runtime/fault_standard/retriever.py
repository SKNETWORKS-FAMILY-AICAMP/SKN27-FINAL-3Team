"""인정기준 Qwen 4B·pgvector·전용 V9 Neo4j·결정식 계산기 RAG.

법률 Neo4j는 참조하지 않는다. 검색은 `fault_standard_db.rag_qwen4`, 관계·계산
근거는 별도 `fault-standard-neo4j`의 Complete30 V9 복원본에서만 읽는다.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from typing import Any

from neo4j import GraphDatabase

from .utils import flat_facts as _flat_facts
from .calculator import calculate_fault_ratio
from .graph_schema import node_pattern
from .neo4j_reranker import (
    calculator_profiles as c2b_calculator_profiles,
    select as c2b_select,
)
from etl.fault_cases.rag_runtime.contracts import DomainSearchResult, RagRequest
from etl.fault_cases.rag_runtime.fault_standard.v9_graph_adapter import graph_data
from etl.fault_cases.rag_runtime.shared.qwen4_retrieval import (
    encode_live_query,
    precomputed_query_vectors,
    search_by_vector,
    validate_vector,
)


def _resolve_vector(request: RagRequest) -> list[float]:
    """운영 질의 또는 내부 평가용 Qwen 4B 벡터를 선택한다."""

    supplied = request.get("query_vector")
    if supplied is not None:
        values = [float(value) for value in supplied]
        validate_vector(values)
        return values
    evaluation_query_id = request.get("evaluation_query_id")
    if evaluation_query_id:
        return precomputed_query_vectors("fault_standard")[str(evaluation_query_id)]
    return encode_live_query(str(request.get("query_text") or request.get("raw_user_text") or ""))





def _graph_config() -> tuple[str, str, str, str]:
    """인정기준 전용 Neo4j 연결값만 읽는다. 법률 연결값은 사용하지 않는다."""

    uri = os.environ.get("FAULT_STANDARD_NEO4J_URI", "bolt://fault-standard-neo4j:7687")
    user = os.environ.get("FAULT_STANDARD_NEO4J_USER", "neo4j")
    password = os.environ.get("FAULT_STANDARD_NEO4J_PASSWORD")
    database = os.environ.get("FAULT_STANDARD_NEO4J_DATABASE", "neo4j")
    if not password:
        raise RuntimeError("FAULT_STANDARD_NEO4J_PASSWORD가 없어 전용 V9 그래프를 읽을 수 없습니다.")
    return uri, user, password, database


def _graph_profiles(rule_ids: list[str]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    """V9의 조건·당사자·기준 과실·가감요인 관계를 후보 Rule별로 읽는다."""

    conditions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    profiles: dict[str, dict[str, Any]] = {
        rule_id: {"rule_id": rule_id, "source_records": {"base_faults": [], "parties": [], "adjustment_factors": []}}
        for rule_id in rule_ids
    }
    uri, user, password, database = _graph_config()
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session(database=database) as session:
            # record_json은 백업에서 보존된 PDF 구조화 원본이며, 답안지와 무관하다.
            queries = (
                ("REQUIRES_FACT", "conditions", "Fact"),
                ("HAS_PARTY", "parties", "Party"),
                ("HAS_BASE_FAULT", "base_faults", "BaseFault"),
                ("HAS_ADJUSTMENT", "adjustment_factors", "Adjustment"),
            )
            for relation, destination, label in queries:
                cypher = (
                    f"MATCH {node_pattern('r', 'Rule')}-[:{relation}]->{node_pattern('n', label)} "
                    "WHERE r.rule_id IN $rule_ids "
                    "RETURN r.rule_id AS rule_id, n.record_json AS record_json"
                )
                for record in session.run(cypher, rule_ids=rule_ids):
                    rule_id = str(record["rule_id"])
                    raw = record["record_json"]
                    if not raw:
                        continue
                    row = json.loads(raw)
                    if destination == "conditions":
                        conditions[rule_id].append(row)
                    else:
                        profiles[rule_id]["source_records"][destination].append(row)
    finally:
        driver.close()
    for records in conditions.values():
        records.sort(key=lambda row: str(row.get("condition_id") or ""))
    return dict(conditions), profiles





def _evidence(row: dict[str, Any]) -> dict[str, Any]:
    """인정기준 검색 후보를 슈퍼바이저 공통 근거 JSON으로 변환한다."""

    return {
        "source_type": "fault_standard",
        "source_reference": str(row["source_reference"]),
        "title": str(row.get("title") or row["document_id"]),
        "chunk_id": str(row["target_id"]),
        "chunk_text": str(row.get("evidence_text") or ""),
        "rank": int(row["rank"]),
        "similarity_score": float(row["cosine_similarity"]),
        "retrieval_score": float(row["cosine_similarity"]),
        "score_type": "qwen3_4b_cosine_similarity",
        "confidence": "not_calibrated",
        "metadata": dict(row.get("metadata") or {}),
        "limitations": ["코사인 유사도는 정답 확률 또는 과실비율이 아닙니다."],
    }


def search_fault_standard(request: RagRequest) -> DomainSearchResult:
    """인정기준 Top-20을 검색하고 V9 관계 대조·결정식 계산 결과를 함께 반환한다."""

    try:
        # V9 C2b의 승인 계약은 semantic Top-50 후보를 관계 대조하는 방식이다.
        candidates = search_by_vector("fault_standard", _resolve_vector(request), top_k=50, candidate_k=277)
        rule_ids = [str(candidate["document_id"]) for candidate in candidates]
        # C2b는 V9 차로 경로·진입 순서·문맥 관계까지 읽어 당사자 방향을 대조한다.
        graphs = graph_data(rule_ids)
        facts = _flat_facts(dict(request.get("accident_facts") or {}))
        selection = c2b_select(
            str(request.get("message_id") or request.get("session_id") or "runtime_request"),
            [
                {
                    "rule_id": str(candidate["document_id"]),
                    "rank": int(candidate["rank"]),
                    "cosine_similarity": float(candidate["cosine_similarity"]),
                }
                for candidate in candidates
            ],
            graphs,
            facts,
        )
        profiles = c2b_calculator_profiles([selection], graphs)
        calculation = calculate_fault_ratio(selection, facts, profiles)
        # 슈퍼바이저가 계산 근거를 설명할 수 있도록 검색 순위·V9 조건 대조 trace를 보존한다.
        calculation["selection_trace"] = selection
    except (KeyError, RuntimeError, ValueError, OSError, json.JSONDecodeError) as error:
        return {
            "contract_version": request.get("contract_version", "v1"),
            "domain": "fault_standard",
            "status": "failed",
            "evidence": [],
            "calculation_result": None,
            "limitations": [f"인정기준 검색·계산을 실행하지 못했습니다: {error}"],
            "missing_fields": [],
        }
    missing = next((item.get("missing", []) for item in selection["decision_trace"] if item["rule_id"] == selection["selected_rule_id"]), [])
    return {
        "contract_version": request.get("contract_version", "v1"),
        "domain": "fault_standard",
        "status": "success" if calculation.get("status") == "calculated" else "partial",
        "evidence": [_evidence(row) for row in candidates[:10]],
        "calculation_result": calculation,
        "limitations": [
            "선택은 Qwen 4B cosine 후보를 V9 `REQUIRES_FACT` 관계와 대조한 결과입니다.",
            "누락 Fact가 있거나 당사자 매핑이 모호하면 임의 과실비율을 만들지 않고 not_calculable을 반환합니다.",
            "현재 이관 벡터는 AB artifact의 revision 미고정 경고를 보존합니다.",
        ],
        "missing_fields": list(missing),
    }
