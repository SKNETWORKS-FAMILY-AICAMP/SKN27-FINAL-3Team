# Django Demo Backend Workspace

Django canonical API 워크스페이스다. 운영 경로는 실제 인증과 Agent adapter를 사용하고, 명시적인 `/api/mock/...` alias만 회귀 테스트용 mock 경계로 남긴다.

## 실행

```powershell
python backend/manage.py runserver 127.0.0.1:8000
```

## Docker 실행

루트 디렉터리에서 백엔드 이미지를 빌드한다.

```powershell
docker build -t skn27-demo-backend .
```

컨테이너를 실행한다.

```powershell
docker run --rm -p 8000:8000 --name skn27-demo-backend skn27-demo-backend
```

공개 health endpoint 실행 확인:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health/
```

보호된 endpoint는 배포 흐름과 맞추기 위해 `Authorization: Bearer ...` 헤더가 필요하다.

```powershell
Invoke-RestMethod `
  -Headers @{ Authorization = "Bearer <app-jwt-issued-after-google-login>" } `
  http://127.0.0.1:8000/api/agents/nodes/
```

Docker Compose를 쓰면 빌드와 실행을 한 번에 처리할 수 있다.

```powershell
docker compose up --build backend
```

필요하면 실행 시 환경변수를 덮어쓸 수 있다.

```powershell
docker run --rm -p 8000:8000 `
  -e DJANGO_SECRET_KEY=dev-secret `
  -e DJANGO_DEBUG=1 `
  -e DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1 `
  --name skn27-demo-backend `
  skn27-demo-backend
```

## 인증/JWT 경계

보호된 canonical endpoint는 백엔드가 발급한 app JWT의 서명, issuer, audience, 만료, DB의 활성 `auth_session`을 검증한다. 토큰이 없거나 잘못됐거나 이미 revoke된 경우 `auth_error.v1` envelope와 `WWW-Authenticate` header로 `401`을 반환한다.

유일한 공개 Google 로그인 경계는 `POST /api/auth/google/code/`다. 프론트는 Google Identity Services `google.accounts.oauth2.initCodeClient()`로 authorization code만 받고, 공개 client ID, 정확한 frontend origin, `X-Requested-With: XmlHttpRequest` header와 함께 백엔드로 전송한다. 백엔드는 요청 origin/client ID/redirect origin을 서버 설정과 비교한 뒤 Google token endpoint에서 code를 한 번 교환하고, 검증된 Google `sub`를 `social_accounts.provider_user_id`로 저장한다. 로그인 전용 Google access/refresh/ID token은 신원 확인 직후 폐기하며 저장하거나 클라이언트에 반환하지 않는다.

실제 Google Code Flow 모드는 다음 환경변수가 필요하다.

- `GOOGLE_CLIENT_ID=<Google OAuth web client id>`
- `GOOGLE_CLIENT_SECRET=<Google OAuth client secret>`
- `GOOGLE_POPUP_REDIRECT_URI=<frontend origin, 예: http://127.0.0.1:5173>`
- `VITE_GOOGLE_CLIENT_ID=<same frontend client id>`
- `APP_JWT_SECRET=<32자 이상의 app JWT secret>`
- `OAUTH_TOKEN_SECRET=<32자 이상의 별도 OAuth integration secret>`
- `GOOGLE_OAUTH_CODE_EXCHANGE_DAILY_LIMIT=20`
- `GOOGLE_OAUTH_TRUSTED_PROXY_CIDRS=<trusted reverse-proxy CIDRs only; empty for direct access>`

Google 로그인 관점에서 인증 없이 호출되는 공개 login endpoint는 `POST /api/auth/google/code/` 하나다. 그 밖의 보호된 canonical endpoint는 app JWT와 활성 `auth_session`을 요구하며, 권한 부족은 같은 envelope의 `forbidden`/`403`으로 반환한다.

인증 실패 응답 예시:

```json
{
  "error": {
    "contract_version": "auth_error.v1",
    "type": "auth",
    "code": "auth_required",
    "message": "로그인이 필요합니다.",
    "status": 401,
    "missing_fields": [],
    "retryable": false,
    "required_action": "login",
    "auth": {
      "scheme": "Bearer",
      "reason": "missing_token"
    }
  }
}
```

## 주요 endpoint

운영 후보 URL은 canonical `/api/...` 형태로 먼저 호출할 수 있다. 이 경로도 내부적으로는 mock service를 사용하므로 JSON 응답에 `api_surface: "canonical_mock"`, `execution_mode: "mock"`을 포함한다. Canonical 응답에 포함된 report/file/job 링크도 `/api/...` 형태로 변환된다. 기존 `/api/mock/...` 경로는 회귀 테스트와 명시적 mock smoke용으로 계속 유지한다.

| Method | Canonical path | Mock path |
|---|---|---|
| `POST` | `/api/auth/guest-session/` | - |
| `POST` | `/api/auth/google/code/` | - |
| `POST` | `/api/auth/refresh/` | - |
| `POST` | `/api/auth/logout/` | - |
| `GET` | `/api/auth/me/` | - |
| `GET` | `/api/mypage/summary/` | - |
| `GET` | `/api/history/` | `/api/mock/history/` |
| `POST` | `/api/chat/sessions/` | `/api/mock/chat/sessions/` |
| `POST` | `/api/chat/messages/` | `/api/mock/chat/messages/` |
| `GET`/`POST` | `/api/files/` | `/api/mock/attachments/` |
| `GET` | `/api/files/{attachment_id}/` | `/api/mock/attachments/{attachment_id}/` |
| `GET`/`POST` | `/api/analysis/jobs/` | `/api/mock/analysis/jobs/` |
| `GET` | `/api/analysis/jobs/{job_id}/` | `/api/mock/analysis/jobs/{job_id}/` |
| `GET` | `/api/analysis/results/{job_id}/` | `/api/mock/analysis/results/{job_id}/` |
| `GET` | `/api/agents/nodes/` | `/api/mock/agents/nodes/` |
| `POST` | `/api/agents/nodes/run/` | `/api/mock/agents/nodes/run/` |
| `POST` | `/api/agents/plans/run/` | `/api/mock/agents/plans/run/` |
| `POST` | `/api/reports/` | `/api/mock/reports/` |
| `GET` | `/api/reports/{report_id}/download/` | `/api/mock/reports/{report_id}/download/` |

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health/` | backend health와 demo scenario 목록 |
| `POST` | `/api/auth/guest-session/` | 비회원 `guest_id`, rate limit key, merge policy mock 발급 |
| `POST` | `/api/auth/google/code/` | Google Authorization Code Flow로 app Bearer token 발급, `social_accounts` 저장, 로그인용 provider token 폐기 |
| `POST` | `/api/auth/refresh/` | Rotate a valid app Bearer token for the same `auth_session_id` |
| `POST` | `/api/auth/logout/` | Revoke the current `auth_session_id` and return client clear-token action |
| `GET` | `/api/auth/me/` | 현재 Bearer/guest identity와 `auth_session_id` 분리 상태 확인 |
| `GET` | `/api/mypage/summary/` | canonical My Case progress summary from `analysis_jobs`, `analysis_job_events`, `agent_results`, `analysis_display_results`, and `reports` |
| `GET` | `/api/history/` | `history_event.v1` 표준-라이트 mock sidecar 이벤트 조회 |
| `GET` | `/api/mock/chat/scenarios/` | `fine_notice`, `fault_ratio` 시나리오 목록 |
| `GET` | `/api/mock/attachments/` | session별 mock attachment metadata 목록 |
| `POST` | `/api/mock/attachments/` | multipart 파일 업로드 또는 JSON metadata 등록 |
| `GET` | `/api/mock/attachments/{attachment_id}/` | 단일 attachment metadata 조회 |
| `GET` | `/api/mock/analysis/jobs/` | session별 mock analysis job 목록 |
| `POST` | `/api/mock/analysis/jobs/` | 메시지, plan, node 실행을 job으로 묶어 생성 |
| `GET` | `/api/mock/analysis/jobs/{job_id}/` | 단일 analysis job 상태와 결과 조회 |
| `GET` | `/api/mock/analysis/results/{job_id}/` | 화면 표시용 analysis result DTO 조회 |
| `GET` | `/api/mock/agents/nodes/` | Agent/Node registry 목록 |
| `POST` | `/api/mock/agents/nodes/run/` | 단일 Agent/Node mock 실행 envelope 반환 |
| `POST` | `/api/mock/agents/plans/run/` | `analysis_plan` 기반 전체 node mock 실행 |
| `POST` | `/api/mock/chat/sessions/` | mock chat session 생성 |
| `POST` | `/api/mock/chat/messages/` | 챗봇 mock 분석 응답 반환 |
| `POST` | `/api/mock/reports/` | 리포트 저장/다운로드 action mock |
| `GET` | `/api/mock/reports/{report_id}/download/` | mock report 다운로드 |

## History event

Canonical `GET /api/history/?session_id=...`는 PostgreSQL `history_events`의 `history_event.v1` 표준-라이트 이벤트를 조회한다. 명시적 `/api/mock/history/`만 `backend/media/mock_history_events` sidecar JSON을 유지한다. 현재 정책은 `standard_light`이며 사용자 원문, OCR 원문, Agent reasoning 전문은 저장하지 않는다.

테스트나 로컬 실험에서 저장 위치를 분리하려면 `MOCK_HISTORY_EVENT_ROOT` 환경변수를 사용한다.

## Attachment handoff 예시

업로드 또는 metadata 등록 후 받은 `attachment_id`만 챗봇 요청에 넘겨도 backend가 저장된 metadata를 자동으로 붙인다.

```json
{
  "session_id": "ses_demo",
  "user_text": "이 고지서로 이의신청서를 만들 수 있을까요?",
  "attachments": [
    {
      "attachment_id": "att_0001"
    }
  ],
  "mock_scenario": "fine_notice",
  "mock_status": "success"
}
```

응답의 `analysis_plan.input_summary`에는 저장된 `purpose`, `type`이 반영된다.

## Analysis job 예시

Canonical `POST /api/analysis/jobs/`는 실행 가능한 plan을 검증한 뒤 `analysis_jobs`, 최초 `analysis_job_events`, `agent_work_items`만 queued 상태로 저장하고 `202 Accepted`를 반환한다. Agent 실행과 `agent_results`, `ai_sessions`, `agent_invocations` 저장은 worker가 work item을 claim한 뒤 수행한다. caller-supplied `job_id`는 session과 요청 지문에 묶여 동일 요청은 재사용되고 다른 요청은 `409`로 거절된다. 명시적 `/api/mock/analysis/jobs/`는 회귀 테스트와 smoke check를 위해 sidecar-only로 유지한다.

분석 job은 메시지 1개에서 시작된 `chat_response`, `analysis_plan`, `node_execution`을 `job_id`로 묶는다.

```json
{
  "session_id": "ses_demo",
  "user_text": "이 고지서로 이의신청서를 만들 수 있을까요?",
  "attachments": [
    {
      "attachment_id": "att_0001"
    }
  ],
  "mock_scenario": "fine_notice",
  "mock_status": "success"
}
```

`POST /api/mock/analysis/jobs/` 응답의 `status`는 `queued`, `running`, `success`, `partial`, `failed` 중 하나다. 현재 mock backend는 실제 queue 없이 즉시 실행한 결과를 JSON sidecar로 저장한다.

## Analysis result display DTO

Canonical `GET /api/analysis/results/{job_id}/` saves the display snapshot to `analysis_display_results` when the matching canonical `analysis_jobs` row exists. Explicit `/api/mock/analysis/results/{job_id}/` remains sidecar-only.

`GET /api/mock/analysis/results/{job_id}/`는 프론트 화면이 바로 사용하는 표시용 결과를 반환한다. Canonical shadow endpoint는 `GET /api/analysis/results/{job_id}/`이며 응답에 `api_surface: "canonical_mock"`, `execution_mode: "mock"`을 포함하고 report/file/job 링크를 `/api/...` 형태로 변환한다.

반환 필드는 `assistant_message`, `progress`, `cards`, `pending_questions`, `attachments`, `report_links`, `evidence`, `agent_results`, `limitations` 중심이다. 디버깅용 원본 묶음인 `analysis_plan`, `node_execution`, `chat_response`는 `GET /api/mock/analysis/jobs/{job_id}/`에서만 조회한다.

Canonical `POST /api/reports/` saves report metadata to `reports` and links it to `analysis_jobs` plus `analysis_display_results` when available. It now wraps the generated artifact in an `object_storage_adapter.v1` envelope and stores an `s3://...` adapter URI while keeping the original mock URI as `source_storage_uri`.

Canonical `GET /api/reports/{report_id}/download/`는 `reports` table을 먼저 확인한다. metadata가 있으면 요청 subject와 `reports.owner_id`를 비교해 소유자만 다운로드할 수 있고, 성공 응답에는 `X-Report-Persistence`, `X-Report-Storage-Backend`, `X-Report-Storage-URI`, `X-Report-Object-Key`, `X-Report-Object-Policy`, `X-Report-Access-Decision`을 포함한다. metadata가 없으면 기존 mock text download로 fallback한다.

## Redis status

Current status: Docker Compose now includes a Redis 7 service and the backend uses
`REDIS_URL` to switch Django cache to `django.core.cache.backends.redis.RedisCache`.
When `REDIS_URL` is absent, local tests use `LocMemCache`. Redis stores only short
TTL progress snapshots for `analysis_job_progress:{job_id}` and
`chat_session_state:{session_id}`; PostgreSQL remains the fallback source of truth.

Redis는 `chat_session_state:{session_id}`, `analysis_job_progress:{job_id}` 같은 짧은 TTL 캐시로 연결되어 있다. 현재 구현은 PostgreSQL `analysis_jobs`, `analysis_job_events`, `usage_events`, `history_events`를 기준 저장소로 유지하고, Redis miss나 장애 시 PostgreSQL fallback을 사용한다.

## My Case summary

Canonical `GET /api/mypage/summary/?session_id=...`는 Supervisor-facing 내 사건 read model을 반환한다. 조회 경로는 PostgreSQL metadata 기준이며 `chat_sessions`, `chat_messages`, `analysis_jobs`, `analysis_job_events`, `agent_results`, `ai_sessions`, `agent_invocations`, `analysis_display_results`, `reports`를 읽는다.

The response includes active case counts, saved report counts, recent analysis count, and compact case rows with agent/result/report linkage. Deadline calculation, real JWT ownership checks, and subscription/rate-limit enforcement remain explicit limitations for the next auth/session pass.

## Agent adapter 계약

`GET /api/mock/agents/nodes/` 응답의 각 node에는 `adapter_contract`가 포함된다. 실제 Agent 구현체는 이 계약의 함수명과 입출력 필드를 맞춘다.

```python
def run_{node_code}(
    agent_input: AgentAdapterInput,
    context: AgentAdapterContext,
) -> AgentAdapterOutput:
    ...
```

공통 입력은 `analysis_plan_id`, `job_id`, `session_id`, `message_id`, `node_code`, `user_text`, `attachments`, `context`, `required_inputs`, `depends_on`, `upstream_results`를 포함한다. 출력은 `node_name`, `node_code`, `status`, `summary`, `structured_result`, `evidence`, `next_actions`, `limitations`, `created_at` 공통 envelope를 반환하며 `status`는 `success`, `partial`, `failed`만 사용한다.

## 테스트

```powershell
python backend/manage.py check
python backend/manage.py test chatbot
python -m pytest test/test_chatbot_mock_service.py test/test_agent_node_service.py test/test_attachment_mock_service.py test/test_analysis_job_mock_service.py
```

Docker 실행 후 smoke check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health/
Invoke-RestMethod `
  -Headers @{ Authorization = "Bearer <app-jwt-issued-after-google-login>" } `
  http://127.0.0.1:8000/api/agents/nodes/
```

## 발표 우선 범위

- 과태료/이의신청 흐름: `mock_scenario=fine_notice`
- 과실비율 흐름: `mock_scenario=fault_ratio`
- 파일/첨부 metadata 연결: `POST /api/files/`, mock alias `POST /api/mock/attachments/`
- 분석 job 추적: `POST /api/analysis/jobs/`, `GET /api/analysis/jobs/{job_id}/`
- 분석 결과 표시: `GET /api/analysis/results/{job_id}/`, mock alias `GET /api/mock/analysis/results/{job_id}/`
- Agent/Node 연결 경계: `GET /api/agents/nodes/`, `POST /api/agents/plans/run/`
- JWT 인증은 현재 mock에서 Bearer 헤더 형식과 실패 envelope까지 연결, 운영 전환 때 실제 JWT 서명/권한 검증으로 교체
- MCP, 최신 법령 조회, 외부 API, 실제 ML/RAG 호출은 제외

