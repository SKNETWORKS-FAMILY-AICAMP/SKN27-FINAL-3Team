# storage

DB, RAG, migration, 개발용 저장소 실행 환경, 저장소 계약을 관리하는 공간이다.

## 하위 폴더 역할

| 폴더 | 역할 |
|---|---|
| `docker/` | 개발용 DB, vector store, 검색 엔진 실행 환경 파일을 둔다. |
| `schemas/` | DB table, document store, registry schema 문서 또는 schema 파일을 둔다. |
| `migrations/` | DB 변경 이력과 migration 파일을 둔다. |
| `rag/` | chunk, embedding, evidence metadata, RAG 저장 계약을 둔다. |
| `samples/` | 비식별화된 샘플 manifest와 작은 fixture만 둔다. |

## 배치 원칙

- 데이터 수집과 전처리 코드는 `etl/`에 둔다.
- Agent 내부 판단 로직은 `ai/`에 둔다.
- 원본 고지서, 원본 영상, 개인정보 포함 파일은 직접 커밋하지 않는다.
- 저장소 계약은 특정 Agent 구현보다 안정적으로 유지한다.
