# OpenAPI persona execution - hi20260204-maker

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-06-29 |
| 기준 브랜치 | `codex/openapi-persona-contract-start` |
| 기준 OpenAPI | `docs/api/openapi-v0.yaml` |
| persona | `hi20260204-maker` |
| 실행 기준 | `confirmed` contract만 1차 실행 대상으로 사용 |
| 제외 기준 | MCP, 외부 API, 실제 Agent/RAG/LLM 호출, `review_required` endpoint 직접 구현 |
| 연결 전략 | `docs/architecture/service-protocol-persona-strategy-2026-06-29.md` |

## 1. 시작 가능 여부

가능하다. 현재 `dev`에는 OpenAPI v0 계약, auth session mock, history event mock, canonical `/api/...` shadow endpoint, Agent adapter 계약, PostgreSQL 저장 경계가 들어와 있다. 따라서 `hi20260204-maker` persona는 OpenAPI에서 자기 담당 계약을 도출해 1차 실행 범위를 잡을 수 있다.

다만 1차 실행은 실제 production 구현이 아니라 `confirmed` 계약 기반의 안전한 mock/backend/QA 실행으로 제한한다. `review_required` 항목은 구현하지 않고 정책, 저장 범위, 담당자 sample output 확인 목록으로 둔다.

## 2. 이번 persona 범위

`hi20260204-maker`의 현재 실행 범위는 다음 축이다.

| 축 | 1차 실행 범위 |
|---|---|
| Auth | guest session, current auth subject, `auth_error.v1` |
| Chat | session 생성, message 제출, Supervisor `analysis_plan` 생성 |
| Files | attachment metadata 저장/조회와 Agent handoff |
| Analysis Jobs | job 생성, 상태 조회, raw mock detail 조회 |
| Analysis Results | frontend display DTO 조회 |
| Agents | node registry, 단일 node 실행, plan 실행 |
| Reports | report action 저장/다운로드 mock |
| History | standard-light history event 조회 |
| QA | OpenAPI persona pack, confirmed/review_required 분리, 회귀 테스트 |

## 3. confirmed endpoint pack

아래 endpoint는 1차 persona 실행에 사용할 수 있다.

### Auth

| Method | Path | 목적 |
|---|---|---|
| `POST` | `/api/auth/guest-session/` | guest identity 발급/갱신 |
| `GET` | `/api/auth/me/` | 현재 auth subject 확인 |

### Chat

| Method | Path | 목적 |
|---|---|---|
| `POST` | `/api/chat/sessions/` | chat session 생성 |
| `POST` | `/api/chat/messages/` | 사용자 message 제출과 Supervisor plan 생성 |
| `POST` | `/api/mock/chat/sessions/` | mock alias |
| `POST` | `/api/mock/chat/messages/` | mock alias |

### Files

| Method | Path | 목적 |
|---|---|---|
| `GET` | `/api/files/` | attachment metadata 목록 조회 |
| `POST` | `/api/files/` | attachment 등록/업로드 |
| `GET` | `/api/files/{attachment_id}/` | attachment metadata 상세 조회 |
| `GET` | `/api/mock/attachments/` | mock alias |
| `POST` | `/api/mock/attachments/` | mock alias |
| `GET` | `/api/mock/attachments/{attachment_id}/` | mock alias |

### Analysis Jobs

| Method | Path | 목적 |
|---|---|---|
| `GET` | `/api/analysis/jobs/` | analysis job 목록 조회 |
| `POST` | `/api/analysis/jobs/` | analysis job 생성 |
| `GET` | `/api/analysis/jobs/{job_id}/` | job 상태와 raw mock detail 조회 |
| `GET` | `/api/mock/analysis/jobs/` | mock alias |
| `POST` | `/api/mock/analysis/jobs/` | mock alias |
| `GET` | `/api/mock/analysis/jobs/{job_id}/` | mock alias |

### Analysis Results

| Method | Path | 목적 |
|---|---|---|
| `GET` | `/api/analysis/results/{job_id}/` | frontend display result 조회 |
| `GET` | `/api/mock/analysis/results/{job_id}/` | mock alias |

### Agents

| Method | Path | 목적 |
|---|---|---|
| `GET` | `/api/agents/nodes/` | Agent/Supervisor node registry 조회 |
| `POST` | `/api/agents/nodes/run/` | 단일 Agent node mock 실행 |
| `POST` | `/api/agents/plans/run/` | `analysis_plan` 기반 전체 node mock 실행 |
| `GET` | `/api/mock/agents/nodes/` | mock alias |
| `POST` | `/api/mock/agents/nodes/run/` | mock alias |
| `POST` | `/api/mock/agents/plans/run/` | mock alias |

### Reports

| Method | Path | 목적 |
|---|---|---|
| `POST` | `/api/reports/` | report action 저장/요청 |
| `GET` | `/api/reports/{report_id}/download/` | report artifact 다운로드 |
| `POST` | `/api/mock/reports/` | mock alias |
| `GET` | `/api/mock/reports/{report_id}/download/` | mock alias |

### History

| Method | Path | 목적 |
|---|---|---|
| `GET` | `/api/history/` | standard-light history event 조회 |
| `GET` | `/api/mock/history/` | mock alias |

## 4. 선확인 후속 범위

아래 endpoint는 OpenAPI에는 있지만 1차 구현 대상에서 제외한다.

| Method | Path | 제외 이유 |
|---|---|---|
| `GET` | `/api/chat/sessions/` | 대화 목록 정책과 owner 권한 미확정 |
| `GET` | `/api/chat/sessions/{session_id}/messages/` | 메시지 원문 조회와 보관 정책 미확정 |
| `GET` | `/api/mypage/summary/` | 마이페이지 집계 기준 미확정 |
| `GET` | `/api/reports/` | report 목록 DB 연결 미확정 |
| `GET` | `/api/reports/{report_id}/` | report 상세 DB 연결 미확정 |
| `POST` | `/api/reports/objection-draft/` | PDF/PM 초안에는 있으나 현재 Django route 없음 |

## 5. 오늘 시작한 구현 경계

| 파일 | 역할 |
|---|---|
| `app/services/openapi_persona_schema_service.py` | OpenAPI v0에서 persona별 endpoint/schema contract pack 도출 |
| `test/test_openapi_persona_schema_service.py` | persona pack, confirmed/review_required 분리, Agent/Supervisor schema 포함 여부 검증 |

이 구현은 실제 endpoint를 추가하지 않는다. OpenAPI를 읽어서 `hi20260204-maker`, `agent`, `supervisor`, `django_backend`, `frontend`가 각자 봐야 할 계약 묶음을 기계적으로 도출하는 선행 레이어다.

## 6. 1차 실행 기준

1차 persona 실행은 아래 순서로 진행한다.

1. `hi20260204-maker` pack을 `include_review_required=False`로 생성한다.
2. confirmed endpoint와 schema만 사용한다.
3. `review_required` 항목은 별도 확인 목록으로 둔다.
4. `POST /api/chat/messages/` 또는 `POST /api/analysis/jobs/`에서 생성되는 `analysis_plan`을 기준으로 Agent 실행 계획을 확인한다.
5. `GET /api/analysis/results/{job_id}/` display DTO로 화면 표시 가능성을 확인한다.
6. `GET /api/history/`로 standard-light 이력 이벤트가 남는지 확인한다.

## 7. 다음 구현 우선순위

| 우선 | 작업 | 연결 이슈 |
|---:|---|---|
| 1 | Agent 실행 결과를 `agent_results` 저장 경계에 연결 | `#22`, `#29`, `#40`, `#68` |
| 2 | Supervisor display DTO를 `analysis_display_results`에 저장하거나 DB에서 재구성 | `#29`, `#40`, `#58`, `#68` |
| 3 | report persistence와 object storage download flow 연결 | `#27`, `#43`, `#58`, `#68` |
| 4 | Redis progress cache와 PostgreSQL fallback 기준 정리 | `#40`, `#43`, `#68` |
| 5 | `review_required` endpoint 정책 확정 후 다음 OpenAPI 버전 반영 | `#22`, `#41`, `#68` |

## 7.1 회의 메모 반영 우선순위

2026-06-29 추가 메모 기준으로 아래 항목을 우선 확인한다.

| 우선 | 항목 | 처리 |
|---:|---|---|
| 1 | 로그인 세션과 채팅/사건 세션 구분 | `user_id`, `guest_id`, `auth_session_id`, `session_id`를 OpenAPI와 DB metadata에서 섞지 않는다. |
| 2 | 히스토리와 애프터서비스 | 채팅 원문 저장보다 `history_event.v1` 표준-라이트 이벤트를 우선한다. |
| 3 | 비회원/회원/구독 rate limit | API 비용이 드는 Agent 실행, 파일 업로드, report 생성에 quota key를 둔다. |
| 4 | 내 사건 진행도 | `analysis_jobs`, `analysis_job_events`, `agent_results`, `reports`, `history_events`에서 재구성한다. |
| 5 | Agent 동기/비동기 기준 | 입력 검증과 plan 생성은 동기, OCR/RAG/이미지/LLM은 비동기 worker 후보로 둔다. |
| 6 | 사고 장면 샘플과 rule | 실제 Vision 비용 전 mock sample과 품질 rule을 먼저 만든다. |
| 7 | RAG 사용 이유 | 법령/판례/사례 근거 추적과 재현성을 위해 쓰고, frontier model은 요약/설명에 제한한다. |

## 8. 완료 기준

- `hi20260204-maker` persona pack이 OpenAPI v0에서 재현 가능해야 한다.
- confirmed endpoint만으로 중간 발표 mock 흐름을 설명할 수 있어야 한다.
- `review_required` endpoint가 실수로 구현 범위에 들어가지 않아야 한다.
- 전체 pytest와 Django check가 통과해야 한다.
- #68에 현재 판단, 구현 파일, 검증 결과, 다음 순서가 남아 있어야 한다.
