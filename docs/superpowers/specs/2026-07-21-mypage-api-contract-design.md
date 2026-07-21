# 마이페이지 요약 API 공식 계약 설계

## 목적

Issue #272의 `GET /api/mypage/summary/`를 현재 동작을 바꾸지 않는 shadow OpenAPI 계약으로 등록하고, 본인·세션·guest 소유권 경계를 회귀 테스트로 고정한다.

이 작업은 UI, 집계 규칙, DB, Worker/Agent 또는 인증 구현을 재설계하지 않는다. 기존 Django view `mypage_summary`와 `get_mycase_summary()`를 그대로 사용한다.

## 현재 구현과의 정합성

- 프런트엔드는 `app/web/apiClient.js`에서 `session_id`만 query로 보내며, 화면은 응답의 `cases`를 사용한다. 호출 URL·UI·상태 처리는 바꾸지 않는다.
- 서버는 `owner_id`를 우선하고, 없을 때 레거시 `user_id`, 그 다음 인증 subject의 `user_id`를 사용한다. 이 우선순위는 문서화만 하고 변경하지 않는다.
- `limit`은 양의 정수이며 기본값은 10이다. 누락·0·음수·정수가 아닌 값은 현재처럼 400이 아니라 기본값으로 처리한다.
- App JWT 또는 검증된 guest credential을 사용할 수 있다. `X-Guest-Id`는 식별 보조값일 뿐이고, 보호된 guest 요청의 권한 증명은 `X-Guest-Credential`이다.

## 결정

### A. DTO는 shadow 문서·생성 전용으로 둔다

DTO와 RouteSpec은 OpenAPI 및 정적 계약 테스트의 기준이다. Django view의 입력 검증이나 응답 필터로 연결하지 않는다.

현재 응답에는 안정적인 화면용 요약 외에도 `storage`, `progress_cache`, `object_storage`, `session_cache`, 실행 메타데이터처럼 운영 환경 또는 향후 확장에 따라 달라질 수 있는 값이 있다. 따라서 응답 상위 모델은 `extra="allow"`로 두고, 다음의 안정적인 공개 필드만 타입화한다.

- `active_cases`, `due_soon_cases`, `saved_reports`, `recent_analysis_count`
- `cases`
- `conversation_save_policy`
- `limitations`

이렇게 하면 기존 응답 필드가 사라지거나 프런트가 DTO allowlist 때문에 깨지는 일이 없다. 운영 메타데이터의 상세 구조를 장기 공개 계약으로 고정하지도 않는다.

### B. query·인증 경계를 현재 구현 그대로 명시한다

공식 route spec에는 다음 선택 query를 선언한다.

- `session_id`: 세션 기준 요약 및 세션 캐시 조회
- `owner_id`: 요청 대상 owner. 존재하면 최우선
- `user_id`: `owner_id`가 없을 때만 쓰는 호환용 별칭
- `limit`: 양의 정수, 기본값 10, 잘못된 값은 기본값 처리

`X-Guest-Credential`, `X-Guest-Id` header도 기존 공통 parameter를 재사용해 문서화한다. 이 route는 App JWT와 guest credential 경로를 모두 허용하므로 `auth_optional=True`로 등록한다. 단, 이는 무인증 허용을 뜻하지 않으며 실제 권한 판정은 현행 `mypage_summary`의 access payload 및 owner/session 인가 로직이 수행한다.

credential은 header로만 다루며 query, response DTO, 로그용 DTO에 추가하지 않는다.

### C. Deferred 해제는 계약 등록만 의미한다

기존 Deferred 사유에는 query service 미추출이라는 오래된 표현이 있으나, 실제로 `get_mycase_summary()`가 이미 존재한다. 이번 작업은 서비스 리팩터링을 하지 않고, DTO·route registry·생성 OpenAPI·회귀 테스트를 추가해 해당 GET route만 Deferred 목록에서 제거한다.

## 검증 설계

정적 계약 테스트는 다음을 고정한다.

- route가 공식 registry에 있고 Deferred 목록에는 없음
- `owner_id`/`user_id`의 설명과 우선순위, `limit`의 기본값 폴백
- `auth_optional=True`, guest credential/ID header의 역할
- OpenAPI의 GET operation, 200 응답 DTO 및 query/header parameter
- 안정 필드 타입화와 상위 응답의 확장 허용

Django 통합 테스트는 다음을 고정한다.

- 본인 owner 또는 본인 세션 요청은 200
- 다른 owner 요청과 다른 세션 요청은 403
- `X-Guest-Id`만 보낸 protected guest 요청은 credential 누락으로 거부
- 유효한 guest credential 요청은 기존 정책 범위에서만 허용
- `limit`의 유효·무효 입력이 기존 기본값 폴백을 유지

## 비범위

- `mypage_summary` view, `get_mycase_summary()` 및 query/aggregation 로직 변경
- 프런트 UI·History API·DB migration·Worker/Agent/OCR/report 변경
- 앱 전체 공통 오류 envelope 정비
- runtime DTO validation 또는 응답 allowlist 적용

## 완료 기준

1. `/api/mypage/summary/`가 Deferred가 아닌 shadow route spec과 generated OpenAPI에 존재한다.
2. 기존 응답·인증·소유권·limit 폴백 동작을 바꾸지 않는 테스트가 통과한다.
3. raw guest ID 단독으로 protected mypage 리소스에 접근할 수 없음을 검증한다.
4. 체크리스트 H의 마이페이지 API 계약 항목은 모든 검증 후 같은 PR에서만 갱신한다.
