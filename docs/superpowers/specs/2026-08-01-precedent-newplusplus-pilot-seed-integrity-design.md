# Precedent NEW++ Pilot Seed Integrity Design

## 1. 목적

파일럿의 기존 PostgreSQL RDS `law_db` 안에 판례 NEW++ 고정 bootstrap을
provider 호출 없이 적재하고, 검증된 seed만 원자적으로 활성화하며, 직전 seed로
복구할 수 있는 운영 계약을 추가한다.

이번 설계의 완료 조건은 다음과 같다.

- 활성 판례 corpus가 정확히 `3,339 blocks / 825 cases / 2,560 dimensions`이다.
- 입력 NPY와 metadata의 고정 SHA-256이 기존 bootstrap 계약과 일치한다.
- 적재 실패 또는 count/dimension 불일치가 현재 활성 corpus를 변경하지 않는다.
- runtime app role은 판례 schema를 읽을 수만 있고 seed row를 수정할 수 없다.
- readiness가 실제 활성 seed version과 runtime 기대 version을 대조한다.
- 유료 API 또는 문서 재임베딩을 실행하지 않는다.
- 운영 재배포 후 기존 13개 E2E gate를 그대로 수행한다.

## 2. 확인된 현재 상태

- 파일럿은 RDS 인스턴스 하나와 database `law_db` 하나를 사용한다.
- app role은 현재 `public` schema의 SELECT/INSERT/UPDATE/DELETE 권한을 가진다.
- NEW++ 검색 코드는 `precedent_newplusplus.blocks`를 읽지만 파일럿 배포에는
  schema, DSN fallback, bootstrap 적재 단계가 연결되어 있지 않다.
- 저장소에는 다음 immutable bootstrap 파일이 Git으로 추적되어 있고 backend
  image의 `COPY etl ./etl` 단계에 포함된다.
  - `01_document_embeddings_qwen3_4b.npy`: 42,854,528 bytes
  - `02_document_embedding_metadata.jsonl`: 14,396,918 bytes
- 기존 loader는 두 파일의 SHA-256, 선택 row, 등급, 차원, dtype, finite 값을
  provider 호출 전에 검증할 수 있다.
- 기존 seed manifest의 `precedent_fault_ratio_chunks` 343행은 현재 NEW++
  `3,339` block corpus와 같은 배포 단위가 아니다. 두 corpus를 합치거나 343행을
  NEW++ 대체물로 취급하지 않는다.

## 3. 검토한 방식

### 선택안 A — 기존 `law_db`의 전용 schema 사용

`precedent_newplusplus` schema에 versioned seed tables와 runtime view를 둔다.
기존 RDS와 secret을 재사용하면서 public schema와 권한을 분리할 수 있다.

### 선택안 B — `public` schema에 직접 적재

구현은 짧지만 기존 app role의 광범위한 쓰기 권한과 섞이며, 판례 seed의
읽기 전용 경계를 보장하기 어렵다.

### 선택안 C — 별도 RDS 또는 database 생성

격리는 가장 강하지만 Terraform, secret, 백업, 모니터, 비용, 장애 복구 범위가
증가한다. 현재 3,339 block 고정 corpus에는 과도하다.

### 결정

선택안 A를 사용한다. 사용자가 2026-08-01 승인한 방향이며, 추가 인프라 비용 없이
데이터·권한·rollback 경계를 가장 명확하게 유지한다.

## 4. 데이터 모델

### `precedent_newplusplus.seed_releases`

검증된 seed identity와 입력 증거를 보존한다.

- `seed_version TEXT PRIMARY KEY`
- `source_npy_sha256 CHAR(64) NOT NULL`
- `source_metadata_sha256 CHAR(64) NOT NULL`
- `model_id TEXT NOT NULL`
- `model_revision TEXT NOT NULL`
- `block_count INTEGER NOT NULL CHECK (block_count = 3339)`
- `case_count INTEGER NOT NULL CHECK (case_count = 825)`
- `embedding_dimension INTEGER NOT NULL CHECK (embedding_dimension = 2560)`
- `status TEXT NOT NULL CHECK (status IN ('staged', 'active', 'previous'))`
- `verified_at TIMESTAMPTZ NOT NULL`

`seed_version`은 contract version, 두 source SHA-256, model ID/revision,
3,339/825/2,560 값을 key-sort한 canonical JSON의 SHA-256으로 계산한다.
동일 입력은 항상 동일 version을 만든다.

### `precedent_newplusplus.block_versions`

기존 NEW++ runtime row에 `seed_version`을 추가한 immutable row 집합이다.

- primary key: `(seed_version, block_id)`
- foreign key: `seed_version -> seed_releases.seed_version`
- runtime 필드: `record_id`, `block_type`, `semantic_role`, `block_text`,
  사건 metadata, `internal_grade`, `source_metadata`, `embedding vector(2560)`
- index: `(seed_version, record_id)`, `(seed_version, block_type, record_id)`

app role에는 INSERT/UPDATE/DELETE 권한을 부여하지 않는다.

### `precedent_newplusplus.active_seed`

singleton row 하나로 원자적 활성화와 rollback pointer를 관리한다.

- `singleton BOOLEAN PRIMARY KEY CHECK (singleton)`
- `active_seed_version TEXT NOT NULL`
- `previous_seed_version TEXT NULL`
- `updated_at TIMESTAMPTZ NOT NULL`

### `precedent_newplusplus.blocks`

기존 runtime SQL을 유지하기 위한 read-only view이다.

`active_seed.active_seed_version`과 일치하는 `block_versions` row만 노출한다.
현재 candidate/context query는 수정 없이 이 view를 조회한다. 기존 검증 설계대로
3,339개 vector를 exact cosine scan하며 이번 핫픽스에서 검색 알고리즘이나
reranker를 변경하지 않는다.

## 5. 연결과 권한

- runtime은 새 secret을 만들지 않고 기존 `POSTGRES_HOST`, `POSTGRES_PORT`,
  `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `PGSSLMODE`를 사용한다.
- `PRECEDENT_NEWPLUSPLUS_DSN`이 명시된 비파일럿 환경에서는 기존 우선순위를
  유지한다.
- DSN이 없으면 NEW++ connection helper가 기존 POSTGRES 환경 변수로 연결한다.
- maintenance master role만 schema 생성, seed 적재, promotion, rollback을 수행한다.
- app role에는 다음 권한만 부여한다.
  - `GRANT USAGE ON SCHEMA precedent_newplusplus`
  - `GRANT SELECT ON precedent_newplusplus.blocks`
  - readiness에 필요한 `seed_releases`, `active_seed` SELECT
- app role의 판례 schema 쓰기 권한은 테스트와 운영 preflight에서 0건임을
  확인한다.

## 6. 적재·promotion 흐름

1. backend image 안의 고정 NPY와 metadata 경로를 resolve한다.
2. DB transaction 밖에서 기존 `load_bootstrap_pair` 검증을 모두 수행한다.
3. deterministic `seed_version`을 계산한다.
4. master connection에서 transaction-scoped advisory lock을 획득한다.
5. 같은 version이 이미 정확히 staged/active이면 idempotent reuse로 종료한다.
6. 새 version의 3,339 rows를 `block_versions`에 적재한다.
7. transaction 안에서 block count, distinct case count, min/max dimension,
   허용 grade를 다시 조회한다.
8. exact 검증을 통과한 version만 `staged`로 기록한다.
9. promotion transaction이 기존 active를 `previous`, staged를 `active`로 바꾸고
   singleton pointer를 한 번에 갱신한다.
10. promotion 후 별도 connection으로 readiness를 재조회한다.

단계 2~8 실패 시 active pointer는 변경되지 않는다. 단계 9가 실패하면 pointer와
release status 변경 전체가 rollback된다.

## 7. rollback 흐름

- rollback 명령은 호출자가 제공한 `expected_active_seed_version`과 DB의 active가
  정확히 일치할 때만 실행한다.
- `previous_seed_version`이 없으면 fail-closed로 종료하며 active를 비우지 않는다.
- advisory lock과 단일 transaction 안에서 active/previous pointer와 release
  status를 서로 교환한다.
- transaction 이후 readiness가 3,339/825/2,560과 rollback target version을
  만족해야 성공이다.
- 현재 bootstrap과 동일 version을 재적재하는 동작은 rollback으로 간주하지 않고
  idempotent reuse로 기록한다.
- app image rollback은 release-independent seed pointer를 자동 변경하지 않는다.
  seed promotion 자체가 장애 원인으로 확인된 경우에만 별도 maintenance rollback
  명령을 실행한다.

## 8. management command 계약

다음 command를 분리해 destructive action을 명확히 한다.

- `stage_precedent_newplusplus_seed`
  - 고정 파일 또는 명시 경로를 검증하고 versioned rows를 staged 상태로 적재
  - `--format json`
  - provider 관련 option 없음
- `promote_precedent_newplusplus_seed`
  - 필수 `--seed-version`, `--expected-active-seed-version`
  - 최초 promotion은 expected 값을 `none`으로 명시
- `rollback_precedent_newplusplus_seed`
  - 필수 `--expected-active-seed-version`
- `verify_precedent_newplusplus_seed`
  - read-only
  - expected version, counts, dimensions, model identity를 확인

각 JSON 결과는 credential, DSN, host, user를 포함하지 않는다.

## 9. 파일럿 배포 연결

### `Maintain-PilotDatabase.ps1`

기존 maintenance profile과 master secret 경계 안에서 다음 순서를 사용한다.

1. pgvector extension 확인
2. Django migration과 review-case schema 적용
3. NEW++ versioned schema 적용
4. provider-free bootstrap stage
5. staged exact verification
6. explicit initial/replacement promotion
7. promotion 후 DB active version 재검증
8. SSM runtime parameter의 `PRECEDENT_NEWPLUSPLUS_SEED_VERSION`을 active
   version으로 갱신하고 read-back 검증
9. app role read-only grant
10. app credential을 사용한 read-only readiness
11. maintenance marker 제거와 runtime IAM profile 복원

provider 호출 명령, `precedent_embedding.build_embeddings`, model download 명령은
이 스크립트에 포함하지 않는다.

### runtime env와 readiness

- `PRECEDENT_NEWPLUSPLUS_SEED_VERSION`을 필수 runtime evidence 값으로 기록한다.
- `_verify_fault_ratio_precedent`는 active seed version, 3,339 blocks, 825 cases,
  2,560 dimensions를 확인한다.
- runtime expected version과 DB active version이 다르면
  `fault_ratio_precedent_seed_version_mismatch`로 fail한다.
- `verify_pgvector_rag_readiness`는 fault-ratio를 required domain으로 유지한다.

### release gate

- NEW++ readiness가 fail이면 legal seed marker, operational descriptor,
  candidate promotion을 허용하지 않는다.
- NEW++ seed version은 release evidence와 배포 기록에 포함한다.
- 기존 97,394 legal seed rollback 상태는 NEW++ bootstrap 준비와 독립적으로
  유지한다.

## 10. 오류 처리

- source SHA 불일치: DB write 전 실패
- 3,339/825/2,560 불일치: staged transaction rollback
- 중복 block ID 또는 허용되지 않은 grade: staged transaction rollback
- advisory lock timeout: 현재 active를 유지하고 실패
- expected active mismatch: promotion/rollback 거부
- app role write privilege 발견: maintenance gate 실패
- runtime expected version mismatch: readiness fail, release 중단
- DB promotion 후 SSM version 갱신 실패: active DB는 보존하되 descriptor 생성과
  app release를 차단하고 같은 version의 evidence sync만 재시도
- previous version 없음: rollback 거부, active 유지

seed rollback은 DB pointer swap 검증 후 SSM expected version도 rollback target으로
갱신하고 read-back한다. SSM 갱신 전에는 release descriptor를 재생성하지 않는다.

로그에는 파일 경로, SHA-256, version, counts, error code만 남기고 credential과
DSN은 남기지 않는다.

## 11. 테스트 전략

### 단위 테스트

- deterministic seed version
- source 검증 후에만 DB transaction 진입
- exact counts와 dimension 불일치 거부
- same-version idempotent reuse
- promotion expected-active compare-and-swap
- previous 없음 rollback 거부
- rollback pointer swap
- DSN 우선순위와 POSTGRES fallback
- readiness expected/actual version 일치와 불일치

### schema·권한 계약

- versioned tables, singleton constraint, read-only view 존재
- app role grant에 INSERT/UPDATE/DELETE 없음
- 기존 public schema grant와 판례 schema grant 분리

### 배포 계약

- maintenance 순서가 schema → stage → verify → promote → grant → runtime verify
- bootstrap 경로가 backend image에 존재
- paid/provider embedding command 문자열 0건
- release gate가 fault-ratio unavailable/version mismatch에서 fail-closed

### 회귀

- 판례 pipeline/agent adapter tests
- seed·readiness·AWS infrastructure focused tests
- 전체 pytest
- frontend Node tests와 Vite production build
- 운영 재배포 후 13개 E2E와 10분 operational acceptance

## 12. 비범위

- Qwen 문서 재임베딩
- BGE/Qwen model 또는 retrieval/reranking 알고리즘 변경
- 별도 RDS 생성
- legacy 343-row artifact를 NEW++에 합치기
- review-case, legal 97,394 seed 내용 변경
- 운영 적재·재배포·13개 E2E를 로컬 구현 완료로 간주하기

## 13. 활성화 순서

1. 이 명세와 구현 계획 승인
2. RED/GREEN으로 schema·service·command·deployment 계약 구현
3. 전체 로컬 회귀와 build
4. commit·push·PR·dev merge
5. 새 backend image build와 digest 고정
6. 별도 운영 승인 후 database maintenance stage/promotion
7. active seed version과 readiness 확인
8. app release pipeline 승인
9. 10분 operational acceptance
10. 배포 후 13개 E2E 및 최종 GO/NO-GO
