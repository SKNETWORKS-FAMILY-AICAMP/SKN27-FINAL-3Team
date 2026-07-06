# text_ml_case_search RAG V2 계획 - 과실비율 판례 통합

작성 기준일: 2026-07-05

---

## 0. 문서 목적

이 문서는 `text_ml_case_search` Agent의 RAG V2 계획을 정리한다.

V1은 `review_case` 심의사례를 BM25+Nori로 검색하고, 그 결과를 `evidence`, `similar_cases`, `display_evidence`, `ratio_range_label`, `insurer_claim_review`로 정리하는 구조였다.

V2는 이 V1 구조를 최대한 유지하면서, 과실비율 관련 판례 source인 `fault_ratio_precedent`를 추가한다.

핵심 원칙:

```text
V1 구조는 유지한다.
BM25+Nori 검색 조건은 최대한 동일하게 유지한다.
source_type만 review_case + fault_ratio_precedent로 확장한다.
심의사례와 판례의 필드 차이는 mapper/display 단계에서만 분기한다.
```

---

## 1. V2 범위 확정

## 1.1 active source

V2 active source는 아래 2개로 확정한다.

```text
review_case
fault_ratio_precedent
```

### review_case

의미:

```text
과실비율 심의사례
```

역할:

```text
1. 실제 사고 유형과 유사한 심의사례를 제공한다.
2. 심의에서 판단된 과실비율과 쟁점을 제공한다.
3. decision_fault_ratio, claimant_final_ratio, respondent_final_ratio를 기반으로 참고 비율을 만든다.
4. Supervisor가 사용자에게 유사 심의사례 근거를 설명할 때 사용한다.
```

### fault_ratio_precedent

의미:

```text
과실비율, 과실상계, 책임 제한, 손해배상 비율 판단과 관련된 판례
```

역할:

```text
1. 법원이 과실 또는 책임 범위를 판단한 문맥을 제공한다.
2. 보험사 주장과 비교할 수 있는 법원 판단 근거를 보강한다.
3. review_case만으로 부족한 법적 판단 배경을 보완한다.
4. Supervisor가 판례상 고려 요소를 설명할 때 사용한다.
```

---

## 1.2 standby / excluded source

이번 V2에서는 아래 source를 active evidence에 넣지 않는다.

```text
standby:
  traffic_precedent

excluded:
  standard / 인정기준
```

### traffic_precedent를 standby로 두는 이유

```text
1. traffic_precedent는 교통사고 일반 법리, 주의의무, 신호위반, 전방주시의무에 강하다.
2. 하지만 이번 V2의 핵심은 과실비율 판단 근거를 보강하는 것이다.
3. traffic_precedent까지 동시에 붙이면 source가 3개가 되어 merge/display/ratio 해석이 복잡해진다.
4. 따라서 V2에서는 standby로 두고, V2.1 또는 V3에서 별도 검토한다.
```

### standard / 인정기준을 제외하는 이유

```text
1. 인정기준은 아직 Agent input 기준과 검색 계획이 완전히 잠기지 않았다.
2. 심의사례/판례와 metadata 구조가 다르다.
3. V2에서 같이 붙이면 output 의미가 흔들릴 수 있다.
4. 인정기준은 V2.5 또는 V3에서 별도 설계한다.
```

---

## 2. V1과 V2의 관계

## 2.1 V1 구조

```text
agent_input
-> validator
-> context_builder
-> normalizer
-> issue_tagger
-> search_text_builder
-> review_case BM25+Nori retriever
-> review_case evidence_mapper
-> evidence_validator
-> display/similar/ratio/insurer builders
-> output_builder
```

## 2.2 V2 구조

V2는 V1 흐름을 바꾸지 않고, RAG 부분만 multi-source로 확장한다.

```text
agent_input
-> validator
-> context_builder
-> normalizer
-> issue_tagger
-> search_text_builder
-> unified_retriever
   -> review_case BM25+Nori retriever
   -> fault_ratio_precedent BM25+Nori retriever
   -> source별 evidence_mapper
   -> evidence_validator
   -> evidence_merger
-> display/similar/ratio/insurer builders
-> output_builder
```

중요:

```text
V2는 새 Agent를 만드는 것이 아니다.
기존 text_ml_case_search Agent의 RAG source를 확장하는 것이다.
```

---

## 3. BM25+Nori 조건 동일성 원칙

사용자가 이미 판례와 심의사례에서 BM25+Nori를 비교했고, V1도 BM25+Nori 기준으로 안정화했다. 따라서 V2에서도 검색 조건의 핵심은 최대한 동일하게 유지한다.

공통 유지 조건:

```text
검색 방식:
  Elasticsearch BM25+Nori

query type:
  multi_match

multi_match type:
  best_fields

operator:
  or

highlight:
  search_text
  chunk_text

검색 입력:
  search_text_builder가 만든 schema_search_text 우선
  없으면 full_optional_context / normalized_description / natural_query_text fallback
```

다만 source별 실제 field 이름은 다를 수 있다.

```text
review_case:
  case_title, header_road_context 같은 심의사례 전용 field가 있음

fault_ratio_precedent:
  case_name, case_number, court_name 같은 판례 전용 field가 있음
```

따라서 “조건 동일”의 의미는 아래와 같다.

```text
동일하게 유지할 것:
  BM25+Nori
  multi_match
  best_fields
  operator=or
  highlight
  search_text/chunk_text 중심 검색
  top_k 정책

source별로 달라질 수 있는 것:
  field 이름
  metadata 구조
  display_evidence에 보여줄 세부 항목
```

---

## 4. 실제 코드 구조 기준

현재 V1 Agent 파일은 아래와 같다.

```text
etl/fault_cases/src/agents/text_ml_case_search/rag/bm25_nori_retriever.py
etl/fault_cases/src/agents/text_ml_case_search/rag/evidence_mapper.py
etl/fault_cases/src/agents/text_ml_case_search/rag/retrieval_pipeline.py
```

이 파일들은 V2에서 이름을 바꾸지 않는다.

```text
bm25_nori_retriever.py:
  review_case 전용 BM25+Nori retriever로 유지

evidence_mapper.py:
  review_case hit -> evidence mapper로 유지

retrieval_pipeline.py:
  review_case 단독 V1 pipeline으로 유지
```

V2에서 새로 추가할 파일:

```text
rag/fault_ratio_precedent_retriever.py
rag/fault_ratio_precedent_evidence_mapper.py
rag/evidence_merger.py
rag/unified_retriever.py
```

이 전략을 쓰는 이유:

```text
1. V1 active 10개 실행 결과가 기존 파일 구조로 이미 검증됐다.
2. V2에서 V1 파일명을 바꾸면 기존 테스트와 실행 경로가 흔들린다.
3. V2의 목적은 review_case를 교체하는 것이 아니라 fault_ratio_precedent를 추가하는 것이다.
```

---

## 5. Elasticsearch index와 field 기준

## 5.1 review_case index

```text
review_case_chunks_bm25_nori_v1
```

V1에서 검증한 field를 유지한다.

```python
REVIEW_CASE_BM25_FIELDS = [
    "search_text^4",
    "chunk_text^2",
    "case_title^2",
    "header_road_context^1.5",
    "search_text_standard",
    "chunk_text_standard",
]
```

---

## 5.2 fault_ratio_precedent index

```text
precedent_fault_ratio_chunks_bm25_nori_v1
```

실제 판례 BM25 indexer를 확인한 결과, Elasticsearch 최상위 field는 아래와 같다.

```text
dataset
case_id
chunk_id
chunk_index
chunk_type
chunk_strategy
case_name
case_number
court_name
decision_date
chunk_text
search_text
chunk_text_standard
search_text_standard
metadata
source_fields
indexed_at
index_version
```

이 중 V2 baseline에서 검색 field로 바로 쓸 수 있는 것은 아래다.

```text
search_text
chunk_text
case_name
search_text_standard
chunk_text_standard
```

따라서 V2 baseline field는 아래처럼 둔다.

```python
FAULT_RATIO_PRECEDENT_BM25_FIELDS = [
    "search_text^4",
    "chunk_text^2",
    "case_name^1.5",
    "search_text_standard",
    "chunk_text_standard",
]
```

---

## 5.3 현재 쓰지 않는 field

아래 field는 V2 baseline에서 직접 검색 field로 쓰지 않는다.

```text
holding_summary
fault_ratio_text
issue_summary
law_reference
case_title
```

이유:

```text
1. 현재 Elasticsearch 최상위 searchable text field로 확정되어 있지 않다.
2. metadata/source_fields는 enabled=false object로 색인되어 내부 값이 BM25 검색 대상이 아니다.
3. 없는 field에 boost를 줘도 기대한 검색 개선이 발생하지 않는다.
```

후속 개선으로 해당 field를 쓰려면 아래 작업이 필요하다.

```text
1. precedent BM25 indexer 수정
2. holding_summary/fault_ratio_text/issue_summary/law_reference를 최상위 text field로 승격
3. Elasticsearch index recreate
4. sample search 재검증
5. Agent V2 field boost 재조정
```

V2 baseline 결론:

```text
기존 판례 BM25 index를 재설계하지 않는다.
search_text/chunk_text/case_name 중심으로 fault_ratio_precedent를 붙인다.
```

---

## 6. Config 설계

파일:

```text
etl/fault_cases/src/agents/text_ml_case_search/config.py
```

V2 추가 설정:

```python
CONTRACT_VERSION = "text_ml_case_search_v2"

BM25_TOP_K_PER_SOURCE = int(os.getenv("TEXT_ML_CASE_SEARCH_BM25_TOP_K_PER_SOURCE", "5"))
BM25_FINAL_TOP_K = int(os.getenv("TEXT_ML_CASE_SEARCH_BM25_FINAL_TOP_K", "8"))

FAULT_RATIO_PRECEDENT_INDEX = os.getenv(
    "FAULT_RATIO_PRECEDENT_ES_BM25_INDEX",
    "precedent_fault_ratio_chunks_bm25_nori_v1",
)

ENABLE_REVIEW_CASE_RETRIEVER = True
ENABLE_FAULT_RATIO_PRECEDENT_RETRIEVER = True
ENABLE_TRAFFIC_PRECEDENT_RETRIEVER = False
ENABLE_STANDARD_RETRIEVER = False

FAULT_RATIO_PRECEDENT_BM25_FIELDS = [
    "search_text^4",
    "chunk_text^2",
    "case_name^1.5",
    "search_text_standard",
    "chunk_text_standard",
]
```

예상 효과:

```text
1. V2 active/standby/excluded source가 코드에서 명확해진다.
2. fault_ratio_precedent index 이름을 .env로 override할 수 있다.
3. source별 top_k와 최종 top_k를 조정할 수 있다.
```

---

## 7. fault_ratio_precedent retriever 설계

파일:

```text
rag/fault_ratio_precedent_retriever.py
```

역할:

```text
1. fault_ratio_precedent index를 대상으로 BM25+Nori 검색을 수행한다.
2. V1과 동일한 검색 철학을 유지한다.
3. source별 field 차이만 반영한다.
```

예상 query:

```python
def build_fault_ratio_precedent_bm25_query(*, search_text: str, top_k: int) -> dict:
    return {
        "query": {
            "multi_match": {
                "query": search_text,
                "fields": FAULT_RATIO_PRECEDENT_BM25_FIELDS,
                "type": "best_fields",
                "operator": "or",
            }
        },
        "size": top_k,
        "highlight": {
            "fields": {
                "search_text": {"fragment_size": 180, "number_of_fragments": 2},
                "chunk_text": {"fragment_size": 180, "number_of_fragments": 2},
            }
        },
    }
```

---

## 8. fault_ratio_precedent evidence mapper 설계

파일:

```text
rag/fault_ratio_precedent_evidence_mapper.py
```

역할:

```text
Elasticsearch hit을 Agent 공통 evidence schema로 변환한다.
```

예상 evidence:

```json
{
  "source_type": "fault_ratio_precedent",
  "title": "case_name",
  "source_reference": "precedent_fault_ratio_db:{case_id}#{chunk_id}",
  "metadata": {
    "case_id": "...",
    "case_number": "...",
    "court_name": "...",
    "decision_date": "...",
    "case_name": "...",
    "chunk_id": "...",
    "chunk_type": "...",
    "score": 123.4,
    "score_type": "bm25_score",
    "retriever": "bm25_nori",
    "index": "precedent_fault_ratio_chunks_bm25_nori_v1",
    "rank": 1,
    "highlight": {},
    "matched_facts": [],
    "different_facts": []
  },
  "chunk_text": "...",
  "search_text": "...",
  "confidence": null
}
```

---

## 9. source_reference 규칙

기존 V1:

```text
review_case_db:{review_case_id or review_no}#{chunk_id}
```

V2 추가:

```text
precedent_fault_ratio_db:{case_id or case_number}#{chunk_id}
```

구현 위치:

```text
rag/source_reference.py
```

---

## 10. evidence merge 설계

파일:

```text
rag/evidence_merger.py
```

필요한 이유:

```text
review_case와 fault_ratio_precedent는 서로 다른 Elasticsearch index다.
서로 다른 index의 BM25 score는 문서 길이, corpus 크기, field 구성에 따라 scale이 달라 직접 비교하면 안 된다.
```

기본 merge 전략:

```text
review_case 최대 5개
fault_ratio_precedent 최대 5개
final_top_k = 10
source_reference 기준 중복 제거
```

5+5로 잡는 이유:

```text
1. V2의 목적은 심의사례와 과실비율 판례를 함께 보여주는 것이다.
   한쪽 source가 결과를 독점하면 V2를 만든 의미가 약해진다.

2. review_case는 실제 과실비율 심의사례 근거에 강하다.
   fault_ratio_precedent는 법원 판단, 과실상계, 책임 제한 근거에 강하다.
   두 source의 역할이 다르므로 초기 V2에서는 같은 후보 수를 보장한다.

3. 4+4는 가볍지만 판례와 심의사례의 다양성을 보기에는 조금 좁을 수 있다.
   5+5는 Supervisor가 source별 후보를 비교하기에 충분한 폭을 주면서도,
   전체 10개로 제한되어 후처리 부담이 과도하게 커지지 않는다.

4. BM25 raw score는 source 간 직접 비교하지 않기 때문에
   공정한 초기 비교를 위해 source별 동일 quota를 둔다.

5. V2 active 10개 실행 결과를 본 뒤 6+4, 4+6, 3+3 등으로 조정할 수 있다.
   따라서 5+5는 운영 최종값이 아니라 V2 초기 기준값이다.
```

예상 효과:

```text
1. review_case가 evidence를 독점하지 않는다.
2. fault_ratio_precedent도 Supervisor가 볼 수 있는 근거로 남는다.
3. source별 후보가 5개씩 남아 display_evidence와 similar_cases 구성의 폭이 넓어진다.
4. V2.1에서 reranker를 붙이면 그때 cross-source 재정렬을 할 수 있다.
```

---

## 11. unified_retriever 설계

파일:

```text
rag/unified_retriever.py
```

역할:

```text
1. review_case V1 pipeline을 호출한다.
2. fault_ratio_precedent retriever/mapper/validator를 호출한다.
3. source별 evidence를 모은다.
4. evidence_merger로 최종 evidence를 만든다.
5. source_counts와 source_summary 생성 재료를 반환한다.
```

예상 반환:

```json
{
  "retriever": "unified_bm25_nori",
  "active_sources": ["review_case", "fault_ratio_precedent"],
  "standby_sources": ["traffic_precedent"],
  "excluded_sources": ["standard"],
  "source_counts": {
    "review_case": 5,
    "fault_ratio_precedent": 5
  },
  "evidence_by_source": {},
  "evidence": [],
  "raw_debug": {}
}
```

---

## 12. source_summary 설계

V2 output에는 `structured_result.source_summary`를 추가한다.

예상 구조:

```json
{
  "source_summary": {
    "active_sources": ["review_case", "fault_ratio_precedent"],
    "standby_sources": ["traffic_precedent"],
    "excluded_sources": ["standard"],
    "source_counts": {
      "review_case": 5,
      "fault_ratio_precedent": 5
    },
    "final_top_k": 10,
    "merge_strategy": "source_quota"
  }
}
```

구현 위치:

```text
schemas.py:
  StructuredResult에 source_summary 추가

builders/output_builder.py:
  build_output 인자에 source_summary: dict | None = None 추가
  structured_result["source_summary"] = source_summary or {}

rag/unified_retriever.py:
  source_counts 생성

agent.py:
  rag_result에서 source_summary 조립
```

---

## 13. builder 확장 계획

```text
evidence_display_builder.py:
  source_type별 표시 필드 분기

similar_case_builder.py:
  source_type별 summary 분기

ratio_range_builder.py:
  V2 초기에는 review_case ratio 우선
  fault_ratio_precedent의 숫자 표현은 보조 근거로 유지

insurer_claim_review_builder.py:
  review_case와 fault_ratio_precedent의 역할 차이를 comparison_summary에 반영
```

---

## 14. V2 예상 결과

```text
contract_version:
  text_ml_case_search_v2

evidence:
  review_case + fault_ratio_precedent 혼합

display_evidence:
  source_type별 표시 방식 분기

similar_cases:
  source_type별 metadata를 반영해 요약

ratio_range_label:
  V2 초기에는 review_case 기반 비율 우선
  fault_ratio_precedent의 과실상계/책임제한 표현은 보조 근거로 사용

source_summary:
  active/standby/excluded source와 source_counts 표시
```

---

## 15. 완료 기준

```text
1. V1 review_case 테스트가 깨지지 않는다.
2. fault_ratio_precedent retriever가 BM25 query를 정상 생성한다.
3. fault_ratio_precedent hit이 공통 evidence schema로 변환된다.
4. evidence_merger가 source quota를 적용한다.
5. output에 source_summary가 포함된다.
6. traffic_precedent와 standard는 active evidence에 들어가지 않는다.
7. active 10개 입력 실행 시 Agent JSON이 깨지지 않는다.
```

