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
- Reviewed Pre-delta Head: `33143f87d7e192aa235967418776d8a77131f6bc`
- Delta RED Head: `f39e83c08f4f2ac912e3b4074d4a759429e5c740`
- Delta GREEN Head: `68cd3ba69ff163225bc5aa0f1f6fb063af825c79`
- Delta Sensitivity Head: `b4219ad1e7a05222087b6da1b7f4dfc2606c6686`
- PR: `#414`
- State: `OPEN`
- Draft: `true`
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
6. `test: reproduce guest-session cross-owner FileRead disclosure`
   - Head: `f39e83c08f4f2ac912e3b4074d4a759429e5c740`
   - Result: valid guest G, guest-authorized session S, legitimate attachment A, and foreign-owner attachment X.session_id=S fixture에서 `GET /api/files/?session_id=S`가 X를 노출하는 `AssertionError`를 재현했다.
7. `fix: enforce per-attachment authorization in FileRead list`
   - Head: `68cd3ba69ff163225bc5aa0f1f6fb063af825c79`
   - Result: candidate attachment를 `get_uploaded_file_access_metadata`와 `authorize_resource_access`로 검증한 후에만 public projection하도록 변경했다.
8. `test: cover guest-session cross-owner FileRead sensitivity`
   - Head: `ab815e4c4ad68745af91c7478f9525209fe53cc3`
   - Result: `guest_session_attachment_owner_bypass`와 exact seven-mutation contract를 추가했다.
9. `fix: preserve D10 detail sensitivity mutation`
   - Head: `b4219ad1e7a05222087b6da1b7f4dfc2606c6686`
   - Result: 새 list helper와 충돌하지 않도록 `detail_owner_authorization_bypass` mutation anchor를 detail-only 문맥으로 고정했다.

`RED_SECURITY_HEAD` is an ancestor of `GREEN_SECURITY_HEAD`. `D10_DELTA_RED_HEAD` is an ancestor of `D10_DELTA_GREEN_HEAD`, and all Delta commits are append-only descendants of `33143f87d7e192aa235967418776d8a77131f6bc`.

## Application boundary

- Routes: `GET /api/files/`, `GET /api/files/<attachment_id>/`
- View: `attachments`, `attachment_detail`
- Application module: `app/application/files/read_queries.py`
- Commands: `ListFileAttachmentsQuery`, `GetFileAttachmentQuery`
- Executors: `execute_list_file_attachments`, `execute_get_file_attachment`
- Results: `ListFileAttachmentsResult`, `GetFileAttachmentResult`
- Typed errors: `FileReadGuestIdentityInvalid`, `FileReadAccessDenied`, `FileReadNotFound`

The views retain HTTP parsing, trusted request identity reconstruction, and typed-error-to-response mapping. Repository selection, owner/session authorization, guest policy, and public projection are inside the application boundary.

## P0 security delta remediation

### Initial implementation and pre-delta Independent Review

Initial implementation blocked unscoped guest-without-session enumeration. However, the Independent Review of `33143f87d7e192aa235967418776d8a77131f6bc` independently found `P0_CROSS_OWNER_FILE_LIST_DISCLOSURE`: guest G authorized session S, while a legacy/inconsistent `UploadedFile` X had `session_id=S` and `owner_id=authenticated user B`. `GET /api/files/?session_id=S` returned X metadata with HTTP `200`; direct detail access to X correctly returned `403`.

The root cause was the guest list path passing `owner_id=None` to `list_uploaded_files`, which consequently applied only the session filter. The list route then projected raw candidates without individual attachment authorization. There is no database constraint that prevents this legacy/inconsistent owner/session relation; this Delta intentionally does not add a migration or redesign persistence.

### Delta remediation

- Collection scope authorization remains separate: users are owner-scoped; guests require an authorized session; guest requests with no session remain fail-closed.
- Every candidate now loads `get_uploaded_file_access_metadata` and uses the existing `authorize_resource_access` contract before `project_file_attachment_public`.
- Owner precedence is unchanged: resource `owner_id=B` and guest G is denied even when `session_id=S` matches.
- `test_guest_session_list_excludes_foreign_owner_attachment_even_when_session_matches` proves legitimate guest-bound A remains in the HTTP `200` list while foreign-owner X, its `attachment_id`, `original_filename`, and `filename` are absent.
- Detail semantics are unchanged: foreign owner and supplied session mismatch remain `403`.

`P0_CROSS_OWNER_FILE_LIST_DISCLOSURE`: `REMEDIATED_PENDING_DELTA_REVIEW`.

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
| `guest_session_attachment_owner_bypass` | `AssertionError` |

The baseline exit code was `0`; all seven mutations failed directly by assertion. The seventh mutation removes the per-attachment list authorization call and is detected by `test_guest_session_list_excludes_foreign_owner_attachment_even_when_session_matches`. At `b4219ad1e7a05222087b6da1b7f4dfc2606c6686`, `source_restored`, `working_tree_unchanged`, and `residual_diff_zero` were `true`.

`P1_SENSITIVITY_GUEST_SESSION_INCONSISTENT_RELATION_GAP`: `REMEDIATED_PENDING_DELTA_REVIEW`.

## P2 metadata correction

- PR metadata: `#414`, `OPEN`, Draft `true`, Merge `NOT_PERFORMED`.
- View metadata: `attachments` and `attachment_detail` match `backend/chatbot/views.py`.
- Pre-delta CI is no longer recorded as pending: production-gate `32578985125`, offline-verification `97045414143`, compose-integration `97046155784`, and regression-signal `32578985127` completed successfully for `33143f87d7e192aa235967418776d8a77131f6bc`.
- The historical Independent Review remains authoritative for its reviewed Head: `FAIL`, `BLOCKED`, and `PHASE_2_D10_NEEDS_DELTA_FIX`; it identified `P0_CROSS_OWNER_FILE_LIST_DISCLOSURE`, `P1_SENSITIVITY_GUEST_SESSION_INCONSISTENT_RELATION_GAP`, `P2_RECEIPT_PR_CI_METADATA_STALE`, and `P2_RECEIPT_VIEW_NAME_MISMATCH`.

`P2_RECEIPT_PR_CI_METADATA_STALE` and `P2_RECEIPT_VIEW_NAME_MISMATCH`: `REMEDIATED_PENDING_DELTA_REVIEW`.

## Verification

- Delta D10 focused: `python backend/manage.py test chatbot.test_phase_02_file_read_queries_use_case --verbosity 1` — `14 tests, OK`.
- Delta P0 direct RED: `test_guest_session_list_excludes_foreign_owner_attachment_even_when_session_matches` failed with the expected foreign attachment disclosure before the GREEN commit and passed after it.
- Delta sensitivity: baseline `0`, exact mutations `7`, all direct `AssertionError`, `source_restored=true`, `working_tree_unchanged=true`, `residual_diff_zero=true` at `b4219ad1e7a05222087b6da1b7f4dfc2606c6686`.
- B1–D10 application-boundary selection, API route/OpenAPI generation selection, frontend suite/build, and OpenAPI drift results below are pre-delta evidence until the final Delta Head is verified.
- D1/D2 results below are pre-delta evidence. Fresh final-Delta local Docker/Compose provenance is recorded separately in `Final Delta verification provenance` and is distinct from GitHub CI evidence.

### Windows local-suite observation

- `python backend/manage.py test chatbot --verbosity 1`: `570 tests`, `20 errors`, retaining the existing `pymupdf._extra` DLL loading and attachment-classification portability groups.
- `python scripts/refactoring/verify_pytest_collection_baseline.py`: `new_collection_regression`; the expected `cv2` 3-case / `pypdf` 1-case baseline is masked by six `pymupdf._extra` DLL loading collection errors on Windows.
- `python -m pytest -q`: collection stopped with the same 9 errors (`cv2` 3, `pymupdf._extra` DLL 6), so the full pytest test body did not run locally.

These are environment observations, not D10-specific functional regressions. Linux CI remains the authority for the full offline suite.

## CI and release state

- Reviewed Pre-delta Head: `33143f87d7e192aa235967418776d8a77131f6bc`
- Pre-delta production-gate: `32578985125` / `SUCCESS`
- Pre-delta offline-verification: `97045414143` / `SUCCESS`
- Pre-delta compose-integration: `97046155784` / `SUCCESS`
- Pre-delta regression-signal: `32578985127` / `SUCCESS`
- Final Delta GitHub blocking CI completed successfully before this docs-only provenance correction; the exact run, job, artifact, and synthetic checkout are recorded in `Final Delta verification provenance`.
- Fresh CI for this docs-only provenance commit is intentionally not self-referenced here to avoid a further Receipt commit loop.
- Production DB audit: `NOT_EXECUTED`
- Pre-delta Independent Review: `FAIL` / `BLOCKED` / `PHASE_2_D10_NEEDS_DELTA_FIX`
- Delta Independent Review — Pre-P2-Provenance-Fix: `PASS_WITH_CONDITIONS` / `ALLOWED_AFTER_P2_FIX` / `PHASE_2_D10_NEEDS_DELTA_FIX`.
- Docs-only provenance Delta Review: `NOT_PERFORMED`.
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
- P0 unscoped list enumeration: `REMEDIATED_IN_D10` (historical)
- P0 cross-owner guest-session list disclosure: `CLOSED` by the Delta Independent Review; this docs-only correction does not alter the runtime closure.
- P1 guest-session inconsistent-relation sensitivity gap: `CLOSED` by the Delta Independent Review with `guest_session_attachment_owner_bypass` and `test_guest_session_list_excludes_foreign_owner_attachment_even_when_session_matches`.
- P2 Receipt PR/CI metadata and view-name mismatch: `CLOSED` by the Delta Independent Review; this docs-only correction addresses the separate fresh D1/D2 provenance finding.
- P2 fresh D1/D2 provenance: `P2_REMEDIATED_PENDING_DOCS_DELTA_REVIEW`.
- Owner/session/guest authorization: `PASS` in Delta focused coverage
- Public projection: `PASS` in Delta focused coverage
- Sensitivity: `PASS` with `7` direct mutations
- Fresh Delta local Docker D1: `PASS`; D2: `PASS`; `cleanup_success=true`.
- Full Windows pytest: `ENVIRONMENT_BLOCKED`
- Final Delta GitHub blocking CI: `SUCCESS`; fresh CI for this docs-only provenance commit is `PENDING` and intentionally not self-referenced here.
- Delta Independent Review — Pre-P2-Provenance-Fix: `PASS_WITH_CONDITIONS` / `ALLOWED_AFTER_P2_FIX` / `PHASE_2_D10_NEEDS_DELTA_FIX`.
- Docs-only provenance Delta Review: `NOT_PERFORMED`.
- Merge: `NOT_PERFORMED`

## Final Delta verification provenance

### Local Final Delta verification

- Reviewed Final Delta Head: `1a2da456c0132fdb5179eaca879b85da979e7668`
- D1: `PASS`
  - Execution timing: Final Delta Head 생성 이후. Local image `skn27-phase-02-d10-delta-local` was created at `2026-08-26T05:18:20.373905635Z` (`2026-08-26 14:18:20 KST`).
  - Purpose: Docker image build and D1 import-smoke verification.
  - Build command: `docker build --progress=quiet -t skn27-phase-02-d10-delta-local .`.
  - Import-smoke command: `docker run --rm -e DJANGO_SETTINGS_MODULE=config.settings skn27-phase-02-d10-delta-local python -c "import django; django.setup(); from app.application.files.read_queries import execute_list_file_attachments; print('D1_IMPORT_SMOKE_PASS')"`.
  - Evidence: `D1_IMPORT_SMOKE_PASS`.
  - Repository source changed by verification: `NO`.
- D2: `PASS`
  - Gate: `scripts/refactoring/run_phase_00_compose_gate.sh`.
  - Evidence timestamp: `2026-08-26 14:26 KST`.
  - `gate-summary.json`: `status=pass`, backend ready/live, agent worker consumed, and file scan worker consumed.
  - `cleanup_success`: `true`; the Compose project left no container or volume residue.
- External LF normalization shim: `USED`.
  - Purpose: Windows host line-ending normalization only; Python subprocess CRLF output was normalized to LF before Git Bash `read` consumed probe identifiers.
  - Repository source modified: `NO`.
  - Canonical gate script modified: `NO`.
  - Docker/Compose semantics modified: `NO`.
  - The shim changed no authorization logic, test result, health condition, timeout, service dependency, Compose manifest, or repository script.

### GitHub blocking CI for Final Delta Head

- production-gate: `32934110180` / `SUCCESS`
- offline-verification: `98071933549` / `SUCCESS`
- compose-integration: `98072987523` / `SUCCESS`
- regression-signal: `32934110157` / `98071933390` / `SUCCESS`
- D10 sensitivity artifact: `9594311701` (`phase-02-d10-sensitivity-evidence`).
  - Source Head: `1a2da456c0132fdb5179eaca879b85da979e7668`
  - Synthetic runtime checkout: `49a613327fc0faf5e9cfd6747ef7f74a95c8751a`
  - baseline: `0`; mutations: `7`; all: `AssertionError`.
  - `source_restored=true`, `working_tree_unchanged=true`, `residual_diff_zero=true`.

Local D1/D2 and GitHub CI are separate evidence sources. Fresh CI generated by this docs-only provenance commit is intentionally not added to this Receipt, preventing a self-reference commit loop.

## Delta Independent Review — Pre-P2-Provenance-Fix

- Reviewed Head: `1a2da456c0132fdb5179eaca879b85da979e7668`
- P0: `0` — `P0_CROSS_OWNER_FILE_LIST_DISCLOSURE` closed: legitimate guest attachment A remained and foreign-owner attachment X was excluded.
- P1: `0` — `P1_SENSITIVITY_GUEST_SESSION_INCONSISTENT_RELATION_GAP` closed with `guest_session_attachment_owner_bypass` and its direct detector.
- P2: `1` — `P2_RECEIPT_FRESH_D1_D2_PROVENANCE_STALE`.
- Final Judgment: `PASS_WITH_CONDITIONS`.
- Merge Allowed: `ALLOWED_AFTER_P2_FIX`.
- Phase Status: `PHASE_2_D10_NEEDS_DELTA_FIX`.

This is historical review authority before the docs-only provenance correction. It does not declare `PHASE_2_D10_READY_TO_MERGE`, `PASS`, or `ALLOWED`.
