# ES·lexical 제거 및 law·review_case pgvector 단일화 설계

**Issue:** #291  
**Branch:** `feat-291-pgvector-only-rag`  
**Updated:** 2026-07-23

## 목표

활성 검색·배포 경로에서 Elasticsearch, Kibana, OpenSearch, BM25/Nori,
`postgres_lexical`, `django_rag_tables` fallback을 제거한다. `law`와
`review_case`는 PostgreSQL/pgvector만 사용하고 동일한 임베딩 공간을 공유한다.

## 범위

- `law`와 `review_case`의 기준은 `openai / text-embedding-3-large / 1024`다.
  법령의 검증 완료 공간을 기준으로 review-case를 재임베딩한다.
- 법령 검색은 `ready`, `empty`, `unavailable`,
  `embedding_space_mismatch` 상태를 유지하며 다른 backend로 fallback하지 않는다.
- review-case loader, query embedder, schema, HNSW partial index와 readiness는
  동일한 provider/model/dimensions를 강제한다.
- fault-ratio precedent는 공통 임베딩 공간 통합 대상이 아니다. 기존 pgvector
  동작은 보존하고, ES 제거에 필요한 호출부만 정리한다.
- 실제 DB 재임베딩, Terraform apply/destroy, OpenSearch 삭제는 운영 runbook
  단계이며 코드 PR에서 실행하지 않는다.

## 임베딩 계약

공통 설정은 아래 값이다.

```text
RAG_EMBEDDING_PROVIDER=openai
RAG_EMBEDDING_MODEL=text-embedding-3-large
RAG_EMBEDDING_DIMENSIONS=1024
```

법령 query/seed와 review-case embedding/query는 이 공통 설정을 읽는다.
기존 `LEGAL_RAG_*`와 `OPENAI_EMBEDDING_*` 키는 전환 기간 호환 입력으로만
허용하되, 공통 설정과 값이 다르면 readiness를 실패시킨다.

`review_case_chunk_embeddings.embedding_vector`는 `vector(1024)`이며
`embedding_dim = 1024` check를 갖는다. 기존 1536차원 행은 백업 후 운영
마이그레이션에서 제거하고 1024차원으로 재생성한다.

## 검색 및 오류 처리

- 법령과 review-case는 각각 자신의 DB에서 cosine pgvector 검색을 수행한다.
- query vector 길이와 저장 metadata가 1024 계약과 다르면 SQL을 실행하지 않고
  `embedding_space_mismatch`로 종료한다.
- 빈 결과는 `empty`, 연결·API·index 오류는 `unavailable`이다.
- ES나 lexical 결과로 빈 결과·장애를 숨기지 않는다.

## 배포 및 데이터 전환

1. law/review-case DB와 기존 검색 인프라 설정을 백업한다.
2. review-case embedding column을 1024차원으로 전환한다.
3. review-case 전체를 `text-embedding-3-large`, 1024차원으로 재임베딩한다.
4. HNSW index를 재생성한다.
5. law/review-case readiness와 대표 질의, p50/p95를 검증한다.
6. 애플리케이션·배포 정의에서 ES/OpenSearch를 제거한다.
7. 관찰 기간 후 외부 검색 리소스를 별도 승인 절차로 삭제한다.

## 검증

- 법령과 review-case가 동일 provider/model/dimensions를 보고한다.
- 두 도메인의 chunk/embedding count와 HNSW index가 준비 상태다.
- 대표 질의가 ES/lexical 없이 결과를 반환한다.
- 전체 테스트는 Python 3.13에서 실행한다.
- 실제 latency는 운영 데이터가 준비된 실행에서만 기록하며 추정값을 쓰지 않는다.

## 체크리스트 반영

`docs/ops/project-readiness-master-checklist.md` C-1에서 다음만 #291 증적으로
완료 처리한다.

- ES/lexical 제거와 pgvector-only 운영 경계
- law/review_case 동일 임베딩 공간, readiness, 대표 질의·지연 증적

다음 항목은 별도 작업이므로 미완료로 유지한다.

- 대표 사고 시나리오별 정확도 평가 세트
- 사용자 표시용 출처·검색 시점·한계
- 유사도 점수만으로 결론 내리지 않는 근거 검토 기준
