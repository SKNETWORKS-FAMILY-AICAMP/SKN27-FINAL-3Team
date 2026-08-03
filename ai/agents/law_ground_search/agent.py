import logging
import os
import re
from datetime import datetime
from typing import Any, Protocol
from .query_understanding import process_query
from .search import search_law_provisions, evaluate_confidence
from .rule_guard import validate_input_envelope, validate_and_filter_provisions

logger = logging.getLogger(__name__)

_LAW_CODE_ARTICLE_PATTERN = re.compile(r"^\s*(?P<law_name>.+?)\s+제\s*\d+\s*조")

class LLMExtractor(Protocol):
    def extract_legal_keywords(self, text: str) -> list[str]: ...
    def format_api_response(self, provisions: list, input_context: dict) -> dict: ...

_neo4j_driver = None

def _get_neo4j_session():
    """환경변수 기반 Neo4j 세션 생성기"""
    global _neo4j_driver
    try:
        if _neo4j_driver is None:
            from neo4j import GraphDatabase
            uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
            user = os.environ.get("NEO4J_USER", "neo4j")
            password = os.environ.get("NEO4J_PASSWORD", "password")
            _neo4j_driver = GraphDatabase.driver(uri, auth=(user, password))
        return _neo4j_driver.session()
    except Exception as exc:
        logger.warning(
            "Neo4j connection failed; error_class=%s",
            exc.__class__.__name__,
        )
        return None

def run_law_ground_search(
    agent_input: dict[str, Any], 
    context: dict[str, Any],
    llm_extractor: LLMExtractor | None = None,
    neo4j_session: Any = None
) -> dict[str, Any]:
    """
    V4 최종 완전판 GraphRAG 아키텍처 진입점
    """
    input_context = agent_input.get("context", {})
    output = _init_output(agent_input)

    # 1. 입력 검증
    validation_res = validate_input_envelope(input_context)
    if not validation_res["valid"]:
        output["status"] = "failed"
        output["limitations"].extend(validation_res["errors"])
        return output
        
    # Neo4j 세션 주입 (명시 설정이 있을 때만 자체 생성)
    session = neo4j_session
    if session is None and _should_open_neo4j_session(context, input_context):
        session = _get_neo4j_session()

    # 2. Query Processing & Neo4j Hint Graph Boosting
    query_data = input_context.get("query", {})
    qp_result = process_query(
        raw_text=query_data.get("raw_text", ""),
        search_query=query_data.get("search_query"),
        retrieval_seed=input_context.get("retrieval_seed", {}),
        neo4j_session=session
    )
    
    if not qp_result.searchability:
        output["status"] = "failed"
        output["summary"] = "질의가 입력되지 않았습니다."
        output["missing_fields"] = qp_result.missing_fields
        if session:
            session.close()
        return output

    # 3. Vector Search & Neo4j Law Graph Expansion
    temporal_basis = input_context.get("temporal_basis", {})
    scope = input_context.get("scope", {})
    
    query_text = qp_result.boosted_query
    used_llm_fallback = False

    if not qp_result.hint_terms and llm_extractor:
        fallback_keywords = llm_extractor.extract_legal_keywords(qp_result.original_query)
        used_llm_fallback = True
        if fallback_keywords:
            output["limitations"].append("Hint Graph 검색어 없음: LLM 키워드 추출로 1차 검색을 보강했습니다.")
            query_text = " ".join(fallback_keywords)

    raw_provisions = search_law_provisions(
        query_text=query_text,
        article_refs=qp_result.article_refs,
        temporal_basis=temporal_basis,
        scope=scope,
        neo4j_session=session
    )
    raw_provisions, excluded_source_count = _filter_confirmed_law_sources(
        raw_provisions,
        law_code=query_data.get("law_code"),
    )
    if excluded_source_count:
        output["limitations"].append(
            f"확인된 법령명과 일치하지 않는 검색 결과 {excluded_source_count}건을 제외했습니다."
        )

    # 4. Confidence Evaluation & LLM Fallback
    conf_res = evaluate_confidence(raw_provisions)
    
    if not conf_res["is_confident"]:
        output["limitations"].append(f"1차 검색 신뢰도 부족: {conf_res['reason']}")
        
        if llm_extractor and not used_llm_fallback:
            fallback_keywords = llm_extractor.extract_legal_keywords(qp_result.original_query)
            if fallback_keywords:
                used_llm_fallback = True
                output["limitations"].append("LLM Fallback 검색 가동됨.")
                fallback_query = " ".join(fallback_keywords)
                raw_provisions = search_law_provisions(
                    query_text=fallback_query,
                    article_refs=qp_result.article_refs,
                    temporal_basis=temporal_basis,
                    scope=scope,
                    neo4j_session=session
                )
                raw_provisions, fallback_excluded_count = _filter_confirmed_law_sources(
                    raw_provisions,
                    law_code=query_data.get("law_code"),
                )
                if fallback_excluded_count and not excluded_source_count:
                    output["limitations"].append(
                        f"확인된 법령명과 일치하지 않는 검색 결과 {fallback_excluded_count}건을 제외했습니다."
                    )

    # 5. Rule Guard 필터링
    valid_provisions, limitations = validate_and_filter_provisions(raw_provisions, scope)
    output["limitations"].extend(limitations)
    sourced_provisions = []
    for provision in valid_provisions:
        source_reference = (
            provision.get("source_reference")
            or provision.get("source_ref")
            or provision.get("chunk_id")
        )
        if not str(source_reference or "").strip():
            output["limitations"].append(
                f"Missing source_reference; legal provision was excluded: {provision.get('chunk_id')}"
            )
            continue
        provision["source_reference"] = str(source_reference).strip()
        sourced_provisions.append(provision)
    valid_provisions = sourced_provisions
    final_conf_res = evaluate_confidence(valid_provisions)
    retrieval_metadata = next(
        (
            provision.get("_retrieval")
            for provision in valid_provisions
            if isinstance(provision.get("_retrieval"), dict)
        ),
        None,
    )
    for provision in valid_provisions:
        provision.pop("_retrieval", None)
        provision.pop("source_ref", None)

    # 6. 결과 구성
    if not valid_provisions:
        output["status"] = "empty"
        output["summary"] = "검색 조건에 맞는 유효한 조문이 없습니다."
    else:
        output["status"] = "success"
        output["summary"] = f"조문 {len(valid_provisions)}건 검색됨 (관계 확장 포함)"
        
        if llm_extractor:
            api_result = llm_extractor.format_api_response(valid_provisions, input_context)
            if api_result:
                output["structured_result"].update(api_result)
        
        output["structured_result"]["law_provisions"] = valid_provisions
        if retrieval_metadata:
            output["structured_result"]["retrieval_quality"] = (
                retrieval_metadata.get("backend") or "postgres_pgvector"
            )
            output["structured_result"]["retrieval"] = retrieval_metadata
        
        
        # Evidence 배열 추출
        evidence_list = []
        for prov in valid_provisions:
            evidence_list.append({
                "source_reference": prov["source_reference"],
                "chunk_id": prov.get("chunk_id"),
                "source_name": prov.get("source_name"),
                "source_type": prov.get("source_type"),
                "article_no": prov.get("article_no"),
                "appendix_no": prov.get("appendix_no"),
                "article_title": prov.get("article_title"),
                "source_url": prov.get("source_url"),
                "retrieval_score": prov.get("retrieval_score") or prov.get("score"),
                "match_reason": prov.get("match_reason")
            })
        output["evidence"] = evidence_list
        if not final_conf_res["is_confident"]:
            if used_llm_fallback:
                output["status"] = "failed"
                output["summary"] = "LLM 재검색까지 시도했으나 유효한 신뢰도를 확보하지 못했습니다."
                output["limitations"].append(f"최종 검색 신뢰도 부족(2회 연속 실패): {final_conf_res['reason']}")
            else:
                output["status"] = "partial"
                output["summary"] = f"조문 {len(valid_provisions)}건 검색됨. 다만 신뢰도가 낮아 추가 확인이 필요합니다."
                output["limitations"].append(f"최종 검색 신뢰도 부족: {final_conf_res['reason']}")

    if session and not neo4j_session:
        session.close()

    return output


def _filter_confirmed_law_sources(
    provisions: list[dict[str, Any]],
    *,
    law_code: Any,
) -> tuple[list[dict[str, Any]], int]:
    expected_law_name = _law_name_from_code(law_code)
    if not expected_law_name:
        return provisions, 0

    filtered = [
        provision
        for provision in provisions
        if _normalized_law_name(provision.get("source_name")) == expected_law_name
    ]
    return filtered, len(provisions) - len(filtered)


def _law_name_from_code(value: Any) -> str:
    text = str(value or "").strip()
    match = _LAW_CODE_ARTICLE_PATTERN.match(text)
    if not match:
        return ""
    return _normalized_law_name(match.group("law_name"))


def _normalized_law_name(value: Any) -> str:
    return " ".join(str(value or "").split())

def _init_output(agent_input: dict) -> dict:
    return {
        "session_id": agent_input.get("session_id"),
        "message_id": agent_input.get("message_id"),
        "job_id": agent_input.get("job_id"),
        "node_name": "법령 근거 검색",
        "node_code": "law_ground_search",
        "node_type": "search",
        "owner": "techshin31",
        "status": "success",
        "summary": "",
        "structured_result": {"law_provisions": []},
        "evidence": [],
        "next_actions": [],
        "limitations": [],
        "missing_fields": [],
        "created_at": datetime.now().isoformat()
    }


def _should_open_neo4j_session(adapter_context: dict[str, Any], input_context: dict[str, Any]) -> bool:
    graph_config = input_context.get("law_graph") if isinstance(input_context.get("law_graph"), dict) else {}
    if "enabled" in graph_config:
        return _truthy(graph_config.get("enabled"))
    if "enable_neo4j" in adapter_context:
        return _truthy(adapter_context.get("enable_neo4j"))
    return _truthy(os.environ.get("LAW_GROUND_SEARCH_ENABLE_NEO4J"))


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}
