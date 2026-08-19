# Phase 2-D7 GetMyPageSummary Application Boundary

## Authority

- Repository: `SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team`
- Base: `c2f1b721640e2d97b84d27ddb4d1515b59860421`
- Branch: `refactor/phase-02-d7-get-mypage-summary-use-case`
- RED Head: `46bdd78a9170f3f44fe37ab6206111fd27106908`
- GREEN/Behavior Head: `d7959b32cdbd402acba005aeb4a21d5eb0bcbaac`
- Verification-gate Head: `05fe8296c206e87ec3348a5c19db123521a34b2e`
- PR: `PENDING`
- State: `NOT_CREATED`
- Draft: `true` when created
- Merge: `NOT_PERFORMED`

이 Receipt는 source와 verification을 완료한 `05fe8296c206e87ec3348a5c19db123521a34b2e`를 기록한다. 이어지는 docs-only Receipt metadata commit은 self-reference 하지 않으며, CI는 그 Final Head에서 다시 실행한다.

## Target and Boundary

- Route: `GET /api/mypage/summary/`
- View: `mypage_summary`
- Application: `app/application/mypage/get_summary.py`
- Use Case: `GetMyPageSummary`
- Entrypoint: `execute_get_mypage_summary`

`mypage_summary`는 HTTP query extraction, framework identity 수신, `GetMyPageSummaryQuery` 생성, Application 호출, `MyPageSummaryAccessDenied`의 기존 HTTP error mapping, JSON serialization만 수행한다.

`execute_get_mypage_summary`는 trusted identity 해석, `owner_id > user_id > authenticated user_id` resolution, owner/session authorization, positive `limit` normalization, 기존 `get_mycase_summary` DB aggregate 호출, existing saved-state visibility, optional `read_chat_session_state` hit/miss fallback, `GetMyPageSummaryResult` construction을 담당한다.

Application module은 Django HTTP, direct ORM model access, `transaction.atomic`, direct Redis client, Queue/Worker, Storage/Renderer, Agent/RAG, frontend, explicit mock runtime에 의존하지 않는다. DB aggregate authority와 session cache의 ephemeral progress projection authority는 변경하지 않았다.

## RED Chronology

- RED commit: `test: characterize mypage summary application boundary`
- RED command: `python backend/manage.py test chatbot.test_phase_02_mypage_summary_use_case --verbosity 1`
- RED exit: nonzero
- RED failure: `AssertionError` — `execute_get_mypage_summary` called `0` times
- GREEN commit: `refactor: extract get mypage summary use case`
- RED ancestor of GREEN: `YES`
- Classification: `INDEPENDENTLY_PROVABLE`

## Strict Behavior Parity

Behavior strategy: `STRICT_BEHAVIOR_PARITY`.

Base response characterization covered no `session_id`, cache hit, and cache miss/DB fallback. The extraction preserves the Base key/type surface, including existing `storage.tables`, `progress_cache.backend`, cache-key representation, and raw `read_chat_session_state`-based `session_cache` fields. No Base-absent response key is permitted; the `response_surface_expansion_bypass` negative control proves this with an injected `internal_debug` field.

Focused runtime assertions confirm that the summary does not contain access/refresh/bearer token, credential, password, secret, API key, raw OCR, or private reasoning values. Foreign owner/session data remains denied.

## Deferred Public Projection Hardening

Status: `MYPAGE_PUBLIC_PROJECTION_HARDENING_REQUIRED`.

Current `LEGACY_PUBLIC_SURFACE` includes topology/table metadata, cache backend metadata, cache-key-related metadata, and raw session-cache representation. These are preserved for strict behavior parity and are not endorsed as the target public projection.

They are deferred because a change requires coordinated public DTO redesign, regression migration, OpenAPI review/update, frontend compatibility validation, and an explicit security/privacy contract decision. Recommended future scope: `MyPagePublicProjectionHardening` under `PUBLIC_PROJECTION_CONTRACT_REDESIGN`.

## Contract Matrix

| Scenario | Result |
| --- | --- |
| Authenticated owner | own summary preserved |
| `owner_id` / `user_id` | `owner_id` precedence preserved |
| Foreign owner or legacy user | `403 object_access_denied` |
| Own session | allowed |
| Foreign session | `403 object_access_denied` |
| Missing, invalid, zero, negative `limit` | default `10` |
| `pending` / `session_only` | not promoted |
| Saved case/report | preserved |
| Cache hit | existing `session_cache` hit surface preserved |
| Cache miss | existing DB-backed `miss_fallback` surface preserved |
| Guest and anonymous | `401 auth_required` |

## Sensitivity

`python scripts/refactoring/verify_phase_02_d7_mypage_summary_test_sensitivity.py` at `05fe8296c206e87ec3348a5c19db123521a34b2e` produced baseline `0`; all required mutations returned nonzero `AssertionError`; source restore and `working_tree_unchanged` were `true`.

| Mutation | Direct detection |
| --- | --- |
| `view_application_bypass` | View seam assertion |
| `owner_session_fence_bypass` | foreign owner `403` assertion |
| `saved_state_fence_bypass` | pending/session-only visibility assertion |
| `cache_fallback_bypass` | `miss_fallback` assertion |
| `response_surface_expansion_bypass` | exact Base response-surface assertion |

The runner contract also rejects a missing mutation, unexpected mutation success, non-assertion failure, dirty restoration, and stale evidence head.

## Local Verification

| Suite | Command | Result |
| --- | --- | --- |
| D7 focused + MyPage contract + guest boundary | `python backend/manage.py test chatbot.test_phase_02_mypage_summary_use_case chatbot.test_mypage_api_contract chatbot.test_guest_credential_boundary --verbosity 1` | `25 tests, OK` |
| D7 sensitivity and shadow contracts | `python -m pytest -p no:cacheprovider test/test_phase_02_d7_sensitivity_runner.py test/test_mypage_api_contract.py test/test_api_route_specs.py -q` | `20 passed` |
| B1–D6 application regression | `python backend/manage.py test chatbot.test_phase_02_case_workspace_use_case chatbot.test_phase_02_case_fact_confirmation_use_case chatbot.test_phase_02_case_analysis_use_case chatbot.test_phase_02_case_list_use_case chatbot.test_phase_02_case_creation_use_case chatbot.test_phase_02_report_document_confirmation_use_case chatbot.test_phase_02_conversation_save_state_use_case chatbot.test_phase_02_report_read_queries_use_case chatbot.test_phase_02_history_list_events_use_case chatbot.test_report_api_contract chatbot.test_history_api_contract --verbosity 1` | `89 tests, OK` |
| B2–D7 sensitivity runner contracts + MyPage/OpenAPI shadow contracts | `python -m pytest -p no:cacheprovider test/test_phase_02_b2_sensitivity_runner.py test/test_phase_02_b3_sensitivity_runner.py test/test_phase_02_d1_sensitivity_runner.py test/test_phase_02_d2_sensitivity_runner.py test/test_phase_02_d3_sensitivity_runner.py test/test_phase_02_conversation_save_state_sensitivity_runner.py test/test_phase_02_d5_sensitivity_runner.py test/test_phase_02_d6_sensitivity_runner.py test/test_phase_02_d7_sensitivity_runner.py test/test_mypage_api_contract.py test/test_api_route_specs.py -q` | `44 passed` |
| Django/OpenAPI/frontend/Ruff | `python backend/manage.py check`; `python scripts/generate_openapi_v1.py --check`; `python scripts/generate_frontend_case_routes.py --check`; `ruff check --select E9,F63,F7,F82 .`; `ruff check --select F401 app/application/mypage/get_summary.py` | `PASS` |
| Diff | `git diff --check` | `PASS` |

Windows full Django `chatbot` suite: `537 tests`, `20 errors`. The errors are pre-existing environment observations outside D7 source delta: `pymupdf._extra` DLL loading and attachment classification/import portability. The D7 focused and previous application regression suites have `0` failures/errors.

## Docker and CI

- Local Docker D1 / Compose D2: `NOT_EXECUTED`
- Reason: Docker Desktop Linux engine was unavailable; `docker version` could not connect to `//./pipe/dockerDesktopLinuxEngine`, and no Docker Desktop process/service was present.
- Source, Dockerfile, Compose, dependencies, and system configuration were not changed.
- CI: `PENDING` after Draft PR creation. `production-gate` contains blocking D7 boundary, sensitivity negative control, artifact upload, and F401 guard stages.

## Deferred and Risks

- Production DB audit: `NOT_EXECUTED`
- Remaining Phase 2 and Phase 3 structural work: deferred
- P0: `0`
- P1: `0`
- P2: existing Windows dependency/portability observations; `MYPAGE_PUBLIC_PROJECTION_HARDENING_REQUIRED`