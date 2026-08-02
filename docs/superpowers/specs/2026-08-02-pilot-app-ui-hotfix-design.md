# Pilot App Response and UI Hotfix Design

> 기준일: 2026-08-02  
> 기준 브랜치: `origin/dev`  
> 기준 SHA: `6cd91da405c684a9d01ba76871c3a031299e3d78`  
> 상태: 사용자 승인 범위를 구현 가능한 설계로 고정

## 1. 목표

운영 상담에서 발생한 빈 응답 표시 문제를 API·프런트 표시 경계에서 재현하고 고친다. 동시에 `차분해 UI·UX 릴리즈 리뷰 · 2026-07-31`의 15개 항목을 P0 → P1 → P2 순서로 반영한다.

완료 조건은 다음 네 가지뿐이다.

1. 응답 상태와 표시 내용의 계약 결함을 재현하는 테스트가 통과한다.
2. 프런트 15개 UI·UX 항목의 자동 검증과 로컬 화면 검증이 통과한다.
3. 관련 Python·Django·Node 회귀 테스트가 통과한다.
4. Vite 프로덕션 빌드와 `git diff --check`가 통과한다.

## 2. 입력 근거

- `2026-08-02-pilot-hotfix-goal-realignment-and-final-acceptance.md`
- `차분해_UIUX_릴리즈_리뷰_2026-07-31.html`
- 최신 `dev`의 현재 API·프런트 코드와 테스트
- 2026-08-02 베이스라인 결과
  - Node: 66 passed
  - Vite production build: success
  - 서비스 pytest: 69 passed, 기존 warning 1건
  - Django analysis job queue: 33 passed

## 3. 고정 범위

### 3.1 포함

- `needs_input`, `needs_clarification`, `partial`, `failed`, `success`, `queued`, `running`의 표시 계약
- 실행 가능한 요청과 동기 안내 응답의 분기 계약 테스트
- 빈 `assistant_message`에 대한 안전한 사용자 안내와 복구 행동
- 안전한 Markdown/GFM 답변 렌더링
- 본 답변, 한계, 추가 질문, 리포트 진입점의 시각적 계층
- 모바일 작성기, Enter/Shift+Enter/한글 IME, 첨부 메뉴 접근성
- 모바일 전역 내비게이션, 한글 줄바꿈, overflow
- 리포트 누락 항목 직렬화, 작업대 비율, 법률 고지, 빈 상태
- 로그인 전 `내 사건` gate, 로그인 CTA 중복 제거
- 전송·페이지 이동 아이콘 구분과 제품 용어 통일

### 3.2 제외

- AI, Supervisor, Agent, RAG, OCR, Vision 엔진의 판단 로직 변경
- 새로운 라우팅 의도, Agent node, 모델 provider 또는 데이터 모델 도입
- DB migration, 영속 데이터 구조, 인증 정책 변경
- `deploy/aws-pilot/**`, `infra/terraform-pilot/**`, buildspec, Pipeline 수정
- AWS 수동 승인, 운영 배포, 운영 13개 E2E 실행
- paid provider 호출
- 리뷰와 무관한 리팩터링 또는 신규 기능

## 4. 운영·병합 제약

- 앱 핫픽스 코드는 별도 작업 범위로 유지한다.
- 최신 `dev`에는 CodeBuild release safety, evidence permission, disk headroom 수정이 포함돼 있다.
- 앱 핫픽스는 배포 스크립트나 배포 계약 테스트를 수정하지 않는다.
- `dev` 병합은 backend/frontend immutable image Build를 유발할 수 있다.
- 운영 수동 승인은 이 작업 범위가 아니다. 별도 사용자 요청이 있을 때만 모든 핫픽스가 모인 최종 SHA를 승인 대상으로 검토한다.

## 5. 현재 코드에서 확인한 결함 경계

### 5.1 응답 상태와 빈 말풍선

`backend/chatbot/views.py::submit_chat_message`는 동기 안내 상태를 job 생성 전에 반환하고 실행 가능한 요청만 Worker queue로 전달한다. 동기 응답 helper는 원칙적으로 `assistant_message.answer`를 제공한다.

프런트는 여러 후보 문자열을 순서대로 선택하지만 모든 후보가 비면 빈 문자열을 메시지로 추가한다. 따라서 수정은 다음 순서를 따른다.

1. 실제 API 경계 테스트로 동기 상태의 비어 있지 않은 표시 내용을 고정한다.
2. API가 계약을 지키는데 프런트가 비운 경우 프런트 정규화만 수정한다.
3. 현재 확인된 helper 계약을 기준으로 production backend는 수정하지 않고 API 회귀 테스트만 추가한다.
4. 새 테스트가 예상과 달리 backend 누락으로 RED가 되면 backend를 바로 수정하지 않고 원인과 변경 경계를 다시 사용자에게 보고한다.
5. 엔진 내부 응답 생성·라우팅·Agent 실행 코드는 수정하지 않는다.

### 5.2 Markdown

현재 AI 답변은 `<p>{message.content}</p>`로 렌더링되어 제목, 목록, 표, 인용, 링크 구조가 보존되지 않는다. raw HTML은 실행하지 않고 CommonMark와 GFM만 허용한다.

### 5.3 입력과 첨부 메뉴

현재 textarea에는 Enter 전송 handler가 없고 전송 버튼 클릭만 지원한다. 첨부 메뉴는 열기/닫기 토글만 있으며 바깥 클릭, Escape, focus 이동 계약이 없다.

### 5.4 리포트 누락 항목

`reportWorkbenchState.js`는 누락 항목을 `String(value)`로 변환한다. 객체 payload가 들어오면 `[object Object]`가 사용자 화면에 노출된다.

### 5.5 모바일 내비게이션과 작성기

현재 모바일 하단 메뉴는 새 상담·내 사건·사고 가이드의 3개 항목이다. 전역 IA의 상담·리포트 접근이 빠져 있고 새 상담이 전역 탭으로 섞여 있다. 작성기와 고정 하단 메뉴 사이의 안전 영역도 명시적으로 공유되지 않는다.

## 6. 설계

### 6.1 응답 표시 모델

프런트 API 경계에 순수 정규화 모듈을 둔다. 이 모듈은 서버 payload를 다음 표시 모델로 변환한다.

```text
ChatResponsePresentation
  semanticStatus
  tone
  answerMarkdown
  followUp
  pendingQuestions
  retryAction
  reportLink
```

정규화 우선순위는 다음과 같다.

1. `assistant_message.core_answer`
2. `assistant_message.answer`
3. `assistant_message.summary`
4. `polling_notice.message`
5. `analysis_progress.user_message`
6. 상태별 안전한 사용자 fallback

내부 상태 이름, 객체 문자열, `undefined`, `null`, 빈 문자열은 답변으로 사용하지 않는다. 상태별 fallback은 원인 추정 문구가 아니라 사용자가 할 수 있는 다음 행동만 제공한다.

### 6.2 상태 의미 보존

- `queued`, `running`: 진행 중 표시를 유지하며 성공으로 표현하지 않는다.
- `needs_input`, `needs_clarification`: Worker 성공처럼 표현하지 않고 질문을 답변과 분리한다.
- `partial`: 확인된 결과와 미완료 항목을 함께 표시한다.
- `failed`: 실패 안내와 재시도 행동을 표시하고 내부 오류를 숨긴다.
- `success`: 비어 있지 않은 최종 답변이 있어야 한다. 최종 답변이 비면 안전한 복구 안내로 강등한다.

### 6.3 안전한 Markdown

- `react-markdown`과 `remark-gfm`을 사용한다.
- raw HTML을 렌더링하지 않는다.
- 링크는 안전한 URL만 허용하고 외부 링크에는 `rel="noreferrer noopener"`를 적용한다.
- 표는 bubble 내부 전용 overflow wrapper에 넣는다.
- 제목, 문단, 목록, 인용, inline code, fenced code, 링크, 표에 전용 class를 적용한다.
- XSS 문자열과 `javascript:` 링크 회귀 테스트를 둔다.

### 6.4 답변 정보 계층

한 assistant turn은 다음 순서를 유지한다.

1. Markdown 본 답변
2. 접힌 한계·주의 안내
3. 사용자 추가 질문 1개와 선택 가능한 보조 항목
4. 리포트 상태와 `현재 리포트 보기` CTA

같은 한계 문구나 추가 질문 패널을 한 턴에 중복 렌더링하지 않는다. 리포트 CTA는 persisted report 또는 표시 가능한 reporting payload가 있을 때만 노출한다.

### 6.5 작성기와 키보드

- Enter: 전송
- Shift+Enter: 줄바꿈
- `event.isComposing` 또는 native event의 composition 상태: 전송 금지
- 빈 입력: 전송 금지
- 전송 중: 중복 전송 금지
- 전송 후: 입력 비우기, 사용자 메시지와 loading 상태 즉시 표시
- 모바일 버튼: 최소 44px 터치 영역
- 입력 하단에 키보드 규칙을 짧게 표시

### 6.6 첨부 메뉴

- trigger에 `aria-haspopup="menu"`, `aria-expanded`를 적용한다.
- 열 때 첫 항목으로 focus를 이동한다.
- 바깥 pointerdown, Escape, 항목 선택, 경로 이동 시 닫는다.
- 닫은 뒤 trigger로 focus를 복원한다.
- ArrowUp/ArrowDown으로 항목을 이동한다.
- 메뉴는 320px viewport 밖으로 넘지 않는다.

### 6.7 모바일 레이아웃과 전역 IA

- 모바일 전역 메뉴는 `사고 가이드 · AI 상담 · 리포트 · 내 사건` 4탭으로 고정한다.
- `새 상담`은 전역 탭에서 제거하고 상담 화면 내부 secondary action으로 유지한다.
- 상단 모바일 전역 메뉴와 하단 메뉴를 동시에 표시하지 않는다.
- 작성기는 하단 메뉴와 safe area 높이를 고려해 배치한다.
- 메시지 스크롤 영역에 작성기와 하단 메뉴 높이만큼 여백을 확보한다.
- 주요 heading에는 `word-break: keep-all`, `overflow-wrap: break-word`, 가능한 환경에서 `text-wrap: balance`를 적용한다.
- 320px부터 가로 페이지 overflow가 없어야 한다.

### 6.8 리포트 표시 계약

누락 항목은 다음 순서로 문자열을 고른다.

1. 문자열 payload
2. 객체의 `question`
3. 객체의 `label`
4. 객체의 `description`
5. 사용자용 fallback `추가 확인 항목을 불러오지 못했습니다.`

목록은 중복을 제거하고 최대 표시 수를 유지한다. `[object Object]`, `undefined`, `null`은 표시하지 않는다.

데스크톱 작업대는 중앙 문서를 65~75% 범위의 주 콘텐츠로 둔다. 목록과 inspector는 접을 수 있게 하며, 모바일 순서는 리포트 → 다음 행동 → 보조 목록·설명이다.

### 6.9 고지·빈 상태·인증 IA·용어

- 법률 고지는 목록에서 제거하고 결론·다운로드 맥락에 1~2줄과 disclosure로 표시한다.
- 리포트 빈 상태는 한 viewport에 한 번만 표시하고 CTA는 `AI 상담 시작` 하나만 둔다.
- 비회원 전역 메뉴는 `마이페이지` 대신 `내 사건`을 사용한다.
- 비회원 `내 사건`은 0건 KPI가 아니라 저장 가치와 Google 로그인 CTA 하나를 표시한다.
- 같은 destination은 `AI 상담 시작`으로 통일한다.
- `접수` 또는 `저장`은 실제 사건 저장 행동에만 사용한다.
- 전송은 paper-plane 또는 `보내기` 라벨로 표시하고 scroll-to-top과 같은 아이콘을 쓰지 않는다.

## 7. 파일 경계

예상 변경 파일은 다음 영역으로 제한한다.

### 프런트

- `app/web/package.json`
- `app/web/package-lock.json`
- `app/web/FrontendAppShell.jsx`
- `app/web/styles.css`
- `app/web/reportWorkbenchState.js`
- `app/web/chatResponsePresentation.js`
- `app/web/SafeMarkdown.js`
- `app/web/composerInteraction.js`
- `app/web/chatResponsePresentation.test.js`
- `app/web/SafeMarkdown.test.js`
- `app/web/composerInteraction.test.js`
- `app/web/reportWorkbenchState.test.js`
- `app/web/consultationLayout.test.js`

### API 경계

- `test/test_chat_orchestration_service.py` — 동기 응답 helper 계약만 검증
- `backend/chatbot/test_analysis_job_queue.py` — HTTP 동기·비동기 분기 계약만 검증

`app/services/chat_orchestration_service.py`, `backend/chatbot/views.py`,
`app/web/analysisProgressUi.js`, `app/web/workerPolling.js`는 현재 production
동작을 유지한다. 새 회귀 테스트가 이 가정과 다른 RED를 만들면 구현을 멈추고
설계 변경 승인을 받는다.

다음 경로는 변경하지 않는다.

- `ai/**`
- Agent 실행·RAG·Vision 구현
- `deploy/**`
- `infra/**`
- `buildspec*.yml`

## 8. 테스트 전략

모든 구현은 실패 테스트 → 최소 구현 → 집중 테스트 → 관련 회귀 순서로 진행한다.

### 8.1 API·상태 계약

- 동기 비실행 상태마다 비어 있지 않은 `assistant_message`와 `pending_questions` 검증
- 실행 가능한 요청만 `async_worker`와 work item을 갖는지 검증
- `success`지만 표시 결과가 빈 경우 성공 말풍선을 만들지 않는지 검증
- `needs_input`, `partial`, `failed` 의미가 polling 뒤에도 보존되는지 검증

### 8.2 Markdown·표시 모델

- 제목, 목록, 인용, 링크, 표 렌더링
- raw HTML/XSS 및 위험 URL 비실행
- 객체·배열·null·중첩 누락 항목 정규화
- 모든 상태별 사용자 fallback과 복구 행동

### 8.3 상호작용

- Enter, Shift+Enter, 한글 composition, 빈 입력, 전송 중 중복 차단
- 첨부 메뉴 바깥 클릭, Escape, 선택, focus 복원, Arrow key
- 모바일 4탭의 route와 active 상태
- 비회원 로그인 CTA 중복 0건

### 8.4 레이아웃·시각 검증

- 320×568, 360×800, 390×844, 430×932에서 작성기와 전역 메뉴 확인
- 긴 Markdown 표·제목·답변·오류 상태에서 가로 페이지 overflow 확인
- 데스크톱 1366px에서 중앙 리포트 비율 확인
- 가이드·상담·리포트·내 사건의 전역 메뉴 일관성 확인
- 로컬 브라우저 검증은 기능·레이아웃 확인용이며 운영 배포 검증으로 간주하지 않는다.

### 8.5 회귀와 빌드

- `node --test` in `app/web`
- `npm run build` in `app/web`
- 관련 root pytest
- 관련 `python backend/manage.py test ...`
- 전체 root `python -m pytest -q`
- 전체 Django `python backend/manage.py test chatbot --verbosity 1`
- `git diff --check`

## 9. 오류 처리와 개인정보

- 사용자 입력이나 서버 원문 오류를 새 로그에 기록하지 않는다.
- fallback은 내부 exception, Agent node, execution mode를 노출하지 않는다.
- Markdown은 raw HTML을 실행하지 않는다.
- 외부 링크 정책과 accessible name을 유지한다.
- 기존 민감정보 차단·인증·소유권 정책은 변경하지 않는다.

## 10. 완료 판정

다음 조건을 모두 만족할 때 로컬 핫픽스 구현 완료로 판정한다.

- 응답 없음 또는 빈 assistant 말풍선 재현 0건
- `[object Object]`, `undefined`, `null` 사용자 노출 0건
- 프런트 15개 항목의 자동·로컬 화면 검증 통과
- 관련 Python·Django·Node 테스트 통과
- Vite production build 통과
- `git diff --check` 통과
- 제외 경로 변경 0건

운영 수동 승인, 운영 배포, 운영 13개 E2E는 이 완료 판정에 포함하지 않는다.
