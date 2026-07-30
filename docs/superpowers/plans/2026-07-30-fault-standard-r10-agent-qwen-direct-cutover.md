# Fault Standard R10 Agent-Owned Qwen Direct Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 과실비율 에이전트가 소유한 공용 Qwen 질의 임베딩 게이트웨이를 통해 승인된 인정기준 R10을 실제 `text_ml_case_search` 경로에 연결하고, 격리 적재·검색·계산·출력 검증 후 기존 인정기준 구현을 R10 단일 경로로 직접 교체한다.

**Architecture:** Supervisor와 연결된 공개 node/adapter는 기존 `text_ml_case_search`로 유지하고, 신규 내부 패키지 `fault_ratio_knowledge`가 도메인 조율·공용 Qwen·R10 호출을 담당한다. 이 내부 코어는 Supervisor에 별도 node로 등록하지 않으며 기존 에이전트가 단일 함수 계약으로 호출한다. R10 내부 결과는 기존 공개 `evidence`, `display_evidence`, `source_summary`, `rag_debug`, `ratio_range_label`로만 변환하며 공개 출력 필드를 추가하지 않는다. 인정기준 R10의 최초 구축은 기존 `qwen3_4b_r6_embeddings.jsonl.gz`에 들어 있는 6,145개 문서 벡터를 한 번 immutable S3 seed로 승격한 뒤 그대로 검증·적재하고, 이후 문서 갱신은 `input_text_sha256`가 새롭거나 바뀐 문서만 임베딩하는 증분 파이프라인으로 처리한다.

**Tech Stack:** Python 3.11+, pytest, Django management commands, PostgreSQL 16 + pgvector, Neo4j 5 Community, psycopg2, neo4j-driver, requests, RunPod Serverless, PyTorch, Transformers, Qwen/Qwen3-Embedding-4B, Docker Compose, AWS S3/SSM.

## Global Constraints

- 유일한 허용 release는 `fault_standard_r10_9e86695d05190c6d`다.
- R10 Next, R20 및 `standard_TEST`의 failed/invalid candidate는 코드·데이터·평가 입력으로 사용하지 않는다.
- 모델은 `Qwen/Qwen3-Embedding-4B`, revision `5cf2132abc99cad020ac570b19d031efec650f2b`, last-token pooling, L2 normalization, float32 output, 2,560차원으로 고정한다.
- 인정기준 질의 instruction은 `주어진 자동차 사고 질문과 가장 일치하는 자동차사고 과실비율 인정기준 문서를 검색하세요.`로 고정한다.
- 최초 R10 구축에서는 기존 `qwen3_4b_r6_embeddings.jsonl.gz`의 문서 벡터 6,145개를 재사용하며 corpus/document 재임베딩을 0건으로 유지한다.
- 기존 GZ의 평가 질문 벡터 30개는 COMPLETE30 재현 평가에서만 읽고 운영 PostgreSQL에는 적재하지 않는다.
- 사용자 질문은 검색 시점에 질의 벡터만 생성한다. 이는 6,145개 문서 재임베딩과 다른 온라인 query embedding 작업이다.
- 이후 데이터 갱신은 새롭거나 `input_text_sha256`가 변경된 문서만 임베딩하고, unchanged 문서 벡터는 그대로 재사용한다.
- 모델 ID, revision, pooling, normalization 또는 차원이 바뀌면 기존 벡터와 신규 벡터를 혼합하지 않고 새 release 전체 재색인을 별도 승인받는다.
- 기존 `RAG_EMBEDDING_*`와 `LEGAL_RAG_QUERY_*` OpenAI 1,024차원 설정은 변경하지 않는다.
- Supervisor node code, capability code, public adapter import는 `text_ml_case_search`로 유지한다.
- `fault_ratio_knowledge`는 내부 Python 패키지이며 새 Supervisor node, 새 라우팅 intent 또는 중복 공개 에이전트로 등록하지 않는다.
- 공개 `text_ml_case_search`는 입력/출력 호환 계층을 담당하고, Qwen·도메인 실행·RAG 결과 조립은 `fault_ratio_knowledge` 내부 코어가 담당한다.
- Supervisor 공개 top-level 및 `structured_result` 필드 이름·타입은 교체 전과 완전히 동일하게 유지한다. 공개 `fault_standard`, `ratio_anchors` 또는 다른 R10 전용 필드를 추가하지 않는다.
- R10 상세 결과와 수치 후보는 `fault_ratio_knowledge` 내부 계약에만 존재하며 공개 어댑터가 기존 `evidence.metadata`와 기존 출력 builder 입력으로 변환한다.
- 운영·일반 개발·CI 코드에서 `etl/fault_cases/standard_TEST`, `etl/fault_cases/review_case_test`, `etl/fault_cases/precedents_test`를 import하거나 파일 경로로 참조하지 않는다.
- 세 복사 폴더는 Git에 없고 fresh clone에서 존재하지 않는 것으로 간주한다. 일반 개발·CI 단위 테스트는 Git에 포함된 소형 synthetic fixture만 사용하고, 전체 6,145건 통합 검증은 immutable S3 seed를 내려받는 승인 환경에서 수행한다.
- PostgreSQL 검색 후보는 `doc_type='rule_retrieval' AND embedding_scope='rule_candidate'`인 277개 Rule 문서의 exact cosine Top-50으로 고정한다.
- R10 데이터 적재는 PostgreSQL `fault_standard_r10` schema와 Neo4j `FaultStandardR10` label/release ID에만 쓰며 기존 법률·심의사례·판례·인정기준 데이터를 삭제하거나 변환하지 않는다.
- 운영에는 `legacy | shadow | r10` 선택기와 기존 인정기준 자동 fallback을 만들지 않는다.
- Variant가 유일하게 선택되면 Variant 비율을 사용하고, 불명확하면 canonical Rule 기본비율을 사용하며 첫 번째 Variant를 임의 선택하지 않는다.
- canonical Rule 기본비율이 없는 `official_2023_보22`, `official_2023_차43-7`은 승인 Variant 전체의 수치 범위를 `variant_set_range`로 반환하고 단일 숫자를 만들지 않는다.
- 확인된 가감요소만 적용하고 누락·불명확한 가감요소는 0으로 취급한다.
- user/opponent 방향이 불명확하면 원문 당사자 비율 또는 수치 범위는 반환하되 user/opponent 단일 비율은 만들지 않는다.
- Supervisor 외부 입력에서 임의 query vector 주입을 허용하지 않는다. 사전 계산 벡터는 평가 전용 경로에서만 사용한다.
- 심의사례·판례의 Qwen 전환은 이번 계획에서 활성화하지 않는다. 공용 게이트웨이 프로필만 등록하고 현재 OpenAI 검색 경로는 그대로 유지한다.
- 심의사례 RAG 교체가 같은 저장소에서 진행 중이면 먼저 테스트 통과·안정 커밋을 만든다. R10 구현 브랜치는 그 커밋을 반영한 뒤 시작하고, 특히 Task 7·11의 공개 어댑터 통합을 병행 수정하지 않는다.
- 현재 로컬에만 있는 세 복사 폴더는 R10 seed 최초 승격이 완료될 때까지만 보존한다. S3 manifest/hash 검증 후에는 없어도 모든 일반 개발·CI·런타임 경로가 동작해야 한다.

---

## Source of Truth

- 배경 설계: `docs/superpowers/specs/2026-07-30-fault-standard-r10-operational-replacement-design.md`
- 운영 데이터 source of truth: manifest SHA가 포함된 immutable S3 R10 seed prefix와 `fault_standard_r10_seed_manifest.v1`
- Git source of truth: release ID, 모델 좌표계, artifact SHA/count, S3 manifest 위치를 고정한 작은 release contract와 loader/validator
- 최초 seed 승격의 로컬 원본: 현재 로컬에만 있는 `standard_TEST` approved R10 산출물. 이 경로는 provenance이며 일반 개발·CI·런타임 입력이 아니다.
- 최초 승격 후 R10 release/Core/Search/embedding manifest, Calculator V2, PostgreSQL B, Neo4j C reference는 모두 immutable S3 seed에서 읽는다.
- 실제 앱 진입점: `ai/agents/text_ml_case_search/agent.py`
- 공개 과실비율 에이전트 어댑터: `etl/fault_cases/src/agents/text_ml_case_search/agent.py`
- 신규 내부 코어: `etl/fault_cases/src/agents/fault_ratio_knowledge`

`etl/fault_cases/rag_runtime/agent_runtime/agent.py`는 현재 앱 진입점이 아니다. 이 계획은 해당 테스트용 통합기를 운영 진입점으로 바꾸지 않고, 실제 `etl/fault_cases/src/agents/text_ml_case_search`에서 R10을 호출한다.

이 구현 계획은 이후 승인된 두 변경에 한해 배경 설계보다 우선한다.

1. query embedding은 R10 내부가 아니라 `fault_ratio_knowledge` 내부 코어의 공용
   Qwen 게이트웨이가 담당한다.
2. 대형 R10 artifact를 Git 운영 경로로 복사하지 않고 기존 GZ를 포함한 immutable
   S3 seed bundle로 전달하며, 최초 구축에서는 문서 재임베딩을 수행하지 않는다.
3. R10 내부 결과는 공개 스키마에 새 필드를 추가하지 않고 기존
   `text_ml_case_search` 출력 builder를 통해서만 Supervisor 형식으로 변환한다.

```text
Supervisor
→ ai/agents/text_ml_case_search/agent.py
→ etl/fault_cases/src/agents/text_ml_case_search/agent.py
→ etl/fault_cases/src/agents/fault_ratio_knowledge/orchestrator.py
→ fault_ratio_knowledge/embedding + domains/fault_standard_r10.py
→ R10 DomainSearchResult
→ 기존 text_ml_case_search Supervisor envelope
```

## Public Output Contract Freeze

R10 교체 전후 ETL `AgentOutput` top-level key set은 정확히 다음과 같다.

```text
contract_version
node_code
status
structured_result
evidence
next_actions
limitations
missing_fields
```

ETL `StructuredResult` key set은 정확히 다음과 같다.

```text
normalized_description
accident_type_candidates
issue_tags
evidence_tags
recommended_evidence
insurer_claim_review
similar_cases
ratio_range_label
display_evidence
search_text
rag_debug
source_summary
reliability_score
limitations
```

최종 `ai/agents/text_ml_case_search` Supervisor envelope top-level key set도 교체 전과
동일하게 유지한다.

```text
session_id
message_id
job_id
node_name
node_code
node_type
owner
status
summary
structured_result
evidence
next_actions
limitations
created_at
```

AI adapter가 이미 추가하는 `query_text`, `top_cases`, `retrieval`은 기존 호환
동작으로 유지한다. R10은 새 공개 필드를 만들지 않고 다음 기존 위치에만
데이터를 기록한다.

```text
evidence[]                                 ← machine-readable R10 근거
evidence[].metadata                        ← release/rule/A-B/ratio_source
structured_result.display_evidence[]       ← 표시용 R10 근거
structured_result.source_summary           ← source count/status
structured_result.rag_debug                ← 비민감 검색 상태
structured_result.ratio_range_label        ← 기존 case 범위 또는 R10 수치 fallback
```

`source_summary.source_counts.fault_standard`와
`source_summary.source_statuses.fault_standard`는 기존 dynamic dictionary의 값이며
새 output field가 아니다.

## Embedding Reuse and Future Update Policy

### Initial R10 deployment

```text
etl/fault_cases/bootstrap/fault_standard/qwen3_4b_r6/
├── qwen3_4b_r6_embeddings.jsonl.gz
│   ├── document records 6,145 → hash/revision/dimension 검증 후 DB 적재
│   └── evaluation query records 30 → 운영 적재 금지, COMPLETE30에서만 사용
└── qwen3_4b_r6_embeddings_manifest.json
```

초기 seed loader는 모델을 호출하지 않는다. GZ 전체 SHA-256
`cd6d031ff775beb7401dcb729007190685a687b43afcad4c7c96207f171b8e8d`와
각 record의 `record_type`, ID, 입력 hash, 2,560차원, L2 norm을 검사한 뒤 문서
record만 적재한다.

### Live search

새 사용자 질문은 기존 파일 안에 존재할 수 없으므로 검색할 때 질의 벡터를 1개
생성해야 한다. 과실비율 에이전트의 Qwen 게이트웨이는 query instruction을 적용한
질의 벡터만 만들며 문서 corpus를 다시 인코딩하지 않는다.

### Future document updates

```text
신규 Search 문서 manifest
→ 현재 release와 doc_id/input_text_sha256 비교
→ unchanged: 기존 벡터 재사용
→ added/changed: RunPod 증분 bundle로 임베딩
→ delta GZ + manifest 검증
→ staging schema에 기존+delta 병합
→ 전체 count/hash/좌표계 검증
→ 새 release 승인
```

문서 임베딩에는 query instruction을 붙이지 않는다. 증분 결과는 기존 좌표계와
동일한 모델/revision/pooling/normalization/dimension일 때만 병합한다.

## Target File Map

### Fault-ratio knowledge 내부 코어와 Qwen 계층

- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/__init__.py`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/contracts.py`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/orchestrator.py`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/embedding/__init__.py`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/embedding/profiles.py`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/embedding/gateway.py`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/embedding/runpod_client.py`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/embedding/worker/handler.py`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/embedding/worker/requirements-runpod.txt`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/embedding/worker/Dockerfile`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/embedding/tests/test_profiles.py`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/embedding/tests/test_gateway.py`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/embedding/tests/test_worker_contract.py`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/domains/__init__.py`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/domains/fault_standard_r10.py`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/tests/test_orchestrator.py`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/tests/test_fault_standard_r10.py`

### 향후 R10 문서 증분 임베딩

- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/indexing/__init__.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/indexing/build_document_delta.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/indexing/run_qwen_document_delta.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/indexing/validate_document_delta.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/indexing/tests/test_build_document_delta.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/indexing/tests/test_run_qwen_document_delta.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/indexing/tests/test_validate_document_delta.py`

### R10 release·seed·저장소

- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/__init__.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/constants.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/types.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/release_contract.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/seed_bundle.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/postgres_repository.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/neo4j_repository.py`
- Create: `etl/fault_cases/rag_runtime/database/migrations/002_fault_standard_r10.sql`
- Create: `etl/fault_cases/rag_runtime/database/loaders/load_fault_standard_r10_postgres.py`
- Create: `etl/fault_cases/rag_runtime/database/loaders/load_fault_standard_r10_neo4j.py`
- Create: `backend/chatbot/management/commands/build_fault_standard_r10_seed.py`
- Create: `backend/chatbot/management/commands/verify_fault_standard_r10_seed.py`
- Create: `backend/chatbot/management/commands/load_fault_standard_r10_seed.py`

### R10 검색·계산·출력

- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/fact_adapter.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/structural_matcher.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/graph_matcher.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/selector.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/calculator.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/result_adapter.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/runtime.py`
- Modify: `etl/fault_cases/rag_runtime/contracts/supervisor_contract.py`
- Modify: `etl/fault_cases/rag_runtime/fault_standard/retriever.py`
- Modify: `etl/fault_cases/rag_runtime/fault_standard/service.py`
- Delete after cutover: `etl/fault_cases/rag_runtime/fault_standard/calculator.py`
- Delete after cutover: `etl/fault_cases/rag_runtime/fault_standard/graph_schema.py`
- Delete after cutover: `etl/fault_cases/rag_runtime/fault_standard/neo4j_reranker.py`
- Delete after cutover: `etl/fault_cases/rag_runtime/fault_standard/utils.py`
- Delete after cutover: `etl/fault_cases/rag_runtime/fault_standard/v9_graph_adapter.py`

### 공개 text_ml_case_search·내부 fault_ratio_knowledge·배포

- Modify: `ai/agents/text_ml_case_search/agent.py`
- Modify input types only: `etl/fault_cases/src/agents/text_ml_case_search/schemas.py`
- Modify: `etl/fault_cases/src/agents/text_ml_case_search/input/context_builder.py`
- Modify: `etl/fault_cases/src/agents/text_ml_case_search/agent.py`
- Modify: `etl/fault_cases/src/agents/text_ml_case_search/tests/test_agent_v2_output_schema.py`
- Create: `etl/fault_cases/src/agents/text_ml_case_search/tests/test_fault_ratio_knowledge_integration.py`
- Modify: `backend/config/settings.py`
- Modify: `.env.example`
- Modify: `deploy/aws-pilot/runtime.env.example`
- Modify: `deploy/aws-pilot/docker-compose.pilot.yml`
- Modify: `deploy/aws-pilot/Load-Rag-Seed-Pilot.ps1`
- Modify: `backend/chatbot/readiness.py`
- Modify: `backend/chatbot/management/commands/check_production_readiness.py`
- Modify: `backend/chatbot/management/commands/smoke_text_ml_case_search.py`
- Modify: `deploy/aws-pilot/README.ko.md`
- Modify: `etl/fault_cases/rag_runtime/agent_runtime/supervisor_input.py`
- Modify: `etl/fault_cases/rag_runtime/agent_runtime/tests/test_agent_contract.py`

---

### Task 1: Freeze the R10 Release Contract and Internal Types

**Files:**
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/constants.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/types.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/release_contract.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_release_contract.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_types.py`

**Interfaces:**
- Consumes: 승인된 R10 release/core/search/embedding manifest JSON.
- Produces: `load_release_contract(manifest_path: Path) -> R10ReleaseContract`, `R10_RELEASE_ID`, `R10_MODEL_REVISION`, `R10_QUERY_PROFILE_ID`.

- [ ] **Step 1: Write failing contract tests**

```python
def test_load_release_contract_accepts_only_frozen_r10(tmp_path: Path) -> None:
    manifest = frozen_release_manifest()
    path = write_json(tmp_path / "release.json", manifest)
    contract = load_release_contract(path)
    assert contract.release_id == "fault_standard_r10_9e86695d05190c6d"
    assert contract.rule_count == 277
    assert contract.search_document_count == 6145
    assert contract.document_embedding_count == 6145
    assert contract.query_embedding_count == 30
    assert contract.embedding_dimension == 2560


def test_release_contract_rejects_r10_next_or_r20(tmp_path: Path) -> None:
    for release_id in ("fault_standard_r10_next", "fault_standard_r20"):
        manifest = frozen_release_manifest()
        manifest["release_id"] = release_id
        with pytest.raises(R10ReleaseContractError, match="release_id"):
            load_release_contract(write_json(tmp_path / f"{release_id}.json", manifest))
```

- [ ] **Step 2: Run the tests and verify the missing-module failure**

Run:

```bash
python -m pytest etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_release_contract.py etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_types.py -v
```

Expected: FAIL because `constants`, `types`, and `release_contract` do not exist.

- [ ] **Step 3: Define frozen constants and dataclasses**

```python
R10_RELEASE_ID = "fault_standard_r10_9e86695d05190c6d"
R10_CORE_RELEASE_ID = "core_v2_r2_aa08a022f003"
R10_POSTGRES_RELEASE_ID = "fault_standard_r7_cd6d031ff775"
R10_NEO4J_RELEASE_ID = "fault_standard_r8_core_v2_r2"
R10_MODEL_ID = "Qwen/Qwen3-Embedding-4B"
R10_MODEL_REVISION = "5cf2132abc99cad020ac570b19d031efec650f2b"
R10_EMBEDDING_DIMENSION = 2560
R10_QUERY_PROFILE_ID = "fault_standard_r10"
R10_QUERY_INSTRUCTION = (
    "주어진 자동차 사고 질문과 가장 일치하는 "
    "자동차사고 과실비율 인정기준 문서를 검색하세요."
)
```

Define immutable dataclasses `R10ReleaseContract`, `RuleCandidate`, `PartyMappingDecision`, `RatioResult`, and `R10RuntimeResult`. The shared `QueryEmbedding` type is defined once in Task 2 under `agents/fault_ratio_knowledge/contracts.py`; the R10 package imports that type instead of defining a second shape.

- [ ] **Step 4: Implement strict release validation**

Validate the exact release ID, child release IDs, artifact hashes, counts, model ID/revision, last-token pooling, L2 normalization, float32 output, and 2,560 dimensions. Reject any path containing `R10_NEXT`, `R20`, `invalid`, or `failed_candidate`, case-insensitively.

- [ ] **Step 5: Run the focused tests**

Run:

```bash
python -m pytest etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_release_contract.py etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_types.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit the contract boundary**

```bash
git add etl/fault_cases/rag_runtime/fault_standard/r10
git commit -m "feat: freeze fault standard r10 release contract"
```

---

### Task 2: Build the Fault-Ratio Knowledge Core Contracts and Batched Qwen Gateway

**Files:**
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/__init__.py`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/contracts.py`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/embedding/__init__.py`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/embedding/profiles.py`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/embedding/gateway.py`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/embedding/runpod_client.py`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/embedding/worker/handler.py`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/embedding/worker/requirements-runpod.txt`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/embedding/worker/Dockerfile`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/embedding/tests/test_profiles.py`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/embedding/tests/test_gateway.py`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/embedding/tests/test_worker_contract.py`

**Interfaces:**
- Consumes: `Sequence[EmbeddingJob]` where every job has `job_id`, `profile_id`, and raw `query_text`.
- Produces: `QwenQueryGateway.embed(jobs: Sequence[EmbeddingJob]) -> dict[str, QueryEmbedding]`.
- Produces: `build_gateway_from_environment() -> QwenQueryGateway`.
- Defines: `FaultRatioKnowledgeRequest` and `FaultRatioKnowledgeResult`, consumed by the Task 11 orchestrator.
- Production provider: RunPod queue API with one remote job containing one to three domain jobs.

- [ ] **Step 1: Write failing profile and batch tests**

```python
def test_profiles_share_model_but_keep_distinct_instructions() -> None:
    profiles = [
        get_profile("fault_standard_r10"),
        get_profile("review_case"),
        get_profile("precedent"),
    ]
    assert {item.model_revision for item in profiles} == {
        "5cf2132abc99cad020ac570b19d031efec650f2b"
    }
    assert {item.dimension for item in profiles} == {2560}
    assert len({item.query_instruction for item in profiles}) == 3


def test_gateway_sends_three_profiles_in_one_provider_call(fake_provider) -> None:
    gateway = QwenQueryGateway(fake_provider)
    vectors = gateway.embed(
        [
            EmbeddingJob("standard", "fault_standard_r10", "교차로 사고"),
            EmbeddingJob("review", "review_case", "교차로 사고"),
            EmbeddingJob("precedent", "precedent", "교차로 사고"),
        ]
    )
    assert fake_provider.call_count == 1
    assert set(vectors) == {"standard", "review", "precedent"}
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest etl/fault_cases/src/agents/fault_ratio_knowledge/embedding/tests -v
```

Expected: FAIL because the gateway package does not exist.

- [ ] **Step 3: Define exact query profiles**

```python
@dataclass(frozen=True)
class EmbeddingJob:
    job_id: str
    profile_id: str
    query_text: str


@dataclass(frozen=True)
class QueryEmbedding:
    profile_id: str
    model_id: str
    model_revision: str
    dimension: int
    normalized: bool
    vector: tuple[float, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "dimension": self.dimension,
            "normalized": self.normalized,
            "vector": list(self.vector),
        }


@dataclass(frozen=True)
class FaultRatioKnowledgeRequest:
    message_id: str
    query_text: str
    accident_facts: dict[str, Any]
    required_domains: tuple[str, ...] = ("fault_standard",)


@dataclass(frozen=True)
class FaultRatioKnowledgeResult:
    status: str
    domains: dict[str, dict[str, Any]]
    evidence: tuple[dict[str, Any], ...]
    ratio_candidates: tuple[dict[str, Any], ...]
    limitations: tuple[str, ...]


PROFILES = {
    "fault_standard_r10": QueryProfile(
        profile_id="fault_standard_r10",
        query_instruction=(
            "주어진 자동차 사고 질문과 가장 일치하는 "
            "자동차사고 과실비율 인정기준 문서를 검색하세요."
        ),
    ),
    "review_case": QueryProfile(
        profile_id="review_case",
        query_instruction=(
            "Given a Korean traffic-accident description, retrieve the most "
            "relevant fault-ratio dispute review cases"
        ),
    ),
    "precedent": QueryProfile(
        profile_id="precedent",
        query_instruction=(
            "Given a Korean traffic-accident description, retrieve the most "
            "relevant Korean traffic-accident fault-liability precedents"
        ),
    ),
}


def encoded_text(profile: QueryProfile, query_text: str) -> str:
    query = " ".join(query_text.split())
    if not query:
        raise QueryEmbeddingError("empty_query")
    return f"Instruct: {profile.query_instruction}\nQuery: {query}"
```

Only `fault_standard_r10` is activated by this cutover. The other two profiles establish the future batching contract without changing their current retrievers.

- [ ] **Step 4: Implement the gateway and strict response validation**

The gateway must:

1. reject duplicate `job_id`;
2. deduplicate identical `(profile_id, normalized_query)` pairs;
3. make exactly one provider call for the remaining jobs;
4. restore results for deduplicated job IDs;
5. require finite 2,560-dimensional vectors with norm `0.99 <= norm <= 1.01`;
6. require exact model, revision, profile ID, and normalization metadata.

- [ ] **Step 5: Implement the RunPod worker contract**

The worker loads tokenizer/model once at module import and applies the same last-token pooling used by R10:

```python
def last_token_pool(last_hidden_states, attention_mask):
    left_padding = attention_mask[:, -1].sum() == attention_mask.shape[0]
    if left_padding:
        return last_hidden_states[:, -1]
    sequence_lengths = attention_mask.sum(dim=1) - 1
    batch_size = last_hidden_states.shape[0]
    return last_hidden_states[
        torch.arange(batch_size, device=last_hidden_states.device),
        sequence_lengths,
    ]


def handler(event):
    request = validate_request(event["input"])
    texts = [encoded_text(get_profile(job.profile_id), job.query_text) for job in request.jobs]
    vectors = encode_batch(texts)
    return build_response(request.jobs, vectors)
```

`requirements-runpod.txt` pins the R10-compatible major/minor line:

```text
runpod>=1.7,<2
torch==2.4.1
transformers==4.53.3
huggingface-hub>=0.33,<1
safetensors>=0.4,<1
sentencepiece>=0.2,<1
```

- [ ] **Step 6: Package the worker image**

```dockerfile
FROM pytorch/pytorch:2.4.1-cuda12.4-cudnn9-runtime
WORKDIR /app
COPY requirements-runpod.txt /app/requirements-runpod.txt
RUN pip install --no-cache-dir -r /app/requirements-runpod.txt
COPY handler.py /app/handler.py
ENV PYTHONUNBUFFERED=1
CMD ["python", "-u", "/app/handler.py"]
```

At worker startup, load `Qwen/Qwen3-Embedding-4B` with the exact revision and fail if the resolved model commit differs.

- [ ] **Step 7: Implement the privacy-safe RunPod client**

Use `POST /run`, poll `GET /status/{job_id}`, enforce configured timeout, never log raw query text or vectors, and normalize all provider errors to stable codes:

```python
class RunPodQwenClient:
    def embed(self, jobs: Sequence[EmbeddingJob]) -> dict[str, QueryEmbedding]:
        payload = {"input": build_request_payload(jobs)}
        run_id = self._submit(payload)
        output = self._poll(run_id)
        return parse_response(output)
```

- [ ] **Step 8: Run gateway tests**

Run:

```bash
python -m pytest etl/fault_cases/src/agents/fault_ratio_knowledge/embedding/tests -v
```

Expected: PASS, including one provider call for three profiles and rejection of wrong revision/dimension/norm.

- [ ] **Step 9: Commit the Qwen gateway**

```bash
git add etl/fault_cases/src/agents/fault_ratio_knowledge/__init__.py etl/fault_cases/src/agents/fault_ratio_knowledge/contracts.py etl/fault_cases/src/agents/fault_ratio_knowledge/embedding
git commit -m "feat: add batched qwen query embedding gateway"
```

---

### Task 3: Build and Verify a Separate Immutable R10 Seed Bundle

**Files:**
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/seed_bundle.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_seed_bundle.py`
- Create: `backend/chatbot/management/commands/build_fault_standard_r10_seed.py`
- Create: `backend/chatbot/management/commands/verify_fault_standard_r10_seed.py`
- Create: `backend/chatbot/test_fault_standard_r10_seed_commands.py`

**Interfaces:**
- Consumes: an explicit release-owner-only `R10_RELEASE_SOURCE_ROOT` during the one-time seed promotion; normal development, CI, loaders, and runtime consume only the immutable seed manifest/bundle.
- Git delivery seed: `etl/fault_cases/bootstrap/fault_standard/qwen3_4b_r6/`; this is a promoted immutable copy, not an embedding-generation output directory.
- Produces: `fault_standard_r10_seed_manifest.v1` plus exact approved files in a standalone bundle directory.
- No command has a copied-test-directory default. Runtime loaders consume only the bundle and never any of the three copied test directories.

- [ ] **Step 1: Write failing seed contract tests**

```python
def test_seed_manifest_contains_exact_required_roles(tmp_path: Path) -> None:
    bundle = build_test_bundle(tmp_path)
    validated = load_and_validate_seed(bundle / "fault-standard-r10-manifest.json")
    assert validated.release_id == "fault_standard_r10_9e86695d05190c6d"
    assert validated.artifacts["embeddings"].bytes == 78002144
    assert validated.artifacts["search_documents"].row_count == 6145


def test_seed_rejects_query_vectors_as_database_rows(tmp_path: Path) -> None:
    bundle = build_test_bundle(tmp_path)
    validated = load_and_validate_seed(bundle / "fault-standard-r10-manifest.json")
    assert validated.document_embedding_count == 6145
    assert validated.evaluation_query_embedding_count == 30


def test_build_command_requires_explicit_release_source_root() -> None:
    command = BuildFaultStandardR10SeedCommand()
    assert command.default_source_root is None


def test_seed_unit_fixture_is_self_contained(tmp_path: Path) -> None:
    fixture = build_synthetic_seed_source(tmp_path)
    assert "standard_TEST" not in str(fixture)
    assert load_and_validate_seed(fixture / "fault-standard-r10-manifest.json")
```

- [ ] **Step 2: Define exact seed roles**

The manifest contains these roles and no R10 Next/R20 files:

```python
REQUIRED_SEED_ROLES = (
    "release_manifest",
    "core_manifest",
    "core_rules",
    "core_parties",
    "core_base_faults",
    "core_variants",
    "core_adjustments",
    "core_lane_paths",
    "core_lane_steps",
    "core_contexts",
    "core_evidence_blocks",
    "core_shared_rule_groups",
    "core_shared_rule_members",
    "predicate_manifest",
    "predicate_registry",
    "search_manifest",
    "search_documents",
    "embedding_manifest",
    "embeddings",
)
```

- [ ] **Step 3: Implement one-time promotion copying and cross-manifest verification**

The builder must require an explicit source root, reject a missing argument, resolve every artifact under that root, verify the release manifest and every child manifest hash/count, copy only the required files, recompute SHA-256 after copying, and write the seed manifest last. The implementation must not contain the names `standard_TEST`, `review_case_test`, or `precedents_test`; those local folders are release-owner provenance, not application configuration.

The generated manifest records:

```json
{
  "contract_version": "fault_standard_r10_seed_manifest.v1",
  "release_id": "fault_standard_r10_9e86695d05190c6d",
  "model_id": "Qwen/Qwen3-Embedding-4B",
  "model_revision": "5cf2132abc99cad020ac570b19d031efec650f2b",
  "embedding_dimension": 2560,
  "rule_count": 277,
  "search_document_count": 6145,
  "document_embedding_count": 6145,
  "evaluation_query_embedding_count": 30,
  "artifacts": []
}
```

- [ ] **Step 4: Add release-owner promotion and normal bundle verification commands**

One-time promotion only, on the release-owner machine while the approved source still
exists:

```powershell
if (-not $env:R10_RELEASE_SOURCE_ROOT) { throw 'R10_RELEASE_SOURCE_ROOT is required for one-time seed promotion.' }
python backend/manage.py build_fault_standard_r10_seed --source-root "$env:R10_RELEASE_SOURCE_ROOT" --output-dir artifacts/deploy/fault-standard-r10 --format json
```

This command is not part of normal developer setup or CI. After building, upload the
bundle to the versioned S3 prefix and record the exact manifest SHA in the Git release
contract. Normal verification receives an already downloaded manifest:

```bash
python backend/manage.py verify_fault_standard_r10_seed --manifest artifacts/runtime/fault-standard-r10/fault-standard-r10-manifest.json --format json
```

Expected JSON status: `passed`.

- [ ] **Step 5: Run tests**

```bash
python -m pytest etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_seed_bundle.py backend/chatbot/test_fault_standard_r10_seed_commands.py -v
```

Expected: PASS.

The tests build their own tiny synthetic bundle under `tmp_path`; they do not skip and
do not read any copied test directory.

- [ ] **Step 6: Commit seed tooling without committing the generated 78MB artifact**

```bash
git add etl/fault_cases/rag_runtime/fault_standard/r10/seed_bundle.py etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_seed_bundle.py backend/chatbot/management/commands/build_fault_standard_r10_seed.py backend/chatbot/management/commands/verify_fault_standard_r10_seed.py backend/chatbot/test_fault_standard_r10_seed_commands.py
git commit -m "feat: add immutable fault standard r10 seed bundle"
```

---

### Task 4: Provide the Future Incremental Document Embedding Pipeline

**Files:**
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/indexing/__init__.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/indexing/build_document_delta.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/indexing/run_qwen_document_delta.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/indexing/validate_document_delta.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/indexing/tests/test_build_document_delta.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/indexing/tests/test_run_qwen_document_delta.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/indexing/tests/test_validate_document_delta.py`

**Interfaces:**
- Consumes: current approved document manifest/embeddings and a future Search V2-compatible document JSONL.
- Produces: `document_embedding_delta_input.jsonl`, a RunPod execution bundle, `qwen3_4b_document_delta.jsonl.gz`, and `qwen3_4b_document_delta_manifest.json`.
- This pipeline is not called during initial R10 deployment.

- [ ] **Step 1: Write failing delta classification tests**

```python
def test_delta_builder_skips_unchanged_documents() -> None:
    current = [
        {"doc_id": "same", "input_text_sha256": "a" * 64},
        {"doc_id": "changed", "input_text_sha256": "b" * 64},
    ]
    incoming = [
        {"doc_id": "same", "input_text_sha256": "a" * 64},
        {"doc_id": "changed", "input_text_sha256": "c" * 64},
        {"doc_id": "added", "input_text_sha256": "d" * 64},
    ]
    delta = classify_document_delta(current=current, incoming=incoming)
    assert delta.unchanged_ids == ("same",)
    assert delta.embed_ids == ("added", "changed")


def test_delta_builder_never_includes_query_records() -> None:
    delta = classify_document_delta(
        current=[],
        incoming=[{"doc_id": "q1", "record_type": "query", "input_text_sha256": "a" * 64}],
    )
    assert delta.embed_ids == ()
    assert delta.rejected_ids == ("q1",)
```

- [ ] **Step 2: Run tests and verify missing-module failure**

```bash
python -m pytest etl/fault_cases/rag_runtime/fault_standard/r10/indexing/tests -v
```

Expected: FAIL because the indexing package does not exist.

- [ ] **Step 3: Implement deterministic change detection**

Use `doc_id` plus `input_text_sha256` as the reuse key:

```python
@dataclass(frozen=True)
class DocumentDelta:
    unchanged_ids: tuple[str, ...]
    embed_ids: tuple[str, ...]
    removed_ids: tuple[str, ...]
    rejected_ids: tuple[str, ...]


def needs_embedding(current: Mapping[str, str], row: Mapping[str, Any]) -> bool:
    doc_id = str(row["doc_id"])
    input_hash = str(row["input_text_sha256"])
    return current.get(doc_id) != input_hash
```

Sort every ID list to make the bundle byte-reproducible. Removed IDs are recorded for the
new release staging merge; this step does not delete rows from the active release.

- [ ] **Step 4: Build a RunPod bundle containing only added/changed documents**

The bundle includes:

```text
document_embedding_delta_input.jsonl
document_embedding_delta_input_manifest.json
run_qwen_document_delta.py
requirements-runpod.txt
```

Each input row contains only `doc_id`, `doc_text`, `input_text_sha256`,
`encoded_text_sha256`, `doc_type`, and `embedding_scope`. Do not include evaluation
questions, qrels, expected Rule rank, or expected ratio.

- [ ] **Step 5: Implement document-only Qwen encoding**

```python
def encode_documents(rows: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    texts = [str(row["doc_text"]) for row in rows]
    vectors = encode_batch(texts)  # document instruction 없음
    for row, vector in zip(rows, vectors, strict=True):
        yield {
            "record_type": "document",
            "source_id": row["doc_id"],
            "input_text_sha256": row["input_text_sha256"],
            "embedding_dimension": 2560,
            "embedding": [float(value) for value in vector],
        }
```

Use the same model revision, last-token pooling, L2 normalization, float32 output, and
2,048-token maximum as R10 R6. The execution script writes gzip directly and records
resolved revision plus output SHA-256.

- [ ] **Step 6: Implement strict delta-result validation**

Reject the result unless:

- output IDs equal exactly the requested added/changed IDs;
- every row is `record_type=document`;
- no duplicates, missing IDs, or extra IDs exist;
- every vector is finite 2,560-dimensional L2-normalized float data;
- model/revision/pooling/normalization match R10;
- input/output hashes and row counts match the delta manifests.

- [ ] **Step 7: Run indexing tests**

```bash
python -m pytest etl/fault_cases/rag_runtime/fault_standard/r10/indexing/tests -v
```

Expected: PASS, including an unchanged-only update that produces an empty embedding
request and makes zero model calls.

- [ ] **Step 8: Commit the future update pipeline**

```bash
git add etl/fault_cases/rag_runtime/fault_standard/r10/indexing
git commit -m "feat: add incremental r10 document embedding pipeline"
```

---

### Task 5: Create the Isolated PostgreSQL R10 Schema, Loader, and Repository

**Files:**
- Create: `etl/fault_cases/rag_runtime/database/migrations/002_fault_standard_r10.sql`
- Create: `etl/fault_cases/rag_runtime/database/loaders/load_fault_standard_r10_postgres.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/postgres_repository.py`
- Create: `etl/fault_cases/rag_runtime/database/tests/test_load_fault_standard_r10_postgres.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_postgres_repository.py`

**Interfaces:**
- Consumes: validated `R10SeedBundle`, explicit PostgreSQL config, validated query vector.
- Produces: `load_postgres_seed(bundle, config) -> PostgresLoadReport`, `PostgresR10Repository.search_rule_candidates(vector, top_k=50)`, `fetch_rule_bundle(rule_ids)`.

- [ ] **Step 1: Write failing migration/loader tests**

Tests must assert:

- schema name is exactly `fault_standard_r10`;
- all runtime tables include `release_id`;
- vector is `vector(2560)`;
- no HNSW/IVFFlat index exists for the 277 Rule candidate vectors;
- query records from the 6,175-row embedding file are not inserted;
- rerunning the same release is an idempotent validation/no-op;
- a different release in the target schema is rejected.

- [ ] **Step 2: Run focused tests**

```bash
python -m pytest etl/fault_cases/rag_runtime/database/tests/test_load_fault_standard_r10_postgres.py etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_postgres_repository.py -v
```

Expected: FAIL because migration, loader, and repository are missing.

- [ ] **Step 3: Port the approved R7 schema into the isolated R10 schema**

Keep the R10 source tables:

```text
release_manifests
core_v2_rules
core_v2_parties
core_v2_base_faults
core_v2_variants
core_v2_adjustments
core_v2_adjustment_conditions
core_v2_lane_paths
core_v2_lane_steps
core_v2_contexts
core_v2_evidence_blocks
core_v2_shared_rule_groups
core_v2_shared_rule_members
search_v2_documents
```

Add checks that every row has `release_id='fault_standard_r10_9e86695d05190c6d'` at the operational boundary.

- [ ] **Step 4: Implement transactional loading**

Load into `fault_standard_r10_staging`, validate all counts and foreign keys, then rename to `fault_standard_r10`. Do not drop or rename any existing non-R10 schema. If `fault_standard_r10` already contains the same release and all counts match, return `already_loaded`; otherwise fail closed.

- [ ] **Step 5: Implement exact-cosine repository methods**

```python
def search_rule_candidates(
    self,
    query_vector: Sequence[float],
    *,
    top_k: int = 50,
) -> list[RuleCandidate]:
    sql = """
        SELECT doc_id, rule_id,
               1 - (embedding <=> %s::vector) AS cosine_similarity
        FROM fault_standard_r10.search_v2_documents
        WHERE release_id = %s
          AND doc_type = 'rule_retrieval'
          AND embedding_scope = 'rule_candidate'
        ORDER BY embedding <=> %s::vector, doc_id
        LIMIT %s
    """
```

Require exactly 50 unique Rule IDs and deterministic `doc_id` tie-breaking.

- [ ] **Step 6: Run unit and optional integration tests**

Unit:

```bash
python -m pytest etl/fault_cases/rag_runtime/database/tests/test_load_fault_standard_r10_postgres.py etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_postgres_repository.py -v
```

Integration with the isolated local R10 PostgreSQL:

```bash
python -m pytest -m integration etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_postgres_repository.py -v
```

Expected: 277 Rule rows, 6,145 search rows, 6,145 stored document embeddings, 2,560 dimensions.

- [ ] **Step 7: Commit PostgreSQL support**

```bash
git add etl/fault_cases/rag_runtime/database/migrations/002_fault_standard_r10.sql etl/fault_cases/rag_runtime/database/loaders/load_fault_standard_r10_postgres.py etl/fault_cases/rag_runtime/database/tests/test_load_fault_standard_r10_postgres.py etl/fault_cases/rag_runtime/fault_standard/r10/postgres_repository.py etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_postgres_repository.py
git commit -m "feat: add isolated r10 postgres store"
```

---

### Task 6: Create the Isolated Neo4j R10 Loader and Repository

**Files:**
- Create: `etl/fault_cases/rag_runtime/database/loaders/load_fault_standard_r10_neo4j.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/neo4j_repository.py`
- Create: `etl/fault_cases/rag_runtime/database/tests/test_load_fault_standard_r10_neo4j.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_neo4j_repository.py`

**Interfaces:**
- Consumes: validated seed Core/Predicate files and explicit Neo4j config.
- Produces: `load_neo4j_seed(bundle, config) -> Neo4jLoadReport`, `Neo4jR10Repository.fetch_paths(rule_ids) -> dict[str, RuleGraph]`.

- [ ] **Step 1: Write failing graph isolation tests**

Tests inspect generated Cypher and assert every operational node has both:

```cypher
:FaultStandardR10
release_id: 'fault_standard_r10_9e86695d05190c6d'
```

They also assert there is no unscoped `MATCH (n) DETACH DELETE n`, no `Law` label mutation, and no query lacking `$release_id`.

- [ ] **Step 2: Port only the approved R8 graph model**

Create Rule, Party, BaseFault, Variant, Adjustment, LanePath, LaneStep, Context, Evidence, and Predicate nodes and approved relationships. Use stable composite operational IDs such as:

```text
fault_standard_r10_9e86695d05190c6d::Rule::official_2023_차43-7
```

MERGE on `operational_id`; do not MERGE on a law graph property shared with another domain.

- [ ] **Step 3: Implement idempotent loading and validation**

Validate node/relationship counts against the R8 load report, duplicate Rule count 0, orphan nodes 0, exactly 277 Rules, and required Party/BaseFault relationships.

AWS uses the existing Neo4j service with label/release isolation:

```text
FAULT_STANDARD_NEO4J_URI=bolt://law-neo4j:7687
FAULT_STANDARD_NEO4J_DATABASE=neo4j
```

Local development may continue using `bolt://fault-standard-neo4j:7687`. The runtime query is identical because isolation is logical.

- [ ] **Step 4: Implement read-only repository queries**

Every query begins from:

```cypher
MATCH (r:FaultStandardR10:Rule)
WHERE r.release_id = $release_id AND r.rule_id IN $rule_ids
```

Return ordered lane steps, parties, base fault, variants, adjustments, predicates, and contexts without reading law graph labels.

- [ ] **Step 5: Run tests**

```bash
python -m pytest etl/fault_cases/rag_runtime/database/tests/test_load_fault_standard_r10_neo4j.py etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_neo4j_repository.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit Neo4j support**

```bash
git add etl/fault_cases/rag_runtime/database/loaders/load_fault_standard_r10_neo4j.py etl/fault_cases/rag_runtime/database/tests/test_load_fault_standard_r10_neo4j.py etl/fault_cases/rag_runtime/fault_standard/r10/neo4j_repository.py etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_neo4j_repository.py
git commit -m "feat: add isolated r10 neo4j graph"
```

---

### Task 7: Preserve Structured Accident Facts Through the Real Agent Boundary

**Files:**
- Modify: `ai/agents/text_ml_case_search/agent.py`
- Modify: `etl/fault_cases/src/agents/text_ml_case_search/schemas.py`
- Modify: `etl/fault_cases/src/agents/text_ml_case_search/input/context_builder.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/fact_adapter.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_fact_adapter.py`
- Modify: `etl/fault_cases/src/agents/text_ml_case_search/tests/test_supervisor_contract.py`

**Interfaces:**
- Consumes: optional `accident_facts` or `structured_facts` from Supervisor context.
- Produces: normalized R10 facts with `user`, `opponent`, `scene`, `adjustment_facts`, and explicit missing/conflict trace.

- [ ] **Step 1: Write failing boundary tests**

```python
def test_etl_input_preserves_structured_accident_facts() -> None:
    result = _etl_agent_input(
        {
            "session_id": "s",
            "message_id": "m",
            "job_id": "j",
            "context": {
                "accident_facts": {
                    "user": {"movement": "직진"},
                    "opponent": {"movement": "좌회전"},
                    "scene": {"road_type": "교차로"},
                }
            },
        },
        "교차로 충돌",
    )
    assert result["accident_facts"]["user"]["movement"] == "직진"
```

- [ ] **Step 2: Modify only the input/context side of the adapter schema**

Accept `accident_facts` first, then `structured_facts`, otherwise `{}`. Do not make the
new input field required so existing callers remain valid. In `schemas.py`, change only
`AgentContext`; do not add, remove, rename, or retype any `AgentOutput` or
`StructuredResult` field.

- [ ] **Step 3: Implement deterministic fact normalization**

`adapt_accident_facts(raw: Mapping[str, Any]) -> AdaptedFacts` must:

- preserve user/opponent identity;
- normalize supported scalar fields without inferring missing values;
- retain conflicting values in `conflicts`;
- convert only explicit `state="confirmed"` adjustment facts to calculator confirmations;
- report missing fields but never block Rule base/range retrieval.

- [ ] **Step 4: Run tests**

```bash
python -m pytest etl/fault_cases/src/agents/text_ml_case_search/tests/test_supervisor_contract.py etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_fact_adapter.py -v
```

Expected: PASS, existing Supervisor inputs without `accident_facts` remain accepted,
and the pre-cutover output key/type snapshot is unchanged.

- [ ] **Step 5: Commit fact propagation**

```bash
git add ai/agents/text_ml_case_search/agent.py etl/fault_cases/src/agents/text_ml_case_search/schemas.py etl/fault_cases/src/agents/text_ml_case_search/input/context_builder.py etl/fault_cases/src/agents/text_ml_case_search/tests/test_supervisor_contract.py etl/fault_cases/rag_runtime/fault_standard/r10/fact_adapter.py etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_fact_adapter.py
git commit -m "feat: preserve structured facts for r10"
```

---

### Task 8: Port R10 A/B/C Selection Without Candidate Drift

**Files:**
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/structural_matcher.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/graph_matcher.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/selector.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_structural_matcher.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_graph_matcher.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_selector.py`

**Interfaces:**
- Consumes: one ordered A Top-50 candidate list plus adapted facts.
- Produces: `SelectionResult` with method `C`, `B_DEGRADED`, or `A_EVIDENCE_ONLY`, selected Rule, party mapping decision, Variant decision, and complete trace.

- [ ] **Step 1: Write failing parity and degradation tests**

```python
def test_b_and_c_never_change_a_candidate_set() -> None:
    a = candidates(50)
    result = selector.select(a, facts=complete_facts())
    assert set(result.a_rule_ids) == set(result.b_rule_ids) == set(result.c_rule_ids)


def test_neo4j_failure_degrades_to_b_without_legacy_fallback() -> None:
    result = selector.select(candidates(50), facts=complete_facts(), graph_error=OSError())
    assert result.method == "B_DEGRADED"
    assert "neo4j_unavailable" in result.limitations
```

- [ ] **Step 2: Port PostgreSQL B comparison rules**

Port the R10 aliases, movement/road/signal/entry normalization, orientation comparison, grade ordering, deterministic tie-breaking, and complete comparison trace. When both orientations have the same effective grade/contradiction/match/unknown tuple, set `party_mapping.status="unresolved"` instead of treating lexical source-key ordering as factual proof.

- [ ] **Step 3: Port Neo4j C path comparison**

Use the same A candidate set, ordered LanePath/LaneStep relations, and R10 grade ordering. C may reorder but never add or remove a Rule.

- [ ] **Step 4: Implement explicit stage degradation**

```python
try:
    c = graph_matcher.rerank(a, facts)
    return choose(c, method="C")
except Neo4jRepositoryError:
    try:
        b = structural_matcher.rerank(a, facts)
        return choose(b, method="B_DEGRADED")
    except PostgresStructureError:
        return evidence_only(a, method="A_EVIDENCE_ONLY")
```

`A_EVIDENCE_ONLY` returns evidence and selected A Rule for trace but does not authorize a user/opponent calculation because structural storage failed.

- [ ] **Step 5: Run tests**

```bash
python -m pytest etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_structural_matcher.py etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_graph_matcher.py etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_selector.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit the selector**

```bash
git add etl/fault_cases/rag_runtime/fault_standard/r10/structural_matcher.py etl/fault_cases/rag_runtime/fault_standard/r10/graph_matcher.py etl/fault_cases/rag_runtime/fault_standard/r10/selector.py etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_structural_matcher.py etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_graph_matcher.py etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_selector.py
git commit -m "feat: port r10 abc selector"
```

---

### Task 9: Implement the Forced Numeric Base/Range Calculator

**Files:**
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/calculator.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_calculator.py`

**Interfaces:**
- Consumes: selected Rule, optional unique Variant, optional party mapping, adapted confirmed facts.
- Produces: `RatioResult` with `ratio_source` in `variant | rule_base | variant_set_range`.

- [ ] **Step 1: Write failing numeric policy tests**

```python
def test_ambiguous_variant_uses_primary_rule_ratio() -> None:
    result = calculator.calculate(
        rule=pair_rule(primary=(40, 60), variants=[(35, 65), (45, 55)]),
        variant_id=None,
        party_mapping={"user": "A", "opponent": "B"},
        facts={},
    )
    assert result.ratio_source == "rule_base"
    assert result.final_ratio == {"user": 40, "opponent": 60}


def test_variant_only_rule_returns_range_not_first_variant() -> None:
    result = calculator.calculate(
        rule=variant_only_rule("official_2023_차43-7", [(100, 0), (70, 30)]),
        variant_id=None,
        party_mapping={"user": "A", "opponent": "B"},
        facts={},
    )
    assert result.ratio_source == "variant_set_range"
    assert result.user_ratio_range == {"min": 70, "max": 100}
    assert result.final_ratio is None
```

Also test:

- unique Variant selection;
- no first-Variant fallback;
- confirmed adjustment applied;
- unknown adjustment ignored and traced;
- ratio bounds 0..100 and sum 100;
- unresolved party mapping returns source-party values/ranges and null user/opponent values;
- missing base data outside the two declared variant-only Rules fails integrity validation.

- [ ] **Step 2: Implement canonical base resolution**

Resolution order:

```text
unique matched Variant
→ canonical Rule primary ratio option
→ Rule single-party base
→ approved Variant set numeric range for the two variant-only Rules
→ data-integrity failure
```

Do not use list position to select a Variant.

- [ ] **Step 3: Implement adjustment application**

Evaluate only approved predicate records. Apply a delta only for predicate `TRUE`; record `FALSE` and `UNKNOWN` without applying them. Clamp the target to 0..100 and set the other party to `100-target`.

- [ ] **Step 4: Run tests**

```bash
python -m pytest etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_calculator.py -v
```

Expected: PASS, including exact special handling for `official_2023_보22` and `official_2023_차43-7`.

- [ ] **Step 5: Commit the calculator**

```bash
git add etl/fault_cases/rag_runtime/fault_standard/r10/calculator.py etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_calculator.py
git commit -m "feat: add r10 base and range calculator"
```

---

### Task 10: Compose the R10 Runtime and Existing Domain Result Contract

**Files:**
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/result_adapter.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/runtime.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_runtime.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_result_adapter.py`
- Modify: `etl/fault_cases/rag_runtime/contracts/supervisor_contract.py`
- Modify: `etl/fault_cases/rag_runtime/agent_runtime/supervisor_input.py`
- Modify: `etl/fault_cases/rag_runtime/agent_runtime/tests/test_agent_contract.py`
- Modify: `etl/fault_cases/rag_runtime/fault_standard/retriever.py`
- Modify: `etl/fault_cases/rag_runtime/fault_standard/service.py`

**Interfaces:**
- Consumes: `RagRequest` containing query text, accident facts, and agent-generated `query_embedding`.
- Produces: existing `DomainSearchResult` fields plus R10 calculation trace.

- [ ] **Step 1: Write failing runtime contract tests**

```python
def test_runtime_returns_r10_numeric_anchor() -> None:
    result = runtime.run(request_with_r10_embedding_and_facts())
    assert result["domain"] == "fault_standard"
    assert result["status"] == "success"
    assert result["calculation_result"]["release_id"] == R10_RELEASE_ID
    assert result["calculation_result"]["ratio_source"] in {"variant", "rule_base"}


def test_runtime_rejects_external_wrong_profile_vector() -> None:
    request = request_with_embedding(profile_id="review_case")
    result = runtime.run(request)
    assert result["status"] == "failed"
    assert result["calculation_result"] is None
```

- [ ] **Step 2: Implement runtime composition**

```python
class FaultStandardR10Runtime:
    def run(self, request: RagRequest) -> DomainSearchResult:
        embedding = parse_and_validate_embedding(request["query_embedding"])
        facts = adapt_accident_facts(request.get("accident_facts") or {})
        candidates = self.postgres.search_rule_candidates(embedding.vector, top_k=50)
        selection = self.selector.select(candidates, facts)
        calculation = self.calculator.calculate(selection, facts)
        return build_domain_result(candidates, selection, calculation)
```

`calculation_result` is internal and uses this exact field set so Task 11 can map it
without guessing:

```python
{
    "release_id": str,
    "rule_id": str,
    "ratio_source": Literal["variant", "rule_base", "variant_set_range"],
    "a_ratio": int | None,
    "b_ratio": int | None,
    "source_party_ratio_range": dict[str, dict[str, int]] | None,
    "party_mapping_status": Literal["resolved", "unresolved"],
    "user_ratio": int | None,
    "opponent_ratio": int | None,
    "user_ratio_range": dict[str, int] | None,
    "opponent_ratio_range": dict[str, int] | None,
    "applied_adjustments": list[dict[str, Any]],
    "assumptions": list[str],
}
```

- [ ] **Step 3: Extend the internal RAG request type**

Add only the internal metadata envelope:

```python
class RagRequest(TypedDict, total=False):
    # Existing fields remain unchanged.
    query_embedding: dict[str, Any]
```

`query_vector` remains evaluation-only during the transition. The real agent adapter always sends `query_embedding`, and no Supervisor/API parser copies a user-supplied `query_embedding` into this field.

- [ ] **Step 4: Close the external vector-injection path**

Change `agent_runtime.supervisor_input.parse_input` so it never copies raw
`query_vector` or `query_embedding` from Supervisor input:

```python
return {
    "contract_version": "v1",
    "message_id": message_id,
    "query_text": query_text,
    "accident_facts": accident_facts,
    "required_domains": required_domains,
}
```

Add a contract test that supplies both fields externally and asserts neither is present
in the parsed request. Evaluation code constructs its internal request directly after
loading the approved frozen vector.

- [ ] **Step 5: Define statuses exactly**

- `success`: selected Rule plus user/opponent single ratio.
- `partial`: selected Rule plus source-party numeric values, user/opponent unresolved, `variant_set_range`, or B degradation.
- `failed`: embedding, PostgreSQL vector search, release contract, or data-integrity failure.

Neo4j-only failure may return a B-derived number with `partial`; it never calls an old implementation.

- [ ] **Step 6: Rewrite the public retriever as a thin R10 entrypoint**

`search_fault_standard(request)` constructs repositories/runtime from explicit R10 config and calls only `FaultStandardR10Runtime.run`. Remove imports of `shared.qwen4_retrieval.encode_live_query`, `v9_graph_adapter`, and the old calculator.

- [ ] **Step 7: Run tests**

```bash
python -m pytest etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_runtime.py etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_result_adapter.py etl/fault_cases/rag_runtime/agent_runtime/tests/test_agent_contract.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit the R10 runtime entrypoint**

```bash
git add etl/fault_cases/rag_runtime/fault_standard/r10/result_adapter.py etl/fault_cases/rag_runtime/fault_standard/r10/runtime.py etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_runtime.py etl/fault_cases/rag_runtime/fault_standard/r10/tests/test_result_adapter.py etl/fault_cases/rag_runtime/contracts/supervisor_contract.py etl/fault_cases/rag_runtime/agent_runtime/supervisor_input.py etl/fault_cases/rag_runtime/agent_runtime/tests/test_agent_contract.py etl/fault_cases/rag_runtime/fault_standard/retriever.py etl/fault_cases/rag_runtime/fault_standard/service.py
git commit -m "feat: expose r10 fault standard runtime"
```

---

### Task 11: Add the Internal Fault-Ratio Knowledge Orchestrator and Preserve the Public Agent

**Files:**
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/orchestrator.py`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/domains/__init__.py`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/domains/fault_standard_r10.py`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/tests/test_orchestrator.py`
- Create: `etl/fault_cases/src/agents/fault_ratio_knowledge/tests/test_fault_standard_r10.py`
- Modify: `etl/fault_cases/src/agents/text_ml_case_search/agent.py`
- Create: `etl/fault_cases/src/agents/text_ml_case_search/builders/fault_standard_evidence_builder.py`
- Create: `etl/fault_cases/src/agents/text_ml_case_search/tests/test_fault_standard_evidence_builder.py`
- Create: `etl/fault_cases/src/agents/text_ml_case_search/tests/test_fault_ratio_knowledge_integration.py`
- Modify: `etl/fault_cases/src/agents/text_ml_case_search/tests/test_agent_v2_output_schema.py`
- Modify: `etl/fault_cases/src/agents/text_ml_case_search/tests/test_supervisor_contract.py`
- Modify: `ai/agents/text_ml_case_search/agent.py`

**Interfaces:**
- Consumes: `FaultRatioKnowledgeRequest` from the existing public `text_ml_case_search`.
- Produces: `run_fault_ratio_knowledge(request, gateway=None) -> FaultRatioKnowledgeResult`.
- Public `node_code`, adapter import, owner, Supervisor envelope, and existing
  `StructuredResult` field set remain unchanged. R10-only fields stay internal.

- [ ] **Step 1: Write failing internal-core and public-boundary tests**

```python
def test_orchestrator_calls_qwen_once_and_returns_r10(monkeypatch) -> None:
    gateway = fake_gateway()
    monkeypatch.setattr(fault_standard_r10, "handle_request", fake_r10_handler)
    result = run_fault_ratio_knowledge(
        FaultRatioKnowledgeRequest(
            message_id="m1",
            query_text="교차로 직진 차량과 좌회전 차량 충돌",
            accident_facts=complete_facts(),
        ),
        gateway=gateway,
    )
    assert gateway.call_count == 1
    assert result.domains["fault_standard"]["calculation_result"]["release_id"] == R10_RELEASE_ID


def test_public_agent_keeps_text_ml_case_search_node(monkeypatch) -> None:
    monkeypatch.setattr(text_ml_agent, "run_fault_ratio_knowledge", fake_knowledge_result)
    result = text_ml_agent.run_text_ml_case_search(valid_agent_input())
    assert result["node_code"] == "text_ml_case_search"
    assert set(result) == {
        "contract_version",
        "node_code",
        "status",
        "structured_result",
        "evidence",
        "next_actions",
        "limitations",
        "missing_fields",
    }
    assert set(result["structured_result"]) == {
        "normalized_description",
        "accident_type_candidates",
        "issue_tags",
        "evidence_tags",
        "recommended_evidence",
        "insurer_claim_review",
        "similar_cases",
        "ratio_range_label",
        "display_evidence",
        "search_text",
        "rag_debug",
        "source_summary",
        "reliability_score",
        "limitations",
    }
    assert "fault_standard" not in result["structured_result"]
    assert "ratio_anchors" not in result["structured_result"]
    standard_evidence = [
        item for item in result["evidence"]
        if item.get("source_type") == "fault_standard"
    ]
    assert standard_evidence[0]["metadata"]["release_id"] == R10_RELEASE_ID


def test_ai_adapter_keeps_exact_supervisor_envelope(monkeypatch) -> None:
    monkeypatch.setattr(
        ai_adapter,
        "_run_fault_ratio_knowledge_agent",
        lambda **kwargs: supervisor_output_fixture(),
    )
    result = ai_adapter.run_text_ml_case_search(
        supervisor_agent_input(),
        {"node": {"node_name": "Text ML case search", "node_type": "agent"}},
    )
    assert set(result) == {
        "session_id",
        "message_id",
        "job_id",
        "node_name",
        "node_code",
        "node_type",
        "owner",
        "status",
        "summary",
        "structured_result",
        "evidence",
        "next_actions",
        "limitations",
        "created_at",
    }
    assert "fault_standard" not in result["structured_result"]
    assert "ratio_anchors" not in result["structured_result"]
```

- [ ] **Step 2: Implement the R10 domain adapter inside the new core**

```python
def search_fault_standard_r10(
    *,
    request: FaultRatioKnowledgeRequest,
    embedding: QueryEmbedding,
) -> dict[str, Any]:
    return handle_request(
        {
            "contract_version": "v1",
            "message_id": request.message_id,
            "query_text": request.query_text,
            "accident_facts": request.accident_facts,
            "query_embedding": embedding.to_dict(),
        }
    )
```

The domain adapter does not create the embedding and the R10 RAG never loads Qwen.

- [ ] **Step 3: Implement the internal orchestrator**

```python
def run_fault_ratio_knowledge(
    request: FaultRatioKnowledgeRequest,
    *,
    gateway: QwenQueryGateway | None = None,
) -> FaultRatioKnowledgeResult:
    active_gateway = gateway or build_gateway_from_environment()
    embeddings = active_gateway.embed(
        [
            EmbeddingJob(
                job_id="fault_standard",
                profile_id="fault_standard_r10",
                query_text=request.query_text,
            )
        ]
    )
    standard = search_fault_standard_r10(
        request=request,
        embedding=embeddings["fault_standard"],
    )
    return assemble_knowledge_result({"fault_standard": standard})
```

Implement result assembly without importing public `text_ml_case_search` builders:

```python
def assemble_knowledge_result(
    domains: dict[str, dict[str, Any]],
) -> FaultRatioKnowledgeResult:
    standard = domains["fault_standard"]
    calculation = standard.get("calculation_result") or {}
    evidence = tuple(standard.get("evidence") or ())
    candidates = ()
    if calculation:
        candidates = (
            {
                "source_type": "fault_standard",
                "release_id": calculation.get("release_id"),
                "rule_id": calculation.get("rule_id"),
                "ratio_source": calculation.get("ratio_source"),
                "a_ratio": calculation.get("a_ratio"),
                "b_ratio": calculation.get("b_ratio"),
                "source_party_ratio_range": calculation.get("source_party_ratio_range"),
                "party_mapping_status": calculation.get("party_mapping_status"),
                "user_ratio": calculation.get("user_ratio"),
                "opponent_ratio": calculation.get("opponent_ratio"),
                "user_ratio_range": calculation.get("user_ratio_range"),
                "opponent_ratio_range": calculation.get("opponent_ratio_range"),
            },
        )
    status = str(standard.get("status") or "failed")
    return FaultRatioKnowledgeResult(
        status=status if status in {"success", "partial", "failed"} else "failed",
        domains=domains,
        evidence=evidence,
        ratio_candidates=candidates,
        limitations=tuple(standard.get("limitations") or ()),
    )
```

Task 11 activates only the R10 domain. When 심의사례/판례 are upgraded later, the
orchestrator adds their jobs to this same list and still makes one batch gateway call.
`domains` and `ratio_candidates` are internal objects and must never be copied wholesale
into `structured_result`.

- [ ] **Step 4: Keep `text_ml_case_search` as a compatibility adapter**

The existing agent continues to:

1. validate and normalize Supervisor input;
2. run the current review-case/precedent case-search pipeline;
3. call `run_fault_ratio_knowledge` once for R10;
4. map the internal R10 result to the existing public `Evidence` item shape;
5. merge only those mapped evidence items and existing scalar builder results;
6. discard internal `domains` and `ratio_candidates` at the public boundary;
7. return the unchanged Supervisor envelope.

Do not register `fault_ratio_knowledge` in capability catalog, routing intent, node
definitions, readiness node list, or frontend node mappings.

- [ ] **Step 5: Convert R10 to the existing evidence shape without extending output**

Implement:

```python
def build_fault_standard_evidence(
    *,
    domain_result: dict[str, Any],
    query_text: str,
) -> list[dict[str, Any]]:
    calculation = domain_result.get("calculation_result") or {}
    selected = domain_result.get("selected_rule") or {}
    return [
        {
            "source_type": "fault_standard",
            "title": str(selected.get("title") or "자동차사고 과실비율 인정기준"),
            "source_reference": (
                f"fault_standard_r10:{calculation.get('rule_id') or selected.get('rule_id')}"
            ),
            "metadata": {
                "release_id": calculation.get("release_id"),
                "rule_id": calculation.get("rule_id") or selected.get("rule_id"),
                "ratio_source": calculation.get("ratio_source"),
                "a_ratio": calculation.get("a_ratio"),
                "b_ratio": calculation.get("b_ratio"),
                "source_party_ratio_range": calculation.get("source_party_ratio_range"),
                "party_mapping_status": calculation.get("party_mapping_status"),
                "user_ratio": calculation.get("user_ratio"),
                "opponent_ratio": calculation.get("opponent_ratio"),
                "user_ratio_range": calculation.get("user_ratio_range"),
                "opponent_ratio_range": calculation.get("opponent_ratio_range"),
                "score": selected.get("score"),
                "rank": selected.get("rank"),
            },
            "chunk_text": str(selected.get("chunk_text") or ""),
            "search_text": query_text,
            "confidence": selected.get("score"),
        }
    ]
```

Return `[]` when the R10 domain failed before selecting a Rule. Do not add
`fault_standard`, `ratio_anchors`, `ratio_candidates`, `domains`, or
`calculation_result` as a new top-level or `structured_result` field. Keep
`similar_cases` limited to 심의사례/판례; mapped R10 evidence may be included in
top-level `evidence` and transformed by the existing `display_evidence` builder.

- [ ] **Step 6: Record R10 after the case retriever without changing its configuration**

```python
active_sources = source_summary.setdefault("active_sources", [])
if "fault_standard" not in active_sources:
    active_sources.append("fault_standard")
source_counts = source_summary.setdefault("source_counts", {})
source_statuses = source_summary.setdefault("source_statuses", {})
source_counts["fault_standard"] = len(r10_evidence)
source_statuses["fault_standard"] = r10_status
source_results = rag_debug.setdefault("source_results", {})
source_results["fault_standard"] = {
    "status": r10_status,
    "release_id": R10_RELEASE_ID,
    "valid_evidence_count": len(r10_evidence),
}
```

Do not add `fault_standard` to `V2_ACTIVE_SOURCE_TYPES`: that configuration belongs to
the existing case pgvector pipeline. The existing review-case/precedent quota merger
continues to receive only those two case evidence lists. The compatibility adapter adds
R10 to the already-built dynamic summary/debug dictionaries afterward. Adding a
`fault_standard` map entry is data inside the existing dictionaries, not a new public
output field.

- [ ] **Step 7: Keep current case builders direction-safe**

Continue passing only case evidence to:

```text
build_similar_cases
build_insurer_claim_review
```

Compute the existing `ratio_range_label` field with this exact precedence:

```python
case_ratio_label = build_ratio_range_label(evidence=case_evidence)
ratio_range_label = case_ratio_label or build_r10_ratio_label(
    ratio_candidates=knowledge_result.ratio_candidates,
)
```

`build_r10_ratio_label` returns a user/opponent label only when
`party_mapping_status == "resolved"`. Otherwise it still returns the numeric source
direction, for example `인정기준 원문 기준 A 30 : B 70 (사용자 방향 미확정)`, or the
approved `variant_set_range`. It never flips A/B. Pass combined case + mapped R10
evidence to `build_display_evidence` and top-level `evidence`. This prevents an
인정기준 Rule from being mistaken for a 심의사례 while still providing the required
numeric fallback when case evidence has no range.

- [ ] **Step 8: Define agent status aggregation**

- case evidence ready + R10 success/partial: agent `success`;
- case evidence ready + R10 failed: agent `partial`;
- case evidence empty + R10 success/partial: agent `partial` with the R10 numeric value
  in the existing `ratio_range_label` and its provenance in `evidence.metadata`;
- all sources unavailable: agent `partial` or `failed` according to the existing input-validation boundary.

- [ ] **Step 9: Run internal-core and public-adapter tests**

```bash
python -m pytest etl/fault_cases/src/agents/fault_ratio_knowledge/tests etl/fault_cases/src/agents/text_ml_case_search/tests/test_fault_standard_evidence_builder.py etl/fault_cases/src/agents/text_ml_case_search/tests/test_fault_ratio_knowledge_integration.py etl/fault_cases/src/agents/text_ml_case_search/tests/test_agent_v2_output_schema.py etl/fault_cases/src/agents/text_ml_case_search/tests/test_supervisor_contract.py backend/chatbot/test_non_dl_analysis_reporting_smoke.py -v
```

Expected: PASS, `fault_ratio_knowledge` is not a public node, both public output key
snapshots are unchanged, and no R10-only internal object leaks into
`structured_result`.

- [ ] **Step 10: Commit the internal core and public adapter integration**

```bash
git add ai/agents/text_ml_case_search/agent.py etl/fault_cases/src/agents/fault_ratio_knowledge etl/fault_cases/src/agents/text_ml_case_search/agent.py etl/fault_cases/src/agents/text_ml_case_search/builders/fault_standard_evidence_builder.py etl/fault_cases/src/agents/text_ml_case_search/tests/test_fault_standard_evidence_builder.py etl/fault_cases/src/agents/text_ml_case_search/tests/test_fault_ratio_knowledge_integration.py etl/fault_cases/src/agents/text_ml_case_search/tests/test_agent_v2_output_schema.py etl/fault_cases/src/agents/text_ml_case_search/tests/test_supervisor_contract.py
git commit -m "feat: add fault ratio knowledge core"
```

---

### Task 12: Add R10 Configuration, AWS Loading, Readiness, and Smoke Checks

**Files:**
- Modify: `backend/config/settings.py`
- Modify: `.env.example`
- Modify: `deploy/aws-pilot/runtime.env.example`
- Modify: `deploy/aws-pilot/docker-compose.pilot.yml`
- Create: `backend/chatbot/management/commands/load_fault_standard_r10_seed.py`
- Modify: `deploy/aws-pilot/Load-Rag-Seed-Pilot.ps1`
- Modify: `backend/chatbot/readiness.py`
- Modify: `backend/chatbot/management/commands/check_production_readiness.py`
- Modify: `backend/chatbot/management/commands/smoke_text_ml_case_search.py`
- Modify: `deploy/aws-pilot/README.ko.md`
- Create: `backend/chatbot/test_fault_standard_r10_readiness.py`

**Interfaces:**
- Consumes: S3 R10 bundle URI/hash, RDS connection, Neo4j connection, RunPod endpoint configuration.
- Produces: validated DB load, readiness result, and smoke result without exposing secrets or vectors.

- [ ] **Step 1: Write failing settings/readiness tests**

Assert:

- legal OpenAI settings stay 1,024 dimensions;
- R10 Qwen settings are separate;
- R10 is not ready if endpoint ID, model revision, seed release, PostgreSQL counts, or Neo4j counts mismatch;
- readiness output never contains API keys, passwords, raw query text, or vectors.

- [ ] **Step 2: Add explicit settings**

```text
FAULT_STANDARD_R10_ENABLED=1
FAULT_RATIO_QWEN_PROVIDER=runpod
FAULT_RATIO_QWEN_ENDPOINT_ID=
FAULT_RATIO_QWEN_API_KEY=
FAULT_RATIO_QWEN_MODEL=Qwen/Qwen3-Embedding-4B
FAULT_RATIO_QWEN_REVISION=5cf2132abc99cad020ac570b19d031efec650f2b
FAULT_RATIO_QWEN_DIMENSIONS=2560
FAULT_RATIO_QWEN_TIMEOUT_SECONDS=60
FAULT_RATIO_QWEN_POLL_INTERVAL_SECONDS=0.5
FAULT_STANDARD_POSTGRES_HOST=
FAULT_STANDARD_POSTGRES_PORT=5432
FAULT_STANDARD_POSTGRES_USER=
FAULT_STANDARD_POSTGRES_PASSWORD=
FAULT_STANDARD_POSTGRES_DB=
FAULT_STANDARD_POSTGRES_SCHEMA=fault_standard_r10
FAULT_STANDARD_NEO4J_URI=bolt://law-neo4j:7687
FAULT_STANDARD_NEO4J_USER=neo4j
FAULT_STANDARD_NEO4J_PASSWORD=
FAULT_STANDARD_NEO4J_DATABASE=neo4j
FAULT_STANDARD_R10_RELEASE_ID=fault_standard_r10_9e86695d05190c6d
FAULT_STANDARD_R10_SEED_MANIFEST_SHA256=
```

Do not change:

```text
RAG_EMBEDDING_PROVIDER=openai
RAG_EMBEDDING_MODEL=text-embedding-3-large
RAG_EMBEDDING_DIMENSIONS=1024
LEGAL_RAG_QUERY_EMBEDDING_DIMENSIONS=1024
```

- [ ] **Step 3: Add the combined seed loader command**

`load_fault_standard_r10_seed` must:

1. validate the standalone R10 manifest;
2. load/validate PostgreSQL;
3. load/validate Neo4j;
4. write completion metadata only after both stores pass;
5. return non-zero on any mismatch.

- [ ] **Step 4: Extend the AWS seed script with a separate R10 prefix**

Add parameters:

```powershell
[string]$FaultStandardR10S3Uri,
[string]$FaultStandardR10ManifestRelativePath = "fault-standard-r10-manifest.json",
[string]$FaultStandardR10ManifestSha256
```

The script downloads to `/opt/skn27-pilot/fault-standard-r10-seed/<manifest_sha>`, verifies SHA-256, mounts read-only into `rag-loader`, runs `verify_fault_standard_r10_seed`, runs `load_fault_standard_r10_seed`, performs readiness/smoke, then removes the local seed directory.

- [ ] **Step 5: Add readiness and smoke checks**

Readiness verifies:

```text
PostgreSQL Rule=277
PostgreSQL search docs=6145
PostgreSQL embedding dimensions=2560
PostgreSQL release ID exact
Neo4j Rule=277
Neo4j duplicate Rule=0
Neo4j orphan required nodes=0
Qwen configured model/revision/dimension exact
```

Smoke executes one safe synthetic accident query and requires:

- adapter source `fault_ratio_knowledge_agent`;
- at least one top-level `evidence` item with `source_type="fault_standard"`;
- that evidence item's `metadata.release_id` exact and `metadata.ratio_source` present;
- `structured_result.source_summary.source_counts.fault_standard >= 1`;
- existing `structured_result.ratio_range_label` contains a numeric case range or the
  direction-safe R10 numeric fallback;
- no public `structured_result.fault_standard`, `ratio_anchors`, `ratio_candidates`,
  `domains`, or `calculation_result` field;
- no secrets/vectors in output.

- [ ] **Step 6: Run configuration/readiness tests**

```bash
python -m pytest backend/chatbot/test_fault_standard_r10_readiness.py backend/chatbot/tests.py::ChatbotCommandTests::test_text_ml_case_search_smoke_reports_pgvector_contract -v
```

Expected: PASS.

- [ ] **Step 7: Commit deployment support**

```bash
git add backend/config/settings.py .env.example deploy/aws-pilot/runtime.env.example deploy/aws-pilot/docker-compose.pilot.yml backend/chatbot/management/commands/load_fault_standard_r10_seed.py deploy/aws-pilot/Load-Rag-Seed-Pilot.ps1 backend/chatbot/readiness.py backend/chatbot/management/commands/check_production_readiness.py backend/chatbot/management/commands/smoke_text_ml_case_search.py deploy/aws-pilot/README.ko.md backend/chatbot/test_fault_standard_r10_readiness.py
git commit -m "feat: add r10 deployment readiness"
```

---

### Task 13: Reproduce COMPLETE30, Cut Over Directly, and Remove the Old Runtime

**Files:**
- Modify: `etl/fault_cases/rag_runtime/evaluation/evaluate_fault_standard_complete30.py`
- Create: `etl/fault_cases/rag_runtime/evaluation/tests/test_fault_standard_r10_complete30.py`
- Create: `backend/chatbot/management/commands/verify_fault_standard_r10_cutover.py`
- Delete: `etl/fault_cases/rag_runtime/fault_standard/calculator.py`
- Delete: `etl/fault_cases/rag_runtime/fault_standard/graph_schema.py`
- Delete: `etl/fault_cases/rag_runtime/fault_standard/neo4j_reranker.py`
- Delete: `etl/fault_cases/rag_runtime/fault_standard/utils.py`
- Delete: `etl/fault_cases/rag_runtime/fault_standard/v9_graph_adapter.py`
- Modify: `etl/fault_cases/rag_runtime/README.md`
- Modify: `etl/fault_cases/rag_runtime/database/README.md`

**Interfaces:**
- Consumes: approved COMPLETE30 question vectors for evaluation only and the loaded operational R10 stores.
- Produces: deterministic regression report and a cutover gate with no runtime legacy selector.

- [ ] **Step 1: Write the cutover gate tests**

```python
def test_cutover_gate_rejects_old_runtime_imports() -> None:
    report = inspect_runtime_imports()
    assert report["standard_test_import_count"] == 0
    assert report["legacy_fault_standard_import_count"] == 0
    assert report["version_selector_count"] == 0


def test_complete30_gate_matches_r10_floor() -> None:
    metrics = run_complete30()
    assert metrics["recall_at_50"] == 1.0
    assert metrics["c_hit_at_1"] >= 22 / 30
    assert metrics["final_ratio_exact"] >= 18 / 30
```

- [ ] **Step 2: Update the evaluator to inject only evaluation vectors**

The evaluator may construct `query_embedding` from the frozen R6 30 query records. Production agent requests may not read these vectors. Confirm runtime has no qrels/gold access and all three runs produce identical result hashes.

- [ ] **Step 3: Run the complete R10 verification matrix**

Unit and contract:

```bash
python -m pytest etl/fault_cases/src/agents/fault_ratio_knowledge/embedding/tests etl/fault_cases/src/agents/fault_ratio_knowledge/tests etl/fault_cases/rag_runtime/fault_standard/r10/tests etl/fault_cases/src/agents/text_ml_case_search/tests backend/chatbot/test_fault_standard_r10_seed_commands.py backend/chatbot/test_fault_standard_r10_readiness.py -v
```

Integration:

```bash
python -m pytest -m integration etl/fault_cases/rag_runtime/fault_standard/r10/tests -v
```

Evaluation:

```bash
python -m etl.fault_cases.rag_runtime.evaluation.evaluate_fault_standard_complete30
python backend/manage.py verify_fault_standard_r10_cutover --format json
```

Expected:

```text
Recall@50 = 30/30
C Hit@1 >= 22/30
Final Ratio Exact >= 18/30
three-run deterministic hash match
runtime gold/qrels access = 0
normal selected Rule numeric single/range result = 100%
```

- [ ] **Step 4: Remove the old operational implementation**

After every gate passes, delete the five old V9 operational modules listed above. Keep Git history as the only emergency recovery mechanism. Do not add a runtime environment switch or import fallback.

- [ ] **Step 5: Run import and smoke regression after deletion**

```bash
python -m pytest etl/fault_cases/rag_runtime/fault_standard/r10/tests etl/fault_cases/src/agents/text_ml_case_search/tests backend/chatbot/test_non_dl_analysis_reporting_smoke.py -v
python backend/manage.py smoke_text_ml_case_search --require-pgvector --format json
python backend/manage.py check_production_readiness --format json
```

Expected: PASS with R10 as the only 인정기준 runtime.

- [ ] **Step 6: Update runtime documentation**

Document:

- R10 release ID and Qwen contract;
- agent-owned embedding responsibility;
- S3 seed → PostgreSQL/Neo4j load path;
- `variant | rule_base | variant_set_range` policy;
- two variant-only Rules;
- direct cutover and Git redeploy recovery;
- absence of legacy/shadow modes.

- [ ] **Step 7: Commit the direct cutover**

```bash
git add etl/fault_cases/rag_runtime/evaluation/evaluate_fault_standard_complete30.py etl/fault_cases/rag_runtime/evaluation/tests/test_fault_standard_r10_complete30.py backend/chatbot/management/commands/verify_fault_standard_r10_cutover.py etl/fault_cases/rag_runtime/fault_standard etl/fault_cases/rag_runtime/README.md etl/fault_cases/rag_runtime/database/README.md
git commit -m "feat: cut over fault standard to r10"
```

---

## Production Execution Order

1. Build and publish the Qwen RunPod worker image pinned to the approved model revision.
2. Deploy the RunPod endpoint and inject endpoint ID/API key through the runtime secret path.
3. On the release-owner machine only, set explicit `R10_RELEASE_SOURCE_ROOT` to the
   approved local source and build the standalone R10 seed bundle.
4. Confirm the seed build reused the existing 78,002,144-byte GZ and made zero document-embedding model calls.
5. Verify the generated manifest locally.
6. Upload the immutable bundle to a versioned S3 prefix containing the manifest SHA.
7. Record the S3 manifest URI and exact manifest SHA in the Git release contract.
8. From a clean worktree where all three copied test folders are absent, download and
   verify the S3 seed and run unit/contract tests.
9. Deploy application code with `FAULT_STANDARD_R10_ENABLED=0`.
10. Run the AWS R10 seed loader against RDS and Neo4j.
11. Run R10 readiness and COMPLETE30 against the loaded stores.
12. Set `FAULT_STANDARD_R10_ENABLED=1` in the deployment configuration and redeploy.
13. Run `smoke_text_ml_case_search` and the Supervisor reporting smoke.
14. Confirm logs contain release ID/profile/status but no query text, vectors, API keys, or passwords.
15. Remove the enable flag from code in the final direct-cutover commit so the operational code has only the R10 path.

The temporary enable flag exists only across deployment commits to prevent traffic before seed readiness. The final repository state does not contain a legacy/R10 runtime selector.

## Acceptance Checklist

- [ ] 심의사례 RAG 교체의 안정 커밋과 테스트 결과를 기준점으로 반영한 뒤 R10 공개 어댑터 통합을 시작했다.
- [ ] R10 release/core/search/embedding hashes and counts match the approved manifests.
- [ ] Initial seed loading reuses the existing 78,002,144-byte GZ and performs zero corpus/document embedding calls.
- [ ] Future updates embed only added/changed document hashes and make zero model calls for unchanged-only updates.
- [ ] Qwen model is loaded once per worker and three future domain profiles can be embedded in one provider call.
- [ ] Only the R10 profile is active in this cutover.
- [ ] Legal OpenAI 1,024-dimensional query embedding remains unchanged.
- [ ] Runtime, normal development, and CI do not import or read `standard_TEST`, `review_case_test`, or `precedents_test`.
- [ ] A clean worktree with all three copied folders absent passes unit/contract tests and can verify the downloaded immutable S3 seed.
- [ ] RDS stores 277 Rules, 6,145 search documents, and 6,145 document vectors at 2,560 dimensions.
- [ ] The 30 evaluation query vectors are not inserted into an operational DB table.
- [ ] Neo4j R10 nodes are isolated by `FaultStandardR10` label and exact release ID.
- [ ] A/B/C candidate sets are identical and deterministic.
- [ ] Neo4j failure degrades to B without invoking old code.
- [ ] Variant ambiguity uses Rule base for 275 eligible Rules.
- [ ] The two variant-only Rules return `variant_set_range` rather than an invented single ratio.
- [ ] Unconfirmed adjustments are never applied.
- [ ] Unresolved party mapping never flips source parties into user/opponent arbitrarily.
- [ ] The real `text_ml_case_search` agent exposes R10 only through existing
  `evidence`, `display_evidence`, `source_summary`, `rag_debug`, and
  `ratio_range_label` fields.
- [ ] ETL `AgentOutput`, ETL `StructuredResult`, and the final AI adapter Supervisor
  envelope have exactly the pre-cutover field names and types; public
  `fault_standard`, `ratio_anchors`, `ratio_candidates`, `domains`, and
  `calculation_result` fields do not exist.
- [ ] `similar_cases` contains only 심의사례/판례; R10 evidence uses
  `source_type="fault_standard"`.
- [ ] When case evidence has no numeric range, the existing `ratio_range_label`
  returns the R10 numeric ratio/range without inventing user/opponent direction.
- [ ] Supervisor and capability catalog expose only `text_ml_case_search`; `fault_ratio_knowledge` remains an internal package.
- [ ] The public adapter contains no Qwen model loading or R10 storage queries.
- [ ] Existing review-case/precedent paths and Supervisor envelope remain compatible.
- [ ] COMPLETE30 meets Recall@50 30/30, C Hit@1 at least 22/30, and Final Ratio Exact at least 18/30.
- [ ] No runtime `legacy | shadow | r10` mode or old-code fallback remains.
- [ ] Production smoke and readiness pass before traffic is enabled.
