# Phase 2-D1 ListConsultationCases application use case receipt

## 범위와 기준점

- Base SHA: `ec8ca2dba6543c3ca65489218a462923e148b8bc`
- Branch: `refactor/phase-02-d1-list-consultation-cases-use-case`
- Behavior Head: `8f5dbdb57ff54831aff117ce97e6ae44e16870b1`
- Initial implementation Final Head: `e1238aa223ab18b74c5778baa72f92318c6ab924`
- Reviewed implementation Head / Remote·CI·Independent-review authority: `2e4f9100be439db416f77858f5049b55d62dd632`
- Receipt metadata delta: docs-only append commit. 이 commit의 SHA는 self-reference를 만들지 않도록 receipt에 기록하지 않는다.
- 대상 route: `GET /api/cases/`
- Application Use Case: `execute_list_consultation_cases`
- 작업 범위: GET-only extraction.

## Application boundary와 보존 계약

Target View `consultation_cases`의 `GET /api/cases/` branch는 HTTP adapter로서 authentication fence와 HTTP 직렬화만 유지한다.

`ListConsultationCasesQuery` → `execute_list_consultation_cases` → `access_subject_from_payload` → `list_cases(owner_id=trusted_user_id)`

- owner authority는 trusted `identity_payload.auth_context`에서만 파생한다. client-supplied `owner_id`/`user_id`는 persisted/public identifier 또는 repository filter로 사용하지 않는다.
- 비로그인 또는 trusted user subject가 아닌 요청은 `CaseListAccessDenied`와 기존 HTTP 403 access contract를 유지한다.
- route, method, response, status, ordering 및 owner isolation을 변경하지 않았다.
- 동일 View의 `POST /api/cases/` branch와 POST Case creation behavior는 추출하지 않았으며 변경하지 않았다.
- `backend/chatbot/case_repository.py`, `backend/chatbot/repositories.py`, model, migration, queue/worker semantics, frontend runtime, Dockerfile 및 Compose YAML은 변경하지 않았다.

## 변경 파일

- `app/application/cases/list_cases.py`
- `backend/chatbot/views.py`
- `backend/chatbot/test_phase_02_case_list_use_case.py`
- `scripts/refactoring/verify_phase_02_d1_test_sensitivity.py`
- `test/test_phase_02_d1_sensitivity_runner.py`
- `.github/workflows/production-gate.yml`

## RED, focused regression, sensitivity

- RED / characterization: commit `eab8156`의 `backend/chatbot/test_phase_02_case_list_use_case.py`.
- D1 boundary: 7 passed.
- D1/B1/B2/B3 focused regression: 39 tests, OK.
- Case API regression: 3 tests, OK.
- `scripts/refactoring/verify_phase_02_d1_test_sensitivity.py`: PASS.
- sensitivity mutation: `identity_authority_bypass`, `owner_filter_bypass`, `view_application_bypass` 모두 nonzero `assertion`으로 차단됐다.

## 로컬 검증

- `python backend/manage.py check`: PASS.
- `python scripts/generate_openapi_v1.py --check`: current.
- `python scripts/generate_frontend_case_routes.py --check`: current.
- `ruff check --select E9,F63,F7,F82 .`: PASS.
- `git diff --check`: PASS.
- Docker D1: `skn27-production-gate` build, CI import smoke, `ROOT_URLCONF=config.urls` import 및 Explicit Mock configuration import PASS.

## Docker host bind recovery와 Compose D2

- Root cause: Windows Docker Desktop의 stale D: host bind mount subsystem. D: repository 및 `storage/schemas/law_db_schema.sql`은 Windows에서 정상이나 Docker bind probe는 `no such device`였다. C: control probe는 PASS였다.
- Recovery: Docker Desktop restart. 이후 D: repository bind와 `law_db_schema.sql` bind가 모두 PASS였다.
- Compose source는 변경하지 않았다. 기존 `scripts/refactoring/run_phase_00_compose_gate.sh`를 그대로 실행했다.
- Local Compose D2: `phase_00_compose_gate.v1` PASS, PostgreSQL/Redis/ClamAV/Neo4j/backend ready, agent/file-scan worker consumed, `compose-final`, `cleanup_success`, `mock://` 0, local Compose residue 0.
- Compose D1 runtime probe: `GET /api/cases/` HTTP 200, owner isolation PASS, canonical database `mock://` persistence 0, Explicit Mock runtime side effect 0.

## GitHub CI와 artifacts

| Evidence | ID | Head | Result |
| --- | --- | --- | --- |
| `production-gate` | `32032680398` | `2e4f9100be439db416f77858f5049b55d62dd632` | PASS |
| `offline-verification` | `95396014639` | `2e4f9100be439db416f77858f5049b55d62dd632` | PASS; D1 boundary/sensitivity, collection, OpenAPI, frontend, Ruff, Docker 포함 |
| `compose-integration` | `95397379747` | `2e4f9100be439db416f77858f5049b55d62dd632` | PASS |
| `regression-signal` | `32032680386` | `2e4f9100be439db416f77858f5049b55d62dd632` | PASS; non-blocking |
| `phase-02-d1-sensitivity-evidence` | `9289554227` | `2e4f9100be439db416f77858f5049b55d62dd632` | `phase_02_d1_sensitivity.v1`, PASS, original exit 0, working tree unchanged |
| `phase-00-compose-evidence` | `9289725241` | `2e4f9100be439db416f77858f5049b55d62dd632` | `phase_00_compose_gate.v1`, PASS, `compose-final`, `cleanup_success`, `mock://` 0 |
| `phase-01-pytest-collection-baseline` | `9289558681` | `2e4f9100be439db416f77858f5049b55d62dd632` | PASS |

이 표는 Runtime/Test/Workflow를 변경하지 않는 docs-only metadata delta 이전의 검증 authority `2e4f9100be439db416f77858f5049b55d62dd632`를 기록한다. `phase-02-d1-sensitivity-evidence` 내부 결과는 세 mutation 모두 `assertion` 실패이며 original은 exit 0이다. `phase-00-compose-evidence` 내부 결과는 backend live/ready, database/cache/ClamAV/Neo4j ready, agent/file-scan worker consumed 및 file scan clean을 기록한다.

## PR

- Draft PR: `#405`
- Base: `dev`
- Head: `refactor/phase-02-d1-list-consultation-cases-use-case`
- Ready 전환 및 merge는 수행하지 않았다.

## Windows 환경 관찰

다음은 Base safety worktree와 feature worktree에서 재현된 기존 Windows 환경 관찰이며 Phase 2-D1 source delta의 production defect가 아니다.

- `pymupdf._extra` DLL loading.
- attachment classification import environment.
- `cv2` missing collection baseline.
- Base safety worktree full Django suite는 `487 tests`, 20 errors를 보였다.
- Feature worktree full Django suite는 `494 tests`, 20 errors를 보였다.
- 두 suite의 failure test set은 동일한 20개 failing test 이름이다. Classification은 `BASELINE_ENVIRONMENT_DEBT`이며 D1 regression은 0이다.
- Linux CI의 full Django chatbot regression과 full offline pytest는 PASS였다.

## Deferred scope와 remaining risk

- `POST /api/cases/`: 변경 없음.
- repository split, Queue redesign, storage redesign, Phase 3: `DEFERRED`.
- Production DB audit: `NOT_EXECUTED`.
- 남은 위험은 Windows local full-suite dependency portability와 Production DB audit 미실행이다. Linux CI, Docker D1 및 Compose D2는 통과했다.

## Self-reference policy

이 receipt는 Behavior Head `8f5dbdb57ff54831aff117ce97e6ae44e16870b1`, initial implementation Final Head `e1238aa223ab18b74c5778baa72f92318c6ab924`, 그리고 Remote·CI·Independent-review authority Head `2e4f9100be439db416f77858f5049b55d62dd632`를 구분해 기록한다. 이 docs-only metadata delta commit의 SHA와 이후 CI는 PR #405 metadata 및 final status에서 별도로 기록하며, self-referential receipt commit을 연쇄 생성하지 않는다.
