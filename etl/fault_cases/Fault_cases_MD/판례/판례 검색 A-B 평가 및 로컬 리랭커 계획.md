# 판례 검색 A-B 평가 및 로컬 리랭커 계획

## 1. 문서 목적

이 문서는 판례 RAG 파이프라인의 검색 방식 A/B 테스트를 어떻게 공정하게 비교할지 정리한다.

본 계획은 전처리, DB 적재, chunk 생성, embedding 저장 자체가 아니라 다음 단계를 다룬다.

```text
pgvector 검색
Elasticsearch BM25/Nori 검색
Elasticsearch vector/hybrid 검색

위 검색 방식들이 가져온 top_k 결과를
같은 기준으로 평가하는 방법
```

---

# 최신 보강본: 판례 검색 A/B 평가 및 로컬 리랭커 점수 보고서 계획

## 1. 보강 목적

이 보강본은 기존 LAW A/B 참고 문서의 구조를 판례 검색 실험에 맞게 확장한 것이다.

참고 구조:

```text
etl/fault_cases/Fault_cases_MD/참고/ab_test_report.md
  - 실험 개요
  - 비교 대상
  - 결과 요약
  - 비용/운영 판단
  - 최종 권장안

etl/fault_cases/Fault_cases_MD/참고/ab_test_scores.md
  - query별 점수표
  - 점수 차이 원인 분석
  - 방식별 평균 점수
```

판례 검색 A/B도 같은 식으로 두 종류의 결과물을 만든다.

```text
1. 판례 검색 A-B 평가 결과 보고서.md
   - 사람이 읽는 분석 보고서
   - 어떤 검색 방식이 왜 좋은지 설명

2. 판례 검색 A-B 정량 점수표.md
   - query별 점수표
   - retriever별 평균 점수
```

현재 리랭커 평가는 아직 실행하지 않았다.  
따라서 이 문서는 **리랭커 실행 전 평가 설계와 보고서 구조를 확정하는 계획서**다.

## 2. 현재 실제 비교 대상

현재 1차 A/B 비교 대상은 3개가 아니라 4개다.

```text
A. PostgreSQL pgvector
B. Elasticsearch BM25/Nori
C. Elasticsearch vector
D. Elasticsearch hybrid = BM25/Nori + vector
```

각 방식의 역할은 다음과 같다.

| 방식 | 설명 | 기대 강점 | 주의점 |
|---|---|---|---|
| PostgreSQL pgvector | PostgreSQL embedding_vector를 cosine 기준으로 검색 | PostgreSQL 안에서 원본과 벡터 검색을 함께 관리 | 키워드 정확 매칭과 하이라이트는 약함 |
| Elasticsearch BM25/Nori | Nori analyzer 기반 한국어 키워드 검색 | 신호위반, 횡단보도, 과실비율 같은 명시 키워드에 강함 | 표현이 바뀐 의미 검색에는 약할 수 있음 |
| Elasticsearch vector | PostgreSQL embedding을 ES dense_vector로 색인해 검색 | 같은 embedding을 다른 검색엔진에서 비교 가능 | keyword 기반 정밀 매칭은 직접 반영하지 않음 |
| Elasticsearch hybrid | BM25 후보와 vector 후보를 RRF로 결합 | 키워드 검색과 의미 검색을 같이 반영 | hybrid_score는 내부 정렬용이며 최종 품질 점수가 아님 |

비교 조건은 반드시 통제한다.

```text
같은 query set
같은 top_k
같은 chunk_text
같은 embedding_model
같은 embedding_version
같은 평가 reranker
```

현재 baseline embedding 조건:

```text
embedding_model = text-embedding-3-small
embedding_dim = 1536
embedding_version = openai_text_embedding_3_small_chunk_text_v1
input_field = chunk_text
```

## 3. 현재 산출물 상태

현재 검색 결과는 이미 같은 A/B 후보 포맷으로 통합되어 있다.

```text
etl/fault_cases/artifacts/traffic_precedents_output/retrieval_ab_exports/
  retrieval_ab_candidates.jsonl
  retrieval_ab_summary.json
```

현재 통합 결과:

```text
query_count: 6
top_k: 5
retriever_count: 4
candidate_count: 120
```

계산:

```text
6 queries × 5 results × 4 retrievers = 120 candidates
```

retriever 구성:

```text
pgvector
elasticsearch_bm25_nori
elasticsearch_vector_cosine
elasticsearch_hybrid_bm25_vector_rrf
```

이 파일은 리랭커 평가의 입력 데이터가 된다.

## 4. retriever_score를 직접 비교하지 않는 이유

각 검색 방식은 점수 의미가 다르다.

```text
pgvector:
  cosine_similarity

Elasticsearch BM25/Nori:
  bm25_score

Elasticsearch vector:
  elasticsearch_vector_score

Elasticsearch hybrid:
  rrf_hybrid_score
```

예를 들어 다음 점수들은 직접 비교할 수 없다.

```text
pgvector cosine_similarity = 0.62
BM25 score = 38.05
Elasticsearch vector score = 0.82
hybrid RRF score = 0.030
```

이유:

```text
1. cosine_similarity는 벡터 방향 유사도다.
2. BM25 score는 키워드 빈도, 문서 길이, 역문서빈도 기반 점수다.
3. Elasticsearch vector score는 ES dense_vector 내부 점수다.
4. hybrid score는 BM25/vector 순위를 RRF로 합친 내부 정렬 점수다.
```

따라서 `retriever_score`는 저장하되, 검색 방식 간 최종 비교 기준으로 쓰지 않는다.  
최종 비교는 별도 공통 점수인 `local_reranker_score`로 한다.

## 5. Hybrid와 RRF 해석

현재 hybrid는 BM25 score와 vector score를 직접 더하지 않는다.  
대신 BM25 순위와 vector 순위를 RRF 방식으로 합친다.

공식:

```text
rrf_score = 1 / (k + rank)
hybrid_score = rrf_bm25 + rrf_vector
```

현재 baseline:

```text
k = 60
```

`k=60`을 쓰는 이유:

```text
1. RRF에서 널리 쓰이는 기본 baseline 값이다.
2. 한 검색기의 1등 결과가 과하게 지배하지 않도록 완충한다.
3. BM25와 vector 양쪽에서 모두 상위권에 잡힌 후보를 우대한다.
4. BM25 score와 vector score의 스케일 차이를 피할 수 있다.
```

예시:

```text
BM25 rank = 1, vector rank = 없음
rrf_bm25 = 1 / (60 + 1) = 0.01639
rrf_vector = 0
hybrid_score = 0.01639

BM25 rank = 15, vector rank = 1
rrf_bm25 = 1 / (60 + 15) = 0.01333
rrf_vector = 1 / (60 + 1) = 0.01639
hybrid_score = 0.02972
```

즉 BM25에서만 1등인 결과보다, BM25와 vector 양쪽에서 함께 잡힌 후보가 hybrid에서 더 위로 올라올 수 있다.

후속 실험에서는 다음 값을 비교할 수 있다.

```text
k = 10
k = 30
k = 60
```

하지만 1차 baseline은 `k=60`으로 고정한다.

## 6. 리랭커 사용 방식

1차 평가에서는 로컬 기성 reranker를 **검색 개선용**이 아니라 **평가용**으로만 사용한다.

사용 방식:

```text
방식 A = 평가용 reranker
```

사용하지 않는 방식:

```text
방식 B = 검색 개선용 reranker
```

방식 A에서는 reranker가 검색 결과 순서를 바꾸지 않는다.

```text
pgvector 결과 순서 유지
BM25/Nori 결과 순서 유지
Elasticsearch vector 결과 순서 유지
Elasticsearch hybrid 결과 순서 유지
```

reranker는 각 후보에 점수만 부여한다.

```text
input:
  query + chunk_text

output:
  local_reranker_score
```

이렇게 하는 이유:

```text
1. 검색 방식 자체의 차이를 비교하기 위해서다.
2. reranker가 순서를 바꾸면 어떤 retriever가 잘한 것인지 흐려진다.
3. fine-tuning 없이 로컬 기성 모델로 baseline 평가를 만들 수 있다.
4. 외부 API 비용 없이 시작할 수 있다.
```

## 7. 로컬 기성 reranker 후보

1차 후보는 fine-tuning 없이 바로 사용할 수 있는 로컬 기성 reranker다.

| 후보 | 장점 | 한계 | 적용 판단 |
|---|---|---|---|
| `BAAI/bge-reranker-v2-m3` | 다국어 지원, 한국어 query-document 점수화에 사용 가능 | 모델 다운로드와 로컬 추론 비용 필요 | 1차 우선 후보 |
| multilingual cross-encoder reranker | query와 문서의 관련성 점수화에 적합 | 모델별 한국어 성능 확인 필요 | 후보 |
| LLM judge | 평가 기준을 자연어로 자세히 줄 수 있음 | 비용, 속도, 일관성 관리 부담 | 보조 검토 |
| API형 reranker | 서버/GPU 부담 적음 | 외부 API 비용 발생 | 현재 보류 |
| fine-tuned reranker | 도메인 최적화 가능 | 학습 데이터 구축 필요 | 후속 보류 |

현재 원칙:

```text
1. 비용이 들지 않는 로컬 기성 reranker부터 시작한다.
2. fine-tuning은 하지 않는다.
3. reranker 점수가 이상한 샘플은 사람이 일부 검수한다.
4. 평가 결과가 불안정하면 LLM judge를 소량 보조 평가로 붙인다.
```

## 8. 점수 산출 방식

로컬 reranker가 각 후보에 `local_reranker_score`를 부여하면 다음 지표를 계산한다.

| 지표 | 의미 | 보는 이유 |
|---|---|---|
| `top1_score` | 각 검색기가 1등으로 가져온 후보의 reranker 점수 | 사용자에게 가장 먼저 보여줄 후보 품질 |
| `avg_score@5` | top5 후보 reranker 점수 평균 | 검색 결과 목록 전체 품질 |
| `max_score@5` | top5 중 최고 reranker 점수 | 좋은 근거가 하나라도 들어왔는지 |
| `min_score@5` | top5 중 최저 reranker 점수 | 검색 결과에 잡음이 섞이는지 |
| `std_score@5` | top5 점수 표준편차 | 결과 품질이 안정적인지 |

1차 핵심 지표:

```text
top1_score
avg_score@5
max_score@5
```

보조 지표:

```text
min_score@5
std_score@5
latency_ms
```

## 9. 점수 보고서 산출물

LAW 참고 문서처럼 판례 A/B도 보고서와 점수표를 분리한다.

권장 산출물:

```text
etl/fault_cases/artifacts/traffic_precedents_output/retrieval_ab_exports/
  retrieval_ab_candidates.jsonl
  retrieval_ab_summary.json
  retrieval_ab_reranker_scores.jsonl
  retrieval_ab_score_summary.json

etl/fault_cases/Fault_cases_MD/판례/
  판례 검색 A-B 평가 결과 보고서.md
  판례 검색 A-B 정량 점수표.md
```

`retrieval_ab_reranker_scores.jsonl`에는 다음 필드를 저장한다.

```json
{
  "query_id": "traffic_q001",
  "dataset": "traffic",
  "query": "차로변경 중 발생한 교통사고 판례",
  "retriever": "pgvector",
  "rank": 1,
  "case_id": "...",
  "chunk_id": "...",
  "chunk_type": "case_overview",
  "retriever_score": 0.5336,
  "score_type": "cosine_similarity",
  "local_reranker_score": 0.82,
  "reranker_model": "BAAI/bge-reranker-v2-m3",
  "reranker_input_field": "chunk_text"
}
```

## 10. 정량 점수표 템플릿

`판례 검색 A-B 정량 점수표.md`는 다음 구조로 작성한다.

### 전체 평균

| Retriever | Query Count | Top K | Avg Top1 | Avg Score@5 | Avg Max@5 | Avg Min@5 | Avg Latency |
|---|---:|---:|---:|---:|---:|---:|---:|
| pgvector | 6 | 5 | TBD | TBD | TBD | TBD | TBD |
| elasticsearch_bm25_nori | 6 | 5 | TBD | TBD | TBD | TBD | TBD |
| elasticsearch_vector_cosine | 6 | 5 | TBD | TBD | TBD | TBD | TBD |
| elasticsearch_hybrid_bm25_vector_rrf | 6 | 5 | TBD | TBD | TBD | TBD | TBD |

### Dataset별 평균

| Dataset | Retriever | Avg Top1 | Avg Score@5 | Avg Max@5 | 비고 |
|---|---|---:|---:|---:|---|
| traffic | pgvector | TBD | TBD | TBD |  |
| traffic | elasticsearch_bm25_nori | TBD | TBD | TBD |  |
| traffic | elasticsearch_vector_cosine | TBD | TBD | TBD |  |
| traffic | elasticsearch_hybrid_bm25_vector_rrf | TBD | TBD | TBD |  |
| fault_ratio | pgvector | TBD | TBD | TBD |  |
| fault_ratio | elasticsearch_bm25_nori | TBD | TBD | TBD |  |
| fault_ratio | elasticsearch_vector_cosine | TBD | TBD | TBD |  |
| fault_ratio | elasticsearch_hybrid_bm25_vector_rrf | TBD | TBD | TBD |  |

### Query별 점수

| Query ID | Dataset | Query | Retriever | Top1 | Avg@5 | Max@5 | Winner 여부 |
|---|---|---|---|---:|---:|---:|---|
| traffic_q001 | traffic | 차로변경 중 발생한 교통사고 판례 | pgvector | TBD | TBD | TBD |  |
| traffic_q001 | traffic | 차로변경 중 발생한 교통사고 판례 | elasticsearch_bm25_nori | TBD | TBD | TBD |  |
| traffic_q001 | traffic | 차로변경 중 발생한 교통사고 판례 | elasticsearch_vector_cosine | TBD | TBD | TBD |  |
| traffic_q001 | traffic | 차로변경 중 발생한 교통사고 판례 | elasticsearch_hybrid_bm25_vector_rrf | TBD | TBD | TBD |  |

## 11. 자연어 분석 보고서 템플릿

`판례 검색 A-B 평가 결과 보고서.md`는 다음 구조를 따른다.

```text
1. 실험 개요
   - 실험 일시
   - 대상 데이터셋
   - query 수
   - top_k
   - 비교 retriever
   - 평가 reranker

2. 전체 결과 요약
   - 전체 winner
   - traffic winner
   - fault_ratio winner
   - 검색 방식별 강점/약점

3. Query별 분석
   - 어떤 query에서 어떤 retriever가 강했는지
   - BM25가 강한 query
   - vector가 강한 query
   - hybrid가 강한 query

4. 점수 차이 원인 분석
   - 키워드 일치가 중요한 경우
   - 의미 유사성이 중요한 경우
   - metadata chunk가 과하게 올라오는 경우
   - case_overview가 과하게 올라오는 경우

5. 운영 판단
   - 품질
   - 속도
   - 구현 복잡도
   - 비용
   - 유지보수성

6. 최종 권장안
   - 1차 서비스 baseline
   - 후속 개선 후보
```

## 12. 최소 실행 버전과 확장 계획

현재 최소 실행 버전:

```text
query_count = 6
top_k = 5
retriever_count = 4
candidate_count = 120
```

이 정도면 로컬 reranker 흐름을 검증하기에 충분하다.

검증 후 확장:

```text
query_count = 20
top_k = 5
retriever_count = 4
candidate_count = 400
```

최종 실험 확장:

```text
query_count = 50
top_k = 5
retriever_count = 4
candidate_count = 1,000
```

## 13. 평가 시 주의할 점

### 13.1 metadata chunk 편향

현재 검색 결과에는 `traffic_metadata`, `fault_ratio_metadata`, `fault_ratio_evidence` chunk가 상위에 많이 올라올 수 있다.

이는 항상 나쁜 것은 아니다.  
하지만 사용자가 법리 판단을 원할 때는 `holding_summary`, `main_text`가 더 적합할 수 있다.

따라서 평가 보고서에는 chunk_type 분포를 함께 넣는다.

```text
retriever별 top5 chunk_type 분포
winner 후보의 chunk_type 분포
metadata chunk 과다 여부
```

### 13.2 case_overview 편향

vector 검색은 사건명과 라벨 중심의 `case_overview`를 많이 가져올 수 있다.

장점:

```text
사건 주제 매칭에 강함
```

한계:

```text
구체적인 법리나 판단 이유가 부족할 수 있음
```

### 13.3 BM25 편향

BM25는 명시적 단어가 정확히 맞을 때 강하다.

예:

```text
신호위반
횡단보도
과실비율
손해배상
과실상계
```

한계:

```text
표현이 바뀐 의미 검색에는 약할 수 있음
```

### 13.4 Hybrid 해석 주의

Hybrid가 항상 최고일 것이라고 가정하지 않는다.

Hybrid는 다음 경우 강할 수 있다.

```text
BM25와 vector가 같은 후보를 동시에 상위권으로 잡는 경우
```

하지만 다음 경우에는 애매할 수 있다.

```text
BM25와 vector가 서로 다른 방향의 후보를 잡는 경우
metadata chunk가 vector에서 과하게 올라오는 경우
```

## 14. 실행 순서

다음 순서로 진행한다.

```text
1. retrieval_ab_candidates.jsonl 확인
2. local reranker 모델 선택
3. query + chunk_text로 reranker score 생성
4. retrieval_ab_reranker_scores.jsonl 저장
5. retrieval_ab_score_summary.json 생성
6. 판례 검색 A-B 정량 점수표.md 작성
7. 판례 검색 A-B 평가 결과 보고서.md 작성
8. 사람이 일부 샘플 검수
9. 1차 검색 방식 winner 결정
```

평가 입력 필드 기준:

```text
1차 smoke 평가:
  chunk_preview 사용 가능

정식 평가:
  full chunk_text 사용 권장
```

## 15. 최종 원칙

```text
지금 단계는 검색 방식을 비교하는 단계다.
따라서 reranker는 검색 개선용이 아니라 평가용으로만 사용한다.

retriever_score는 검색기 내부 점수다.
검색 방식 간 직접 비교 기준으로 쓰지 않는다.

공통 비교 점수는 local_reranker_score로 만든다.

최종 보고서는 정량 점수표와 자연어 분석 보고서를 분리한다.
```

후속 확장:

```text
1. query set 확대
2. RRF k=10/30/60 비교
3. text-embedding-3-large 1536 차원 추가 비교
4. reranker를 실제 검색 개선용으로 적용
5. 최종 Agent/RAG retriever router 설계
```

따라서 통합 계획서에는 결정 요약만 남기고, 검색 평가 세부 설계는 이 문서에서 별도로 관리한다.

## 2. 최종 결정

1차 검색 방식 A/B 테스트에서는 비용이 들지 않는 로컬 기성 reranker를 평가용으로만 사용한다.

```text
사용 방식:
  방식 A = 평가용 reranker

사용하지 않는 방식:
  방식 B = 검색 결과를 실제로 재정렬하는 reranker
```

즉, reranker는 사용자에게 보여줄 검색 결과를 바꾸지 않는다.

```text
pgvector 결과를 reranker가 바꾸지 않음
BM25/Nori 결과를 reranker가 바꾸지 않음
hybrid 결과를 reranker가 바꾸지 않음

각 검색기가 가져온 top_k를
같은 reranker로 점수화해서
어느 검색기가 좋은 후보를 더 잘 가져왔는지 비교
```

## 3. 왜 로컬 기성 reranker인가

BM25 score, cosine similarity, hybrid score는 검색기 내부 점수라서 직접 비교하면 안 된다.

예를 들어 다음 점수들은 같은 의미의 점수가 아니다.

```text
pgvector cosine similarity = 0.82
Elasticsearch BM25 score = 13.7
hybrid score = 0.64
```

따라서 A/B 테스트에는 검색기와 분리된 공통 평가 점수가 필요하다.

로컬 기성 reranker를 선택하는 이유는 다음과 같다.

| 기준 | 판단 |
|---|---|
| 비용 | 외부 API 호출 비용이 없다. |
| 실험 통제 | pgvector, BM25, hybrid 결과를 같은 모델로 채점할 수 있다. |
| 파이프라인 영향 | 검색 결과를 바꾸지 않고 평가 단계에만 사용한다. |
| 구현 부담 | fine-tuning 없이 기성 모델로 시작할 수 있다. |
| 한계 | 모델 설치, 로컬 실행 속도, CPU/GPU 자원 부담이 있다. |

## 4. 비교 대상

1차 검색 방식 A/B 대상은 다음과 같다.

```text
A. PostgreSQL pgvector
B. Elasticsearch BM25/Nori
C. Elasticsearch hybrid = BM25/Nori + vector
```

통제 조건은 다음과 같다.

```text
같은 query set
같은 chunk_id
같은 chunk_text
같은 embedding_version
같은 top_k
같은 평가 reranker
```

이렇게 해야 결과 차이가 검색 방식 차이인지, chunk나 embedding 차이인지 섞이지 않는다.

## 5. 전체 평가 흐름

```text
사용자 테스트 질문
→ pgvector top_k 검색
→ BM25/Nori top_k 검색
→ hybrid top_k 검색

각 검색 결과는 원래 순서와 raw score를 그대로 저장

→ local reranker 평가 모듈
   input: query + chunk_text
   output: local_reranker_score

→ 검색 방식별 집계
   avg_reranker_score@5
   max_reranker_score@5
   top1_reranker_score
```

중요한 점은 reranker가 검색기 자체를 보정하지 않는다는 것이다.

```text
검색기 raw 결과 보존
공통 평가 점수만 추가
```

## 6. 방식 A와 방식 B의 차이

| 구분 | 방식 A: 평가용 reranker | 방식 B: 검색 개선용 reranker |
|---|---|---|
| 목적 | 검색 방식 비교 | 최종 검색 품질 개선 |
| 결과 순서 변경 | 변경하지 않음 | reranker 점수로 재정렬 |
| A/B 테스트 적합성 | 높음 | 검색기 차이가 흐려질 수 있음 |
| 현재 적용 | 1차 적용 | 후속 검토 |
| 예시 | pgvector top5를 그대로 두고 점수만 매김 | pgvector/BM25/hybrid 후보를 합쳐 다시 top5 선정 |

현재 단계에서는 방식 A가 맞다.

방식 B를 먼저 적용하면 다음 판단이 어려워진다.

```text
pgvector가 잘한 것인지
BM25/Nori가 잘한 것인지
hybrid가 잘한 것인지
reranker가 살린 것인지
```

## 7. 평가 결과 저장 구조

검색기별 raw 결과와 reranker 평가 점수를 함께 저장한다.

```json
{
  "query_id": "q001",
  "query": "차로변경 사고에서 과실비율 판단 판례",
  "retriever": "pgvector",
  "rank": 1,
  "chunk_id": "...",
  "case_id": "...",
  "chunk_type": "main_text",
  "retriever_score": 0.823,
  "reranker_score": 0.91,
  "case_name": "...",
  "chunk_text": "..."
}
```

BM25/Nori 결과도 같은 구조를 사용한다.

```json
{
  "query_id": "q001",
  "retriever": "bm25_nori",
  "rank": 1,
  "retriever_score": 13.72,
  "reranker_score": 0.78
}
```

여기서 비교 기준은 `retriever_score`가 아니라 `reranker_score`다.

```text
retriever_score:
  검색기 내부 점수
  검색기별 의미가 다르므로 직접 비교 금지

reranker_score:
  공통 평가 점수
  검색 방식 A/B 비교에 사용
```

## 8. 집계 지표

1차 집계 지표는 다음 3개를 기본으로 둔다.

| 지표 | 의미 | 보는 이유 |
|---|---|---|
| `avg_reranker_score@5` | top5 전체 reranker 점수 평균 | 검색 결과 목록 전체 품질 |
| `max_reranker_score@5` | top5 중 최고 reranker 점수 | 좋은 근거가 하나라도 들어왔는지 |
| `top1_reranker_score` | 1위 결과의 reranker 점수 | 검색기가 가장 위에 올린 결과의 품질 |

예시 해석은 다음과 같다.

```text
pgvector:
  top1 = 0.82
  avg@5 = 0.58
  max@5 = 0.82

BM25/Nori:
  top1 = 0.74
  avg@5 = 0.61
  max@5 = 0.88

hybrid:
  top1 = 0.91
  avg@5 = 0.73
  max@5 = 0.91
```

이 경우 해석은 다음과 같다.

```text
hybrid는 1위 결과도 좋고 top5 평균도 높다.
BM25/Nori는 top5 안에 좋은 후보가 있지만 1위 정렬은 약할 수 있다.
pgvector는 의미 검색 후보를 찾지만 top5 평균이 낮을 수 있다.
```

## 9. 로컬 기성 reranker 후보

1차 후보는 fine-tuning 없이 사용할 수 있는 다국어 또는 한국어 대응 reranker로 둔다.

| 후보 | 장점 | 한계 | 적용 판단 |
|---|---|---|---|
| `bge-reranker-v2-m3` | 다국어 대응, 검색 평가용으로 사용 사례가 많음 | 모델 다운로드와 로컬 추론 필요 | 1차 후보 |
| 다국어 cross-encoder reranker | query-document 관련성 점수화에 적합 | 모델별 한국어 성능 확인 필요 | 후보 |
| 직접 fine-tuned reranker | 도메인 최적화 가능 | 학습 데이터와 튜닝 비용 필요 | 현 단계 보류 |
| API형 reranker | 서버/GPU 부담 적음 | 외부 API 비용 발생 | 비용 최소화 원칙상 보류 |
| LLM judge | 평가 기준을 자연어로 설명 가능 | 비용과 일관성 관리 부담 | 보조 검토 |

현재 원칙은 다음과 같다.

```text
외부 API 비용을 들이지 않는다.
fine-tuning 없이 시작한다.
검색 결과를 바꾸지 않고 평가 점수만 만든다.
점수가 이상한 샘플은 사람이 일부 검수한다.
```

## 10. 최소 실행 버전

처음부터 전체 query를 크게 돌리지 않는다.

```text
query set:
  10~20개

retriever:
  pgvector
  BM25/Nori
  hybrid

top_k:
  5
```

20개 query 기준 평가 pair 수는 다음과 같다.

```text
20 queries × 3 retrievers × 5 chunks = 300 query-chunk pairs
```

이 정도면 로컬 reranker 속도와 점수 품질을 확인하기에 적당하다.

## 11. 실행 순서

```text
1. pgvector baseline 검색 결과 저장
2. Elasticsearch BM25/Nori 검색 결과 저장
3. Elasticsearch hybrid 검색 결과 저장
4. 세 검색 결과를 같은 포맷으로 합치기
5. local reranker로 query + chunk_text 점수화
6. query별, retriever별 지표 집계
7. 일부 샘플을 사람이 검수
8. 검색 방식 1차 결론 작성
```

## 12. 후속 확장

1차 A/B 평가가 끝난 뒤에만 다음을 검토한다.

```text
1. reranker를 검색 개선용으로 사용
   - 후보 통합
   - reranker 재정렬
   - 최종 top_k 반환

2. LLM judge 병행
   - 사람이 만든 평가 기준을 prompt로 변환
   - local reranker 점수와 비교

3. fine-tuned reranker
   - query-positive-negative 데이터 축적 후 검토
   - 초기 단계에서는 하지 않음
```

## 13. 최종 원칙

```text
지금은 검색 방식을 비교하는 단계다.
따라서 reranker는 검색 개선기가 아니라 평가자로만 둔다.

비용이 들지 않는 로컬 기성 reranker를 먼저 사용한다.
BM25 score, cosine similarity, hybrid score를 직접 비교하지 않는다.
공통 비교는 local_reranker_score로 한다.

검색 방식 비교가 끝난 뒤에
실제 검색 개선용 reranking이나 fine-tuning을 검토한다.
```

---

## 14. 20개 Query Set 확장 및 재실행 절차

### 14.1 목적

이 섹션은 `sample_queries.py`를 20개 query로 확장한 이후, 검색 결과와 리랭커 평가 산출물을 다시 생성하기 위한 실행 절차를 정리한다.

6개 query는 smoke test 성격이었다. 20개 query는 검색 방식 A/B 비교를 조금 더 넓게 보기 위한 1차 평가용 query set이다.

```text
6개 query:
  검색 파이프라인, 리랭커 실행, 보고서 생성 흐름 검증용

20개 query:
  사고 유형과 과실비율 유형을 넓힌 1차 비교 평가용
```

### 14.2 20개 query 구성

`sample_queries.py`는 다음 위치에서 관리한다.

```text
etl/fault_cases/src/traffic_precedents/precedent_search/sample_queries.py
```

현재 구성은 다음과 같다.

```text
traffic: 10개
fault_ratio: 10개
총 20개
```

traffic query는 다음 사고 유형을 포함한다.

```text
1. 차로변경
2. 신호위반
3. 횡단보도 보행자 사고
4. 중앙선 침범
5. 후방추돌
6. 교차로 좌회전/직진 충돌
7. 음주운전
8. 오토바이 사고
9. 자전거 사고
10. 주정차 차량 사고
```

fault_ratio query는 다음 과실비율/손해배상 유형을 포함한다.

```text
1. 차로변경 과실비율
2. 손해배상 과실상계
3. 신호위반 과실비율
4. 횡단보도 보행자 사고 과실상계
5. 후방추돌 과실비율
6. 중앙선 침범 과실비율
7. 교차로 좌회전/직진 과실비율
8. 보행자 무단횡단 과실상계
9. 오토바이 사고 과실비율
10. 자전거 사고 과실상계
```

이 구성의 목적은 특정 검색 방식에만 유리한 query로 평가가 치우치는 것을 줄이는 것이다.

```text
BM25/Nori:
  명시 키워드가 강한 query에서 유리할 수 있음

Vector:
  표현은 다르지만 의미가 가까운 query에서 유리할 수 있음

Hybrid:
  BM25와 vector가 모두 적당히 잡는 query에서 유리할 수 있음
```

### 14.3 전체 재실행 순서

20개 query로 확장한 뒤에는 기존 산출물을 그대로 쓰면 안 된다. query set이 바뀌었기 때문에 4개 retriever 결과부터 다시 생성해야 한다.

전체 순서는 다음과 같다.

```text
1. pgvector 샘플 검색
2. BM25/Nori 샘플 검색
3. Elasticsearch vector 샘플 검색
4. Elasticsearch hybrid 샘플 검색
5. A/B 후보 통합
6. 로컬 reranker 평가
7. 점수표/보고서 생성
8. metadata 보강 context 생성
```

### 14.4 샘플 검색 4종 재생성 명령어

먼저 4개 검색 방식의 sample query 결과를 다시 생성한다.

```powershell
python -B -m etl.fault_cases.src.traffic_precedents.precedent_search.pgvector.run_sample_queries
python -B -m etl.fault_cases.src.traffic_precedents.precedent_search.elasticsearch.run_bm25_sample_queries
python -B -m etl.fault_cases.src.traffic_precedents.precedent_search.elasticsearch.run_vector_sample_queries
python -B -m etl.fault_cases.src.traffic_precedents.precedent_search.elasticsearch.run_hybrid_sample_queries
```

각 명령은 `sample_queries.py`의 query set을 읽어 dataset별 검색 결과 JSON을 갱신한다.

생성 또는 갱신되는 주요 파일은 다음과 같다.

```text
postgres_exports/traffic/traffic_pgvector_sample_queries.json
postgres_exports/fault_ratio/fault_ratio_pgvector_sample_queries.json

elasticsearch_exports/traffic/traffic_elasticsearch_bm25_sample_queries.json
elasticsearch_exports/fault_ratio/fault_ratio_elasticsearch_bm25_sample_queries.json

elasticsearch_exports/traffic/traffic_elasticsearch_vector_sample_queries.json
elasticsearch_exports/fault_ratio/fault_ratio_elasticsearch_vector_sample_queries.json

elasticsearch_exports/traffic/traffic_elasticsearch_hybrid_sample_queries.json
elasticsearch_exports/fault_ratio/fault_ratio_elasticsearch_hybrid_sample_queries.json
```

### 14.5 A/B 후보, 리랭커, 보고서, 보강 context 재생성 명령어

샘플 검색 4종이 끝난 뒤 아래 명령을 순서대로 실행한다.

```powershell
python -B -m etl.fault_cases.src.traffic_precedents.precedent_search.evaluation.export_retrieval_ab_candidates --top-k 5
python -B -m etl.fault_cases.src.traffic_precedents.precedent_search.evaluation.run_local_reranker --model models/bge-reranker-v2-m3 --input-field chunk_text --batch-size 4 --device cpu
python -B -m etl.fault_cases.src.traffic_precedents.precedent_search.evaluation.build_reranker_reports
python -B -m etl.fault_cases.src.traffic_precedents.precedent_search.evaluation.augment_answer_contexts
```

각 단계의 역할은 다음과 같다.

```text
export_retrieval_ab_candidates:
  pgvector / BM25 / ES vector / ES hybrid 결과를 같은 JSONL 스키마로 통합한다.

run_local_reranker:
  통합 후보에 대해 query + chunk_text 기준으로 local_reranker_score를 생성한다.

build_reranker_reports:
  retrieval_ab_score_summary.json, 정량 점수표 MD, 평가 결과 보고서 MD를 생성한다.

augment_answer_contexts:
  metadata winner가 나온 경우 같은 case_id의 holding_summary / main_text / fault_ratio_evidence를 보강한다.
```

### 14.6 예상 후보 수와 실행 시간

20개 query 기준 예상 후보 수는 다음과 같다.

```text
20 queries x 4 retrievers x top5 = 400 candidates
```

기존 6개 query 기준은 다음과 같았다.

```text
6 queries x 4 retrievers x top5 = 120 candidates
```

따라서 20개 query 기준 reranker 평가는 기존보다 약 3.3배 많아진다.

CPU 기준 예상 시간은 다음과 같이 잡는다.

```text
120 candidates:
  약 1~2분

400 candidates:
  약 4~7분
```

실제 시간은 CPU 성능, background process, `batch_size`, 모델 로딩 상태에 따라 달라질 수 있다.

### 14.7 갱신되는 최종 산출물

20개 query 재실행 후 갱신되는 주요 산출물은 다음과 같다.

```text
retrieval_ab_candidates.jsonl
retrieval_ab_summary.json
retrieval_ab_reranker_scores.jsonl
retrieval_ab_score_summary.json
판례 검색 A-B 정량 점수표.md
판례 검색 A-B 평가 결과 보고서.md
retrieval_ab_answer_contexts.jsonl
retrieval_ab_answer_contexts_summary.json
```

각 파일의 역할은 다음과 같다.

```text
retrieval_ab_candidates.jsonl:
  4개 retriever가 가져온 top_k 후보를 같은 포맷으로 모은 원천 평가 후보 파일

retrieval_ab_summary.json:
  query_count, retriever_count, candidate_count, query별 top_k 정렬 상태 요약

retrieval_ab_reranker_scores.jsonl:
  각 후보에 local_reranker_score를 붙인 평가 결과 원본

retrieval_ab_score_summary.json:
  retriever별, dataset별, query별 점수 집계 JSON

판례 검색 A-B 정량 점수표.md:
  사람이 보기 위한 점수표

판례 검색 A-B 평가 결과 보고서.md:
  점수 해석과 운영 판단을 포함한 분석 보고서

retrieval_ab_answer_contexts.jsonl:
  metadata winner에 같은 사건의 본문성 chunk를 붙인 RAG 답변 후보 context

retrieval_ab_answer_contexts_summary.json:
  metadata 보강 결과 요약
```

### 14.8 주의사항

query set을 바꾼 뒤에는 `retrieval_ab_candidates`만 다시 만들면 안 된다.

반드시 아래 순서를 지켜야 한다.

```text
sample_queries.py 변경
→ 4개 retriever sample 검색 재실행
→ retrieval_ab_candidates 재생성
→ reranker 재평가
→ report 재생성
→ answer context 보강 생성
```

그 이유는 다음과 같다.

```text
1. pgvector/BM25/vector/hybrid 결과 JSON이 query set별로 따로 저장되기 때문이다.
2. 후보 통합 파일은 기존 검색 결과 JSON을 읽어 만들기 때문이다.
3. reranker 결과는 후보 통합 파일에 의존한다.
4. 보고서와 보강 context는 reranker 결과에 의존한다.
```

즉 앞 단계가 갱신되지 않으면 뒤 단계 결과도 오래된 query set 기준이 된다.

### 14.9 20개 query 평가 이후 판단 기준

20개 query 평가 후에는 다음을 확인한다.

```text
1. 전체 winner count
2. traffic dataset winner
3. fault_ratio dataset winner
4. query별 winner가 특정 retriever에 치우치는지
5. metadata chunk가 top1으로 과도하게 올라오는지
6. metadata_top1_missing_supplement_count가 0인지
7. BM25/Nori와 hybrid의 차이가 query 유형별로 어떻게 나는지
```

특히 아래 값은 반드시 확인한다.

```text
metadata_top1_missing_supplement_count = 0
```

이 값이 0이면 metadata가 top1으로 나와도 같은 사건의 본문성 chunk 보강이 누락되지 않았다는 뜻이다.

### 14.10 다음 확장 후보

20개 query 평가가 안정적으로 끝나면 다음 확장을 검토한다.

```text
1. query_count = 50 확장
2. RRF k=10/30/60 비교
3. text-embedding-3-large 1536 차원 버전 비교
4. reranker를 평가용이 아니라 실제 검색 개선용으로 적용하는 방식 B 검토
5. 최종 Agent/RAG retriever router 설계
```
