# Phase 2-D12 GetCurrentAuthIdentity implementation receipt

## Authority
- Repository: SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team
- Base: fb9b2fbfc614bc67aa8019d8c4da47071bbef4c9 (dev and origin/dev at work start)
- Branch: refactor/phase-02-d12-get-current-auth-identity
- RED_SECURITY Head: 1b5760785520681c98ff8740614091e2c51d938a
- GREEN_SECURITY Head: aaf3fe937c343b23a559aefd8db5126c1858e607
- RED_APP Head: 8c72102b5c31166d8e6708aeb763835b18324a51
- GREEN_APP Head: 14e780966b1d5af907375adb1c79df8a6279da8d
- Sensitivity Runtime Head: bde41e12fe63ab08c029b691308df54b09566b16
- PR: PENDING_DRAFT_PR_CREATION at Receipt commit time.
- Self-reference: this Receipt deliberately records no future Receipt SHA, CI run, synthetic SHA, or artifact ID.

## Decision and public contract
- AUTH_ME_TRANSPORT_DECISION=PRESERVE_ACTUAL_EXTERNAL_CONTRACT.
- External anonymous GET /api/auth/me/ remains 401 auth_required.
- OpenAPI requires bearer OR signed guest credential; it does not advertise anonymous access.
- Middleware was not modified and /api/auth/me/ was not made public.
- The service-level anonymous branch remains internal and is not an external transport success path.
- AUTH_ME_GET_MUTATION_SEMANTICS_PRESERVED.
- Authenticated persisted user/AuthSession requests retain the public auth/me contract.
- Signed guest credential requests retain the public guest identity contract and bootstrap behavior.
- No credential, malformed/invalid credential, and invalid persisted authority return the existing 401 contract.
- Session binding errors map to 403 forbidden and persistence DatabaseError maps to retryable 503 provider_unavailable.

## Security and state
- Conflicting X-Guest-Id and query guest_id fail closed with guest_identity_source_mismatch.
- Existing expired or inactive GuestIdentity rows fail closed; an absent row with a valid signed credential retains bootstrap 200 behavior.
- Active persisted AuthSession and user state remain authoritative; unpersisted or invalid user JWT authority is rejected.
- Persistence failure returns auth_me_persistence_unavailable with required_action=retry.
- The Application result uses explicit public projection and excludes credential, token, and raw-claim fields.

## Application boundary
- Module: app/application/auth/get_current_identity.py.
- DTOs: GetCurrentAuthIdentityQuery and GetCurrentAuthIdentityResult carry transport-normalized input and the projected result.
- Typed errors: invalid, access-denied, and persistence-unavailable map in the View to the existing HTTP response contract.
- auth_me now parses HTTP input, creates the query, invokes execute_get_current_auth_identity, and serializes typed outcomes.
- Existing service validation and repository persistence/history helpers are reused; the Application layer contains no ORM access.

## Transaction and history
- persist_current_auth_subject remains before the successful response and preserves optional session binding semantics.
- Repository persistence continues to create the current AuthEvent receipt.
- auth_me_checked HistoryEvent is recorded after successful persistence and remains best-effort.
- History persistence failure does not change an already-successful auth/me response.
- Transaction/outbox architecture changes are deferred; this Slice preserves the existing GET mutation decision.

## RED, GREEN and intentional drift
- RED security was test-only in 1b576078; GREEN security followed in aaf3fe9.
- RED application seam was test-only in 8c72102; GREEN Application extraction followed in 14e7809.
- Both RED tests failed by direct AssertionError, and both RED-to-GREEN ancestry checks exited 0.
- The GREEN View keeps the compatibility alias for _get_current_auth_subject because unrelated routes import it; auth/me itself no longer orchestrates through that alias.
- Sensitivity correction commits 49fd618 and bde41e1 changed only the runner/test so the OpenAPI negative control remains a valid non-anonymous RouteSpec and reaches its direct assertion detector.

## Sensitivity
env PHASE_02_D12_SENSITIVITY_HEAD=bde41e12fe63ab08c029b691308df54b09566b16 .venv/bin/python scripts/refactoring/verify_phase_02_d12_get_current_auth_identity_sensitivity.py recorded baseline exit 0, all nine assertion failures, source restoration, unchanged worktree, residual diff zero, and status: pass.

| Control | Direct detector | Result |
|---|---|---|
| view_application_bypass | View executor seam | AssertionError |
| anonymous_transport_contract_bypass | OpenAPI bearer-or-guest contract | AssertionError |
| guest_identity_source_mismatch_bypass | conflicting guest IDs | AssertionError |
| persisted_guest_state_bypass | expired guest row | AssertionError |
| persisted_auth_session_bypass | unpersisted JWT authority | AssertionError |
| session_binding_authorization_bypass | binding 403 mapping | AssertionError |
| persistence_failure_mapping_bypass | persistence 503 mapping | AssertionError |
| history_event_bypass | successful history sequencing | AssertionError |
| private_projection_bypass | credential/raw-claim exclusion | AssertionError |

## Verification
- Focused: .venv/bin/python backend/manage.py test chatbot.test_phase_02_get_current_auth_identity_use_case chatbot.test_guest_credential_boundary chatbot.test_security_hardening --verbosity 1.
- B1-D11: .venv/bin/python backend/manage.py test for the 14 discovered chatbot.test_phase_02_*_use_case modules excluding D12.
- Python contracts: .venv/bin/python -m pytest test/test_auth_session_service.py test/test_frontend_auth_session_contract.py test/test_api_route_specs.py test/test_openapi_v1_generation.py test/test_phase_02_d12_sensitivity_runner.py -q -p no:cacheprovider.
- Static: .venv/bin/python backend/manage.py check; generate_openapi_v1.py --check; generate_frontend_case_routes.py --check; required Ruff selectors; git diff --check.

| Check | Result |
|---|---|
| D12 focused + guest credential + security | 42 tests, OK |
| B1-D11 Application boundary modules | 131 tests, OK |
| AuthSession persistence-lock regression | 1 test, OK |
| Python service/OpenAPI/runner pytest subset | 42 passed |
| Prescribed pytest including frontend contract | 67 passed, 2 failed only because host node executable is absent |
| D12 sensitivity | baseline 0, 9/9 AssertionError, pass |
| Django check | OK |
| OpenAPI generation check | current |
| Frontend case-route generation check | current |
| Ruff E9,F63,F7,F82 and D12 F401 guard | All checks passed |
| git diff --check | clean |
| Frontend node --test / npm run build | NOT_EXECUTED_HOST_NODE_NPM_UNAVAILABLE |
| Docker D1 build/import smoke | NOT_EXECUTED_HOST_DOCKER_IMAGE_PULL_STALLED after more than seven minutes before image creation |
| Compose D2 | NOT_EXECUTED_USER_SCOPE_CLEANUP_PROHIBITED |
| Windows | NOT_EXECUTED_WINDOWS_HOST_UNAVAILABLE; no Windows shell was present |
| Production DB audit | NOT_EXECUTED |

## CI
- Initial Draft PR #416 CI authority failure:
  - production-gate `33172045718`: failed.
  - offline-verification job `98851313081`: failed.
  - compose-integration job `98852385504`: skipped.
  - regression-signal `33172045698` / job `98851312730`: success.
  - failed phase-02-d12-sensitivity-evidence artifact: `9686120723`.
- The initial PR Source Head was `a3e3e20b5aa3fe9e2c94deb51275f16d0390e653`, but the workflow checkout was synthetic merge SHA `eb11bc7d6f6872add3aabca46de8bfa97cff21bc`.
- Root cause: `PHASE_02_D12_SENSITIVITY_HEAD` passed the PR Source Head to a runner executing at the synthetic checkout, so the stale-head guard correctly failed before mutations.
- Classification: `CI_AUTHORITY_PROPAGATION_DEFECT`. Production defect: NO. Application defect: NO. Security contract defect: NO. Sensitivity guard defect: NO.
- Remediation RED: `9e8269e1f83fb900107d0824f5203b652bfdc78d` adds the direct D12 workflow runtime-authority contract test and failed by AssertionError before the workflow change.
- Remediation GREEN: `c37cdb09c7f85ad1808465679faf0d6800463783` changes only the D12 workflow authority expression to `PHASE_02_D12_SENSITIVITY_HEAD: ${{ github.sha }}`. The stale-head guard, checkout action, artifact contract, and D1-D11 workflow remain unchanged.
- Green local runtime sensitivity passed with `head == actual_head == c37cdb09c7f85ad1808465679faf0d6800463783`, baseline exit 0, all nine AssertionError mutations, source restoration, unchanged worktree, and residual diff zero.
- Fresh CI and artifact identity will be recorded in PR #416 after this Docs commit; no Receipt self-reference commit records future CI IDs.

## Independent Review — Pre-P2-Remediation
- Reviewed Head: `6e6b7f0176a35b3867398c658728dda16d56b1d4`.
- Final Judgment: `PASS_WITH_CONDITIONS`.
- Merge Allowed: `ALLOWED_AFTER_P2_FIX`.
- P0: `0`.
- P1: `0`.
- P2: `1`.
- Finding: `P2_D12_SENSITIVITY_CONTROL_NAME_SEMANTIC_MISMATCH`.
- Phase Status: `PHASE_2_D12_NEEDS_DELTA_FIX`.

## Sensitivity Control Semantic Remediation
- D12_P2_RED_HEAD: `a2978ea94d702388391f37a3b9c6e3bfc3bba6a7`.
- D12_P2_GREEN_HEAD: `a96dc3147adbfabbb8c24e43ef516529ef394ad3`.
- Old control: `anonymous_transport_contract_bypass`.
- New control: `signed_guest_security_alternative_removal`.
- Actual mutation: signed guest security alternative removed; Bearer-only remains.
- Direct detector: `test_openapi_requires_bearer_or_signed_guest_credential`.
- Detector/invariant coverage changed: `NO`.
- Mutation implementation changed: `NO`, except dispatch/key rename.
- Exact mutation count: `9`.
- Local sensitivity evidence at GREEN Head: baseline exit `0`; all `9` controls failed by direct `AssertionError`; `head == actual_head == a96dc3147adbfabbb8c24e43ef516529ef394ad3`; source restored, worktree unchanged, and residual diff zero were all `true`.
- Production behavior changed: `NO`.
- Application/View changed: `NO`.
- OpenAPI behavior changed: `NO`.
- Workflow changed: `NO`.
- P0: `CLOSED`.
- P1: `CLOSED`.
- P2: `P2_REMEDIATED_PENDING_DELTA_REVIEW`.
- Merge: `NOT_PERFORMED`.
- Independent Delta Review: `NOT_PERFORMED`.
- Self-reference: this Receipt records no future Receipt SHA, CI run/job, synthetic SHA, or artifact ID; fresh CI/artifact metadata belongs only in PR #416.

## Scope
- Production: get_current_identity Application boundary, auth/me View thinning, guest source normalization/state authority, and OpenAPI correction.
- Tests: D12 characterization/security coverage, existing contract expectation updates, and sensitivity runner coverage.
- Workflow: blocking D12 boundary, sensitivity, artifact, and F401 gates in production-gate.yml.
- Docs: this Receipt and generated docs/api/openapi-v1.yaml.
- Not modified: frontend production source, middleware, models/migrations, guest-session/refresh/logout flows, D13, Phase 3, and Production DB.

## Deferred
- IssueGuestSession, RefreshAuthSession, and LogoutAuthSession remain separate Phase 2 slices.
- Phase 3 work and transaction/outbox redesign remain deferred.
- Windows portability debt, host Node/npm availability, Docker image-pull availability, and Production DB audit are not source changes in this Slice.

## Historical Status at Initial CI-Authority-Remediation Handoff
- Historical Draft status at that handoff: PR #416 was OPEN and had to remain Draft.
- Historical Independent Review status at that handoff: not performed.
- Historical Merge status at that handoff: not performed.
- Historical status at that handoff: `D12_CI_REMEDIATED_PENDING_FRESH_CI`.
- Historical current pre-merge remaining at that handoff: 4.
- Historical projected remaining after D12 merge at that handoff: 3; authoritative recount was required after merge.
- Historical PHASE_2_EXIT_REVIEW_REQUIRED=YES.
- Historical next step after fresh CI/artifact: PHASE_2_D12_INDEPENDENT_REVIEW.

## Independent P2 Delta Review — Pre-Receipt-Status-Fix
- Reviewed Head: `ce4f3521deeb9303c45f63f30098abb129565016`.
- Final Judgment: `PASS_WITH_CONDITIONS`.
- Merge Allowed: `ALLOWED_AFTER_P2_FIX`.
- P0: `0`.
- P1: `0`.
- P2: `1`.
- Finding: `P2_D12_RECEIPT_STALE_CURRENT_STATUS`.
- Phase Status: `PHASE_2_D12_NEEDS_DELTA_FIX`.

## Current Status After Receipt Clarification
- P0: `CLOSED`.
- P1: `CLOSED`.
- P2: `P2_REMEDIATED_PENDING_RECEIPT_DELTA_REVIEW`.
- Receipt status clarification: `COMPLETED`.
- Runtime/Application behavior changed: `NO`.
- Tests/sensitivity/workflow changed: `NO`.
- Draft: `true`.
- Merge: `NOT_PERFORMED`.
- Independent Receipt Delta Review: `NOT_PERFORMED`.
- Phase Status: `PHASE_2_D12_READY_FOR_RECEIPT_STATUS_DELTA_INDEPENDENT_REVIEW`.
- Next step: `PHASE_2_D12_RECEIPT_STATUS_DELTA_INDEPENDENT_REVIEW`.
- Current pre-merge remaining: `4`.
- Projected after D12 merge: `3`.
- Authoritative recount: `REQUIRED_AFTER_MERGE`.
- PHASE_2_EXIT_REVIEW_REQUIRED: `YES`.
