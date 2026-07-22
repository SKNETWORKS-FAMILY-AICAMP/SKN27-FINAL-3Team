# Elasticsearch·Lexical 제거 및 pgvector 단일 검색 설계

**Issue:** #291  
**Branch:** `feat-291-pgvector-only-rag`  
**Date:** 2026-07-22

## 1. 목표와 결정

프로젝트의 활성 검색·적재·배포 경로에서 Elasticsearch, Kibana, BM25/Nori와 PostgreSQL lexical/Django token-coverage fallback을 제거한다. 법령, 심의사례(`review_case`), 과실비율 판례(`fault_ratio_precedent`)는 각자의 PostgreSQL pgvector 테이블과 HNSW 인덱스만 사용한다.

이 설계는 과거 실험 보고서 안의 Elasticsearch 언급을 삭제하지 않는다. 보고서는 검증 이력이며 실행 경로나 운영 지침은 아니다. 반면 실행 코드, 배포 구성, 의존성, 환경 변수, seed loader, DB의 ES 전용 메타데이터는 제거 대상이다.

## 2. 현재 구조와 전환 대상

| 도메인 | 현재 활성 또는 fallback 경로 | 전환 후 |
| --- | --- | --- |
| 법령 | `postgres_pgvector -> postgres_lexical -> django_rag_tables` | `postgres_pgvector` 단일 |
| 심의사례 | ES BM25/Nori 또는 Django `RagChunk` token coverage | `review_case_chunk_embeddings` pgvector 단일 |
| 과실비율 판례 | ES BM25/Nori | `fault_ratio_precedent_chunk_embeddings` pgvector 단일 |

이미 존재하는 `etl/fault_cases/src/review_case/search/pgvector/`와 `etl/fault_cases/src/traffic_precedents/precedent_search/pgvector/`를 재사용한다. 새 검색 엔진이나 lexical 대체 인덱스는 만들지 않는다.

## 3. 런타임 설계

### 3.1 법령 검색

`app/services/legal_rag_service.py`의 `search_legal_rag()`는 `_search_pgvector()`을 한 번만 호출한다. 성공하면 `ready`, 매칭이 없으면 `empty`, DB·임베딩·설정 오류면 `unavailable`을 반환한다. `postgres_lexical`, `django_rag_tables`, `attempted_backends`, `fallback_from`은 반환 계약에서 제거한다.

법령은 `law_chunks`와 `law_embeddings`의 1024차원 공간을 유지한다. 쿼리 provider/model/dimensions와 적재된 embedding metadata가 일치하지 않으면 벡터 질의를 실행하지 않고 `embedding_space_mismatch`로 실패 종료한다.

### 3.2 심의사례·과실비율 판례 검색

`text_ml_case_search`는 ES client를 받지 않는다. 입력 정규화와 source-quota 병합은 유지하고, 선택된 질의 문자열을 다음 두 pgvector 검색기에 전달한다.

1. `review_case_chunk_embeddings`의 cosine pgvector 검색
2. `fault_ratio_precedent_chunk_embeddings`의 cosine pgvector 검색

두 검색 결과는 기존 evidence mapper·validator·source quota 병합 규칙을 사용해 기존 Agent 출력 구조를 유지한다. `retriever` 값은 `unified_pgvector`로 바꾸고 source별 값은 `review_case_pgvector`, `fault_ratio_precedent_pgvector`으로 명확히 기록한다. 한 source가 실패해도 다른 source의 정상 evidence는 반환하고, 결과 상태는 `partial`로 유지한다.

### 3.3 임베딩 재생성

임베딩은 모든 도메인을 하나의 차원으로 강제하지 않는다. 각 테이블은 이미 다른 차원을 가진다(법령 1024, 심의사례·판례 1536). 대신 각 도메인에서 다음 세 값이 적재 데이터와 질의 설정에 정확히 일치해야 한다.

- provider
- model
- dimensions

법령은 기존 loader의 `--replace`로 `law_chunks`/`law_embeddings`를 원자적으로 교체한다. 심의사례와 과실비율 판례는 기존 embedding loader와 HNSW index creator를 사용해 해당 embedding 테이블을 재생성하고 인덱스를 만든다. 적재 수, vector 수, HNSW index 존재 여부, 대표 질의 결과를 모두 확인한 뒤에만 ES 제거 배포를 통과시킨다.

## 4. 구성·적재·스키마 정리

다음 활성 자산을 제거한다.

- `docker-compose.yml`의 Elasticsearch/Kibana 서비스·healthcheck·volume
- `deploy/aws-pilot/`의 ES env file, ES 변수, ES를 전제로 한 deploy/rollback/seed 절차
- `.env.production.example` 및 runtime example의 ES 설정
- `requirements.txt`의 `elasticsearch` 의존성
- `infra/elasticsearch/` 이미지 정의
- `backend/chatbot/readiness.py`, production seed loader, smoke command의 ES 조건
- ES 전용 ETL indexer/retriever/sample-query/test 모듈

`review_case_db_schema.sql`와 `precedent_db_schema.sql`에서 ES 전용 컬럼과 index-job 테이블을 제거한다. 이미 생성된 DB에는 별도 idempotent SQL migration으로 같은 컬럼·테이블을 제거한다. 이 migration은 운영 DB에 적용하기 전 백업과 re-embedding 검증이 완료되어야 한다.

## 5. 오류 처리와 운영 안전성

- 질의 임베딩 생성 실패, DB 연결 실패, embedding-space mismatch는 결과를 꾸며내지 않고 `unavailable` 또는 source별 실패로 반환한다.
- 심의사례 또는 과실비율 판례 한 도메인의 실패는 다른 도메인의 evidence를 차단하지 않는다.
- ES가 없다는 사실을 fallback limitation으로 노출하지 않는다. 대신 `pgvector_unavailable`, `embedding_space_mismatch`, `no_eligible_seed_embeddings` 같은 실제 원인을 기록한다.
- 배포 순서는 `재임베딩 및 HNSW 생성 -> pgvector smoke/회귀 검증 -> ES 코드·배포 제거 -> 운영 지표 확인 -> ES 데이터 볼륨 물리 정리`로 한다. 마지막 단계는 배포 운영자가 수행한다.

## 6. 검증 기준

### 자동 테스트

- 법령 pgvector 검색의 `ready`, `empty`, `unavailable`, embedding-space mismatch 계약
- 법령 검색에서 lexical/Django fallback이 호출되지 않는 회귀 테스트
- 심의사례·과실비율 판례의 pgvector 결과를 기존 evidence 계약으로 매핑하는 단위 테스트
- 한 source의 pgvector 장애에서 다른 source evidence와 `partial` 상태를 보존하는 테스트
- production seed loader와 readiness/smoke command가 ES 패키지·환경 변수 없이 동작하는 테스트
- Compose·pilot 배포 파일과 requirements에 ES/Kibana 의존성이 없는 계약 테스트

### 실제 데이터 검증

- 법령, 심의사례, 과실비율 판례별 chunk 수와 embedding 수 일치
- 각 도메인의 provider/model/dimensions 일치
- HNSW 인덱스 존재
- 대표 질의에서 결과 수, `unavailable` 비율, p50/p95 latency 기록
- 법령은 기존 전환 기준(p95 589 ms 이하 검증 증적)을 보존하고, 심의사례·과실비율 판례는 별도 실제 실행 결과를 새 보고서에 추가

## 7. 완료 기준과 체크리스트

이 이슈가 완료되면 C-1의 `Elasticsearch의 역할과 pgvector/Neo4j/Elasticsearch 선택 조건 문서화` 항목은 ES 퇴역 및 PostgreSQL/pgvector·Neo4j 기준으로 완료 처리한다.

다만 C-1 전체 완료에는 대표 사고 시나리오 평가 세트, 출처·검색 시점·한계 표시, 근거 검토 기준이 별도로 남는다. 이 이슈는 그 세 항목을 완료로 표시하지 않는다.
