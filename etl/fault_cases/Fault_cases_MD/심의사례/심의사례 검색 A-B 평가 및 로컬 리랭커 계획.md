# 심의사례 검색 A-B 평가 및 로컬 리랭커 계획

## 1. 문서 목적

이 문서는 `review_case_db`에 적재된 자동차사고 과실비율분쟁 심의사례 데이터를 대상으로 검색 방식 A/B 평가를 어떻게 진행할지 정리한다.

이 문서의 범위는 전처리, DB 적재, chunk 생성, embedding 저장 자체가 아니다. 이미 생성된 심의사례 chunk와 embedding을 이용해 다음 검색 방식들을 같은 기준으로 비교하는 것이 목적이다.

```text
A. PostgreSQL pgvector
B. Elasticsearch BM25/Nori
C. Elasticsearch vector
D. Elasticsearch hybrid = BM25/Nori + vector
```

핵심은 검색기별 raw score를 직접 비교하지 않고, 같은 후보 집합을 로컬 기성 reranker로 다시 채점하여 공통 평가 점수를 만드는 것이다.

---

## 2. 현재 완료 상태

현재 심의사례 검색 평가 전 단계는 다음까지 완료된 상태다.

```text
1. review_case_db schema 생성
2. 전처리 JSONL -> PostgreSQL 적재
3. row count 검증
4. search_text 생성/보강
5. chunk embedding 저장
6. pgvector HNSW index 생성
7. pgvector baseline 샘플 검색
8. Elasticsearch BM25/Nori index 생성
9. Elasticsearch BM25/Nori 샘플 검색
10. Elasticsearch dense_vector index 생성
11. Elasticsearch vector 샘플 검색
12. Elasticsearch hybrid 샘플 검색
13. 4개 retriever 결과를 A/B 후보 JSONL로 통합
```

현재 주요 데이터 수는 다음과 같다.

```text
review_case_documents = 226
review_case_chunks = 904
review_case_chunk_embeddings = 904
embedding_pending = 0
```

현재 A/B 후보 통합 결과는 다음과 같다.

```text
query_count = 5
top_k = 5
retriever_count = 4
candidate_count = 100
```

계산 근거:

```text
5 queries x 4 retrievers x top5 = 100 candidates
```

즉, 현재 100개 후보는 임의 숫자가 아니다. `sample_queries.py`에 정의된 5개 심의사례 평가 질문을 4개 검색 방식으로 각각 top5 검색했기 때문에 생성된 후보 수다.

---

## 3. 현재 100개 후보를 사용하는 이유

현재 단계는 최종 평가가 아니라 smoke evaluation 성격이다.

100개 후보를 먼저 쓰는 이유는 다음과 같다.

```text
1. pgvector, BM25/Nori, vector, hybrid 검색 코드가 모두 같은 query set으로 동작하는지 확인한다.
2. 검색 결과 JSON 구조가 retriever별로 다르더라도 A/B 후보 JSONL로 통합 가능한지 확인한다.
3. 로컬 reranker가 심의사례 chunk_text를 정상 입력으로 받아 점수를 만들 수 있는지 확인한다.
4. 점수표와 보고서 생성 위치/포맷을 먼저 안정화한다.
5. query set을 30개 이상으로 늘리기 전에 비용과 실행 시간을 작게 검증한다.
```

현재 5개 query는 대표 사고상황 중심의 샘플이다.

```text
review_q001: 신호등 없는 중앙선 설치 도로에서 중앙선을 침범한 역주행 사고
review_q002: 신호등 있는 사거리 교차로에서 녹색 직진 차량과 적색 직진 차량 충돌
review_q003: 차로 변경 중 후행 직진 차량과 충돌한 사고의 과실비율
review_q004: 비보호 좌회전 차량과 녹색 신호 직진 차량 사이 교차로 사고
review_q005: 주차장 또는 이면도로에서 출차 차량과 직진 차량이 충돌한 사고
```

이 query set은 작은 검증용이다. 최종 평가용으로는 부족하다. 다만 현재 단계에서는 검색기 4개가 같은 질문으로 후보를 만들고, 통합 후보가 100개로 정확히 맞는지 확인하는 데 적합하다.

---

## 4. 비교 대상 검색 방식

### 4.0 서비스 후보 3개와 실험 분석 4개의 구분

검색 방식을 말할 때는 관점을 분리해야 한다.

서비스 후보 관점에서는 큰 축이 3개다.

```text
1. PostgreSQL pgvector
2. Elasticsearch BM25/Nori
3. Elasticsearch hybrid
```

이렇게 3개로 보는 이유는 실제 서비스나 Agent/RAG retriever router에서 사용자가 선택하거나 운영자가 비교할 최종 검색 방식이 이 세 갈래이기 때문이다.

반면 실험 분석 관점에서는 4개로 본다.

```text
1. PostgreSQL pgvector
2. Elasticsearch BM25/Nori
3. Elasticsearch vector
4. Elasticsearch hybrid = BM25/Nori + Elasticsearch vector
```

여기서 `Elasticsearch vector`는 최종 서비스 후보라기보다는 hybrid를 설명하고 검증하기 위한 중간 비교군에 가깝다.

이 중간 비교군을 따로 두는 이유는 다음과 같다.

```text
1. hybrid 결과가 좋아졌을 때 BM25 때문인지 vector 때문인지 분리해서 보기 위해서다.
2. PostgreSQL pgvector와 Elasticsearch vector가 같은 embedding으로 유사한 결과를 내는지 확인하기 위해서다.
3. Elasticsearch dense_vector 색인이 정상적으로 동작하는지 검증하기 위해서다.
4. hybrid가 BM25와 vector 양쪽의 장점을 실제로 결합하는지 확인하기 위해서다.
```

따라서 이 문서에서 `4개 retriever`라고 말하는 것은 최종 서비스 후보가 4개라는 뜻이 아니다.  
정확히는 다음 의미다.

```text
서비스 후보 관점:
  pgvector vs BM25/Nori vs hybrid = 3개

실험 분석 관점:
  pgvector vs BM25/Nori vs ES vector vs hybrid = 4개
```

현재 100개 후보도 이 실험 분석 관점의 4개 retriever를 기준으로 계산한다.

```text
5 queries x 4 retrievers x top5 = 100 candidates
```

### 4.1 PostgreSQL pgvector

pgvector는 PostgreSQL의 `review_case_chunk_embeddings.embedding_vector`를 기준으로 cosine similarity 검색을 수행한다.

강점:

```text
사용자 자연어 사고 설명과 PDF 표현이 달라도 의미적으로 가까운 chunk를 찾을 수 있다.
PostgreSQL 안에서 원본 chunk와 embedding을 함께 관리할 수 있다.
```

주의점:

```text
도표번호, 신호위반, 중앙선 침범 같은 정확 키워드 매칭은 BM25보다 약할 수 있다.
```

### 4.2 Elasticsearch BM25/Nori

BM25/Nori는 `search_text`를 중심으로 한국어 형태소 분석 기반 키워드 검색을 수행한다.

강점:

```text
신호등 있음/없음
사거리
중앙선 침범
비보호 좌회전
참고기준 249
청구차량 0%, 피청구차량 100%
```

같은 명시 키워드에 강하다.

주의점:

```text
사용자 표현이 PDF/검색 텍스트와 다르면 의미 검색보다 약할 수 있다.
```

### 4.3 Elasticsearch vector

Elasticsearch vector는 PostgreSQL에 이미 저장된 embedding을 Elasticsearch `dense_vector`로 색인한 뒤 vector 검색을 수행한다.

중요 원칙:

```text
embedding을 다시 만들지 않는다.
PostgreSQL의 review_case_chunk_embeddings.embedding_vector를 재사용한다.
```

이렇게 하는 이유:

```text
1. pgvector와 Elasticsearch vector가 같은 embedding으로 비교되어야 공정하다.
2. OpenAI embedding API 비용을 다시 쓰지 않는다.
3. embedding_model / embedding_version의 source of truth를 PostgreSQL에 둔다.
4. Elasticsearch index는 실험용 검색 index로 보고 언제든 재생성할 수 있게 한다.
```

### 4.4 Elasticsearch hybrid

Hybrid는 BM25/Nori 결과와 vector 결과를 합친 검색 방식이다.

현재 방식:

```text
BM25 top candidate 검색
vector top candidate 검색
각 후보의 rank를 RRF로 변환
hybrid_score = rrf_bm25 + rrf_vector
```

현재 RRF 기준:

```text
rrf_k = 60
```

RRF 공식을 쓰는 이유:

```text
BM25 score와 vector score는 서로 점수 범위와 의미가 다르다.
두 점수를 직접 더하면 한쪽 검색기 점수가 과도하게 지배할 수 있다.
RRF는 raw score 대신 순위를 결합하므로 검색 방식이 다른 두 결과를 섞기 쉽다.
```

공식:

```text
rrf_score = 1 / (k + rank)
hybrid_score = rrf_bm25 + rrf_vector
```

`k=60`을 쓰는 이유:

```text
1. RRF에서 널리 쓰이는 안정적인 baseline 값이다.
2. 1위 결과만 과도하게 지배하지 않도록 완충한다.
3. BM25와 vector 양쪽에서 모두 상위권인 후보를 자연스럽게 올린다.
4. 현재 단계에서는 hybrid 방식 검증이 목적이므로 k 값을 먼저 고정한다.
```

후속 실험에서는 다음 값을 비교할 수 있다.

```text
rrf_k = 10
rrf_k = 30
rrf_k = 60
```

---

## 5. retriever_score를 직접 비교하지 않는 이유

각 검색기의 raw score는 의미가 다르다.

```text
pgvector:
  cosine_similarity

Elasticsearch BM25/Nori:
  bm25_score

Elasticsearch vector:
  elasticsearch dense_vector _score

Elasticsearch hybrid:
  RRF fused score
```

예를 들어 아래 값은 서로 직접 비교하면 안 된다.

```text
pgvector cosine_similarity = 0.48
BM25 score = 182.2
Elasticsearch vector score = 0.74
hybrid_score = 0.032
```

이 값들은 같은 척도의 점수가 아니다.

따라서 A/B 평가에서는 다음 원칙을 둔다.

```text
retriever_score:
  검색기 내부 정렬용 점수로만 보존한다.

local_reranker_score:
  검색 방식 간 공통 비교 점수로 사용한다.
```

---

## 6. 로컬 reranker 사용 방식

현재 단계에서는 reranker를 검색 결과 개선용으로 쓰지 않는다. 평가용으로만 사용한다.

사용 방식:

```text
방식 A = 평가용 reranker
```

하지 않는 방식:

```text
방식 B = 실제 검색 결과 재정렬용 reranker
```

방식 A의 의미:

```text
pgvector top5 결과 순서를 바꾸지 않는다.
BM25/Nori top5 결과 순서를 바꾸지 않는다.
Elasticsearch vector top5 결과 순서를 바꾸지 않는다.
Elasticsearch hybrid top5 결과 순서를 바꾸지 않는다.

각 검색기가 가져온 후보를 같은 reranker로 채점만 한다.
```

이렇게 하는 이유:

```text
1. 검색 방식 자체의 차이를 보기 위해서다.
2. reranker가 결과를 다시 섞으면 어떤 retriever가 잘한 것인지 흐려진다.
3. fine-tuning 없이 기성 로컬 모델로 평가 baseline을 만들 수 있다.
4. 외부 reranker API 비용이 들지 않는다.
5. 후속 단계에서 reranker를 실제 검색 개선용으로 확장할 수 있다.
```

---

## 7. 로컬 reranker 모델 후보

1차 후보는 다음 모델이다.

```text
BAAI/bge-reranker-v2-m3
```

선택 이유:

```text
1. 다국어 query-document relevance 평가에 사용할 수 있다.
2. API 비용 없이 로컬에서 실행할 수 있다.
3. fine-tuning 없이 baseline 평가에 바로 사용할 수 있다.
4. 판례 A/B 평가 흐름과 같은 방식으로 재사용 가능하다.
```

주의점:

```text
1. CPU 실행 시 시간이 걸릴 수 있다.
2. 모델 점수가 절대 정답은 아니므로 일부 샘플은 사람이 확인해야 한다.
3. 심의사례 도표번호/과실비율처럼 도메인 특화 판단은 사람이 보조 검수해야 한다.
```

현재 100개 후보 기준 예상 실행 시간:

```text
100 candidates:
  CPU 기준 대략 1~2분 내외 예상
```

후속 30개 query 기준 예상 후보 수:

```text
30 queries x 4 retrievers x top5 = 600 candidates
```

이 경우 reranker 실행 시간이 더 늘어난다.

---

## 8. 평가 입력과 출력

### 8.1 입력 파일

로컬 reranker 평가 입력은 다음 파일이다.

```text
etl/fault_cases/artifacts/review_case_output/retrieval_ab_exports/review_case_retrieval_ab_candidates.jsonl
```

현재 이 파일에는 다음 구조의 후보가 들어간다.

```json
{
  "query_id": "review_q001",
  "query": "신호등 없는 중앙선 설치 도로에서 중앙선을 침범한 역주행 사고",
  "retriever": "pgvector_cosine",
  "rank": 1,
  "review_case_id": "review_case_2017_032889",
  "review_no": "2017-032889",
  "chunk_id": "review_case_2017_032889_case_overview",
  "chunk_type": "case_overview",
  "reference_chart_key": "249",
  "retriever_score": 0.4849,
  "score_type": "cosine_similarity",
  "chunk_preview": "..."
}
```

### 8.2 reranker 입력 필드

정식 평가는 `chunk_text`를 쓰는 것이 가장 좋다. 다만 현재 A/B 후보 JSONL에는 빠른 확인을 위해 `chunk_preview`와 `search_preview`가 포함되어 있다.

우선순위:

```text
1순위: chunk_text
2순위: search_preview
3순위: chunk_preview
```

현재 smoke 평가에서는 `chunk_preview` 또는 `search_preview`로 시작할 수 있다. 정식 평가 전에는 후보 JSONL에 full `chunk_text`를 포함하거나, chunk_id로 DB에서 chunk_text를 조회해 평가하는 방식이 더 좋다.

### 8.3 출력 파일

reranker 평가와 점수표 산출물은 아래 위치에 둔다.

```text
etl/fault_cases/artifacts/review_case_output/retrieval_ab_exports/
  review_case_retrieval_ab_reranker_scores.jsonl
  review_case_retrieval_ab_score_summary.json
```

사람이 읽는 MD 보고서는 반드시 아래 폴더에 생성한다.

```text
etl/fault_cases/Fault_cases_MD/심의사례/
  심의사례 검색 A-B 정량 점수표.md
  심의사례 검색 A-B 평가 결과 보고서.md
```

이 위치를 고정하는 이유:

```text
1. 심의사례 문서와 판례 문서를 분리한다.
2. 판례 평가 결과와 섞이지 않게 한다.
3. DBeaver/DB 적재 결과가 아니라 사람이 읽는 분석 문서는 Fault_cases_MD 아래에서 관리한다.
4. 팀원이 심의사례 관련 판단 근거를 한 폴더에서 찾을 수 있게 한다.
```

---

## 9. 점수 지표

로컬 reranker가 각 후보에 `local_reranker_score`를 부여하면 다음 지표를 계산한다.

| 지표 | 의미 | 보는 이유 |
|---|---|---|
| top1_score | 각 retriever가 1위로 가져온 후보의 reranker 점수 | 사용자가 가장 먼저 볼 후보의 품질 |
| avg_score@5 | top5 후보 reranker 점수 평균 | 검색 결과 목록 전체 품질 |
| max_score@5 | top5 중 최고 reranker 점수 | 좋은 후보가 하나라도 들어왔는지 |
| min_score@5 | top5 중 최저 reranker 점수 | 잡음 후보가 얼마나 섞이는지 |
| std_score@5 | top5 점수 표준편차 | 결과 품질이 안정적인지 |

1차 핵심 지표:

```text
top1_score
avg_score@5
max_score@5
```

심의사례에서는 여기에 아래 보조 판단도 같이 봐야 한다.

```text
expected_reference_chart_key 일치 여부
chunk_type 분포
case_overview 과다 여부
decision chunk 회수 여부
metadata/overview만 있고 결정이유가 부족한지 여부
```

---

## 10. 심의사례 평가에서 특히 봐야 할 점

### 10.1 reference_chart_key

심의사례는 참고기준 도표가 매우 중요하다.

예:

```text
query: 신호등 없는 중앙선 설치 도로에서 중앙선을 침범한 역주행 사고
expected_reference_chart_key: 249
```

이 경우 top5 안에 `reference_chart_key = 249`가 들어오는지 확인해야 한다.

단, 모든 query에 정답 도표번호를 강제로 두지는 않는다. 일부 query는 사고상황 탐색용으로 쓰기 때문에 expected 값이 비어 있을 수 있다.

### 10.2 chunk_type

현재 심의사례 chunk는 4종류다.

```text
case_overview
arguments
evidence_issue
decision
```

질문 유형별 기대 chunk_type이 다르다.

```text
사고상황 질문:
  case_overview가 유리

주장 질문:
  arguments가 유리

증거/쟁점 질문:
  evidence_issue가 유리

결정이유/과실비율 질문:
  decision이 유리
```

따라서 전체 점수만 보지 말고 retriever별 top5 chunk_type 분포를 함께 봐야 한다.

### 10.3 case_overview 과다 문제

case_overview는 사고유형, 참고기준 키워드, 결정비율이 들어 있어 검색에는 강하다.

하지만 실제 답변을 만들 때는 결정근거/결정이유가 부족할 수 있다.

따라서 평가 보고서에는 다음 내용을 포함한다.

```text
1. winner 후보가 case_overview에 과도하게 몰리는지
2. decision chunk가 충분히 검색되는지
3. case_overview가 top1일 때 같은 review_no의 decision chunk를 보강 context로 붙일 필요가 있는지
```

---

## 11. 현재 실행 명령 계획

### 11.1 이미 완료된 검색 후보 생성

현재 4개 retriever 샘플 검색과 후보 통합은 완료되어 있다.

재생성이 필요할 때는 아래 순서로 실행한다.

```powershell
python -B -m etl.fault_cases.src.review_case.search.pgvector.run_sample_queries --top-k 5
python -B -m etl.fault_cases.src.review_case.search.elasticsearch.run_bm25_sample_queries --top-k 5
python -B -m etl.fault_cases.src.review_case.search.elasticsearch.run_vector_sample_queries --top-k 5
python -B -m etl.fault_cases.src.review_case.search.elasticsearch.run_hybrid_sample_queries --top-k 5
python -B -m etl.fault_cases.src.review_case.search.evaluation.export_retrieval_ab_candidates --top-k 5
```

주의:

```text
pgvector, Elasticsearch vector, Elasticsearch hybrid 샘플 검색은 query embedding 생성을 위해 OpenAI embedding API 호출이 필요하다.
BM25/Nori 샘플 검색은 API 호출이 필요 없다.
```

### 11.2 다음에 만들 실행 명령

다음 단계에서 구현할 명령은 아래와 같다.

```powershell
python -B -m etl.fault_cases.src.review_case.search.evaluation.run_local_reranker --model models/bge-reranker-v2-m3 --input-field chunk_preview --batch-size 4 --device cpu
python -B -m etl.fault_cases.src.review_case.search.evaluation.build_reranker_reports
```

정식 평가에서는 가능하면 아래처럼 full `chunk_text`를 쓰는 방식으로 확장한다.

```powershell
python -B -m etl.fault_cases.src.review_case.search.evaluation.run_local_reranker --model models/bge-reranker-v2-m3 --input-field chunk_text --batch-size 4 --device cpu
```

---

## 12. 정량 점수표 MD 구조

`심의사례 검색 A-B 정량 점수표.md`는 다음 구조로 만든다.

```text
1. 평가 개요
2. 전체 평균 점수표
3. retriever별 top1/avg@5/max@5
4. query별 winner
5. query별 retriever 점수표
6. chunk_type 분포
7. reference_chart_key hit 요약
8. 주의할 샘플
```

예상 표:

| Retriever | Query Count | Top K | Candidate Count | Avg Top1 | Avg@5 | Max@5 | Winner Count |
|---|---:|---:|---:|---:|---:|---:|---:|
| pgvector_cosine | 5 | 5 | 25 | TBD | TBD | TBD | TBD |
| elasticsearch_bm25_nori | 5 | 5 | 25 | TBD | TBD | TBD | TBD |
| elasticsearch_vector_cosine | 5 | 5 | 25 | TBD | TBD | TBD | TBD |
| elasticsearch_hybrid_bm25_vector_rrf | 5 | 5 | 25 | TBD | TBD | TBD | TBD |

---

## 13. 평가 결과 보고서 MD 구조

`심의사례 검색 A-B 평가 결과 보고서.md`는 단순 점수표가 아니라 사람이 해석할 수 있는 보고서로 만든다.

구조:

```text
1. 실험 개요
2. 실행 환경
3. 비교 대상 retriever
4. 후보 수 산정 방식
5. 전체 결과 요약
6. retriever별 강점/약점
7. query별 분석
8. chunk_type 관점 분석
9. reference_chart_key 관점 분석
10. case_overview 과다 여부
11. 운영 후보 판단
12. 후속 개선 계획
```

특히 `후보 수 산정 방식`에는 현재 100개 후보의 이유를 반드시 쓴다.

```text
현재 실험은 5개 query, 4개 retriever, top5 기준이다.
따라서 후보 수는 5 x 4 x 5 = 100개다.
이는 최종 평가가 아니라 4개 검색 방식과 로컬 reranker 평가 파이프라인을 검증하기 위한 smoke evaluation이다.
```

---

## 14. 100개 후보 이후 확장 계획

100개 후보 평가가 정상적으로 끝나면 query set을 확장한다.

권장 확장:

```text
1차 smoke:
  5 queries x 4 retrievers x top5 = 100 candidates

1차 정식:
  30 queries x 4 retrievers x top5 = 600 candidates

2차 정식:
  50 queries x 4 retrievers x top5 = 1,000 candidates
```

심의사례 최종 평가 query 유형:

```text
A. 사고상황형
B. 도표번호형
C. 주장형
D. 증거형
E. 쟁점형
F. 결정이유형
G. 비율형
```

확장 전 반드시 확인할 것:

```text
1. query 문자열 인코딩이 깨지지 않았는지
2. 4개 retriever 결과가 같은 query_id/query 순서를 쓰는지
3. 후보 통합 결과의 candidate_count가 계산식과 맞는지
4. reranker 점수표 MD가 심의사례 폴더에 생성되는지
5. case_overview top1일 때 decision 보강 규칙이 필요한지
```

---

## 15. 최종 판단 기준

심의사례 검색에서는 단순히 reranker 평균 점수가 높은 retriever만 고르면 안 된다.

최종 판단은 아래 요소를 함께 본다.

```text
1. local_reranker_score
2. expected_reference_chart_key hit
3. 사고상황 키워드 일치
4. chunk_type 적합성
5. decision chunk 회수 여부
6. top1 결과의 답변 근거 충분성
7. 실행 속도
8. 운영 복잡도
```

초기 예상:

```text
BM25/Nori:
  도표번호, 신호위반, 중앙선 침범처럼 명확한 키워드 query에 강할 가능성이 높다.

pgvector:
  자연어 사고상황 설명에 강할 가능성이 있다.

Elasticsearch vector:
  pgvector와 같은 embedding을 쓰므로 유사한 방향의 결과가 나오되, ES 검색 운영 구조 검증에 의미가 있다.

Hybrid:
  BM25와 vector가 같은 후보를 상위로 밀 때 가장 안정적일 가능성이 높다.
```

단, 현재 심의사례 데이터는 904개 chunk로 비교적 작다. 따라서 BM25/Nori만으로도 충분히 강하게 나올 가능성이 있다. 이 점은 점수표와 사람이 보는 샘플 검수로 확인해야 한다.

---

## 16. 다음 단계

이 문서 작성 후 바로 진행할 단계는 다음이다.

```text
1. 로컬 reranker 평가 코드 구현
2. review_case_retrieval_ab_candidates.jsonl 100개 후보 채점
3. review_case_retrieval_ab_reranker_scores.jsonl 생성
4. review_case_retrieval_ab_score_summary.json 생성
5. 심의사례 검색 A-B 정량 점수표.md 생성
6. 심의사례 검색 A-B 평가 결과 보고서.md 생성
```

보고서 생성 위치:

```text
etl/fault_cases/Fault_cases_MD/심의사례/
```

현재 단계의 성공 기준:

```text
candidate_count = 100
scored_candidate_count = 100
query_count = 5
retriever_count = 4
점수표 MD 생성
평가 결과 보고서 MD 생성
```
