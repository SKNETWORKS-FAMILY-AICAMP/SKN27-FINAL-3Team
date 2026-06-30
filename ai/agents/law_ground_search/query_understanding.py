import re
from dataclasses import dataclass
from typing import Any

@dataclass
class QueryUnderstandingResult:
    original_query: str
    boosted_query: str
    article_refs: list[str]
    dates: list[str]
    amounts: list[str]
    demerit_points: list[str]
    searchability: bool
    missing_fields: list[str]

def process_query(
    raw_text: str, 
    search_query: str | None = None,
    retrieval_seed: dict[str, Any] | None = None,
    neo4j_session: Any = None
) -> QueryUnderstandingResult:
    """
    1차 MVP + 복원 스펙: 다중 Regex 추출 + Neo4j Hint Graph + Searchability 검증
    """
    text_to_process = search_query if search_query else raw_text
    
    # 1. Regex 기반 다중 정보 추출 (초안 스펙 복원)
    article_refs = _extract_article_numbers(text_to_process)
    dates = _extract_dates(text_to_process)
    amounts = _extract_amounts(text_to_process)
    demerits = _extract_demerit_points(text_to_process)
    
    # 2. Neo4j Hint Graph 쿼리
    hint_terms = []
    if neo4j_session:
        # 실제: MATCH (u:UserTerm)-[:NORMALIZES_TO]->(l:LegalTerm)-[:SEARCHES_WITH]->(s:LawSearchTerm)
        hint_terms = _boost_with_neo4j_stub(text_to_process, neo4j_session)
    
    # 3. Searchability (검색 포기) 게이트 (초안 스펙 복원)
    # 조문번호도 없고, 추출된 힌트 단어도 없다면 엉뚱한 벡터 검색 방지를 위해 포기
    has_clues = bool(article_refs or hint_terms)
    searchability = True
    missing_fields = []
    
    if not has_clues:
        searchability = False
        missing_fields.append("법령 검색을 위한 최소한의 단서(법률 용어 또는 조문 번호)가 부족합니다.")
        boosted_query = text_to_process
    else:
        boosted_query = f"{text_to_process} {' '.join(hint_terms)}".strip()
    
    return QueryUnderstandingResult(
        original_query=text_to_process,
        boosted_query=boosted_query,
        article_refs=article_refs,
        dates=dates,
        amounts=amounts,
        demerit_points=demerits,
        searchability=searchability,
        missing_fields=missing_fields
    )

def _extract_article_numbers(text: str) -> list[str]:
    return [m.replace(" ", "") for m in re.findall(r"제\s*\d+\s*조", text)]

def _extract_dates(text: str) -> list[str]:
    return re.findall(r"\d{4}년\s*\d{1,2}월\s*\d{1,2}일", text)

def _extract_amounts(text: str) -> list[str]:
    return re.findall(r"\d+[만천백십원]+", text)

def _extract_demerit_points(text: str) -> list[str]:
    return re.findall(r"\d+\s*점", text)

def _boost_with_neo4j_stub(text: str, session: Any) -> list[str]:
    """Neo4j Hint Graph에서 연관 검색어를 찾아옵니다."""
    if not session:
        return []
    
    # UserTerm과 텍스트 매칭을 위해 입력 문장을 단어 단위로 쪼개거나 전체를 활용할 수 있습니다.
    # MVP에서는 text 전체를 간단히 MATCH에 사용하거나 단어 리스트로 쪼개어 사용합니다.
    words = text.split()
    
    query = """
    UNWIND $words AS word
    MATCH (u:UserTerm)-[:NORMALIZES_TO]->(l:LegalTerm)-[:SEARCHES_WITH]->(s:LawSearchTerm)
    WHERE u.text CONTAINS word
    RETURN DISTINCT s.text AS search_term
    """
    
    try:
        result = session.run(query, words=words)
        return [record["search_term"] for record in result]
    except Exception as e:
        print(f"[Warning] Neo4j Hint Graph 쿼리 실패: {e}")
        return []
