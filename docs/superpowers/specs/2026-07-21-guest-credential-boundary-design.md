# 비회원 guest credential 서버 검증 경계 설계

## 목적

현재 비회원 리소스의 소유권 및 Google 로그인 결합은 클라이언트가 제공하는
`guest_id` 값에 의존한다. 이 값은 식별자일 뿐 증명 수단이 아니므로, 유출 또는
복제한 값만으로 기존 비회원 세션을 재개하거나 로그인 결합을 시도할 수 있다.

Issue #258의 목표는 `guest_id`와 별도의 서명된 guest credential을 발급하고,
서버가 검증한 credential이 있는 경우에만 해당 비회원 신원을 사용하도록 경계를
바꾸는 것이다. 기존 비회원 → Google 로그인 → Case 승격 흐름과 사용자 JWT 흐름은
유지한다.

## 현재 위험과 설계 전제

- `create_guest_session()`이 요청 본문의 `guest_id`를 그대로 재사용한다.
- `_payload_with_request_identity()`는 app JWT 검증 실패 뒤에도 `X-Guest-Id`를
  신뢰해 guest `auth_context`를 만들 수 있다.
- `persist_guest_session_identity()`는 요청이 제공한 `session_id`를 guest 신원에
  결합할 수 있다.
- Google code 로그인은 본문의 `guest_id`와 기존 세션의 `guest_id`를 비교하지만,
  그 값이 해당 요청자의 증명인지는 확인하지 않는다.

따라서 credential이 없거나 유효하지 않은 요청은 **새 비회원 신원을 발급하는
엔드포인트에서만** 새로 시작할 수 있고, 기존 `guest_id`나 기존 `session_id`를
재사용하거나 결합해서는 안 된다.

## 결정

### A. credential 형식과 수명

- 새 모듈 `app/services/guest_credential_service.py`가 JWT(HS256)를 발급·검증한다.
- claim은 `iss`, `aud`, `typ`, `sub`(정규화된 `guest_id`), `iat`, `exp`, `jti`를
  포함한다. `aud`와 `typ`은 guest credential 전용 값으로 고정한다.
- 서명 키는 앱 JWT 키와 같은 원문 설정값을 사용하더라도, 별도 HMAC 파생 키/고정
  salt를 사용한다. issuer·audience·type 모두 달라 앱 JWT와 상호 대체되지 않는다.
- 만료는 현행 guest TTL(7일)을 사용한다. 이번 범위에는 DB revocation, 즉시 폐기,
  HttpOnly Cookie 전환을 포함하지 않는다.
- credential은 `POST /api/auth/guest-session/`의 성공 응답에만 호환성 추가 필드
  `guest_credential`으로 내려간다. 반환 객체의 기존 필드는 삭제하거나 이름을
  바꾸지 않는다.

### B. 신원 입력 경계

- guest credential은 `X-Guest-Credential` request header로만 받는다.
- `guest_id`는 요청의 대상·세션 결합 여부를 표현하는 보조 값일 수는 있으나,
  신원 증명에는 사용하지 않는다. request body, query string, `auth_context`,
  `X-Guest-Id` 단독 값은 모두 증명이 아니다.
- 서버는 먼저 app JWT를 검증한다. 유효한 app JWT가 있으면 현행 로그인 사용자
  경로를 유지한다.
- app JWT가 없고 guest 대상 요청이면 credential을 검증한 뒤, 검증한 claim의
  `guest_id`만 `auth_context`와 소유권 판정에 주입한다. 원문 credential은 그 어떤
  payload에도 넣지 않는다.
- `X-Guest-Id` raw fallback과 body/query `guest_id` fallback은 제거한다.

### C. 새 비회원 세션 정책

`POST /api/auth/guest-session/`만 예외적으로 credential 없이 호출할 수 있다.

- 유효 credential이 있으면 claim의 guest 신원을 재개하고 새 credential을 발급한다.
  요청의 raw `guest_id`가 claim과 달라도 그 raw 값은 무시하며, 타인의 신원으로
  전환하거나 재발급하지 않는다.
- credential이 없거나 만료·변조·claim 불일치면 서버가 새 랜덤 `guest_id`를
  발급한다. 요청이 보낸 기존 `guest_id`를 재사용하지 않는다.
- 위 새 시작 경로에서는 요청의 기존 `session_id`도 신뢰하거나 결합하지 않는다.
  프런트엔드는 저장된 `session_id`와 guest 상태를 폐기하고 새 신원으로 시작한다.
- 유효 credential인 경우에만 그 credential claim의 guest와 `session_id` 결합을
  허용하며, 기존 세션의 소유자/guest 상태 검사는 현행 정책을 유지한다.

### D. 보호 API와 오류 계약

채팅, 파일, analysis job, 이력, 보고서/다운로드와 Google 로그인 결합 경로는 공통
request identity helper를 호출한다. header/body/query의 guest ID 또는 기존 guest
세션을 가리키는 `session_id`는 **credential 필요 여부를 판별하는 입력으로만** 쓴다.
이 값으로 `auth_context`를 만들지는 않는다. guest 대상으로 판별된 요청에
credential이 없거나 유효하지 않으면 해당 helper가 리소스 조회, DB 쓰기, Worker
enqueue, history 기록, provider 호출 전에 동일한 401을 반환한다. 존재하지 않는
`session_id`와 기존 guest `session_id`의 응답 차이로 리소스 존재가 드러나지 않는다.

- 응답은 기존 `auth_error.v1` 계약을 유지하고, `token_invalid` 또는
  `token_expired` 코드와 `guest_credential_missing`, `guest_credential_invalid`,
  `guest_credential_expired`, `guest_credential_guest_mismatch` reason을 사용한다.
- 응답에는 제출한 token, 예상 guest ID, 기존 리소스 존재 여부를 포함하지 않는다.
- credential이 없는 완전한 anonymous 요청을 허용하던 공개 화면은 guest 리소스에
  접근하거나 guest 상태를 생성하지 않는 한 기존 동작을 유지한다.

### E. Google 로그인 결합

Google code 로그인은 Google provider 요청 전에 guest credential을 검증한다.

- 요청이 guest `session_id` 또는 guest 결합용 `guest_id`를 지정했다면 유효한
  credential이 필수다.
- 세션 결합 비교에는 본문의 raw `guest_id`가 아닌 검증된 claim의 guest ID를 쓴다.
- credential claim, 결합 요청, 기존 ChatSession의 guest ID가 하나라도 일치하지
  않으면 현행 `403 google_guest_session_mismatch`를 반환한다.
- 이미 로그인 사용자에게 소유된 세션은 현행
  `403 google_session_already_owned`를 유지한다.
- 어느 거부 경로에서도 Google provider 호출, AuthSession 생성, 리소스 소유권
  변경이 발생하지 않는다. guest 결합을 요청하지 않는 일반 Google 로그인은
  기존대로 동작한다.

### F. 프런트엔드 상태와 전송

- `authSession.js`의 기존 비회원 상태에 `guestCredential`을 추가해 `guest_id`와
  함께 저장·복원·삭제한다. Cookie 전환은 이슈 범위 밖이므로 현행 저장소 정책을
  따른다.
- `apiClient.js`의 request header builder는 `guestCredential`을 받으면
  `X-Guest-Credential`을 추가한다. `guest_id`는 호환성/대상 식별이 필요한 경우에만
  함께 보낸다.
- guest-session bootstrap은 응답의 `guest_credential`을 즉시 저장한다. credential
  오류를 받으면 저장된 guest identity와 session ID를 폐기한 뒤, 사용자가 다시
  시작할 수 있도록 guest-session endpoint만 호출한다.
- Google code 요청에도 verified guest 흐름일 때만 header를 전달한다.
- 개발용 `previewLoggedInUi`는 raw guest ID만으로 보호 API를 호출하는 동작을
  중단한다. 실제 bootstrap credential을 쓰거나 순수 UI preview로 제한한다.

### G. 저장·로그·내부 경계

- credential은 DB metadata, AuthEvent raw payload, history event, worker payload,
  analysis input, request fingerprint, logger에 저장하거나 출력하지 않는다.
- PII/secret masking 키 목록에 `guest_credential` 및 header 표기를 추가한다.
- repository와 worker는 이미 검증되어 주입된 `auth_context`만 소비하며, raw header,
  body, credential을 해석하거나 재검증하지 않는다.
- 기존 `guest_id`와 최소 정책 상태는 소유권 연결을 위해 저장할 수 있으나 credential
  자체는 저장하지 않는다.

## 구현 경계

변경 대상은 다음으로 한정한다.

- `app/services/guest_credential_service.py` 및 `auth_session_service.py`
- `backend/chatbot/views.py`의 identity hydration, guest-session, auth/me,
  chat/files/jobs/history/보고서 접근, Google code 결합 전처리
- `backend/chatbot/repositories.py`의 안전한 session binding
- `app/web/apiClient.js`, `app/web/authSession.js`, `app/web/FrontendAppShell.jsx`
- 관련 API 계약·privacy·Django E2E·프런트 단위 테스트
- `docs/ops/project-readiness-master-checklist.md`의 #256 완료 및 #258 진행 상태

앱 JWT 형식·Google provider 검증·DB schema migration·HttpOnly Cookie·credential
revocation은 변경하지 않는다.

## 검증 계획

### 정상 경로

- guest-session이 서버 생성 guest ID와 credential을 반환하고, 저장한 credential으로
  chat, 파일, job, 이력, report 경로를 사용할 수 있다.
- 정상 credential과 결합한 Google login이 기존 ChatSession과 그 하위 리소스를
  로그인 사용자/Case로 승격한다.

### 거부 경로

- raw `guest_id`만 있는 요청, 다른 guest의 credential, 변조 credential, 만료
  credential, app JWT를 guest credential으로 사용한 요청을 각각 401로 거부한다.
- credential이 없거나 유효하지 않은 guest-session 요청은 새 랜덤 guest ID를
  발급하며, 보낸 `guest_id`와 `session_id`를 재사용하지 않는다.
- Google 결합 거부는 provider mock 호출 0회, AuthSession/ChatSession/리소스
  소유권 변경 0건을 검증한다.
- 다른 guest와 로그인 사용자의 리소스 조회·변경은 기존 소유권 오류 계약을 유지한다.

### 비밀 비노출

- API 응답, history/DB metadata, worker payload, request fingerprint, 운영 로그에서
  실제 guest credential 문자열이 발견되지 않는 회귀 테스트를 추가한다.

## 완료 기준

- 비회원 리소스 신원은 서버 검증한 credential claim에서만 만들어진다.
- raw `guest_id` 단독으로 기존 비회원 세션·리소스·Google 결합을 재개할 수 없다.
- 정상 비회원 → Google 로그인 → Case 승격 흐름과 로그인 사용자 JWT 흐름이 유지된다.
- 새 필드는 호환성 있게 추가되고, 기존 오류·소유권 계약은 필요한 범위에서 유지된다.
- 전체 관련 테스트와 project readiness checklist가 같은 구현 PR에 반영된다.
