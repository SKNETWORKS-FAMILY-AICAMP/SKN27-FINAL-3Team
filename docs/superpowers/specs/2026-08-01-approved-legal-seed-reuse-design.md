# 승인 기반 법령 seed 임베딩 재사용 설계

## 목표

운영에서 검증된 `production_rag_seed_manifest.v1`의 OpenAI 법령 임베딩을 최신 법령 재수집 결과와 대조하여, 텍스트가 동일한 청크의 벡터는 재사용하고 변경·신규 청크만 별도 비용 승인 후 임베딩한다. 기존 seed만 재포장해 최신성을 위조하거나 승인 없이 provider를 호출하지 않는다.

## 기존 설계와의 관계

이 설계는 `2026-07-28-approved-legal-rag-pgvector-neo4j-ingestion-design.md`의 승인 기반 ingestion job을 대체하지 않고 미구현 seed build 구간을 구체화한다. 다음 계약은 유지한다.

- manifest 계약은 `production_rag_seed_manifest.v1`이다.
- 법령 embedding 공간은 `openai` / `text-embedding-3-large` / `1024`다.
- PostgreSQL/pgvector가 유일한 벡터 검색 backend다.
- Neo4j graph는 검증된 `legal_chunks`에서 결정적으로 파생한다.
- review-case와 fault-ratio precedent artifact는 기존 검증 bundle에서 그대로 복사하되 새 manifest가 다시 해시·행 수를 검증한다.
- AWS 업로드, 운영 DB 적재, descriptor 생성, App Release 승인은 이 builder의 범위 밖이며 별도 운영 단계다.

## 승인한 접근

최신 법령 source를 실제로 다시 수집한 뒤 각 새 청크를 기존 법령 임베딩과 `chunk_id + embedding_text_hash`로 비교한다.

- 두 값이 모두 같으면 기존 벡터 행을 그대로 재사용한다.
- `chunk_id`는 같지만 hash가 다르면 `changed`다.
- 새 `chunk_id`면 `new`다.
- 기존에만 존재하는 `chunk_id`는 `removed`이며 새 seed에서 제외한다.
- `changed`와 `new`만 provider 입력 파일에 기록한다.
- pending이 0이면 유료 승인 없이 새 bundle을 완성할 수 있다.
- pending이 1개 이상이면 `--allow-paid-embedding`이 없는 실행은 provider 호출 전에 중단한다.

단순히 기존 임베딩 baseline으로 청크를 재구축하고 현재 시각을 `last_verified_at`으로 기록하는 방식은 사용하지 않는다. 최신성은 법제처 source 재수집이 성공하고 `legal_ingestion_run_summary.v2` 검증을 통과한 경우에만 인정한다.

## 구성 요소

### `app/services/legal_embedding_reuse.py`

파일 기반 순수 서비스다. 검증된 기존 bundle과 최신 ingestion의 `embedding_inputs.jsonl`을 한 행씩 읽어 벡터를 메모리에 적재하지 않고 다음 산출물을 만든다.

- `reused_embeddings.jsonl`: 동일한 기존 embedding 행
- `pending_embedding_inputs.jsonl`: 변경·신규 입력만 포함
- `embedding_reuse_plan.v1.json`: `reused`, `changed`, `new`, `removed`, `pending` 건수와 안전한 식별 정보
- `embedding_reuse_audit.csv`: 벡터·원문 없이 `chunk_id`, 분류, 이전 hash, 새 hash만 포함

중복 `chunk_id`, 빈 hash, embedding 공간 불일치, 새 청크와 임베딩의 최종 1:1 불일치는 즉시 실패한다. 임시 파일을 사용하고 성공한 경우에만 최종 파일로 원자적으로 교체한다.

### `app/services/approved_legal_seed_builder.py`

다음 순서를 조정한다.

1. `etl.legal.ingestion.run`으로 승인된 source config를 실제 수집한다.
2. 생성된 `run_summary.json`을 승인된 `max_age_hours`와 필수 source 집합으로 검증한다.
3. 기존 manifest와 모든 artifact를 전체 검증한다.
4. 증분 재사용 계획을 생성한다.
5. `--dry-run`이면 provider를 호출하지 않고 계획까지만 반환한다.
6. pending이 있고 비용 승인이 없으면 계획을 보존한 채 실패한다.
7. 승인이 있으면 pending에 대해서만 OpenAI 임베딩을 생성한다.
8. reused와 신규 embedding을 결합한다.
9. 최신 legal chunks, 결합 embeddings, 기존 review-case, 기존 precedent를 새 bundle에 배치한다.
10. manifest를 생성하고 다시 로드하여 전체 이중 검증한다.

### `build_approved_legal_rag_seed` Django command

항상 필요한 인자는 다음과 같다.

- `--source-config`
- `--existing-manifest`
- `--output-root`
- `--max-age-hours`

선택 인자는 `--dataset-version`, `--approved-plan-sha256`, `--client`, `--base-date`, `--history-years`, `--dry-run`, `--allow-paid-embedding`, `--format`이다. dry-run은 새 ingestion summary에서 `dataset_version`과 pending identity를 정렬해 계산한 `plan_sha256`을 출력한다. non-dry 실행은 `--dataset-version`을 필수로 요구하고 새 summary 값과 exact match를 검증한다. pending이 있는 유료 실행은 dry-run에서 승인된 `--approved-plan-sha256`도 필수로 요구하며 현재 plan digest와 exact match를 검증한 뒤에만 provider를 호출한다. `--dry-run`은 법령 source API를 호출할 수 있지만 OpenAI, S3, 운영 DB는 호출하지 않으며 재사용 vector 파일도 materialize하지 않는다.

## 데이터와 비용 경계

기존 검증 seed는 97,394개 법령 청크와 같은 수의 OpenAI 임베딩을 포함한다. 이 수는 재사용 후보일 뿐 새 수집 결과와 hash가 일치하기 전에는 재사용 확정이 아니다.

유료 호출 승인 요청에는 다음을 포함한다.

- `changed` 건수
- `new` 건수
- 총 pending 건수
- 예상 API batch 수
- 대상 model과 dimensions

승인 범위는 그 실행의 pending 집합으로 고정한다. 계획 생성 후 입력 파일이나 source summary가 바뀌면 승인을 무효화하고 계획을 다시 만든다.

`plan_sha256`은 dataset version, 기존 manifest SHA, model, dimensions, 그리고 정렬된 pending `chunk_id:embedding_text_hash` 목록으로 계산한다. count만 같아도 identity가 달라지면 digest가 달라져 유료 실행이 차단된다.

## 실패 및 복구

- source 수집, freshness, 기존 manifest, hash 대조 중 하나라도 실패하면 final bundle을 만들지 않는다.
- provider 실패 시 기존 재사용 파일과 plan은 조사용으로 남기되 final manifest를 만들지 않는다.
- final manifest 이중 검증 실패 시 output을 승인 seed로 취급하지 않는다.
- final build는 materialized reuse 임시 파일에 변경분을 먼저 append하고 완성된 파일만 final `data/legal_embeddings.jsonl`로 원자 이동하여, 부분 최종 파일 노출과 2.4GB vector 사본 중복 보관을 모두 방지한다.
- 실패한 로컬 output은 운영 descriptor나 현재 release를 변경하지 않는다.
- 재실행은 새 output root를 사용하거나 명시적으로 비어 있는 output root만 사용한다.

## 검증 기준

1. 테스트는 네트워크와 provider를 호출하지 않는다.
2. 동일 청크는 벡터 값이 바뀌지 않고 재사용된다.
3. 변경·신규 청크만 pending으로 분류된다.
4. 삭제 청크는 새 bundle에 포함되지 않는다.
5. 비용 승인 없는 pending 실행은 OpenAI 호출 전에 실패한다.
6. pending 0건 실행은 OpenAI 자격증명 없이 완료된다.
7. 완성 bundle은 manifest build와 verify를 모두 통과한다.
8. audit JSON/CSV에는 embedding vector와 법령 원문이 없다.
9. 기존 법령 graph, pgvector loader, Pilot maintenance, App Release 계약의 회귀 테스트가 통과한다.
