# pgvector 법령 RAG 전환 게이트 해소 설계

## 목표

법령 RAG pgvector의 HNSW 사후 필터링으로 발생한 빈 결과를 없애고, OpenAI query embedding부터 결과 매핑까지의 **전체** 검색 지연을 측정·개선한다. 완료 판정은 기존 계약을 유지한다. 즉 pgvector는 no-result rate `0`, 전체 p95 latency `1,413 ms` 이하, 공개 법령 20개 질의의 RAGAS `20/20` 평가와 aggregate 생성이 모두 충족되어야만 `transition_decision.eligible=true`가 될 수 있다.

## 확인된 증적과 원인 가설

`legal-ab-016-ragas-20260722`에서 pgvector는 20개 중 18개 `ready`, `law-q006`과 `law-q010` 두 개는 오류 없이 `empty`였다. 동일 `law` scope·기준일·embedding space에서 실제 검색 가능한 row는 97,394개 embedding 중 1,219개(약 1.25%)였다.

현재 `_query_pgvector_rows()`는 HNSW `ORDER BY embedding_vector <=> query_vector`와 법령 유효성·출처 필터를 한 SQL에 둔다. pgvector HNSW는 근사 후보를 우선 탐색하고 필터를 후적용하므로, 낮은 선택도의 조건에서 기본 후보 집합이 `top_k`를 채우지 못할 수 있다. 이는 [pgvector HNSW filtering 문서](https://github.com/pgvector/pgvector#filtering)의 동작과 일치한다. 실제 DB는 vector extension `0.8.2`와 `law_embeddings_hnsw_idx`를 사용한다.

전체 p95는 embedding API 호출도 포함한다. 현재 `_openai_embedding()`은 질의마다 새 `OpenAI` client를 만들어 연결 재사용이 없다. 따라서 빈 결과 해결과 별개로, client 재사용과 구간별 측정 없이는 전체 p95 원인을 판별하거나 gate 통과를 주장할 수 없다.

## 범위와 비범위

- 대상은 `law` source family의 PostgreSQL `law_chunks`·`law_embeddings` 검색 경로와 공개 법령 평가 도구다.
- 검색 순서, lexical fallback, Django RAG fallback, embedding provider/model/dimension 일치 검증, RAGAS 완전성 계약은 유지한다.
- pgvector 서버의 전역 설정, index DDL, seed 데이터, corpus snapshot은 변경하지 않는다.
- 판례·심의사례·과실기준·Elasticsearch·Neo4j 범위로 확장하지 않는다.
- 키, 원문 질의·답변·context, 예외 전문을 응답·artifact·보고서에 추가하지 않는다.

## 설계 결정

### 1. 요청 단위 HNSW iterative scan

`_query_pgvector_rows()`는 vector SELECT와 같은 DB transaction 안에서 다음 session-local 설정을 먼저 적용한다.

```sql
SET LOCAL hnsw.ef_search = 400;
SET LOCAL hnsw.iterative_scan = 'strict_order';
```

`ef_search=400`은 관측된 약 1.25% 필터 통과율에서 top-5 후보를 얻기 위한 초기 탐색 규모다. `strict_order` iterative scan은 초기 후보만으로 법령 필터를 통과한 결과가 부족할 때 추가 탐색하며, 반환 순서는 거리 순서를 유지한다. `SET LOCAL`을 사용하므로 DB 인스턴스나 다른 요청의 설정을 변경하지 않는다.

검색 SQL의 법령 source·시행일·폐지일·출처 URL·조문 본문·embedding space filter는 제거하거나 완화하지 않는다. iterative scan이 지원되지 않거나 설정·조회가 실패하면 기존 예외 계약에 따라 pgvector 응답은 안전한 `unavailable` reason code가 되며, lexical fallback을 유지한다. 빈 vector 결과를 lexical 결과로 위장하지 않는다.

### 2. OpenAI embedding client 재사용

새 내부 helper `_openai_embedding_client()`를 프로세스 단위로 캐시한다. 최초 호출에서 현재 API key, timeout, 고정 OpenAI base URL로 client를 만들고 이후 embedding 요청은 같은 client의 connection pool을 재사용한다.

- embedding 요청의 model, dimensions, input, L2 normalization은 현재와 동일하다.
- API key는 응답·테스트 assertion·로그·artifact에 포함하지 않는다.
- 환경 변수 변경은 기존 프로세스 재시작 규칙을 따른다. 테스트는 cache를 명시적으로 비운 뒤 독립적으로 실행한다.

### 3. 안전한 전체·구간별 latency 증적

pgvector 응답에는 기존 전체 `latency_ms`와 함께 다음 정수형 `latency_breakdown_ms`를 추가한다.

```json
{
  "preflight_ms": 0,
  "embedding_ms": 0,
  "vector_query_ms": 0,
  "result_mapping_ms": 0
}
```

- `preflight_ms`: embedding space, DB/table, eligible seed 검증 시간
- `embedding_ms`: query embedding API 호출과 vector normalization 시간
- `vector_query_ms`: HNSW 설정과 SQL 실행·row fetch 시간
- `result_mapping_ms`: DB row를 public result metadata로 변환하는 시간

모든 값은 음수가 아닌 밀리초 정수다. 예외로 중단된 뒤의 미실행 phase는 `0`이며, 이미 끝난 phase만 기록한다. 전체 `latency_ms`는 계속 요청 시작부터 응답 생성까지의 시간이고 transition gate의 유일한 latency 입력이다.

`evaluation.normalize_backend_response()`는 위 네 key만 whitelist하여 후보 artifact로 보존하고, 임의 key·원문·비밀값은 버린다. backend summary에는 각 phase의 count, p50, p95, mean을 별도 `latency_breakdown_ms` 집계로 기록한다. 이 보조 집계는 병목 판단용이며 기존 전체 p50/p95와 gate 계산을 대체하지 않는다.

## 데이터 흐름

1. 공개 법령 query와 동일한 temporal/scope filter를 lexical·pgvector에 전달한다.
2. pgvector preflight가 DB와 embedding space의 fail-closed 계약을 검증하고 시간을 기록한다.
3. 재사용 OpenAI client가 query embedding을 만들고 시간을 기록한다.
4. transaction-local HNSW 설정 후 strict-order iterative vector query를 실행하고 시간을 기록한다.
5. 결과를 public citation metadata로 정규화하고 시간을 기록한다.
6. evaluator는 전체 latency와 whitelist된 phase latency만 `candidates.json`과 `summary.json`에 기록한다.
7. RAGAS는 context가 있는 20개 pgvector record에만 실행하며, 하나라도 누락되면 aggregate를 만들지 않는 현재 계약을 유지한다.

## 테스트와 검증

### 단위·회귀 테스트

- pgvector query cursor가 vector SELECT보다 먼저 두 `SET LOCAL` 문을 실행하는지 검증한다.
- strict-order HNSW 설정이 기존 SQL filter와 embedding space predicate를 제거하지 않는지 검증한다.
- OpenAI client factory가 같은 프로세스 설정에서 한 번만 생성되고, embedding 요청의 model·dimensions·정규화 결과를 유지하는지 검증한다.
- 정상·empty·unavailable response 각각에서 phase latency가 안전한 네 정수 key만 갖고, 음수·임의 key·비밀 문자열을 artifact에 내보내지 않는지 검증한다.
- backend summary가 phase별 count/p50/p95/mean을 계산하고, 기존 전체 p50/p95 및 `transition_decision()`의 gate가 변하지 않는지 검증한다.
- 기존 legal evaluation, environment, service 회귀 테스트를 모두 실행한다.

### 실제 실행 검증

1. Python 3.13 전용 평가 환경의 `pip check`와 preflight를 확인한다.
2. 같은 corpus snapshot과 공개 법령 20개 질의로 PostgreSQL lexical ↔ pgvector A/B를 실행한다.
3. `law-q006`, `law-q010` 포함 pgvector 20/20이 `ready`인지, no-result rate가 `0`인지 확인한다.
4. 전체 pgvector p95가 `1,413 ms` 이하인지 확인하고, phase p50/p95/mean으로 병목을 함께 보고한다.
5. 같은 run의 pgvector RAGAS가 20/20 평가되고 aggregate 네 metric을 생성하는지 확인한다.
6. 전환 조건이 하나라도 실패하면 `eligible=false`와 lexical 우선 경로를 유지하고, 수치와 failed gate를 보고서·C-1에 기록한다.

## 산출물

- 코드와 회귀 테스트
- `docs/tech-validation-reports/legal-rag/2026-07-22-legal-rag-ab-execution-report.md`의 #289 실행 업데이트
- `docs/ops/project-readiness-master-checklist.md` C-1 상태 및 증적 링크
- 로컬 ignored evaluation artifact (`candidates.json`, `summary.json`, RAGAS 결과); artifact와 `.env.rag-eval`은 Git에 넣지 않는다.
