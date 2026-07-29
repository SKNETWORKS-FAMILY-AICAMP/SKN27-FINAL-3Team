# 승인 기반 법령 RAG Neo4j 적재 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 승인된 법령 데이터 버전을 PostgreSQL/pgvector와 EC2 내부 법령 전용 Neo4j에 함께 적재하고, 모두 검증된 경우에만 Pilot runtime이 graph evidence를 사용하게 한다.

**Architecture:** PostgreSQL/pgvector는 유일한 벡터 검색 backend로 유지한다. Neo4j graph는 검증된 `production_rag_seed_manifest.v1`의 `legal_chunks`에서 파생하며, source/version/chunk/용어/조문 관계를 보관한다. SSM 승인 job은 seed bundle을 검증하고 PostgreSQL 적재 뒤 Neo4j 적재·parity 검증을 실행하며, 모든 결과가 성공해야 active marker를 쓴다.

**Tech Stack:** Python 3.14, Django management commands, Neo4j Python driver 6.2, Neo4j 5 Community, PostgreSQL 16/pgvector, Docker Compose, AWS SSM/S3/ECR, pytest.

## Global Constraints

- 기존 `production_rag_seed_manifest.v1`의 네 artifact와 승인 SHA-256을 변경하지 않는다.
- `LEGAL_RAG_VECTOR_ENABLED=1`과 PostgreSQL/pgvector 검색 우선순위를 바꾸지 않는다.
- Neo4j는 `law-neo4j` 전용 컨테이너·전용 named volume·내부 Docker network만 사용하며 host port를 노출하지 않는다.
- 법령 Neo4j와 `fault-standard-neo4j` 또는 local `neo4j`는 컨테이너·volume·secret·환경변수를 공유하지 않는다.
- OpenAI 임베딩과 RAG seed 쓰기는 승인된 SSM ingestion job에서만 수행한다. 테스트는 외부 provider를 호출하지 않는다.
- graph가 실패하거나 manifest metadata가 일치하지 않으면 새 dataset version을 active로 표시하지 않는다.

---

### Task 1: Pilot 법령 Neo4j runtime 계약을 추가한다

**Files:**
- Modify: `test/test_aws_pilot_infrastructure.py:260-310`
- Modify: `deploy/aws-pilot/docker-compose.pilot.yml`
- Modify: `deploy/aws-pilot/runtime.env.example`
- Modify: `docs/ops/production-env.md`

**Interfaces:**
- Consumes: `LAW_NEO4J_IMAGE_REF`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`, `LAW_GRAPH_REQUIRED`.
- Produces: private `law-neo4j:7687` service reachable to backend and seed-maintenance compose jobs.

- [ ] **Step 1: Write the failing compose contract test**

Change the Pilot infrastructure test so it requires `law-neo4j`, its `law_neo4j_data` volume, a healthcheck, and no `ports`. Keep `postgres`, `kibana`, and `elasticsearch` disallowed.

```python
assert "law-neo4j" in services
assert "ports" not in services["law-neo4j"]
assert "law_neo4j_data" in compose["volumes"]
assert {"postgres", "kibana", "elasticsearch"}.isdisjoint(services)
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest test/test_aws_pilot_infrastructure.py -k low_cost_runtime -q`

Expected: FAIL because the current Pilot compose disables and excludes Neo4j.

- [ ] **Step 3: Implement the private Neo4j service**

Add `law-neo4j` with a pinned `${LAW_NEO4J_IMAGE_REF}`, `NEO4J_AUTH=neo4j/${NEO4J_PASSWORD}`, memory limit, `cypher-shell` healthcheck, no host port, and a dedicated volume. Add `NEO4J_URI=bolt://law-neo4j:7687`, credentials, database, image ref, and `LAW_GRAPH_REQUIRED=1` to the runtime template. Document that real passwords remain only in SSM SecureString.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest test/test_aws_pilot_infrastructure.py -k low_cost_runtime -q`

Expected: PASS, including the no-external-port assertion.

- [ ] **Step 5: Commit**

```powershell
git add test/test_aws_pilot_infrastructure.py deploy/aws-pilot/docker-compose.pilot.yml deploy/aws-pilot/runtime.env.example docs/ops/production-env.md
git commit -m "feat: add private legal Neo4j pilot runtime"
```

### Task 2: Validated RAG seed에서 결정적 법령 graph를 파생한다

**Files:**
- Create: `app/services/law_graph_seed.py`
- Create: `test/test_law_graph_seed.py`
- Modify: `etl/legal/extract_extra_relations.py`
- Modify: `etl/legal/export_neo4j.py`

**Interfaces:**
- Consumes: `RagSeedBundle`, `iter_rag_seed_jsonl`, `storage/rag/law_query_terms.yaml`.
- Produces: `LawGraphSeed(dataset_version, manifest_sha256, canonical_chunk_sha256, sources, versions, chunks, relations, hint_terms)`.

- [ ] **Step 1: Write the failing deterministic graph-seed test**

Create a minimal valid v1 bundle fixture and prove `build_law_graph_seed()` preserves legal chunk IDs, creates stable source/version IDs, deduplicates relations, and produces the same canonical digest after JSONL row order changes.

```python
def test_graph_seed_is_deterministic_for_verified_legal_chunks(valid_bundle, hint_terms_path):
    first = build_law_graph_seed(valid_bundle, hint_terms_path)
    second = build_law_graph_seed(valid_bundle, hint_terms_path)
    assert first.canonical_chunk_sha256 == second.canonical_chunk_sha256
    assert [row["chunk_id"] for row in first.chunks] == ["law:1", "law:2"]
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest test/test_law_graph_seed.py -q`

Expected: FAIL with missing `app.services.law_graph_seed`.

- [ ] **Step 3: Implement graph-seed derivation**

Read only the already-validated `legal_chunks` artifact. Derive stable version IDs from source and effective-date fields, reuse `build_extra_relations`, and calculate the canonical digest from sorted chunk IDs. Adapt `export_neo4j.py` to import this object in bounded `MERGE` batches. Do not create `SIMILAR_TO` relationships or copy embeddings to Neo4j.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest test/test_law_graph_seed.py test/unit/test_legal_law_graph_relations.py -q`

Expected: PASS; the existing relation importer remains compatible.

- [ ] **Step 5: Commit**

```powershell
git add app/services/law_graph_seed.py etl/legal/extract_extra_relations.py etl/legal/export_neo4j.py test/test_law_graph_seed.py test/unit/test_legal_law_graph_relations.py
git commit -m "feat: derive legal graph from verified RAG seed"
```

### Task 3: Neo4j import, metadata, and readiness를 구현한다

**Files:**
- Create: `backend/chatbot/management/commands/load_legal_graph_seed.py`
- Create: `backend/chatbot/management/commands/verify_legal_graph_readiness.py`
- Create: `test/test_legal_graph_seed_commands.py`
- Modify: `backend/chatbot/readiness.py`
- Modify: `backend/chatbot/tests.py`

**Interfaces:**
- Consumes: manifest path, Neo4j runtime variables, `LEGAL_RAG_SEED_MANIFEST_SHA256`, `LEGAL_DATASET_VERSION`.
- Produces: `LegalGraphDataset {dataset_version, manifest_sha256, canonical_chunk_sha256}` metadata and redacted node/relationship counts.

- [ ] **Step 1: Write the failing import/readiness tests**

Use a fake driver/session to assert constraint creation, bounded `MERGE` imports, and metadata creation only after all graph batches succeed. Assert readiness fails for unavailable Neo4j, mismatched manifest SHA, and mismatched active PostgreSQL/Neo4j chunk counts.

```python
def test_graph_readiness_rejects_manifest_mismatch(settings, fake_graph):
    settings.LAW_GROUND_SEARCH_ENABLE_NEO4J = "1"
    settings.LEGAL_RAG_SEED_MANIFEST_SHA256 = "a" * 64
    fake_graph.metadata_manifest_sha256 = "b" * 64
    assert check_legal_graph_readiness()["status"] == "fail"
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest test/test_legal_graph_seed_commands.py backend/chatbot/tests.py -k neo4j -q`

Expected: FAIL because graph commands and required graph readiness are absent.

- [ ] **Step 3: Implement idempotent import and real readiness**

Validate v1 seed before opening Neo4j; import graph data; then write `LegalGraphDataset`. Verify connectivity, required constraints, metadata manifest SHA, canonical digest, active chunk count, and one hint-term/Cypher expansion query. Extend `_law_ground_search_sync_check` only when both graph flags are true. Never log credentials, raw user query text, or raw provider exceptions.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest test/test_legal_graph_seed_commands.py backend/chatbot/tests.py -k neo4j -q`

Expected: PASS, with disabled local Neo4j behavior unchanged.

- [ ] **Step 5: Commit**

```powershell
git add backend/chatbot/management/commands/load_legal_graph_seed.py backend/chatbot/management/commands/verify_legal_graph_readiness.py backend/chatbot/readiness.py backend/chatbot/tests.py test/test_legal_graph_seed_commands.py
git commit -m "feat: verify legal Neo4j graph seed"
```

### Task 4: 승인 기반 seed build와 Pilot maintenance를 graph-aware로 만든다

**Files:**
- Modify: `etl/legal/run_pipeline.py`
- Create: `backend/chatbot/management/commands/build_approved_legal_rag_seed.py`
- Create: `test/test_approved_legal_rag_seed.py`
- Modify: `deploy/aws-pilot/Load-Rag-Seed-Pilot.ps1`
- Modify: `deploy/aws-pilot/Deploy-Pilot.ps1`
- Modify: `test/test_aws_pilot_infrastructure.py`

**Interfaces:**
- Consumes: operator-selected `dataset_version`, legal source configuration, `--allow-paid-embedding`, and versioned S3 prefix under `_rag-seed/`.
- Produces: v1 JSONL bundle, manifest, metadata-only CSV audit index, graph evidence, and `.production-rag-seed.complete` after all readiness checks.

- [ ] **Step 1: Write the failing orchestration tests**

Require the approved builder to use legal ingestion, 1024-dimensional OpenAI embedding, v1 manifest double-validation, and CSV without embedding values. Require Pilot loading to start `law-neo4j`, run legal pgvector loading before graph loading, run graph readiness, then write the complete marker.

```python
assert "load_legal_graph_seed" in loader
assert loader.index("load_production_rag_seed") < loader.index("load_legal_graph_seed")
assert loader.index("verify_legal_graph_readiness") < loader.index(".production-rag-seed.complete")
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest test/test_approved_legal_rag_seed.py test/test_aws_pilot_infrastructure.py -k "rag_seed or low_cost_runtime" -q`

Expected: FAIL because no graph-aware approved build or maintenance sequence exists.

- [ ] **Step 3: Implement approved build and maintenance sequence**

Implement a command requiring `--dataset-version`, source config, output root, and `--allow-paid-embedding`. It runs existing legal ingestion and OpenAI embedding stages, packages the existing four v1 artifacts, validates twice, and emits a CSV audit index without vectors. Update Pilot maintenance to stage `law-neo4j`, load review-case and legal pgvector data, load/verify graph from the exact mounted bundle, and write the completion marker only on success. Update deploy service expectations to health-check `law-neo4j` without opening a host port.

- [ ] **Step 4: Verify GREEN and parse deployment scripts**

Run:

```powershell
python -m pytest test/test_approved_legal_rag_seed.py test/test_aws_pilot_infrastructure.py -k "rag_seed or low_cost_runtime" -q
pwsh -NoProfile -Command "[void][System.Management.Automation.Language.Parser]::ParseFile('deploy/aws-pilot/Load-Rag-Seed-Pilot.ps1',[ref]`$null,[ref]`$null); [void][System.Management.Automation.Language.Parser]::ParseFile('deploy/aws-pilot/Deploy-Pilot.ps1',[ref]`$null,[ref]`$null)"
```

Expected: pytest PASS and no PowerShell parser errors.

- [ ] **Step 5: Commit**

```powershell
git add etl/legal/run_pipeline.py backend/chatbot/management/commands/build_approved_legal_rag_seed.py deploy/aws-pilot/Load-Rag-Seed-Pilot.ps1 deploy/aws-pilot/Deploy-Pilot.ps1 test/test_approved_legal_rag_seed.py test/test_aws_pilot_infrastructure.py
git commit -m "feat: automate approved legal graph seed loading"
```

### Task 5: 법령 graph evidence와 배포 검증을 종합한다

**Files:**
- Modify: `test/test_legal_rag_service.py`
- Modify: `test/test_law_ground_contract.py`
- Modify: `docs/ops/production-rag-seed.md`
- Modify: `docs/ops/project-readiness-master-checklist.md`

**Interfaces:**
- Consumes: verified graph runtime, graph metadata, and real pgvector top results.
- Produces: law-ground evidence whose retrieval backend remains `postgres_pgvector` and whose graph state is `disabled`, `verified`, or `unavailable`.

- [ ] **Step 1: Write the failing graph evidence tests**

Assert that pgvector remains the retrieval backend, verified graph expansion adds only linked legal references, and required graph failure returns an explicit unavailable/error state instead of claiming graph-enhanced evidence.

```python
assert result["backend"] == "postgres_pgvector"
assert result["graph_expansion"]["status"] == "verified"
assert all(item["source_reference"] for item in result["results"])
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest test/test_legal_rag_service.py test/test_law_ground_contract.py -q`

Expected: FAIL because verified graph state is not in the result contract.

- [ ] **Step 3: Implement provenance-safe graph state**

Expose only `disabled`, `verified`, or `unavailable`; never expose Neo4j URI, graph counts, manifest SHA, or raw failures to public payloads. Update RAG documentation so pgvector-only means vector retrieval only and Neo4j is a verified graph-evidence dependency for Pilot.

- [ ] **Step 4: Verify relevant full regression**

Run:

```powershell
python -m pytest test/test_law_graph_seed.py test/test_legal_graph_seed_commands.py test/test_approved_legal_rag_seed.py test/test_legal_rag_service.py test/test_law_ground_contract.py test/test_pgvector_rag_readiness.py test/test_production_rag_seed.py test/test_aws_pilot_infrastructure.py -q
python backend/manage.py test chatbot
```

Expected: all tests pass without external provider calls.

- [ ] **Step 5: Commit**

```powershell
git add test/test_legal_rag_service.py test/test_law_ground_contract.py docs/ops/production-rag-seed.md docs/ops/project-readiness-master-checklist.md
git commit -m "test: verify legal graph evidence readiness"
```

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-28-approved-legal-rag-neo4j-ingestion.md`.

Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task and review between tasks.
2. **Inline Execution** — execute the tasks in this session with checkpoints.
