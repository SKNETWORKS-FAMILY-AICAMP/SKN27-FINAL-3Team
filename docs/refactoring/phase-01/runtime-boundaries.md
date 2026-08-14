# Phase 1 Runtime Boundaries

## Canonical Runtime

기본 `config.urls`와 `/api/`는 Canonical repository, queue/worker, `attachment_staging_service`, `history_event_contract`, object-storage adapter만 사용한다. Canonical module은 `app.mock_runtime` 또는 Explicit Mock service를 import하지 않는다. 기본 runtime에서 `/api/mock/`는 등록되지 않는다.

## Explicit Mock Runtime

Explicit Mock은 `app/mock_runtime/**`와 `config.mock_urls`에 격리한다. 활성화에는 `EXPLICIT_MOCK_RUNTIME_ENABLED=True`, `DEBUG=True`, `ROOT_URLCONF=config.mock_urls`가 모두 필요하다. 어느 하나라도 충족되지 않으면 `ImproperlyConfigured`로 fail-closed한다.

## Neutral Attachment Scan Gate

`app/services/attachment_scan_gate_contract.py`가 `CANONICAL_SCAN_GATE_MARKER`를 단일 소유한다.

- `app.services.attachment_staging_service`, `app.mock_runtime.attachments`, `app.services.attachment_mock_service`는 같은 singleton을 import 또는 re-export한다.
- `is_canonical_scan_ready_reference()`는 marker identity와 canonical metadata를 함께 확인한다. 문자열 값 비교는 provenance proof가 아니다.
- `merge_canonical_scan_ready_reference()`는 `metadata_source=canonical_scan_gate`를 유지하고 public result에서 `_canonical_scan_gate`를 제거한다.
- Canonical scan-ready reference는 staging resolver와 legacy compatibility resolver 모두에서 retention fence를 통과한다.
- retention expiry면 byte read 전에 fail-closed한다. Explicit Mock attachment나 client-forged marker는 canonical provenance를 얻지 못한다.

## Local Infrastructure Adapter

`mock_s3`는 Explicit Mock runtime이 아니라 production storage contract의 local implementation이다. Canonical upload는 `local://attachment-staging/`에서 quarantine 및 file-scan handoff를 거친다. scan-ready 이후에만 canonical object storage URI를 agent handoff에 사용한다.

## Worker Boundary

Public node는 actual `AnalysisJob` → `AgentWorkItem` → queue → `process_agent_work_items` → `AgentResult` 경로를 사용한다. node test는 provider leaf만 deterministic double로 대체하고 `execute_agent_node`, `execute_agent_plan`, worker, repository persistence를 patch하지 않는다. 모든 public node execution은 `explicit_mock_usage_forbidden()` 안에서 Explicit Mock call, sidecar write, public/DB marker, 신규 `mock://` URI가 0임을 assertion한다.

## Legacy DB Column

`AnalysisJob.mock_scenario` physical column은 이 Phase에서 제거하지 않는다. Canonical write/read/serialization은 해당 field에 의존하지 않으며 physical removal은 production data audit 뒤 별도 migration 범위다. 상태는 `DEFERRED`다.

## CI Boundary

`production-gate.yml`은 attachment compatibility, all-public-worker isolation, full Django chatbot regression을 blocking으로 실행한다. `regression-signal`은 `continue-on-error: true`를 사용하는 non-blocking signal이며 merge proof가 아니다. typed pytest collection baseline v2는 `cv2` 3건과 `pypdf` 1건의 known dependency debt 외 새 collection regression을 fail-closed한다.
