# OpenAPI v0 팀원 전달 가이드

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-06-29 |
| 기준 파일 | `docs/api/openapi-v0.yaml` |
| 보조 메모 | `docs/api/openapi-v0-notes.md` |
| OpenAPI 버전 | `3.2.0` |
| 목적 | 프론트엔드, Django, Supervisor, Agent 담당자가 같은 API 계약으로 mock 연결과 output schema를 맞춘다. |

## 1. 전달 파일

팀원에게 아래 두 파일을 우선 공유한다.

| 파일 | 용도 |
|---|---|
| `docs/api/openapi-v0.yaml` | 기계 판독 가능한 API 계약 원본 |
| `docs/api/openapi-v0-notes.md` | PDF, 마크다운, 현재 구현 차이와 확정/검토 기준 |

이 문서는 공유 순서와 담당자별 확인 항목을 설명하는 배포용 가이드다.

기본 공유 파일은 `openapi-v0.yaml`(`OpenAPI 3.2.0`)을 정본으로 사용한다. Swagger UI는 `3.2.0` 지원 버전을 사용하고, codegen/validator 호환 문제가 실제로 확인되면 `3.1.x` 호환본을 별도 생성한다.

## 2. 상태 구분

OpenAPI 안의 확장 필드는 반드시 구분해서 읽는다.

| 표시 | 의미 | 처리 기준 |
|---|---|---|
| `x-contract-status: confirmed` | 현재 mock backend, 테스트, 또는 안정된 PM 계약에 근거가 있음 | 연결과 테스트에 사용 가능 |
| `x-contract-status: review_required` | 화면/회의/PDF에는 필요하지만 구현 또는 정책 확인이 남음 | 임의 구현 금지, 샘플 output 또는 정책 확인 후 확정 |
| `x-review-note` | 왜 검토 상태인지 설명 | 담당자가 확인해야 할 질문으로 본다 |
| `x-internal-note` | Supervisor 내부 routing 또는 mock 개발 메모 | public API 약속으로 보지 않는다 |

## 3. 담당자별 확인 순서

### Frontend

먼저 아래 태그를 확인한다.

1. `Auth`
2. `Chat`
3. `Files`
4. `Analysis Results`
5. `Reports`
6. `MyPage`

현재 화면 연결에서 중요한 값은 `guest_id`, `auth_session_id`, `session_id`를 분리하는 것이다. 채팅과 리포트 요청에는 header `X-Guest-Id`, `X-Auth-Session-Id`와 body `auth_context`를 함께 사용할 수 있다.

### Django Backend

우선 `confirmed` endpoint와 공통 오류를 맞춘다.

| 우선 | 확인 항목 |
|---|---|
| 1 | `auth_error.v1`, `WWW-Authenticate` |
| 2 | canonical `/api/...` 응답의 `api_surface`, `execution_mode` |
| 3 | `/api/auth/guest-session/`, `/api/auth/me/` |
| 4 | `/api/chat/messages/`, `/api/files/`, `/api/analysis/jobs/`, `/api/analysis/results/{job_id}/` |
| 5 | `/api/mypage/summary/` My Case read model |
| 6 | `/api/history/` standard-light sidecar 조회 |

`review_required` endpoint는 route를 바로 만들지 않는다. 먼저 정책, 화면 owner, 저장 범위를 확인한다.

### Supervisor

Supervisor는 화면 DTO와 Agent 실행 흐름을 본다.

| 확인 대상 | 이유 |
|---|---|
| `AnalysisPlan` | 어떤 node를 어떤 순서로 부를지 |
| `AgentPlanExecution` | 여러 Agent 결과 묶음 |
| `AnalysisResult` | 프론트가 직접 보는 display output |
| `HistoryEvent` | 재상담, 진행도, 디버깅에 필요한 표준-라이트 이력 |
| DDD/MAS roadmap | Agent 실행과 history log management를 어느 bounded context에 둘지 |

화면에는 Agent raw output을 그대로 보내지 않고 `AnalysisResult` 형태로 병합한다.

### Agent 담당자

자기 node의 입력과 출력을 아래 순서로 맞춘다.

1. `AgentAdapterInput`
2. `AgentAdapterContext`
3. `AgentAdapterOutput`
4. 자기 node의 `structured_result`

Agent output에는 `status`, `summary`, `structured_result`, `evidence`, `next_actions`, `limitations`를 반드시 포함한다. 내부 reasoning 전문은 history에 저장하지 않는다.

## 4. 현재 확정 API

현재 mock 연결 기준으로 확정된 핵심 API는 아래와 같다.

| Method | Path | 담당 |
|---|---|---|
| `POST` | `/api/auth/guest-session/` | Frontend, Django |
| `GET` | `/api/auth/me/` | Frontend, Django |
| `POST` | `/api/chat/sessions/` | Frontend, Django |
| `POST` | `/api/chat/messages/` | Frontend, Django, Supervisor |
| `GET`/`POST` | `/api/files/` | Frontend, Django, Agent |
| `GET`/`POST` | `/api/analysis/jobs/` | Frontend, Django, Supervisor |
| `GET` | `/api/analysis/results/{job_id}/` | Frontend, Supervisor |
| `GET` | `/api/agents/nodes/` | Django, Agent |
| `POST` | `/api/agents/nodes/run/` | Django, Agent |
| `POST` | `/api/agents/plans/run/` | Django, Supervisor, Agent |
| `POST` | `/api/reports/` | Frontend, Django |
| `GET` | `/api/reports/{report_id}/download/` | Frontend, Django |
| `GET` | `/api/mypage/summary/` | Frontend, Django, Supervisor |
| `GET` | `/api/history/` | Frontend, Django, Supervisor |

## 5. 아직 구현 금지 항목

아래는 OpenAPI에 있어도 `review_required`로 남긴다.

| 항목 | 이유 |
|---|---|
| `GET /api/chat/sessions/` | 대화 목록 정책과 owner 권한 미확정 |
| `GET /api/chat/sessions/{session_id}/messages/` | 메시지 원문 조회와 보관 정책 미확정 |
| `GET /api/reports/`, `GET /api/reports/{report_id}/` | 리포트 목록/상세 DB 연결 미확정 |
| `POST /api/reports/objection-draft/` | PDF에는 있으나 현재 mock route 없음 |
| 히스토리 TTL/DB table | 보관 기간, 조회 권한, migration 시점 미확정 |

## 6. 검증 방법

OpenAPI 파일은 YAML 문법과 핵심 문자열 존재 여부를 먼저 확인한다.

```powershell
python -m pytest test\test_openapi_v0_distribution.py
```

mock backend 회귀 확인은 아래를 사용한다.

```powershell
python -m pytest
python backend\manage.py test chatbot
```

## 7. 다음 버전 후보

ver1로 넘어갈 때는 아래를 확정해야 한다.

| 우선순위 | 결정 항목 |
|---|---|
| 1 | 비회원 TTL, rate limit, guest-to-user merge 정책 |
| 2 | 히스토리 DB table 전환과 보관 기간 |
| 3 | Agent별 실제 sample output |
| 4 | 리포트 목록/상세/이의신청서 전용 API |
| 5 | 동기/비동기 worker 혼합 방식 |
