# Phase 2-B2 ConfirmCaseFacts Application Command Receipt

## Scope and base

- Repository: `SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team`
- Base SHA: `6f597b7e6ca21edadefe4f1c753d309d610129e7`
- Branch: `refactor/phase-02-b2-confirm-case-facts-use-case`
- Scope: `POST /api/cases/<case_id>/facts/confirm/` only
- Production DB audit: `NOT_EXECUTED`
- P2-B3 `StartCaseAnalysis`: deferred and out of scope.

## Call graph

Before:

`consultation_case_fact_confirmation` → authorization → validation → `confirm_case_facts` → HTTP response

After:

`consultation_case_fact_confirmation` → `execute_confirm_case_facts` → authorization → validation → `confirm_case_facts` → HTTP response

The View remains the HTTP adapter. `app.application.cases.confirm_facts` owns application orchestration and has no Django HTTP, Explicit Mock, direct ORM, or `transaction.atomic` dependency.

## Preserved contracts

- Authorization remains before request validation. A foreign caller with an invalid payload receives `403 object_access_denied` without validation details.
- `chatbot.case_repository.confirm_case_facts` is unchanged. It remains the owner of `transaction.atomic`, `select_for_update`, Case lookup, ownership check, request fingerprinting, idempotency replay, `ConfirmedFactVersion` creation, and Case mutation.
- Exact replay retains the same fact version and does not erase manually set active-analysis metadata.
- A changed payload creates the next fact version and preserves the existing `active_analysis_job_id` reset contract.
- Route, method, HTTP status, response payload, headers, models, migrations, queue, worker, frontend runtime, and Explicit Mock runtime are unchanged.
- P2-B1 `consultation_case_workspace` and the existing analysis-start path are unchanged.

## Application interface

`app.application.cases.confirm_facts` provides:

- `ConfirmCaseFactsCommand`
- `ConfirmCaseFactsResult`
- `CaseFactConfirmationAccessDenied`
- `execute_confirm_case_facts`

The command resolves access metadata (with the existing Case fallback), authorizes the identity payload, validates `ConfirmCaseFactsRequest`, and delegates the validated Python payload to the existing repository command.

## Characterization and sensitivity

- `chatbot.test_phase_02_case_fact_confirmation_use_case`: 8 tests, `OK`.
- Existing `test_fact_confirmation_precedes_real_worker_queue` and `chatbot.test_phase_02_case_workspace_use_case`: 7 tests, `OK`.
- Mutation A removed application authorization: the foreign invalid-payload characterization changed from `403` to `422 request_validation_error.v1`; the test failed as required.
- Mutation B delegated raw payload before validation: the owner invalid-payload characterization changed from `422` to `409 consultation_case_error.v2`; the test failed as required.
- Both mutations were restored byte-for-byte. The combined B2/B1 regression run found 15 tests and passed.

## Local verification

- Phase 1 Python gate: 27 passed.
- Phase 1 Django gate: 35 tests, `OK`.
- Phase 0 deterministic suite and Windows full Django suite retain the Base-identical `pymupdf._extra` DLL-loading environment debt. The feature adds 8 B2 tests; the full Django error count remained 20 on both Base and feature. This is not a source regression.
- `test/test_phase_01_collection_baseline_contract.py`: 6 passed. The Windows collection verifier separately reports the same PyMuPDF import environment issue and no B2 source regression.
- `python backend/manage.py check`, OpenAPI check, frontend route check, and `ruff check --select E9,F63,F7,F82 .`: passed.
- `node --test app/web/*.test.js`: 155 passed.
- `npm --prefix app/web run build`: passed.

## Docker D1

- `docker build -t skn27-phase-02-b2-local .`: passed.
- CI-equivalent `chat_orchestration_service` and `runtime_health` import: passed.
- Container Django check: passed.
- Container `ConfirmCaseFacts` import with production runtime settings: passed (`phase-02-b2 import ok`).

## Compose D2

`scripts/refactoring/run_phase_00_compose_gate.sh` ran with an ephemeral Git Bash `python3` shim and `COMPOSE_PROJECT_NAME=skn27_phase02_b2_local`. Repository scripts and system/user PATH were unchanged.

- `gate-summary.json`: `status: pass`; backend, database, cache, Neo4j, ClamAV, agent worker, and file-scan worker ready/consumed.
- File scan: `status: pass`, `scan_status: clean`, `retry_count: 0`, and `local://attachment-staging/...` evidence.
- `mock://` evidence: 0.
- `failed-step.txt`: absent.
- `last-step.txt`: `compose-final`.
- Latest cleanup marker: `cleanup_success`.
- `skn27_phase02_b2_local` container, volume, and network residue: 0.

## CI and review

- `.github/workflows/production-gate.yml` adds the blocking `Phase 2 B2 case fact confirmation application boundary` step without `continue-on-error` or `|| true`.
- The Draft PR CI result is pending at this receipt commit and must pass before review readiness is declared.
- Draft PR must remain unmerged and must not be converted to Ready by this task.
