# Phase 2-D13 IssueGuestSession implementation receipt

## Authority

- Repository: `SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team`
- Base: `5b86f4a357b6c156d3c9e92845f62f038cede4ee`
- Branch: `refactor/phase-02-d13-issue-guest-session-use-case`
- RED_SECURITY Head: `f594e2ebadd103f5c10a0922bee02793156a4b48`
- GREEN_SECURITY Head: `3c0dc1277586cc1581c2890673acdf05595d6ab3`
- RED_APP Head: `d79657d07d2c74ab66ac613469245130b697567a`
- GREEN_APP Head: `e099e423262c64d23e084195566b064dc949ea11`
- Sensitivity Runtime Head: `d467e094cb7cf2aab2ec66d2910fc87b8a18c7ed`
- PR: `PENDING_DRAFT_PR_CREATION` at Receipt commit time.
- Self-reference: this Receipt records no future Receipt SHA, CI run, runtime checkout, or artifact ID.

## Security and public contract

- A signed credential for a persisted `EXPIRED` identity fails closed as `401 token_invalid / guest_expired`; a `MERGED` identity fails closed as `401 token_invalid / guest_inactive`.
- `persist_guest_session_identity` uses `transaction.atomic()` and `select_for_update()` for an existing guest row, validates issue eligibility before and after its update, and never rewrites a terminal state to `ACTIVE`.
- Guest-session transport normalizes every non-object JSON value to `{}` before it reaches the issuance service.
- An invalid credential continues to issue a new unbound guest and ignores body-supplied identity and session binding.
- A valid credential cannot bind a foreign guest chat session; the existing `403 forbidden / guest_session_binding_mismatch` contract remains unchanged.
- `DatabaseError` remains `503 provider_unavailable / guest_session_store_unavailable` with `required_action=retry`.
- The guest-session `AuthEvent` retains only allow-listed audit facts: `source` and the resolved `chat_session_id`. It never stores the raw request body or request secret markers.

## Application boundary

- Module: `app/application/auth/issue_guest_session.py`.
- DTOs: `IssueGuestSessionCommand` and `IssueGuestSessionResult` carry normalized input, injected existing collaborators, and the compatible response payload.
- Typed outcomes `IssueGuestSessionInvalid`, `IssueGuestSessionAccessDenied`, and `IssueGuestSessionPersistenceUnavailable` preserve the view's `401` / `403` / `503` response mapping.
- `guest_session` now performs HTTP parsing and non-object normalization, invokes `execute_issue_guest_session`, and serializes its typed outcome.
- Guest issuance stays in the existing auth service; persisted-state validation and session binding stay in the repository. The application layer contains no ORM access and no raw request audit persistence.
- Successful history remains best effort and derives actor, subject, session binding, and metadata from the issued payload, not the request body.

## RED, GREEN, and chronology

- `f594e2e` is test-only RED_SECURITY; no production file changed there.
- `3c0dc12` completes GREEN_SECURITY before any application extraction.
- `d79657d` adds only the RED_APP delegation test; it failed by direct `AssertionError` because the view did not invoke `execute_issue_guest_session`.
- `e099e42` completes GREEN_APP by adding the application command and thinning the view.
- `d467e09` adds the exact-ten sensitivity runner, its runner contract test, and blocking CI evidence artifact wiring.

## Exact sensitivity controls

Runner: `scripts/refactoring/verify_phase_02_d13_issue_guest_session_sensitivity.py`

| Control | Direct detector | Result |
| --- | --- | --- |
| `view_application_bypass` | guest-session executor seam | `AssertionError` |
| `expired_guest_reactivation_bypass` | expired persisted guest fail-closed contract | `AssertionError` |
| `merged_guest_reactivation_bypass` | merged persisted guest fail-closed contract | `AssertionError` |
| `raw_audit_payload_bypass` | request-secret audit exclusion | `AssertionError` |
| `non_object_transport_normalization_bypass` | truthy non-object JSON normalization | `AssertionError` |
| `invalid_credential_unbound_contract_bypass` | invalid credential new-unbound contract | `AssertionError` |
| `foreign_session_binding_authorization_bypass` | foreign guest binding authorization | `AssertionError` |
| `guest_state_401_mapping_bypass` | persisted guest-state 401 mapping | `AssertionError` |
| `session_binding_403_mapping_bypass` | session-binding 403 mapping | `AssertionError` |
| `persistence_503_mapping_bypass` | persistence-unavailable 503 mapping | `AssertionError` |

At `d467e094cb7cf2aab2ec66d2910fc87b8a18c7ed`, the fresh runner recorded baseline exit `0`, exactly `10` nonzero mutation results, all `assertion`, `source_restored=true`, `working_tree_unchanged=true`, `residual_diff_zero=true`, and `status=pass`.

## Verification

| Check | Result |
| --- | --- |
| D13 + runtime + credential + D12 focused regression | `35 tests, OK` |
| All discovered Phase 2 use-case modules | `152 tests, OK` |
| Guest runtime, credential boundary, and security hardening | `30 tests, OK` |
| D13 runner contract | `5 passed` |
| Auth-session/API/OpenAPI/runner Python selection | `74 passed`; 2 host-Node-dependent tests could not start |
| Django system check | `OK` |
| OpenAPI generation drift check | current |
| Frontend case-route drift check | current |
| Ruff `E9,F63,F7,F82` plus D13 `F401` guard | passed |
| D13 sensitivity | baseline `0`, `10/10` assertion, pass |
| `git diff --check` | clean before this Receipt change |

The two Python-selection exceptions came from `FileNotFoundError: node`; direct `node --version` returned `command not found`. No Node, npm, frontend source, Docker, production database, or host-environment change is part of D13.

## CI handoff and scope

- `production-gate.yml` adds blocking D13 boundary and sensitivity steps, the runtime authority `PHASE_02_D13_SENSITIVITY_HEAD: ${{ github.sha }}`, the `phase-02-d13-sensitivity-evidence` artifact, and a D13 F401 import guard.
- The next authorized lifecycle action is push, Draft PR creation, then fresh CI/artifact collection. This task must stop after that fresh evidence.
- Not implemented or changed: RefreshAuthSession, LogoutAuthSession, D14, Phase 2 Exit Review, Phase 3, independent review, merge, cleanup, or Draft-to-ready conversion.
