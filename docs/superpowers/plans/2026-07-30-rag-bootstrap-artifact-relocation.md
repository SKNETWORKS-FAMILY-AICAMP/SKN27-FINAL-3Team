# RAG Bootstrap Artifact Relocation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the committed-delivery copies of the precedent and fault-standard embedding bundles into domain/version-scoped bootstrap directories without changing their generator, validation, or experimental source pipelines.

**Architecture:** Keep `etl/fault_cases/standard_TEST` as the immutable source-generation and validation workspace. Store only the Git-delivered bootstrap copies under `etl/fault_cases/bootstrap/<domain>/<version>/`, with README files explaining provenance, hashes, record counts, and loading boundaries. Preserve all artifact filenames and bytes so manifests and downstream CLI arguments remain stable.

**Tech Stack:** Git, PowerShell, SHA-256, Markdown, existing Python/pytest validation.

## Global Constraints

- Do not modify any Python file under `etl/fault_cases/standard_TEST`.
- Do not rename embedding or metadata files.
- The source and destination SHA-256 values must match before the old delivery copy is removed.
- The final tree must contain exactly one Git-delivery copy of each artifact.
- Preserve unrelated user changes in the dirty worktree.

---

### Task 1: Relocate the immutable bootstrap copies

**Files:**
- Move: `etl/fault_cases/bootstrap/precedent_newplusplus_bge_v1/*`
- To: `etl/fault_cases/bootstrap/precedent/qwen3_4b_bge_v1/*`
- Move: `etl/fault_cases/rag_runtime/fault_standard/r10/resources/embedding_seed/*`
- To: `etl/fault_cases/bootstrap/fault_standard/qwen3_4b_r6/*`
- Create: `etl/fault_cases/bootstrap/README.md`
- Create: `etl/fault_cases/bootstrap/fault_standard/qwen3_4b_r6/README.md`

**Interfaces:**
- Consumes: the byte-identical untracked delivery copies already present in the worktree.
- Produces: one canonical Git bootstrap path per domain and version.

- [ ] **Step 1: Verify no production or experimental Python file references either delivery path**

Run exact-path searches across tracked, untracked, and ignored Python files. References to the original `standard_TEST/11_ARTIFACTS/...` generator output are allowed; references to either delivery-copy path are not.

- [ ] **Step 2: Record source SHA-256 values**

Expected:

```text
precedent embeddings: bc4bc1146b76784f2ba95f9287e7f1b8d0280e41fa249d0154c94789d453126c
precedent metadata:   ab6ab0bedafd3152f9b5ee668b503c35d28288e0c6b421e872866b2f014ff9ff
fault-standard seed:  cd6d031ff775beb7401dcb729007190685a687b43afcad4c7c96207f171b8e8d
```

- [ ] **Step 3: Copy into the new domain/version directories**

Create only the two exact destination directories, copy the existing files, and preserve filenames.

- [ ] **Step 4: Verify destination hashes**

Compare every destination SHA-256 to Step 2 and stop if any value differs.

- [ ] **Step 5: Remove only the verified old delivery copies**

Remove the old `precedent_newplusplus_bge_v1` and `rag_runtime/fault_standard/r10/resources/embedding_seed` delivery-copy directories after resolving both absolute paths inside the workspace.

- [ ] **Step 6: Add bootstrap documentation**

Document the directory purpose, source-generation boundary, model revision, dimensions, hashes, record counts, and the rule that fault-standard query records must not be loaded into production.

### Task 2: Update path-bearing documentation and verify

**Files:**
- Modify: `etl/fault_cases/docs/precedent_rag_replacement_handoff.md`
- Modify: `docs/superpowers/plans/2026-07-30-precedent-rag-replacement.md`
- Modify: `docs/superpowers/plans/2026-07-30-fault-standard-r10-agent-qwen-direct-cutover.md`

**Interfaces:**
- Consumes: the canonical bootstrap paths from Task 1.
- Produces: loader examples and plans that name only the new paths.

- [ ] **Step 1: Replace precedent bootstrap path references**

Use `etl/fault_cases/bootstrap/precedent/qwen3_4b_bge_v1/` in every loader command and file listing.

- [ ] **Step 2: Declare the fault-standard seed input path**

Use `etl/fault_cases/bootstrap/fault_standard/qwen3_4b_r6/qwen3_4b_r6_embeddings.jsonl.gz` and its adjacent manifest as the future R10 seed-bundle input.

- [ ] **Step 3: Run final verification**

Verify:

```text
no Python delivery-path references
no old documentation path references
all three artifact hashes unchanged
old delivery directories absent
new delivery directories present
git diff --check passes
focused precedent and fault-standard tests pass
```

