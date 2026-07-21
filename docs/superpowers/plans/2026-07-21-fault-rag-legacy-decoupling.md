# Fault RAG Legacy Decoupling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish an operational Fault RAG structure that does not read from `legacy_runnable` and preserves selected legacy Markdown as official records.

**Architecture:** Complete30 query vectors become a versioned evaluation input alongside questions and answer keys. The Agent contract is normalized at the Supervisor boundary, so domain services receive a single request shape. Legacy Markdown is documentation-only and keeps its original relative hierarchy under `Fault_cases_MD/legacy_runnable`.

**Tech Stack:** Python 3.14, pytest, Git, parquet evaluation input.

## Global Constraints

- Do not delete or alter the local rescue archive.
- Do not add model weights, zip bundles, or generated legacy artifacts to the publish branch.
- Exclude only `models/Qwen3-Embedding-4B/README.md` from the Markdown migration.

---

### Task 1: Make Complete30 evaluation self-contained

**Files:**
- Create: `etl/fault_cases/evaluation/fault_standard/complete30_v9/v1/query_embeddings.parquet`
- Modify: `etl/fault_cases/rag_runtime/evaluation/evaluate_fault_standard_complete30.py`
- Test: `etl/fault_cases/rag_runtime/evaluation/tests/test_complete30_paths.py`

- [ ] Write a test asserting `COMPLETE30_ROOT` is the official `evaluation/fault_standard/complete30_v9/v1` directory.
- [ ] Run the test and observe the old legacy path failure.
- [ ] Change the evaluator path and copy the existing 30-query parquet artifact into the official evaluation directory.
- [ ] Re-run the test and confirm it passes.

### Task 2: Align the Supervisor Agent contract

**Files:**
- Modify: `etl/fault_cases/rag_runtime/agent_runtime/supervisor_input.py`
- Modify: `etl/fault_cases/rag_runtime/agent_runtime/agent.py`
- Modify: `etl/fault_cases/rag_runtime/agent_runtime/supervisor_output.py`
- Test: `etl/fault_cases/rag_runtime/agent_runtime/tests/test_agent_contract.py`

- [ ] Write tests for `accident_facts` normalization, requested-domain dispatch, and all-domain failure returning `failed`.
- [ ] Run tests and observe failures against the current implementation.
- [ ] Implement the minimal request normalization, dispatch filtering, and aggregate status rules.
- [ ] Re-run the targeted tests and confirm they pass.

### Task 3: Preserve legacy Markdown as official records

**Files:**
- Create: `etl/fault_cases/Fault_cases_MD/legacy_runnable/<legacy relative path>` for the selected 27 Markdown files.
- Create: `etl/fault_cases/Fault_cases_MD/legacy_runnable/README.md`

- [ ] Copy the 27 selected Markdown files without changing their contents or relative hierarchy.
- [ ] Add a short index explaining that the local `legacy_runnable` archive remains the executable historical source and that this tree is its document-only record.
- [ ] Verify no model, zip, parquet, or legacy runtime source file is staged by this task.

### Task 4: Verify and record remaining CI access blocker

**Files:**
- Modify: `docs/superpowers/specs/2026-07-21-fault-rag-legacy-decoupling-design.md`

- [ ] Run targeted runtime tests, full `etl/fault_cases/src` tests, and `compileall`.
- [ ] Confirm `rg` finds no active `legacy_runnable` or `NEW_ABC_TEST` reference under `rag_runtime` and `src`.
- [ ] Record that GitHub Actions logs remain unavailable until `gh auth status` succeeds with repository/workflow scopes.
