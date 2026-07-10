from typing import Any

LAW_GRAPH_EXPANSION_RELATION_TYPES = ["HAS_PENALTY", "HAS_APPENDIX", "HAS_EXCEPTION", "RELATED_TO"]

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
        # OpenAI 임베딩으로 확정됨
        core_provisions = search_laws(
            query=query_text, 
            top_k=top_k,
            provider="openai",
            embeddings_path="output/law_ingestion/embeddings/law_embeddings_openai.jsonl",
            temporal_basis=temporal_basis,
            scope=scope
        )
    except Exception as e:
        print(f"[Warning] Vector Search 실패: {e}")
        core_provisions = []

    if not core_provisions:
        core_provisions = _search_fallback_legal_rag(query_text=query_text, top_k=top_k)

    # Temporal & Scope 검증 (초반 필터)
    # 실제 구현에서는 rule_guard를 통해 거르거나 쿼리 시점에 필터링합니다.
    
    # 2. Neo4j Law Graph 관계 확장 (초안 스펙 복원: 타겟팅 확장)
    if neo4j_session:
        core_scores = {p["chunk_id"]: p.get("score", p.get("retrieval_score", 0.0)) for p in core_provisions if "chunk_id" in p}
        core_provisions = _expand_with_law_graph(core_provisions, article_refs, neo4j_session, core_scores)

    return core_provisions

def _search_fallback_legal_rag(query_text: str, top_k: int) -> list[dict[str, Any]]:
    """Django RAG tables fallback for local/dev environments without pgvector."""
    try:
        from app.services import legal_rag_service

        rag_response = legal_rag_service.search_legal_rag(
            query_text,
            top_k=top_k,
            source_type="law",
        )
    except Exception as e:
        print(f"[Warning] Django RAG fallback 실패: {e}")
        return []

    if rag_response.get("status") != "ready":
        return []

    provisions = []
    backend = rag_response.get("backend") or "django_rag_tables"
    for item in rag_response.get("results") or []:
        source_reference = item.get("source_reference") or item.get("chunk_id") or ""
        provisions.append(
            {
                "chunk_id": source_reference,
                "source_ref": source_reference,
                "source_name": item.get("source_name"),
                "source_type": item.get("source_type") or "law",
                "article_no": item.get("article") or item.get("section_ref"),
                "appendix_no": None,
                "article_title": item.get("title"),
                "provision_text": item.get("summary") or "",
                "source_url": item.get("source_url") or "",
                "retrieval_score": item.get("score", 0.0),
                "score": item.get("score", 0.0),
                "match_reason": f"legal_rag_fallback:{backend}",
            }
        )
    return provisions

def evaluate_confidence(provisions: list[dict[str, Any]]) -> dict[str, Any]:
    if not provisions:
        return {"is_confident": False, "reason": "검색 결과 없음"}

    # etl/legal/search.py returns "score"
    top1_score = provisions[0].get("score", provisions[0].get("retrieval_score", 0.0))
    
    # 사용자의 피드백 반영: OpenAI 임베딩으로 확정 (코사인 유사도가 0.5를 넘기 힘든 점 감안)
    THRESHOLD = 0.4

    # Top-1 score check
    if top1_score < THRESHOLD:
        return {"is_confident": False, "reason": f"Top-1 점수({top1_score:.3f})가 절대 기준치({THRESHOLD}) 미만"}
    
    return {"is_confident": True, "reason": "신뢰할 수 있는 검색 결과"}

def _expand_with_law_graph(core_provisions: list[dict], article_refs: list[str], session: Any, core_scores: dict[str, float] = None) -> list[dict]:
    """Neo4j Law Graph 타겟팅 확장 쿼리 및 명시적 조문(article_refs) 병합"""
    if not session:
        return core_provisions
    core_scores = core_scores or {}
        
    chunk_ids = [p["chunk_id"] for p in core_provisions if "chunk_id" in p]
    
    expanded_chunks = []
    
    # [1] Reverse Graph Expansion
    if chunk_ids:
        query_graph = """
        UNWIND $chunk_ids AS cid
        MATCH (c1:LawChunk {chunk_id: cid})-[r]-(c2:LawChunk)
        WHERE type(r) IN $relation_types
        RETURN cid, type(r) AS relation_type, c2 LIMIT 100
        """
        try:
            result = session.run(query_graph, chunk_ids=chunk_ids, relation_types=LAW_GRAPH_EXPANSION_RELATION_TYPES)
            for record in result:
                cid = record["cid"]
                relation_type = record["relation_type"]
                node = record["c2"]
                base_score = core_scores.get(cid, 0.5)
                expanded_chunks.append({
                    "chunk_id": node.get("chunk_id"),
                    "source_ref": node.get("source_ref"),
                    "source_name": node.get("source_name"),
                    "article_no": node.get("article_no"),
                    "appendix_no": node.get("appendix_no"),
                    "article_title": node.get("article_title"),
                    "provision_text": node.get("provision_text"),
                    "source_type": node.get("source_type"),
                    "source_url": node.get("source_url"),
                    "retrieval_score": base_score * 0.9, # 원본 조문 대비 감가
                    "match_reason": f"graph_expansion:{relation_type}"
                })
        except Exception as e:
            print(f"[Warning] Neo4j Law Graph 확장 실패: {e}")
            
    # [2] 명시적 조문(article_refs) 주입 (강력한 정답 유도)
    if article_refs:
        query_refs = """
        UNWIND $refs AS ref
        MATCH (c:LawChunk)
        WHERE c.article_no = ref
        RETURN c LIMIT 10
        """
        try:
            result = session.run(query_refs, refs=article_refs)
            for record in result:
                node = record["c"]
                expanded_chunks.append({
                    "chunk_id": node.get("chunk_id"),
                    "source_ref": node.get("source_ref"),
                    "source_name": node.get("source_name"),
                    "article_no": node.get("article_no"),
                    "appendix_no": node.get("appendix_no"),
                    "article_title": node.get("article_title"),
                    "provision_text": node.get("provision_text"),
                    "source_type": node.get("source_type"),
                    "source_url": node.get("source_url"),
                    "retrieval_score": 0.95, # 명시적 참조는 가장 높은 신뢰도
                    "match_reason": "article_ref_injection"
                })
        except Exception as e:
            print(f"[Warning] Neo4j Article Ref 주입 실패: {e}")
        

    # 핵심 조문과 확장 조문 병합
    # 중복 제거 (chunk_id 기준)
    seen = {p["chunk_id"] for p in core_provisions if "chunk_id" in p}
    for chunk in expanded_chunks:
        if chunk.get("chunk_id") and chunk["chunk_id"] not in seen:
            core_provisions.append(chunk)
            seen.add(chunk["chunk_id"])
            
    return core_provisions
