# PGVector-only RAG Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all active Elasticsearch, Kibana, AWS OpenSearch, BM25/Nori, and lexical/Django RAG fallback paths. Serve law, review-case, and fault-ratio-precedent retrieval exclusively from their existing PostgreSQL pgvector stores while preserving the public text-ML evidence contract.

**Architecture:** Keep each corpus in its existing embedding space (law: 1024 dimensions; review-case and fault-ratio precedent: 1536 dimensions). Add one text-ML pgvector adapter that queries both precedent stores independently, normalizes their rows into the existing evidence mapper contract, then validates and quota-merges them. The legal service becomes a strict pgvector-only service. Source-specific loaders perform review-case and fault-ratio source loading/re-embedding; the Django management command loads only legal data and verifies all three stores, never inventing source records from the abbreviated seed manifest.

**Tech Stack:** Python 3.12, Django management commands, PostgreSQL + pgvector/HNSW, OpenAI embeddings, Docker Compose, PowerShell pilot deployment automation, Terraform, pytest.

## Global Constraints

- [ ] Work only in `D:\dev\project\SKN27-FINAL-3Team-issue-291` on `feat-291-pgvector-only-rag`. The user owns Git staging, commit, push, PR, merge, issue, and worktree commands.
- [ ] Do not remove historical reports under `docs/`; remove active executable code, dependency, schema, compose, deployment, and Terraform references only.
- [ ] Preserve Django `SourceDocument`, `RagChunk`, and their migrations/fixtures. Remove only the `django_rag_tables` search backend and review-case lexical caller; physical cleanup of retained generic table rows is out of scope.
- [ ] Do not silently force all corpora to a common vector dimension. Validate provider/model/dimensions within each corpus before querying it.
- [ ] Preserve the text-ML V2 contract: `contract_version="text_ml_case_search_v2"`, `adapter_source="fault_ratio_knowledge_agent"`, `similar_cases`, `recommended_evidence`, `source_summary`, and source quota behavior.
- [ ] A failing review-case retrieval must not suppress healthy fault-ratio evidence (and vice versa); expose `partial` with source-level diagnostics rather than use a law or lexical fallback.
- [ ] No live database, Terraform apply/destroy, OpenSearch domain deletion, or production re-embedding occurs during code implementation. The post-merge operator runbook performs those actions only after backup and verification.

## Task 1: Establish pgvector-only retrieval contract tests

**Files:**
- Create: `etl/fault_cases/src/agents/text_ml_case_search/tests/test_pgvector_unified_retriever.py`
- Modify: `etl/fault_cases/src/agents/text_ml_case_search/tests/test_agent_skeleton.py`
- Modify: `etl/fault_cases/src/agents/text_ml_case_search/tests/test_agent_v2_output_schema.py`
- Modify: `test/test_agent_node_service.py`

- [ ] Write failing, database-free tests that monkeypatch both existing pgvector retrievers and prove the unified result has `retriever="unified_pgvector"`, normalized source names, V2 evidence fields, and unchanged per-source quotas.
- [ ] Add cases for blank query, no result, review-case failure with healthy fault-ratio result, and fault-ratio failure with healthy review-case result. Assert the one-source cases return `partial`, preserve healthy evidence, and contain no ES or legal-search fallback call.
- [ ] Replace test fixtures that model an Elasticsearch client or `_optional_elasticsearch_client()` with normalized pgvector row fixtures. Keep public-agent assertions focused on output fields rather than private implementation details.

Run:

```powershell
D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q etl/fault_cases/src/agents/text_ml_case_search/tests/test_pgvector_unified_retriever.py etl/fault_cases/src/agents/text_ml_case_search/tests/test_agent_skeleton.py etl/fault_cases/src/agents/text_ml_case_search/tests/test_agent_v2_output_schema.py test/test_agent_node_service.py -p no:cacheprovider
```

Expected: the new tests initially fail because no pgvector unified retriever exists; they pass only after Tasks 2 and 3.

## Task 2: Implement normalized two-source pgvector retrieval

**Files:**
- Create: `etl/fault_cases/src/agents/text_ml_case_search/rag/pgvector_unified_retriever.py`
- Modify: `etl/fault_cases/src/agents/text_ml_case_search/rag/evidence_merger.py`
- Reuse without changing public behavior: `etl/fault_cases/src/agents/text_ml_case_search/rag/evidence_mapper.py`, `fault_ratio_precedent_evidence_mapper.py`, and `evidence_validator.py`
- Call: `etl/fault_cases/src/review_case/search/pgvector/retriever.py:search_query`
- Call: `etl/fault_cases/src/traffic_precedents/precedent_search/pgvector/retriever.py:search_query`

- [ ] Move or reuse the pure query-text selection logic without importing an Elasticsearch protocol or client.
- [ ] Query review-case and fault-ratio stores independently. Convert each returned pgvector row to the existing mapper input shape: retain original fields, set `retriever` to `review_case_pgvector` or `fault_ratio_precedent_pgvector`, set `retriever_score` from `cosine_similarity`, set `score_type="cosine_similarity"`, and use empty highlight/index values where the mapper requires them.
- [ ] Feed normalized rows through the existing mapper, validator, and quota merger. Return selected text, source results, source summary, source diagnostics, and `retriever="unified_pgvector"` in a stable internal result.
- [ ] Catch a source-specific database/embedding exception at the source boundary, report a safe source diagnostic, and continue the other source. Do not catch programming errors broadly enough to hide them in tests.
- [ ] Replace Elasticsearch/BM25-specific language in `evidence_merger.py` comments with score-normalization language appropriate for independent pgvector stores.

Run:

```powershell
D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q etl/fault_cases/src/agents/text_ml_case_search/tests/test_pgvector_unified_retriever.py -p no:cacheprovider
```

Expected: all unit cases pass without network access, an Elasticsearch package, or a running database.

## Task 3: Route text-ML runtime through pgvector and retain V2

**Files:**
- Modify: `etl/fault_cases/src/agents/text_ml_case_search/agent.py`
- Modify: `etl/fault_cases/src/agents/text_ml_case_search/rag/search_text_builder.py`
- Modify: `etl/fault_cases/src/agents/text_ml_case_search/run_agent_sample.py`
- Modify: `etl/fault_cases/src/agents/text_ml_case_search/run_full_optional_inputs.py`
- Modify: `etl/fault_cases/src/agents/text_ml_case_search/build_full_optional_report.py`
- Modify: `ai/agents/text_ml_case_search/agent.py`
- Modify: `app/services/agent_node_service.py`
- Modify tests from Task 1

- [ ] Remove `es_client` from `run_text_ml_case_search()` and make V2 contract selection independent of the backend client. Normal requests invoke the unified pgvector retriever; tests may still inject already-normalized evidence through an explicit test seam if one exists.
- [ ] Replace the outer adapter’s optional Elasticsearch client/ping flow with the pgvector agent invocation. Remove its top-level `search_legal_rag(..., source_type="review_case")` fallback entirely.
- [ ] Preserve `adapter_source`, `similar_cases`, `recommended_evidence`, `source_summary`, and quota output for healthy retrieval. Return a structured unavailable/partial response for pgvector failures; never downgrade to a non-V2 result merely because a source is unavailable.
- [ ] Remove `TEXT_ML_CASE_SEARCH_SYNC_USE_ES` handling and ES-specific operational limitation strings from `app/services/agent_node_service.py` and all sample/report commands. Update command help and report text to describe pgvector validation.

Run:

```powershell
D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q etl/fault_cases/src/agents/text_ml_case_search/tests test/test_agent_node_service.py -p no:cacheprovider
```

Expected: V2 response tests pass; no test imports or constructs an Elasticsearch client.

## Task 4: Make legal retrieval strictly pgvector-only

**Files:**
- Modify: `app/services/legal_rag_service.py`
- Modify: `test/test_legal_rag_service.py`
- Modify: `test/test_legal_rag_evaluation_environment.py`
- Modify: `test/test_legal_rag_evaluation.py`

- [ ] Remove `POSTGRES_LEXICAL_BACKEND`, `DJANGO_RAG_BACKEND`, `_search_law_chunks_lexical()`, `_search_django_rag_tables()`, and `DJANGO_ONLY_SOURCE_TYPES` routing. Keep the `SearchResult` response schema but report only `postgres_pgvector` outcomes.
- [ ] Make invalid or missing requested backend resolve to the pgvector-only path rather than re-enabling a deprecated backend. Preserve distinct `ready`, `empty`, `unavailable`, and `embedding_space_mismatch` outcomes.
- [ ] Keep the strict 1024-dimension law embedding validation and configure tests so `LEGAL_RAG_VECTOR_ENABLED=1` is the required deployment/evaluation state. Remove tests that expect a lexical or Django fallback.

Run:

```powershell
D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q test/test_legal_rag_service.py test/test_legal_rag_evaluation_environment.py test/test_legal_rag_evaluation.py -p no:cacheprovider
```

Expected: pgvector-only service contracts pass and no fallback function is reachable.

## Task 5: Replace ES seeding/readiness with legal-load plus three-store verification

**Files:**
- Modify: `app/services/rag_seed_bundle.py`
- Modify: `backend/chatbot/management/commands/load_production_rag_seed.py`
- Create: `backend/chatbot/management/commands/verify_pgvector_rag_readiness.py`
- Modify: `backend/chatbot/management/commands/smoke_text_ml_case_search.py`
- Modify: `backend/chatbot/readiness.py`
- Modify: `test/test_production_rag_seed.py`
- Modify: `backend/chatbot/tests.py`
- Modify: `test/test_fault_rag_recovery_compose_contract.py`

- [ ] Delete ES index-name validation, ES bulk-index functions, `--recreate-es`, and all ES result fields from the seed bundle/loader. Retain manifest integrity checks and legal `--replace-legal` atomic load.
- [ ] Implement a read-only verifier for law, review-case, and fault-ratio stores. For each store, verify connection/queryability, chunk-to-embedding count expectations, provider/model/dimensions metadata, and its HNSW index. Return machine-readable domain results; a failed required domain makes the command nonzero.
- [ ] Do not create review-case or fault-ratio source records from manifest chunks. Their production preparation remains the existing source-specific commands: `etl/fault_cases/src/review_case/db_loading/run_db_load.py`, `etl/fault_cases/src/review_case/embedding/run_embedding.py`, `etl/fault_cases/src/review_case/search/pgvector/create_index.py`, `etl/fault_cases/src/traffic_precedents/precedent_db_loading/load_fault_ratio_precedents.py`, `etl/fault_cases/src/traffic_precedents/precedent_embedding/before_embedding/embed_fault_ratio_chunks.py`, and `etl/fault_cases/src/traffic_precedents/precedent_search/pgvector/create_indexes.py`.
- [ ] Replace smoke `--require-es` with `--require-pgvector`; assert `retrieval_backend="unified_pgvector"`, V2 fields, and nonempty results when `--require-results` is selected. Readiness must report actual pgvector domain faults, never "ES unavailable".
- [ ] Test all paths with fake DB/query/embedding dependencies and assert no code imports `elasticsearch` or relies on an ES environment variable.

Run:

```powershell
D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q test/test_production_rag_seed.py backend/chatbot/tests.py test/test_fault_rag_recovery_compose_contract.py -p no:cacheprovider
```

Expected: legal load and three-store verification are deterministic in tests, and `--require-pgvector` replaces every `--require-es` contract.

## Task 6: Remove active Elasticsearch/BM25/Nori Python modules and dependencies

**Files:**
- Delete: `etl/fault_cases/src/agents/text_ml_case_search/rag/bm25_nori_retriever.py`, `es_client.py`, `fault_ratio_precedent_retriever.py`, `retrieval_pipeline.py`, `unified_retriever.py`
- Delete corresponding tests: `test_bm25_nori_retriever.py`, `test_es_client.py`, `test_fault_ratio_precedent_retriever.py`, `test_retrieval_pipeline.py`, `test_unified_retriever.py`
- Delete: `etl/fault_cases/src/review_case/search/elasticsearch/`
- Delete: `etl/fault_cases/src/traffic_precedents/precedent_search/elasticsearch/`
- Modify/delete callers in: `etl/fault_cases/src/review_case/db_loading/db_config.py`, `etl/fault_cases/src/traffic_precedents/precedent_search/search_config.py`, and `etl/fault_cases/src/traffic_precedents/precedent_search/traffic_law/bm25_nori_retriever.py`
- Modify: `requirements.txt`

- [ ] Delete only modules whose active purpose is Elasticsearch/BM25/Nori. Keep pgvector retrieval modules and the separate `etl/fault_cases/rag_runtime/` subsystem unless an actual import proves it is an ES-only caller.
- [ ] Remove `elasticsearch` and `opensearch-py` package requirements and their explanatory comments. Remove unused ES settings/data classes and test imports left by the deletion.
- [ ] Add a lightweight repository contract test or extend the existing deployment contract tests to reject active Python imports of `elasticsearch`/`opensearchpy` and active ES backend setting names while excluding historical `docs/` evidence.

Run:

```powershell
D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q etl/fault_cases/src/agents/text_ml_case_search/tests test/test_production_hardening_contract.py -p no:cacheprovider
rg -n --glob '!docs/**' --glob '!**/*.md' 'from elasticsearch|import elasticsearch|opensearchpy|TEXT_ML_CASE_SEARCH_SYNC_USE_ES' D:\dev\project\SKN27-FINAL-3Team-issue-291
```

Expected: pytest passes; the ripgrep command has no active-code matches (test assertions that intentionally check absence may remain only if clearly named as such).

## Task 7: Remove ES/OpenSearch runtime, compose, schema, and Terraform assets

**Files:**
- Modify: `docker-compose.yml`, `.env.example`, `.env.production.example`, `deploy/aws-pilot/runtime.env.example`
- Modify: `deploy/aws-pilot/docker-compose.pilot.yml`, `deploy/aws-pilot/Deploy-Pilot.ps1`, `deploy/aws-pilot/Rollback-Pilot.ps1`, `deploy/aws-pilot/Load-Rag-Seed-Pilot.ps1`
- Delete: `infra/elasticsearch/Dockerfile`
- Modify: `infra/terraform/main.tf`, `infra/terraform/variables.tf`, `infra/terraform/outputs.tf` and related Terraform files found by `rg -l 'OpenSearch|opensearch|Nori|TEXT_ML_CASE_SEARCH_PROVIDER' infra/terraform`
- Modify: `infra/terraform-pilot/variables.tf`, `infra/terraform-pilot/user_data.sh.tftpl` when the text is active ES capacity/configuration
- Modify: `storage/schemas/review_case_db_schema.sql`, `storage/schemas/precedent_db_schema.sql`
- Create: `storage/migrations/20260722_remove_es_search_artifacts.sql`
- Modify: `test/test_aws_pilot_infrastructure.py`, `test/test_deployment_readiness_artifacts.py`, `test/test_production_hardening_contract.py`

- [ ] Remove Elasticsearch/Kibana services, healthchecks, volumes, networks, image build/push, fixed IPs, env files, deployment manifest fields, release cleanup, rollback digest checks, and ES seed/smoke flags. Enable the documented legal pgvector runtime settings in pilot/example configuration without exposing secrets.
- [ ] Remove the AWS OpenSearch domain, Nori package association, ES/OpenSearch IAM policies, variables, outputs, and runtime environment injection from Terraform. Change only configuration code; do not execute `terraform apply` or destroy cloud resources.
- [ ] Remove ES-specific chunk columns and index-job tables from fresh schema SQL. Add an idempotent SQL migration using `DROP ... IF EXISTS` for existing DBs; it must document the prerequisite backup and successful per-domain re-embedding/HNSW verification.
- [ ] Update pilot orchestration so source-specific review/fault pgvector preparation is an explicit precondition, followed by the read-only three-store verifier, legal seed load, and `smoke_text_ml_case_search --require-pgvector --require-results`.
- [ ] Update contract tests to assert the absence of active services, Terraform resources, dependencies, and flags; retain tests for required pgvector settings and verification gates.

Run:

```powershell
D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q test/test_aws_pilot_infrastructure.py test/test_deployment_readiness_artifacts.py test/test_production_hardening_contract.py -p no:cacheprovider
docker compose -f D:\dev\project\SKN27-FINAL-3Team-issue-291\docker-compose.yml config
docker compose -f D:\dev\project\SKN27-FINAL-3Team-issue-291\deploy\aws-pilot\docker-compose.pilot.yml config
```

Expected: artifact contract tests pass and both Compose files render without Elasticsearch/Kibana services or undefined ES variables.

## Task 8: Full regression, static removal checks, and implementation report

**Files:**
- Create: `docs/superpowers/reports/2026-07-22-pgvector-only-rag-verification.md`
- Update test files only when failures are caused by intentional ES/OpenSearch removal

- [ ] Run the focused suites from Tasks 1–7, then the repository test suite permitted by the environment. Record exact pass/fail/skip counts, duration, and any unavailable integration dependencies.
- [ ] Run active-path searches for `Elasticsearch`, `OpenSearch`, `Kibana`, `BM25`, `Nori`, `postgres_lexical`, `django_rag_tables`, and legacy flags. Classify any remaining match as historical evidence, an absence assertion, or a release-blocking active reference.
- [ ] Record actual test results and available retrieval metrics in the verification report. The report must distinguish unit-test evidence from production operator measurements; do not fabricate p50/p95 or retrieval quality values.
- [ ] Review the working diff for unintended deletion of generic Django RAG models, `rag_runtime`, public output fields, or non-RAG infrastructure.

Run:

```powershell
D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q --timeout=60 -p no:cacheprovider
rg -n --glob '!docs/**' --glob '!**/*.md' 'Elasticsearch|OpenSearch|Kibana|BM25|Nori|postgres_lexical|django_rag_tables|TEXT_ML_CASE_SEARCH_SYNC_USE_ES|--require-es|--recreate-es' D:\dev\project\SKN27-FINAL-3Team-issue-291
git -C D:\dev\project\SKN27-FINAL-3Team-issue-291 diff --check
git -C D:\dev\project\SKN27-FINAL-3Team-issue-291 status --short
```

Expected: all relevant tests pass, `diff --check` has no whitespace errors, and every active-path search match is either removed or explicitly justified in the report.

## Task 9: Post-merge operator runbook and release gates

**Files:**
- Create: `docs/superpowers/runbooks/2026-07-22-pgvector-only-rag-cutover.md`
- Reference: `storage/migrations/20260722_remove_es_search_artifacts.sql`
- Reference source loaders and verifier from Task 5

- [ ] Document the ordered, operator-owned release procedure: backup source DBs and OpenSearch configuration; run review-case and fault-ratio source load/re-embedding/HNSW creation; run legal seed; run three-store verifier and pgvector smoke; deploy the code/compose/Terraform change; observe errors, source partial rate, result counts, p50/p95; only then apply schema cleanup and delete external ES/OpenSearch resources.
- [ ] Include rollback boundaries: before external deletion, restore the previous deployment and retain backups; after the schema migration/domain deletion, rollback requires restoring backed-up data/config rather than recreating a hidden runtime fallback.
- [ ] Include required report fields for each corpus: chunk count, embedding count, provider/model/dimensions, HNSW existence, representative query result count, unavailable rate, p50, p95, and test pass totals.
- [ ] State that this completes only the C-1 ES-role/selection documentation item. Keep the remaining C-1 items—representative accident evaluation set, user-visible source/search-time/limits, and evidence-review criteria—open.

Expected: implementation PR contains no cloud deletion action; its merge handoff is sufficient for the authorized operator to execute a measured, recoverable cutover.

## Implementation Checkpoints

1. Complete Tasks 1–3 and run focused text-ML tests before deleting ES modules.
2. Complete Tasks 4–5 and run legal/seed/readiness tests before modifying deployment assets.
3. Complete Tasks 6–7 and run configuration/contract tests before final regression.
4. Complete Tasks 8–9, review the diff, then hand the user the test report and Git commands for their commit/PR workflow.
