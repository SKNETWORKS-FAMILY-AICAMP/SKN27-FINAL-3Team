# Pilot 핫픽스 구현·검증·재배포 마스터 체크리스트

> 문서 상태: 실행 중 / G0~G6 로컬 검증 및 runtime RC SHA 고정 완료 / G3·G5 운영 증거 수집 대기
> 최초 작성일: 2026-07-31
> 기준 권고서: `docs/tech-validation-reports/2026-07-31-e2e-cross-analysis-final-hotfix-report.md`
> 대상 HFX: HFX-009 ~ HFX-018
> 최종 범위: 구현, 회귀 테스트, 운영 재배포, 배포 후 13개 E2E, GO/NO-GO 판정
> 구현 기준: `origin/dev` `61e0c56ba8a783423cb8a830e5d7088001e5593b`
> 구현 브랜치: `feat-pilot-safety-hotfix`

## 1. 이 문서의 역할

이 문서는 이번 핫픽스의 단일 진행 기준이다. 작업자는 다음 원칙을 지킨다.

- 작업 상태, 변경 범위, 테스트 결과, 배포 증거는 이 문서에 먼저 반영한다.
- 이 문서에 없는 문제를 발견하면 즉시 구현하지 않고 `변경관리 원장`에 등록한다.
- 단계 종료 조건을 통과하기 전에는 다음 단계로 넘어가지 않는다.
- 코드가 작성됐다는 이유만으로 `완료`로 표시하지 않는다. 관련 테스트와 재현 검증을 모두 통과해야 한다.
- 로컬 테스트 통과와 운영 배포 통과를 구분한다.
- 운영 재배포는 별도 사용자 승인 후 실행한다.
- 개인정보, 인증 소유권, 데이터 보존, 배포·롤백 정책을 임의로 변경하지 않는다.

## 2. UI 핫픽스 동결 해제 기록

### 종료 전 금지 조건 이행

- [x] UI 핫픽스 종료 전 애플리케이션 코드 수정 금지
- [x] UI 핫픽스 종료 전 테스트 코드 수정 금지
- [x] UI 핫픽스 종료 전 신규 브랜치 생성 금지
- [x] UI 핫픽스 종료 전 커밋·push·PR·merge 금지
- [x] UI 핫픽스 종료 전 Vite 또는 운영 image build 금지
- [x] UI 핫픽스 종료 전 staging·운영 배포 금지

### 동결 해제 근거

- [x] E2E 결과·로그·스크린샷·코드 원인 분석
- [x] 최종 권고서 작성
- [x] 마스터 체크리스트 작성
- [x] 사용자의 마스터 체크리스트 검토·승인
- [x] UI 핫픽스 PR `#354`가 `dev`에 병합됨
- [x] UI 핫픽스 merge SHA `61e0c56ba8a783423cb8a830e5d7088001e5593b`
- [x] UI 작업 브랜치에서 프런트 테스트 `43/43` 및 Vite build 성공
- [x] 최신 `dev` 기반 현재 worktree에서 프런트 테스트 `43/43` 및 Vite build 재통과
- [x] 단계별 P0 상세 구현 계획 작성

## 3. 최신 `dev` 재기준화 게이트

현재 분석 SHA는 `691ed6bdd07ca944d0f4e4bf63397f8c21612b91`이지만 실제 구현 기준 SHA로 고정하지 않는다.

UI 핫픽스가 끝나면 반드시 아래 순서로 기준을 다시 잡는다.

- [x] UI 핫픽스가 원격 `dev`에 병합됐음을 PR과 merge SHA로 확인
- [x] 원격 `dev` 최신 상태 fetch
- [x] `origin/dev`의 최신 SHA 기록
- [x] UI 핫픽스가 수정한 파일 목록과 diff 확인
- [x] 현재 권고서의 원인 코드가 최신 `dev`에도 남아 있는지 재검증
- [x] 권고서의 HFX-009~018 각각을 `그대로 재현 / 이미 수정됨 / 구현 위치 변경 / 더 이상 적용 안 됨`으로 분류
- [x] 최신 `dev`에서 관련 기존 테스트를 수정 없이 실행해 baseline 기록
- [x] 최신 `dev`에서 전용 핫픽스 브랜치 생성
- [x] 구현 브랜치명, 기준 SHA, 관련 PR을 이 문서에 기록

### G0 확인 증거

- 기준 SHA: `61e0c56ba8a783423cb8a830e5d7088001e5593b`
- UI PR: `#354` (`feat-compact-chat-composer` → `dev`)
- UI PR 변경 파일:
  - `app/web/FrontendAppShell.jsx`
  - `app/web/consultationLayout.test.js`
  - `app/web/styles.css`
  - 설계·구현 계획 문서 4개
- 구현 브랜치: `feat-pilot-safety-hotfix`
- Python P0 baseline:
  - 명령: `python -m pytest test/test_pii_masking.py test/test_chat_input_privacy.py test/test_service_scope_policy_service.py test/test_public_consultation_routing_service.py test/test_chat_orchestration_service.py -q`
  - 결과: `65 passed`, `1 warning`
- frontend baseline:
  - 명령: `node --test`
  - 결과: `43 passed`, `0 failed`
- build baseline:
  - 최초 결과: worktree 의존성 미설치로 `vite` 실행 파일 없음
  - 조치: 추적된 `package-lock.json` 기준 `npm ci`
  - 재실행: `npm run build`
  - 결과: Vite `7.3.6`, `39 modules transformed`, build 성공
- 기존 의존성 경고:
  - `postcss <=8.5.17`, GHSA `GHSA-r28c-9q8g-f849`, high 1건
  - 자동 `npm audit fix`는 실행하지 않았으며 G7 전 별도 영향·업데이트 검토가 필요하다.

### HFX 최신 `dev` 재분류

| HFX | 최신 상태 | 재검토 근거 |
|---|---|---|
| HFX-009 | 그대로 재현 | service-scope 제외 규칙이 intent/context와 무관하게 `보행자`, `횡단보도`를 적용 |
| HFX-010 | 그대로 재현 | 주민번호·면허번호 regex의 후행 `\b`가 한국어 조사 결합 입력을 놓침 |
| HFX-011 | 그대로 재현 | pre-routing 의미 gate가 없고 `general_consultation` plan이 여전히 law search 실행 |
| HFX-012 | 부분 수정 / 잔여 구현 필요 | PR #351~353에서 OAuth·복구 일부 개선, `startNewConversation()`의 attachment 초기화는 잔존 |
| HFX-013 | 그대로 재현 | run summary 배포 연결과 Caddy credential 제거 작업 미반영 |
| HFX-014 | 그대로 재현 | 고지서 slot gate와 raw law text 출력 제한 미완료 |
| HFX-015 | 구현 위치 일부 변경 / 기능 미완료 | composer UI는 변경됐으나 분류→확인→OCR handoff 계약은 미완료 |
| HFX-016 | 그대로 재현 | same-message `fact_conflicts` 계약 미반영 |
| HFX-017 | 그대로 재현 | polling semantic status·partial/retry UX 계약 미완료 |
| HFX-018 | 그대로 재현 | 배포 후 13개 E2E evidence bundle 규격 미적용 |

### 최신 `dev` 재검토 우선 파일

UI 핫픽스와 충돌 가능성이 높은 파일은 새 기준 SHA에서 먼저 다시 읽는다.

- `app/web/FrontendAppShell.jsx`
- `app/web/authSession.js`
- `app/web/apiClient.js`
- `app/web/styles.css`
- 프런트 관련 `*.test.js`

백엔드·운영 원인 코드도 최신 상태를 다시 확인한다.

- `app/security/pii_masking.py`
- `app/security/chat_input_privacy.py`
- `app/services/supervisor_routing_service.py`
- `app/config/supervisor_routing_policy.v1.json`
- `app/services/service_scope_policy_service.py`
- `app/config/service_scope_policy.v1.json`
- `app/services/chat_orchestration_service.py`
- `app/services/supervisor_control_service.py`
- `app/services/supervisor_llm_contract.py`
- `backend/chatbot/views.py`
- `deploy/aws-pilot/Caddyfile`
- `deploy/aws-pilot/docker-compose.pilot.yml`
- `deploy/aws-pilot/Deploy-Pilot.ps1`
- `backend/chatbot/operational_observability.py`

### 재기준화 종료 조건

- [x] 최신 `origin/dev` SHA가 기록됨
- [x] UI 핫픽스와의 파일 충돌 가능성이 기록됨
- [x] HFX-009~018의 최신 재현 상태가 기록됨
- [x] baseline 테스트 실패가 핫픽스 작업 전 기존 실패인지 구분됨
- [x] 작업 브랜치가 최신 `origin/dev`에서 생성됨

## 4. 작업 상태 정의

| 상태 | 의미 | 상태 변경에 필요한 증거 |
|---|---|---|
| 대기 | 선행 단계가 끝나지 않음 | 선행 조건 목록 |
| 진행 중 | 구현 또는 검증 수행 중 | 담당 범위와 시작 SHA |
| 차단 | 외부 승인·환경·선행 수정 없이는 진행 불가 | 차단 원인과 해제 조건 |
| 구현 완료 | 요구 코드는 작성됐으나 전체 검증 전 | 변경 파일과 좁은 테스트 |
| 검증 완료 | 관련 회귀와 재현 테스트 통과 | 명령, 통과 수, 로그 |
| 배포 완료 | 운영 반영은 됐으나 전체 E2E 전 | release SHA/image digest |
| 최종 완료 | 배포 후 13개 E2E와 운영 게이트 통과 | 최종 evidence bundle |

## 5. 전체 진행 현황

| 단계 | 범위 | 상태 | 진입 조건 | 종료 조건 |
|---|---|---|---|---|
| G0 | UI 핫픽스 종료·최신 dev 재기준화 | 검증 완료 | UI 핫픽스 병합 | 기준 SHA·baseline·브랜치 확정 |
| G1 | P0 개인정보·입력 gate·라우팅 | 검증 완료 | G0 완료 | ID 2·8·10·12 회귀 통과 |
| G2 | 인증·새 상담 상태 | 검증 완료 | G1 완료 | ID 5 기능 재평가 가능, auth 유지 |
| G3 | 운영 모니터·로그·Neo4j | 로컬 구현·검증 완료 / 운영 확인 대기 | G1 완료 | monitor 정상, credential 로그 0 |
| G4 | 고지서·첨부·상충 진술 | 로컬 구현·검증 완료 / 운영 E2E 대기 | G1·G2 완료 | ID 3·4·9·11·13 통과 |
| G5 | polling·부분 실패 UX·증거 규격 | 로컬 구현·검증 완료 / 운영 증거 수집 대기 | G2·G4 완료 | 상태 UX와 캡처 규격 통과 |
| G6 | 전체 로컬·통합 회귀 | 완료 / runtime RC `631e9278` | G1~G5 완료 | 관련 전체 test/build 통과 |
| G7 | 운영 재배포 준비·승인 | 대기 | G6 완료 | 배포 전 체크와 사용자 승인 |
| G8 | 운영 재배포·smoke | 대기 | G7 승인 | 운영 smoke 통과 |
| G9 | 배포 후 13개 E2E·운영 관찰 | 대기 | G8 완료 | 13/13, 즉시 실패 0, monitor 정상 |
| G10 | 최종 GO/NO-GO·인수인계 | 대기 | G9 증거 확보 | 판정·남은 위험·롤백 상태 기록 |

## 6. HFX 실행 원장

| HFX | 우선순위 | 목표 | 대표 E2E | 선행 | 현재 상태 |
|---|---|---|---|---|---|
| HFX-009 | P0 | 의도·서비스 범위 라우팅 정렬 | 2 | G0 | 검증 완료 |
| HFX-010 | P0 | 한국어 문맥 개인정보 차단·로그 credential 제거 | 8 | G0 | 앱 경계 검증 완료 / Caddy는 G3 대기 |
| HFX-011 | P0 | 저정보·욕설-only·해석 불가 입력 gate | 10, 12 | G0 | 검증 완료 |
| HFX-012 | P0 | 인증 session 복구·새 상담 상태 원자화 | 5 | G1 | 로컬 검증 완료 / 배포 E2E 대기 |
| HFX-013 | P0 | run summary 배포·monitor·Neo4j 정상화 | 운영 | G1 | 로컬 구현·검증 완료 / 운영 확인 대기 |
| HFX-014 | P1 | 고지서 intake slot·안전한 법령 응답 | 3, 9, 11 | G1 | 로컬 구현·검증 완료 / 운영 E2E 대기 |
| HFX-015 | P1 | 첨부 분류→확인→OCR→분석 handoff | 4, 5 | G2, HFX-014 | 로컬 구현·검증 완료 / 운영 E2E 대기 |
| HFX-016 | P1 | 상충 진술 계약·반복 질문 제거 | 13 | G1 | 로컬 구현·검증 완료 / 운영 E2E 대기 |
| HFX-017 | P1 | polling timeout·partial·retry UX | 10, 11 | G2, G4 | 로컬 구현·검증 완료 / 운영 E2E 대기 |
| HFX-018 | P1 | E2E 증거 캡처·correlation 규격 | 전체 | G4 | bundle 계약 검증 완료 / G9 실제 증거 수집 대기 |

## 7. G1 — P0 개인정보·입력 gate·라우팅

### HFX-010 개인정보 차단

#### 구현 범위

- [x] 주민번호 pattern의 word boundary를 digit boundary로 교체
- [x] 운전면허번호 pattern의 word boundary를 digit boundary로 교체
- [x] 한국어 조사·괄호·공백·문장부호 변형 지원
- [x] 입력 원문이 history, Agent payload, RAG query, 운영 로그로 전달되지 않는지 확인
- [x] 차단 응답이 원문 번호를 포함하지 않는지 확인
- [x] 프런트 대화 목록에 민감 원문이 영구 상태로 남지 않도록 처리
- [ ] Caddy credential 로그 제거는 G3 운영 항목과 함께 완료

#### 관련 파일 후보

- `app/security/pii_masking.py`
- `app/security/chat_input_privacy.py`
- `backend/chatbot/views.py`
- `app/web/FrontendAppShell.jsx`
- `test/test_pii_masking.py`
- `test/test_chat_input_privacy.py`
- `test/test_chat_session_contract.py`

#### 필수 테스트

- [x] `900101-1234567이고` 차단
- [x] `900101-1234567입니다` 차단
- [x] `(900101-1234567)` 차단
- [x] `11-22-333333-44입니다` 차단
- [x] 번호 앞뒤에 숫자가 더 붙은 오탐 방지
- [x] 차단 metadata에 category와 개수만 존재
- [x] ID 8 exact input에서 Agent invocation 0회

### HFX-011 입력 이해도 gate

#### 구현 범위

- [x] Agent routing 전 `input_understanding_gate.v1` 적용
- [x] 결과 상태를 `accepted`, `needs_clarification`, `blocked_sensitive`, `out_of_scope`로 제한
- [x] 욕설-only 입력은 중립적 재질문으로 동기 종료
- [x] 초성-only·의미 토큰 부족 입력은 추측 없이 재입력 요청
- [x] 의도가 함께 있는 욕설 입력은 욕설을 제거한 뒤 상담 intent 유지
- [x] `needs_clarification` 입력에서 Worker·RAG job을 만들지 않음
- [x] usage 차감 정책이 기존 `needs_input` 제품 정책과 일치하는지 확인

#### 관련 파일 후보

- 새 전용 service 파일 또는 최신 `dev`의 기존 입력 정책 service
- `app/services/chat_orchestration_service.py`
- `app/services/supervisor_control_service.py`
- `backend/chatbot/views.py`
- 관련 backend·frontend contract tests

#### 필수 테스트

- [x] ID 9는 `fine_notice_procedure`
- [x] ID 10은 `needs_clarification`, Agent invocation 0회
- [x] ID 11은 `fine_notice_procedure`
- [x] ID 12는 `needs_clarification`, Agent invocation 0회
- [x] 욕설을 assistant answer에서 반복하지 않음

### HFX-009 intent-aware 라우팅

#### 구현 범위

- [x] 지원 intent 판정 후 서비스 범위 policy 적용
- [x] 일반 법령 질문에는 보행자 사고 제외 규칙을 적용하지 않음
- [x] `보행자/횡단보도` 제외는 사고·충돌·접촉·과실 문맥일 때만 적용
- [x] `general_consultation`이 무조건 law search를 실행하지 않도록 plan 수정
- [x] 범위 불명 입력은 clarification에서 종료

#### 관련 파일 후보

- `app/services/supervisor_routing_service.py`
- `app/config/supervisor_routing_policy.v1.json`
- `app/services/service_scope_policy_service.py`
- `app/config/service_scope_policy.v1.json`
- `app/services/chat_orchestration_service.py`
- `test/test_public_consultation_routing_service.py`
- `test/test_service_scope_policy_service.py`
- `test/test_chat_orchestration_service.py`

#### 필수 테스트

- [x] ID 2 → `traffic_law_search`
- [x] ID 2에 expert handoff가 없음
- [x] 실제 보행자 충돌 사고 및 `쳤습니다` 동의어 → expert handoff 유지
- [x] 기존 고위험 ID 7 → 과실 산정 차단 유지
- [x] 일반 질문·초성-only → 자동 law search 없음

### G1 종료 조건

- [x] ID 2·8·10·12 exact-input 테스트 통과
- [x] ID 7·9·11 안전 회귀 통과
- [x] 개인정보가 API 응답·DB·Agent input·로그에 없음
- [x] 좁은 테스트와 관련 계약 테스트 통과
- [x] 변경 범위 review 완료

### G1 최종 검증 증거

- Python P0·privacy·routing·Supervisor:
  - 명령: `python -m pytest`로 관련 13개 test module 실행
  - 결과: `179 passed`, `1 existing LangChainPendingDeprecationWarning`
- Django Production API·operational log privacy:
  - 명령: `python backend/manage.py test chatbot.test_production_hardening.ProductionApiContractTests chatbot.test_operational_log_privacy --verbosity 1`
  - 결과: `34 tests`, `OK`
  - 테스트용 강제 persistence 예외 로그 1건은 의도된 failure-path fixture이며 suite는 통과
- frontend:
  - 명령: `node --test`
  - 결과: `45 passed`, `0 failed`
- production build:
  - 명령: `npm run build`
  - 결과: Vite `7.3.6`, `40 modules transformed`, 성공
- diff:
  - `git diff --check`: 오류 없음
  - 변경 범위: HFX-009~011 production/test와 승인 문서만 포함

## 8. G2 — 인증·새 상담 상태

### HFX-012 구현 범위

- [x] 앱 시작 시 저장 token이 있으면 `/auth/me`로 서버 상태 검증
- [x] access token refresh와 session/resource 오류를 구분
- [x] 인증 상태에서는 guest bootstrap을 호출하지 않음
- [x] Google code 403을 안전한 reason code로 분류
- [x] 인증 오류가 기존 상담·첨부·사용자 소유권을 잘못 폐기하지 않음
- [x] 새 상담은 서버에서 새 session ID를 발급받은 뒤 활성화
- [x] 새 상담에서 chat, intake, report, OCR, pending auth action 초기화
- [x] 새 상담에서 `registeredAttachments`를 0개로 초기화
- [x] 새 상담 후에도 authenticated user는 유지
- [x] 다른 사용자의 session/report 접근 차단 유지

### 필수 사용자 흐름

- [x] guest 상담 → Google 로그인 → 동일 상담 소유권 연결
- [x] 로그인 → 새로고침 → `/auth/me` → 로그인 유지
- [x] 로그인 → 새 상담 → auth 유지 + 새 session
- [x] 로그인 → 첨부 → 새 상담 → 이전 첨부 0개
- [x] access token 만료 임박 → 선제 refresh 성공 → 동일 사용자 유지
- [x] 이미 만료·무효·revoked 또는 refresh 실패 → 안전 안내, 기존 상담 보존, 소유권 혼합 없음
- [x] ID 5 → 인증 유지·첨부 진입 계약 통과. 초안 생성 전체 흐름은 HFX-015/G4와 배포 E2E에서 계속 검증

### G2 종료 조건

- [x] ID 5의 인증 미평가 원인을 제거하고 로컬 인증·첨부 진입 계약으로 재평가 가능
- [x] guest/auth/session/attachment lifecycle 계약 테스트 통과
- [x] resource ownership E2E 통과
- [x] UI 핫픽스 merge SHA 기반 충돌 resolution review 완료

### G2 최종 검증 증거

- 기준:
  - P0/G1 사용자 커밋: `9db7ccb50f5d9961597bb551846cbfc677723db6`
  - 상세 계획: `docs/superpowers/plans/2026-07-31-auth-new-conversation-state-hotfix.md`
- frontend auth/new-conversation 집중 검증:
  - `app/web/authSession.test.js`: 저장 JWT `/auth/me` 검증, 만료 임박 선제 refresh, refresh 실패 시 guest/session 보존, auth-session 불일치 차단
  - `app/web/newConversationState.test.js`: 새 session 발급, 누락·동일 ID 거부, conversation-owned state fresh reset
  - `test/test_frontend_auth_session_contract.py`: startup 검증, guest bootstrap 차단, 세션 gate 실패 시 요청 중단, 새 상담 전체 초기화
- frontend 전체:
  - 명령: `node --test app/web/*.test.js`
  - 결과: `52 passed`, `0 failed`
- Python P0·인증 통합:
  - 명령: G1 안전 경계와 G2 인증 관련 14개 test module을 `python -m pytest ... -q`로 실행
  - 결과: `175 passed`, `1 existing LangChainPendingDeprecationWarning`
- Django 인증·소유권·P0 API:
  - 명령: `python backend/manage.py test chatbot.test_production_hardening chatbot.test_security_hardening.AuthSessionRotationSecurityTests chatbot.test_guest_credential_boundary chatbot.test_report_api_contract chatbot.test_resource_ownership_e2e chatbot.test_guest_login_session_ownership_e2e chatbot.test_operational_log_privacy --verbosity 1`
  - 결과: `71 tests`, `OK`
  - 테스트용 queue persistence 예외 및 provider key 부재 안내는 의도된 fixture/fallback 로그이며 실패가 아님
- production build:
  - 올바른 작업 디렉터리: `app/web`
  - 명령: `npm run build`
  - 결과: Vite `7.3.6`, `41 modules transformed`, 성공
  - 저장소 루트에서의 최초 `npm run build`는 `package.json` 부재로 ENOENT였으며 코드·번들 오류가 아님
- diff:
  - `git diff --check`: 오류 없음
  - 변경 범위: HFX-012 프런트 production/test와 승인 계획·체크리스트
- 저장소 전체 Python suite:
  - 명령: `python -m pytest -q`
  - 최초 결과: `1316 passed`, `37 skipped`, `4 subtests passed`, `2 failed`, `1 existing warning`
  - 최초 실패 2건은 `test_consultation_v2_contract.py`의 삭제된 persistent Vision/OCR 안내 문구 단정과 `test_ui_v3_frontend_contract.py`의 quick examples 구형 위치 단정
  - 사용자 커밋 `9db7ccb5`의 `FrontendAppShell.jsx`에서도 동일하게 실패하는 기존 불일치이며 이번 G2 diff는 해당 문구·레이아웃 구간을 수정하지 않음
  - 최신 `app/web/consultationLayout.test.js`는 반대로 persistent instruction 부재와 empty-state 내부 quick examples를 명시하며 통과
  - 사용자 승인 후 production UI는 유지하고 구형 Python 계약 2건만 최신 Node/UI 계약에 맞춰 정렬
  - 최종 결과: `1318 passed`, `37 skipped`, `4 subtests passed`, `0 failed`, `1 existing warning`
- 남은 검증:
  - 실제 Google Console·운영 브라우저의 reload/login/new-chat는 G8 smoke와 G9 ID 5에서 재검증
  - 첨부→분류→OCR→초안 생성의 후반부는 HFX-015/G4 범위

## 9. G3 — 운영 모니터·로그·Neo4j

### HFX-013 run summary·monitor

- [x] 법령 적재 후 검증된 `run_summary.json` 생성
- [x] release 디렉터리에서 operational evidence 경로로 원자 복사
- [x] ops-monitor 시작 전 file 존재·JSON schema·freshness 검사
- [x] stale/missing/invalid이면 배포 precheck 실패
- [x] monitor가 legal dataset version과 release SHA를 안전하게 연결
- [x] 정상 증적에서 `legal_data.status=success`, 전체 snapshot `status=pass|warn` 계약 검증

로컬 구현 증거:

- `app/services/legal_operational_evidence.py`는 manifest 검증을 통과한
  `legal_chunks`의 식별자·개수·날짜만 사용하며 법령 본문과 embedding을
  증적에 포함하지 않는다.
- `build_legal_operational_evidence` management command는
  `LEGAL_DATASET_VERSION`, `APP_RELEASE_VERSION`, timezone-aware 검증 시각을
  `legal_ingestion_run_summary.v2`에 결합한다.
- `Load-Rag-Seed-Pilot.ps1`은 graph/PGVector/readiness/smoke 통과 후 release
  전용 임시 summary를 생성·검증·`0444` 설정·원자 rename하고 나서만
  `.production-rag-seed.complete`를 기록한다.
- `Deploy-Pilot.ps1`은 cutover 전에 release summary를 검증하고, shared
  evidence를 임시 파일로 설치·재검증·원자 rename한다. one-shot monitor의
  dataset/release 일치를 확인한 뒤에만 loop `ops-monitor`를 시작하며
  rollback은 이전 release 증적을 복원한다.

### Caddy credential 로그

- [x] access log에서 request header 객체 전체 제거
- [x] `Authorization` 기록 금지
- [x] `Cookie` 기록 금지
- [x] `X-Guest-Credential` 기록 금지
- [ ] 기존 노출 guest credential 폐기
- [ ] 기존 로그 접근자·보존·복제 범위 확인
- [x] 로그 redaction 회귀 테스트 추가

로컬 구현 증거:

- `deploy/aws-pilot/Caddyfile`의 `format filter`가
  `request>headers delete` 후 JSON으로 인코딩한다. reverse proxy의 인증
  header 전달 계약은 변경하지 않았다.
- `docs/ops/caddy-credential-log-incident-runbook.md`에 SSM
  `APP_JWT_SECRET` 회전, backend 계열 서비스 재생성, 기존 app/guest
  credential `401`, local/CloudWatch/backup/replication 범위 조사,
  승인된 purge와 credential canary zero-match 절차를 분리했다.
- 실제 secret 회전과 로그 삭제는 파괴적 운영 작업이므로 G7/G8 승인 전
  실행하지 않았다.

### Neo4j readiness

- [x] seed/load 코드의 graph snapshot schema와 temporal index 계약 확인
- [x] `expire_date` property 계약과 seed 결과 정렬
- [ ] 대표 law query에서 property 경고 0건 확인
- [x] graph 결과가 없을 때 안전 fallback 확인
- [x] 신규 RAG/graph 설계 반영 여부와 이번 핫픽스 범위 구분

로컬 구현 증거:

- `LawVersion`과 `LawChunk`에
  `(enforce_date, expire_date)` idempotent index를 추가했다.
- readiness는 모든 version/chunk의 `enforce_date`, historical
  version/chunk의 `expire_date`를 집계로 검증한다. active
  `expire_date=null`은 정상이다.
- 오류는 `law_version_temporal_metadata_invalid` 또는
  `law_chunk_temporal_metadata_invalid`의 고정 코드만 반환한다.
- Neo4j session이 없을 때 안전한 partial/empty 결과를 반환하고
  `--require-results`에서는 실패하는 기존 fallback 2건을 재검증했다.
- 신규 그래프 재설계나 backfill은 하지 않았고, 이번 범위는 기존
  immutable seed의 property/index/readiness 계약 강화로 제한했다.

### G3 로컬 검증 증거

- G3 비-Django 집중:
  - 명령: 법령 증적·요약 validation·AWS pilot·배포 문서·Neo4j command의
    6개 test module을 `python -m pytest ... -q`로 실행
  - 결과: `127 passed`, `0 failed`
- G3 Django 집중:
  - 명령: operational observability/privacy와 Neo4j unavailable
    fallback을 `python backend/manage.py test ... --verbosity 1`로 실행
  - 결과: `19 tests`, `OK`
- 전체 Python:
  - 명령: `python -m pytest -q`
  - 결과: `1335 passed`, `37 skipped`, `4 subtests passed`,
    `0 failed`, `1 existing LangChainPendingDeprecationWarning`
- frontend 전체:
  - 명령: `node --test app/web/*.test.js`
  - 결과: `52 passed`, `0 failed`
- production build:
  - 작업 디렉터리: `app/web`
  - 명령: `npm run build`
  - 결과: Vite `7.3.6`, `41 modules transformed`, 성공
- 배포 스크립트:
  - `Load-Rag-Seed-Pilot.ps1`, `Deploy-Pilot.ps1` PowerShell AST parse 성공
  - 실제 SSM·AWS·Docker 배포 명령은 실행하지 않음
- Caddy:
  - 구성·privacy 정적 계약 테스트 통과
  - 로컬 호스트에 `caddy` binary와 `caddy:2.11.4-alpine` image가 없어
    native `caddy validate`는 실행하지 않음. G8에서 고정 image의 실제
    container 시작과 credential canary zero-match로 확인

### G3 종료 조건

- [ ] 운영과 동형인 환경에서 monitor 10분 연속 정상
- [ ] credential 원문 로그 0건
- [ ] Neo4j 대표 질의 경고 0건 또는 승인된 비차단 warning 문서화
- [ ] 배포 precheck가 잘못된 run summary를 실제로 차단

위 네 항목은 로컬 정적/회귀 검증으로 완료 처리하지 않는다. G7 승인 후
G8 재배포와 G9 13개 E2E·운영 관찰에서 실제 증거를 수집해야 G3를 최종
완료로 전환한다.

## 10. G4 — 고지서·첨부·상충 진술

### HFX-014 고지서 intake

- [x] 필수 slot을 문서명/처분 유형, 발급기관, 기한, 첨부 여부로 고정
- [x] 법령 검색 성공 여부와 무관하게 미충족 slot 질문
- [x] ID 3에서 문서명·발급기관·기한·사진 요청
- [x] ID 9에서 욕설 제거 후 동일 intake 유지
- [x] ID 11에서 오타를 허용하되 사실을 추측하지 않음
- [x] raw `provision_text`·깨진 OCR/RAG chunk 직접 노출 금지
- [x] 법령명·조문·검증된 짧은 요약만 표시

### HFX-015 첨부 handoff

- [x] scan
- [x] classification
- [x] classification 사용자 확인
- [x] OCR
- [x] OCR field 사용자 확인
- [x] fine notice analysis
- [x] 확인 정보·누락 정보·근거·한계 병합
- [x] appeal/report gate
- [x] 각 상태를 사용자에게 구분해 표시
- [x] partial/failed에서 다음 행동과 retry 제공
- [x] 실제 고지서와 닮은 합성 fixture 사용

### HFX-016 상충 진술·반복 질문

- [x] Supervisor 계약에 `fact_conflicts` 추가
- [x] same-message conflict 보존
- [x] `signal_priority` 충돌을 사용자에게 명시
- [x] 충돌 field만 재질문
- [x] 이미 수집된 `vehicle_actions` 재질문 금지
- [x] 사실 카드 source와 confidence 유지
- [x] ID 13 exact input에서 과실 숫자 0건

### G4 종료 조건

- [x] ID 3·4·9·11·13 로컬 계약·오케스트레이션 통과
- [x] ID 6·7 안전 회귀 통과
- [x] 첨부 상태별 API·UI contract 통과
- [x] raw OCR·private storage path·PII 노출 0건

### G4 로컬 구현·검증 증적

- 기준: `HEAD dfd12f4e` 위 미커밋 G4 작업 트리
- 구현 계획:
  - `docs/superpowers/plans/2026-07-31-g4-consultation-contract-hotfix.md`
  - `docs/superpowers/specs/2026-07-31-g4-fine-notice-attachment-conflict-design.md`
- 전체 Python:
  - 명령: `python -m pytest -q`
  - 결과: `1388 passed`, `37 skipped`, `4 subtests passed`, `0 failed`
  - 경고: 기존 `LangChainPendingDeprecationWarning` 1건
- frontend 전체:
  - 명령: 확인된 `app/web/*.test.js` 10개를 `node --test`로 실행
  - 결과: `57 passed`, `0 failed`
- Django 첨부 분류 확인 API:
  - 명령:
    `python backend/manage.py test chatbot.test_attachment_classification_confirmation_flow --verbosity 1`
  - 결과: `4 tests`, `OK`
- production build:
  - 작업 디렉터리: `app/web`
  - 명령: `npm run build`
  - 결과: Vite `7.3.6`, `42 modules transformed`, 성공
- 추가 집중 검증:
  - 부분 응답·대기 조회·저장 복원 교차검토: `73 passed`, `0 failed`
  - G4-C 충돌 계약: `119 passed`, `0 failed`
  - G4-B 합성 fixture·UI·오케스트레이션: `56 passed`, `0 failed`
  - 첨부 상태 머신·저장 복원·입력 제어: `92 passed`, `0 failed`
- 범위 확인:
  - `UploadedFileStatus`, model, migration, generic polling loop, paid-call retry
    정책은 변경하지 않음
  - 실제 운영 배포 및 배포 후 13개 E2E는 G7 승인 후 G8·G9에서 별도 수행

## 11. G5 — polling·부분 실패 UX·증거 규격

### HFX-017

- [x] Worker `success`와 사용자 과업 성공을 분리
- [x] 장기 polling에서 일반 “접수” 문구로 결과를 덮지 않음
- [x] `queued`, `running`, `partial`, `failed`, `needs_input`, `success` 구분
- [x] polling 중 `queued` → `running` → terminal 상태를 화면에 실시간 반영
- [x] retry 가능 여부 표시
- [x] job/correlation ID를 개발자 진단에 연결
- [x] 화면에는 안전한 사용자 문구만 표시
- [x] backend 재기동 후 polling continuity 검증

### HFX-018

각 E2E evidence bundle은 다음을 포함한다.

- [x] release SHA — bundle 필수 계약 검증 완료, 실제 값은 G9에서 수집
- [x] frontend/backend image digest — bundle 필수 계약 검증 완료, 실제 값은 G9에서 수집
- [x] 테스트 ID와 exact input — bundle 필수 계약 검증 완료
- [x] 입력·최종 응답이 함께 보이는 스크린샷 — 안전한 상대 artifact 이름 계약 완료, 실제 촬영은 G9
- [x] HTTP status와 안전한 public response — allowlist·privacy 계약 완료
- [x] routing intent
- [x] node list
- [x] semantic status
- [x] job/correlation ID
- [x] credential·PII를 제거한 로그 — masking·unsafe rejection 계약 완료
- [x] 실행 시각과 테스트 계정 유형

재촬영 필수 기존 증거:

- [ ] ID 2
- [ ] ID 4 비회원
- [ ] ID 4 인증 사용자
- [ ] ID 5
- [ ] ID 10
- [ ] ID 11
- [ ] ID 13

### G5 로컬 구현·검증 증적

- 기준: `HEAD fe80bc93` 위 미커밋 G5 작업 트리
- 설계·구현 계획:
  - `docs/superpowers/specs/2026-07-31-g5-polling-evidence-design.md`
  - `docs/superpowers/plans/2026-07-31-g5-polling-evidence-hotfix.md`
- G5 집중 Python:
  - 명령: semantic progress·analysis query·evidence bundle·frontend source
    contract 5개 module을 `python -m pytest ... -q`로 실행
  - 결과: `114 passed`, `0 failed`
- G5·인접 frontend:
  - 명령: progress/polling·auth·attachment·new conversation 5개 Node test
    module 실행
  - 결과: `26 passed`, `0 failed`
- Django worker·continuity·paid retry 경계:
  - 명령:
    `python backend/manage.py test chatbot.test_production_hardening chatbot.test_supervisor_reporting_pipeline --verbosity 1`
  - 결과: `71 tests`, `OK`
- 인접 개인정보·오케스트레이션·첨부·인증:
  - 결과: `106 passed`, `0 failed`
  - 경고: 기존 `LangChainPendingDeprecationWarning` 1건
- 전체 Python:
  - 명령: `python -m pytest -q`
  - 결과: `1449 passed`, `37 skipped`, `4 subtests passed`, `0 failed`
  - 경고: 기존 `LangChainPendingDeprecationWarning` 1건
- frontend 전체:
  - 명령: 확인된 `app/web/*.test.js` 12개를 `node --test`로 실행
  - 결과: `66 passed`, `0 failed`
- production build:
  - 작업 디렉터리: `app/web`
  - 명령: `npm run build`
  - 결과: Vite `7.3.6`, `44 modules transformed`, 성공
- 범위 확인:
  - model·migration·worker lease·retry backoff·requeue API·paid Agent replay를
    변경하지 않음
  - 실제 release SHA·image digest·스크린샷·운영 로그·13개 E2E는 G8·G9에서
    수집하며, G5 로컬 완료가 운영 증거 확보를 의미하지 않음

## 12. G6 — 전체 회귀 검증

실제 명령은 UI 핫픽스 병합 후 최신 `dev`의 의존성·테스트 구성을 다시 확인하고 단계별 구현 계획에 고정한다.

### 테스트 순서

- [x] 변경 단위별 가장 좁은 테스트
- [x] PII·입력 gate·라우팅 계약 테스트
- [x] auth/session/ownership 테스트
- [x] fine notice·attachment·Supervisor 테스트
- [x] 운영 설정·배포 계약 테스트
- [x] 전체 프런트 node test
- [x] 관련 Python 계약 테스트
- [x] Django 통합 E2E
- [x] Agent·RAG·graph 회귀
- [x] Vite production build
- [x] docker compose config validation

### G6 로컬 검증 증거

- 상세 증거:
  `docs/tech-validation-reports/2026-07-31-g6-full-regression-evidence.md`
- runtime RC SHA:
  `631e927833a7bfead2ae5efcd318bdac99212b8a`
- 전체 pytest: `1450 passed`, `37 skipped`, `4 subtests passed`, 실패 0
- Django chatbot 전체 discovery: `383 tests`, `OK`
- frontend Node: `66 passed`, 실패 0
- Vite production build: `44 modules transformed`, 성공
- local·pilot Compose: `config --quiet` 성공
- 신규 warning 없음. 기존 `LangChainPendingDeprecationWarning` 1건 유지
- DISC-003·DISC-004 해결 후 focused·전체 회귀 재검증 완료

### 검증 기록

각 명령에 다음을 기록한다.

- 실행 SHA
- 명령
- 시작·종료 시각
- 통과·실패·skip 수
- 경고
- 실패 로그 위치
- 재실행 결과

### G6 종료 조건

- [x] 관련 전체 테스트 0 failure
- [x] production build 성공
- [x] compose/config 검증 성공
- [x] 새 warning은 영향 분석과 승인 기록 — 신규 warning 없음, 기존 LangChain warning 1건
- [x] 변경 파일 전체 review 완료
- [x] 배포 전 release candidate SHA 고정 — `631e927833a7bfead2ae5efcd318bdac99212b8a`

## 13. G7 — 운영 재배포 준비·승인

### 배포 전 체크

- [ ] UI 핫픽스를 포함한 최신 `dev` 기반 확인
- [ ] 승인된 PR만 포함
- [ ] release candidate SHA 기록
- [ ] immutable frontend/backend image digest 기록
- [ ] DB migration 목록 확인
- [ ] data seed·run summary 확인
- [ ] 최신 법령 source dry-run과 기존 97,394개 embedding 재사용 대조 완료
- [ ] `dataset_version`·`plan_sha256`·reused/changed/new/removed/pending 기록
- [ ] pending이 있으면 exact plan 비용 승인, 없으면 provider 무호출 증거 기록
- [ ] 새 manifest 이중 검증과 immutable `_rag-seed/<manifest-sha256>/` 업로드 확인
- [ ] secret·환경 변수 존재 여부만 확인하고 값은 기록하지 않음
- [ ] rollback 대상 이전 release SHA/digest 기록
- [ ] 운영 비용 발생 provider 실행 범위 확인
- [ ] 배포 시간과 관찰 담당 확인
- [ ] 사용자에게 운영 배포 승인 요청

### operational evidence/app-release hold point

로컬 구현·계약 테스트 완료는 아래 운영 작업의 실행 완료를 의미하지 않는다.
현재 운영 복구 입력(S3 URI, manifest 상대 경로, manifest SHA-256)과 실제 AWS
변경 명령은 실행 직전에 별도 승인한다.

- [ ] 기존 stale seed로 evidence-only 복구를 반복하지 않음
- [ ] 새 dataset version·verified time·manifest SHA로 candidate update stage
- [ ] `Load-Rag-Seed-Pilot.ps1` 성공 및 descriptor·release evidence 생성
- [ ] candidate promotion transaction gate 및 600초 연속 acceptance 통과
- [ ] 성공 후 후속 app-release pipeline 승인 재개
- [ ] G8 운영 재배포·smoke 완료
- [ ] 배포 후 13개 E2E 13/13 통과

`Recover-PilotOperationalEvidence.ps1`과
`Confirm-PilotOperationalAcceptance.ps1`은 provider·seed loader를 실행하지
않는다. immutable seed 검증 실패 시 자동 재적재하지 않고, 유료/전체 seed
작업이 필요한 경우 정확한 범위로 별도 승인받는다.

로컬 구현 검증 증거(2026-07-31):

- [x] 공통 transaction/acceptance gate와 Django command 계약 — 집중 pytest
  `130 passed`, Django `16 passed`
- [x] AWS 파일럿 배포·복구·수동 롤백·watcher 계약 — `89 passed`
- [x] CodeBuild app-release 계약 — `14 passed`
- [x] 전체 Python 회귀 — `1473 passed`, `37 skipped`, 기존 LangChain warning 1건
- [x] 프런트 Node 회귀 — `node --test *.test.js`, `66 passed`
- [x] Vite production build — 성공
- [x] 전체 AWS PowerShell parser, app-release/watcher 원격 Bash 문법,
  Terraform `fmt -check -recursive`, 금지된 유료·loader 문자열 0건
- [ ] Terraform `validate` — 로컬 `.terraform/providers`에
  `archive 2.8.0`, `aws 6.54.0`, `random 3.9.0` package가 없어 실행 차단.
  구성 변경이나 임의 provider 다운로드 없이 G7 환경 검증으로 이관

### 배포 중단 조건

- precheck 실패
- migration 계획과 실제 schema 불일치
- run summary 누락·stale·invalid
- image SHA 불일치
- secret/credential 노출 가능성
- rollback release 미확보

## 14. G8 — 운영 재배포·smoke

- [ ] 승인된 release 배포
- [ ] 컨테이너/서비스 상태 확인
- [ ] backend live/ready 확인
- [ ] frontend 로딩 확인
- [ ] guest session 생성 확인
- [ ] 로그인 시작 경계 확인
- [ ] 빈 입력 확인
- [ ] PII 차단 smoke
- [ ] 일반 법령 routing smoke
- [ ] Worker queue/result smoke
- [ ] report/mypage ownership smoke
- [ ] Caddy log credential 비기록 확인
- [ ] operational health 정상 확인

### 즉시 롤백 조건

- 개인정보 또는 credential 원문 로그
- 인증 소유권 혼합·타 사용자 접근
- migration/DB 장애
- 핵심 API 지속 5xx
- monitor critical
- ID 8·12·13 즉시 실패 조건 재발
- UI가 주요 상담 입력을 막는 회귀

## 15. G9 — 배포 후 13개 E2E

| ID | 핵심 성공 기준 | 배포 후 상태 | 증거 |
|---|---|---|---|
| 1 | 빈 입력 분석 미시작 | 대기 | 미수집 |
| 2 | 일반 법령 근거·한계, 사고 오분류 없음 | 대기 | 미수집 |
| 3 | 고지서 필수정보·사진 요청 | 대기 | 미수집 |
| 4 | 확인·누락·근거·한계 구분 | 대기 | 미수집 |
| 5 | 인증 유지·첨부 기반 초안 gate | 대기 | 미수집 |
| 6 | 네 필수 사고 항목 질문, 과실 숫자 없음 | 대기 | 미수집 |
| 7 | 긴급조치·증거보존·전문가 이관 | 대기 | 미수집 |
| 8 | 민감정보 차단, 원문 재노출 없음 | 대기 | 미수집 |
| 9 | 욕설 미반복·고지서 정보 요청 | 대기 | 미수집 |
| 10 | 중립적 clarification, Agent 미실행 | 대기 | 미수집 |
| 11 | 오타 의도 인식·필수정보 요청 | 대기 | 미수집 |
| 12 | 임의 해석 없음·재입력 요청 | 대기 | 미수집 |
| 13 | 충돌 명시·중복 질문 없음·과실 숫자 없음 | 대기 | 미수집 |

### 운영 관찰

- [ ] 13개 테스트 중 즉시 실패 0건
- [ ] 13/13 통과
- [ ] ID 5 미평가 해소
- [ ] CloudWatch operational health 10분 연속 정상
- [ ] credential 로그 0건
- [ ] browser console error/warn 검토
- [ ] 5xx·Worker timeout·partial 비율 검토
- [ ] 모든 evidence bundle 개인정보 제거 확인

## 16. G10 — 최종 GO/NO-GO

### GO 조건

- [ ] 13개 E2E 전부 통과
- [ ] 즉시 실패 조건 0건
- [ ] 개인정보·credential 노출 0건
- [ ] 인증·resource ownership 통과
- [ ] monitor 10분 연속 정상
- [ ] Neo4j·RAG readiness 통과
- [ ] 모든 증거가 동일 release SHA/digest를 가리킴
- [ ] 롤백이 필요하지 않음

### NO-GO 조건

다음 중 하나라도 해당하면 NO-GO다.

- E2E 실패 1건 이상
- ID 5 미평가 상태 유지
- 즉시 실패 조건 1건 이상
- credential 또는 개인정보 원문 노출
- 인증 소유권 오류
- monitor critical
- 증거 SHA 불일치
- 핵심 흐름의 기능 판정 불가

### 최종 기록

- [ ] GO/NO-GO 판정
- [ ] 판정 시각
- [ ] release SHA와 image digest
- [ ] 배포 결과
- [ ] E2E 결과
- [ ] 남은 비차단 위험
- [ ] 후속 backlog
- [ ] 롤백 여부
- [ ] 다음 담당자 행동

## 17. 변경관리 원장

작업 중 새 문제가 발견되면 아래 표에 먼저 등록한다.

| 발견 ID | 발견 단계 | 증상 | 기존 HFX 포함 여부 | 위험도 | 이번 핫픽스 포함 결정 | 근거 |
|---|---|---|---|---|---|---|
| DISC-001 | G0 | `postcss <=8.5.17` path traversal advisory | 기존 HFX 외 | high advisory | G7 전 영향 확인 후 별도 lockfile 업데이트 여부 결정 | `npm audit --json`, GHSA-r28c-9q8g-f849 |
| DISC-002 | G2 종료 검증 | UI PR #354의 최신 Node 계약과 과거 Python source-contract 2건이 상충하여 전체 `pytest` 2건 실패 | 기존 HFX 외 / UI test debt | integration gate | 포함 승인·해결. production UI는 유지하고 구형 Python 단정만 최신 UI 계약에 맞춰 조정 | `HEAD(9db7ccb5)` 동일 재현, 집중 2/2 및 전체 `1318 passed / 0 failed` |
| DISC-003 | G6 Django 전체 discovery | public law projector·law adapter의 최신 계약과 구형 Django fixture 2건이 불일치해 383건 중 1 failure·1 error | 기존 HFX 외 / Django test debt | integration gate | 포함·해결. production 코드는 유지하고 source-backed law fixture와 `llm_extractor` keyword 수용 mock으로 정렬 | 단독 RED 2건, 집중 GREEN `2 tests / OK`, 전체 GREEN `383 tests / OK` |
| DISC-004 | G6 pilot Compose render | `docker compose config --quiet`가 `OPERATIONAL_LOG_GROUP` 필수 변수 누락으로 실패 | 기존 HFX 외 / deployment template defect | release gate | 포함·해결. Compose 필수 키와 runtime template의 집합 계약을 추가하고 deploy-script 주입 placeholder 한 줄 보완 | 신규 RED 1건, GREEN `1 passed`; AWS pilot `85 passed`; local·pilot Compose render 성공 |

### 범위 변경 규칙

- 보안·개인정보·인증 소유권·데이터 손실·배포 장애는 P0 후보로 즉시 평가한다.
- 현재 HFX 완료에 필수인 문제만 이번 핫픽스에 포함한다.
- 독립 기능 개선·디자인 개선·성능 최적화는 별도 backlog로 분리한다.
- 범위 추가는 사용자 승인 후 반영한다.

## 18. 결정 기록

| 결정 | 선택 | 이유 | 상태 |
|---|---|---|---|
| 문서 구조 | 마스터 체크리스트 + 단계별 상세 구현 계획 | 전체 흐름과 독립 검증을 함께 유지 | 승인 |
| 최종 범위 | 운영 재배포와 배포 후 13개 E2E 포함 | 실제 운영 결과까지 확인해야 완료 판정 가능 | 승인 |
| 현재 행동 | 문서 작성만 수행 | UI 핫픽스 진행 중 충돌·중복 구현 방지 | 승인 |
| 구현 기준 | UI 핫픽스 병합 후 최신 `origin/dev` | 오래된 SHA 기반 구현 방지 | 승인 |
| 운영 배포 | 별도 승인 게이트 | 운영 변경과 롤백 권한 보호 | 승인 |
| G0 기준점 | PR #354 merge SHA `61e0c56b` | UI 핫픽스 포함 최신 `dev`에서 재기준화 | 완료 |
| P0 실행 계획 | `docs/superpowers/plans/2026-07-31-p0-safety-boundary-hotfix.md` | HFX-009~011을 TDD와 커밋 경계로 분리 | 검증 완료 |
| G2 실행 계획 | `docs/superpowers/plans/2026-07-31-auth-new-conversation-state-hotfix.md` | HFX-012 startup auth 검증·session gate·원자적 새 상담을 TDD로 분리 | 검증 완료 |

## 19. 단계별 상세 계획 문서 전환 조건

다음 조건을 만족하면 상세 구현 계획을 작성한다.

- [x] 사용자가 이 마스터 체크리스트를 검토·승인
- [x] UI 핫픽스가 `dev`에 병합됨
- [x] 사용자가 빌드 성공 후 구현 시작을 승인

상세 계획은 다음 단위로 분리한다.

1. P0 안전 경계: HFX-009·010·011
2. 인증·상담 상태: HFX-012
3. 운영·로그·모니터: HFX-013
4. 상담 기능: HFX-014·015·016
5. UX·증거: HFX-017·018
6. 전체 회귀·운영 재배포·13개 E2E

각 상세 계획에는 최신 `dev` 기준의 정확한 수정 파일, 테스트 파일, 실패 테스트, 최소 구현, 통과 명령, review gate, 커밋 경계를 기록한다.
