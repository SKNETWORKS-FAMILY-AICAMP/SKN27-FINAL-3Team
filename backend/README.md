# Django Demo Backend Workspace

중간발표용 mock API 워크스페이스다. 실제 Agent, RAG, MCP, 외부 API 호출 없이 프론트엔드가 앱 흐름을 붙일 수 있도록 최소 Django endpoint를 제공한다.

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

보호된 mock endpoint는 배포 흐름과 맞추기 위해 `Authorization: Bearer ...` 헤더가 필요하다.

```powershell
Invoke-RestMethod `
  -Headers @{ Authorization = "Bearer dev-mock-token" } `
  http://127.0.0.1:8000/api/mock/agents/nodes/
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
  -e MOCK_REQUIRE_AUTH=1 `
  -e DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1 `
  --name skn27-demo-backend `
  skn27-demo-backend
```

## 인증/JWT 경계

현재 mock API는 실제 JWT 서명 검증은 수행하지 않는다. 대신 `MOCK_REQUIRE_AUTH=1`을 기본값으로 두고 보호된 `/api/mock/...` endpoint에서 `Authorization: Bearer ...` 헤더의 존재와 형식을 확인한다. 토큰이 없거나 형식이 맞지 않으면 운영 전환 때 사용할 공통 auth error envelope로 `401`을 반환한다.

공개 endpoint는 `GET /api/health/`, `GET /api/mock/chat/scenarios/`로 제한한다. 운영 전환 시에는 같은 middleware 위치에서 실제 JWT 검증 또는 DRF authentication layer로 교체하고, 권한 부족은 같은 envelope의 `forbidden`/`403`으로 반환한다.

인증 실패 응답 예시:

```json
{
  "error": {
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

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health/` | backend health와 demo scenario 목록 |
| `GET` | `/api/mock/chat/scenarios/` | `fine_notice`, `fault_ratio` 시나리오 목록 |
| `GET` | `/api/mock/attachments/` | session별 mock attachment metadata 목록 |
| `POST` | `/api/mock/attachments/` | multipart 파일 업로드 또는 JSON metadata 등록 |
| `GET` | `/api/mock/attachments/{attachment_id}/` | 단일 attachment metadata 조회 |
| `GET` | `/api/mock/analysis/jobs/` | session별 mock analysis job 목록 |
| `POST` | `/api/mock/analysis/jobs/` | 메시지, plan, node 실행을 job으로 묶어 생성 |
| `GET` | `/api/mock/analysis/jobs/{job_id}/` | 단일 analysis job 상태와 결과 조회 |
| `GET` | `/api/mock/agents/nodes/` | Agent/Node registry 목록 |
| `POST` | `/api/mock/agents/nodes/run/` | 단일 Agent/Node mock 실행 envelope 반환 |
| `POST` | `/api/mock/agents/plans/run/` | `analysis_plan` 기반 전체 node mock 실행 |
| `POST` | `/api/mock/chat/sessions/` | mock chat session 생성 |
| `POST` | `/api/mock/chat/messages/` | 챗봇 mock 분석 응답 반환 |
| `POST` | `/api/mock/reports/` | 리포트 저장/다운로드 action mock |
| `GET` | `/api/mock/reports/{report_id}/download/` | mock report 다운로드 |

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
  -Headers @{ Authorization = "Bearer dev-mock-token" } `
  http://127.0.0.1:8000/api/mock/agents/nodes/
```

## 발표 우선 범위

- 과태료/이의신청 흐름: `mock_scenario=fine_notice`
- 과실비율 흐름: `mock_scenario=fault_ratio`
- 파일/첨부 metadata 연결: `POST /api/mock/attachments/`
- 분석 job 추적: `POST /api/mock/analysis/jobs/`, `GET /api/mock/analysis/jobs/{job_id}/`
- Agent/Node 연결 경계: `GET /api/mock/agents/nodes/`, `POST /api/mock/agents/plans/run/`
- JWT 인증은 현재 mock에서 Bearer 헤더 형식과 실패 envelope까지 연결, 운영 전환 때 실제 JWT 서명/권한 검증으로 교체
- MCP, 최신 법령 조회, 외부 API, 실제 ML/RAG 호출은 제외

