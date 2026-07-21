# 채팅 세션·메시지·저장 API 공식 계약 설계

## 목적

Issue #270은 기존 Django 채팅 API의 런타임 동작을 바꾸지 않고, 세션 발급·메시지 제출·대화 저장 상태 변경 경로를 OpenAPI와 회귀 테스트가 있는 공식 `shadow` 계약으로 올린다.

대상 경로는 다음 세 개다.

- `POST /api/chat/sessions/`
- `POST /api/chat/messages/`
- `POST /api/chat/save-state/`

이번 작업은 UI, Worker, Agent, DB 스키마, 세션 보관 정책을 변경하지 않는다.

## 확인된 현재 상태

- 세 경로는 `backend/chatbot/urls.py`와 `backend/chatbot/views.py`에 구현돼 있지만, `app/contracts/api_route_specs.py`에서는 `DEFERRED_ROUTE_SPECS`에만 있다.
- `docs/api/openapi-v1.yaml`은 `API_ROUTE_SPECS`에서 생성되므로, 세 경로가 공식 registry에 없으면 OpenAPI에도 나타나지 않는다.
- 메시지 제출은 상황에 따라 즉시 사용자 안내 `200`, 비동기 Worker 대기 `202`, Supervisor 불가 `503`을 반환한다.
- App JWT 또는 guest 흐름이 가능하다. `X-Guest-Id`는 식별 보조값이며, 이미 존재하는 보호 guest 세션·리소스에 대한 권한 증명은 검증 가능한 `X-Guest-Credential` header가 필요하다.
- `POST /api/chat/sessions/`은 현재 draft `session_id`를 발급한다. `ChatSession` DB 레코드는 메시지 제출 또는 후속 상태 저장 과정에서 생성·갱신될 수 있으므로, 세션 발급 성공을 영구 저장 완료로 표현하지 않는다.
- 세션 목록과 메시지 원문 조회의 보관·조회 정책은 아직 확정되지 않았고, 이번 Issue에 포함하지 않는다.

## 결정

### A. 런타임 충실 shadow 계약을 추가한다

새 `app/contracts/chat_session.py`에 공개 request·response DTO를 둔다. DTO는 OpenAPI와 회귀 테스트의 기준이며, 이 Issue에서 Django view의 입력 검증 방식이나 응답 조립을 재작성하지 않는다. 특히 이번 DTO를 Django view에 강제 적용하거나, 기존 응답을 DTO allowlist로 재직렬화하지 않는다.

`app/contracts/api_route_specs.py`에는 `CHAT_SESSION_API_ROUTE_SPECS`를 추가하고, 전체 `API_ROUTE_SPECS` 조합에 포함한다. 세 대상 경로는 deferred 목록에서 제거한다.

이 방식은 이미 사용 중인 Auth·File·Analysis route spec 패턴, OpenAPI 생성기, Django URL resolve 계약과 동일한 구조를 사용한다.

### B. 인증과 guest header를 선택적 경계로 표현한다

세 경로는 `auth_optional=True`로 모델링한다. 이는 App JWT만 사용하는 요청과 guest header를 사용하는 요청 모두 현재 허용된다는 뜻이다.

각 route spec은 다음 header를 문서화한다.

- `X-Guest-Credential`: guest identity를 증명하는 서명 credential
- `X-Guest-Id`: credential과 함께 사용할 수 있는 식별 보조값

OpenAPI의 단순 `required` 속성만으로는 “guest ID를 쓴 경우 credential 필요”라는 조건부 규칙을 완전히 표현할 수 없다. 따라서 두 header는 선택 parameter로 유지하고, 설명·실제 API 회귀 테스트에서 단독 guest ID가 기존 보호 세션의 권한 증명이 아님을 고정한다.

credential은 어떤 request body, query parameter, 응답 DTO, 저장 상태 DTO에도 넣지 않는다.

### C. 메시지 응답은 호환 가능한 공개 상위 DTO로 모델링한다

현재 `RouteSpec`은 한 route의 여러 성공 status를 표현할 수 있지만 status별로 서로 다른 response model을 선언하지는 않는다. 따라서 메시지 응답은 공개 공통 필드와 상태별 선택 필드를 가진 상위 DTO 하나로 표현한다.

- `200`: `needs_input`, `scope_guidance`, `high_risk_handoff`, `case_ready` 등의 즉시 안내
- `202`: `queued` 상태의 Worker 작업 항목과 진행 정보
- `503`: `supervisor_unavailable` 오류

상태별로 반드시 필요한 값은 실제 API 테스트에서 별도로 확인한다. 이 선택은 공통 route spec 프레임워크를 바꾸지 않으면서 현재 프런트·Worker 응답 호환성을 유지한다.

현재 프런트는 최초 메시지 응답의 `work_item`, `supervisor_execution`, `persistence`를 사용해 Worker 결과를 폴링한다. 따라서 상위 DTO는 이 현재 공개 필드를 유지하고, view 응답을 엄격한 allowlist로 축소하지 않는다. 초기 채팅 응답의 별도 공개 경계 재설계는 이번 Issue의 범위가 아니다.

### D. 세션 발급 request와 저장 상태의 현재 의미를 정확히 기록한다

세션 발급 request의 body `user_id`는 신뢰하지 않는다. 현재 identity는 App JWT 또는 검증된 guest header에서만 파생되므로, 공식 request DTO에는 클라이언트가 소유자를 지정하는 필드를 넣지 않는다. 회귀 테스트는 body의 `user_id`가 응답 소유자 값을 위조하지 못함을 확인한다.

저장 상태 API는 존재하지 않는 `session_id`에 대해 현재 `404`가 아니라 `200`과 `conversation_save.status="skipped"`를 반환한다. 이 결과는 기존 idempotent UI 흐름의 정상 응답으로 문서화하며, 새 오류 상태로 변경하지 않는다.

## 구현 경로

1. `app/contracts/chat_session.py`에 다음 공개 DTO를 정의한다.
   - draft 세션 발급 response
   - 소유자 입력을 받지 않는 세션 발급 request
   - 현재 프런트의 Worker 폴링 필드를 보존하는 메시지 request와 상태별 공통 public response
   - `updated`와 `skipped`를 모두 표현하는 대화 저장 상태 request·response
   - 해당 세 API가 실제 반환하는 공개 오류 envelope
2. `api_route_specs.py`에 세 `RouteSpec`을 추가한다.
   - 세션 발급 `200`
   - 메시지 `200`, `202` 성공 상태 및 대표 `401`·`403`·`400`·`429`·`503` 오류
   - 저장 상태 `200` 및 권한 오류
3. registry와 generator를 기준으로 `docs/api/openapi-v1.yaml`을 재생성한다.
4. DTO·route registry·OpenAPI 생성 테스트와 실제 Django API 경로 회귀 테스트를 추가한다.
5. 검증이 통과할 때만 체크리스트 H의 `채팅 세션·메시지·저장 API 계약`을 완료 처리한다.

## 호환성·위험 완화

- **세션 저장 시점 오해**: 세션 발급 response를 draft identifier 발급으로만 문서화한다. DB 저장 보장은 새 API 의미 변경이므로 별도 Issue로 분리한다.
- **guest 권한 약화 위험**: header 순서와 설명을 기존 File·Analysis 계약과 맞추고, raw guest ID만으로 기존 소유 세션을 접근할 수 없음을 API 테스트로 확인한다.
- **다중 성공 응답 드리프트**: `success_statuses=(200, 202)`와 상태별 API 테스트를 함께 둔다.
- **프런트 Worker 폴링 회귀**: `work_item`, `supervisor_execution`, `persistence`를 contract/API 회귀 테스트에서 유지 확인한다. DTO는 이번에 view filtering을 유발하지 않는다.
- **소유자 위조 위험**: 세션 발급의 body identity 값을 계약에서 제외하고, header에서 파생된 subject만 응답에 반영되는지 확인한다.
- **저장 상태 오류 오해**: 없는 세션의 `200 + skipped`를 성공 응답의 한 경우로 문서화·검증한다.
- **전역 오류 계약의 조기 확장**: 이번에는 chat API 전용 오류 envelope만 정의한다. 전체 API 공통 오류는 체크리스트 H의 별도 후속 작업으로 남긴다.
- **범위 확장 위험**: 세션 목록, 메시지 원문 조회, 히스토리, 마이페이지, UI, Worker, Agent, DB migration은 수정하지 않는다.

## 검증 계획

- `test/test_api_route_specs.py`
  - 세 경로가 `CHAT_SESSION_API_ROUTE_SPECS`와 전체 registry에 있고 deferred 목록에는 없는지 확인한다.
  - guest header와 `auth_optional`, 메시지의 `(200, 202)` 성공 상태를 확인한다.
- `test/test_openapi_v1_generation.py`
  - 생성 문서에 세 경로·security·header·success/error schema가 반영됐는지 확인한다.
  - 생성 YAML과 저장된 `docs/api/openapi-v1.yaml`의 동기화를 확인한다.
- `backend/chatbot/test_api_route_specs.py`
  - 새 shadow spec이 실제 Django URL·view name으로 resolve되는지 확인한다.
- 새 또는 기존 Django API 테스트
  - draft 세션 발급에서 body `user_id`가 소유자 값을 바꾸지 않는지 확인한다.
  - 즉시 안내 `200`, Worker 대기 `202`에서 `work_item`, `supervisor_execution`, `persistence`가 현재 프런트 소비 형태로 유지되는지 확인한다.
  - 저장 상태 변경과 존재하지 않는 세션의 `200 + skipped`를 확인한다.
  - 기존 보호 세션의 타 사용자 접근, raw guest ID만의 보호 접근, guest의 `saved` 승격 거부를 확인한다.
  - 응답과 저장 결과에 guest credential이 나오지 않는지 확인한다.

## 완료 기준

1. 세 대상 경로가 deferred가 아닌 공식 shadow route spec과 OpenAPI에 존재한다.
2. draft 세션 발급과 실제 저장 시점을 구분해 문서화한다.
3. 메시지의 `200`·`202`·`503` 흐름, 현재 Worker 폴링 필드, 권한 경계가 회귀 테스트로 고정된다.
4. credential이 body·query·응답·저장 DTO에 없다.
5. 기존 UI, Worker, Agent, DB 스키마와 세션 보관 정책을 변경하지 않는다.
