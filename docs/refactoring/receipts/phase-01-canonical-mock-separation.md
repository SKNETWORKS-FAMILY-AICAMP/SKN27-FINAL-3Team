# Phase 1 Canonical/Explicit Mock Runtime Separation Receipt

## 범위와 Git 상태

- Repository: `SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team`
- Base SHA: `9f05e8b67509c0a1f06bc39d631d6a7c94044a90`
- Previous reviewed Head: `f79d8cf41c443507d3fe6a7ddfec536ced1d7d17`
- Behavior Head: `7ed21931b5e94bd4860ab8f43121e41d4cacba90`
- Branch: `refactor/phase-01-canonical-mock-separation`
- PR: [#401](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/pull/401) (`dev` ← `refactor/phase-01-canonical-mock-separation`, Draft, unmerged)
- Final documentation Head: 이 receipt를 포함하는 docs-only commit 이후의 PR Head를 PR metadata에서 관리한다. 이 문서는 behavior 검증 SHA와 docs-only 검증 SHA를 혼동하지 않는다.

이번 P1 3차 보완은 기존 commit을 수정하지 않은 append-only 변경이다.

| SHA | 내용 |
|---|---|
| `caedce107bc6903b0f9643acd250bb89bbd700ae` | attachment scan gate compatibility RED |
| `b0830c8` | neutral scan gate contract |
| `f63fdf5` | Canonical attachment ID safety seam |
| `ed44127` | 8개 public node 실제 Worker isolation |
| `73cee48` | Phase 1 및 full Django blocking gate |
| `5ce5911` | 독립 P1 blocking steps |
| `7ed21931b5e94bd4860ab8f43121e41d4cacba90` | full Django blocking 정책 CI contract |

## P1 해결 Matrix

| P1 | Root Cause | 구현 | 증명 테스트 | Behavior CI 결과 |
|---|---|---|---|---|
| P1-01 | staging, Explicit Mock runtime, legacy shim이 서로 다른 `CANONICAL_SCAN_GATE_MARKER` identity를 소유했다. | `app/services/attachment_scan_gate_contract.py`가 singleton, predicate, merge를 단일 소유한다. | `chatbot.test_phase_01_attachment_scan_gate_compatibility` | PASS |
| P1-02 | 테스트가 제거된 `register_mock_attachment` alias를 patch했다. | 실제 lookup seam `chatbot.repositories.register_staged_attachment`를 patch하고 server ID persistence assertion을 유지했다. | `ConsultationPersistenceSafetyTests.test_file_api_ignores_client_supplied_attachment_id` | PASS |
| P1-03 | public catalog 비교만 있고 8개 node의 실제 queue/Worker 실행 증거가 없었다. | 실제 `AnalysisJob`·`AgentWorkItem`·queue·Worker·ORM 경로에서 provider leaf만 deterministic double로 대체했다. | `chatbot.test_phase_01_public_worker_node_isolation` | PASS |
| P1-04 | full Django와 regression-signal의 의미가 구분되지 않았고 blocking 증적이 부족했다. | 독립 P1 steps, blocking full Django gate, 해당 policy CI contract를 추가했다. | `test_pull_request_gate_runs_offline_runtime_build_and_infrastructure_checks` | PASS |

## Canonical Scan Gate Contract

- Owner module: `app/services/attachment_scan_gate_contract.py`
- Shared marker: `CANONICAL_SCAN_GATE_MARKER`
- Staging marker identity: `app.services.attachment_staging_service.CANONICAL_SCAN_GATE_MARKER is CANONICAL_SCAN_GATE_MARKER`
- Legacy marker identity: `app.mock_runtime.attachments.CANONICAL_SCAN_GATE_MARKER is CANONICAL_SCAN_GATE_MARKER` 및 `app.services.attachment_mock_service.CANONICAL_SCAN_GATE_MARKER is CANONICAL_SCAN_GATE_MARKER`
- Forged string: 문자열 `"canonical-scan-gate"`만 가진 client payload는 identity predicate에서 거절된다.
- `metadata_source`: 두 resolver 모두 canonical reference에 `canonical_scan_gate`를 유지하고 private `_canonical_scan_gate` key는 public payload에서 제거한다.
- Retention expired: `read_object_bytes` 전에 fail-closed되어 bytes를 반환하지 않는다.
- Retention active: 기존 canonical object bytes read를 유지한다.
- Explicit Mock attachment: canonical provenance로 승격되지 않는다.

## Attachment ID Safety

- Previous patch seam: `chatbot.repositories.register_mock_attachment`
- New patch seam: `chatbot.repositories.register_staged_attachment`
- Client ID: client-supplied `attachment_id`는 Canonical staging/persistence identifier로 신뢰하지 않는다.
- Persisted ID와 public response ID는 모두 server-generated ID이며 client 값과 다르다.
- session/owner/case binding assertion을 유지했다.
- `register_mock_attachment` alias는 Canonical production module에 복원하지 않았다.

## Public Worker Node Matrix

모든 case는 `explicit_mock_usage_forbidden()` 안에서 실제 queue와 `process_agent_work_items`를 실행한다. `execute_agent_node`, `execute_agent_plan`, worker, repository persistence, `AgentResult.objects.create()`를 patch하지 않는다.

| node_code | provider double | terminal contract | Explicit Mock/sidecar/marker |
|---|---|---|---|
| `fine_notice_analysis` | `graph.invoke` | worker success와 `AgentResult` persistence | 0 / 0 / 0 |
| `attachment_document_classification` | `classify_document_bytes` | worker success와 `AgentResult` persistence | 0 / 0 / 0 |
| `law_ground_search` | `run_law_ground_search` | worker success와 `AgentResult` persistence | 0 / 0 / 0 |
| `text_ml_case_search` | `run_text_ml_case_search` | worker success와 `AgentResult` persistence | 0 / 0 / 0 |
| `traffic_accident_confirmation_ocr` | `graph.invoke` | worker success와 `AgentResult` persistence | 0 / 0 / 0 |
| `vision_media_analysis` | `run_vision_media_analysis` | worker success와 `AgentResult` persistence | 0 / 0 / 0 |
| `appeal_decision_flow` | `graph.invoke` | worker success와 `AgentResult` persistence | 0 / 0 / 0 |
| `objection_report_generation` | `run_objection_report_generation` | worker success와 `AgentResult` persistence | 0 / 0 / 0 |

`executed_public_node_codes == actual_public_node_codes`를 exact-match로 assertion한다. public DB/API payload의 `canonical_mock`, `mock_scenario`, `mock_status`, `mock://`도 0이다.

## Blocking Regression Gates

`production-gate.yml`의 `offline-verification`은 다음을 모두 blocking으로 실행한다.

| Gate | Selector 또는 step | Behavior CI |
|---|---|---|
| Phase 1 boundary | canonical/Explicit Mock Python 및 Django selector | PASS |
| Attachment compatibility | retention fence, attachment ID seam, compatibility test | PASS |
| Public Worker isolation | `chatbot.test_phase_01_public_worker_node_isolation` | PASS |
| Full Django | `python backend/manage.py test chatbot --verbosity 1` | PASS |
| Collection baseline v2 | `python scripts/refactoring/verify_pytest_collection_baseline.py` | PASS |
| Phase 0, queued follow-up, frontend, Terraform, Docker | 기존 blocking steps 유지 | PASS |

## Full Regression과 known debt

- Full Django chatbot regression은 `production-gate.yml`의 blocking step이며 Linux CI에서 PASS다.
- typed pytest collection baseline v2는 정확히 `cv2` 3건과 `pypdf` 1건을 known dependency debt로 관리하며 Linux behavior CI에서 unexpected collection regression 0으로 PASS다.
- `regression-signal`의 `Full offline pytest`와 Django suite는 `continue-on-error: true`를 가진 non-blocking signal이다. workflow success는 full offline pytest의 merge proof가 아니다.
- full offline pytest는 dependency debt 때문에 전체 green으로 표현하지 않는다.

## Local Verification

| 명령 또는 gate | 결과 | 판정 |
|---|---|---|
| Phase 1 Python selector | `27 passed` | PASS |
| focused P1-01/P1-02 | `4 tests`, `OK` | PASS |
| public Worker isolation | `1 test`, `OK` | PASS |
| dynamic isolation + public Worker | `4 tests`, `OK` | PASS |
| 실제 존재 Phase 1 Django selector | `24 tests`, `OK` | PASS |
| Contract and artifact gate | `53 passed` | PASS |
| Node tests | `155 passed` | PASS |
| `npm --prefix app/web run build` | exit 0 | PASS |
| `ruff check --select E9,F63,F7,F82 .` | exit 0 | PASS |
| `python backend/manage.py check` | exit 0 | PASS |
| OpenAPI/routes drift checks | exit 0 | PASS |
| mock persistence audit | marker 및 `mock://` 0 | PASS |

Windows native full Django, deterministic contracts, full collection은 `pymupdf._extra` DLL loading으로 중단된다. 기존 EICAR quarantine portability 관찰도 유지한다. 두 관찰은 focused P1 regression이 아니며, P1 behavior 판정은 Docker Linux와 blocking Linux CI 결과로 분리했다. Terraform CLI는 이 Windows 환경에 설치되어 있지 않아 local 실행은 `NOT_EXECUTED`; behavior CI의 Terraform gate는 PASS다.

## Local Docker

- D1 build: `docker build -t skn27-phase-01-p1-third-local .` PASS
- D1 import: `phase-01 p1 third import smoke ok`
- `ROOT_URLCONF`: `config.urls`
- `EXPLICIT_MOCK_RUNTIME_ENABLED`: `False`
- `/api/mock/` registered: `False`
- D2: `scripts/refactoring/run_phase_00_compose_gate.sh` PASS
- D2 database/Redis/ClamAV/Neo4j: ready
- D2 backend live/ready, Agent Worker 및 File Scan Worker consumed: true
- D2 staging URI: `local://attachment-staging/`
- D2 new `mock://`: 0
- D2 last step: `compose-final`; cleanup: `cleanup_success`; container/volume/network 잔존: 0

## Behavior CI와 Artifact

| Workflow | Job | Run ID | Result | Blocking |
|---|---|---:|---|---|
| `production-gate.yml` | `offline-verification` | `31776184874` / `94691971726` | PASS | yes |
| `production-gate.yml` | `compose-integration` | `31776184874` / `94692658166` | PASS | yes |
| `regression-signal` | `regression-signal` | `31776184869` / `94691972055` | PASS | no |

- Compose: `9210084153`
- Sensitivity: `9209980513`
- Collection baseline: `9209976190`

## Production Delta와 Deferred Scope

- API, Model, migration, View, Repository, Frontend, Dockerfile, root Compose, dependency, Terraform: 이번 P1 remediation에서 변경하지 않았다.
- Service: neutral scan gate contract와 기존 staging/mock compatibility import만 변경했다.
- Agent: production dispatch를 변경하지 않았고 public node coverage test만 추가했다.
- Production DB audit: `NOT_EXECUTED`
- `AnalysisJob.mock_scenario` physical column removal: `DEFERRED`
- Remaining TOCTOU risk: P2에서 file identity/replace race의 추가 hardening을 검토한다.

PR #401은 Draft·unmerged 상태로 유지한다. 최종 docs-only Head의 blocking CI가 PASS한 뒤에만 Phase 1-C 독립 재검토 입력으로 사용한다.
