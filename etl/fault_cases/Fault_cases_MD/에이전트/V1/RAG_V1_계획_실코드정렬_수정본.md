# `text_ml_case_search` RAG V1 계획 - 실제 코드베이스 정렬 수정본

생성일시: 2026-07-04T12:33:24

## 0. 문서 목적

이 문서는 `text_ml_case_search` Agent 내부에서 사용할 RAG V1을 실제 코드베이스 기준으로 정리한 계획서다.

핵심은 다음이다.

```text
우리 Agent는 최종 사용자 답변을 만들지 않는다.
우리 Agent는 Supervisor가 보낸 agent_input을 받아 BM25+Nori 기반으로 유사 근거를 찾고,
evidence / similar_cases / ratio_range_label / insurer_claim_review의 재료로 구조화한다.
```

담당 범위는 아래 5단계까지다.

```text
1. Supervisor가 사용자 입력을 보고 text_ml_case_search를 호출한다.
2. Supervisor는 우리가 정한 agent_input schema를 우리에게 보낸다.
3. 우리는 BM25+Nori 기반 RAG로 유사 근거를 찾는다.
4. 우리는 최종 답변을 만들지 않고 evidence / similar_cases / ratio_range_label / insurer_claim_review를 만든다.
5. 그 output을 Supervisor에게 돌려준다.
```

---

## 1. 현재 코드베이스 전제

현재 실제 `etl/fault_cases/src/` 아래에는 다음 source 계층만 존재한다.

```text
etl/fault_cases/src/
  fault_standard/
  review_case/
  traffic_precedents/
```

따라서 아래 구조는 기존 구조가 아니라 신규 생성할 구조다.

```text
etl/fault_cases/src/agents/text_ml_case_search/
```

`text_ml_case_search`는 심의사례 전용 코드가 아니다. 향후 판례, 인정기준, OCR, Vision, 보험사 주장까지 묶어 Supervisor에게 구조화 결과를 반환하는 업무 Agent다. 그래서 `review_case` 아래가 아니라 `agents` 아래에 둔다.

---

## 2. V1 RAG 범위

V1은 review_case BM25+Nori 기반 RAG부터 안정화한다.

```text
V1:
  review_case BM25+Nori 기반 evidence 구조화

V1.1:
  review_case BM25 후보 + local reranker

V2:
  review_case + traffic_precedent + fault_ratio_precedent 통합 검색
```

중요한 점은 이것이다.

```text
Input schema는 여전히 하나다.
source_scope 같은 입력 필드는 만들지 않는다.
V1에서 내부 연결 검색기가 review_case부터라는 뜻이지, 사용자 input을 심의사례 전용으로 나눈다는 뜻이 아니다.
```

V1 출력의 `evidence[].source_type`은 우선 `review_case`가 중심이 된다. 판례는 output schema에서 수용 가능하지만 실제 precedent retriever/mapper 연결은 V1.5 또는 V2에서 추가한다.

---

## 3. BM25+Nori 선택 근거

심의사례 스키마 검색 테스트 결과를 기준으로 V1 검색 방식은 BM25+Nori로 정한다.

```text
실험 조건:
  active_test_case_count: 10
  input_variant_count: 2
  retriever_count: 3

입력 variant:
  query_text
  full_optional_context

검색기:
  pgvector_cosine
  BM25+Nori
  Elasticsearch hybrid

공통 비교:
  models/bge-reranker-v2-m3
```

결정 이유는 다음과 같다.

```text
1. full_optional_context에서는 세 방식 차이가 크지 않았다.
2. query_text 단독에서는 BM25+Nori가 가장 안정적이었다.
3. BM25+Nori는 embedding 호출 없이 동작하므로 운영 부담이 작다.
4. 한국어 사고 표현은 명사구와 행위 키워드가 중요하므로 Nori analyzer가 적합하다.
5. V1 목표는 완벽한 생성형 답변이 아니라 안정적인 evidence 구조화다.
```

---

## 4. 기존 BM25 검색 코드와의 관계

현재 심의사례 BM25 검색 실험 코드는 아래에 있다.

```text
etl/fault_cases/src/review_case/search/elasticsearch/bm25_retriever.py
```

이 코드는 실험/검증용으로 유지한다. 하지만 Agent V1에서는 검증된 검색 정책을 `agents` 폴더로 이관해 Agent RAG 정본으로 사용한다.

```text
V1 구현 결정:
  기존 review_case BM25+Nori 검색 정책을
  agents/text_ml_case_search/rag/bm25_nori_retriever.py로 이관한다.

review_case/search 모듈:
  실험/검증 산출물 재현용으로 유지한다.

agents/text_ml_case_search/rag/bm25_nori_retriever.py:
  실제 Agent 실행 시 사용하는 운영 정본 retriever로 둔다.

향후 검색 정책 변경:
  agents/text_ml_case_search/rag/bm25_nori_retriever.py에서 관리한다.
```

복사 자체가 문제가 아니라, 복사 후 어느 쪽이 정본인지 애매한 것이 문제다. V1에서는 Agent 쪽 retriever를 운영 정본으로 명확히 정한다.

---

## 5. 실제 V1 index와 검색 field

### 5.1 V1 review_case index

```text
review_case_chunks_bm25_nori_v1
```

이 값은 Supervisor input schema가 아니라 서버 내부 설정이다.

여기서 말하는 `index`는 PostgreSQL 테이블이 아니라 Elasticsearch 검색용 색인이다.

```text
PostgreSQL:
  review_case_documents
  review_case_chunks
  review_case_chunk_embeddings
  → 원본/정본 데이터 저장

Elasticsearch:
  review_case_chunks_bm25_nori_v1
  → BM25+Nori 검색을 빠르게 하기 위한 검색 색인
```

따라서 Agent가 BM25+Nori 검색을 하려면 어느 Elasticsearch index를 검색할지 알아야 한다.
이 값을 코드에 고정 문자열로만 두면 index 버전이 바뀔 때마다 코드를 수정해야 하므로, V1 구현에서는 기본값은 유지하되 `.env`로 덮어쓸 수 있게 한다.

```python
REVIEW_CASE_INDEX = os.getenv(
    "REVIEW_CASE_ES_BM25_INDEX",
    "review_case_chunks_bm25_nori_v1",
)
```

예상 결과:

```text
1. 기본 실행 시에는 review_case_chunks_bm25_nori_v1을 사용한다.
2. 나중에 review_case_chunks_bm25_nori_v2를 만들면 .env만 바꿔 전환할 수 있다.
3. Supervisor input에는 검색 대상 선택 필드를 추가하지 않아도 된다.
```

### 5.2 V2 후보 index

```text
precedent_traffic_chunks_bm25_nori_v1
precedent_fault_ratio_chunks_bm25_nori_v1
```

판례 index는 V1에서 바로 연결하지 않고 V2 후보로 둔다.

판례도 V2에서 연결할 때는 같은 원칙을 따른다.

```python
TRAFFIC_PRECEDENT_INDEX = os.getenv(
    "TRAFFIC_PRECEDENT_ES_BM25_INDEX",
    "precedent_traffic_chunks_bm25_nori_v1",
)

FAULT_RATIO_PRECEDENT_INDEX = os.getenv(
    "FAULT_RATIO_PRECEDENT_ES_BM25_INDEX",
    "precedent_fault_ratio_chunks_bm25_nori_v1",
)
```

다만 V1에서는 `ENABLE_PRECEDENT_RETRIEVER = False`로 두고, review_case 검색 안정화 이후 판례 adapter를 붙인다.

### 5.3 V1 BM25 검색 field boost

V1 Agent retriever는 기존 심의사례 BM25 실험에서 사용한 field boost를 그대로 이관한다.

```python
BM25_SEARCH_FIELDS = [
    "search_text^4",
    "chunk_text^2",
    "case_title^2",
    "header_road_context^1.5",
    "search_text_standard",
    "chunk_text_standard",
]
```

| 필드 | 의미 | V1 사용 이유 |
| --- | --- | --- |
| `search_text^4` | 전처리 단계에서 만든 검색용 통합 텍스트 | 가장 중요한 검색 필드 |
| `chunk_text^2` | 실제 chunk 본문 | 근거 원문 매칭 |
| `case_title^2` | 사례 제목 | 사고 유형 힌트 |
| `header_road_context^1.5` | 도로/사고 맥락 | 장소/도로 조건 보강 |
| `search_text_standard` | standard analyzer 보조 검색 필드 | Nori 외 보조 매칭 |
| `chunk_text_standard` | standard analyzer 본문 보조 필드 | 본문 보조 매칭 |

초안에 있던 아래 필드는 이상적인 통합 RAG 예시였고, V1 기준에서 사용하지 않는다.

```text
chunk_text^3
case_title^2
accident_type^2
issue_tags^1
```

### 5.4 `operator="or"`와 highlight 이관 이유

기존 심의사례 BM25 실험 코드에는 `operator="or"`와 `highlight` 설정이 들어 있다.
Agent 쪽 retriever를 운영 정본으로 만들더라도, V1에서 실험 조건을 그대로 이관하려면 이 설정도 함께 가져와야 한다.

#### `operator="or"` 의미

사용자가 아래처럼 긴 검색문을 보낼 수 있다.

```text
신호등 없는 교차로에서 직진 차량과 우측 진입 차량이 충돌한 사고
```

Elasticsearch는 이 문장을 여러 토큰으로 나누어 검색한다.

```text
신호등 / 없는 / 교차로 / 직진 / 차량 / 우측 / 진입 / 충돌 / 사고
```

`operator`는 이 토큰들을 어떤 조건으로 매칭할지 정한다.

```text
operator="or":
  토큰 중 일부가 맞아도 후보로 가져온다.

operator="and":
  모든 토큰이 맞아야 후보로 가져온다.
```

교통사고 검색은 사용자 표현이 길고 다양하다. `and`를 쓰면 후보가 과하게 줄어들 수 있으므로 V1에서는 기존 실험과 동일하게 `or`를 사용한다.

예상 결과:

```text
1. query_text가 짧아도 후보가 나온다.
2. full_optional_context처럼 긴 검색문에서도 검색 결과가 과하게 사라지지 않는다.
3. 다만 관련성이 약한 후보도 일부 들어올 수 있으므로 evidence_validator와 이후 reranker로 보정한다.
```

#### highlight 의미

`highlight`는 검색 결과에서 어떤 부분이 검색어와 맞았는지 확인하기 위한 Elasticsearch 기능이다.

예시:

```json
{
  "highlight": {
    "chunk_text": [
      "피청구 차량은 <em>중앙선</em>을 <em>침범</em>하여 <em>역주행</em>하였고..."
    ]
  }
}
```

V1에서 highlight는 사용자 최종 답변에 그대로 노출하지 않는다. 대신 아래 목적에 사용한다.

```text
1. 검색 결과가 왜 선택됐는지 디버깅
2. evidence 품질 점검
3. 추후 matched_facts 또는 근거 문장 추출 보조
```

예상 결과:

```text
Agent output metadata에는 highlight를 내부 참고값으로 보관할 수 있다.
Supervisor 최종 답변에는 원문 그대로 노출하지 않는다.
```

---

## 6. Config 설계

파일 위치:

```text
etl/fault_cases/src/agents/text_ml_case_search/config.py
```

초안:

```python
import os

BM25_TOP_K = 5
BM25_CANDIDATE_K = 10

REVIEW_CASE_INDEX = os.getenv(
    "REVIEW_CASE_ES_BM25_INDEX",
    "review_case_chunks_bm25_nori_v1",
)

EVIDENCE_INDEX_NAMES = [
    REVIEW_CASE_INDEX,
]

BM25_SEARCH_FIELDS = [
    "search_text^4",
    "chunk_text^2",
    "case_title^2",
    "header_road_context^1.5",
    "search_text_standard",
    "chunk_text_standard",
]

MIN_CHUNK_TEXT_LEN = 50

ENABLE_PRECEDENT_RETRIEVER = False
ENABLE_METADATA_CONTEXT_ENRICHER = False
ENABLE_RERANKER = False
```

이 config의 목적은 검색 정책을 Supervisor input과 분리하는 것이다.

```text
Supervisor:
  사고 설명과 보조 증거를 보낸다.

Agent config:
  어떤 index를 검색할지, top_k를 몇 개로 할지, reranker를 켤지 정한다.
```

이렇게 분리해야 사용자 입력에 `source_scope` 같은 검색 제어 필드를 넣지 않아도 되고, 운영자가 index 버전이나 검색 정책을 서버 내부에서 바꿀 수 있다.

---

## 7. full_optional_context 검색문 생성

검색문은 `query_text`를 중심으로 만들고, 선택 입력이 있으면 보강한다.

```text
[사고 설명]
query_text

[사용자 원문]
raw_user_text

[Vision 요약]
vision_evidence[].description
vision_evidence[].observations

[OCR 요약]
ocr_evidence.accident_datetime
ocr_evidence.accident_location
ocr_evidence.accident_type
ocr_evidence.accident_cause
ocr_evidence.accident_description
ocr_evidence.extracted_fields

[보험사 주장]
insurer_claim.claimed_ratio
insurer_claim.reason_text
insurer_claim.source_text
```

구현 위치:

```text
etl/fault_cases/src/agents/text_ml_case_search/rag/search_text_builder.py
```

구현 초안:

```python
from typing import Any


def build_full_optional_context(agent_input: dict[str, Any]) -> str:
    parts: list[str] = []

    query_text = (agent_input.get("query_text") or "").strip()
    raw_user_text = (agent_input.get("raw_user_text") or "").strip()

    if query_text:
        parts.append(f"[사고 설명]\n{query_text}")

    if raw_user_text and raw_user_text != query_text:
        parts.append(f"[사용자 원문]\n{raw_user_text}")

    for idx, item in enumerate(agent_input.get("vision_evidence") or [], start=1):
        description = (item.get("description") or "").strip()
        observations = item.get("observations") or []
        lines: list[str] = []

        if description:
            lines.append(description)
        for obs in observations:
            obs = str(obs).strip()
            if obs:
                lines.append(f"- {obs}")

        if lines:
            parts.append(f"[Vision 요약 {idx}]\n" + "\n".join(lines))

    ocr = agent_input.get("ocr_evidence")
    if isinstance(ocr, dict):
        lines: list[str] = []
        for key in [
            "accident_datetime",
            "accident_location",
            "accident_type",
            "accident_cause",
            "accident_description",
        ]:
            value = ocr.get(key)
            if value:
                lines.append(f"{key}: {value}")

        extracted_fields = ocr.get("extracted_fields")
        if isinstance(extracted_fields, dict):
            for key, value in extracted_fields.items():
                if value:
                    lines.append(f"{key}: {value}")

        if lines:
            parts.append("[OCR 요약]\n" + "\n".join(lines))

    claim = agent_input.get("insurer_claim")
    if isinstance(claim, dict):
        lines: list[str] = []
        for key in ["claimed_ratio", "reason_text", "source_text"]:
            value = claim.get(key)
            if value:
                lines.append(f"{key}: {value}")
        if lines:
            parts.append("[보험사 주장]\n" + "\n".join(lines))

    return "\n\n".join(parts).strip()
```

---

## 8. BM25+Nori retriever 구현

파일 위치:

```text
etl/fault_cases/src/agents/text_ml_case_search/rag/bm25_nori_retriever.py
```

구현 초안:

```python
from typing import Any
from elasticsearch import Elasticsearch

from ..config import BM25_SEARCH_FIELDS


def build_bm25_query(search_text: str, top_k: int) -> dict[str, Any]:
    return {
        "query": {
            "multi_match": {
                "query": search_text,
                "fields": BM25_SEARCH_FIELDS,
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


def search_bm25_nori(
    es: Elasticsearch,
    index_names: list[str],
    search_text: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    if not search_text.strip():
        return []

    body = build_bm25_query(search_text=search_text, top_k=top_k)
    response = es.search(index=",".join(index_names), body=body)

    hits: list[dict[str, Any]] = []
    for hit in response.get("hits", {}).get("hits", []):
        hits.append(
            {
                "retriever": "bm25_nori",
                "retriever_score": hit.get("_score"),
                "index": hit.get("_index"),
                "source": hit.get("_source", {}) or {},
                "highlight": hit.get("highlight") or {},
            }
        )

    return hits
```

ES 내부 score는 사용자에게 직접 노출하지 않는다. Agent output에서는 metadata 내부 참고값으로만 사용한다.

---

## 9. 실제 review_case hit 기준 evidence mapper

현재 심의사례 BM25 hit의 중심 필드는 다음이다.

```text
review_case_id
review_no
chunk_id
chunk_type
case_title
reference_chart_key
decision_fault_ratio
claimant_final_ratio
respondent_final_ratio
signal_condition
road_feature
standard_a_behavior
standard_b_behavior
chunk_text
search_text
```

따라서 V1 mapper는 `accident_type`, `issue_tags`가 hit에 있다고 가정하지 않는다.

구현 위치:

```text
etl/fault_cases/src/agents/text_ml_case_search/rag/evidence_mapper.py
```

구현 초안:

```python
from typing import Any


def map_review_case_hit_to_evidence(hit: dict[str, Any]) -> dict[str, Any]:
    row = hit.get("source", {}) or {}

    review_case_id = row.get("review_case_id")
    review_no = row.get("review_no")
    chunk_id = row.get("chunk_id")

    source_reference = build_review_case_source_reference(
        review_case_id=review_case_id,
        review_no=review_no,
        chunk_id=chunk_id,
    )

    return {
        "source_type": "review_case",
        "title": row.get("case_title") or "",
        "source_reference": source_reference,
        "metadata": {
            "review_case_id": review_case_id,
            "review_no": review_no,
            "chunk_id": chunk_id,
            "chunk_type": row.get("chunk_type"),
            "reference_chart_key": row.get("reference_chart_key"),
            "decision_fault_ratio": row.get("decision_fault_ratio"),
            "claimant_final_ratio": row.get("claimant_final_ratio"),
            "respondent_final_ratio": row.get("respondent_final_ratio"),
            "standard_context": {
                "signal_condition": row.get("signal_condition"),
                "road_feature": row.get("road_feature"),
                "standard_a_behavior": row.get("standard_a_behavior"),
                "standard_b_behavior": row.get("standard_b_behavior"),
            },
            "similarity_score": hit.get("retriever_score"),
            "score_type": "bm25_score",
            "retriever": hit.get("retriever"),
            "index": hit.get("index"),
            "matched_facts": [],
            "different_facts": [],
        },
        "chunk_text": row.get("chunk_text") or "",
        "confidence": None,
    }


def build_review_case_source_reference(
    *,
    review_case_id: str | None,
    review_no: str | None,
    chunk_id: str | None,
) -> str:
    case_key = review_case_id or review_no or "unknown_review_case"
    chunk_key = chunk_id or "unknown_chunk"
    return f"review_case_db:{case_key}#{chunk_key}"
```

---

## 9-1. Evidence Display Formatter: 사용자/Supervisor 표시용 근거 정리

### 목적

`evidence_mapper.py`가 만든 `evidence`는 RAG 원천 근거에 가깝다.
여기에는 긴 `chunk_text`, Elasticsearch `highlight`, 내부 score, index명, chunk metadata가 함께 들어갈 수 있다.

하지만 Supervisor나 UI가 바로 보기에는 다음 문제가 있다.

```text
1. chunk_text가 길어서 사용자 화면에 그대로 노출하기 어렵다.
2. highlight에는 <em>...</em> 같은 Elasticsearch 표시 태그가 들어간다.
3. BM25 score는 검색 내부 점수라 사용자에게 직접 보여주면 오해가 생긴다.
4. evidence는 원천 근거 보존용이고, 화면 표시용 요약은 별도로 필요하다.
```

따라서 V1에서는 원본 `evidence`는 유지하되,
사용자/Supervisor가 읽기 쉬운 별도 표시 구조를 만든다.

### 구현 위치

```text
etl/fault_cases/src/agents/text_ml_case_search/builders/evidence_display_builder.py
```

### 입력

```text
evidence[]
```

### 출력

`structured_result.display_evidence[]`를 추가한다.

예상 구조는 다음과 같다.

```json
{
  "source_type": "review_case",
  "title": "신호 없는 교차로 사고 심의사례",
  "source_reference": "review_case_db:123#chunk-1",
  "reference_chart_key": "249",
  "ratio_label": "청구인 70 : 피청구인 30",
  "summary": "신호 없는 교차로에서 직진 차량과 우측 진입 차량의 진입 순서, 충돌 위치, 주의의무를 중심으로 판단한 사례입니다.",
  "matched_snippets": [
    "신호 없는 교차로",
    "우측 진입 차량"
  ],
  "display_warnings": []
}
```

### evidence와 display_evidence의 차이

| 필드 | 역할 | 사용자 노출 |
| --- | --- | --- |
| `evidence` | RAG 원천 근거, metadata, chunk_text 보존 | 원칙적으로 내부/Supervisor용 |
| `display_evidence` | 화면 표시와 최종 답변 생성을 돕는 정리된 근거 | 노출 가능 |

`display_evidence`는 `evidence`를 대체하지 않는다.
검색 디버깅, source 추적, 후속 검증에는 여전히 원본 `evidence`가 필요하다.

### 처리 규칙

```text
1. highlight의 <em> 태그는 제거하거나 matched_snippets로만 분리한다.
2. chunk_text는 preview/summary 길이로 줄인다.
3. source_reference는 반드시 유지한다.
4. decision_fault_ratio, claimant_final_ratio, respondent_final_ratio가 있으면 ratio_label로 정리한다.
5. BM25 score, index명, raw highlight는 사용자 표시용 필드에 직접 노출하지 않는다.
6. 원문 인코딩이 깨진 것으로 보이면 display_warnings에 text_encoding_review_required를 남긴다.
```

### 왜 9-1 단계로 분리하는가

`similar_cases`는 유사 사례 목록이고, `evidence`는 원천 근거다.
반면 `display_evidence`는 Supervisor가 최종 사용자 답변을 만들 때 바로 참고할 수 있는 표시용 근거다.

이 단계를 분리하면 다음 장점이 있다.

```text
1. RAG 원본 근거를 훼손하지 않는다.
2. 사용자 화면용 문구와 검색 디버깅용 metadata를 분리할 수 있다.
3. highlight 태그나 내부 score가 최종 응답에 섞이는 것을 막는다.
4. 나중에 판례/인정기준 source가 추가되어도 source별 display formatter만 확장하면 된다.
```

### 예상 결과

9-1 구현 후 Agent output은 아래처럼 확장된다.

```text
structured_result.evidence          기존 원천 근거 유지
structured_result.similar_cases     유사 사례 목록 유지
structured_result.display_evidence  표시용 근거 요약 추가
```

Supervisor는 최종 답변 생성 시 `display_evidence`를 우선 참고하고,
출처 검증이나 상세 근거가 필요할 때 `evidence`를 확인한다.

---

## 10. Ratio Range Builder: metadata 우선, regex fallback

심의사례에는 이미 구조화된 비율 필드가 있다.

```text
decision_fault_ratio
claimant_final_ratio
respondent_final_ratio
```

따라서 순서는 아래와 같다.

```text
1. evidence.metadata.decision_fault_ratio 확인
2. claimant_final_ratio / respondent_final_ratio 확인
3. 없을 때만 chunk_text regex fallback
```

구현 위치:

```text
etl/fault_cases/src/agents/text_ml_case_search/builders/ratio_range_builder.py
```

구현 초안:

```python
import re

RATIO_PATTERNS = [
    re.compile(r"(\d{1,3})\s*[:대]\s*(\d{1,3})"),
    re.compile(r"과실비율\s*(\d{1,3})\s*%"),
    re.compile(r"과실상계\s*(\d{1,3})\s*%"),
    re.compile(r"책임\s*(\d{1,3})\s*%"),
]


def build_ratio_range_label(evidence: list[dict]) -> str:
    metadata_ratios = collect_metadata_ratios(evidence)
    if metadata_ratios:
        return (
            "유사 심의사례에서 "
            + ", ".join(metadata_ratios[:3])
            + " 비율 정보가 확인됩니다. "
            + "다만 이는 확정 과실비율이 아니라 참고 근거입니다."
        )

    regex_ratios = collect_regex_ratios(evidence)
    if regex_ratios:
        return (
            "유사 근거 본문에서 "
            + ", ".join(regex_ratios[:3])
            + " 등의 과실 관련 표현이 확인됩니다. "
            + "다만 이는 확정 과실비율이 아니라 참고 근거입니다."
        )

    return ""


def collect_metadata_ratios(evidence: list[dict]) -> list[str]:
    ratios: list[str] = []
    for item in evidence:
        metadata = item.get("metadata") or {}
        decision = metadata.get("decision_fault_ratio")
        if decision:
            ratios.append(str(decision))

        claimant = metadata.get("claimant_final_ratio")
        respondent = metadata.get("respondent_final_ratio")
        if claimant is not None and respondent is not None:
            ratios.append(f"청구인 {claimant} : 피청구인 {respondent}")

    return list(dict.fromkeys(ratios))


def collect_regex_ratios(evidence: list[dict]) -> list[str]:
    ratios: list[str] = []
    for item in evidence:
        text = item.get("chunk_text") or ""
        for pattern in RATIO_PATTERNS:
            for match in pattern.finditer(text):
                ratios.append(match.group(0))
    return list(dict.fromkeys(ratios))
```

중요 제한:

```text
ratio_range_builder는 과실비율을 계산하지 않는다.
문서에 이미 존재하는 비율 정보를 참고 라벨로 정리할 뿐이다.
```

---

## 11. Metadata Context Enricher

파일 위치:

```text
etl/fault_cases/src/agents/text_ml_case_search/rag/metadata_context_enricher.py
```

V1에서는 기본 비활성화한다.

```python
ENABLE_METADATA_CONTEXT_ENRICHER = False
```

활성화 조건은 다음과 같다.

```text
1. 검색 결과 상위에 case_overview 같은 metadata성 chunk가 반복적으로 뜬다.
2. decision 또는 evidence_issue chunk 보강이 필요하다.
3. ratio_range_label을 만들 근거가 부족하다.
4. similar_cases 요약에 본문성이 부족하다.
```

---

## 12. RAG Pipeline

구현 위치:

```text
etl/fault_cases/src/agents/text_ml_case_search/rag/retrieval_pipeline.py
```

흐름:

```text
full_optional_context 생성
→ review_case BM25+Nori 검색
→ review_case hit evidence 변환
→ evidence validation
→ 필요 시 metadata_context_enricher
```

구현 초안:

```python
from elasticsearch import Elasticsearch

from ..config import (
    EVIDENCE_INDEX_NAMES,
    BM25_TOP_K,
    ENABLE_METADATA_CONTEXT_ENRICHER,
    MIN_CHUNK_TEXT_LEN,
)
from .search_text_builder import build_full_optional_context
from .bm25_nori_retriever import search_bm25_nori
from .evidence_mapper import map_review_case_hit_to_evidence
from .evidence_validator import validate_evidence
from .metadata_context_enricher import enrich_with_neighbor_chunks


def run_rag_pipeline(
    *,
    es: Elasticsearch,
    agent_input: dict,
    issue_tags: list[str],
) -> dict:
    search_text = build_full_optional_context(agent_input)

    raw_hits = search_bm25_nori(
        es=es,
        index_names=EVIDENCE_INDEX_NAMES,
        search_text=search_text,
        top_k=BM25_TOP_K,
    )

    evidence = [map_review_case_hit_to_evidence(hit) for hit in raw_hits]

    valid_evidence = validate_evidence(
        evidence=evidence,
        issue_tags=issue_tags,
        min_text_len=MIN_CHUNK_TEXT_LEN,
    )

    if ENABLE_METADATA_CONTEXT_ENRICHER:
        valid_evidence = enrich_with_neighbor_chunks(
            es=es,
            evidence=valid_evidence,
            index_names=EVIDENCE_INDEX_NAMES,
        )

    return {
        "search_text": search_text,
        "raw_hit_count": len(raw_hits),
        "valid_evidence_count": len(valid_evidence),
        "evidence": valid_evidence,
    }
```

---

## 13. RAG 폴더 구조

```text
etl/fault_cases/src/agents/text_ml_case_search/rag/
  __init__.py
  search_text_builder.py
  bm25_nori_retriever.py
  evidence_mapper.py
  evidence_validator.py
  metadata_context_enricher.py
  retrieval_pipeline.py
  source_reference.py
```

| 파일 | 역할 |
| --- | --- |
| `search_text_builder.py` | `full_optional_context` 검색문 생성 |
| `bm25_nori_retriever.py` | Agent 운영 정본 BM25+Nori 검색 |
| `evidence_mapper.py` | review_case ES hit → Agent evidence 변환 |
| `evidence_validator.py` | evidence 유효성 검증 |
| `metadata_context_enricher.py` | metadata성 chunk 보강. V1 기본 OFF |
| `retrieval_pipeline.py` | RAG 내부 흐름 조립 |
| `source_reference.py` | 출처 문자열 생성/표준화 |

---

## 14. 테스트 계획

### 14.1 테스트셋 구분

```text
full optional input test set:
  전체 25개
  Agent schema 안정성 검증용

active schema search eval:
  주석 제외 10개
  BM25+Nori 검색 품질 평가용
```

주의:

```text
JSONL parser는 // 로 시작하는 라인을 skip해야 한다.
```

### 14.2 단위 테스트

```text
test_search_text_builder.py
  - query_text만 있는 경우
  - Vision/OCR/보험사 주장까지 있는 경우
  - None/빈 배열 입력 처리

test_bm25_nori_retriever.py
  - BM25_SEARCH_FIELDS가 V1 field boost와 일치하는지 확인
  - operator가 "or"인지 확인
  - highlight 설정이 search_text/chunk_text에 적용되는지 확인
  - 빈 search_text면 [] 반환
  - ES hit parsing 확인
  - 기존 review_case/search BM25 결과와 Agent BM25 결과의 top_k chunk_id 일치 확인

test_evidence_mapper.py
  - review_case hit 필드 매핑 확인
  - reference_chart_key / decision_fault_ratio / standard_context 매핑 확인
  - source_reference fallback 확인

test_ratio_range_builder.py
  - decision_fault_ratio 우선 사용
  - claimant_final_ratio/respondent_final_ratio 사용
  - metadata 없을 때 regex fallback
  - 표현 없으면 빈 문자열
```

---

## 15. 구현 순서

```text
1. agents/text_ml_case_search/rag/search_text_builder.py 구현
2. agents/text_ml_case_search/config.py 구현
3. agents/text_ml_case_search/rag/bm25_nori_retriever.py 구현
4. agents/text_ml_case_search/rag/source_reference.py 구현
5. agents/text_ml_case_search/rag/evidence_mapper.py 구현
6. agents/text_ml_case_search/rag/evidence_validator.py 구현
7. agents/text_ml_case_search/rag/retrieval_pipeline.py 구현
8. builders/ratio_range_builder.py metadata 우선 구현
9. full optional input 25개로 RAG 단독 테스트
10. active 10개로 검색 품질 확인
11. 기존 review_case/search BM25 결과와 Agent BM25 결과의 top_k chunk_id 일치 검증
12. Agent output_builder와 연결
```

`top_k chunk_id 일치 검증`은 Agent RAG 구현 후 수행한다.
목적은 기존 실험 코드의 검색 정책이 Agent 운영 코드로 제대로 이관됐는지 확인하는 것이다.

예시:

```text
query = "중앙선 침범 역주행 사고"

기존 review_case/search BM25 top5:
  chunk_a, chunk_b, chunk_c, chunk_d, chunk_e

Agent BM25 top5:
  chunk_a, chunk_b, chunk_c, chunk_d, chunk_e
```

예상 결과:

```text
1. 일치하면 검색 정책 이관이 정상이다.
2. 다르면 index명, field boost, operator, highlight 포함 query body 차이를 확인한다.
3. 이 검증은 최종 서비스 품질 평가가 아니라 검색 정책 이관 검증이다.
```

---

## 16. V1 완료 기준

```text
1. agents 폴더가 신규 생성된다.
2. review_case BM25+Nori 검색 정책이 Agent retriever로 이관된다.
3. V1 index는 review_case_chunks_bm25_nori_v1을 사용한다.
4. BM25_SEARCH_FIELDS가 실험 기준 field boost와 일치한다.
5. full_optional_context 검색문이 안정적으로 생성된다.
6. BM25+Nori 검색이 top_k 후보를 반환한다.
7. review_case hit가 evidence schema로 변환된다.
8. evidence[].source_type은 review_case로 들어간다.
9. evidence[].source_reference가 들어간다.
10. ratio_range_label은 metadata 우선, regex fallback으로 생성된다.
11. metadata_context_enricher는 기본 OFF다.
12. 검색 실패/무결과 상황에서도 빈 배열로 안전하게 반환된다.
13. Agent는 최종 자연어 답변을 생성하지 않는다.
```

---

## 17. V1.1 / V2 고도화

```text
V1.1:
  BM25+Nori candidate_k=10~20
  local reranker 재정렬
  top_k=5

V2:
  traffic_precedent adapter 추가
  fault_ratio_precedent adapter 추가
  source별 evidence mapper 분리
  review_case + precedent evidence merge
  과실비율 인정기준 index 추가 검토
```

---

## 18. 최종 정리

RAG V1은 다음 한 줄로 정리된다.

```text
Supervisor가 보낸 agent_input에서 full_optional_context 검색문을 만들고,
기존 심의사례 BM25+Nori 실험에서 검증한 검색 정책을 Agent 쪽으로 이관해
review_case_chunks_bm25_nori_v1에서 근거 chunk를 찾은 뒤,
review_case hit를 evidence / similar_cases / ratio_range_label 재료로 구조화해
text_ml_case_search Agent output에 넘기는 검색 계층이다.
```
---

## 부록 A. 2026-07-04 5단계 전 스키마 정렬 반영

### 목적

5단계 `search_text_builder.py` 구현 전에 Agent input/output schema를 먼저 맞춘다.

이유:

```text
RAG 검색 결과는 결국 evidence / similar_cases / recommended_evidence로 변환된다.
검색을 먼저 붙인 뒤 output schema가 바뀌면 mapper와 보고서 생성 로직을 다시 고쳐야 한다.
따라서 검색 연결 전에 evidence 관련 출력 계약을 먼저 고정한다.
```

### 반영 대상

```text
etl/fault_cases/src/agents/text_ml_case_search/input/context_builder.py
etl/fault_cases/src/agents/text_ml_case_search/builders/recommended_evidence_builder.py
etl/fault_cases/Fault_cases_MD/에이전트/스키마 관련.md
```

### 결정 사항

1. `vision_evidence`는 필수가 아니다.

```text
사용자가 텍스트만 입력해도 Agent는 동작해야 한다.
Vision 결과는 있으면 검색 품질을 높이는 보조 입력이다.
```

2. `source_ref`는 입력 alias로만 허용한다.

```text
source_ref 입력 허용
-> context_builder에서 source_reference로 변환
-> 최종 output에는 source_ref 미사용
```

3. `evidence_tags`와 `recommended_evidence`는 분리한다.

```text
evidence_tags:
  내부 분류/필터/후속 로직용 태그

recommended_evidence:
  Supervisor 또는 사용자에게 보여줄 수 있는 증거자료 요청 객체
```

값은 겹칠 수 있다. 예를 들어 `evidence_tags`에 `lane_change_video`가 있고, `recommended_evidence[].type`도 `lane_change_video`일 수 있다. 다만 전자는 내부 태그, 후자는 사용자에게 설명 가능한 항목이다.

4. `recommended_evidence`는 다음 필드를 가진다.

```json
{
  "type": "lane_change_video",
  "title": "차로 변경 시작 시점 영상",
  "description": "방향지시등 작동 여부, 차로 변경 시작 시점, 후행 차량과의 거리가 함께 보이는 영상이 필요합니다.",
  "related_issue": "진로변경 주의의무",
  "priority": "high",
  "based_on": ["issue_tags", "vision_evidence"]
}
```

5. `evidence[].metadata`는 공통 필드와 source별 세부 필드를 함께 둔다.

```text
공통:
  case_id, chunk_id, score, score_type, matched_facts, different_facts

review_case 전용:
  review_no, reference_chart_key, decision_fault_ratio, standard_context
```

### 예상 결과

```text
5단계 search_text_builder는 schema_search_text 생성에 집중한다.
6단계 BM25 retriever 연결 시 evidence mapper는 이미 고정된 output schema에 맞춰 변환한다.
Supervisor는 evidence_tags와 recommended_evidence를 혼동하지 않고 사용할 수 있다.
```
## 테스트 코드 운영 기준과 존재 이유

### 목적

`etl/fault_cases/src/agents/text_ml_case_search/tests/` 폴더의 파일들은 운영 실행용 코드가 아니라, Agent/RAG 구현이 계획한 계약을 계속 지키는지 확인하기 위한 검증 코드다.

즉 실제 서비스 흐름은 다음 파일들을 중심으로 동작한다.

```text
agent.py
rag/search_text_builder.py
rag/bm25_nori_retriever.py
rag/evidence_mapper.py
rag/evidence_validator.py
rag/retrieval_pipeline.py
rag/es_client.py
```

테스트 파일은 위 운영 코드가 의도대로 동작하는지 확인한다.

### 왜 테스트 폴더를 남기는가

Agent/RAG는 작은 변경에도 결과가 달라질 수 있다.

예를 들면 다음 항목이 바뀌면 검색 결과와 Agent output이 달라진다.

```text
1. BM25 검색 필드 boost
2. operator="or" 설정
3. highlight 설정
4. evidence mapper의 source_reference 생성 규칙
5. evidence validator의 최소 chunk_text 길이
6. Elasticsearch client 인증 방식
7. search_text variant fallback 순서
```

테스트는 이런 정책이 실수로 바뀌었을 때 바로 확인하기 위한 안전장치다.

### test_es_client.py의 의미

`test_es_client.py`는 실제 Elasticsearch 서버에 접속하는 테스트가 아니다.

이 파일은 다음만 확인한다.

```text
1. username + password가 있으면 basic_auth 인자가 만들어지는지
2. username이 없으면 인증 없는 client kwargs가 만들어지는지
3. username은 있는데 password가 없으면 ValueError가 발생하는지
```

따라서 테스트 안의 `dummy-password-for-test` 또는 `test-password` 같은 값은 실제 비밀번호가 아니다.

그 값은 아래 조건을 검증하기 위한 더미 문자열이다.

```text
입력:
  username = elastic
  password = dummy-password-for-test

기대:
  basic_auth = ("elastic", "dummy-password-for-test")
```

### 보안 기준

운영/개발 비밀번호는 절대 `.py` 파일에 직접 넣지 않는다.

비밀번호는 아래 환경변수 중 하나로만 주입한다.

```env
TEXT_ML_CASE_SEARCH_ELASTICSEARCH_PASSWORD=...
```

또는 기존 공통 설정을 사용한다.

```env
ELASTIC_PASSWORD=...
```

코드에는 실제 비밀번호가 아니라 환경변수 이름과 검증 로직만 남긴다.

### 예상 결과

이 기준을 적용하면 다음 효과가 있다.

```text
1. 코드에 실제 비밀번호가 남지 않는다.
2. password 누락 상태로 조용히 기본값 접속을 시도하지 않는다.
3. Agent/RAG 리팩터링 중에도 검색 정책 변화가 테스트로 드러난다.
4. 운영 코드와 테스트 코드의 역할이 분리된다.
```

---
