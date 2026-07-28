# Review-case Embedding Retention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve every successful review-case embedding revision and call the provider only for chunks whose current text has no matching stored vector.

**Architecture:** The database stores an immutable `source_text_hash` per embedding revision and an `is_active` state per source chunk. Seed loading applies an active manifest snapshot without deleting rows. Embedding selection and retrieval join on the current chunk hash, so historical vectors remain retained but cannot surface in current search.

**Tech Stack:** PostgreSQL 16 with pgvector, Django management commands, Python 3.13, psycopg2, pytest.

## Global Constraints

- Keep the canonical OpenAI embedding space: `text-embedding-3-large`, 1024 dimensions, version `openai_text_embedding_3_large_1024_chunk_text_v1`.
- Never delete review-case source rows or embeddings as part of a seed reload.
- Preserve existing historical rows even when their source hash cannot be verified; exclude them from current retrieval.
- A provider retry must select only active chunks without a matching current-hash vector.
- Do not stage, commit, or push changes unless the user separately requests it.

---

## File structure

- `storage/schemas/review_case_db_schema.sql` defines the clean-database active-state and embedding-revision schema.
- `storage/migrations/20260728_review_case_embedding_retention.sql` migrates an existing Pilot database without deleting vectors.
- `etl/fault_cases/src/review_case/db_loading/schema_manager.py` applies the retention migration after the idempotent base schema.
- `app/services/review_case_seed_service.py` applies a manifest snapshot using upserts and inactive markers rather than deletes.
- `etl/fault_cases/src/review_case/embedding/run_embedding.py` selects and writes only current-hash revisions.
- `etl/fault_cases/src/review_case/search/pgvector/create_index.py` counts current searchable revisions.
- `etl/fault_cases/src/review_case/search/pgvector/retriever.py` searches only active chunks whose source hash matches their current text.
- `test/test_review_case_seed_service.py`, `test/test_pgvector_rag_readiness.py`, and a new focused embedding-retention test module lock down the contract.

## Task 1: Add non-destructive database revision support

**Files:**
- Modify: `storage/schemas/review_case_db_schema.sql`
- Create: `storage/migrations/20260728_review_case_embedding_retention.sql`
- Modify: `etl/fault_cases/src/review_case/db_loading/schema_manager.py`
- Modify: `test/test_pgvector_rag_readiness.py`

**Interfaces:**
- Produces: `review_case_chunks.is_active BOOLEAN NOT NULL DEFAULT TRUE`.
- Produces: `review_case_chunk_embeddings.source_text_hash TEXT NOT NULL` and a primary key of `(chunk_id, embedding_model, embedding_version, source_text_hash)`.
- Produces: `apply_schema()` applies `20260728_review_case_embedding_retention.sql` after the base schema.

- [x] **Step 1: Write failing schema contract tests**

Add assertions that the base schema includes `is_active BOOLEAN NOT NULL DEFAULT TRUE`, `source_text_hash TEXT NOT NULL`, and the four-column embedding primary key. Add assertions that the new migration contains no `TRUNCATE`, no `DELETE FROM review_case_chunk_embeddings`, backfills from `embedding_meta->>'text_hash'`, and preserves unverifiable rows with a non-matching legacy sentinel.

- [x] **Step 2: Run the schema contract tests to verify they fail**

Run: `python -m pytest test/test_pgvector_rag_readiness.py -q`

Expected: FAIL because the active-state/revision columns and retention migration do not yet exist.

- [x] **Step 3: Update clean schema and write an idempotent retention migration**

In the base schema, add the chunk active marker and source hash column, then define the four-column primary key. In the migration, lock the embedding table, add missing columns, populate source hashes from `embedding_meta.text_hash`, assign `legacy-unverified:<ctid>` only where no verified hash exists, replace the old primary key, create the active-chunk index, and commit. Do not remove rows or vector values.

Update `schema_manager.py` with a fixed migration path and apply it after `apply_sql_file()` so the existing EC2 schema receives the same change.

- [x] **Step 4: Run the schema contract tests to verify they pass**

Run: `python -m pytest test/test_pgvector_rag_readiness.py -q`

Expected: PASS.

## Task 2: Make seed reloads retain history and activate only the current manifest

**Files:**
- Modify: `app/services/review_case_seed_service.py`
- Modify: `test/test_review_case_seed_service.py`
- Modify: `backend/chatbot/management/commands/load_review_case_pgvector_seed.py`
- Modify: `backend/chatbot/test_review_case_pgvector_seed_command.py`

**Interfaces:**
- Consumes: validated `Sequence[ReviewCaseSeedRow]` and `replace=True` as an active-manifest snapshot request.
- Produces: `replace_and_upsert_review_case_rows(...) -> dict[str, int]` with no delete statement and an `inactive_review_case_chunks` count.

- [x] **Step 1: Write failing seed-loader tests**

Add a recording-connection test that calls `replace_and_upsert_review_case_rows(rows, replace=True)` and asserts it emits `UPDATE review_case_chunks SET is_active = FALSE` scoped to `source_type = 'review_case'`, contains no `DELETE FROM review_case_documents`, and upserts each manifest chunk with `is_active = TRUE`.

Add a command test asserting `--replace` remains accepted but is passed to the retention-safe snapshot path and does not mean destructive deletion.

- [x] **Step 2: Run the focused seed-loader tests to verify they fail**

Run: `python -m pytest test/test_review_case_seed_service.py backend/chatbot/test_review_case_pgvector_seed_command.py -q`

Expected: FAIL because the current replace branch deletes documents and does not track inactive rows.

- [x] **Step 3: Implement the retention-safe snapshot upsert**

Replace the delete branch with a scoped inactive update. Extend the chunk insert/update values and SQL to set `is_active = TRUE` for manifest chunks. Preserve the existing text-hash comparison so changed current text becomes pending, and return the inactive count without querying or deleting embeddings.

- [x] **Step 4: Run the focused seed-loader tests to verify they pass**

Run: `python -m pytest test/test_review_case_seed_service.py backend/chatbot/test_review_case_pgvector_seed_command.py -q`

Expected: PASS.

## Task 3: Reuse current-hash vectors and isolate historical revisions

**Files:**
- Modify: `etl/fault_cases/src/review_case/embedding/run_embedding.py`
- Modify: `etl/fault_cases/src/review_case/search/pgvector/create_index.py`
- Modify: `etl/fault_cases/src/review_case/search/pgvector/retriever.py`
- Create: `test/test_review_case_embedding_retention.py`

**Interfaces:**
- Produces: `fetch_pending_chunks(settings, limit)` returns only active chunks without a vector matching `chunk_id`, embedding space, and current `text_hash`.
- Produces: `upsert_embedding_batch(...)` inserts a revision keyed by `source_text_hash` and never overwrites a historical vector.
- Produces: `search_by_vector(...)` filters `c.is_active IS TRUE` and `e.source_text_hash = c.text_hash`.

- [x] **Step 1: Write failing embedding/retrieval tests**

Create focused tests using recording cursors to assert that pending selection requires `c.is_active IS TRUE` and excludes only a matching `e.source_text_hash = c.text_hash`; a changed hash remains pending even if an old vector exists. Assert batch insert includes `source_text_hash` in its conflict identity and no update clause replaces `embedding_vector`. Assert retrieval joins only active chunks with matching source hashes.

- [x] **Step 2: Run the focused retention tests to verify they fail**

Run: `python -m pytest test/test_review_case_embedding_retention.py -q`

Expected: FAIL because current code identifies an embedding only by chunk/model/version and retrieval does not filter active/current hashes.

- [x] **Step 3: Implement current-hash selection, immutable writes, and filtered retrieval**

Change pending selection to compare the current chunk `text_hash` with `source_text_hash` inside the configured embedding space. Include `source_text_hash` in insert values and conflict handling; use `ON CONFLICT DO NOTHING` for an already-stored immutable revision. Make current embedding counts join the chunk table and apply active/current-hash predicates. Add the identical predicates to the pgvector retrieval SQL.

- [x] **Step 4: Run the focused retention tests to verify they pass**

Run: `python -m pytest test/test_review_case_embedding_retention.py -q`

Expected: PASS.

## Task 4: Run regression tests and prepare the safe operational sequence

**Files:**
- Modify: `docs/ops/production-env.md`

**Interfaces:**
- Produces: an operator sequence: run schema maintenance once, run the seed with `--replace`, then verify current embedding count and retrieval readiness without a forced re-embedding.

- [x] **Step 1: Document the exact non-destructive operational sequence**

Add a short retention section explaining that the schema migration must precede seed loading, `--replace` marks absent chunks inactive, and repeat runs reuse matching hashes. State that a model/version change intentionally creates a new retained embedding space.

- [x] **Step 2: Run the full relevant regression suite**

Run: `python -m pytest test/test_review_case_seed_service.py test/test_review_case_embedding_retention.py test/test_pgvector_rag_readiness.py backend/chatbot/test_review_case_pgvector_seed_command.py -q`

Expected: PASS with no provider calls.

- [x] **Step 3: Verify the migration syntax without applying it to RDS**

Run: `python -m pytest test/test_aws_pilot_infrastructure.py -q`

Expected: PASS; no EC2, RDS, OpenAI, or production seed command is executed during this task.

## Plan self-review

- Spec coverage: Task 1 preserves database history, Task 2 removes destructive seed behavior, Task 3 prevents repeat provider calls and stale retrieval, and Task 4 documents and verifies the safe operational path.
- Placeholder scan: no TODO/TBD or conditional implementation placeholders.
- Type consistency: `is_active` belongs to chunks; `source_text_hash` belongs to embedding revisions; every selection and retrieval operation uses both fields.
