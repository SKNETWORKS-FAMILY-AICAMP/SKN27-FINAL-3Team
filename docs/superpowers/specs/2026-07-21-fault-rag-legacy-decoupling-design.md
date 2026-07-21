# Fault RAG Legacy Decoupling Design

## Goal

Make the published Fault RAG runtime independent of `legacy_runnable`, preserve 27 legacy Markdown records in the official document tree, and align the Supervisor boundary with the runtime contract.

## Decisions

- Preserve the full `legacy_runnable` tree only in the local rescue worktree. Do not delete it.
- Copy 27 legacy experiment, execution, and result Markdown files to `etl/fault_cases/Fault_cases_MD/legacy_runnable/`, preserving each file's relative directory below `legacy_runnable`.
- Exclude the third-party model README at `models/Qwen3-Embedding-4B/README.md` from the official document copy.
- Move the only runtime-required legacy artifact, `query_embeddings.parquet`, to `evaluation/fault_standard/complete30_v9/v1/` and make the evaluator resolve that official path.
- The agent normalizes `structured_facts` into `accident_facts`, restricts work to `required_domains` when supplied, and emits only `success`, `partial`, or `failed` for validated requests.

## Verification

- Add unit tests for the evaluator's official input path and the Agent contract behavior.
- Run the new tests, all `etl/fault_cases/src` tests, and Python compilation for `rag_runtime` and `src`.
- Do not claim GitHub Actions diagnosis until an authenticated `gh` session can retrieve check logs.

## Verification Record (2026-07-21)

- `python -m pytest etl/fault_cases/rag_runtime/agent_runtime/tests/test_agent_contract.py etl/fault_cases/rag_runtime/evaluation/tests/test_complete30_paths.py -q` exited 0: 6 passed in 1.05s.
- `python -m pytest etl/fault_cases/src -q` exited 0: 37 passed in 1.03s (one existing Python 3.14/Pydantic V1 compatibility warning from `langchain_core`).
- `python -m compileall etl/fault_cases/rag_runtime etl/fault_cases/src` exited 0.
- `rg -n --glob '*.py' 'legacy_runnable|NEW_ABC_TEST' etl/fault_cases/rag_runtime etl/fault_cases/src` exited 1 with no matches, confirming neither identifier is actively referenced by Python code in the runtime or ETL source trees.
- GitHub Actions log verification remains blocked: `gh auth status` could not run because `gh` is not installed or available on `PATH` (PowerShell command-not-found; exit 1). Install GitHub CLI and authenticate with repository/workflow scopes before diagnosing CI logs.
