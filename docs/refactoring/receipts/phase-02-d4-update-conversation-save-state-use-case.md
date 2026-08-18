# Phase 2-D4 — UpdateConversationSaveState Application Boundary Receipt

## Authority

- Repository: `SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team`
- Base SHA: `0dcd41bd56978d89347f74aa96e56b8017ffbdb3`
- Branch: `refactor/phase-02-d4-update-conversation-save-state-use-case`
- Behavior Head: `b64615ace29e9ecb728bb5a9b4e22af68d8ed334`
- Reviewed Runtime / PR Head before docs remediation: `467497838d086e313d3ee585a62efcee002ad841`
- Docs-only remediation: independent review 후 수행. 새 Docs Delta Head는 자기참조를 피하기 위해 Git/PR authority와 후속 Delta Review에서 기록한다.
- PR: `#408` (`OPEN`, Draft)
- Merge: `NOT_PERFORMED`

## Target

- Route: `POST /api/chat/save-state/`
- View: `update_chat_save_state`
- Application module: `app/application/chat/update_save_state.py`
- Use Case: `UpdateConversationSaveState`

## Behavior Order

Base와 Head는 다음 순서를 보존한다.

`trusted request identity` → session access metadata / ownership authorization → guest validity 및 save policy → `mark_conversation_save_state()` → 기존 multi-record propagation transaction → `write_chat_session_state()` → saved `conversation_saved` HistoryEvent → HTTP response.

`mark_conversation_save_state()`의 transaction, `ChatSession`/`ChatMessage`/`AnalysisJob`/`Report`/기존 `HistoryEvent` propagation, owner promotion, cache 구현은 변경하지 않았다. Application은 이 Repository operation을 한 번만 위임한다.

## Changes

| Path | Change | Symbol | Purpose |
| --- | --- | --- | --- |
| `app/application/chat/__init__.py` | 신규 package | chat application package | Chat use case namespace |
| `app/application/chat/update_save_state.py` | 신규 orchestration | `UpdateConversationSaveStateCommand`, `UpdateConversationSaveStateResult`, `execute_update_conversation_save_state` | trusted `auth_context`만 사용해 ownership·guest policy를 처리한 뒤 기존 Repository transaction에 위임 |
| `backend/chatbot/views.py` | thin adapter | `update_chat_save_state` | HTTP body/auth/error/status mapping 유지, direct `mark_conversation_save_state` 및 direct history call 제거 |
| `backend/chatbot/test_phase_02_conversation_save_state_use_case.py` | characterization | `ConversationSaveStateUseCaseCharacterizationTests` | seam, ownership, guest policy, unknown session, propagation, cache, history, architecture 보호 |
| `scripts/refactoring/verify_phase_02_conversation_save_state_test_sensitivity.py` | negative-control runner | `TARGETS`, `build_evidence` | 실제 source mutation 5종 assertion 탐지 |
| `test/test_phase_02_conversation_save_state_sensitivity_runner.py` | runner contract | evidence contract tests | mutation exact set·assertion·restore·tree invariant 보호 |
| `.github/workflows/production-gate.yml` | blocking CI | D4 focused, sensitivity, artifact, F401 | Linux CI의 D4 gate 지속 검증 |

## Public Contract

- Request: `ChatSaveStateRequest`; `session_id`, `conversation_save_state`와 optional `conversation_save_source`를 그대로 사용한다.
- Response: `ChatSaveStateResponse` envelope를 유지한다.
- Success: `200`.
- Unknown session: `200`, `status: "skipped"`, `reason: "session_not_found"` 유지.
- Errors: 기존 `401 guest_session_invalid`, `403 login_required`, `403 object_access_denied` 유지.
- Identity authority: client-supplied `owner_id`, `user_id`, `guest_id`, `auth_context` override는 authority가 아니며 server-derived trusted `auth_context`만 Command의 identity source가 된다.
- DB schema / migrations / Queue / Worker / Storage / Renderer / Agent / RAG / frontend / Docker / Compose / Terraform: 변경 없음.

## Behavior Matrix

| Scenario | Base | Head | Preserved |
| --- | --- | --- | --- |
| authenticated owner + `saved` | `200`, propagation, cache, `conversation_saved` | 동일 | yes |
| authenticated owner + `pending` | `200`, propagation, no saved event | 동일 | yes |
| authenticated owner + `session_only` | `200`, propagation, no saved event | 동일 | yes |
| unknown session | `200`, `skipped` | 동일 | yes |
| guest + `saved` | `403 login_required`, no mutation | 동일 | yes |
| guest + `pending` / `session_only` | `200`, allowed state transition | 동일 | yes |
| foreign authenticated owner | `403 object_access_denied`, no mutation | 동일 | yes |
| expired guest | `401 guest_session_invalid`, no mutation | 동일 | yes |
| forged identity | trusted owner remains authority | 동일 | yes |
| repeated same save-state | `200`, existing `updated` result | 동일 | yes |

## Propagation

- `ChatSession`: existing metadata state and saved-owner promotion unchanged.
- `ChatMessage`: existing session-wide save-state propagation unchanged.
- `AnalysisJob`: existing metadata and owner propagation unchanged.
- `Report`: existing metadata and owner propagation unchanged.
- `HistoryEvent`: Repository propagation remains unchanged; adapter records `conversation_saved` only for `saved`.
- Cache: existing Repository `write_chat_session_state()` call remains unchanged.

## RED

- Command: `python backend/manage.py test chatbot.test_phase_02_conversation_save_state_use_case --verbosity 1`
- Base SHA: `0dcd41bd56978d89347f74aa96e56b8017ffbdb3`
- Exit: `1`
- Assertion: `Expected 'execute_update_conversation_save_state' to have been called once. Called 0 times.`
- Meaning: Base View returned its normal response but did not invoke the new Application seam. The failure was an `AssertionError`, not an import, syntax, or environment failure.

## GREEN

| Suite | Command | Result |
| --- | --- | --- |
| D4 characterization | `python backend/manage.py test chatbot.test_phase_02_conversation_save_state_use_case --verbosity 1` | 9 tests, `OK` |
| D4 + existing chat API contract | `python backend/manage.py test chatbot.test_phase_02_conversation_save_state_use_case chatbot.test_chat_session_api_contract.ChatSessionApiContractTests --verbosity 1` | 16 tests, `OK` |
| D4 sensitivity runner contract | `python -m pytest -p no:cacheprovider test/test_phase_02_conversation_save_state_sensitivity_runner.py -q` | 3 passed |
| API/OpenAPI contract | `python -m pytest -p no:cacheprovider test/test_api_route_specs.py test/test_openapi_v1_generation.py -q` | 27 passed |
| Previous Phase 2 regression | `python backend/manage.py test chatbot.test_phase_02_case_workspace_use_case chatbot.test_phase_02_case_fact_confirmation_use_case chatbot.test_phase_02_case_analysis_use_case chatbot.test_phase_02_case_list_use_case chatbot.test_phase_02_case_creation_use_case chatbot.test_phase_02_report_document_confirmation_use_case --verbosity 1` | 52 tests, `OK` |

## Sensitivity

| Mutation | Defect | Result | Failure Type | Restored |
| --- | --- | --- | --- | --- |
| `view_application_bypass` | View가 Use Case를 우회하고 Repository를 직접 호출 | nonzero | `assertion` | true |
| `session_authorization_bypass` | foreign owner access gate 제거 | nonzero | `assertion` | true |
| `guest_saved_login_bypass` | guest `saved` 허용 | nonzero | `assertion` | true |
| `state_propagation_bypass` | 기존 save-state Repository propagation 우회 | nonzero | `assertion` | true |
| `history_event_bypass` | `conversation_saved` event 생략 | nonzero | `assertion` | true |

`python scripts/refactoring/verify_phase_02_conversation_save_state_test_sensitivity.py`는 original exit `0`, 모든 mutation assertion, `working_tree_unchanged: true`, `status: pass`를 기록했다. B2/B3/D1/D2/D3 sensitivity도 모두 `pass`였다.

## Static / Contract

- Django: `python backend/manage.py check` → `0`.
- OpenAPI: `python scripts/generate_openapi_v1.py --check` → `0`.
- Frontend route: `python scripts/generate_frontend_case_routes.py --check` → `0`.
- Ruff: `ruff check --select E9,F63,F7,F82 .` 및 Phase 2 F401 targets → `0`.
- Diff: `git diff --check` → `0`.

## Environment and Existing Debt

- Windows ownership E2E: 이번 docs-only remediation에서는 terminal sandbox helper가 새 process를 initialization 단계에서 거절해 독립 재실행하지 못했다. 기존 `pymupdf._extra` DLL loading은 portability/environment observation으로만 유지하며 D4 PASS evidence로 사용하지 않는다.
- Linux blocking CI: 다음 ownership E2E 3건을 실제 실행하여 PASS했다. Classification: `VERIFIED_IN_LINUX_BLOCKING_CI`.
  - `test_matching_guest_login_can_promote_all_resources_to_one_case`
  - `test_other_user_cannot_read_mutate_or_claim_promoted_resources`
  - `test_attacker_cannot_access_or_mutate_any_owner_bound_resource`
- Existing Phase 0 sensitivity: clean behavior head에서 process-only Git safe-directory context로 실행했지만 `ocr_law` original test가 `app.services.attachment_document_classification_adapter` patch resolution `AttributeError`로 실패했다. 이 source 상태는 Base에도 존재하며 D4는 이를 변경하지 않았다. 분류: `PRE_EXISTING_PHASE_00_SENSITIVITY_DEBT`.
- New D4 production regression: Linux blocking CI 기준 `0`.

## CI

- D4 blocking workflow steps were added: focused boundary, D4 sensitivity negative controls, evidence artifact, F401 guard.
- Reviewed Runtime / PR Head CI authority: `467497838d086e313d3ee585a62efcee002ad841`.
- `production-gate`: run `32135419258`, `offline-verification` job `95705484668`, `success`, blocking.
- `production-gate`: run `32135419258`, `compose-integration` job `95706845315`, `success`, blocking.
- `regression-signal`: run `32135419271`, job `95705484301`, `success`.
- D4 boundary: `19 tests, OK`.
- Full Django chatbot regression: `516 tests, OK`.
- D4 sensitivity: `5/5 assertion detection`.
- D4 evidence artifact: `9323853216`.
- Linux CI passed the D4 focused boundary, D4 sensitivity, Phase 0 sensitivity, frontend, Terraform, and Docker/Compose gates.

## Deferred

- Production DB audit: `NOT_EXECUTED`.
- Phase 3 queue/storage/repository physical split: deferred.
- Remaining Phase 2 query slices: deferred.

## Risks

- P0: 0.
- P1: 0.
- P2: Receipt/PR metadata remediation performed; `REMEDIATED_PENDING_DELTA_REVIEW`.
- Windows `pymupdf._extra` portability와 Phase 0 sensitivity patch-resolution debt는 D4 source delta가 도입하지 않은 기존 환경 관찰이다.
