# 교통분쟁 AI 서비스 설계서

작성일: 2026-07-21
범위: 전체 서비스 (홈 화면 ~ AI 상담 ~ 마이페이지 ~ 리포트), UI/UX 흐름 + 기술 아키텍처

---

## 1. 서비스 개요

교통분쟁 AI는 교통사고 과실비율, 과태료·범칙금 이의신청, 교통 법령 조회를 지원하는 상담형 웹 서비스다. 사용자가 상황을 텍스트/자료로 입력하면 AI가 쟁점과 부족한 정보를 정리해 되묻고, 필요한 법적 근거를 찾아 다음 행동(이의신청서 작성, 리포트 다운로드 등)을 제안한다.

핵심 원칙(README 기준):
- 최종 자연어 답변은 개별 Agent가 아니라 Supervisor 흐름에서 통합한다.
- 서비스는 "AI가 결론을 대신 내리지 않고, 판단에 필요한 정보를 명확하게 만드는 것"을 목표로 한다.

---

## 2. 전체 아키텍처

```
[사용자 브라우저]
      │  (Vite dev / 정적 빌드)
[React 프론트엔드]  app/web/FrontendAppShell.jsx
      │  REST(JSON) — /api/*
[Django 백엔드]      backend/  (config, chatbot app)
  ├─ JwtAuthMiddleware / SameOriginCorsMiddleware
  ├─ chatbot/views.py  ── API 엔드포인트
  └─ app/services/*    ── 도메인 서비스 계층
        ├─ chat_orchestration_service  (라우팅 + 응답 조립)
        ├─ supervisor_llm_service       (Supervisor LLM 연동, OpenAI)
        ├─ consultation_v2_service      (사고 과실비율 사실관계 수집)
        └─ google_auth_service          (Google OAuth 처리)
      │
[ai/agents/*]  ── 5개 도메인 Agent (아래 4절)
      │
[agent-worker 프로세스] ── 큐에 쌓인 상담 작업을 비동기로 실제 처리
      │
[PostgreSQL] [Neo4j] [Redis] [ClamAV] [Object Storage]
```

- 프론트/백엔드는 REST API로 통신하며, 채팅 메시지는 "즉시 접수(queued) → agent-worker가 비동기 처리 → 프론트가 폴링으로 결과 수신" 구조다.
- 로컬 개발은 Postgres/Neo4j/Redis 없이도 sqlite + in-memory 캐시로 동작하도록 폴백이 되어 있다(단, 법령 검색용 RAG 데이터는 시드가 없으면 빈 결과를 반환한다).

---

## 3. 화면 구조 및 사용자 흐름 (UI/UX)

프론트엔드는 탭 3개를 중심으로 구성된다 (`TAB_ROUTES`):

| 탭 id | 라벨 | 설명 |
|---|---|---|
| `chatbot` | 사고·과실 상담 | AI와 대화하며 상황을 정리하는 메인 화면 |
| `mypage` | 마이페이지 | 로그인 사용자의 저장된 사건 목록("내 사건") |
| `reporting` | 리포트 | 리포트 생성/다운로드 작업대 |

### 3.1 홈 / 진입 화면 (`EntryScreenV2`)
- 히어로 카피: "복잡한 교통 문제, 다음 행동부터 함께 정리합니다."
- CTA 2개: **내 상황 정리 시작**(로그인 유도) / **자료 없이 먼저 질문하기**(게스트 진입)
- 하단에 "지금 상황에 맞는 도움부터 시작하세요" 카드 그리드, "결론을 대신 내리지 않습니다 — 판단에 필요한 정보를 더 명확하게 만듭니다" 4단계 설명(상황 요약 → 쟁점 확인 → 근거 조회 → 다음 행동) 배치.
- 예전 가치설명 박스 등 불필요한 잡음 요소는 제거된 상태(2026-07-16 개편, `docs/uiux-concept-v2-screen-design-2026-07-16.md` 참조).

### 3.2 AI 상담 화면 (`ChatScreenV2`)
- 좌측 사이드바: 대화 목록 + 계정 상태.
- 중앙: 대화 스레드. 사용자 메시지 / AI 응답 말풍선.
  - AI 응답 말풍선은 고정 안내 문구 없이 **실제 답변 내용**을 바로 보여준다.
  - AI가 답변을 생성하는 동안에는 점 3개가 튀는 로딩 인디케이터("AI가 답변을 정리하고 있어요")를 표시한다.
  - 응답에 아직 채워지지 않은 필드가 있으면 `MissingFieldsPrompt` 컴포넌트가 "지금 분석에 필요한 정보예요" 박스로 구체적 질문 목록을 보여준다.
  - 하단에는 리포트 액션(로그인 후 저장 / 화면 PDF 저장 / 로그인 후 이의신청서 PDF) 패널이 붙는다.
- 하단 입력창 + 자료 첨부(고지서, 보조 자료) + 빠른 질문 버튼.
- 개발 모드에서만 보이는 "UI 미리보기(로그인 상태로 보기)" 버튼: 백엔드 호출 없이 화면만 로그인 상태로 전환해 확인할 수 있다(`previewLoggedInUi`).

### 3.3 마이페이지 (`MyPageScreen`)
- "내 사건" 목록. 로그인 사용자가 저장한 상담을 카드로 보여주고 클릭 시 사건 결과 화면으로 이동.

### 3.4 과거 이력 (`HistoryScreen`)
- 시간순 이벤트 로그(상담/리포트/로그인 등)를 나열.

### 3.5 사건 결과 화면 (`CaseResultScreen`)
- 라우팅 인텐트에 따라 "사고 과실비율 분석 결과" 또는 "과태료·범칙금 분석 결과" 타이틀로 분기 표시.

### 3.6 리포팅 화면 (`ReportingScreen`)
- "리포트 작업대" — 생성된 리포트 상태 확인, 다운로드, 재실행.

---

## 4. 인증 및 세션 모델

세 가지 신원 상태를 구분한다.

1. **anonymous(비로그인, 게스트ID도 없음)** — 극히 제한된 quota.
2. **guest(게스트 세션)** — `X-Guest-Id` 헤더로 식별. `Authorization` 헤더가 없어야 게스트 허용 경로(`GUEST_ALLOWED_PATHS`)에 접근 가능.
3. **authenticated** — Google OAuth 로그인 후 발급된 App JWT(`Authorization: Bearer ...`)로 식별.

인증 흐름:
- Google OAuth Authorization Code 팝업 플로우 (`app/web/authSession.js`) → 백엔드 `/api/auth/google/code/`에서 코드 교환 → App JWT 발급.
- 서버 측 검증은 `app/services/google_auth_service.py`의 `_validate_google_code_request`/`normalize_google_web_origin`에서 처리하며, `client_id`, `redirect_uri`, 브라우저 `Origin` 헤더가 정확히 일치해야 한다(호스트가 `127.0.0.1`이냐 `localhost`냐까지 구분).
- `backend/config/middleware.py`의 `JwtAuthMiddleware`가 모든 보호 경로(`PROTECTED_PREFIXES`)에 대해 게스트 허용 여부 또는 JWT 유효성을 검사한다. `Authorization` 헤더가 존재하는 순간 게스트 우회 경로는 무조건 비활성화된다.

---

## 5. AI 상담 처리 파이프라인

1. **라우팅** (`chat_orchestration_service._routing_intent`) — 사용자 텍스트의 키워드로 3가지 인텐트 중 하나로 분류:
   - `fine_notice_objection` (과태료, 고지서, 범칙금, 의견제출, 이의신청)
   - `fault_ratio_text` (과실, 사고, 충돌, 접촉, 교차로, 보행자, 구급차, 다쳐 등)
   - `traffic_law_search` (그 외 전부 — 기본값)

2. **사실관계 수집**
   - `fault_ratio_text`(사고) 인텐트는 `consultation_v2_service.build_consultation_state_v2()`가 전담. `road_layout`, `vehicle_actions`, `signal_priority`, `collision_location` 4개 핵심 사실을 확인하고, 고위험(인명피해 등) 판단 시 `high_risk_handoff`로 우선 처리한다.
   - 그 외 인텐트는 `supervisor_llm_service.build_supervisor_state_with_optional_llm()`을 통해 Supervisor 상태(missing_fields/next_questions 포함)를 만든다. `SUPERVISOR_LLM_ENABLED=1`이면 OpenAI(`gpt-5.4-mini`)를 호출해 실제 판단을 받고, 꺼져 있으면 결정론적 폴백(`_fallback_supervisor_state`, 항상 "필요 정보 없음"으로 처리)을 쓴다.
   - LLM 응답은 매우 엄격한 JSON 계약(`_valid_llm_state_candidate`)을 통과해야 정식 채택되며, 실패해도 `next_questions`만은 최대한 느슨하게 추출해 사용자에게 보여준다(`_lenient_missing_fields`).

3. **작업 접수 및 비동기 실행**
   - 위 상태가 "정보 충분"으로 판단되면 `chat_orchestration_service.submit_message()`가 `analysis_plan`(Agent 실행 계획)을 만들어 큐에 등록하고 `status: "queued"`로 즉시 응답한다.
   - 실제 실행은 별도 **agent-worker 프로세스**(`process_agent_work_items`)가 큐를 폴링하며 처리한다. 이 프로세스가 떠 있지 않으면 작업이 영원히 대기 상태로 남고, 프론트는 폴링 타임아웃 후 안내 문구만 표시한다.
   - 실행 결과는 `compose_agent_response()`가 각 노드의 summary를 모아 하나의 답변으로 합친다. 노드가 "결과 없음(empty)" 등으로 끝나면, 원본 메시지에 이어 사용자에게 추가 정보를 요청하는 안내 문구를 덧붙인다(`NEEDS_MORE_INFO_PROMPT`).

4. **폴링** — 프론트(`pollQueuedWorkerResult`)가 `/api/analysis/results/{job_id}/`를 최대 60회(0.5초 간격)까지 조회하며 `queued/running/retrying` 상태가 끝날 때까지 기다린다.

---

## 6. AI Agent 구성

`NODE_PLANS`에 정의된 인텐트별 실행 노드와 담당자(`NODE_OWNERS`):

| 인텐트 | 실행 노드 순서 | 담당자 |
|---|---|---|
| `fine_notice_objection` | fine_notice_analysis → law_ground_search → appeal_decision_flow → objection_report_generation | workzion2 / techshin31 / hi20260204-maker |
| `fault_ratio_text` | text_ml_case_search → law_ground_search | leejaegang27 / techshin31 |
| `traffic_law_search` | law_ground_search | techshin31 |

Agent 구현 위치(`ai/agents/`):
- `fine_notice_analysis` — 과태료·범칙금 고지서 판독/검증
- `law_ground_search` — Neo4j 그래프 + 벡터 검색 기반 법령 조문 검색 (`search.py`, `query_understanding.py`, `rule_guard.py`)
- `text_ml_case_search` — RAG 기반 유사 사고 사례 검색
- `appeal_decision_flow` — 이의신청 가능 여부 판단 플로우(위험도 게이트, 기한 확인 등)
- `objection_report_generation` — 이의신청서/리포트 문서 생성(docx)
- `vision_media_analysis` — 아직 구현 전(빈 디렉터리, 영상/이미지 분석 예정 영역)

---

## 7. 백엔드 API 엔드포인트

`backend/chatbot/urls.py` 기준 (`/api/` prefix):

| 경로 | 용도 |
|---|---|
| `health/`, `health/live/`, `health/ready/` | 헬스체크 |
| `capabilities/` | 클라이언트 기능 플래그 조회 |
| `auth/guest-session/` | 게스트 세션 발급 |
| `auth/google/code/` | Google OAuth 코드 교환 |
| `auth/refresh/`, `auth/logout/`, `auth/me/` | 세션 갱신/로그아웃/내 정보 |
| `mypage/summary/` | 마이페이지 요약 |
| `history/` | 이력 이벤트 |
| `chat/sessions/`, `chat/messages/`, `chat/save-state/` | 상담 세션 생성/메시지 전송/저장 상태 변경 |
| `cases/`, `cases/<id>/workspace/`, `cases/<id>/facts/confirm/`, `cases/<id>/analysis/jobs/` | 사건(케이스) 관리 |
| `files/`, `files/<id>/` | 첨부파일 업로드/조회 |
| `analysis/jobs/`, `analysis/jobs/<id>/`, `analysis/results/<id>/` | 분석 작업/결과 조회(폴링 대상) |
| `agents/nodes/` | Agent 노드 메타 조회 |
| `reports/`, `reports/<id>/`, `reports/<id>/download/` | 리포트 생성/조회/다운로드 |

---

## 8. 데이터 및 인프라 구성

`docker-compose.yml` 기준 서비스 구성:

- **backend** — Django + gunicorn (포트 8000)
- **agent-worker** — `process_agent_work_items --loop --limit 10` (상담 분석 큐 처리)
- **file-scan-worker** — `process_uploaded_file_scans --loop` (업로드 파일 바이러스/정책 스캔)
- **frontend** — Vite 개발 서버
- **postgres** (pgvector 확장) — 정형 데이터 + RAG 임베딩 저장
- **neo4j** — 법령 조문 그래프 검색
- **redis** — 캐시/세션
- **clamav** — 업로드 파일 바이러스 스캔 엔진
- **elasticsearch / kibana** — 로그/검색 인프라
- **data-seed** — 초기 시드 데이터 적재 컨테이너

로컬 개발 시 위 인프라 없이도 sqlite + in-memory 캐시로 백엔드는 뜨지만, 법령 검색(RAG)은 데이터가 없어 항상 빈 결과를 반환한다.

---

## 9. 로컬 개발 환경 실행

Docker 없이 로컬에서 직접 띄울 때 필요한 프로세스 4개 (자동화 스크립트: `dev-local.ps1`):

```
.\dev-local.ps1
```

내부적으로 아래 4개를 각각 새 창으로 띄운다:
1. `python backend\manage.py runserver 8010` — 백엔드
2. `python backend\manage.py process_agent_work_items --loop` — 상담 분석 워커
3. `python backend\manage.py process_uploaded_file_scans --loop` — 파일 스캔 워커
4. `npm run dev` (in `app/web`) — 프론트엔드

`.env`의 `DJANGO_ENV_FILE=".env"`가 셸 환경변수로 먼저 설정되어 있어야 `.env` 값이 로드된다(위 스크립트에 반영됨).

---

## 10. 알려진 제약사항 / TODO

- 로컬 환경엔 법령 RAG 시드 데이터(Neo4j/Postgres 벡터)가 없어 `law_ground_search`가 항상 "검색 결과 없음"을 반환할 수 있다. 실제 검색 결과를 보려면 `load_legal_rag_pgvector`/`load_production_rag_seed` 등 시드 커맨드로 데이터를 적재해야 한다.
- `vision_media_analysis` Agent는 아직 미구현 상태.
- Google OAuth는 Google Cloud Console에 등록된 Authorized JavaScript Origin이 실제 접속 origin(`http://127.0.0.1:5173`)과 정확히 일치해야 동작한다.
- Supervisor LLM의 strict JSON 계약 검증(`_valid_llm_state_candidate`)이 매우 엄격해 LLM이 계약을 못 맞추면 "invalid_contract"로 폴백되는 경우가 있다. 이 경우 느슨한 질문 추출(`_lenient_missing_fields`)로 최소한의 되묻기만 보장한다.
