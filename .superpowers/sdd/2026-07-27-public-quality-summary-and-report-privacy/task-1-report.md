# Task 1 Report: Sanitize `law_ground_search` For Public Results

## Scope

Implemented the server-side allowlist boundary for public law retrieval metadata and the canonical `structured_result.public_quality_summary` projection.

## Changes

- Reduced `_retrieval_metadata` in `app/services/agent_node_service.py` to the allowed fields:
  `contract_version`, `status`, `backend`, `result_count`, `retrieved_at`,
  `effective_at`, `error_code`, `fallback_from`, and `attempted_backends`.
- Added `_project_public_quality_summary(value)` in
  `app/services/analysis_job_query_service.py` with allowlisted freshness,
  retrieval, limitation, and status fields.
- Added `_project_public_law_ground_structured_result(value)` and applied it only
  to `law_ground_search` entries in the existing public
  `supervisor_execution.node_results` projection.
- Kept the existing reduced `retrieval` field available for law results, using
  only its safe subset.
- Did not modify operator provenance or projection behavior for other nodes.
- Added regression tests covering private retrieval metadata removal and public
  quality-summary/law structured-result projection.

## TDD Evidence

1. Added the two focused regression tests before implementation.
2. Ran the focused suite and confirmed the expected RED state: 2 failed, 17 passed.
3. Implemented the allowlist and public projections.
4. Re-ran the focused suite and confirmed GREEN: 19 passed.

## Verification

Command:

```text
python -m pytest test/test_analysis_job_query_service.py test/test_law_ground_contract.py -q
```

Result: `19 passed in 0.23s`

`git diff --check` also passed. The worktree contains an unrelated pre-existing
untracked plan file at `docs/superpowers/plans/2026-07-27-public-quality-summary-and-report-privacy.md`; it was not included.

## Concerns

## Round 1 Fix Report

### Findings Addressed

- Replaced nested deep-copying of law matches, provisions, and freshness with
  scalar allowlists. URI-like values, signed URLs, storage paths, and nested
  provenance mappings are omitted.
- Converted retrieval `fallback_from` to a boolean status and
  `attempted_backends` to the scalar status `none`, `single`, or `multiple`.
- Added fallback-based synthesis so every projected `law_ground_search`
  structured result contains `public_quality_summary`, including when the
  stored summary is absent.
- Limited public limitations to approved user-facing messages and omit raw
  exception/debug text.
- Preserved the existing `supervisor_execution.node_results` projection
  location and operator provenance behavior.

### TDD Evidence

1. Added failing regression tests for nested freshness/law metadata,
   attempted-backend mappings, unsafe limitations, and missing summaries.
2. Confirmed the expected RED state: 2 new tests failed while the prior 19
   focused tests passed.
3. Implemented the safe nested projections and summary synthesis.
4. Updated the existing public-contract expectation to account for the now
   mandatory summary field.
5. Re-ran the amended covering suite successfully.

### Verification

```text
python -m pytest test/test_analysis_job_query_service.py test/test_law_ground_contract.py -q
```

Result: `21 passed in 0.21s`

### Round 1 Concerns

None identified within Task 1 scope.

## Round 2 Fix Report

### Finding Addressed

- `law_ground_search` node-level `limitations` are now projected through the
  same approved user-facing limitation allowlist as the quality summary.
  Unsafe exception/debug text is removed, while an absent field remains
  absent. Other node types are unchanged.

### TDD Evidence

1. Added a regression test with an unsafe raw exception and an approved
   limitation in node-level `limitations`.
2. Confirmed the expected RED state: 1 test failed and 21 passed.
3. Applied the law-node-only limitation projection.
4. Re-ran the covering suite successfully.

### Verification

```text
python -m pytest test/test_analysis_job_query_service.py test/test_law_ground_contract.py -q
```

Result: `22 passed in 0.19s`

### Round 2 Concerns

None identified within Task 1 scope.

None identified within Task 1 scope. The projection intentionally operates at
the existing `supervisor_execution.node_results` public boundary; deriving that
projection directly from `agent_results` would be cross-task behavior and was
not introduced.
