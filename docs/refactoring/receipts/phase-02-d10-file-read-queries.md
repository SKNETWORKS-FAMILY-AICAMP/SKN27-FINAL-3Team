# Phase 2-D10 FileReadQueries receipt

## Authority

- Repository: `SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team`
- Base: `77d9c9d2434b63c3d3f373f795a579e9066da1aa`
- Branch: `refactor/phase-02-d10-file-read-queries`
- RED_APP Head: `243302dbb66bf986c33bbeb080590ba23a6c8f43`
- GREEN_APP Head: `a96b9e013264c2ca4d3dc1dccb672b83193e272a`
- RED_SECURITY Head: `694153d7e7f47aeacb38a45729aa882b93531474`
- GREEN_SECURITY Head: `6966399736e537c5534943ea9fa1a601982f0f0e`
- Sensitivity Verification Runtime Head: `ec143c3fbddcb1d51c6f517cd9ccc6aa0021903d`
- PR: `PENDING`
- State: `NOT_CREATED`
- Draft: `PENDING`
- Merge: `NOT_PERFORMED`

This receipt does not include its own commit SHA to avoid a self-reference commit loop.

## RED chronology

1. `test: characterize FileReadQueries application seam`
   - Head: `243302dbb66bf986c33bbeb080590ba23a6c8f43`
   - File: `backend/chatbot/test_phase_02_file_read_queries_use_case.py`
   - Command: `python backend/manage.py test chatbot.test_phase_02_file_read_queries_use_case --verbosity 1`
   - Result: `execute_list_file_attachments` and `execute_get_file_attachment` seam assertions each failed before extraction.
2. `refactor: extract FileReadQueries application boundary`
   - Head: `a96b9e013264c2ca4d3dc1dccb672b83193e272a`
   - Result: focused application-seam tests passed.
3. `test: add red coverage for FileRead security boundaries`
   - Head: `694153d7e7f47aeacb38a45729aa882b93531474`
   - Result: 12 tests ran; four security assertions intentionally failed.
4. `fix: harden FileRead ownership and public projection`
   - Head: `6966399736e537c5534943ea9fa1a601982f0f0e`
   - Result: the 12 security tests passed.
5. `test: add phase 2 D10 sensitivity gate`
   - Head: `ec143c3fbddcb1d51c6f517cd9ccc6aa0021903d`
   - Result: baseline and six negative controls passed.

`RED_SECURITY_HEAD` is an ancestor of `GREEN_SECURITY_HEAD`.

## Application boundary

- Routes: `GET /api/files/`, `GET /api/files/<attachment_id>/`
- View: `list_files`, `file_detail`
- Application module: `app/application/files/read_queries.py`
- Commands: `ListFileAttachmentsQuery`, `GetFileAttachmentQuery`
- Executors: `execute_list_file_attachments`, `execute_get_file_attachment`
- Results: `ListFileAttachmentsResult`, `GetFileAttachmentResult`
- Typed errors: `FileReadGuestIdentityInvalid`, `FileReadAccessDenied`, `FileReadNotFound`

The views retain HTTP parsing, trusted request identity reconstruction, and typed-error-to-response mapping. Repository selection, owner/session authorization, guest policy, and public projection are inside the application boundary.

## P0 security remediation

`P0_CANDIDATE_UNSCOPED_FILE_LIST_ENUMERATION` was directly reproduced: a valid guest without a session could receive attachments outside the intended owner/session scope. It is `CONFIRMED` and `REMEDIATED_IN_D10`.

- The list executor does not call `list_uploaded_files(session_id=None, owner_id=None)` on any public route.
- User requests without a session are owner-scoped.
- Guest list requests require an existing authorized session; unscoped guest enumeration is fail-closed with `object_access.v1` and `trusted_scope_required`.
- Detail requests authorize the supplied session, then require the attachment session to match it before owner/guest resource authorization.
- Expired, malformed, and forged guest credentials retain the existing guest identity policy behavior.
- Unknown sessions preserve the owner-scoped empty-list behavior; foreign existing sessions and foreign owner resources are denied.

## Public projection and OpenAPI

`project_file_attachment_public` is the shared list/detail projection. `FileReadAttachment` uses `ConfigDict(extra="forbid")`; list and detail responses therefore permit only:

- `attachment_id`, `case_id`, `session_id`, `message_id`, `purpose`, `type`
- `original_filename`, `filename`, `content_type`, `size_bytes`
- `status`, `scan_status`, `retention_expires_at`, `privacy_risk`, `created_at`, `limitations`

The response excludes `agent_handoff`, `checks`, `deleted_at`, `object_storage`, `persistence`, `scan_result`, and `storage_uri`.

`storage_uri` was also removed from the browser attachment payload. `backend/chatbot/file_scan_service.py` resolves server-side storage data from `attachment_id`; the browser does not need to supply it. The generated `docs/api/openapi-v1.yaml` now maps the GET list/detail surfaces to `FileReadAttachment` with `additionalProperties: false`. The raw `FileAttachment` upload contract remains limited to the POST upload surface and is outside this GET-read remediation.

## Sensitivity

Runner: `scripts/refactoring/verify_phase_02_d10_file_read_queries_sensitivity.py`

| Mutation | Result |
| --- | --- |
| `list_view_application_bypass` | `AssertionError` |
| `detail_view_application_bypass` | `AssertionError` |
| `list_scope_authorization_bypass` | `AssertionError` |
| `detail_owner_authorization_bypass` | `AssertionError` |
| `canonical_guest_policy_bypass` | `AssertionError` |
| `privacy_projection_bypass` | `AssertionError` |

The baseline exit code was `0`; all six mutations failed as expected. `source_restored`, `working_tree_unchanged`, and `residual_diff_zero` were `true`. Evidence: `tmp/phase-02-d10-sensitivity-evidence.json`.

## Verification

- D10 focused: `13 tests, OK`
- B1–D10 application-boundary selection: `115 tests, OK`
- API route/OpenAPI generation selection: `27 passed`
- Frontend node suite: `155 passed`
- Frontend production build: passed
- OpenAPI generation drift check: passed
- D1: `docker build -t skn27-phase-02-d10-local .` passed; Django-initialized module smoke output `D1_IMPORT_SMOKE_PASS`.
- D2: script-equivalent PowerShell execution of `scripts/refactoring/run_phase_00_compose_gate.sh` passed. PostgreSQL, ClamAV, Neo4j, Redis, backend live/ready, agent-worker, and file-scan-worker all passed; `cleanup_success` was recorded. Evidence: `tmp/phase-00-compose-evidence/gate-summary.json`.

### Windows local-suite observation

- `python backend/manage.py test chatbot --verbosity 1`: `570 tests`, `20 errors`, retaining the existing `pymupdf._extra` DLL loading and attachment-classification portability groups.
- `python scripts/refactoring/verify_pytest_collection_baseline.py`: `new_collection_regression`; the expected `cv2` 3-case / `pypdf` 1-case baseline is masked by six `pymupdf._extra` DLL loading collection errors on Windows.
- `python -m pytest -q`: collection stopped with the same 9 errors (`cv2` 3, `pymupdf._extra` DLL 6), so the full pytest test body did not run locally.

These are environment observations, not D10-specific functional regressions. Linux CI remains the authority for the full offline suite.

## CI and release state

- Fresh PR CI: `PENDING`
- Fresh sensitivity artifact: `PENDING`
- Production DB audit: `NOT_EXECUTED`
- Independent Review: `NOT_PERFORMED`
- Draft Ready transition: `NOT_PERFORMED`
- Merge: `NOT_PERFORMED`

## Deferred

- `AnalysisReadQueries`
- guest-session issue, refresh, logout, `auth/me`
- Phase 3 provider, storage, queue/worker, renderer, retry/refund, and transaction architecture work
- `RESUME_GUEST_TRANSPORT_VIEW_CONTRACT_ALIGNMENT`
- `MYPAGE_PUBLIC_PROJECTION_HARDENING_REQUIRED`
- Windows portability debt

`ESTIMATED_REMAINING_PHASE_2_SLICES=6`

## Current status

- Application boundary: `PASS`
- P0 unscoped list enumeration: `REMEDIATED_IN_D10`
- Owner/session/guest authorization: `PASS`
- Public projection: `PASS`
- OpenAPI synchronization: `PASS`
- Sensitivity: `PASS`
- Local Docker D1/D2: `PASS`
- Full Windows pytest: `ENVIRONMENT_BLOCKED`
- CI: `PENDING`
- Independent Review: `NOT_PERFORMED`
- Merge: `NOT_PERFORMED`
