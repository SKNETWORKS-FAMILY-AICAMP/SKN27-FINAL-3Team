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

이 Receipt는 security fix와 sensitivity verification을 완료한 `e0d6a819949e7a90ac090707d82489bd5dc66263`를 기록한다. 이어지는 docs-only Receipt metadata commit은 자기 자신의 Git SHA를 본문에 기록하지 않는다. push 후 PR의 Final Head와 새 CI는 PR metadata에서 확인한다.

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

## CI

The pre-security-fix CI for `bf0736acbb91c48dcf06bcb8af7de3ae80114fc9` passed:

- `regression-signal`
- `offline-verification`
- `compose-integration`
- strict D7 artifact SHA evidence

This pre-fix CI is not security-delta authority. A new Final Head must receive new blocking CI after push.

Local Docker D1 and Compose D2 remain `NOT_EXECUTED` for this delta; no Docker, Compose, dependency, or system configuration files were changed.

## Deferred Scope

- `MYPAGE_PUBLIC_PROJECTION_HARDENING_REQUIRED`: still deferred.
- Legacy same-owner topology/cache metadata remains preserved for behavior compatibility and is not the target public projection.
- Production DB audit: `NOT_EXECUTED`.
- Phase 3 and unrelated public projection, schema, repository, Queue/Worker, Storage/Renderer, Agent/RAG work: out of scope.

## Status

- P0: `REMEDIATED_PENDING_INDEPENDENT_REVIEW`
- P1: `REMEDIATED_PENDING_INDEPENDENT_REVIEW`
- P2: `UPDATED_PENDING_INDEPENDENT_REVIEW`
- PR: `DRAFT`
- Merge: `NOT_PERFORMED`
