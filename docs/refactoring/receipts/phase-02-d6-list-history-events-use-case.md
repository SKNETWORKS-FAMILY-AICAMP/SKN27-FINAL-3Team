# Phase 2-D6 ListHistoryEvents Application Boundary

## Authority

- Repository: `SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team`
- Base: `ac598819f4f266367cb95934b281ad3d71a23b01`
- Branch: `refactor/phase-02-d6-list-history-events-use-case`
- RED Head: `9b76084b82415b8be9c4dd111534bbcb523ab5dc`
- GREEN/Behavior Head: `5d9f5405d4cef863e5cb2ebd690b2f17e0981f0d`
- Verification-gate Head: `743de5a2f0bee2b4bf2c107f854de333adff7659`
- Final reviewed runtime Head: `df513820b2bfa3b72cadc4e0b4057436cd8f440a`
- PR: `#410`
- State: `OPEN`
- Draft: `true`
- Merge: `NOT_PERFORMED`

이 Receipt는 runtime 및 검증 변경이 끝난 `df513820b2bfa3b72cadc4e0b4057436cd8f440a`를 기록한다. 이어지는 docs-only metadata commit의 SHA는 self-reference 하지 않는다.

## Target

- Route: `GET /api/history/`
- View: `history_events`
- Application: `app/application/history/list_events.py`
- Use Case: `ListHistoryEvents`

## RED Chronology

- RED commit: `test: characterize history application boundary`
- RED command: `python backend/manage.py test chatbot.test_phase_02_history_list_events_use_case --verbosity 1`
- RED exit: nonzero
- RED failure: `AssertionError` — `execute_list_history_events` called `0` times
- GREEN commit: `refactor: extract list history events use case`
- RED ancestor of GREEN: `YES`
- Classification: `INDEPENDENTLY_PROVABLE`

## Application Boundary

`history_events`는 HTTP query parsing, framework identity 수신, `ListHistoryEventsQuery` 생성, Application 호출, `HistoryListAccessDenied`의 기존 HTTP error mapping, JSON serialization만 수행한다.

`execute_list_history_events`는 `auth_context`만 authority로 해석하고, job/session/user/guest authorization, subject scope/filter derivation, invalid 또는 non-positive `limit`의 `100` normalization, 기존 `list_history_event_records` 호출, standard-light public projection과 response policy construction을 담당한다.

직접 ORM, `transaction.atomic`, HTTP request/response, cache write, Queue/Worker, Storage/Renderer, Agent/RAG 의존성은 Application module에 없다. retention, history record 조회, projection과 marker sanitization은 기존 repository/service helper에 위임한다.

## Contract and Privacy

- Bearer 또는 유효한 `X-Guest-Credential` semantics 유지
- `X-Guest-Id` 단독은 `401`로 거부
- foreign user, guest, session, job은 `403 object_access_denied`
- owner job 및 credential-proved guest history read 유지
- invalid/non-positive `limit`은 `100`
- guest retention cutoff 유지
- standard-light 응답에서 raw conversation, OCR, private reasoning, internal metadata, legacy/mock marker를 노출하지 않음
- `GET /api/history/`는 `HistoryEvent`를 추가 생성하지 않는 read-only 경계
- Route, query parameter, OpenAPI DTO, History repository physical semantics, schema/migration, write/Queue/Worker/Storage/Renderer/frontend는 변경하지 않음

## Tests

| Suite | Command | Result |
| --- | --- | --- |
| D6 focused + History contract | `python backend/manage.py test chatbot.test_phase_02_history_list_events_use_case chatbot.test_history_api_contract --verbosity 1` | `10 tests, OK` |
| History guest/marker/mock regression | `python backend/manage.py test chatbot.test_phase_02_history_list_events_use_case chatbot.test_history_api_contract chatbot.test_guest_credential_boundary chatbot.test_phase_01_legacy_marker_projection chatbot.test_phase_01_dynamic_negative_reachability --verbosity 1` | `28 tests, OK` |
| B1–D5 Application regression | `python backend/manage.py test chatbot.test_phase_02_case_workspace_use_case chatbot.test_phase_02_case_fact_confirmation_use_case chatbot.test_phase_02_case_analysis_use_case chatbot.test_phase_02_case_list_use_case chatbot.test_phase_02_case_creation_use_case chatbot.test_phase_02_report_document_confirmation_use_case chatbot.test_phase_02_conversation_save_state_use_case chatbot.test_phase_02_report_read_queries_use_case chatbot.test_report_api_contract --verbosity 1` | `79 tests, OK` |
| D6 runner + History/OpenAPI shadow contracts | `python -m pytest -p no:cacheprovider test/test_phase_02_d6_sensitivity_runner.py test/test_history_api_contract.py test/test_api_route_specs.py -q` | `20 passed` |
| Existing B2–D5 sensitivity runner contracts | `python -m pytest -p no:cacheprovider test/test_phase_02_b2_sensitivity_runner.py test/test_phase_02_b3_sensitivity_runner.py test/test_phase_02_d1_sensitivity_runner.py test/test_phase_02_d2_sensitivity_runner.py test/test_phase_02_d3_sensitivity_runner.py test/test_phase_02_conversation_save_state_sensitivity_runner.py test/test_phase_02_d5_sensitivity_runner.py test/test_phase_02_d6_sensitivity_runner.py -q` | `24 passed` |
| Django/OpenAPI/frontend/Ruff | `python backend/manage.py check`; `python scripts/generate_openapi_v1.py --check`; `python scripts/generate_frontend_case_routes.py --check`; `ruff check --select E9,F63,F7,F82 .`; `ruff check --select F401 app/application/history/list_events.py` | `PASS` |
| Diff | `git diff --check` | `PASS` |

Windows native full Django suite는 `python backend/manage.py test chatbot --verbosity 1`에서 `526 tests`, `20 errors`였다. `pymupdf._extra` DLL loading 및 attachment classification adapter import 계열의 기존 Windows 환경 debt이며, D6 source delta 경로와 무관하다. focused History 및 이전 Phase 2 boundary regression은 모두 통과했다. Linux blocking CI가 full Django authority다.

## Sensitivity

`python scripts/refactoring/verify_phase_02_d6_history_list_events_test_sensitivity.py`는 baseline `0`, 다음 다섯 변이 모두 nonzero `AssertionError`, source restore `true`, working tree unchanged `true`를 확인했다.

| Mutation | Direct detection |
| --- | --- |
| `view_application_bypass` | View seam assertion |
| `job_authorization_bypass` | foreign job `403` assertion |
| `session_authorization_bypass` | foreign session `403` assertion |
| `default_limit_bypass` | default `100` assertion |
| `public_marker_projection_bypass` | public marker stripping assertion |

B2, B3, D1, D2, D3, D4, D5 기존 sensitivity gates도 모두 `PASS`였다.

## Local Docker

### D1

- Image: `skn27-phase-02-d6-local`
- Build: `docker build -t skn27-phase-02-d6-local .` → `PASS`
- Django initialization 및 `execute_list_history_events` / `history_events` import smoke: `PASS`

### D2

- Script: `scripts/refactoring/run_phase_00_compose_gate.sh`
- Host recovery: 저장소 밖 임시 `python3`/`docker` shim으로 Git Bash Windows CRLF만 정규화; repository, Dockerfile, Compose, system PATH는 변경하지 않음
- PostgreSQL, Redis, ClamAV, Neo4j: `ready`
- backend live/ready: `true`
- Agent Worker/File Scan Worker consumed: `true`
- staging URI: `local://attachment-staging/`
- new `mock://`: `0`
- `last-step.txt`: `compose-final`
- `cleanup.txt`: `cleanup_success`
- `failed-step.txt`: 없음
- Compose containers/volumes/networks residue: `0`
- Result: `PASS`

## CI

- D6 blocking steps는 `.github/workflows/production-gate.yml`에 추가했다.
- Draft PR 생성 직후의 CI: `PENDING`
- CI가 통과한 뒤 PR body에 run/job/artifact metadata만 갱신한다. 이 갱신은 CI를 재실행하지 않는다.

## Deferred and Risks

- Production DB audit: `NOT_EXECUTED`
- Remaining Phase 2 slices 및 Phase 3 대규모 구조 변경: 범위 외
- P0: `0`
- P1: `0`
- P2: Windows full-suite dependency portability debt (`pymupdf._extra`, attachment classification adapter import)