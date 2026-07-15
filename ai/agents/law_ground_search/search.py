import logging
import re
from datetime import date, datetime
from typing import Any


logger = logging.getLogger(__name__)

LAW_GRAPH_EXPANSION_RELATION_TYPES = ["HAS_PENALTY", "HAS_APPENDIX", "HAS_EXCEPTION", "RELATED_TO"]
_STRICT_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

def search_law_provisions(
    query_text: str,
    article_refs: list[str],
    temporal_basis: dict[str, Any],
    scope: dict[str, Any],
    neo4j_session: Any = None,
    top_k: int = 5
) -> list[dict[str, Any]]:
    """
    설정된 운영 legal RAG 검색 후 특정 관계(처벌/별표)를 정밀 확장한다.
    """
    # Provider/model/cost policy는 legal_rag_service의 환경 설정 한 곳에서 결정한다.
    # Agent가 별도 ETL 검색기를 호출하면 운영 설정을 우회해 예기치 않은 유료
    # embedding 요청이나 seed provider 불일치가 생길 수 있으므로 사용하지 않는다.
    core_provisions = _search_fallback_legal_rag(
        query_text=query_text,
        top_k=top_k,
        temporal_basis=temporal_basis,
        scope=scope,
    )

    # Temporal & Scope 검증 (초반 필터)
    # 실제 구현에서는 rule_guard를 통해 거르거나 쿼리 시점에 필터링합니다.
    
    # 2. Neo4j Law Graph 관계 확장 (초안 스펙 복원: 타겟팅 확장)
    if neo4j_session and core_provisions:
        core_scores = {p["chunk_id"]: p.get("score", p.get("retrieval_score", 0.0)) for p in core_provisions if "chunk_id" in p}
        core_provisions = _expand_with_law_graph(
            core_provisions,
            article_refs,
            neo4j_session,
            core_scores,
            temporal_basis=temporal_basis,
            scope=scope,
        )

    return core_provisions

def _search_fallback_legal_rag(
    query_text: str,
    top_k: int,
    temporal_basis: dict[str, Any],
    scope: dict[str, Any],
) -> list[dict[str, Any]]:
    """Django RAG tables fallback for local/dev environments without pgvector."""
    try:
        from app.services import legal_rag_service

        rag_response = legal_rag_service.search_legal_rag(
            query_text,
            top_k=top_k,
            source_type="law",
            temporal_basis=temporal_basis,
            scope=scope,
        )
    except Exception as exc:
        logger.warning(
            "Django RAG fallback failed; error_class=%s",
            exc.__class__.__name__,
        )
        return []

    if rag_response.get("status") != "ready":
        return []

    provisions = []
    backend = rag_response.get("backend") or "django_rag_tables"
    retrieval_metadata = {
        key: value
        for key, value in rag_response.items()
        if key != "results"
    }
    for item in rag_response.get("results") or []:
        source_reference = item.get("source_reference") or item.get("chunk_id") or ""
        provisions.append(
            {
                "chunk_id": source_reference,
                "source_ref": source_reference,
                "source_name": item.get("source_name"),
                "source_id": item.get("source_id") or item.get("source_document_id") or "",
                "source_type": item.get("source_type") or "law",
                "article_no": item.get("article") or item.get("section_ref"),
                "appendix_no": None,
                "article_title": item.get("title"),
                "summary": item.get("summary") or "",
                "provision_text": item.get("provision_text") or "",
                "source_url": item.get("source_url") or "",
                "enforce_date": item.get("effective_date"),
                "expire_date": item.get("expire_date"),
                "retrieval_score": item.get("score", 0.0),
                "score": item.get("score", 0.0),
                "matched_token_count": item.get("matched_token_count"),
                "query_token_count": item.get("query_token_count"),
                "match_reason": f"legal_rag_fallback:{backend}",
                "_retrieval": retrieval_metadata,
            }
        )
    return provisions

def evaluate_confidence(provisions: list[dict[str, Any]]) -> dict[str, Any]:
    if not provisions:
        return {"is_confident": False, "reason": "검색 결과 없음", "reason_code": "no_results"}

    top_result = provisions[0]
    top1_score = float(top_result.get("score", top_result.get("retrieval_score", 0.0)) or 0.0)
    retrieval = top_result.get("_retrieval") if isinstance(top_result.get("_retrieval"), dict) else {}
    score_kind = retrieval.get("score_kind")
    backend = retrieval.get("backend")
    if score_kind == "token_coverage" or backend in {"postgres_lexical", "django_rag_tables"}:
        matched_token_count = int(top_result.get("matched_token_count") or 0)
        query_token_count = int(
            top_result.get("query_token_count") or retrieval.get("query_token_count") or 0
        )
        if matched_token_count < 2 or query_token_count < 2:
            return {
                "is_confident": False,
                "reason": "Lexical 검색에서 서로 다른 검색 토큰 2개 이상이 일치하지 않음",
                "reason_code": "insufficient_lexical_term_support",
            }
        if top1_score < 0.5:
            return {
                "is_confident": False,
                "reason": f"Lexical token coverage({top1_score:.3f})가 기준치(0.5) 미만",
                "reason_code": "low_lexical_token_coverage",
            }
        return {
            "is_confident": True,
            "reason": "Lexical token coverage와 일치 토큰 수가 기준을 충족",
            "reason_code": "lexical_token_coverage_sufficient",
        }

    THRESHOLD = 0.4

    if top1_score < THRESHOLD:
        return {
            "is_confident": False,
            "reason": f"Top-1 score({top1_score:.3f})가 기준치({THRESHOLD}) 미만",
            "reason_code": "low_vector_score",
        }

    return {
        "is_confident": True,
        "reason": "Vector similarity score가 기준을 충족",
        "reason_code": "vector_score_sufficient",
    }

def _expand_with_law_graph(
    core_provisions: list[dict],
    article_refs: list[str],
    session: Any,
    core_scores: dict[str, float] | None = None,
    *,
    temporal_basis: dict[str, Any] | None = None,
    scope: dict[str, Any] | None = None,
) -> list[dict]:
    """Neo4j Law Graph 타겟팅 확장 쿼리 및 명시적 조문(article_refs) 병합"""
    if not session or not core_provisions:
        return core_provisions
    from app.services.legal_rag_service import resolve_legal_search_filters

    allowed_source_types, effective_at, filter_error = resolve_legal_search_filters(
        source_type="law",
        temporal_basis=temporal_basis,
        scope=scope,
    )
    if filter_error or effective_at is None or not allowed_source_types:
        return core_provisions

    core_scores = core_scores or {}
    chunk_ids = [p["chunk_id"] for p in core_provisions if "chunk_id" in p]
    core_source_ids = list(
        dict.fromkeys(
            str(provision.get("source_id") or "").strip()
            for provision in core_provisions
            if str(provision.get("source_id") or "").strip()
        )
    )
    expanded_chunks = []

    # [1] Reverse Graph Expansion
    if chunk_ids:
        query_graph = """
        UNWIND $chunk_ids AS cid
        MATCH (c1:LawChunk {chunk_id: cid})-[r]-(c2:LawChunk)
        WHERE type(r) IN $relation_types
          AND c2.is_searchable = true
          AND c2.source_type IN $allowed_source_types
          AND c2.enforce_date IS NOT NULL
          AND date(c2.enforce_date) <= date($effective_at)
          AND (c2.expire_date IS NULL OR date(c2.expire_date) >= date($effective_at))
        RETURN cid, type(r) AS relation_type, c2 LIMIT 100
        """
        try:
            result = session.run(
                query_graph,
                chunk_ids=chunk_ids,
                relation_types=LAW_GRAPH_EXPANSION_RELATION_TYPES,
                allowed_source_types=list(allowed_source_types),
                effective_at=effective_at,
            )
            for record in result:
                cid = record["cid"]
                relation_type = record["relation_type"]
                node = record["c2"]
                if not _graph_node_is_allowed(
                    node,
                    allowed_source_types=allowed_source_types,
                    effective_at=effective_at,
                ):
                    continue
                base_score = core_scores.get(cid, 0.5)
                expanded_chunks.append(
                    _graph_node_result(
                        node,
                        retrieval_score=base_score * 0.9,
                        match_reason=f"graph_expansion:{relation_type}",
                    )
                )
        except Exception as exc:
            logger.warning(
                "Neo4j law graph expansion failed; error_class=%s",
                exc.__class__.__name__,
            )
            
    # [2] 명시적 조문(article_refs) 주입 (강력한 정답 유도)
    if article_refs and core_source_ids:
        query_refs = """
        UNWIND $refs AS ref
        MATCH (c:LawChunk)
        WHERE c.article_no = ref
          AND c.source_id IN $core_source_ids
          AND c.is_searchable = true
          AND c.source_type IN $allowed_source_types
          AND c.enforce_date IS NOT NULL
          AND date(c.enforce_date) <= date($effective_at)
          AND (c.expire_date IS NULL OR date(c.expire_date) >= date($effective_at))
        RETURN c LIMIT 10
        """
        try:
            result = session.run(
                query_refs,
                refs=article_refs,
                core_source_ids=core_source_ids,
                allowed_source_types=list(allowed_source_types),
                effective_at=effective_at,
            )
            for record in result:
                node = record["c"]
                if not _graph_node_is_allowed(
                    node,
                    allowed_source_types=allowed_source_types,
                    effective_at=effective_at,
                ):
                    continue
                expanded_chunks.append(
                    _graph_node_result(
                        node,
                        retrieval_score=0.95,
                        match_reason="article_ref_injection",
                    )
                )
        except Exception as exc:
            logger.warning(
                "Neo4j article reference lookup failed; error_class=%s",
                exc.__class__.__name__,
            )
        

    # 핵심 조문과 확장 조문 병합
    # 중복 제거 (chunk_id 기준)
    seen = {p["chunk_id"] for p in core_provisions if "chunk_id" in p}
    for chunk in expanded_chunks:
        if chunk.get("chunk_id") and chunk["chunk_id"] not in seen:
            core_provisions.append(chunk)
            seen.add(chunk["chunk_id"])
            
    return core_provisions


def _graph_node_is_allowed(
    node: Any,
    *,
    allowed_source_types: tuple[str, ...],
    effective_at: date,
) -> bool:
    for field in ("chunk_id", "source_id", "provision_text", "source_url"):
        value = node.get(field)
        if not isinstance(value, str) or not value.strip():
            return False
    if node.get("is_searchable") is not True:
        return False
    if str(node.get("source_type") or "").strip() not in allowed_source_types:
        return False
    enforce_date = _graph_date(node.get("enforce_date"))
    expire_value = node.get("expire_date")
    expire_date = _graph_date(expire_value) if expire_value not in (None, "") else None
    if enforce_date is None or enforce_date > effective_at:
        return False
    if expire_value not in (None, "") and expire_date is None:
        return False
    return expire_date is None or expire_date >= effective_at


def _graph_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "to_native"):
        native_value = value.to_native()
        if isinstance(native_value, datetime):
            return native_value.date()
        if isinstance(native_value, date):
            return native_value
    text = str(value or "").strip()
    if not _STRICT_ISO_DATE_PATTERN.fullmatch(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _graph_node_result(
    node: Any,
    *,
    retrieval_score: float,
    match_reason: str,
) -> dict[str, Any]:
    return {
        "chunk_id": node.get("chunk_id"),
        "source_id": node.get("source_id"),
        "source_ref": node.get("source_ref"),
        "source_name": node.get("source_name"),
        "article_no": node.get("article_no"),
        "appendix_no": node.get("appendix_no"),
        "article_title": node.get("article_title"),
        "provision_text": node.get("provision_text"),
        "source_type": node.get("source_type"),
        "source_url": node.get("source_url"),
        "enforce_date": node.get("enforce_date"),
        "expire_date": node.get("expire_date"),
        "retrieval_score": retrieval_score,
        "score": retrieval_score,
        "match_reason": match_reason,
    }
