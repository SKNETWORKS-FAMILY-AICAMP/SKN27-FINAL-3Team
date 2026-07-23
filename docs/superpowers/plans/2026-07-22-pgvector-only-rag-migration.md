# Law·Review-Case PGVector Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove active ES/lexical fallbacks and serve law and review-case retrieval from the same OpenAI `text-embedding-3-large` 1024-dimensional pgvector contract.

**Architecture:** Keep law and review-case in separate PostgreSQL databases but use one embedding-space contract. Preserve fault-ratio pgvector behavior without including it in the common-space gate. Fail closed on metadata or dimension mismatch.

**Tech Stack:** Python 3.13, Django, PostgreSQL, pgvector/HNSW, OpenAI embeddings, pytest, Docker Compose, Terraform.

## Global Constraints

- [x] Canonical law/review-case space is `openai / text-embedding-3-large / 1024`.
- [x] Do not run production re-embedding, DB migration, Terraform apply/destroy, or cloud deletion.
- [x] Preserve `ready`, `empty`, `unavailable`, and `embedding_space_mismatch`.
- [x] Keep fault-ratio precedent outside the common embedding-space gate.
- [x] Update only checklist claims backed by tests or measured evidence.

---

### Task 1: Lock the common embedding contract

**Files:**
- Modify: `.env.example`
- Modify: `.env.production.example`
- Modify: `etl/fault_cases/src/review_case/db_loading/db_config.py`
- Test: `test/test_pgvector_rag_readiness.py`

- [x] Add failing tests asserting review-case defaults equal
  `openai / text-embedding-3-large / 1024`.
- [x] Add canonical `RAG_EMBEDDING_*` settings and compatibility validation.
- [x] Run the focused tests and confirm they pass.

### Task 2: Convert review-case schema and loader to 1024 dimensions

**Files:**
- Modify: `storage/schemas/review_case_db_schema.sql`
- Create: `storage/migrations/20260723_unify_law_review_case_embeddings.sql`
- Modify: `etl/fault_cases/src/review_case/embedding/run_embedding.py`
- Test: `test/test_production_hardening_contract.py`

- [x] Add failing schema-contract tests for `vector(1024)` and
  `CHECK (embedding_dim = 1024)`.
- [x] Update fresh schema and add a backup-gated idempotent migration.
- [x] Verify the embedder sends `dimensions=1024` and rejects other vector lengths.

### Task 3: Enforce the shared space in search and readiness

**Files:**
- Modify: `etl/fault_cases/src/review_case/search/pgvector/retriever.py`
- Modify: `backend/chatbot/management/commands/verify_pgvector_rag_readiness.py`
- Test: `test/test_pgvector_rag_readiness.py`

- [x] Add failing tests for cross-domain provider/model/dimension mismatch.
- [x] Make law and review-case required readiness domains.
- [x] Keep fault-ratio as an optional diagnostic, not a common-space gate.
- [x] Reject non-1024 query vectors before SQL execution.

### Task 4: Reconcile ES removal with current dev

**Files:**
- Modify active ES/lexical callers found by repository scan.
- Preserve current `dev` attachment/agent work in overlapping files.
- Test: deployment and agent contract suites.

- [x] Merge current `dev` and resolve conflicts in favor of current public contracts.
- [x] Remove only active ES/OpenSearch/BM25/Nori dependencies and callers.
- [x] Confirm no production code imports removed search clients.

### Task 5: Correct documentation, checklist, and PR evidence

**Files:**
- Modify: `docs/ops/project-readiness-master-checklist.md`
- Modify: `docs/superpowers/reports/2026-07-22-pgvector-only-rag-verification.md`
- Modify: PR #293 title and body.

- [x] Mark only pgvector-only boundary and shared law/review-case embedding evidence.
- [x] Leave the three separate C-1 quality items open.
- [x] Record focused/full results and the measured Python 3.13 installation limitation.
- [ ] Retitle PR to `[Refactor] ES·lexical 제거 및 law·review_case pgvector 단일화`.

### Task 6: Python 3.13 verification and publication

- [ ] Create an isolated Python 3.13 `.venv`.
- [ ] Install runtime and development requirements.
- [x] Run focused law/review-case, deployment, and Django tests.
- [ ] Run the full repository suite without excluding `rag_runtime`.
- [ ] Push the reconciled branch and confirm PR status.
