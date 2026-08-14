# Django Demo Backend Workspace

Django canonical API 워크스페이스다. 기본 `config.urls`는 canonical `/api/...`만 등록하며, 운영 요청은 실제 인증·repository·queue·worker·Agent adapter 경계를 사용한다.

Explicit Mock Runtime은 test/demo 전용으로 완전히 분리돼 있다. `/api/mock/...`는 기본 URLConf나 Production settings에 등록되지 않는다. 사용하려면 `EXPLICIT_MOCK_RUNTIME_ENABLED=True`, `DEBUG=True`, `ROOT_URLCONF=config.mock_urls`를 모두 명시해야 한다. canonical 공개 label은 `canonical`, Explicit Mock 공개 label은 `explicit_mock`이며 두 runtime의 label을 섞지 않는다.

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

운영 URL은 canonical `/api/...`로만 호출하며 response의 report/file/job 링크도 `/api/...`를 사용한다. `config.mock_urls`를 명시적으로 선택한 test/demo 프로세스에서만 아래 Explicit Mock subset이 별도 sidecar runtime으로 열릴 수 있다.

| Method | Canonical path | Explicit Mock path (`config.mock_urls` only) |
|---|---|---|
| `GET` | `/api/history/` | `/api/mock/history/` |
| `GET`/`POST` | `/api/files/` | `/api/mock/attachments/` |
| `GET`/`POST` | `/api/analysis/jobs/` | `/api/mock/analysis/jobs/` |
| `POST` | Canonical Agent/Worker boundary | `/api/mock/agents/plans/` |
| `GET`/`POST` | `/api/reports/` | 없음 |

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health/` | backend health와 demo scenario 목록 |
| `POST` | `/api/auth/guest-session/` | 비회원 `guest_id`, rate limit key, merge policy mock 발급 |
| `POST` | `/api/auth/google/code/` | Google Authorization Code Flow로 app Bearer token 발급, `social_accounts` 저장, 로그인용 provider token 폐기 |
| `POST` | `/api/auth/refresh/` | Rotate a valid app Bearer token for the same `auth_session_id` |
| `POST` | `/api/auth/logout/` | Revoke the current `auth_session_id` and return client clear-token action |
| `GET` | `/api/auth/me/` | 현재 Bearer/guest identity와 `auth_session_id` 분리 상태 확인 |
| `GET` | `/api/mypage/summary/` | canonical My Case progress summary from `analysis_jobs`, `analysis_job_events`, `agent_results`, `analysis_display_results`, and `reports` |
| `GET` | `/api/history/` | PostgreSQL `history_events`의 public DTO 조회 |
| `GET`/`POST` | `/api/files/` | canonical attachment staging, quarantine, scan worker 경계 |
| `GET`/`POST` | `/api/analysis/jobs/` | canonical queue와 worker 상태 조회/생성 |
| `GET` | `/api/agents/nodes/` | production-callable Agent capability 조회 |
| `GET`/`POST` | `/api/reports/` | canonical report public DTO 조회 및 worker-owned action 경계 |

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
  ]
}
```

응답의 `analysis_plan.input_summary`에는 저장된 `purpose`, `type`이 반영된다.

## Analysis job 예시

Canonical `POST /api/analysis/jobs/`는 실행 가능한 plan을 검증한 뒤 `analysis_jobs`, 최초 `analysis_job_events`, `agent_work_items`만 queued 상태로 저장하고 `202 Accepted`를 반환한다. Agent 실행과 `agent_results`, `ai_sessions`, `agent_invocations` 저장은 worker가 work item을 claim한 뒤 수행한다. caller-supplied `job_id`는 session과 요청 지문에 묶여 동일 요청은 재사용되고 다른 요청은 `409`로 거절된다.

분석 job은 메시지 1개에서 시작된 `chat_response`, `analysis_plan`, `node_execution`을 `job_id`로 묶는다.

```json
{
  "session_id": "ses_demo",
  "user_text": "이 고지서로 이의신청서를 만들 수 있을까요?",
  "attachments": [
    {
      "attachment_id": "att_0001"
    }
  ]
}
```

Explicit Mock의 analysis-job sidecar는 `config.mock_urls`를 명시적으로 선택한 test/demo 프로세스에서만 사용할 수 있다. Canonical `AnalysisJob`에는 mock marker나 sidecar URI를 새로 저장하지 않는다.

## Analysis result display DTO

Canonical `GET /api/analysis/results/{job_id}/`는 일치하는 canonical `analysis_jobs` row의 display snapshot을 `analysis_display_results`에 저장한다. 공개 응답은 `api_surface: "canonical"`을 사용하며, Explicit Mock sidecar와 섞지 않는다.

반환 필드는 `assistant_message`, `progress`, `cards`, `pending_questions`, `attachments`, `report_links`, `evidence`, `agent_results`, `limitations` 중심이다.

Canonical `POST /api/reports/`는 report metadata를 `reports`에 저장하고 가능한 경우 `analysis_jobs`, `analysis_display_results`와 연결한다. artifact는 `object_storage_adapter.v1`과 canonical `s3://...` storage contract로 관리한다.

Canonical `GET /api/reports/{report_id}/download/`는 `reports` table과 요청 subject의 소유권을 검증한다. 성공 header의 `X-API-Surface`는 `canonical`, worker 결과의 `X-Execution-Mode`는 `async_worker`다.

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

`GET /api/agents/nodes/` 응답의 각 node에는 `adapter_contract`가 포함된다. 실제 Agent 구현체는 이 계약의 함수명과 입출력 필드를 맞춘다.

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

- 과태료/이의신청 흐름: canonical Agent/Worker contract
- 과실비율 흐름: canonical Agent/Worker contract
- 파일/첨부 metadata 연결: `POST /api/files/`
- 분석 job 추적: `POST /api/analysis/jobs/`, `GET /api/analysis/jobs/{job_id}/`
- 분석 결과 표시: `GET /api/analysis/results/{job_id}/`
- Agent/Node 연결 경계: `GET /api/agents/nodes/`
- JWT 인증은 app JWT 서명과 활성 `auth_session`을 검증
- MCP, 최신 법령 조회, 외부 API, 실제 ML/RAG 호출은 제외

