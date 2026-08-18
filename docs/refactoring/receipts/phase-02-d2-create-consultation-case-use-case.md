# Phase 2-D2 — CreateConsultationCase Application Boundary Receipt

## Authority

- Repository: `SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team`
- Branch: `refactor/phase-02-d2-create-consultation-case-use-case`
- Base SHA: `9e8367b4cdcd41d7db3ab815d613a77caed7fbce`
- Behavior commit: `9a7db066c0fd6d5b7360fe4ca06c39ae71d85e2c`
- Implementation Head: `664c1a433b40ae0564548bf45c8a146cbf85ce84`
- Final Head (runtime implementation): `664c1a433b40ae0564548bf45c8a146cbf85ce84`
- PR: `#406` — Draft

이 receipt는 비동작 metadata commit으로 별도 기록한다. 따라서 self-referential SHA 대신 실제 runtime implementation의 Final Head를 기록한다.

## Scope

- Target route: `POST /api/cases/`
- Method: `POST`
- View: `consultation_cases`
- Application module: `app/application/cases/create_case.py`
- Use Case: `CreateConsultationCase`
- 제외: `GET /api/cases/` D1 흐름과 `chatbot.case_repository.create_case`의 persistence/business semantics.

## Changes

| Path | Change | Symbol | Reason | Test |
| --- | --- | --- | --- | --- |
| `app/application/cases/create_case.py` | 신규 Application orchestration | `CreateConsultationCaseCommand`, `CreateConsultationCaseResult`, `execute_create_consultation_case` | trusted identity로 legacy boundary 호출 | `CaseCreationUseCaseCharacterizationTests` |
| `backend/chatbot/views.py` | POST adapter extraction | `consultation_cases` | typed validation 뒤 Application seam 호출 | HTTP characterization 및 기존 Case regression |
| `backend/chatbot/test_phase_02_case_creation_use_case.py` | 신규 characterization | 4 D2 tests | identity, promotion, fences, AST boundary | focused suite 4 tests |
| `scripts/refactoring/verify_phase_02_d2_test_sensitivity.py` | 신규 negative-control runner | `TARGETS`, `build_evidence` | D2 계약 mutation 4종 증명 | runner 및 actual mutation |
| `test/test_phase_02_d2_sensitivity_runner.py` | 신규 runner contract | D2 evidence schema tests | missing/success/restore/failure-kind 차단 | pytest 3 tests |
| `scripts/refactoring/verify_phase_02_d1_test_sensitivity.py` | D1 anchor 호환성 갱신 | `temporarily_bypass_application_in_view` | POST direct `create_case` 제거 뒤 D1 mutation이 계속 실제로 실행되도록 유지 | D1 runner 및 CI gate |
| `.github/workflows/production-gate.yml` | blocking gate 추가 | D2 focused, sensitivity, artifact, F401 | Linux CI에서 D2 boundary 지속 검증 | `offline-verification` |

## Contract

- Request unchanged: `CreateConsultationCaseRequest`의 `session_id`, `title`, `case_type`, `consultation_state`, `location`.
- Response unchanged: `CreateConsultationCaseResponse`, `consultation_case.v2`.
- Success unchanged: `201`.
- Authentication unchanged: View의 `_payload_with_request_identity`, login/authentication fence 유지.
- Ownership unchanged: `auth_context`에서 유래한 identity만 Application이 사용하며 client-supplied identity는 persisted/public authority가 아니다.
- Typed validation unchanged: persistence 이전 `422 validation_error` 유지.
- DB unchanged: schema/model/migration 없음.
- Queue unchanged: `AnalysisJob`, `AgentWorkItem`, worker semantics 변경 없음.
- Frontend unchanged.

## Case promotion preservation

- matching guest: 기존 guest → authenticated promotion을 `create_case`에 그대로 위임.
- foreign guest: `CaseOwnerMismatch` 및 mutation 없음.
- active worker fence: `CaseAnalysisInProgress` 및 mutation 없음.
- reservation fence: 기존 `create_case` behavior 유지.
- existing case: session의 기존 Case 재사용 behavior 유지.
- `AnalysisJob` relink: owner/case relink 유지.
- `Report` relink: owner/case relink 유지.
- `UploadedFile` relink: owner/case relink 및 retention extension 유지.
- `CaseStatus`: 기존 repository 결정 유지.

## RED

- Command: `python backend/manage.py test chatbot.test_phase_02_case_creation_use_case.CaseCreationUseCaseCharacterizationTests.test_http_post_delegates_to_application_with_trusted_identity_and_preserves_case_response --verbosity 1`
- Exit Code: `1`
- Expected failure: View가 Application seam을 호출하지 않음.
- Actual failure: `AssertionError: Expected 'execute_create_consultation_case' to have been called once. Called 0 times.`
- Reason: pre-D2 `consultation_cases` POST branch가 `chatbot.case_repository.create_case`를 직접 호출했다. dependency/environment failure가 아니었다.

## GREEN

| Suite | Command | Exit Code | Result |
| --- | --- | --- | --- |
| D2 characterization | `python backend/manage.py test chatbot.test_phase_02_case_creation_use_case --verbosity 1` | `0` | 4 tests, `OK` |
| D2 focused + Case promotion regression | `python backend/manage.py test chatbot.test_phase_02_case_creation_use_case chatbot.test_consultation_v2.ConsultationCaseApiTests.test_authenticated_user_creates_lists_and_reads_case_workspace chatbot.test_consultation_v2.ConsultationCaseApiTests.test_case_creation_requires_authenticated_user chatbot.test_consultation_v2.ConsultationCaseApiTests.test_case_creation_validates_typed_request_before_repository chatbot.test_consultation_v2.ConsultationPersistenceSafetyTests.test_guest_case_promotion_requires_matching_guest_identity chatbot.test_consultation_v2.ConsultationPersistenceSafetyTests.test_guest_case_promotion_rejects_active_unbound_worker_jobs chatbot.test_consultation_v2.ConsultationPersistenceSafetyTests.test_guest_case_promotion_succeeds_after_worker_becomes_terminal chatbot.test_consultation_v2.ConsultationPersistenceSafetyTests.test_case_creation_rejects_an_unpromoted_analysis_reservation chatbot.test_consultation_v2.ConsultationPersistenceSafetyTests.test_guest_document_is_relinked_and_extended_when_session_becomes_a_case chatbot.test_consultation_v2.ConsultationPersistenceSafetyTests.test_guest_case_promotion_transfers_job_and_report_ownership --verbosity 1` | `0` | 13 tests, `OK` |
| B1/B2/B3/D1 regression | `python backend/manage.py test chatbot.test_phase_02_case_workspace_use_case chatbot.test_phase_02_case_fact_confirmation_use_case chatbot.test_phase_02_case_analysis_use_case chatbot.test_phase_02_case_list_use_case --verbosity 1` | `0` | 39 tests, `OK` |
| D1/D2 sensitivity runner contracts | `python -m pytest -p no:cacheprovider test/test_phase_02_d1_sensitivity_runner.py test/test_phase_02_d2_sensitivity_runner.py -q` | `0` | 6 passed |
| Full local Django | `python backend/manage.py test chatbot --verbosity 1` | `1` | 498 tests, existing 20 environment errors; D2 regression 0 |

## Sensitivity

| Mutation | Result | Failure Type | Source Restored |
| --- | --- | --- | --- |
| D2 `trusted_identity_bypass` | nonzero | `assertion` | true |
| D2 `typed_validation_bypass` | nonzero | `assertion` | true |
| D2 `promotion_fence_bypass` | nonzero | `assertion` | true |
| D2 `view_application_bypass` | nonzero | `assertion` | true |
| D1 `identity_authority_bypass` | nonzero | `assertion` | true |
| D1 `owner_filter_bypass` | nonzero | `assertion` | true |
| D1 `view_application_bypass` | nonzero | `assertion` | true |

Commands: `python scripts/refactoring/verify_phase_02_d1_test_sensitivity.py` 및 `python scripts/refactoring/verify_phase_02_d2_test_sensitivity.py`. 두 evidence 모두 `status: pass`, `working_tree_unchanged: true`였다.

## Static / contract

- Django: `python backend/manage.py check` → `0`, no issues.
- OpenAPI: `python scripts/generate_openapi_v1.py --check` → `0`, current.
- frontend route: `python scripts/generate_frontend_case_routes.py --check` → `0`, current.
- Ruff/F401: `ruff check --select E9,F63,F7,F82 .`, `ruff check --select F401 app/application/cases/confirm_facts.py app/application/cases/start_analysis.py app/application/cases/create_case.py`, 그리고 신규 runner/test `ruff check` → 모두 `0`.
- Diff: `git diff --check` → `0`.

## CI

| Workflow / job | Run ID | Implementation Head | Result | Blocking |
| --- | --- | --- | --- | --- |
| `production-gate` / `offline-verification` | `32105215561` / `95613158015` | `664c1a433b40ae0564548bf45c8a146cbf85ce84` | PASS, 4m54s | yes |
| `production-gate` / `compose-integration` | `32105215561` / `95614128259` | `664c1a433b40ae0564548bf45c8a146cbf85ce84` | PASS, 3m03s | yes |
| `regression-signal` | `32105215489` / `95613157774` | `664c1a433b40ae0564548bf45c8a146cbf85ce84` | PASS, 2m17s | existing policy signal; D2-specific blocking gate 아님 |

이전 `9a7db066c0fd6d5b7360fe4ca06c39ae71d85e2c` run `32104759534`는 D1 runner의 stale import anchor 때문에 실패했다. `664c1a433b40ae0564548bf45c8a146cbf85ce84`의 최소 anchor 보완 뒤 최신 run은 D1/D2 sensitivity와 전체 production/Compose gate를 통과했다.

## Environment observations

- Baseline debt: Windows local full suite의 `pymupdf._extra` DLL loading 및 attachment classification adapter import 계열 20 errors.
- Baseline evidence: D1 receipt의 Base safety worktree `487 tests, 20 errors`와 feature worktree `494 tests, 20 errors`의 동일한 failing test set, `BASELINE_ENVIRONMENT_DEBT`.
- New regression: 0. D2의 focused, promotion, B1/B2/B3/D1, Linux CI gates는 PASS.

## Deferred

- Production DB audit: `NOT_EXECUTED`.
- Repository physical split: deferred to Phase 3.
- Queue/Worker abstraction: deferred.
- Storage abstraction: deferred.

## Risks

- P0: 0.
- P1: 0.
- P2: Windows full-suite dependency portability debt; D2 source delta가 아니며 독립 검토에서 계속 관찰한다.
