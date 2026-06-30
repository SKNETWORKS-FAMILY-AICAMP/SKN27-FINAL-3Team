import os
from datetime import datetime
from typing import Any, Protocol
from .query_understanding import process_query
from .search import search_law_provisions, evaluate_confidence
from .rule_guard import validate_input_envelope, validate_and_filter_provisions

class LLMExtractor(Protocol):
    def extract_legal_keywords(self, text: str) -> list[str]: ...

def _get_neo4j_session():
    """환경변수 기반 Neo4j 세션 생성기"""
    try:
        from neo4j import GraphDatabase
        uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "password")
        driver = GraphDatabase.driver(uri, auth=(user, password))
        return driver.session()
    except ImportError:
        print("[Warning] neo4j 패키지가 설치되지 않았습니다. GraphRAG 기능이 비활성화됩니다.")
        return None
    except Exception as e:
        print(f"[Warning] Neo4j 연결 실패: {e}")
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
        
    # Neo4j 세션 주입 (파라미터로 안 넘어오면 자체 생성)
    session = neo4j_session or _get_neo4j_session()

    # 2. Query Processing & Neo4j Hint Graph Boosting
    query_data = input_context.get("query", {})
    qp_result = process_query(
        raw_text=query_data.get("raw_text", ""),
        search_query=query_data.get("search_query"),
        retrieval_seed=input_context.get("retrieval_seed", {}),
        neo4j_session=session
    )
    
    print(f"\n[QU 디버그] 원본 질문: {qp_result.original_query}")
    print(f"[QU 디버그] 부스팅된 질문(Hint Graph 반영): {qp_result.boosted_query}")

    if not qp_result.searchability:
        output["status"] = "failed"
        output["missing_fields"] = qp_result.missing_fields
        if session: session.close()
        return output

    # 3. Vector Search & Neo4j Law Graph Expansion
    temporal_basis = input_context.get("temporal_basis", {})
    scope = input_context.get("scope", {})
    
    raw_provisions = search_law_provisions(
        query_text=qp_result.boosted_query,
        article_refs=qp_result.article_refs,
        temporal_basis=temporal_basis,
        scope=scope,
        neo4j_session=session
    )

    # 4. Confidence Evaluation & LLM Fallback
    conf_res = evaluate_confidence(raw_provisions)
    
    if not conf_res["is_confident"]:
        output["limitations"].append(f"1차 검색 신뢰도 부족: {conf_res['reason']}")
        
        if llm_extractor:
            fallback_keywords = llm_extractor.extract_legal_keywords(qp_result.original_query)
            if fallback_keywords:
                output["limitations"].append("LLM Fallback 검색 가동됨.")
                fallback_query = " ".join(fallback_keywords)
                raw_provisions = search_law_provisions(
                    query_text=fallback_query,
                    article_refs=qp_result.article_refs,
                    temporal_basis=temporal_basis,
                    scope=scope,
                    neo4j_session=session
                )

    # 5. Rule Guard 필터링
    valid_provisions, limitations = validate_and_filter_provisions(raw_provisions, scope)
    output["limitations"].extend(limitations)

    # 6. 결과 구성
    if not valid_provisions:
        output["status"] = "partial"
        output["summary"] = "검색 조건에 맞는 유효한 조문이 없습니다."
    else:
        output["status"] = "success"
        output["summary"] = f"조문 {len(valid_provisions)}건 검색됨 (관계 확장 포함)"
        output["structured_result"]["law_provisions"] = valid_provisions
        
        # Evidence 배열 추출
        evidence_list = []
        for prov in valid_provisions:
            evidence_list.append({
                "source_ref": prov.get("source_ref"),
                "chunk_id": prov.get("chunk_id"),
                "source_name": prov.get("source_name"),
                "article_no": prov.get("article_no"),
                "retrieval_score": prov.get("retrieval_score"),
                "match_reason": prov.get("match_reason")
            })
        output["evidence"] = evidence_list

    if session and not neo4j_session: 
        session.close()

    return output

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
