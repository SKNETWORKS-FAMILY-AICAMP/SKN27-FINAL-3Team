# Phase 2-D7 GetMyPageSummary Security Delta

## Authority

- Repository: `SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team`
- PR: `#411`
- State: `OPEN`
- Draft: `true`
- Merge: `NOT_PERFORMED`
- Base: `c2f1b721640e2d97b84d27ddb4d1515b59860421`
- Branch: `refactor/phase-02-d7-get-mypage-summary-use-case`
- Original RED Head: `46bdd78a9170f3f44fe37ab6206111fd27106908`
- Original GREEN Head: `d7959b32cdbd402acba005aeb4a21d5eb0bcbaac`
- Pre-fix Reviewed Head: `bf0736acbb91c48dcf06bcb8af7de3ae80114fc9`
- Security RED Head: `4fa4e57324f768503d4c7fdacef9ed59eacf7f37`
- Security GREEN Head: `ffe3f003c2ab99b54842bd722aa1b621fda2b469`
- Verification Head: `e0d6a819949e7a90ac090707d82489bd5dc66263`
- Reviewed Final Runtime Head: `cc42b371aea64ec781c6815a39991835febf31e7`

이 Receipt는 security fix와 sensitivity verification, 그리고 독립 검토가 확인한 Reviewed Final Runtime Head `cc42b371aea64ec781c6815a39991835febf31e7`를 기록한다. 이어지는 docs-only metadata remediation commit은 자기 자신의 미래 Git SHA를 본문에 기록하지 않는다. Docs Delta Head authority는 Git과 PR metadata에서 확인한다.

## Independent Review Finding

- P0: `Cross-owner session_cache disclosure`
  - authenticated A가 `owner_id=A&session_id=B`로 요청하면 B의 `session_cache.snapshot.owner_id`를 포함한 cache metadata를 받았다.
- P1: `owner_session_fence_bypass` sensitivity가 foreign owner assertion만 실행하여 mixed session fence를 직접 검출하지 못했다.
- P2: Receipt의 PR metadata가 stale였고 foreign owner/session data가 항상 차단된다는 문장이 부정확했다.

## Security RED

- Test: `MyPageSummaryUseCaseTests.test_mixed_owned_owner_and_foreign_session_is_denied_before_cache_read`
- Request: authenticated A, `GET /api/mypage/summary/?owner_id=A&session_id=B`
- Expected: `403 object_access_denied`
- Observed before fix: `200` with foreign `session_cache`, including `session_cache.snapshot.owner_id = B`
- Exit: nonzero
- Failure: `AssertionError: 200 != 403`
- Classification: `SECURITY_RED_INDEPENDENTLY_PROVABLE`

## Security Fix

`_authorize_mypage_query` now authorizes requested owner/user scope first and independently authorizes every supplied `session_id` before `get_mycase_summary` or `read_chat_session_state` can run.

- foreign mixed session: aggregate read `0`, cache read `0`, response `403 object_access_denied`
- owner precedence remains: `owner_id > user_id > authenticated user_id`
- foreign owner failure remains first when both owner and session are foreign

## Behavior Strategy

`STRICT_BEHAVIOR_PARITY_EXCEPT_SECURITY_CORRECTION`

Intentional behavior drift:

| Scenario | Base | Fixed |
| --- | --- | --- |
| own `owner_id` + foreign `session_id` | `200` with foreign cache disclosure | `403 object_access_denied` |

All other authorized MyPage behavior remains unchanged: limit normalization, saved-state visibility, DB aggregate authority, cache hit/miss fallback, legacy `session_cache` representation, and guest rejection.

## Security Matrix

| Scenario | Result |
| --- | --- |
| own owner + own session | `200` |
| own owner + foreign session | `403 object_access_denied` |
| own legacy user + foreign session | `403 object_access_denied` |
| foreign session only | `403 object_access_denied` |
| foreign owner + own session | `403 object_access_denied` |
| foreign owner + foreign session | `403 object_access_denied` |
| own owner only | `200` |
| own session only | `200` |

## Sensitivity

`owner_session_fence_bypass` now removes the actual `session_access = _session_access(...)` call and directly executes `test_mixed_owned_owner_and_foreign_session_is_denied_before_cache_read`.

At `e0d6a819949e7a90ac090707d82489bd5dc66263`:

- baseline: `0`
- five required mutations: each nonzero `AssertionError`
- source restoration: `true`
- `working_tree_unchanged`: `true`
- stale requested Head: rejected by strict equality

## Local Verification

| Suite | Result |
| --- | --- |
| D7 focused + MyPage + guest + auth-session regression | `34 tests, OK` |
| B1–D6 application regression | `89 tests, OK` |
| B2–D7 sensitivity contracts + MyPage/OpenAPI shadow contracts | `45 passed` |
| D7 sensitivity evidence | `PASS` |
| Django / OpenAPI / frontend route / Ruff-F401 / diff | `PASS` |

Windows full Django `chatbot` suite: `539 tests`, `20 errors`.

The errors are existing local environment observations outside this D7 delta:

- `pymupdf._extra` DLL loading
- attachment classification adapter import portability

D7 focused and previous application regression suites have no failures or errors.

## Final Runtime CI

Reviewed Final Runtime Head `cc42b371aea64ec781c6815a39991835febf31e7` received all blocking CI successfully.

- `production-gate`: Run `32222672840`, `success`
- `offline-verification`: Job `95976042758`, `success`
- `compose-integration`: Job `95977361708`, `success`
- `regression-signal`: Run `32222672854`, `success`

## D7 sensitivity artifact authority

- Artifact: `9354537141`
- PR Source Head: `cc42b371aea64ec781c6815a39991835febf31e7`
- CI Runtime Checkout: `f4e64009bd317661d8d1161356c175c74d6259cf`
- baseline exit: `0`
- exact mutation set: `5`
- all mutations: `AssertionError`
- source restoration: `true`
- `working_tree_unchanged`: `true`
- artifact `head == actual_head`: `true`

PR Source Head와 CI Runtime Checkout SHA가 다른 것은 `pull_request` merge checkout에서 정상이며, runner의 strict equality가 runtime checkout authority를 검증한다.

Local Docker D1 and Compose D2 remain `NOT_EXECUTED` for this delta. Final CI Docker smoke와 Compose gate는 `PASS`이며, Docker, Compose, dependency, 또는 system configuration files는 변경하지 않았다.

## Deferred Scope

- `MYPAGE_PUBLIC_PROJECTION_HARDENING_REQUIRED`: still deferred.
- Legacy same-owner topology/cache metadata remains preserved for behavior compatibility and is not the target public projection.
- Production DB audit: `NOT_EXECUTED`.
- Phase 3 and unrelated public projection, schema, repository, Queue/Worker, Storage/Renderer, Agent/RAG work: out of scope.

## Final Security Delta Independent Review

- P0: `CLOSED`
  - own owner + foreign session은 `403 object_access_denied`이며, unauthorized `get_mycase_summary` calls `0`, `read_chat_session_state` calls `0`, foreign session data leakage `0`
- P1: `CLOSED`
  - `owner_session_fence_bypass`는 실제 session authorization을 우회하고 mixed own-owner + foreign-session regression을 직접 `AssertionError`로 검출한다.
- P2: metadata correction은 이 docs-only delta에서 보정됐으며 `P2_REMEDIATED_PENDING_DELTA_REVIEW` 상태다.
- Security correction: `PASS`
- Security chronology: `INDEPENDENTLY_PROVABLE`
- Behavior strategy: `STRICT_BEHAVIOR_PARITY_EXCEPT_SECURITY_CORRECTION`
- Intentional security drift: own owner + foreign session의 `200` foreign `session_cache` disclosure → `403 object_access_denied`
- Reviewed Final Runtime Head: `cc42b371aea64ec781c6815a39991835febf31e7`
- Final Runtime CI: `PASS`
- `MYPAGE_PUBLIC_PROJECTION_HARDENING_REQUIRED`: `DEFERRED`
- Production DB audit: `NOT_EXECUTED`

## Status

- P0: `CLOSED`
- P1: `CLOSED`
- P2: `P2_REMEDIATED_PENDING_DELTA_REVIEW`
- PR: `DRAFT`
- Merge: `NOT_PERFORMED`
