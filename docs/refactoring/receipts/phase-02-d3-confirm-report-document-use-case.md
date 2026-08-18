# Phase 2-D3 — ConfirmReportDocument Application Boundary Receipt

## Authority

- Repository: `SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team`
- Base SHA: `5ee4d3f501429268057b9628a35c5ffbfc184b45`
- Branch: `refactor/phase-02-d3-confirm-report-document-use-case`
- Behavior Head: `7833b729db5d59b7224e782bb46faf4875896f8f`
- Runtime Implementation Head: `7833b729db5d59b7224e782bb46faf4875896f8f`
- Final Reviewed Head: `c81dba79e4b6f4c18f45da0c573f3c6281259be6`
- PR: `#407`
- State: `OPEN`
- Draft: `true`
- Merge: `NOT_PERFORMED`

이 receipt는 비동작 metadata commit과 Final Reviewed Head를 구분한다. Runtime behavior authority는 `Runtime Implementation Head`이고, 독립 검토의 Final authority는 `Final Reviewed Head`다.

## Target

- Route: `POST /api/reports/<report_id>/document-confirmation/`
- Method: `POST`
- View: `report_document_confirmation`
- Application module: `app/application/reports/confirm_document.py`
- Use Case: `ConfirmReportDocument`

## Behavior Order

`authentication` → guest session validity → trusted authenticated identity / login policy → report access metadata → owner authorization → `ConfirmReportDocumentRequest` validation → existing `confirm_report_document()` transaction → `ConfirmReportDocumentResponse` / `201`.

Base와 Head 모두 authorization-before-validation이다. foreign owner + invalid body는 `403 object_access_denied`이며 metadata mutation이 없다.

## Changes

| Path | Change | Symbol | Purpose |
| --- | --- | --- | --- |
| `app/application/reports/__init__.py` | 신규 package | reports application package | Report use case namespace |
| `app/application/reports/confirm_document.py` | 신규 orchestration | `ConfirmReportDocumentCommand`, `ConfirmReportDocumentResult`, `execute_confirm_report_document` | trusted `auth_context`만 사용해 access → validation → 기존 transaction 위임 |
| `backend/chatbot/views.py` | thin adapter | `report_document_confirmation` | HTTP/auth/error/status mapping 유지, direct repository confirmation 제거 |
| `backend/chatbot/test_phase_02_report_document_confirmation_use_case.py` | characterization | `ReportDocumentConfirmationUseCaseCharacterizationTests` | owner, foreign, guest, 404, 409, 422, stale, seam, architecture 보호 |
| `scripts/refactoring/verify_phase_02_d3_test_sensitivity.py` | negative-control runner | `TARGETS`, `build_evidence` | 실제 source mutation 5종 assertion 탐지 |
| `test/test_phase_02_d3_sensitivity_runner.py` | runner contract | evidence contract tests | mutation set·assertion·restore·tree invariant 보호 |
| `.github/workflows/production-gate.yml` | blocking CI | D3 focused, sensitivity, artifact, F401 | Linux CI gate 지속 검증 |

## Public Contract

- Request: `ConfirmReportDocumentRequest`; 네 confirmation field는 모두 `true`.
- Response: `ConfirmReportDocumentResponse`, `document_confirmation.v1`.
- Success: `201`.
- Authentication: 기존 Bearer authentication 및 guest session validity policy 유지.
- Ownership: Application은 outer payload가 아닌 trusted `auth_context`에서 owner identity를 유도한다.
- Errors: `401`, `403 login_required`, `403 object_access_denied`, `404 report_not_found`, `409 appeal_gate_blocked`, `409 document_download_not_available`, `422 validation_error` 유지.
- Mutation: 기존 `Report.metadata["document_confirmation"]`만 기존 Repository transaction에서 변경.
- DB schema / migrations / Queue / Worker / Renderer / Storage / frontend: 변경 없음.

## RED

- Command: `python backend/manage.py test chatbot.test_phase_02_report_document_confirmation_use_case --verbosity 2`
- Base SHA: `5ee4d3f501429268057b9628a35c5ffbfc184b45`
- Exit Code: `1`
- Assertion: `Expected 'execute_confirm_report_document' to have been called once. Called 0 times.`
- 의미: Base View는 HTTP `201`을 반환했지만 Application seam을 호출하지 않았다. ImportError·SyntaxError·환경 오류가 아닌 adapter boundary 결함을 재현했다.

## GREEN

| Suite | Command | Result |
| --- | --- | --- |
| D3 characterization | `python backend/manage.py test chatbot.test_phase_02_report_document_confirmation_use_case --verbosity 1` | 9 tests, `OK` |
| D3 + report lifecycle + Repository | `python backend/manage.py test chatbot.test_phase_02_report_document_confirmation_use_case chatbot.test_phase_00_report_lifecycle chatbot.test_supervisor_reporting_pipeline.DocumentConfirmationRepositoryTests --verbosity 1` | 19 tests, `OK` |
| API contract | `python -m pytest -p no:cacheprovider test/test_api_route_specs.py -q` | 15 passed |
| D3 sensitivity runner contract | `python -m pytest -p no:cacheprovider test/test_phase_02_d3_sensitivity_runner.py -q` | 3 passed |
| B1/B2/B3/D1/D2 regression | `python backend/manage.py test chatbot.test_phase_02_case_workspace_use_case chatbot.test_phase_02_case_fact_confirmation_use_case chatbot.test_phase_02_case_analysis_use_case chatbot.test_phase_02_case_list_use_case chatbot.test_phase_02_case_creation_use_case --verbosity 1` | 43 tests, `OK` |

## Sensitivity

| Mutation | Defect | Result | Failure Type | Restored |
| --- | --- | --- | --- | --- |
| `view_application_bypass` | View가 Use Case를 우회하고 Repository를 직접 호출 | nonzero | `assertion` | true |
| `owner_authorization_bypass` | foreign owner authorization 제거 | nonzero | `assertion` | true |
| `typed_validation_bypass` | false/missing confirmation validation 제거 | nonzero | `assertion` | true |
| `appeal_gate_bypass` | blocked appeal confirmation 허용 | nonzero | `assertion` | true |
| `document_availability_bypass` | non-official document confirmation 허용 | nonzero | `assertion` | true |

`python scripts/refactoring/verify_phase_02_d3_test_sensitivity.py` 결과는 `status: pass`, original exit `0`, 모든 mutation assertion, `working_tree_unchanged: true`였다. B2/B3/D1/D2 기존 sensitivity도 모두 `pass`였다.

## Static / Contract

- Django: `python backend/manage.py check` → `0`.
- OpenAPI: `python scripts/generate_openapi_v1.py --check` → `0`; runtime `409 document_download_not_available`와 OpenAPI의 `appeal_gate_blocked` 중심 기술 차이는 기존 observation으로 유지.
- Frontend route: `python scripts/generate_frontend_case_routes.py --check` → `0`.
- Ruff: `ruff check --select E9,F63,F7,F82 .` 및 D3 F401 → `0`.
- Diff: `git diff --check` → `0`.

## Local Full Django Observation

`python backend/manage.py test chatbot --verbosity 1`의 Windows 독립 비교 결과는 다음과 같다.

- Base: 498 tests / 20 errors
- Head: 507 tests / 20 errors
- Exact failing test set: same
- New D3 regression: 0
- Classification: `BASELINE_ENVIRONMENT_DEBT`

- `pymupdf._extra` DLL loading — 10
- `app.services.attachment_document_classification_adapter` patch resolution — 10

Head의 추가 9 tests는 D3 characterization tests이며 통과했다. D3 focused, report lifecycle, Repository, previous Phase 2 slice regression은 모두 통과했다.

## CI

### Final CI Authority

- Final CI Authority Head: `c81dba79e4b6f4c18f45da0c573f3c6281259be6`.
- `offline-verification`: run `32124552591` / job `95672114113` / `success`, blocking.
- `compose-integration`: run `32124552591` / job `95673472025` / `success`, blocking.
- `regression-signal`: run `32124552612` / job `95672114373` / `success`.

### Historical CI Evidence

- Evidence Head: `bf9ad4db8ccb83d9be17c43a12425403728671ee`.
- `production-gate` run `32111900802` / `offline-verification` job `95632969375`: `PASS`, blocking, 5m4s.
- `production-gate` run `32111900802` / `compose-integration` job `95634214514`: `PASS`, blocking, 3m6s.
- `regression-signal` run `32111900796` / job `95632969524`: `PASS`, 2m2s.
- `offline-verification` 내부 `Phase 2 D3 report document confirmation application boundary`, `Phase 2 D3 sensitivity negative controls`, `Upload Phase 2 D3 sensitivity evidence`, `Phase 2 D3 unused import guard`: 모두 `success`.

## Deferred

- Production DB audit: `NOT_EXECUTED`.
- `DownloadReport` extraction: deferred.
- Renderer / Storage extraction: Phase 3 deferred.
- Remaining Phase 2 slices: deferred.

## Risks

- P0: 0.
- P1: 0.
- P2: Windows full-suite dependency portability debt; D3 source delta가 아닌 기존 환경 관찰.