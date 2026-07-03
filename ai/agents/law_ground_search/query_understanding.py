import re
from dataclasses import dataclass
from typing import Any

@dataclass
class QueryUnderstandingResult:
    original_query: str
    boosted_query: str
    hint_terms: list[str]
    article_refs: list[str]
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
    
    # 1. Regex 기반 정보 추출
    article_refs = _extract_article_numbers(text_to_process)
    
    # 2. Neo4j Hint Graph 쿼리
    hint_terms = []
    if neo4j_session:
        hint_terms = _boost_with_neo4j_stub(text_to_process, neo4j_session)
    
    searchability = len(text_to_process.strip()) >= 1
    missing_fields = []
    
    if not searchability:
        missing_fields.append("질의가 입력되지 않았습니다.")
        boosted_query = text_to_process
    else:
        boosted_query = f"{text_to_process} {' '.join(hint_terms)}".strip()
    
    return QueryUnderstandingResult(
        original_query=text_to_process,
        boosted_query=boosted_query,
        hint_terms=hint_terms,
        article_refs=article_refs,
        searchability=searchability,
        missing_fields=missing_fields
    )

def _extract_article_numbers(text: str) -> list[str]:
    # Match "제 N 조" or "제 N 조의 M" or "N조" or "N조의 M"
    matches = re.finditer(r"(?:제\s*)?(\d+)\s*조(?:의\s*(\d+))?", text)
    result = []
    for m in matches:
        main_num = m.group(1)
        sub_num = m.group(2)
        if sub_num:
            result.append(f"제{main_num}조의{sub_num}")
        else:
            result.append(f"제{main_num}조")
    return result

def _boost_with_neo4j_stub(text: str, session: Any) -> list[str]:
    """Neo4j Hint Graph에서 연관 검색어를 찾아옵니다."""
    if not session:
        return []
    
    query = """
    MATCH (u:UserTerm)-[:NORMALIZES_TO]->(l:LegalTerm)-[:SEARCHES_WITH]->(s:LawSearchTerm)
    WHERE $text CONTAINS u.text AND size(u.text) >= 2
    RETURN DISTINCT s.text AS search_term
    """
    
    try:
        result = session.run(query, text=text)
        return [record["search_term"] for record in result]
    except Exception as e:
        print(f"[Warning] Neo4j Hint Graph 쿼리 실패: {e}")
        return []
