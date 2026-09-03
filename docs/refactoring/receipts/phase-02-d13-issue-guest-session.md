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

## Independent Review — Pre-Delta (historical)

- Reviewed Head: `8bfb6684fa9eb40f8aa64d85e6c50da57f505d50`
- Final Judgment: `FAIL`
- Merge Allowed: `BLOCKED`
- P0: `0`
- P1: `4`
- P2: `1`
- Phase Status: `PHASE_2_D13_NEEDS_DELTA_FIX`
- Findings preserved without rewrite:
  - `P1_D13_EXPLICIT_PUBLIC_PROJECTION_MISSING`
  - `P1_D13_GUEST_SESSION_OPENAPI_RUNTIME_MISMATCH`
  - `P1_D13_WWW_AUTHENTICATE_MISSING`
  - `P1_D13_SENSITIVITY_APPROVED_INVARIANTS_MISSING`
  - `P2_D13_PR_TRACEABILITY_INCOMPLETE`

## Review remediation delta

The original six-commit D13 chronology above remains historical and unchanged.
The append-only remediation chronology is:

```text
8bfb6684fa9eb40f8aa64d85e6c50da57f505d50 PRE_DELTA_REVIEWED_HEAD
→ 04aaff80b6347d60ff4033d01724732268ffec3d DELTA_RED_RUNTIME
→ 6d21985ed524b69c9184e087028d49db66154820 DELTA_GREEN_RUNTIME
→ 39cbee3b5c964b301a42cc2d107efce79d85309e DELTA_RED_SENSITIVITY
→ d1fe4d43bddc87d81bb08a4f01121d00735e0964 DELTA_GREEN_SENSITIVITY
→ 7c27ee03358f1c48069765b2c5da6de97810203f DELTA_GREEN_SENSITIVITY_CORRECTIVE
→ DELTA_DOCS (this Receipt; its own future SHA is intentionally absent)
```

The corrective commit is append-only: it fixes the mutation-child source quoting
defect discovered by the full sensitivity runtime and adds a direct compile guard.
It does not remove, replace, reorder, or rename a control.

### Runtime / contract remediation

- `app/application/auth/issue_guest_session.py` now has the route-specific
  `project_issue_guest_session_public` allow-list. It retains the intentionally
  issued `guest_credential`, copies only safe scalar/list values, and projects
  `guest`, `subject`, `session_binding`, `rate_limit`, `merge_policy`, and
  `persistence` through explicit nested allow-lists before both history recording
  and the response.
- Typed guest-session `401` and `403` responses now set `WWW-Authenticate` using
  `build_www_authenticate_header`; typed `503` continues without that challenge.
- The public guest-session route stays unauthenticated and optional-body, while its
  route spec and generated OpenAPI now describe `401 token_invalid`, `403 forbidden`,
  and `503 provider_unavailable` with `AuthErrorResponse`.
- Direct tests characterize signed-credential subject authority plus exact-one,
  safe `AuthEvent` and `HistoryEvent` semantics in addition to the new projection,
  challenge-header, and route/OpenAPI tests.

### Exact fourteen sensitivity controls and directness

| Order | Control | Source mutation point | Direct detector and observed assertion | Kind |
| --- | --- | --- | --- | --- |
| 1 | `view_application_bypass` | `guest_session` executor reference | executor mock call count becomes `0` | `AssertionError` |
| 2 | `expired_guest_reactivation_bypass` | `_require_issuable_guest_identity` expired check | expired result reason changes from `guest_expired` | `AssertionError` |
| 3 | `merged_guest_reactivation_bypass` | `_require_issuable_guest_identity` active-state check | merged request returns `200`, not `401` | `AssertionError` |
| 4 | `raw_audit_payload_bypass` | guest-session AuthEvent metadata | persisted `raw_payload` is present | `AssertionError` |
| 5 | `non_object_transport_normalization_bypass` | guest-session JSON-object normalization | non-object request returns `500`, not `200` | `AssertionError` |
| 6 | `invalid_credential_unbound_contract_bypass` | invalid-credential session binding gate | invalid credential request returns `403`, not `200` | `AssertionError` |
| 7 | `foreign_session_binding_authorization_bypass` | foreign guest binding mismatch raise | foreign binding returns `200`, not `403` | `AssertionError` |
| 8 | `guest_state_401_mapping_bypass` | `GuestIdentityStateError` typed mapping | expired guest maps to `503`, not `401` | `AssertionError` |
| 9 | `session_binding_403_mapping_bypass` | `SessionBindingError` typed mapping | foreign binding maps to `401`, not `403` | `AssertionError` |
| 10 | `persistence_503_mapping_bypass` | `DatabaseError` typed mapping | persistence failure maps to `401`, not `503` | `AssertionError` |
| 11 | `credential_subject_authority_bypass` | valid credential guest creation authority | forged body guest differs from signed subject | `AssertionError` |
| 12 | `auth_event_bypass` | D13 `_create_auth_event` call | `guest_session_created` AuthEvent count is `0`, not `1` | `AssertionError` |
| 13 | `history_event_bypass` | `_record_history_best_effort(command, payload)` | `guest_session_created` HistoryEvent count is `0`, not `1` | `AssertionError` |
| 14 | `public_projection_bypass` | `project_issue_guest_session_public(...)` call | private `access_token` appears in payload | `AssertionError` |

At `7c27ee03358f1c48069765b2c5da6de97810203f`, the final local runtime
recorded requested Head equal to actual Head, baseline exit `0`, exact `14`
controls in order, every mutation nonzero with `failure_kind=assertion`,
`source_restored=true`, `working_tree_unchanged=true`, `residual_diff_zero=true`,
and status `pass`.

## Delta local verification and fresh-evidence handoff

| Check | Result |
| --- | --- |
| Focused Django D13/runtime/credential/security | `42 tests, OK` |
| Route spec, OpenAPI, auth-session, runner pytest selection | `44 passed` |
| Current discovered B1–D13 use-case modules | `16 modules; 157 tests, OK` |
| Final 14-control sensitivity runtime | `pass` at `7c27ee0…` |
| Django/OpenAPI/frontend-catalog/static checks | `OK` |
| Host Node/npm | `NOT_EXECUTED_HOST_NODE_NPM_UNAVAILABLE` |
| Local compose execution | `NOT_EXECUTED_LOCAL_COMPOSE_DEFERRED_TO_FRESH_CI` |
| Production database | `NOT_EXECUTED` |

The post-push authority must be the final source HEAD, a new pull-request
synthetic runtime checkout, and fresh successful production-gate,
offline-verification, compose-integration, regression-signal, and D13
sensitivity-artifact evidence. No future CI run/job/artifact ID belongs in this
Receipt, avoiding a self-referential docs commit.

## Current remediation status

```text
P0:
CLOSED

P1:
P1_REMEDIATED_PENDING_DELTA_REVIEW

P2:
P2_REMEDIATED_PENDING_DELTA_REVIEW

Merge:
NOT_PERFORMED

Independent Delta Review:
NOT_PERFORMED

Phase Status:
PHASE_2_D13_READY_FOR_DELTA_INDEPENDENT_REVIEW

Next:
PHASE_2_D13_DELTA_INDEPENDENT_REVIEW
```

Deferred without change: RefreshAuthSession, LogoutAuthSession, D14, Phase 2
Exit Review, Phase 3, frontend production, Docker/Compose source, and the
global auth response `extra` policy.
