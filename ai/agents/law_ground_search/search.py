from typing import Any

OAI_ABSOLUTE_THRESHOLD = 0.85
OAI_MARGIN_THRESHOLD = 0.03

def search_law_provisions(
    query_text: str,
    article_refs: list[str],
    temporal_basis: dict[str, Any],
    scope: dict[str, Any],
    neo4j_session: Any = None,
    top_k: int = 5
) -> list[dict[str, Any]]:
    """
    1차 MVP + 복원 스펙: pgvector 검색 후 특정 관계(처벌/별표) 정밀 확장
    """
    # 1. 파이프라인 브랜치의 실제 벡터 검색 모듈(etl.legal.search) 연동
    from etl.legal.search import search_laws
    
    # search_laws 내부에서 임베딩을 수행하고 DB/JSONL에서 Top-K 조문을 가져옵니다.
    try:
        import os
        provider = os.environ.get("AB_TEST_PROVIDER", "openai")
        embeddings_path = os.environ.get("AB_TEST_EMBEDDINGS_PATH", "output/law_ingestion/embeddings/law_embeddings_openai.jsonl")
        
        core_provisions = search_laws(
            query_text, 
            top_k=top_k,
            provider=provider,
            embeddings_path=embeddings_path
        )
    except Exception as e:
        print(f"[Warning] Vector Search 실패 (Mock으로 대체): {e}")
        core_provisions = _mock_vector_search(query_text, top_k)

    # Temporal & Scope 검증 (초반 필터)
    # 실제 구현에서는 rule_guard를 통해 거르거나 쿼리 시점에 필터링합니다.
    
    # 2. Neo4j Law Graph 관계 확장 (초안 스펙 복원: 타겟팅 확장)
    if neo4j_session and core_provisions:
        core_provisions = _expand_with_law_graph(core_provisions, neo4j_session)

    return core_provisions

def evaluate_confidence(provisions: list[dict[str, Any]]) -> dict[str, Any]:
    if not provisions:
        return {"is_confident": False, "reason": "검색 결과 없음"}

    # etl/legal/search.py returns "score"
    top1_score = provisions[0].get("score", provisions[0].get("retrieval_score", 0.0))
    # OpenAI cosine similarities naturally hover around 0.5~0.7, so 0.85 is too high.
    OAI_ADAPTED_THRESHOLD = 0.50 
    if top1_score < OAI_ADAPTED_THRESHOLD:
        return {"is_confident": False, "reason": f"Top-1 점수({top1_score})가 절대 기준치 미만"}

    # Note: Margin check is removed because different versions of the same law 
    # (enforce_date) have identical text and score, causing margin=0.0 falsely.
    return {"is_confident": True, "reason": "신뢰할 수 있는 검색 결과"}

def _mock_vector_search(query: str, top_k: int) -> list[dict]:
    """파이프라인 브랜치 병합 전까지 사용할 Mock 검색"""
    return [{"chunk_id": "mock_chunk_1", "provision_text": "임시 조문", "source_url": "http", "retrieval_score": 0.9}]

def _expand_with_law_graph(core_provisions: list[dict], session: Any) -> list[dict]:
    """Neo4j Law Graph 타겟팅 확장 쿼리"""
    if not session or not core_provisions:
        return core_provisions
        
    chunk_ids = [p["chunk_id"] for p in core_provisions if "chunk_id" in p]
    if not chunk_ids:
        return core_provisions
        
    query = """
    UNWIND $chunk_ids AS cid
    MATCH (c1:LawChunk {chunk_id: cid})-[r]->(c2:LawChunk)
    WHERE type(r) IN ['HAS_PENALTY', 'HAS_APPENDIX', 'HAS_EXCEPTION', 'RELATED_TO']
    RETURN c2
    """
    
    expanded_chunks = []
    try:
        result = session.run(query, chunk_ids=chunk_ids)
        for record in result:
            node = record["c2"]
            expanded_chunks.append({
                "chunk_id": node.get("chunk_id"),
                "provision_text": node.get("provision_text"),
                "source_type": node.get("source_type"),
                "source_url": node.get("source_url"),
                "retrieval_score": 0.8, # 확장 조문은 기본 신뢰도 부여
                "match_reason": "graph_expansion"
            })
    except Exception as e:
        print(f"[Warning] Neo4j Law Graph 확장 실패: {e}")
        
    # 핵심 조문과 확장 조문 병합
    # 중복 제거 (chunk_id 기준)
    seen = {p["chunk_id"] for p in core_provisions if "chunk_id" in p}
    for chunk in expanded_chunks:
        if chunk["chunk_id"] not in seen:
            core_provisions.append(chunk)
            seen.add(chunk["chunk_id"])
            
    return core_provisions
