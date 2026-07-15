# Production RAG seed bundle

운영 RAG seed는 대용량 원문을 Git에 넣지 않고, 아래 네 JSONL과 무결성 manifest를 같은 디렉터리 트리에 배치한다.

| role | target | required row fields |
| --- | --- | --- |
| `legal_chunks` | PostgreSQL `law_chunks` | `chunk_id`, `source_id`, `source_name`, `source_type`, `chunk_type`, `provision_text`, `normalized_text`, `source_url`, `enforce_date` |
| `legal_embeddings` | pgvector `law_embeddings` | `chunk_id`, `embedding_provider`, `embedding_model`, `embedding_dimensions=1024`, finite-number·non-zero-norm `embedding_vector` |
| `review_case_chunks` | `review_case_chunks_bm25_nori_v1` | `review_case_id`, `chunk_id`, 50자 이상 `chunk_text` |
| `precedent_fault_ratio_chunks` | `precedent_fault_ratio_chunks_bm25_nori_v1` | `case_id`, `chunk_id`, `chunk_index`, `chunk_type`, `chunk_strategy`, 50자 이상 `chunk_text` |

manifest contract는 `production_rag_seed_manifest.v1`이다. manifest 파일은 bundle root 바로 아래에 두며, 각 artifact는 bundle root 기준 POSIX 상대경로, SHA-256, byte 크기, JSONL row 수를 가진다. 최상위 `embedding_space`에는 검증된 단일 provider/model/dimensions가 기록된다. 절대경로, `..`, 백슬래시, 심볼릭 링크를 통한 bundle 탈출은 거부된다. 네 role은 정확히 한 번씩 있어야 하며, 빈 파일과 중복 `chunk_id`도 거부된다. 법령 chunk와 embedding의 `chunk_id` 집합은 정확히 같아야 한다.

법령 `source_type`은 `law`, `enforcement_decree`, `enforcement_rule`, `administrative_rule`, `notice` 중 하나만 허용한다. `source_url`은 빈 값일 수 없다. `enforce_date`는 실제 존재하는 날짜의 엄격한 `YYYY-MM-DD` 형식이어야 한다. 선택적인 `expire_date`도 같은 형식이며 `enforce_date`보다 빠를 수 없다. embedding은 모든 원소가 finite number여야 하고 1024차원이며 L2 norm이 0보다 커야 한다. 모든 embedding row는 동일한 provider/model/dimensions를 사용해야 한다.

운영 조회에서 `source_type=law`는 위 다섯 종류의 umbrella다. `scope.allowed_source_types`가 있으면 그 목록과 교집합만 검색하며 목록 밖 값은 요청 전체를 거부한다. `temporal_basis.mode=as_of`는 유효한 엄격한 `YYYY-MM-DD` `effective_at`을 요구한다. 조회 시 `enforce_date`가 존재하고 기준일 이하인 row만 허용하며, `expire_date`가 없거나 기준일 이상이어야 한다. Django fallback과 Neo4j 관계·조문 확장에도 동일한 source family·시점 필터를 적용하며, 필터를 통과한 핵심 결과가 없으면 그래프 확장을 실행하지 않는다. 결과의 `summary`는 240자 preview이고, 법령 agent가 사용하는 근거 본문은 별도 `provision_text` 전체 값이다.

## 1. Bundle 구성

예시 디렉터리만 보여 주며 실제 대형 JSONL은 저장소에 커밋하지 않는다.

```text
/srv/skn27/rag-seed-2026-07-14/
  data/legal_chunks.jsonl
  data/legal_embeddings.jsonl
  data/review_case_chunks.jsonl
  data/precedent_fault_ratio_chunks.jsonl
  rag-seed-manifest.json
```

저장소 root에서 manifest를 만든다.

```powershell
python backend/manage.py build_production_rag_seed_manifest `
  --bundle-root C:/secure/rag-seed-2026-07-14 `
  --manifest rag-seed-manifest.json `
  --legal-chunks data/legal_chunks.jsonl `
  --legal-embeddings data/legal_embeddings.jsonl `
  --review-case-chunks data/review_case_chunks.jsonl `
  --precedent-fault-ratio-chunks data/precedent_fault_ratio_chunks.jsonl
```

Linux에서는 같은 옵션을 `/srv/skn27/rag-seed-2026-07-14` bundle root에 사용한다. manifest에 기록되는 artifact 경로는 플랫폼과 관계없이 `/` 구분자를 쓴다.

## 2. 오프라인 검증

이 단계는 PostgreSQL이나 Elasticsearch에 연결하지 않는다.

```bash
python backend/manage.py verify_production_rag_seed_manifest \
  --manifest /srv/skn27/rag-seed-2026-07-14/rag-seed-manifest.json
```

원본 JSONL을 이동하거나 수정한 뒤에는 기존 manifest를 재사용하지 말고 다시 생성한다. 검증부터 load 종료까지 bundle은 운영 host에 읽기 전용으로 mount하고 파일 교체를 금지한다. loader는 외부 쓰기 직전 manifest와 모든 artifact를 다시 검증한다. 내부 SHA만으로 manifest와 artifact를 함께 바꾼 주체의 진위를 판별할 수는 없으므로, 승인된 manifest 파일 자체의 SHA-256을 release metadata나 AWS SSM Parameter Store 같은 별도 신뢰 채널에 기록하고 load 전에 일치 여부를 확인한다.

## 3. 외부 쓰기 없는 load 계획 확인

`--dry-run`은 manifest와 모든 row를 다시 검증하지만 DB/ES client를 만들지 않는다.

```bash
python backend/manage.py load_production_rag_seed \
  --manifest /srv/skn27/rag-seed-2026-07-14/rag-seed-manifest.json \
  --dry-run
```

출력에는 row 수와 target만 포함되고 원문, embedding, DB/ES credential은 포함되지 않는다.

## 4. 운영 주입

먼저 PostgreSQL에 pgvector extension과 `storage/schemas/law_db_schema.sql`을 적용할 권한이 있어야 한다. Elasticsearch에는 Nori analyzer plugin이 설치돼 있어야 한다. 애플리케이션과 동일한 secret store에서 DB/ES 환경변수를 주입한 뒤 실행한다.

기존 pilot의 `law_embeddings` 테이블에는 model/dimensions 컬럼이 없을 수 있다. schema 적용은 두 컬럼을 추가하지만 기존 vector에 값을 추정해 채우지 않는다. 검증된 bundle을 다시 적재하기 전까지 metadata가 NULL인 legacy vector는 exact-space runtime filter에서 검색되지 않는다.

```bash
python backend/manage.py load_production_rag_seed \
  --manifest /srv/skn27/rag-seed-2026-07-14/rag-seed-manifest.json \
  --batch-size 500
```

기본 동작은 법령과 두 ES index 모두 ID 기반 upsert다. 따라서 기존 target에만 있고 새 bundle에는 없는 stale ID는 자동 삭제되지 않는다. 완전한 snapshot 교체가 필요한 경우 승인된 유지보수 시간에만 `--replace-legal --recreate-es`를 명시한다. 법령 JSONL은 `--batch-size` 단위로 스트리밍되어 전체 embedding 파일을 메모리에 올리지 않는다. `--recreate-es`는 두 운영 index를 삭제 후 재생성하므로 서비스 중에는 사용하지 않는다. loader는 PostgreSQL과 Elasticsearch가 보고한 적재 건수가 검증된 artifact row 수와 다르면 실패한다.

load 순서는 법령 pgvector, 심의사례 ES, 과실비율 판례 ES다. 서로 다른 저장소를 하나의 transaction으로 묶을 수 없으므로 중간 실패 시 성공한 앞 단계는 유지된다. 원문을 노출하지 않는 실패 건수만 확인한 뒤 같은 manifest로 재실행하면 upsert로 수렴한다.

환경별 target index는 다음 변수로 맞출 수 있다.

```text
REVIEW_CASE_ES_BM25_INDEX=review_case_chunks_bm25_nori_v1
FAULT_RATIO_PRECEDENT_ES_BM25_INDEX=precedent_fault_ratio_chunks_bm25_nori_v1
```

저비용 AWS 파일럿의 첫 배포는 `.env.production.example`처럼 `LEGAL_RAG_VECTOR_ENABLED=0`을 유지한다. 이때 법률 Agent는 `law_chunks`를 직접 조회하는 PostgreSQL lexical backend를 사용하며 query embedding API를 호출하지 않는다. readiness는 vector가 꺼져 있어도 현재 시점에 검색 가능한 `law_chunks` row가 없으면 실패한다.

Compose의 `data-seed`는 `seed` profile 뒤에 격리된 개발용 전체 ETL 작업이다. 일반 `docker compose up`에서는 실행되지 않으며, 운영 AWS에서는 이 legacy job 대신 승인된 manifest loader를 사용한다. 개발에서 명시적으로 실행할 때도 로컬 sentence-transformers 공간을 사용하므로 OpenAI embedding 비용을 만들지 않는다.

```bash
docker compose --profile seed run --rm data-seed
```

vector를 켤 때는 manifest의 `embedding_space`를 아래 seed 환경변수에 그대로 복사한다. query와 seed provider/model/dimensions가 하나라도 다르면 readiness와 runtime 검색이 fail-closed 한다. runtime은 유효한 동일-space DB row가 있는지 먼저 확인한 뒤에만 query embedding을 생성한다. 운영 readiness는 합성 `hash` provider를 허용하지 않는다.

```text
LEGAL_RAG_SEED_EMBEDDING_PROVIDER=sentence-transformers
LEGAL_RAG_SEED_EMBEDDING_MODEL=intfloat/multilingual-e5-large
LEGAL_RAG_SEED_EMBEDDING_DIMENSIONS=1024
```

sentence-transformers 모델은 프로세스별 한 번만 cache된다. E5-large vector 모드를 켜기 전에는 모델을 image/cache에 미리 준비하고 메모리를 측정하며, 저비용 instance에서는 `WEB_CONCURRENCY=1`부터 검증한다. worker마다 모델 cache가 하나씩 생기므로 기본 worker 수를 그대로 둔 채 vector를 켜면 안 된다.

실행 후 연결 여부만이 아니라 실제 근거 결과를 요구하는 smoke를 실행한다.

```bash
python backend/manage.py smoke_text_ml_case_search --require-es --require-results
python backend/manage.py smoke_law_ground_search --require-results
```

## Fail-closed production contracts

- Legal chunk identifiers and metadata must fit the PostgreSQL `VARCHAR` limits, and `source_url` must be an absolute HTTPS URL on a non-placeholder, non-loopback host.
- Production embeddings accept only `sentence-transformers` or `openai`. Every coordinate must remain finite in IEEE-754 float32 and the converted vector must not be all zero.
- Review-case and fault-ratio Elasticsearch indexes must be non-empty, distinct, lowercase, valid Elasticsearch names of at most 255 UTF-8 bytes.
- Readiness and every legal retrieval backend require nonblank `source_url` and `provision_text`; vector paths also require a non-NULL stored vector before creating a query embedding.
- The manifest verifies required field contracts. Elasticsearch mapping/plugin compatibility for optional source fields remains a staging load gate, followed by both result-required smoke commands above.

seed bundle 자체에는 mock 또는 heuristic fallback 데이터가 들어가면 안 된다.
