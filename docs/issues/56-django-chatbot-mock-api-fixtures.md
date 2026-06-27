# #56 Django mock 챗봇 API와 응답 fixture

| 항목 | 내용 |
|---|---|
| Issue | `#56 django chatbot mock api fixtures` |
| Parent | `#55` |
| Related | `#22`, `#29`, `#40`, `#58` |
| Scope | 실제 Agent 호출 없이 mock response fixture와 Agent/Node 연결 계약 구성 |
| Status | Django mock API + Agent/Node mock runtime + Docker smoke 검증 |
| 작성일 | 2026-06-26 |

## 1. 추가 파일

| 파일 | 역할 |
|---|---|
| `app/services/chatbot_mock_service.py` | 순수 Python mock fixture와 service 함수 |
| `app/services/attachment_mock_service.py` | mock upload 저장과 attachment metadata 생성 |
| `app/services/analysis_job_mock_service.py` | 메시지, plan, node execution을 묶는 mock analysis job 저장/조회 |
| `app/services/agent_adapter_contract.py` | 실제 Agent adapter 함수 시그니처와 output envelope 검증 계약 |
| `app/services/agent_node_service.py` | Agent/Node registry와 mock 실행 envelope |
| `app/api/django_chatbot_mock_views.py` | Django에 연결 가능한 optional view adapter |
| `backend/config/settings.py` | mock API 실행용 최소 Django settings |
| `backend/chatbot/views.py` | mock service를 호출하는 Django JSON view |
| `backend/chatbot/urls.py` | `/api/mock/...` URL 라우팅 |
| `Dockerfile` | 팀원 공유용 Django mock backend 이미지 빌드 |
| `docker-compose.yml` | 팀원 로컬 실행용 compose service |
| `.dockerignore` | 이미지 빌드 context 정리 |

## 2. Endpoint 후보

운영 전환 전 프론트가 canonical `/api/...` 경로로도 붙어볼 수 있도록 shadow endpoint를 둔다. Canonical endpoint는 아직 실제 운영 구현이 아니라 같은 mock service를 재사용하며, JSON 응답에는 `api_surface: "canonical_mock"`, `execution_mode: "mock"`을 포함한다. Canonical 응답 안의 report/file/job 링크도 `/api/...` 형태로 변환한다. 기존 `/api/mock/...` endpoint는 명시적 mock smoke와 회귀 테스트용으로 유지한다.

| Canonical endpoint | Mock endpoint | 목적 |
|---|---|---|
| `POST /api/chat/sessions/` | `POST /api/mock/chat/sessions/` | chat session 생성 |
| `POST /api/chat/messages/` | `POST /api/mock/chat/messages/` | 사용자 질문/첨부 입력 후 분석 응답 반환 |
| `GET/POST /api/files/` | `GET/POST /api/mock/attachments/` | 파일/attachment metadata 등록과 목록 |
| `GET /api/files/{attachment_id}/` | `GET /api/mock/attachments/{attachment_id}/` | 단일 attachment metadata 조회 |
| `GET/POST /api/analysis/jobs/` | `GET/POST /api/mock/analysis/jobs/` | analysis job 목록/생성 |
| `GET /api/analysis/jobs/{job_id}/` | `GET /api/mock/analysis/jobs/{job_id}/` | 단일 analysis job 조회 |
| `GET /api/agents/nodes/` | `GET /api/mock/agents/nodes/` | Agent/Node registry 목록 |
| `POST /api/agents/nodes/run/` | `POST /api/mock/agents/nodes/run/` | 단일 node 실행 envelope |
| `POST /api/agents/plans/run/` | `POST /api/mock/agents/plans/run/` | plan step 전체 node 실행 |
| `POST /api/reports/` | `POST /api/mock/reports/` | 리포트 action |
| `GET /api/reports/{report_id}/download/` | `GET /api/mock/reports/{report_id}/download/` | report 다운로드 |

| Endpoint | 함수 | 목적 |
|---|---|---|
| `GET /api/health/` | `health_check` | backend health와 scenario 목록 |
| `GET /api/mock/attachments/` | `attachments` | session별 attachment metadata 목록 |
| `POST /api/mock/attachments/` | `attachments` | multipart 파일 업로드 또는 JSON metadata 등록 |
| `GET /api/mock/attachments/{attachment_id}/` | `attachment_detail` | 단일 attachment metadata 조회 |
| `GET /api/mock/analysis/jobs/` | `analysis_jobs` | session별 analysis job 목록 |
| `POST /api/mock/analysis/jobs/` | `analysis_jobs` | 메시지, plan, node execution을 묶은 job 생성 |
| `GET /api/mock/analysis/jobs/{job_id}/` | `analysis_job_detail` | 단일 analysis job 상태/결과 조회 |
| `GET /api/mock/agents/nodes/` | `agent_nodes` | Agent/Node registry 목록 |
| `POST /api/mock/agents/nodes/run/` | `run_agent_node` | 단일 node mock 실행 결과 envelope 반환 |
| `POST /api/mock/agents/plans/run/` | `run_agent_plan` | `analysis_plan` steps 전체를 mock node 실행으로 변환 |
| `POST /api/mock/chat/sessions/` | `create_chat_session` | mock chat session 생성 |
| `POST /api/mock/chat/messages/` | `submit_chat_message` | 사용자 질문/첨부 입력 후 mock 분석 결과 반환 |
| `POST /api/mock/reports/` | `report_action` | 리포트 저장/다운로드 mock action |
| `GET /api/mock/reports/{report_id}/download/` | `download_report` | mock report 다운로드 |

## 3. 응답 fixture 상태

| 상태 | 포함 내용 |
|---|---|
| `pending` | 입력 분류 중 progress |
| `partial` | 추가 질문, 제한된 분석 카드 |
| `failed` | 분석 가능한 입력 없음 |
| `success` | 고지서/과실비율 분석 카드와 report action |

각 응답은 Supervisor 호출 계획을 검증할 수 있도록 `analysis_plan`을 포함한다. 화면에는 전체 plan을 그대로 노출하지 않고 `progress`, `pending_questions`, plan step label로 변환하는 것을 우선한다.

| `analysis_plan` field | 목적 |
|---|---|
| `plan_id` | 한 메시지 안에서 호출 계획과 결과를 연결 |
| `input_summary` | 명령문, 첨부, purpose 요약 |
| `required_inputs` | 시나리오별 필수 입력 |
| `steps[]` | node 실행 순서와 상태 |
| `blocked_reason` | 실행 보류 이유 |

## 4. Agent/Node mock runtime

`analysis_plan.steps[].node_code`를 실제 연결 지점으로 쓰기 위해 다음 registry를 둔다.

| node_code | 유형 | 담당 | 현재 구현 범위 |
|---|---|---|---|
| `input_context_validation` | Supervisor internal | `hi20260204-maker` | mock 입력 검증 |
| `fine_notice_analysis` | Agent | `workzion2` | mock 고지서 분석 envelope |
| `law_ground_search` | Agent | `techshin31` | mock 법령 근거 envelope |
| `text_ml_case_search` | Agent | `leejaegang27` | mock 사고 쟁점/유사 사례 envelope |
| `vision_media_analysis` | Agent | `ohjuheecode` | 계약만 등록, mock Vision envelope |
| `objection_report_generation` | Agent | `hi20260204-maker` | mock 이의신청서/리포트 envelope |
| `agent_result_validation` | Supervisor internal | `hi20260204-maker` | mock 최종 검증 envelope |

모든 node mock output은 `node_name`, `node_code`, `status`, `summary`, `structured_result`, `evidence`, `next_actions`, `limitations` 공통 envelope를 반환한다. Plan step의 `blocked`, `running`, `skipped` 상태는 Agent envelope의 `partial` 또는 `failed`로 정규화하고 원본 상태는 `execution_status`로 남긴다.

### 4.1 실제 Agent adapter 함수 계약

실제 Agent 구현체는 `node_code`별로 같은 함수 모양을 따른다. Django mock runtime은 아직 이 함수를 호출하지 않지만, `GET /api/mock/agents/nodes/` 응답의 `adapter_contract`에 함수명, 입력 필드, 출력 필드를 노출한다.

```python
def run_{node_code}(
    agent_input: AgentAdapterInput,
    context: AgentAdapterContext,
) -> AgentAdapterOutput:
    ...
```

예시:

```python
def run_law_ground_search(
    agent_input: AgentAdapterInput,
    context: AgentAdapterContext,
) -> AgentAdapterOutput:
    ...
```

`AgentAdapterInput`의 공통 필드는 다음 기준으로 고정한다.

| Field | 설명 |
|---|---|
| `analysis_plan_id` | 현재 실행이 속한 Supervisor plan |
| `job_id` | 분석 job 식별자 |
| `session_id` / `message_id` | 사용자 세션과 메시지 연결 |
| `node_code` | 실행 대상 node 식별자 |
| `user_text` | 원문 사용자 입력 |
| `attachments` | resolver가 보강한 attachment metadata |
| `context` | 추가 runtime context |
| `required_inputs` | node가 요구하는 입력 조건 |
| `depends_on` | 선행 node 목록 |
| `upstream_results` | 선행 node의 Agent output envelope 모음 |

`AgentAdapterContext`는 `execution_id`, `execution_mode`, `node`, `plan_step`을 포함한다. `AgentAdapterOutput`은 기존 공통 envelope와 동일하게 `node_name`, `node_code`, `status`, `summary`, `structured_result`, `evidence`, `next_actions`, `limitations`, `created_at`을 반환해야 한다. `status`는 `success`, `partial`, `failed` 중 하나만 허용한다.

## 5. Attachment metadata mock

`POST /api/mock/attachments/`는 multipart 파일 업로드와 JSON metadata-only 등록을 모두 지원한다. 반환된 `attachment.agent_handoff`는 그대로 `POST /api/mock/chat/messages/` 또는 `POST /api/mock/agents/plans/run/`의 `attachments[]` 입력으로 사용할 수 있다.

| Field | 설명 |
|---|---|
| `attachment_id` | mock 첨부 식별자 |
| `purpose` | `fine_notice`, `accident_scene`, `evidence`, `accident_statement`, `blackbox_video`, `insurance_record`, `unknown` |
| `type` | `image`, `video`, `pdf`, `text`, `document`, `file` |
| `storage_uri` | `mock://uploads/...` 또는 `mock://metadata/...` |
| `agent_handoff` | Agent/Supervisor에 넘길 최소 첨부 metadata |

파일은 `backend/media/mock_uploads/` 아래에 저장하며 git과 Docker build context에서는 제외한다. 실제 object storage, DB 저장, virus scan, OCR은 아직 수행하지 않는다.

### 5.1 Attachment resolver

`POST /api/mock/chat/messages/`와 `POST /api/mock/agents/plans/run/`는 요청 payload를 처리하기 전에 attachment resolver를 실행한다.

| 입력 형태 | 처리 |
|---|---|
| `{"attachment_id": "att_..."}` | 저장된 metadata sidecar를 찾아 `purpose`, `type`, `storage_uri`, `content_type`, `size_bytes`를 자동 보강 |
| `{"attachment_id": "att_...", "purpose": "...", "type": "..."}` | registry metadata가 없으면 inline metadata로 처리하고 limitation에 기록 |
| `{"attachment_id": "missing"}` | `resolution_status=unresolved`, `unresolved_attachment_ids`에 기록 |

Resolver 결과는 응답의 `attachments[]`, `attachment_resolution`, `analysis_plan.input_summary.modalities`, `analysis_plan.input_summary.attachment_purposes`, node execution의 `agent_input.attachments[]`에 반영된다.

예시:

```json
{
  "session_id": "ses_demo",
  "user_text": "이 고지서로 이의신청서를 만들 수 있을까요?",
  "attachments": [
    {
      "attachment_id": "att_0001"
    }
  ],
  "mock_scenario": "fine_notice"
}
```

위 요청은 내부적으로 다음 handoff metadata로 확장된다.

```json
{
  "attachment_id": "att_0001",
  "purpose": "fine_notice",
  "type": "image",
  "storage_uri": "mock://uploads/att_0001/notice.jpg",
  "content_type": "image/jpeg"
}
```

## 6. Analysis job mock

`analysis job`은 사용자 메시지 1개에서 만들어진 `chat_response`, `analysis_plan`, `node_execution`을 `job_id` 하나로 묶는 추적 단위다. 프론트는 job 생성 후 `GET /api/mock/analysis/jobs/{job_id}/`를 조회해 진행 상태와 결과 묶음을 확인할 수 있다.

| Field | 설명 |
|---|---|
| `job_id` | 분석 작업 식별자 |
| `session_id` / `message_id` | 대화와 사용자 메시지 연결 |
| `status` | `queued`, `running`, `success`, `partial`, `failed` |
| `active_node` | 현재 또는 마지막 활성 node |
| `analysis_plan` | Supervisor 호출 계획 |
| `node_execution` | plan step별 mock Agent 실행 결과 |
| `history` | 상태 변화 기록 |

현재 mock은 실제 queue, Redis, DB 없이 `backend/media/mock_analysis_jobs/{job_id}/job.json`에 저장한다. `mock_status=pending`은 job 상태 `running`으로 매핑하고, `mock_job_status`를 주면 UI 상태 테스트용으로 job status를 강제할 수 있다.

## 7. 중간발표 우선 시나리오

MCP, 외부 법령 API, 최신 판례 조회는 중간발표 범위에서 제외한다. mock service는 앱 흐름 확인을 위해 다음 두 시나리오를 우선 지원한다.

| Scenario | routing_intent | 목적 |
|---|---|---|
| `fine_notice` | `objection_request` | 고지서 분석, 이의신청서 초안, 리포트 저장/다운로드 흐름 |
| `fault_ratio` | `fault_ratio` | 사고 설명 기반 과실비율 쟁점, 유사 사례 후보, 추가 증거 안내 흐름 |

과실비율 시나리오는 수치를 확정하지 않고 `accident_type_candidates`, `issue_tags`, `similar_cases`, `reliability_score`, `ratio_range_label`, `limitations`를 반환한다.

## 8. Docker 실행 기준

팀원은 루트 디렉터리에서 다음 명령으로 동일한 mock backend를 실행한다.

```powershell
docker build -t skn27-demo-backend .
docker run --rm -p 8000:8000 --name skn27-demo-backend skn27-demo-backend
```

또는 Docker Compose를 쓰면 다음 명령만 실행한다.

```powershell
docker compose up --build backend
```

이미지는 `app/`, `backend/`, `requirements.txt`만 포함한다. 실제 배포용 WSGI/ASGI 서버가 아니라 프론트엔드-백엔드 연동 확인을 위한 개발 서버 기준이다.

## 9. 인증/JWT mock 경계

회의 기록의 인증 항목은 `JWT` 기준으로 정정한다. 현재 mock backend는 실제 JWT 서명 검증은 수행하지 않지만, 배포 흐름에 맞춰 보호된 `/api/...`, `/api/mock/...` endpoint에서 `Authorization: Bearer ...` 헤더의 존재와 형식을 확인한다. `MOCK_REQUIRE_AUTH=1`이 기본값이며, `GET /api/health/`, `GET /api/mock/chat/scenarios/`만 공개 endpoint로 둔다.

토큰이 없거나 형식이 맞지 않으면 공통 auth error envelope로 `401`을 반환한다. mock smoke에서는 `Authorization: Bearer dev-mock-token`처럼 임의 Bearer 값을 붙여 보호 endpoint를 호출한다. `Bearer expired`, `Bearer invalid`는 각각 `token_expired`, `token_invalid` 실패 응답을 확인하기 위한 mock 시뮬레이션 값이다.

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

| code | HTTP | reason | required_action |
|---|---:|---|---|
| `auth_required` | 401 | `missing_token` | `login` |
| `token_invalid` | 401 | `invalid_token` 또는 `malformed_authorization_header` | `login` |
| `token_expired` | 401 | `expired_token` | `login` |
| `forbidden` | 403 | `permission_denied` | `none` |

운영 전환 시에는 같은 middleware 위치에서 실제 JWT 검증 또는 DRF authentication layer로 교체하고, 사용자 소유 session/report/file 권한 실패는 같은 envelope의 `forbidden`/`403`으로 반환한다.

## 10. 구현 제외

- 실제 DB 저장
- 실제 async queue, Celery, Redis progress cache
- 실제 object storage 저장
- 실제 virus scan, OCR, 개인정보 masking
- 실제 Agent, RAG, MCP, LLM 호출
- 실제 JWT 서명 검증과 사용자별 리소스 권한 검증

## 11. 검증 기록

- `python backend/manage.py check`
- `python backend/manage.py test chatbot`
- `python -m pytest test/test_chatbot_mock_service.py test/test_agent_node_service.py test/test_attachment_mock_service.py test/test_analysis_job_mock_service.py`
- `docker build -t skn27-demo-backend .`
- `docker compose up --build backend`
- `docker run --rm -d --name skn27-demo-backend-test -p 8001:8000 skn27-demo-backend`
- `GET http://127.0.0.1:8001/api/health/`
- `POST http://127.0.0.1:8001/api/mock/attachments/`
- canonical protected endpoint smoke는 `Authorization: Bearer dev-mock-token` header 포함
- `POST http://127.0.0.1:8001/api/chat/messages/` returns `api_surface=canonical_mock`
- `POST http://127.0.0.1:8001/api/files/`
- `POST http://127.0.0.1:8001/api/analysis/jobs/`
- `GET http://127.0.0.1:8001/api/agents/nodes/`
- explicit mock endpoint smoke도 `Authorization: Bearer dev-mock-token` header 포함
- `GET http://127.0.0.1:8001/api/mock/attachments/?session_id=...`
- `POST http://127.0.0.1:8001/api/mock/chat/messages/` with `attachments=[{"attachment_id": "..."}]`
- `POST http://127.0.0.1:8001/api/mock/analysis/jobs/` with `attachments=[{"attachment_id": "..."}]`
- `GET http://127.0.0.1:8001/api/mock/analysis/jobs/{job_id}/`
- `GET http://127.0.0.1:8001/api/mock/analysis/jobs/?session_id=...`
- `POST http://127.0.0.1:8001/api/mock/agents/plans/run/` with `attachments=[{"attachment_id": "..."}]`
- `GET http://127.0.0.1:8001/api/mock/agents/nodes/`
- `POST http://127.0.0.1:8001/api/mock/agents/plans/run/`
- `POST http://127.0.0.1:8001/api/mock/chat/messages/` with `mock_scenario=fine_notice`
- `POST http://127.0.0.1:8001/api/mock/chat/messages/` with `mock_scenario=fault_ratio`
- no-auth protected endpoint returns `401 auth_required`
- `Authorization: Bearer expired` returns `401 token_expired`

## 12. 검증 필요

- `#22` 공통 result envelope와 필드명 정렬
- `#29` Supervisor routing rule과 fixture intent 정렬
- 담당자별 실제 Agent adapter 구현체 연결
- 실제 업로드 파일 보관 위치와 DB metadata table 연결
- 실제 job 저장소를 PostgreSQL/Redis/Celery 중 어디까지 분리할지 결정
- `analysis_plan`을 실제 API response에 디버그용으로 유지할지 내부 상태로 숨길지 결정
- 운영/배포 단계의 실제 JWT 서명 검증과 사용자별 권한 검증 연결

