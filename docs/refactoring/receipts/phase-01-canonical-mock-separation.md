# Phase 1 Canonical/Mock Runtime Separation Receipt

## Git

- Base SHA: `9f05e8b67509c0a1f06bc39d631d6a7c94044a90`
- Branch: `refactor/phase-01-canonical-mock-separation`
- Worktree: `E:\dev\project\SKN27-FINAL-3Team-phase-01`
- 검증한 동작 Head: `fa12890e4ebcd042ec7b48bb13d052a4c83b03ce`
- PR: [#401](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/pull/401) (`dev` ← `refactor/phase-01-canonical-mock-separation`, Draft, unmerged)

P1 보완 append-only commit은 다음과 같다.

| SHA | 내용 |
|---|---|
| `8b4f946eb65683f1725a3449fb2e5169c6bf7109` | Explicit Mock 구현 소유권 이동 |
| `234e67c80b52cb25349c4e819f3711a98b425a59` | history marker와 file-scan persistence 정리 |
| `cb63d8fa6f8a562a44118f0d2091ba6455ad6112` | collection 및 dynamic isolation 회귀 복구 |
| `d7db59a89314d54b001bc3d0969240e2a8734fce` | Phase 1 runtime boundary CI gate 강화 |
| `b7eb0e7a7b0b8b9e61d90febaf736891d6a26650` | P1 보완 README·Receipt 증빙 기록 |
| `24e898d75e18ed755b2df253d355a4f18c614b16` | Compose shared staging root와 default contract 보완 |
| `bb57268afdb914cf0e921c3ee544b26f18d3035b` | 독립 검토의 source marker·malformed plan·RAG test 보완 |
| `fa12890e4ebcd042ec7b48bb13d052a4c83b03ce` | historical test의 stale mock executor reference 정리 |

## Phase 1-C findings

| P1 | 조치 | 테스트 | 결과 |
|---|---|---|---|
| 실제 Mock owner 부재 | `app/mock_runtime/**`에 구현을 이동하고 legacy service를 thin shim으로 축소 | ownership/import gate | PASS |
| Agent Canonical fallback | allowlist 기반 Explicit Mock executor와 전용 4xx 오류 | mock URL isolation | PASS |
| legacy History marker 노출 | write 및 public projection에서 marker를 contract 기준으로 제거 | legacy marker projection | PASS |
| `smoke_file_scan`의 `mock://` write | neutral staging `UploadedFile`로 이관 | smoke persistence | PASS |
| `execute_mock_node` collection 오류 | canonical executor import와 collection baseline gate로 교체 | targeted collect, baseline | PASS |
| 실제 경계 검증 부족 | HTTP·Worker·ORM·public DTO fail-fast reachability test 추가 | dynamic negative reachability | PASS |

## Actual Mock ownership

| Runtime module | 실제 구현 | legacy shim | Production import |
|---|---|---|---|
| `app/mock_runtime/analysis_jobs.py` | analysis-job sidecar CRUD | `app/services/analysis_job_mock_service.py` | 0 |
| `app/mock_runtime/attachments.py` | attachment fixture·sidecar | `app/services/attachment_mock_service.py` | 0 |
| `app/mock_runtime/history.py` | mock history sidecar | `app/services/history_event_mock_service.py` | 0 |
| `app/mock_runtime/chat.py` | scenario/chat deterministic response | `app/services/chatbot_mock_service.py` | 0 |
| `app/mock_runtime/agent_execution.py` | Explicit Mock plan/node executor | 없음 | 0 |

`test/test_phase_01_mock_runtime_ownership.py`는 runtime에서 legacy mock service import가 0임과 shim에 function/class/sidecar logic이 없음을 검사한다. `test/test_phase_01_runtime_import_boundaries.py`는 `app/**`, `backend/**`, `ai/**`, `etl/**`, `storage/**`의 module-level·local·dynamic import 및 forbidden dispatch symbol을 검사한다.

## Agent fail-closed

- 지원 node: `input_context_validation`, `fine_notice_analysis`, `law_ground_search`, `text_ml_case_search`, `vision_media_analysis`, `objection_report_generation`, `agent_result_validation`
- 미지원 node: `UnsupportedExplicitMockNodeError` 후 mock HTTP view가 `400`과 `unsupported_explicit_mock_node`를 반환한다.
- Canonical fallback: 0 (`app.services.agent_node_service.execute_agent_node`를 import·호출하지 않는다.)
- provider call: 0; executor는 deterministic in-process 결과만 사용한다.
- 공개 `execution_mode`: `explicit_mock` 하나로 통일한다.

## Dynamic negative reachability

| Canonical flow | Mock call | Sidecar write | DB marker | Public marker |
|---|---:|---:|---:|---:|
| `POST /api/files/` 및 file persistence | 0 | 0 | 0 | 0 |
| `GET /api/history/` 및 legacy projection | 0 | 0 | 0 | 0 |
| queued `input_context_validation` worker | 0 | 0 | 0 | 0 |
| report list/detail/download public contract | 0 | 해당 없음 | 0 | 0 |

`backend/chatbot/test_phase_01_dynamic_negative_reachability.py`는 Explicit Mock runtime과 sidecar entry point를 fail-fast spy로 감싼 뒤 실제 canonical HTTP/Worker/ORM 흐름을 실행한다. Mock 호출이 일어나면 테스트가 즉시 실패한다.

## Persistence

- `AnalysisJob`: physical `mock_scenario` column은 유지한다. canonical 신규 write·read·response serialization은 0이며, 테스트 job 값은 빈 문자열이다.
- `ChatMessage`, `UploadedFile`, `HistoryEvent`, `Report`, `AgentWorkItem`: canonical 신규 DB/API mock marker는 0이다.
- `HistoryEvent`: `sanitize_metadata()`가 `mock_scenario`, `mock_status`, `canonical_mock`, `mock_analysis_jobs`, `mock_history_events`와 `mock://` URI를 nested metadata에서도 제거한다. 일반 사용자 문자열의 `mock` 단어는 제거하지 않는다.
- legacy History row: 원본 DB row는 read-only로 보존하고 public DTO에서만 sanitize한다.

## File scan smoke

- source URI: `local://attachment-staging/…`
- staging: `app.services.attachment_staging_service.register_staged_attachment()`
- object storage: `backend/chatbot/object_storage.py`의 Local Infrastructure Adapter와 동일한 root precedence (`settings` → environment → default)
- `UploadedFile`: 실제 canonical row를 생성한다.
- `mock://` 신규 write: 0
- Compose evidence: `production-gate` run `31396988541`, artifact `9066272178`에서 upload `pass`, ClamAV `clean`, `file_scan_worker_consumed=true`, `cleanup_success`, `mock://` 0을 확인했다.

## Collection baseline

| Error/module | Base | P1 보완 Head | 분류 |
|---|---:|---:|---|
| `test/test_evaluate_videomae_classifier.py` | 1 | 1 | known baseline (`cv2`) |
| `test/test_prepare_benchmark_manifest.py` | 1 | 1 | known baseline (`pypdf`) |
| `test/test_supervisor_acceptance_fixture_pdf.py` | 1 | 1 | known baseline (`pypdf`) |
| `test/test_videomae_frame_directory.py` | 1 | 1 | known baseline (`cv2`) |
| PR #401 도입 collection 오류 | 0 | 0 | PASS |

`scripts/refactoring/verify_pytest_collection_baseline.py` 최신 결과는 `known_baseline_only`, `collected_tests: 1674`, `unexpected_error_modules: []`이다.

## Attachment staging safety

- ID validation: `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`
- traversal rejection: `../escape`, `..\\escape`, `/tmp/escape`, `C:\\escape`, `att/child`
- root 일관성: staging service와 object storage가 동일한 root를 선택한다.
- cleanup/oversize rollback: 기존 attachment contract 회귀를 유지한다.
- 결과: staging root 밖 file/directory 생성 0.

## Public API contract

| Field/header | 이전 | 최종 | Consumer test |
|---|---|---|---|
| `api_surface` | `canonical_mock` | `canonical` | `chatbot.test_report_api_contract` |
| `execution_mode` | `mock` | `async_worker` (canonical) | `chatbot.test_report_api_contract` |
| Explicit Mock label | 혼재 | `explicit_mock` | `chatbot.test_phase_01_mock_url_isolation` |
| Production frontend `/api/mock/` | 검증 범위 제한 | source·`.ts`/`.tsx`·build output 0 | `test/test_phase_01_frontend_mock_surface.py` |

기본 `config.urls`에는 `/api/mock/`가 없다. Explicit Mock은 `EXPLICIT_MOCK_RUNTIME_ENABLED=True`, `DEBUG=True`, `ROOT_URLCONF=config.mock_urls`를 모두 명시한 test/demo 프로세스에서만 열릴 수 있다.

## Verification

| 명령 | Exit Code | 통과 | 실패 | 판정 |
|---|---:|---:|---:|---|
| Phase 1 ownership/import/isolation pytest | 0 | 14 | 0 | PASS |
| Phase 1 Django URL/dynamic/persistence/public API | 0 | 31 | 0 | PASS |
| targeted collection | 0 | 24 collected | 0 | PASS |
| `verify_pytest_collection_baseline.py` | 0 | 1673 collected | 신규 0 | PASS |
| Phase 0 core/quarantine/consultation | 0 | 14 | 0 | PASS |
| queued follow-up 및 analysis queue | 0 | 41 | 0 | PASS |
| agent execution/privacy | 0 | 68 | 0 | PASS |
| deterministic contracts | 0 | 33 | 0 | PASS |
| compose probe pytest | 0 | 7 | 0 | PASS |
| sensitivity script | 0 | - | 0 | PASS |
| `manage.py check`, OpenAPI/routes, Ruff, diff check | 0 | - | 0 | PASS |
| frontend test | 0 | 155 | 0 | PASS |
| frontend build 및 built surface gate | 0 | 1 | 0 | PASS |
| production RAG smoke tests | 0 | 3 | 0 | PASS |
| `chatbot.tests` regression suite | 0 | 44 | 0 | PASS |

Frontend install은 `npm --prefix app/web ci`로 재현했으며 npm의 기존 high severity advisory와 Vite chunk-size warning은 build 성공과 별개인 P2 follow-up이다.

## CI

| Workflow | Job | Run ID | 결과 |
|---|---|---|---|
| `production-gate.yml` | `offline-verification` | `31396988541` / `93482212918` | PASS |
| `production-gate.yml` | `compose-integration` | `31396988541` / `93483483962` | PASS |
| `regression-signal` | `regression-signal` | `31396988144` / `93482211777` | PASS |

`.github/workflows/production-gate.yml`에는 repo-wide ownership/import, dynamic isolation, legacy projection, neutral smoke persistence, collection baseline, attachment staging, public API contract와 frontend build-output surface gate를 추가했다. 기존 Phase 0 A–G, sensitivity, Docker 및 Compose gate는 유지했다.

## Artifacts

- Collection: `tmp/phase-01-pytest-collection-baseline.json`
- Sensitivity: `tmp/phase-00-sensitivity-evidence.json`
- Compose: `phase-00-compose-evidence` artifact `9066272178`; `gate-summary.json`의 database/cache/ClamAV/Neo4j=`ready`, backend=`true`, agent/file-scan worker consumed=`true`, status=`pass`.

## Independent review follow-up

- independent review 결과: Critical 0, Important 0, merge assessment `Yes`.
- legacy `HistoryEvent.source`의 `canonical_mock`, `mock://`, `/api/mock/` legacy marker는 public DTO에서 canonical contract로 정규화하고 DB 원본은 유지한다.
- Explicit Mock plan은 non-object step, missing `steps`, missing node code를 `invalid_explicit_mock_plan` 4xx로 fail-closed 처리한다.
- `chatbot.tests`의 law-ground characterization은 Explicit Mock이 아니라 Canonical `execute_agent_node`를 호출하도록 복구했고 44건 전체를 재실행했다.
- `RemovedChatbotMockApiContract` historical reference의 stale `execute_mock_plan` patch도 `execute_agent_plan`으로 갱신했다.

## DB audit

- Local/Test: `scripts/refactoring/audit_phase_01_mock_persistence.py --format json` 실행 완료. local test DB row/marker count는 모두 0이다.
- Production: `NOT_EXECUTED` — 운영 DB/AWS에는 접근하지 않았다.
- Physical column: `AnalysisJob.mock_scenario`는 `DEFERRED`.
- Removal: 별도 migration PR 또는 후속 Legacy Phase 범위다. 이 PR은 migration을 생성하지 않는다.

## Known baseline debt

- `cv2`: known collection baseline
- `pypdf`: known collection baseline
- Windows EICAR: 환경 의존 known baseline
- PR #401 신규 collection regression: 0

## Remaining risks

- P0: 확인된 항목 없음.
- P1: 확인된 항목 없음. `fa12890`의 blocking CI와 Compose artifact를 확인했다.
- P2: Docker Desktop daemon이 로컬에서 중지되어 Compose full integration은 재현하지 못했지만 CI artifact로 확인했다. npm advisory와 build chunk warning은 보안/성능 후속 점검 항목이다.

## Rollback

PR을 merge하지 않은 Draft 상태에서 Phase 1-C 재검토를 받는다. rollback이 필요하면 P1 보완 commit을 최신순으로 별도 revert commit으로 되돌린다. schema 변경과 migration이 없으므로 schema rollback은 필요하지 않다.

Phase 2 View/Application 분리와 Phase 3 queue/repository/storage/bounded-context 재설계는 이 PR 범위에 포함하지 않는다.
