# 비회원·로그인 전환 세션 소유권 E2E 검증 설계

## 목적

비회원 상담 세션이 같은 `guest_id`를 제시한 로그인 사용자에게만 연결되고, 사용자가 명시적으로 사건을 생성할 때 세션의 분석 Job·첨부파일·Report가 같은 사용자에게 원자적으로 귀속되는 현재 정책을 API E2E 회귀 테스트로 고정한다.

## 현재 계약

- `POST /api/auth/guest-session/`은 `guest_id`와 `session_id`를 연결한다.
- `POST /api/auth/google/code/`은 저장된 세션의 `guest_id`와 요청 `guest_id`가 다르면 `403 google_guest_session_mismatch`를 반환하고 Google provider 호출 전에 중단한다.
- 이미 `owner_id`가 있는 세션으로 다시 Google 로그인을 시도하면 `403 google_session_already_owned`를 반환하고 provider 호출 전에 중단한다.
- 일치하는 로그인은 `ChatSession.owner_id`와 인증 문맥을 로그인 사용자로 연결한다. 그러나 기존 Job·첨부파일·Report의 영구 귀속을 로그인만으로 일괄 변경하지 않는다.
- 사용자가 인증된 상태에서 사건을 생성하는 `create_case()`는 같은 세션의 Job·첨부파일·Report를 같은 Case와 사용자에게 원자적으로 연결한다.
- 현재 `guest_id`는 별도 서명 credential이나 서버 세션 증명 없이 전달되는 임시 capability다. 타인의 `guest_id` 자체가 유출된 상황까지 식별해 차단하는 보장은 현재 범위에 포함하지 않는다.

## 선택한 접근

단일 Django API E2E 테스트에서 두 guest와 두 로그인 사용자를 만든다. 소유 guest는 실제 `POST /api/auth/guest-session/`, 채팅, 분석 Job, 첨부 메타데이터 경로로 세션 자료를 준비한다. Agent adapter만 결정론적 대역으로 교체하고 실제 `process_agent_work_item()`을 같은 프로세스에서 호출해 Report를 영속화한다. 이 방식은 외부 Worker·LLM을 호출하지 않으면서 실제 Job→Report 영속화 경로를 검증한다. 결정론적 Google code 대역으로 로그인한 뒤, 소유 사용자는 실제 `POST /api/cases/`로 사건을 생성한다. 그 뒤 `ChatSession`, `AnalysisJob`, `UploadedFile`, `Report`, `Case`의 소유자 및 연결이 모두 일치하는지 확인한다.

로그인 직후 소유 사용자는 실제 Job 상세·결과, 첨부파일 상세, Report 상세를 조회하고 저장 상태 변경을 수행한다. 사건 생성 뒤에는 Case workspace도 조회한다. 다른 guest는 자신의 `guest_id`와 소유자의 `session_id`를 넣어 Google 로그인을 시도한다. 이 요청은 provider 호출, AuthSession 생성, 세션·자원 소유권 변경 없이 기존 `403 google_guest_session_mismatch` 계약으로 끝나야 한다. 이미 소유된 세션에 대한 재로그인도 같은 무변경 원칙으로 `403 google_session_already_owned`를 반환해야 한다.

전환 완료 뒤 다른 인증 사용자는 `GET /api/analysis/jobs/{job_id}/`, `GET /api/analysis/results/{job_id}/`, `GET /api/files/{attachment_id}/`, `GET /api/reports/{report_id}/`, `GET /api/cases/{case_id}/workspace/`, `POST /api/chat/save-state/`, `POST /api/cases/`를 요청한다. 조회·저장 상태 변경은 `403 object_access_denied`, Case 생성은 기존 `403 case_owner_mismatch` 계약으로 차단되어야 한다. 각 거부 JSON·헤더·본문에는 소유 사용자·guest 식별자, 첨부 경로, Report 내용, 문서 바이트가 없어야 한다.

외부 Google OAuth, LLM, OCR, S3, 별도 Worker는 호출하지 않는다. Google code 대역과 Django Test DB만 사용하며, 인증·세션 바인딩·권한·Case 영속화는 실제 코드로 실행한다.

## 대안과 선택 이유

### A. 현재 명시적 승격 정책을 E2E로 고정 (선택)

로그인은 세션 인증 연결, 사건 생성은 자료의 영구 귀속이라는 두 단계를 유지한다. 민감 상담 자료의 자동 병합을 피하면서도 사용자는 로그인 뒤 기존 상담을 계속하고, 저장을 확정하면 자신의 Case로 보존할 수 있다.

### B. 로그인 성공 즉시 모든 자료를 자동 승격

사용자 단계는 줄어들지만, `auto_merge: false` 및 사용자 확인 정책을 바꾼다. 이슈 #256의 회귀 테스트 범위를 넘어서는 제품·보안 정책 변경이므로 선택하지 않는다.

### C. 서명된 guest credential 또는 HttpOnly 세션을 새로 도입

유출된 `guest_id` 복사까지 방지할 수 있으나 인증 API·브라우저 저장·세션 수명 정책을 함께 변경해야 한다. 별도 보안 이슈로 분리한다.

## 검증 범위

### A. 정상 전환과 명시적 귀속

- 소유 guest가 자신의 `guest_id`로 세션·Job·첨부파일을 만들고, 결정론적 Agent 대역과 in-process Worker로 Report를 생성한다.
- 동일 `guest_id`를 포함한 Google 로그인은 세션을 로그인 사용자에게 연결한다.
- 로그인 사용자의 사건 생성 뒤 `ChatSession`, `AnalysisJob`, `UploadedFile`, `Report`, `Case`는 같은 `owner_id`와 Case 연결을 가진다.
- 소유 사용자는 전환된 Job 상세·결과, 첨부파일, Report, Case workspace를 조회하고 `POST /api/chat/save-state/`로 상태를 변경할 수 있다.

### B. 다른 guest와 다른 사용자의 차단

- 다른 guest ID로 소유 세션에 Google 로그인을 시도하면 `403 google_guest_session_mismatch`가 반환된다. provider는 호출되지 않고, 새 `AuthSession`은 생기지 않으며 기존 `ChatSession`, `AnalysisJob`, `UploadedFile`, `Report`, `Case`의 수·`owner_id`·연결이 변하지 않는다.
- 이미 소유된 세션의 재로그인은 `403 google_session_already_owned`가 반환된다. provider는 호출되지 않고, 새 `AuthSession` 및 기존 자원 상태가 변하지 않는다.
- 다른 인증 사용자의 Job 상세·결과, 첨부파일, Report, Case workspace, 저장 상태 변경은 `403 object_access_denied`다. 같은 사용자의 Case 생성은 `403 case_owner_mismatch`다. 어떤 거부도 성공 데이터나 민감한 내부 필드를 반환하지 않는다.

### C. 명시적 제한사항

- 이 테스트는 공격자가 자신의 guest ID만 가진 경우의 분리를 검증한다.
- 공격자가 소유자의 `guest_id`를 획득해 그대로 재사용하는 경우를 구분할 서명 credential은 아직 없다. 이 경계는 별도 체크리스트 항목과 후속 보안 이슈로 관리한다.

## 구현 경계

- 새 테스트는 `backend/chatbot/test_guest_login_session_ownership_e2e.py`에 두고, 필요한 fixture helper도 이 파일 안에 정의한다.
- production code는 새 E2E 테스트가 기존 계약 위반을 재현할 때만 그 경계에 최소 수정한다.
- Google OAuth 공급자, JWT 형식, DB 스키마, guest credential 형식, 프론트엔드 로그인 UI는 변경하지 않는다.
- #255 완료와 #256 진행, 후속 guest credential 보안 항목은 `docs/ops/project-readiness-master-checklist.md`에서 이번 구현 PR과 함께 관리한다. 별도 체크리스트 PR은 만들지 않는다.

## 완료 기준

- 정상 전환 뒤 소유 사용자의 Job 상세·결과, 첨부파일, Report 조회와 저장 상태 변경이 통과한다. 사건 생성 뒤 Case workspace 조회가 통과하고 모든 대상 레코드의 소유권·Case 연결이 일관된다.
- guest mismatch와 이미 소유된 세션 재로그인은 provider 미호출 및 모든 대상 모델의 무변경을 유지한다. 다른 인증 사용자의 조회·변경·사건 생성은 각 기존 403 계약을 유지한다.
- 오류 응답에 다른 사용자의 식별자, 첨부 경로, Report 원문, 문서 바이트가 없다.
- 대상 Django 테스트, chatbot 전체 테스트, 루트 pytest, 린트가 통과한다.

## 제외 범위

- 유출된 `guest_id` 재사용까지 방어하는 새 credential 체계
- 실제 Google OAuth·LLM·OCR·S3·외부 Worker 호출
- 인증 provider·JWT·DB 스키마·프론트엔드 로그인 UI 변경
