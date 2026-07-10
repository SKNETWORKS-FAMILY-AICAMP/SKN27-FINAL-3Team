# LawGroundSearch 에이전트 전체 구성도
## (실제 구현 코드 기반 시퀀스 다이어그램)

```mermaid
sequenceDiagram
    actor User as 👤 사용자
    participant Supervisor as Supervisor Agent
    participant Agent as LawGroundSearch Agent<br/>(agent.py)
    participant RuleGuard as Rule Guard<br/>(rule_guard.py)
    participant QU as Query Understanding<br/>(query_understanding.py)
    participant HintGraph as Neo4j Hint Graph<br/>(UserTerm → LegalTerm)
    participant VectorSearch as Vector Search<br/>(etl/legal/search.py)
    participant OpenAI as OpenAI API<br/>(text-embedding-3-large)
    participant JSONL as 임베딩 DB<br/>(law_embeddings_openai.jsonl)
    participant LawGraph as Neo4j Law Graph<br/>(LawChunk 조항 관계)

    User->>Supervisor: "전동킥보드 뺑소니 처벌이 어떻게 돼?"
    Supervisor->>Agent: run_law_ground_search(context)

    Note over Agent,RuleGuard: ① 입력 검증 (Input Validation)
    Agent->>RuleGuard: validate_input_envelope(context)
    RuleGuard-->>Agent: valid=True

    Note over Agent,HintGraph: ② Query Understanding + Neo4j Hint Graph Boosting
    Agent->>QU: process_query("전동킥보드 뺑소니...")
    QU->>QU: Regex 추출 (조문번호, 날짜, 금액, 벌점)
    QU->>HintGraph: MATCH (u:UserTerm)-[:NORMALIZES_TO]->(l:LegalTerm)<br/>-[:SEARCHES_WITH]->(s:LawSearchTerm)<br/>WHERE u.text CONTAINS word
    HintGraph-->>QU: ["개인형 이동장치", "원동기장치자전거", "도로교통법"]
    QU-->>Agent: boosted_query = "...개인형 이동장치 원동기장치자전거 도로교통법"

    Note over Agent,JSONL: ③ Vector Search (OpenAI 임베딩 기반)
    Agent->>VectorSearch: search_laws(boosted_query, top_k=5)
    VectorSearch->>OpenAI: text → 벡터 변환 요청
    OpenAI-->>VectorSearch: 쿼리 임베딩 벡터 (1536dim)
    VectorSearch->>JSONL: 코사인 유사도 계산 (10만 건 법령 임베딩과 비교)
    JSONL-->>VectorSearch: Top-5 조문 (score 0.65~0.75)
    VectorSearch-->>Agent: core_provisions 5건

    Note over Agent,LawGraph: ④ Neo4j Law Graph 확장 (조항 관계 탐색)
    Agent->>LawGraph: MATCH (c1:LawChunk)-[r]->(c2:LawChunk)<br/>WHERE type(r) IN ["HAS_PENALTY","HAS_APPENDIX",...]
    LawGraph-->>Agent: 확장 조문 (별표, 처벌 관련 연결 조항)

    Note over Agent: ⑤ 신뢰도 평가 (Confidence Evaluation)
    Agent->>Agent: evaluate_confidence(provisions)<br/>Top-1 score >= 0.50 확인

    alt 신뢰도 부족 (score < 0.50)
        Agent->>VectorSearch: LLM Fallback - search_laws(llm_keywords)
        VectorSearch-->>Agent: 2차 검색 결과
    end

    Note over Agent,RuleGuard: ⑥ Rule Guard 필터링 (출력 통제)
    Agent->>RuleGuard: validate_and_filter_provisions(provisions, scope)
    RuleGuard->>RuleGuard: 비법령 제외 / provision_text 누락 제외<br/>source_url 누락 제외
    RuleGuard-->>Agent: valid_provisions (최종 정제 조문)

    Note over Agent,Supervisor: ⑦ 최종 결과 반환
    Agent-->>Supervisor: structured_result<br/>law_provisions / status / limitations
    Supervisor-->>User: 법률 근거 기반 최종 답변 생성
```

---

## 주요 컴포넌트 역할 요약

| 컴포넌트 | 파일 | 역할 | 구현 상태 |
|---|---|---|---|
| **Rule Guard** | `rule_guard.py` | 입력 검증 + 출력 필터링 | ✅ 완료 |
| **Query Understanding** | `query_understanding.py` | 정규식 추출 + Neo4j 힌트 부스팅 | ✅ 완료 |
| **Neo4j Hint Graph** | Neo4j DB | 일상어 → 법률용어 변환 | ✅ 코드 완료 / ⚠️ 테스트 데이터만 적재 |
| **Vector Search** | `etl/legal/search.py` | OpenAI 임베딩 기반 코사인 유사도 검색 | ✅ 완료 (10만 건) |
| **Neo4j Law Graph** | Neo4j DB | 조항 간 처벌·별표·예외·일반 참조 관계 확장 | ✅ extra relation ETL/export 연결 / ⚠️ 산출물 적재 후 count 검증 필요 |
| **Confidence Eval** | `search.py` | Top-1 점수(0.50) 기준 신뢰도 판정 | ✅ 완료 |
| **LLM Fallback** | `agent.py` | 신뢰도 부족 시 LLM 키워드 추출 2차 검색 | ✅ 완료 (LLM 외부 주입 필요) |
