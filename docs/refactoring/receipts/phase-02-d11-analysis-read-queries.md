# Phase 2-D11 AnalysisReadQueries receipt

## Authority

- Repository: `SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team`
- Base: `5772100eecdd3f5fd507fda405a2f8520f793008`
- Branch: `refactor/phase-02-d11-analysis-read-queries`
- RED_SECURITY Head: `292c431155e0f724613dc718957f1d94f2bfb2f3`
- GREEN_SECURITY Head: `a5ba7f57c6a24f5dab73c16307c35e57f74c34d3`
- RED_APP Head: `6e074a82344a3a1c06f361aee8142281478dce3e`
- GREEN_APP Head: `f3abb67ec6390b07a91c840561cd70be6a3762ce`
- Pre-Delta Reviewed Head: `4cfdafdb81e901d983b998a0bfdb5497b21bd041`
- D11_DELTA_RED_HEAD: `2ca8f6d5422ce4609adaeb292423b84c9c0e203b`
- D11_DELTA_GREEN_HEAD: `79a9c5b97364ed79bf8b4fbf821aa5d94fe9ad02`
- D11_DELTA_SENSITIVITY_IMPLEMENTATION_HEAD: `f6426ba9cd1528fc095c4931ec90eec3d8195fb6`
- D11_DELTA_SENSITIVITY_ANCHOR_CORRECTION_HEAD: `842873c5ad7d576655c57cae68b9e7b87616d02a`
- D11_DELTA_SENSITIVITY_HEAD: `964d54ae551f7dc1e6c983966e8c896ed3e0b243`
- Final Delta Runtime Head: `964d54ae551f7dc1e6c983966e8c896ed3e0b243`
- PR: `#415` / `OPEN` / Draft `true` / Merge `NOT_PERFORMED`
- Production DB audit: `NOT_EXECUTED`

This receipt intentionally omits its own commit SHA, Draft PR number, and future CI run IDs to avoid a self-reference commit loop.

## Strategy

`STRICT_BEHAVIOR_PARITY_EXCEPT_SECURITY_AND_STATE_CORRECTIONS`

Only `GET /api/analysis/jobs/`, `GET /api/analysis/jobs/<job_id>/`, and `GET /api/analysis/results/<job_id>/` are in scope. The `POST /api/analysis/jobs/` reservation, queue, worker, retry, lease, and refund behavior is unchanged and remains Phase 3 Deferred scope.

## Independent Review — Pre-Delta

- Reviewed Head: `4cfdafdb81e901d983b998a0bfdb5497b21bd041`
- Final Judgment: `FAIL`
- Merge Allowed: `BLOCKED`
- Phase Status: `PHASE_2_D11_NEEDS_DELTA_FIX`
- Findings:
  - `P0_ANALYSIS_JOB_ACCESS_METADATA_ABSENCE_FAIL_OPEN`
  - `P1_ANALYSIS_LIST_GUEST_OWN_SESSION_EMPTY_RESULT`
  - `P2_PR_BODY_SENSITIVITY_CHRONOLOGY_MISMATCH`

## P0/P1/P2 Delta

- `D11_DELTA_RED_HEAD` adds test-only reproducers for P0/P1 and corrects the unsafe persisted-output fixture.
- `D11_DELTA_GREEN_HEAD` changes only AnalysisRead GET behavior: missing job access metadata now fails closed as the existing `404` result, and a valid guest session lists only metadata-authorized same-session jobs.
- `D11_DELTA_SENSITIVITY_IMPLEMENTATION_HEAD` adds two direct controls; `D11_DELTA_SENSITIVITY_ANCHOR_CORRECTION_HEAD` repairs the moved D11 list mutation anchor; `D11_DELTA_SENSITIVITY_HEAD` removes an unused import so the repository-wide import gate is clean.
- P0: a real-looking stored job with missing access metadata returns `404 analysis_job_not_found` for Detail and `404 analysis_result_not_found` for Result; neither loader is invoked.
- P1: guest G with session S sees own job A, but not foreign-owner X or metadata-unverifiable M.
- P2: PR chronology will state the original sensitivity sequence correctly and add this Delta history after fresh CI is available.
- P0/P1/P2: `REMEDIATED_PENDING_DELTA_REVIEW`.

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
| `access_metadata_absence_fail_open_bypass` | missing-metadata Detail and Result fail-closed contracts | `AssertionError` |
| `guest_session_list_scope_bypass` | guest G sees only same-session authorized job A | `AssertionError` |

At `964d54ae551f7dc1e6c983966e8c896ed3e0b243`, baseline exit code was `0`; all eleven mutation subprocesses failed directly by `AssertionError`; `source_restored=true`, `working_tree_unchanged=true`, and `residual_diff_zero=true`.

## Verification

- `python backend/manage.py test chatbot.test_phase_02_analysis_read_queries_use_case chatbot.test_production_hardening chatbot.test_supervisor_reporting_pipeline --verbosity 1` — `86 tests, OK`.
- `python -m pytest test/test_analysis_job_query_service.py -q -p no:cacheprovider` — `28 passed`.
- `python -m pytest test/test_phase_02_d11_sensitivity_runner.py -q -p no:cacheprovider` — `4 passed`.
- `python scripts/refactoring/verify_phase_02_d11_analysis_read_queries_sensitivity.py` — baseline `0`, exact `11` direct controls, all `AssertionError`.
- B1–D11 Application/security selection excluding Windows PyMuPDF-bound E2E — `159 tests, OK`; the two excluded `resource_ownership_e2e` tests fail before assertions because `pymupdf._extra` cannot load its native DLL.
- B2–D9 Phase 2 sensitivity runners passed in the all-runner selection; D10 was then rerun in isolation with `7` direct AssertionError controls; D11 was rerun in isolation with `11` direct AssertionError controls. Each reported a clean restore/diff.
- `python backend/manage.py check`, `python scripts/generate_openapi_v1.py --check`, `python scripts/generate_frontend_case_routes.py --check`, `ruff check --select E9,F63,F7,F82 .`, and `ruff check --select F401 app/application/analysis/read_queries.py` — `PASS`.
- `node --test app/web/*.test.js` — `155` passing tests; `npm --prefix app/web run build` — `PASS` (existing bundle-size warning only).
- D1 Docker import smoke: `NOT_EXECUTED_HOST_DOCKER_UNAVAILABLE`.
- D2 canonical Compose gate: `NOT_EXECUTED_HOST_SHELL_PYTHON3_UNAVAILABLE`; no Compose-equivalent result is claimed for this Delta run.

### Windows observation

`python -m pytest -q -p no:cacheprovider` stopped at ten collection errors: `cv2` is unavailable for three modules, `pymupdf._extra` cannot load its native DLL for six modules, and the local ignored `tmp/d11-delta-clean` clone duplicates `--run-live`. There was no D11-specific collection error. `python scripts/refactoring/verify_pytest_collection_baseline.py` reported `new_collection_regression`: the six PyMuPDF DLL errors replace the expected `pypdf` baseline observation. Linux CI remains the full-suite authority.

## CI

- Fresh Delta source Head, synthetic pull-request runtime checkout, `production-gate`, offline verification, Compose integration, regression signal, and the `phase-02-d11-sensitivity-evidence` artifact: `PENDING_DELTA_PUSH`.

## CI follow-up

The first Draft CI source Head `0b0bbcf76e842c4410e8ede1ee086bc064de4a0e` had `regression-signal=success`, but `production-gate` stopped before D11 steps because `chatbot.test_supervisor_reporting_pipeline.SupervisorReportingPipelineTests.test_persisted_job_remains_pollable_without_transient_progress_cache` still patched removed `chatbot.views._analysis_job_access_response`.

`246d55f5fc695082c5108735438794b73f2295d1` changes only that test seam to `app.application.analysis.read_queries._authorize_analysis_job`. That historical compatibility result is preserved. The corrected P2 chronology is: initial sensitivity `83d12ed05c9b562d8e2ab0a77989585dd90ea3c7`; sensitivity syntax correction `a170f58f6e3d718e662b43f2c3a004c4646a5aee`; sensitivity directness correction `b48d4e68aa3ddaf54e259c48241b5946de81cd4f`; production regression compatibility `6f1ade1876f15b99de86323f027d8f597d338de2`; receipt `0b0bbcf76e842c4410e8ede1ee086bc064de4a0e`; supervisor polling compatibility `246d55f5fc695082c5108735438794b73f2295d1`; CI follow-up receipt `4cfdafdb81e901d983b998a0bfdb5497b21bd041`.

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

- Final Judgment: `D11_DELTA_FIX_IMPLEMENTED`
- Merge Allowed: `NOT_YET_REVIEWED`
- P0/P1/P2: `REMEDIATED_PENDING_DELTA_REVIEW`
- Phase Status: `PHASE_2_D11_READY_FOR_DELTA_INDEPENDENT_REVIEW`
- NEXT_STEP: `PHASE_2_D11_DELTA_INDEPENDENT_REVIEW`
- Independent Delta Review, Draft Ready transition, and Merge: `NOT_PERFORMED`
