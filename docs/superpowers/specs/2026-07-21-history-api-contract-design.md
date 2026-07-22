# 히스토리 API OpenAPI 계약 및 소유권 회귀 설계

**이슈:** #274
**기준:** PR #275가 병합된 `origin/dev`
**상태:** 구현 완료 · CI 확인 대기

## 1. 목표와 범위

기존 Django `GET /api/history/`의 공개 동작을 변경하지 않고, shadow OpenAPI 계약과 회귀 테스트로 다음 경계를 고정한다.

- 응답의 안정 필드와 확장 허용 정책
- `session_id`, `user_id`, `guest_id`, `job_id`, `event_type`, `limit` 조회 조건
- App JWT 또는 server-verified guest credential 인증 경계
- 본인 사용자·게스트·세션·작업만 조회하는 소유권 경계

`/api/mock/history/` sidecar, 저장소 구현, DB migration, 보존 정책, 프런트 UI, 전역 오류 응답 표준화는 변경하지 않는다.

## 2. 현재 동작과 결정

`/api/history/`는 canonical API 경로에서 PostgreSQL `history_events`를 조회한다. App JWT 사용자는 자신의 히스토리를, 유효한 `X-Guest-Credential`을 제시한 guest는 자신의 guest 히스토리를 조회할 수 있다. `X-Guest-Id`는 보조 식별값이며 credential 없이 권한을 증명하지 못한다.

현재 `job_id` 단독 필터는 분석 작업의 소유권을 먼저 확인하지 않는다. 이 이슈에서만 `history_events()`가 기존 `get_analysis_job_access_metadata()`와 `_analysis_job_access_response()` 계열의 접근 제어를 재사용해 이 공백을 막는다. repository나 데이터 모델은 변경하지 않는다.

## 3. 계약 설계

### 3.1 응답 DTO

`app/contracts/history.py`에 public DTO를 둔다.

- 최상위 응답: `history_contract`, `storage`, `history_policy`, `after_service_summary`, `count`, `events`, `limitations`
- 이벤트의 안정 필드: `event_id`, `event_type`, `event_version`, `occurred_at`, `actor`, `subject`, `source`, `status`
- 이벤트·저장소·정책의 추가 운영 메타데이터는 `extra="allow"`로 유지한다.

이는 현재 이벤트 유형마다 달라지는 확장 필드를 제거하거나 엄격 검증하지 않으면서 공개 최소 계약만 고정한다.

### 3.2 요청·보안 계약

`/api/history/`를 `DEFERRED_ROUTE_SPECS`에서 제거하고 `HISTORY_API_ROUTE_SPECS`의 shadow `RouteSpec`으로 등록한다.

- query: `session_id`, `user_id`, `guest_id`, `job_id`, `event_type`, `limit`
- `limit`: 양의 정수이며 비정상 값과 0 이하는 기존처럼 100으로 폴백
- header: `X-Guest-Credential`, `X-Guest-Id`
- 보안: App JWT **또는** `X-Guest-Credential` 중 하나가 필요
- `X-Guest-Id`는 단독 권한 증명이 아님

기존 `auth_optional=True`는 익명 보안 요구사항(`{}`)을 생성하므로 사용하지 않는다. `RouteSpec`에 경로별 보안 요구사항 override를 추가하고, OpenAPI에는 `bearerAuth` 또는 `guestCredentialAuth`의 OR 조건을 생성한다. `guestCredentialAuth`는 header `X-Guest-Credential`을 사용하는 `apiKey` 보안 scheme이다. 기존 route가 override를 지정하지 않으면 기존 생성 결과를 그대로 유지한다.

### 3.3 오류 계약

이 경로가 실제로 반환하는 엔드포인트 수준의 오류만 기록한다.

- 401: `auth_required`, `token_invalid`, `token_expired`
- 403: `object_access_denied`

이는 전역 오류 envelope 재설계가 아니라 현재 응답의 코드와 상태를 shadow 계약에 기록하는 작업이다.

## 4. 최소 런타임 보완

`history_events()`가 canonical 요청에서 `job_id`를 받으면, 기존 분석 작업 접근 메타데이터로 먼저 소유권을 확인한다.

- 본인 작업이면 기존 히스토리 필터를 실행한다.
- 타인 작업이면 기존 객체 접근 거부 envelope와 403을 반환한다.
- 존재하지 않는 작업은 기존 조회 의미를 유지한다. 즉 새 404 계약을 만들지 않고 빈 이벤트 목록 처리 경로를 유지한다.

세션·사용자·guest 필터의 기존 접근 제어와 저장·정렬·보존 동작은 변경하지 않는다.

## 5. 검증 계획

정적 계약 테스트와 Django 런타임 테스트를 분리한다.

1. `RouteSpec`, DTO, query/header, OpenAPI security OR 조건, generated YAML 최신성을 검증한다.
2. App JWT 본인 조회와 유효 guest credential 본인 조회를 검증한다.
3. raw guest ID 401, 타 사용자·guest·세션·job 403을 검증한다.
4. 잘못된·0 이하 `limit`이 100으로 폴백하는지 검증한다.
5. `/api/mock/history/`가 변경되지 않았음을 기존 sidecar 테스트로 확인한다.
6. 관련 집중 테스트 후 전체 Python 회귀와 OpenAPI 생성 검사를 실행한다.

## 6. 체크리스트

이 PR에는 이미 병합된 PR #275의 RAG 도메인 실패 격리 근거(C-1)를 기록한다. 구현과 검증이 완료되면 H의 `히스토리 API 계약`만 완료 처리한다. C-2, H의 전역 오류 계약, I의 운영·E2E 항목은 상태를 변경하지 않는다.

## 7. 비목표

- mock sidecar를 공식 계약으로 승격하지 않는다.
- guest credential을 App JWT의 대체 인증으로 일반화하지 않는다.
- HistoryEvent 저장 형식·보존 기간·metadata allowlist를 변경하지 않는다.
- 전역 API 오류 형식이나 프런트 화면을 변경하지 않는다.
