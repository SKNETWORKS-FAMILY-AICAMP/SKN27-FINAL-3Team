# Phase 1 Mock Consumer Migration

## 소유권

Explicit Mock 구현과 sidecar는 `app/mock_runtime/**`가 소유한다. `config.mock_urls`는 test/demo 전용 진입점이다. Canonical API, worker, repository, staging, history, report 경로는 Explicit Mock 구현을 import하거나 dispatch하지 않는다.

## Compatibility Direction

legacy `app.services/*_mock_service.py`는 compatibility shim이다. dependency 방향은 Explicit Mock/legacy shim → neutral contract이며, neutral contract와 Canonical production module은 `app.mock_runtime`에 의존하지 않는다.

attachment scan provenance의 shared owner는 `app/services/attachment_scan_gate_contract.py`다. staging, Explicit Mock runtime, legacy shim은 같은 `CANONICAL_SCAN_GATE_MARKER` singleton을 re-export할 수 있지만 별도 marker class 또는 문자열 동등성 검사를 만들지 않는다.

## Canonical Attachment ID

Canonical upload seam은 `chatbot.repositories.register_staged_attachment`다. client-supplied `attachment_id`는 server staging/persistence identifier가 아니다. 안전성 테스트는 production alias를 복원하지 않고 이 lookup seam을 patch한다. persisted/public attachment ID와 owner/session/case binding을 확인한다.

## Public Worker Consumer Coverage

다음 public node는 catalog 비교만이 아니라 실제 Canonical queue/Worker execution으로 검증한다.

- `fine_notice_analysis`
- `attachment_document_classification`
- `law_ground_search`
- `text_ml_case_search`
- `traffic_accident_confirmation_ocr`
- `vision_media_analysis`
- `appeal_decision_flow`
- `objection_report_generation`

각 case는 provider leaf만 deterministic double로 대체하고 terminal job/work/result contract를 확인한다. `executed_public_node_codes == actual_public_node_codes`가 exact-match여야 하며, Explicit Mock call, legacy sidecar write, `mock_scenario`, `mock_status`, `canonical_mock`, `mock://` 신규 write는 모두 0이다.

## Consumer Safety Rules

- default frontend source와 production bundle은 `/api/mock/`를 노출하지 않는다.
- public DTO와 persisted canonical metadata는 mock marker를 projection하지 않는다.
- Explicit Mock endpoint는 enabled debug runtime에서만 존재한다.
- full Django regression은 `production-gate.yml`의 blocking step이다.
- `regression-signal`은 non-blocking 관찰 신호이며 blocking CI 결과로 대체하지 않는다.

## Deferred Work

`AnalysisJob.mock_scenario` physical column removal은 `DEFERRED`다. Phase 2/3의 대규모 View/Application, Queue/Repository/Storage 재설계와 production DB audit은 이번 PR 범위가 아니다.
