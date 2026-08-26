# Phase 2-D11 AnalysisReadQueries receipt

## Authority

- Repository: `SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team`
- Base: `5772100eecdd3f5fd507fda405a2f8520f793008`
- Branch: `refactor/phase-02-d11-analysis-read-queries`
- RED_SECURITY Head: `292c431155e0f724613dc718957f1d94f2bfb2f3`
- GREEN_SECURITY Head: `a5ba7f57c6a24f5dab73c16307c35e57f74c34d3`
- RED_APP Head: `6e074a82344a3a1c06f361aee8142281478dce3e`
- GREEN_APP Head: `f3abb67ec6390b07a91c840561cd70be6a3762ce`
- Sensitivity Runtime Head: `246d55f5fc695082c5108735438794b73f2295d1`
- PR: `NOT_CREATED_AT_RECEIPT_TIME`
- Production DB audit: `NOT_EXECUTED`

This receipt intentionally omits its own commit SHA, Draft PR number, and future CI run IDs to avoid a self-reference commit loop.

## Strategy

`STRICT_BEHAVIOR_PARITY_EXCEPT_SECURITY_AND_STATE_CORRECTIONS`

Only `GET /api/analysis/jobs/`, `GET /api/analysis/jobs/<job_id>/`, and `GET /api/analysis/results/<job_id>/` are in scope. The `POST /api/analysis/jobs/` reservation, queue, worker, retry, lease, and refund behavior is unchanged and remains Phase 3 Deferred scope.

## P0 — owner/session precedence

Reproducer: valid guest G, guest-bound `ChatSession` S, and `AnalysisJob` X with `session_id=S` and explicit `owner_id=usr_foreign_owner`.

- Before: Detail returned `200`; Result returned `202` or terminal `200` despite matching only the session.
- Direct `authorize_resource_access(get_analysis_job_access_metadata(X), guest_identity_payload)` already returned `allowed=false` and `reason=owner_mismatch`.
- Root cause: `_analysis_job_access_response` applied session authorization before explicit job-owner authorization, so session match masked an explicit owner mismatch.
- After: `execute_get_analysis_job_detail` and `execute_get_analysis_result` share explicit-owner-first object authorization; both HTTP routes return the existing `403 object_access_denied` response.
- No ORM ACL query, migration, persistence constraint, or generic ACL framework was introduced.

`P0_CANDIDATE_ANALYSIS_JOB_OWNER_SESSION_PRECEDENCE_BYPASS`: `REMEDIATED_PENDING_INDEPENDENT_REVIEW`.

## P1 — List canonical guest policy

- Before: an expired but cryptographically valid guest credential received `200` from `GET /api/analysis/jobs/`; Detail and Result produced canonical `401 guest_session_invalid`.
- After: `execute_list_analysis_jobs` applies canonical guest policy and maps invalid identity through the existing `401 guest_session_invalid` response.
- Preserved: valid guest without `session_id` receives `200 {"jobs": []}`; authenticated users remain owner-scoped; valid guest session use remains session-authorized.

`P1_CANDIDATE_ANALYSIS_LIST_GUEST_POLICY_PARITY`: `REMEDIATED_PENDING_INDEPENDENT_REVIEW`.

## P2 candidate — progress-cache identity

`read_analysis_job_progress` is auxiliary state. `app/services/analysis_job_query_service.py` rejects a cache snapshot when its nonempty `job_id` differs from the stored job or when its nonempty `session_id` differs from the stored session.

- Mismatched snapshots contribute no public snapshot state, message, status count, job identifier, or session identifier.
- Normal Detail remains `200` with DB-derived detail/progress state; the cache backend is not mutated.
- `AnalysisJob.status`, owner/session relation, terminal status, work item, agent result, and reports remain DB authoritative.

`P2_CANDIDATE_CACHE_SNAPSHOT_IDENTITY_MISMATCH`: `REMEDIATED_PENDING_INDEPENDENT_REVIEW`.

## Application boundary

- Module: `app/application/analysis/read_queries.py`
- Query DTOs: `ListAnalysisJobsQuery`, `GetAnalysisJobDetailQuery`, `GetAnalysisResultQuery`
- Result DTOs: `ListAnalysisJobsResult`, `GetAnalysisJobDetailResult`, `GetAnalysisResultResult`
- Typed errors: `AnalysisReadGuestIdentityInvalid`, `AnalysisReadAccessDenied`, `AnalysisJobNotFound`, `AnalysisResultNotFound`
- Executors: `execute_list_analysis_jobs`, `execute_get_analysis_job_detail`, `execute_get_analysis_result`

The three views retain trusted identity reconstruction, DTO construction, executor call, and existing typed-error-to-JSON mapping. The Application module owns list selection, common authorization, loading, safe progress use, and pending/terminal decisions by reusing `access_subject_from_payload`, `get_chat_session_access_metadata`, `get_analysis_job_access_metadata`, `authorize_resource_access`, `list_analysis_job_records`, `get_analysis_job_record`, `read_analysis_job_progress`, `load_analysis_job_detail`, `load_analysis_result`, and `compose_agent_response`.

## Public contract, state, and privacy

- List keeps `{"jobs": [...]}`, optional `session_id`, existing descending order, valid guest/no-session `200 {"jobs": []}`, and existing `403`/not-found behavior.
- Detail keeps `{"job": ...}`, `200`, `404 analysis_job_not_found`, existing invalid-guest `401`, and now intentionally denies the P0 relation with `403`.
- Result keeps `{"result": ...}`, queued/running `202`, repository-terminal `200`, `404 analysis_result_not_found`, existing invalid-guest `401`, and the same intentional P0 `403`.
- Repository `AnalysisJob.status` remains terminal-status authority; agent rows and cache snapshots do not recompute it.
- Existing service allow-list projection is retained. Storage paths/signed URLs, raw provider or agent payloads, unrestricted metadata, prompt/reasoning, tokens/credentials, internal retry/lease values, and traces are excluded.
- Unsupported `node_code` raw `structured_result` is not exposed; supported projectors alone compose public results.

## Sensitivity

Runner: `scripts/refactoring/verify_phase_02_d11_analysis_read_queries_sensitivity.py`

| Mutation | Direct detector | Result |
| --- | --- | --- |
| `list_view_application_bypass` | `test_analysis_job_list_delegates_to_execute_list_analysis_jobs` | `AssertionError` |
| `detail_view_application_bypass` | `test_analysis_job_detail_delegates_to_execute_get_analysis_job_detail` | `AssertionError` |
| `result_view_application_bypass` | `test_analysis_result_delegates_to_execute_get_analysis_result` | `AssertionError` |
| `list_scope_authorization_bypass` | owner-scope List contract | `AssertionError` |
| `job_owner_precedence_bypass` | foreign explicit owner + matching guest session Detail/Result | `AssertionError` |
| `canonical_guest_policy_bypass` | expired guest List | `AssertionError` |
| `progress_cache_identity_validation_bypass` | mismatched cache identity exclusion | `AssertionError` |
| `public_projection_bypass` | structured private-field exclusion | `AssertionError` |
| `pending_terminal_status_bypass` | queued `202` and terminal `200` contract | `AssertionError` |

At `246d55f5fc695082c5108735438794b73f2295d1`, baseline exit code was `0`; all nine mutation subprocesses failed directly by `AssertionError`; `source_restored=true`, `working_tree_unchanged=true`, and `residual_diff_zero=true`.

## Verification

- `python backend/manage.py test chatbot.test_phase_02_analysis_read_queries_use_case --verbosity 1` — `12 tests, OK`.
- `python -m pytest test/test_analysis_job_query_service.py -q -p no:cacheprovider` — `28 passed`.
- `python -m pytest test/test_phase_02_d11_sensitivity_runner.py -q -p no:cacheprovider` — `4 passed`.
- `python scripts/refactoring/verify_phase_02_d11_analysis_read_queries_sensitivity.py` — baseline `0`, exact `9` direct controls, all `AssertionError`.
- `python backend/manage.py test chatbot.test_production_hardening --verbosity 1` — `32 tests, OK`.
- B1–D11 Application/security selection — `188 tests, OK`; Phase 2 sensitivity runner selection — `44 passed`.
- `python backend/manage.py check`, `python scripts/generate_openapi_v1.py --check`, `python scripts/generate_frontend_case_routes.py --check`, `ruff check --select E9,F63,F7,F82 .`, and `ruff check --select F401 app/application/analysis/read_queries.py` — `PASS`.
- `node --test app/web/*.test.js` — `155` passing tests; `npm --prefix app/web run build` — `PASS` (existing bundle-size warning only).
- `docker build --progress=quiet -t skn27-phase-02-d11-local .` and initialized-Django import smoke for all three executors — `D1_IMPORT_SMOKE_PASS`.
- D2 canonical `scripts/refactoring/run_phase_00_compose_gate.sh` could not complete under the Windows Git Bash `python3` host transport. The unchanged standard Compose-equivalent probes all passed: service health, Redis `PONG`, migration check, live/ready endpoints, `Queue → Agent worker → AgentResult`, and upload → `file-scan worker → clean`. `skn27_phase00_local_0` cleanup left `0` containers, `0` volumes, and `0` networks. Canonical D2: `NOT_EXECUTED_HOST_SHELL_PYTHON3`; equivalent container evidence: `PASS`.

### Windows observation

`python -m pytest -q -p no:cacheprovider` stopped at nine known environment collection errors: `cv2` three times and `pymupdf._extra` DLL loading six times, with no D11-specific collection error. `python scripts/refactoring/verify_pytest_collection_baseline.py` reported `new_collection_regression` because the six DLL errors mask the expected `pypdf` collection baseline. Linux CI remains the full-suite authority.

## CI

- Source Head, synthetic pull-request runtime checkout, production-gate, offline-verification, compose-integration, regression-signal, and `phase-02-d11-sensitivity-evidence` artifact: `PENDING_DRAFT_PR_CREATION`.

## CI follow-up

The first Draft CI source Head `0b0bbcf76e842c4410e8ede1ee086bc064de4a0e` had `regression-signal=success`, but `production-gate` stopped before D11 steps because `chatbot.test_supervisor_reporting_pipeline.SupervisorReportingPipelineTests.test_persisted_job_remains_pollable_without_transient_progress_cache` still patched removed `chatbot.views._analysis_job_access_response`.

`246d55f5fc695082c5108735438794b73f2295d1` changes only that test seam to `app.application.analysis.read_queries._authorize_analysis_job`. It passed directly, the focused combined selection passed `45 tests, OK`, and the final D11 sensitivity runtime passed all nine direct controls. Fresh GitHub CI for the post-remediation Source Head is pending push.

## Deferred

- guest-session lifecycle, refresh, logout, and `auth/me`
- Phase 3 provider, storage, queue/worker, renderer, retry/refund, and transaction architecture
- `RESUME_GUEST_TRANSPORT_VIEW_CONTRACT_ALIGNMENT`
- `MYPAGE_PUBLIC_PROJECTION_HARDENING_REQUIRED`
- D10 DB consistency observation, Windows portability debt, and Production DB audit

## Remaining Phase 2 count

- Current pre-merge remaining: `5`
- Projected after D11 merge: `4`
- Authoritative recount: `REQUIRED_AFTER_MERGE`

## Current status

- P0: `REMEDIATED_PENDING_INDEPENDENT_REVIEW`
- P1: `REMEDIATED_PENDING_INDEPENDENT_REVIEW`
- P2 candidate: `REMEDIATED_PENDING_INDEPENDENT_REVIEW`
- Independent Review, Draft Ready transition, and Merge: `NOT_PERFORMED`
