# Task 1 Report: Complete30 evaluation self-contained

## Files changed

- `etl/fault_cases/rag_runtime/evaluation/evaluate_fault_standard_complete30.py`
  - Set `COMPLETE30_ROOT` to the official `evaluation/fault_standard/complete30_v9/v1` directory.
  - Record the local query parquet SHA-256 instead of reading a legacy manifest, so the evaluator has no remaining dependency on that legacy directory.
- `etl/fault_cases/rag_runtime/evaluation/tests/test_complete30_paths.py`
  - Added a regression test for the official Complete30 root.
- `etl/fault_cases/evaluation/fault_standard/complete30_v9/v1/query_embeddings.parquet`
  - Copied the existing 30-query artifact from the rescue worktree without modifying the source archive.
  - Source and destination SHA-256: `85A95FD75A6DA5533780ECE299A9ACF5FD414C57BC222ED7767472066E84F2BA`.

## Commands and results

### RED

```powershell
pytest etl/fault_cases/rag_runtime/evaluation/tests/test_complete30_paths.py -q
```

Result: expected failure. `COMPLETE30_ROOT` resolved to `etl/fault_cases/NEW_ABC_TEST_V6/artifacts/v7_complete30_abc/01_common_candidates`, not the official evaluation directory.

### Artifact copy

```powershell
Copy-Item -LiteralPath 'C:\dev\project\SKN27-RAG-rescue\etl\fault_cases\legacy_runnable\fault_standard_neo4j_v8_v9\NEW_ABC_TEST_V6\artifacts\v7_complete30_abc\01_common_candidates\query_embeddings.parquet' -Destination 'C:\dev\project\SKN27-RAG-publish\etl\fault_cases\evaluation\fault_standard\complete30_v9\v1\query_embeddings.parquet'
Get-FileHash -Algorithm SHA256 -LiteralPath <source>, <destination>
```

Result: both files have the identical SHA-256 above. The rescue worktree was read only.

### GREEN and final verification

```powershell
pytest etl/fault_cases/rag_runtime/evaluation/tests/test_complete30_paths.py -q
git diff --check
```

Result: `1 passed`; `git diff --check` returned no output and exit code 0.

## Commit

- Implementation commit: `9f12ab6b2ca2c9bd232551d726c58b22f86b8e2d` (`Make Complete30 evaluation self-contained`)

## Concerns

- None. The integration evaluator itself was not run because it executes the full RAG runtime; the scoped path regression test and parity hash cover this task's required change.
