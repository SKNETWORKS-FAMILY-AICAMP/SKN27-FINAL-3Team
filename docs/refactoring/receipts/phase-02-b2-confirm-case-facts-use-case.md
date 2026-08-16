# Phase 2-B2 ConfirmCaseFacts Application Command Receipt

## Scope and base

- Repository: `SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team`
- Base SHA: `6f597b7e6ca21edadefe4f1c753d309d610129e7`
- Branch: `refactor/phase-02-b2-confirm-case-facts-use-case`
- Scope: `POST /api/cases/<case_id>/facts/confirm/` only
- Production DB audit: `NOT_EXECUTED`
- P2-B3 `StartCaseAnalysis`: deferred and out of scope.

## Call graph

Before:

`consultation_case_fact_confirmation` → authorization → validation → `confirm_case_facts` → HTTP response

After:

`consultation_case_fact_confirmation` → `execute_confirm_case_facts` → authorization → validation → `confirm_case_facts` → HTTP response

The View remains the HTTP adapter. `app.application.cases.confirm_facts` owns application orchestration and has no Django HTTP, Explicit Mock, direct ORM, or `transaction.atomic` dependency.

## Preserved contracts

- Authorization remains before request validation. A foreign caller with an invalid payload receives `403 object_access_denied` without validation details.
- `chatbot.case_repository.confirm_case_facts` is unchanged. It remains the owner of `transaction.atomic`, `select_for_update`, Case lookup, ownership check, request fingerprinting, idempotency replay, `ConfirmedFactVersion` creation, and Case mutation.
- Exact replay retains the same fact version and does not erase manually set active-analysis metadata.
- A changed payload creates the next fact version and preserves the existing `active_analysis_job_id` reset contract.
- Route, method, HTTP status, response payload, headers, models, migrations, queue, worker, frontend runtime, and Explicit Mock runtime are unchanged.
- P2-B1 `consultation_case_workspace` and the existing analysis-start path are unchanged.

## Application interface

`app.application.cases.confirm_facts` provides:

- `ConfirmCaseFactsCommand`
- `ConfirmCaseFactsResult`
- `CaseFactConfirmationAccessDenied`
- `execute_confirm_case_facts`

Command는 기존 Case fallback을 포함해 access metadata를 해석하고, `identity_payload`를 authorization한 뒤 `access_subject_from_payload(identity_payload)["subject"]`에서만 `owner_id`를 도출한다. 이어서 `ConfirmCaseFactsRequest`를 validation하고 검증된 Python payload를 기존 repository command에 위임한다. `ValidationError`를 import하거나 처리하지 않으며, 기존 HTTP `422` mapping은 View가 담당한다. 변경하지 않은 repository ownership 재확인은 defense-in-depth로 유지한다.

## Characterization and sensitivity

- `chatbot.test_phase_02_case_fact_confirmation_use_case`: command field exact set, client owner injection, runtime authorization-bypass repository fence를 포함한 11 tests, `OK`.
- Existing `test_fact_confirmation_precedes_real_worker_queue` and `chatbot.test_phase_02_case_workspace_use_case`: 7 tests, `OK`.
- `scripts/refactoring/verify_phase_02_b2_test_sensitivity.py`는 tracked source를 바꾸지 않고 original focused B2 suite와 runtime-only child-process mutation 두 건을 실행한다.
- `authorization_bypass`는 foreign invalid-payload assertion을 실패시키며, `validation_bypass`는 owner invalid payload가 repository에 도달하게 만들어 `422` assertion을 실패시킨다.
- evidence contract는 `phase_02_b2_sensitivity.v1`이며, mutation exit code와 `AssertionError` failure kind는 하드코딩하지 않고 관측한다. 이는 Phase 0 sensitivity artifact와 구분된다.
- runner는 실행 전후 Git status를 비교하고 매 실행마다 evidence를 덮어쓰며, control이 비결정적이면 failure status를 기록한다. CI에서는 `PHASE_02_B2_SENSITIVITY_HEAD`로 PR Head를 명시 전달해 merge ref가 아닌 reviewed Head를 기록한다.

## Local verification

- Phase 1 Python gate: 27 passed.
- Phase 1 Django gate: 35 tests, `OK`.
- 현재 Windows full Django 관찰: Base와 reviewed Head는 모두 동일한 `attachment_document_classification_adapter` fixture-resolution error count를 보인다. P2-B2 변경으로 도입된 regression은 0이다.
- 별도 historical/local 관찰: 일부 collection 또는 focused run에서 `pymupdf._extra` DLL loading이 보고됐다. 이를 현재 Windows full-Django failure의 유일한 원인으로 단정하지 않는다.
- `test/test_phase_01_collection_baseline_contract.py`: 6 passed. The Windows collection verifier separately reports the same PyMuPDF import environment issue and no B2 source regression.
- `python backend/manage.py check`, OpenAPI check, frontend route check, and `ruff check --select E9,F63,F7,F82 .`: passed.
- `node --test app/web/*.test.js`: 155 passed.
- `npm --prefix app/web run build`: passed.

## Docker D1

- `docker build -t skn27-phase-02-b2-p2-delta-local .`: passed.
- CI-equivalent `chat_orchestration_service` and `runtime_health` import: passed.
- Container Django check: passed.
- production runtime settings의 container `ConfirmCaseFacts` import: 통과 (`phase-02-b2 p2 delta import ok`). `owner_id`가 없는 `ConfirmCaseFactsCommand.dataclass_fields`, `ROOT_URLCONF=config.urls`, Explicit Mock disabled를 함께 확인했다.

## Compose D2

`scripts/refactoring/run_phase_00_compose_gate.sh`는 Bash command substitution을 위해 Windows CRLF stdout을 정규화하는 일회성 Git Bash `python3` shim 및 `COMPOSE_PROJECT_NAME=skn27_phase02_b2_p2_delta_local`로 실행했다. Repository script와 system/user PATH는 변경하지 않았다.

- `gate-summary.json`: `status: pass`; backend, database, cache, Neo4j, ClamAV, agent worker, and file-scan worker ready/consumed.
- File scan: `status: pass`, `scan_status: clean`, `retry_count: 0`. fresh gate artifact는 별도 `local://attachment-staging/...` text field를 노출하지 않는다.
- `mock://` evidence: 0.
- `failed-step.txt`: absent.
- `last-step.txt`: `compose-final`.
- Latest cleanup marker: `cleanup_success`.
- `skn27_phase02_b2_local` container, volume, and network residue: 0.

## CI and review

- `.github/workflows/production-gate.yml`는 blocking `Phase 2 B2 case fact confirmation application boundary` step을 유지하고, `continue-on-error` 또는 `|| true` 없이 blocking `Phase 2 B2 sensitivity negative controls`, `phase-02-b2-sensitivity-evidence`, P2-B2 `F401` guard를 추가한다.
- `production-gate`는 blocking이고 `regression-signal`은 non-blocking이다.
- 이전 독립 검토 결과는 `PASS_WITH_CONDITIONS`, `ALLOWED_AFTER_P2_FIX`, `PHASE_2_B2_NEEDS_DELTA_FIX`이다.
- The Draft PR CI result is pending at this receipt commit and must pass before review readiness is declared.
- Draft PR must remain unmerged and must not be converted to Ready by this task.
