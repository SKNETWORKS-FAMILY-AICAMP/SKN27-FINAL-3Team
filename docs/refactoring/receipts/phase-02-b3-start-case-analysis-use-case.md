# Phase 2-B3 StartCaseAnalysis application command receipt

## 범위와 기준점

- Base SHA: `6c7688a17241b2e396420faaa2e00abeaa300e78`
- 작업 범위: Phase 2-B3만 포함한다.
- 대상 route: `POST /api/cases/<case_id>/analysis/jobs/`
- 대상 view: `consultation_case_analysis_jobs`
- Application Command: `StartCaseAnalysis`
- 변경하지 않은 구현: `backend/chatbot/case_repository.py::start_case_analysis`, `enqueue_analysis_job_work()`, `backend/chatbot/repositories.py`, model, migration, worker, queue payload, frontend runtime, Docker/Compose source.

## 호출 그래프

### 이전

`consultation_case_analysis_jobs`가 HTTP body/identity 처리 뒤 `get_case_access_metadata`, `authorize_resource_access`, `access_subject_from_payload`, `StartCaseAnalysisRequest.model_validate`, `start_case_analysis`를 직접 호출했다.

### 이후

`consultation_case_analysis_jobs`는 HTTP adapter로서 body/identity/login fence와 예외의 HTTP 직렬화만 유지한다.

`StartCaseAnalysisCommand` → `execute_start_case_analysis` → `get_case_access_metadata` → `authorize_resource_access` → `access_subject_from_payload` → `StartCaseAnalysisRequest.model_validate` → `start_case_analysis`

## 책임과 보존 계약

- trusted identity authority는 `identity_payload`와 `access_subject_from_payload` 단일 흐름이다. client-supplied owner 값은 사용하지 않는다.
- authorization은 `StartCaseAnalysisRequest.model_validate`보다 먼저 수행된다. foreign invalid 요청은 `object_access_denied`와 HTTP 403을 유지한다.
- owner invalid 요청은 기존 HTTP 422 validation 계약을 유지한다.
- `backend/chatbot/case_repository.py::start_case_analysis`의 `transaction.atomic()` 및 Case `select_for_update()`는 변경하지 않았다.
- confirmed facts와 readiness gate는 그대로 유지하며 `confirmed_facts_required`, `fact_readiness_not_met`의 HTTP 409 계약과 details를 보존한다.
- reusable Job 조건과 재사용 status 목록은 변경하지 않았다. 동일 FactVersion 재요청은 동일 Job/WorkItem을 반환하고, failed Job은 재사용하지 않는다.
- FactVersion별 idempotency를 유지한다. 빈 `fact_version_id`는 최신 confirmed FactVersion을 선택하고, 새 FactVersion은 새 Job/WorkItem을 만든다.
- Queue payload privacy를 보존한다. `server_execution_context.context.user_facts`와 `server_execution_context.context.case_evidence`는 유지하고 public `execution_payload`에는 private facts/evidence, raw object-storage URI, `mock://`를 노출하지 않는다.
- enqueue 이후 예외를 유발한 rollback 특성화는 Job/WorkItem, Case status, active IDs가 outer transaction으로 복구됨을 확인한다.

## API non-change matrix

| 항목 | 검증 결과 |
| --- | --- |
| route/method | `POST /api/cases/<case_id>/analysis/jobs/` 유지 |
| success | HTTP 202, `case_analysis_job.v2`, queued Job/WorkItem 유지 |
| plan nodes | `text_ml_case_search`, `law_ground_search`, `objection_report_generation` 순서 유지 |
| foreign invalid | HTTP 403, `object_access_denied`, Queue row 0 |
| owner invalid | HTTP 422, validation contract, Queue row 0 |
| missing/high-risk/no-session | 기존 repository status/error contract, Queue row 0 |

## 특성화와 sensitivity

- `backend/chatbot/test_phase_02_case_analysis_use_case.py`: 15 tests 통과.
- B3/B2/B1 focused regression: 33 tests 통과.
- `test/test_phase_02_b3_sensitivity_runner.py`: 3 passed.
- `scripts/refactoring/verify_phase_02_b3_test_sensitivity.py`: 원본 suite exit 0, `authorization_bypass`, `validation_bypass`, `reusable_job_bypass`는 모두 nonzero `assertion`, working tree unchanged를 확인했다.
- CI에는 `Phase 2 B3 case analysis application boundary`, `Phase 2 B3 sensitivity negative controls`, `phase-02-b3-sensitivity-evidence` artifact를 blocking으로 추가했다.

## 로컬 검증

- Phase 1 pytest: 27 passed.
- Phase 1 Django boundary: 35 tests, OK.
- OpenAPI: `python scripts/generate_openapi_v1.py --check` 통과.
- Frontend route: `python scripts/generate_frontend_case_routes.py --check` 통과.
- Ruff: `E9,F63,F7,F82` 및 B2/B3/view F401 guard 통과.
- Frontend: 155 passed, `npm run build` 통과.
- Docker D1: `skn27-phase-02-b3-local` build, import, `python backend/manage.py check`, `StartCaseAnalysisCommand` smoke 통과.
- Compose D2: 외부 임시 `python3` shim으로 원본 `scripts/refactoring/run_phase_00_compose_gate.sh`를 실행했다. `phase_00_compose_gate.v1` pass, `compose-final`, `cleanup_success`, failed-step 없음, `mock://` 0, Compose residue 0을 확인했다.

## Windows 환경 관찰

다음은 Phase 2-B3 source 변경과 무관한 기존 Windows 관찰로 기록한다.

- `pymupdf._extra` DLL loading 실패로 전체 Django `487 tests`에 20건 error가 발생했다.
- 같은 DLL 문제는 pytest collection baseline에서 expected `pypdf` 항목을 `ImportError`로 바꾸고, 기존 quarantine portability import 경로 오류를 노출한다.
- Linux Docker D1과 Docker Compose D2는 통과했다.

## Deferred scope

- Production DB audit: `NOT_EXECUTED`
- Phase 3 repository/queue split: `DEFERRED`
- `start_case_analysis()` transaction, lock, reusable Job, Queue 구현의 분할/재구현: Phase 3로 이연.