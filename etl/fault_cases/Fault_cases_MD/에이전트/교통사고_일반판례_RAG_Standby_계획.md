# 교통사고 일반판례 RAG/Search V1 실행 요약

## A. 지금 단계의 결론

현재 `traffic_precedent`는 Agent가 아니라 **교통사고 일반판례 RAG/Search**까지만 만든다.

```text
V1 검색 방식:
  BM25+Nori 단독

V1에서 하지 않는 것:
  Agent 구현
  Supervisor 실제 연결
  text_ml_case_search V2 active source 편입
  hint expansion 구현
  pgvector / hybrid 비교
  local reranker A/B 평가
```

이유:

```text
1. traffic_precedent는 과실비율 직접 판단보다 교통사고 일반 법률/주의의무/책임 판단에 가깝다.
2. 현재 프로젝트에는 법률용어 hint expansion 구조가 없다.
3. Elasticsearch + Nori 환경은 이미 구축되어 있다.
4. 교통사고 판례는 신호위반, 중앙선 침범, 보행자 보호의무, 전방주시의무 같은 키워드가 중요하다.
5. 따라서 V1은 BM25+Nori baseline부터 작게 검증하는 것이 맞다.
```

---

## B. 단계별 실행 순서

### 1단계. traffic_precedent 검색 인프라 확인

할 일:

```text
1. traffic_precedent Elasticsearch index 이름 확인
2. index mapping 확인
3. 검색에 쓸 field 확인
4. 기존 precedent_search 코드 재사용 가능 여부 확인
```

왜 필요한가:

```text
실제 index field를 모르면 BM25 검색 field를 정확히 잡을 수 없다.
없는 field를 검색 대상으로 넣으면 검색 품질이 떨어지거나 결과 해석이 꼬일 수 있다.
```

예상 결과:

```text
BM25 검색에 사용할 index명과 field 후보가 정리된다.
```

---

### 2단계. traffic_law sample query 10개 작성

할 일:

```text
교통사고 일반 법률 쟁점을 대표하는 query 10개를 코드로 정의한다.
```

예상 파일:

```text
etl/fault_cases/src/traffic_precedents/precedent_search/traffic_law/sample_queries.py
```

예상 결과:

```text
traffic_law_q001 ~ traffic_law_q010 query set이 생긴다.
```

---

### 3단계. BM25+Nori retriever 작성

할 일:

```text
traffic_precedent Elasticsearch index에 BM25+Nori 검색 요청을 보내는 코드를 만든다.
```

예상 파일:

```text
etl/fault_cases/src/traffic_precedents/precedent_search/traffic_law/bm25_nori_retriever.py
```

포함할 것:

```text
multi_match
operator = "or"
highlight
search_text / chunk_text 중심 field
```

예상 결과:

```text
단일 query를 넣으면 top_k traffic_precedent 검색 결과를 받을 수 있다.
```

---

### 4단계. sample query 실행 runner 작성

할 일:

```text
sample query 10개를 BM25+Nori로 실행하고 결과 JSON을 저장한다.
```

예상 파일:

```text
etl/fault_cases/src/traffic_precedents/precedent_search/traffic_law/run_bm25_sample_queries.py
```

예상 산출물:

```text
etl/fault_cases/artifacts/traffic_precedents_output/traffic_law_rag/traffic_law_bm25_sample_queries.json
etl/fault_cases/artifacts/traffic_precedents_output/traffic_law_rag/traffic_law_bm25_summary.json
```

예상 결과:

```text
각 query별 top5 판례 후보가 저장된다.
```

---

### 5단계. 검색 평가 보고서 생성

할 일:

```text
검색 결과 JSON을 읽어서 사람이 볼 수 있는 MD 보고서를 만든다.
```

예상 파일:

```text
etl/fault_cases/src/traffic_precedents/precedent_search/traffic_law/build_rag_report.py
```

보고서 위치:

```text
etl/fault_cases/Fault_cases_MD/에이전트/교통사고_일반판례_RAG_검색_평가_보고서.md
```

보고서에 들어갈 내용:

```text
1. query별 top1 판례
2. query별 top5 후보 수
3. case_name / case_number / court_name / decision_date
4. source_reference
5. chunk_preview
6. matched_snippets
7. 사람이 검수해야 할 부분
```

예상 결과:

```text
BM25+Nori 단독 검색이 traffic_precedent V1로 충분한지 사람이 검토할 수 있다.
```

---

### 6단계. 사람이 결과 검수

할 일:

```text
생성된 MD 보고서에서 query별 대표 판례가 실제 질문과 맞는지 확인한다.
```

확인할 것:

```text
1. top1 판례가 질문과 맞는가
2. top5 안에 쓸 만한 판례가 있는가
3. matched_snippets가 법률 쟁점을 보여주는가
4. 과실비율 근거로 오해될 위험은 없는가
5. traffic_precedent가 주의의무/책임 판단 근거로 적절한가
```

예상 결과:

```text
BM25+Nori 단독 유지 여부를 판단한다.
부족하면 hint/vector/hybrid를 추후 확장 후보로 검토한다.
```

---

## C. 파일 구조 계획

위치는 **Agent 폴더가 아니라 기존 판례 검색 흐름 아래**로 둔다.

기준 위치:

```text
etl/fault_cases/src/traffic_precedents/precedent_search/traffic_law/
```

V1에서 실제로 필요한 최소 구조:

```text
traffic_law/
  __init__.py
  sample_queries.py
  bm25_nori_retriever.py
  run_bm25_sample_queries.py
  build_rag_report.py
```

각 파일 역할:

```text
sample_queries.py
→ 교통사고 일반판례 RAG 테스트 query 10개 정의

bm25_nori_retriever.py
→ traffic_precedent Elasticsearch index에 BM25+Nori 검색 요청

run_bm25_sample_queries.py
→ sample query 10개를 돌려서 검색 결과 JSON 생성

build_rag_report.py
→ 검색 결과를 사람이 볼 수 있는 MD 보고서로 정리
```

산출물 위치:

```text
etl/fault_cases/artifacts/traffic_precedents_output/traffic_law_rag/
  traffic_law_bm25_sample_queries.json
  traffic_law_bm25_summary.json
```

보고서 위치:

```text
etl/fault_cases/Fault_cases_MD/에이전트/
  교통사고_일반판례_RAG_검색_평가_보고서.md
```

추후 확장 파일은 V1에 만들지 않고, 나중에 필요할 때만 추가한다.

```text
legal_hint_dictionary.py
search_text_builder.py
pgvector_retriever.py
hybrid_retriever.py
export_ab_candidates.py
run_local_reranker.py
```

현재 계획:

```text
V1 = BM25+Nori 검색 폴더만 작게 만든다.
추후 확장 = hint/vector/hybrid/reranker 파일을 나중에 추가한다.
```

---
# 교통사고 일반판례 RAG/Search Standby 계획

작성 기준일: 2026-07-05

---

## 0. 문서 목적

이 문서는 `traffic_precedent`를 이용한 **교통사고 일반판례 RAG/Search 계획**을 정리한다.

중요한 전제는 다음과 같다.

```text
traffic_precedent는 지금 단계에서 별도 Agent를 만들지 않는다.
traffic_precedent는 text_ml_case_search V2 active source로 바로 합치지 않는다.
traffic_precedent는 교통사고 일반 법률/주의의무/책임 판단용 RAG/Search 모듈로 따로 준비한다.
```

즉 이 문서의 범위는 **검색 모듈과 평가 계획**까지다.

```text
포함:
  - traffic_precedent 검색 방식 설계
  - V1 BM25+Nori 검색 baseline
  - 검색 결과 후보 포맷
  - BM25+Nori 결과 검수 및 평가 계획
  - 향후 교통사고 법률 Agent 또는 Supervisor 연결 준비

제외:
  - 별도 traffic law Agent 구현
  - Supervisor 최종 output schema에 바로 연결
  - text_ml_case_search V2 evidence merge에 즉시 포함
  - 과실비율 확정 또는 ratio_range_label 주 근거로 사용
```

---

## 1. 왜 traffic_precedent를 별도로 분리하는가

현재 `text_ml_case_search` V2는 과실비율 판단 보조 Agent이다.

```text
text_ml_case_search V2 active source:
  1. review_case
     - 과실비율 심의사례

  2. fault_ratio_precedent
     - 과실상계, 손해배상, 과실비율 관련 판례
```

반면 `traffic_precedent`는 교통사고 일반 법률 쟁점에 더 가깝다.

```text
traffic_precedent 주요 역할:
  - 운전자 주의의무
  - 전방주시의무
  - 안전거리 확보의무
  - 신호위반 책임
  - 중앙선 침범
  - 보행자 보호의무
  - 사고 후 미조치
  - 음주운전
  - 교통사고처리특례법 관련 쟁점
  - 형사책임 또는 민사책임 판단 맥락
```

따라서 `traffic_precedent`를 과실비율 Agent에 바로 섞으면 역할이 흐려질 수 있다.

```text
fault_ratio_precedent:
  과실비율/과실상계 판단에 직접 가까움

traffic_precedent:
  교통법규 위반, 주의의무, 형사/민사 책임 맥락에 가까움
```

결론:

```text
traffic_precedent는 text_ml_case_search V2의 standby source가 아니라,
향후 교통사고 법률 RAG/Search 또는 교통사고 법률 Agent에서 사용할 별도 source로 관리한다.
```

---

## 2. 법률 A/B 테스트 문서에서 가져올 원칙

참고 문서:

```text
etl/fault_cases/Fault_cases_MD/참고/ab_test_report.md
etl/fault_cases/Fault_cases_MD/참고/ab_test_scores.md
```

위 문서의 핵심은 다음과 같다.

```text
법률 검색에서는 사용자의 일상어와 법률/판례 표현 사이의 간격이 크다.
다만 현재 프로젝트에는 법률용어 hint expansion 구조가 아직 없다.
따라서 V1에서는 이미 구축된 Elasticsearch BM25+Nori를 기본 검색 방식으로 사용한다.
법률용어 hint, vector, hybrid는 V1 결과가 부족할 때 검토할 추후 개선 후보로 둔다.
```

예시:

```text
사용자 표현:
  뺑소니

법률/판례 표현:
  사고 후 미조치
  도주차량
  특정범죄가중처벌

사용자 표현:
  전동킥보드 사고

법률/판례 표현:
  개인형 이동장치
  원동기장치자전거

사용자 표현:
  보행자 사고

법률/판례 표현:
  보행자 보호의무
  전방주시의무
  횡단보도 통행
```

이 원칙은 `traffic_precedent`에도 적용되지만, V1에서는 새 확장 구조를 만들지 않고 BM25+Nori baseline부터 검증한다.

---

## 3. traffic_precedent RAG의 1차 목표

1차 목표는 교통사고 일반판례 검색 품질을 확인하는 것이다.

```text
목표:
  사용자의 사고 설명에서 관련 교통사고 일반판례를 안정적으로 찾는다.

핵심 평가 기준:
  - 사고 유형이 맞는가
  - 법률 쟁점이 맞는가
  - 주의의무/책임 판단 근거로 쓸 수 있는가
  - 과실비율 근거로 오해될 위험은 없는가
```

이 RAG는 다음 용도로 쓰일 수 있다.

```text
향후 사용처:
  - 교통사고 법률 Agent
  - Supervisor의 보조 법률 근거 검색
  - 사고 책임/주의의무 설명 보강
  - 과실비율 Agent의 한계 설명 보조
```

---

## 4. V1 검색 방식 결정

현재 `traffic_precedent` RAG/Search V1은 **BM25+Nori 단독 검색**으로 시작한다.

결정 이유:

```text
1. traffic_precedent는 교통사고 일반판례이므로 법률/사고 쟁점 키워드가 중요하다.
2. 신호위반, 중앙선 침범, 전방주시의무, 보행자 보호의무, 안전거리 같은 표현은 BM25+Nori에 적합하다.
3. Elasticsearch + Nori 환경은 이미 구축되어 있다.
4. 판례/심의사례 검색에서 BM25+Nori를 사용한 경험이 있다.
5. 현재 프로젝트에는 법률용어 hint expansion 구조가 없다.
6. traffic_precedent는 아직 Agent가 아니라 RAG/Search standby 단계이므로 먼저 단순하고 검증 가능한 검색부터 시작하는 것이 맞다.
```

V1 active 검색 방식:

```text
BM25+Nori
```

V1에서 하지 않는 것:

```text
1. 법률용어 hint expansion 구현
2. pgvector 검색 구현
3. Elasticsearch hybrid 검색 구현
4. Graph-RAG 또는 Neo4j 연동
```

추후 개선 후보:

| 후보 | 검토 시점 | 이유 |
|---|---|---|
| BM25+Nori + 법률용어 hint | BM25 결과가 일상어 query에서 약할 때 | 사용자 표현과 판례 표현 차이 보완 |
| pgvector | 의미 검색이 필요할 때 | 표현이 달라도 의미가 가까운 판례 탐색 |
| hybrid | BM25와 vector 장점을 함께 쓰고 싶을 때 | 키워드와 의미 검색 결합 |
| Graph-RAG | 법률 용어 연결 구조가 필요할 때 | 법령/판례 표현 간 관계 확장 |
```

---

## 5. 추후 확장 후보: 법률용어 hint

이 섹션은 V1 구현 대상이 아니라, **BM25+Nori 결과가 부족할 때 검토할 추후 개선 후보**다.

목적:

```text
사용자의 일상어 query에 법률/판례에서 자주 쓰이는 표현을 보강한다.
```

추후 구현할 경우 예상 파일:

```text
etl/fault_cases/src/traffic_precedents/precedent_search/traffic_law/legal_hint_dictionary.py
```

예시:

```python
LEGAL_HINTS = {
    "뺑소니": ["사고 후 미조치", "도주차량", "특정범죄가중처벌"],
    "전동킥보드": ["개인형 이동장치", "원동기장치자전거"],
    "보행자 사고": ["보행자 보호의무", "전방주시의무", "횡단보도"],
    "중앙선 침범": ["중앙선", "반대차선", "주의의무"],
    "음주운전": ["주취운전", "음주 상태", "위험운전"],
}
```

검색 입력 생성 예:

```text
원문:
  뺑소니 사고 후 운전자 책임 판례

확장 검색문:
  뺑소니 사고 후 운전자 책임 판례 사고 후 미조치 도주차량 특정범죄가중처벌
```

예상 효과:

```text
사용자가 일상어로 질문해도 판례의 공식 표현과 매칭될 가능성이 높아진다.
```

V1에서는 이 기능을 구현하지 않는다.

---

## 6. 테스트 query set

초기 테스트 query는 10개로 시작한다.

```text
traffic_law_q001: 신호위반 교통사고 판례
traffic_law_q002: 중앙선 침범 사고 운전자 책임
traffic_law_q003: 횡단보도 보행자 사고 운전자 주의의무
traffic_law_q004: 음주운전 교통사고 형사 책임
traffic_law_q005: 뺑소니 사고 후 미조치 판례
traffic_law_q006: 전동킥보드 교통사고 법적 책임
traffic_law_q007: 오토바이와 자동차 충돌 사고 책임
traffic_law_q008: 후방추돌 사고 안전거리 주의의무
traffic_law_q009: 어린이보호구역 사고 처벌 판례
traffic_law_q010: 교차로 좌회전 직진 충돌 주의의무
```

이 query set의 목적:

```text
1. 주요 교통사고 법률 쟁점을 넓게 포함한다.
2. 과실비율보다는 책임/주의의무/법규 위반 중심으로 구성한다.
3. BM25+Nori baseline 검색이 실제 판례를 잘 찾는지 확인한다.
```

---

## 7. 결과 후보 포맷

이 단계에서는 Agent output schema를 만들지 않는다.

대신 RAG/Search 평가용 후보 포맷을 만든다.

```json
{
  "query_id": "traffic_law_q001",
  "query": "신호위반 교통사고 판례",
  "retriever": "bm25_nori",
  "rank": 1,
  "source_type": "traffic_precedent",
  "case_id": "...",
  "chunk_id": "...",
  "case_name": "...",
  "case_number": "...",
  "court_name": "...",
  "decision_date": "...",
  "chunk_type": "...",
  "retriever_score": 123.45,
  "score_type": "bm25_score",
  "chunk_preview": "...",
  "matched_snippets": []
}
```

중요:

```text
retriever_score는 검색기 내부 점수다.
BM25 점수와 vector 점수는 직접 비교하지 않는다.
V1에서는 우선 BM25+Nori 결과를 사람이 검수한다.
추후 여러 검색 방식을 비교하게 되면 local reranker score를 공통 비교 기준으로 사용한다.
```

---

## 8. 평가 방식

V1에서는 BM25+Nori 단독 검색 결과를 먼저 검수한다.

추후 pgvector, hybrid, hint 확장을 추가하면 기존 판례/심의사례 A/B 평가와 같은 구조를 따른다.

```text
V1:
  1. BM25+Nori top_k 결과 생성
  2. query별 대표 판례 preview 확인
  3. matched_snippets 확인
  4. source_reference와 chunk_text 품질 확인

추후 A/B:
  1. 각 검색 방식별 top_k 결과 생성
  2. 후보를 공통 JSONL로 통합
  3. local reranker로 query + chunk_text relevance score 계산
  4. 검색 방식별 점수 요약
  5. 사람이 대표 chunk_preview / matched_snippets 검수
```

추후 A/B 확장 시 권장 지표:

```text
avg_reranker_score@5
max_reranker_score@5
top1_reranker_score
```

해석:

```text
avg_reranker_score@5:
  top5 전체 품질

max_reranker_score@5:
  top5 안에 좋은 근거가 하나라도 있는지

top1_reranker_score:
  검색기가 1순위로 올린 결과가 실제로 좋은지
```

---

## 9. 코드 구조 계획

Agent 폴더가 아니라 기존 판례 검색 흐름 아래에 둔다.

추천 위치:

```text
etl/fault_cases/src/traffic_precedents/precedent_search/traffic_law/
  __init__.py
  sample_queries.py
  bm25_nori_retriever.py
  build_rag_report.py
```

추후 A/B 확장 시 추가될 수 있는 파일:

```text
etl/fault_cases/src/traffic_precedents/precedent_search/traffic_law/
  legal_hint_dictionary.py
  search_text_builder.py
  pgvector_retriever.py
  hybrid_retriever.py
  export_ab_candidates.py
  run_local_reranker.py
```

이 위치를 추천하는 이유:

```text
1. traffic_precedent는 Agent가 아니라 판례 검색/RAG 실험에 가깝다.
2. 기존 precedent_search 흐름과 산출물 관리 방식을 재사용할 수 있다.
3. 나중에 교통사고 법률 Agent가 생기더라도 검색 모듈만 가져다 쓰면 된다.
```

---

## 10. 예상 산출물

검색 결과 산출물:

```text
etl/fault_cases/artifacts/traffic_precedents_output/traffic_law_rag/
  traffic_law_bm25_sample_queries.json
  traffic_law_bm25_summary.json
```

추후 A/B 확장 시 추가될 수 있는 산출물:

```text
etl/fault_cases/artifacts/traffic_precedents_output/traffic_law_rag/
  traffic_law_bm25_hint_sample_queries.json
  traffic_law_pgvector_sample_queries.json
  traffic_law_hybrid_sample_queries.json
  traffic_law_ab_candidates.jsonl
  traffic_law_reranker_scores.jsonl
  traffic_law_score_summary.json
```

문서 산출물:

```text
etl/fault_cases/Fault_cases_MD/에이전트/교통사고_일반판례_RAG_Standby_계획.md
etl/fault_cases/Fault_cases_MD/에이전트/교통사고_일반판례_RAG_검색_평가_보고서.md
```

---

## 11. 단계별 구현 계획

아래 단계는 단순 작업 목록이 아니라, 각 단계별로 **왜 필요한지, 목적이 무엇인지, 어떻게 진행할지, 어떤 코드가 생길지, 예상 결과가 무엇인지**를 함께 정리한 실행 계획이다.

---

### 11-1. Standby 계획 MD 정리

왜 필요한가:

```text
traffic_precedent는 과실비율 Agent에 바로 붙일 source가 아니다.
이 점을 먼저 문서로 고정하지 않으면, 나중에 text_ml_case_search V2에 억지로 섞거나 Supervisor output에 바로 합치는 식으로 역할이 흐려질 수 있다.
```

목적:

```text
traffic_precedent의 현재 범위를 "Agent 구현"이 아니라 "교통사고 일반판례 RAG/Search 준비"로 명확히 한다.
```

진행 방식:

```text
1. traffic_precedent의 역할을 정의한다.
2. text_ml_case_search V2 active source가 아님을 명시한다.
3. 향후 교통사고 법률 Agent 또는 Supervisor 보조 검색으로 확장 가능하다는 점을 적는다.
```

코드 계획:

```text
이 단계에서는 코드 수정 없음.
문서 기준만 확정한다.
```

예상 결과:

```text
팀원이 이 문서를 봤을 때 traffic_precedent를 "과실비율 Agent에 바로 추가할 source"로 오해하지 않는다.
```

---

### 11-2. traffic_law sample query 10개 작성

왜 필요한가:

```text
BM25+Nori 검색 품질을 확인하려면 같은 질문 세트가 필요하다.
query set이 없으면 검색 결과가 좋은지 나쁜지 기준을 세우기 어렵다.
```

목적:

```text
교통사고 일반 법률 쟁점을 대표하는 10개 테스트 질문을 고정한다.
```

진행 방식:

```text
1. 신호위반, 중앙선 침범, 보행자 사고, 음주운전, 뺑소니 등 대표 쟁점을 고른다.
2. 과실비율이 아니라 법률 책임/주의의무/교통법규 위반 중심으로 질문을 만든다.
3. BM25+Nori 검색이 같은 query_id와 query_text를 사용하게 한다.
4. 추후 A/B 확장 시에도 같은 query set을 재사용한다.
```

코드 계획:

```text
생성 예정 파일:
etl/fault_cases/src/traffic_precedents/precedent_search/traffic_law/sample_queries.py

예상 구조:
TRAFFIC_LAW_SAMPLE_QUERIES = [
    {
        "query_id": "traffic_law_q001",
        "query": "신호위반 교통사고 판례",
        "issue_tags": ["신호위반", "교차로", "주의의무"],
    },
    ...
]
```

예상 결과:

```text
traffic_law_q001 ~ traffic_law_q010까지 10개 query가 생긴다.
이후 모든 검색 실험은 이 query set을 공통 입력으로 사용한다.
```

---

### 11-3. BM25+Nori baseline 작성

왜 필요한가:

```text
교통사고 판례는 법률 용어와 판례 문구가 중요하다.
BM25+Nori는 한국어 형태소 기반 키워드 검색에 강하므로 가장 먼저 baseline으로 잡기 좋다.
```

목적:

```text
traffic_precedent index에서 일반 교통사고 판례를 BM25+Nori로 검색할 수 있게 한다.
```

진행 방식:

```text
1. Elasticsearch traffic_precedent index명을 확인한다.
2. 실제 mapping에 존재하는 field를 확인한다.
3. search_text, chunk_text, case_name, law_reference 등 검색 field를 구성한다.
4. operator="or"와 highlight를 사용한다.
5. sample query 10개에 대해 top_k 결과를 저장한다.
```

코드 계획:

```text
생성 예정 파일:
etl/fault_cases/src/traffic_precedents/precedent_search/traffic_law/bm25_nori_retriever.py

주요 함수:
build_traffic_law_bm25_query(...)
search_traffic_law_bm25(...)

예상 출력 파일:
etl/fault_cases/artifacts/traffic_precedents_output/traffic_law_rag/traffic_law_bm25_sample_queries.json
```

예상 결과:

```text
각 query별 top5 BM25 검색 결과가 생성된다.
각 결과에는 case_id, chunk_id, case_name, retriever_score, matched_snippets가 포함된다.
```

---

### 11-4. BM25+Nori 결과 보고서 생성

왜 필요한가:

```text
BM25 검색 결과 JSON만으로는 사람이 품질을 빠르게 판단하기 어렵다.
query별 대표 판례, matched snippet, source_reference를 보고서로 정리해야 한다.
```

목적:

```text
BM25+Nori baseline이 traffic_precedent RAG V1로 쓸 만한지 확인한다.
```

진행 방식:

```text
1. traffic_law_bm25_sample_queries.json을 읽는다.
2. query별 top1/top5 결과를 요약한다.
3. 대표 판례 제목, 사건번호, 법원, 판결일, source_reference를 보여준다.
4. matched_snippets와 chunk_preview를 함께 보여준다.
```

코드 계획:

```text
생성 예정 파일:
etl/fault_cases/src/traffic_precedents/precedent_search/traffic_law/build_rag_report.py

예상 출력 파일:
etl/fault_cases/Fault_cases_MD/에이전트/교통사고_일반판례_RAG_검색_평가_보고서.md
```

예상 결과:

```text
BM25+Nori 검색 결과가 사람이 검수 가능한 MD 보고서로 정리된다.
각 query별로 어떤 판례가 잡혔는지 확인할 수 있다.
```

---

### 11-5. 검색 결과 품질 검수

왜 필요한가:

```text
traffic_precedent는 과실비율 Agent의 주 근거가 아니므로 검색 결과가 과실비율 근거처럼 오해되면 안 된다.
검색된 판례가 주의의무/책임 판단 근거로 적절한지 사람이 확인해야 한다.
```

목적:

```text
BM25+Nori 단독 검색이 V1 RAG/Search로 충분한지 판단한다.
```

진행 방식:

```text
1. query별 top1 판례가 질문과 맞는지 확인한다.
2. top5 안에 유효한 판례가 있는지 확인한다.
3. matched_snippets가 실제 법률 쟁점을 보여주는지 확인한다.
4. 과실비율 산정 근거로 오해될 위험이 있는 결과를 표시한다.
```

코드 계획:

```text
이 단계에서는 필수 코드 추가 없음.
build_rag_report.py가 생성한 보고서를 사람이 검수한다.
```

예상 결과:

```text
BM25+Nori 단독으로 충분한 query와 부족한 query가 구분된다.
부족한 query가 많으면 hint/vector/hybrid 확장을 다음 단계로 검토한다.
```

---

### 11-6. 추후 확장 여부 결정

왜 필요한가:

```text
V1은 BM25+Nori 단독으로 시작하지만, 모든 query에서 충분한 품질이 나온다고 보장할 수는 없다.
결과가 부족하면 추가 검색 전략을 선택해야 한다.
```

목적:

```text
BM25+Nori 단독으로 갈지, hint/vector/hybrid를 추가할지 결정한다.
```

진행 방식:

```text
1. 검색 평가 보고서를 확인한다.
2. top1/top5 품질이 낮은 query 유형을 찾는다.
3. 부족 원인이 용어 차이인지, 의미 검색 부족인지 판단한다.
4. 용어 차이면 hint expansion을 검토한다.
5. 의미 검색 부족이면 pgvector/hybrid를 검토한다.
```

코드 계획:

```text
추후 생성 가능 파일:
etl/fault_cases/src/traffic_precedents/precedent_search/traffic_law/legal_hint_dictionary.py
etl/fault_cases/src/traffic_precedents/precedent_search/traffic_law/search_text_builder.py
etl/fault_cases/src/traffic_precedents/precedent_search/traffic_law/pgvector_retriever.py
etl/fault_cases/src/traffic_precedents/precedent_search/traffic_law/hybrid_retriever.py
```

예상 결과:

```text
BM25+Nori 단독 유지 또는 2차 검색 실험 착수 여부가 결정된다.
```

---

### 11-7. 추후 A/B 후보 JSONL 통합

왜 필요한가:

```text
이 단계는 V1 필수 구현이 아니라 추후 여러 검색 방식을 비교할 때 필요하다.
검색 방식마다 score 이름과 구조가 다르다.
BM25 score, cosine similarity, hybrid score를 그대로 비교하면 안 된다.
공통 후보 포맷으로 정리해야 이후 reranker 평가와 보고서 생성이 가능하다.
```

목적:

```text
BM25, hint, pgvector, hybrid 결과를 같은 JSONL 구조로 변환한다.
```

진행 방식:

```text
1. 각 검색 결과 JSON을 읽는다.
2. query_id, retriever, rank, source_type, chunk_id, retriever_score, score_type을 공통 필드로 맞춘다.
3. chunk_text 또는 chunk_preview를 평가 입력으로 포함한다.
```

코드 계획:

```text
추후 생성 예정 파일:
etl/fault_cases/src/traffic_precedents/precedent_search/traffic_law/export_ab_candidates.py

예상 출력 파일:
etl/fault_cases/artifacts/traffic_precedents_output/traffic_law_rag/traffic_law_ab_candidates.jsonl
```

예상 결과:

```text
여러 검색 방식을 비교할 때 10 queries x 검색방식 수 x top5 개수만큼 후보가 생성된다.
예를 들어 BM25와 hybrid를 비교하면 10 x 2 x 5 = 100개 후보가 생성된다.
```

---

### 11-8. 추후 local reranker 평가

왜 필요한가:

```text
이 단계는 V1 필수 구현이 아니라 추후 여러 검색 방식을 공통 점수로 비교할 때 필요하다.
BM25 score와 vector score는 서로 스케일이 달라 직접 비교할 수 없다.
같은 local reranker로 query와 chunk_text의 관련성을 다시 채점해야 공통 기준 비교가 가능하다.
```

목적:

```text
검색 방식별 후보 품질을 공통 relevance score로 비교한다.
```

진행 방식:

```text
1. traffic_law_ab_candidates.jsonl을 입력으로 받는다.
2. query + chunk_text를 local reranker에 넣는다.
3. local_reranker_score를 후보별로 저장한다.
4. retriever별 avg@5, max@5, top1 score를 계산한다.
```

코드 계획:

```text
추후 생성 예정 파일:
etl/fault_cases/src/traffic_precedents/precedent_search/traffic_law/run_local_reranker.py

예상 출력 파일:
etl/fault_cases/artifacts/traffic_precedents_output/traffic_law_rag/traffic_law_reranker_scores.jsonl
etl/fault_cases/artifacts/traffic_precedents_output/traffic_law_rag/traffic_law_score_summary.json
```

예상 결과:

```text
BM25 baseline, hint, pgvector, hybrid 중 어떤 방식이 교통사고 일반판례 검색에 가장 적합한지 수치로 비교할 수 있다.
```

---

### 11-9. 검색 평가 보고서 확장

왜 필요한가:

```text
V1에서는 BM25 결과 보고서를 만든다.
추후 A/B 확장 시에는 점수 JSON만으로 PM이나 팀원이 검색 방식의 차이를 이해하기 어렵다.
대표 query별 winner, 점수, 판례 preview, matched snippet을 한 문서에서 확인할 수 있어야 한다.
```

목적:

```text
traffic_precedent RAG/Search 방식 선택 근거를 문서화한다.
```

진행 방식:

```text
V1:
  1. BM25 검색 결과를 읽는다.
  2. query별 대표 판례 preview와 matched_snippets를 보여준다.
  3. 사람이 품질을 검수할 수 있게 정리한다.

추후 A/B:
  1. score_summary와 reranker_scores를 읽는다.
  2. retriever별 평균 점수를 표로 만든다.
  3. query별 winner와 대표 판례 preview를 보여준다.
```

코드 계획:

```text
생성 예정 파일:
etl/fault_cases/src/traffic_precedents/precedent_search/traffic_law/build_rag_report.py

예상 출력 파일:
etl/fault_cases/Fault_cases_MD/에이전트/교통사고_일반판례_RAG_검색_평가_보고서.md
```

예상 결과:

```text
V1에서는 "BM25+Nori 단독으로 traffic_precedent 검색이 가능한지" 판단할 수 있다.
추후 A/B 확장 시에는 "hint가 필요한지", "hybrid가 더 나은지" 같은 결론을 근거와 함께 낼 수 있다.
```

---

### 11-10. 이후 연결 여부 결정

왜 필요한가:

```text
traffic_precedent는 현재 Agent가 아니라 RAG/Search 단계까지만 만든다.
검색 평가 결과가 나온 뒤에야 어떤 Agent 또는 Supervisor 흐름에 연결할지 판단할 수 있다.
```

목적:

```text
traffic_precedent를 언제, 어디에, 어떤 형태로 연결할지 결정한다.
```

진행 방식:

```text
1. 검색 평가 보고서를 검토한다.
2. traffic_precedent가 독립 교통사고 법률 Agent에 필요한지 판단한다.
3. text_ml_case_search에는 직접 넣지 않고, 필요한 경우 Supervisor가 별도 보조 근거로 호출하는 구조를 검토한다.
```

코드 계획:

```text
이 단계에서는 즉시 코드 구현하지 않는다.
결정 후 다음 중 하나로 분기한다.

A. 별도 traffic_law_search RAG 모듈 유지
B. 교통사고 법률 Agent 구현
C. Supervisor에서 보조 검색으로 직접 호출
D. text_ml_case_search에는 계속 미연결
```

예상 결과:

```text
traffic_precedent의 역할이 명확해지고, 과실비율 Agent와 교통사고 법률 검색의 책임 경계가 유지된다.
```

---

## 12. 완료 기준

1차 완료 기준:

```text
1. traffic_law query 10개가 정의되어 있다.
2. BM25+Nori baseline 검색 결과가 생성된다.
3. BM25+Nori 검색 결과 보고서가 생성된다.
4. query별 대표 판례 preview와 matched_snippets를 확인할 수 있다.
5. traffic_precedent를 교통사고 일반 법률 RAG/Search source로 사용할 수 있는지 1차 판단할 수 있다.
```

아직 완료 기준이 아닌 것:

```text
1. 별도 Agent 구현
2. Supervisor 실제 연결
3. text_ml_case_search V2 active source 편입
4. traffic_precedent 기반 ratio_range_label 생성
5. 법률용어 hint expansion 구현
6. pgvector / hybrid 검색 비교
7. local reranker 기반 A/B 평가
```

---

## 13. 최종 정리

`traffic_precedent`는 과실비율 Agent의 직접 source가 아니라, **교통사고 일반 법률 RAG/Search source**로 분리한다.

이 계획의 핵심은 다음과 같다.

```text
traffic_precedent는 교통사고 일반판례 검색을 위한 별도 RAG/Search로 준비한다.
V1에서는 현재 프로젝트에 이미 있는 검색 인프라를 기준으로 BM25+Nori 단독 검색부터 구현한다.
법률용어 hint, pgvector, hybrid, local reranker A/B 평가는 BM25+Nori 결과가 부족할 때 추후 확장한다.
```

