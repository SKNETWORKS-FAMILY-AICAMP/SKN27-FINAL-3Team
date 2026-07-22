# 공통 오류·권한 오류·부분 결과 API 응답 의미 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 실제 Django 응답을 바꾸지 않고, shadow OpenAPI가 인증 실패·권한 거부·부분 결과·대기 결과의 의미와 body schema를 정확히 표현하도록 만든다.

**Architecture:** `RouteSpec`에 endpoint별 outcome 응답 메타데이터를 추가하고, OpenAPI 생성기는 기존 success/error 응답과 겹치지 않는 outcome 응답을 `x-response-semantics`로 렌더링한다. 401/403은 기존 `x-error-codes`를 그대로 보존한 상태에서 공통 의미만 추가하며, Django 테스트는 실제 guest credential 경계가 RouteSpec에 누락되지 않도록 고정한다.

**Tech Stack:** Python 3, Pydantic v2, Django test client, Pytest, PyYAML, generated OpenAPI YAML.

## Global Constraints

- Django view, HTTP status, error body, 인증 로직, DB schema와 프런트 UI를 변경하지 않는다.
- `x-response-semantics`는 OpenAPI 확장 메타데이터이며 기존 `x-error-codes`를 대체하거나 축소하지 않는다.
- `POST /api/chat/messages/` 409만 `partial_result` outcome이다. `POST /api/analysis/jobs/` 409은 error envelope로 유지한다.
- `GET /api/analysis/results/{job_id}/` 202만 `pending` outcome이다. `POST /api/analysis/jobs/` 202은 Worker 큐 접수 성공으로 유지한다.
- checklist는 이 정상 작업 PR 안에서 H의 마지막 항목만 갱신한다.

---

## File Structure

- Modify: `backend/chatbot/test_guest_credential_boundary.py` — 보호된 분석 경로의 실제 401 error code/reason 회귀 검증.
- Modify: `app/contracts/api_route_specs.py` — outcome 응답 타입·중복 검증·분석 경로 401 계약·채팅/결과 outcome 선언.
- Modify: `app/contracts/openapi_v1.py` — outcome body schema 및 401/403 공통 의미를 OpenAPI에 생성.
- Modify: `test/test_api_route_specs.py` — RouteSpec 상태 중복 방지와 새 endpoint 선언 검증.
- Modify: `test/test_openapi_v1_generation.py` — 생성 OpenAPI의 의미·schema·409/202 경계 검증.
- Modify: `docs/api/openapi-v1.yaml` — generator 출력 갱신.
- Modify: `docs/ops/project-readiness-master-checklist.md` — H의 공통 계약 항목 완료 근거를 #277로 기록.

### Task 1: 실제 guest credential 401 경계와 분석 RouteSpec 동기화

**Files:**
- Modify: `backend/chatbot/test_guest_credential_boundary.py`
- Modify: `app/contracts/api_route_specs.py`
- Modify: `test/test_api_route_specs.py`

**Interfaces:**
- Consumes: Django middleware의 `build_auth_error("auth_required" | "token_invalid" | "token_expired")` 및 canonical guest policy의 `guest_session_invalid`.
- Produces: 모든 분석 job/list/detail/result 경로에 동일하게 선언되는 401 error-code tuple과 그 런타임 증거.

- [ ] **Step 1: 누락된 401을 재현하는 Django 테스트를 작성한다.**

  `GuestCredentialBoundaryTests`에 raw `X-Guest-Id`만 전달한 GET/POST/list/detail/result 요청을 추가한다. middleware가 view 실행 전에 막는 경로는 임의의 `job_id`를 사용하고, POST는 `submit_message`가 호출되지 않았음을 보장한다.

  ```python
  def test_raw_guest_id_cannot_create_or_read_analysis_resources(self) -> None:
      client = Client(raise_request_exception=False, HTTP_X_GUEST_ID="gst_owner")
      requests = (
          ("get", "/api/analysis/jobs/?session_id=ses_credential_owner", {}),
          ("post", "/api/analysis/jobs/", {"session_id": "ses_credential_owner", "user_text": "start"}),
          ("get", "/api/analysis/jobs/job_credential_boundary/", {}),
          ("get", "/api/analysis/results/job_credential_boundary/", {}),
      )
      for method, path, data in requests:
          response = getattr(client, method)(path, data=data, content_type="application/json")
          self.assertEqual(response.status_code, 401, response.content)
          self.assertEqual(response.json()["error"]["code"], "token_invalid")
          self.assertEqual(response.json()["error"]["auth"]["reason"], "missing_guest_credential")
  ```

- [ ] **Step 2: 새 Django 테스트가 현재 구현에서 통과하고, RouteSpec에는 아직 401이 빠져 있음을 확인한다.**

  Run:

  ```powershell
  & "D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe" backend\manage.py test chatbot.test_guest_credential_boundary
  python -m pytest -q --timeout=30 test/test_api_route_specs.py
  ```

  Expected: Django 테스트는 PASS, 분석 jobs의 401 계약을 새로 assert한 정적 테스트는 아직 FAIL.

- [ ] **Step 3: 확인된 기존 401 code만 RouteSpec에 선언한다.**

  `api_route_specs.py`에 재사용 상수를 두고, `ANALYSIS_JOB_API_ROUTE_SPECS`의 list/create/detail/result 모두에 추가한다. 런타임 code를 임의로 만들지 않는다.

  ```python
  ANALYSIS_IDENTITY_ERROR_CODES = (
      "auth_required",
      "token_invalid",
      "token_expired",
      "guest_session_invalid",
  )

  errors=_analysis_job_errors(
      (401, ANALYSIS_IDENTITY_ERROR_CODES),
      (403, ("object_access_denied",)),
      # endpoint별 기존 error는 그대로 유지
  )
  ```

- [ ] **Step 4: RouteSpec 회귀 테스트를 401 목록까지 확장한다.**

  ```python
  assert {
      error.status: error.codes for error in actual[("GET", "/api/analysis/jobs/")].errors
  }[401] == (
      "auth_required", "token_invalid", "token_expired", "guest_session_invalid"
  )
  ```

- [ ] **Step 5: Task 1 검증 후 커밋한다.**

  Run:

  ```powershell
  & "D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe" backend\manage.py test chatbot.test_guest_credential_boundary
  python -m pytest -q --timeout=30 test/test_api_route_specs.py
  ```

  Expected: PASS.

  ```powershell
  git add backend/chatbot/test_guest_credential_boundary.py app/contracts/api_route_specs.py test/test_api_route_specs.py
  git commit -m "test: align analysis auth error contracts"
  ```

### Task 2: RouteSpec outcome 메타데이터와 경로별 의미 경계 추가

**Files:**
- Modify: `app/contracts/api_route_specs.py`
- Modify: `test/test_api_route_specs.py`

**Interfaces:**
- Consumes: 기존 `RouteSpec.success_statuses`, `RouteErrorSpec`, `ChatMessageResponse`, `AnalysisResultResponse`.
- Produces: `OutcomeResponseSpec(status, semantic, description, response_model)` 및 `RouteSpec.outcome_responses`.

- [ ] **Step 1: outcome 등록 충돌을 막는 실패 테스트를 작성한다.**

  ```python
  with pytest.raises(ValueError, match="outcome status codes must be unique and disjoint"):
      route_specs.RouteSpec(
          operation_id="duplicateOutcome", method="GET", path="/api/contracts/probe/",
          route_name="contract-probe", view_name="probe", request_model=None,
          response_model=contracts.ConsultationCaseListResponse, success_status=200,
          success_statuses=(200,), errors=(), auth_required=False, contract_status="shadow",
          tags=("Contracts",), summary="Contract probe",
          outcome_responses=(route_specs.OutcomeResponseSpec(
              status=200, semantic="pending", description="Still pending",
              response_model=contracts.ConsultationCaseListResponse,
          ),),
      )
  ```

- [ ] **Step 2: 실패를 확인한다.**

  Run: `python -m pytest -q --timeout=30 test/test_api_route_specs.py`

  Expected: FAIL because `OutcomeResponseSpec` and `outcome_responses` do not exist.

- [ ] **Step 3: 최소 outcome 타입과 중복 검증을 구현한다.**

  `RouteSpec` 위에 아래 타입을 추가하고, `RouteSpec.__post_init__`에서 outcome status가 성공·오류 status와 교집합이 없도록 검증한다.

  ```python
  OutcomeSemantic = Literal["partial_result", "pending", "service_unavailable"]

  @dataclass(frozen=True, slots=True)
  class OutcomeResponseSpec:
      status: int
      semantic: OutcomeSemantic
      description: str
      response_model: type[BaseModel]

      def __post_init__(self) -> None:
          if not 100 <= self.status <= 599 or not self.description.strip():
              raise ValueError("outcome status and description are required")
  ```

  ```python
  outcome_statuses = {outcome.status for outcome in self.outcome_responses}
  success_statuses = set(self.success_statuses or (self.success_status,))
  error_statuses = {error.status for error in self.errors}
  if len(outcome_statuses) != len(self.outcome_responses) or outcome_statuses & (success_statuses | error_statuses):
      raise ValueError("outcome status codes must be unique and disjoint")
  ```

- [ ] **Step 4: 실제 경로에만 outcome을 선언한다.**

  ```python
  # POST /api/chat/messages/
  success_statuses=(200, 202),
  outcome_responses=(
      OutcomeResponseSpec(409, "partial_result", "Attachment scan blocked; safe partial guidance is available.", ChatMessageResponse),
      OutcomeResponseSpec(503, "service_unavailable", "Supervisor planning is temporarily unavailable.", ChatMessageResponse),
  ),

  # GET /api/analysis/results/{job_id}/
  success_statuses=(200,),
  outcome_responses=(
      OutcomeResponseSpec(202, "pending", "Analysis result is not ready; continue polling the result endpoint.", AnalysisResultResponse),
  ),
  ```

  `POST /api/analysis/jobs/`의 202/409은 수정하지 않는다.

- [ ] **Step 5: Task 2 검증 후 커밋한다.**

  Run: `python -m pytest -q --timeout=30 test/test_api_route_specs.py`

  Expected: PASS.

  ```powershell
  git add app/contracts/api_route_specs.py test/test_api_route_specs.py
  git commit -m "feat: model semantic API outcomes"
  ```

### Task 3: OpenAPI 의미 렌더링과 schema 회귀 고정

**Files:**
- Modify: `app/contracts/openapi_v1.py`
- Modify: `test/test_openapi_v1_generation.py`

**Interfaces:**
- Consumes: `RouteSpec.outcome_responses`, `RouteErrorSpec.status`, Pydantic schema models.
- Produces: response-level `x-response-semantics`와 outcome response schema의 OpenAPI document/YAML 반영.

- [ ] **Step 1: 생성 OpenAPI에 대한 실패 테스트를 작성한다.**

  `test_chat_routes_document_runtime_identity_and_status_boundaries`와 `test_analysis_job_routes_document_async_owner_scoped_contract`에 다음 경계를 추가한다.

  ```python
  assert message["responses"]["409"]["x-response-semantics"] == "partial_result"
  assert message["responses"]["503"]["x-response-semantics"] == "service_unavailable"
  assert message["responses"]["401"]["x-response-semantics"] == "authentication_failure"
  assert message["responses"]["403"]["x-response-semantics"] == "authorization_denied"
  assert result["responses"]["202"]["x-response-semantics"] == "pending"
  assert "x-response-semantics" not in jobs["post"]["responses"]["202"]
  assert "x-response-semantics" not in jobs["post"]["responses"]["409"]
  ```

  각 outcome response의 `application/json` schema가 원래의 `ChatMessageResponse` 또는 `AnalysisResultResponse` ref인지도 함께 assert한다.

- [ ] **Step 2: 실패를 확인한다.**

  Run: `python -m pytest -q --timeout=30 test/test_openapi_v1_generation.py`

  Expected: FAIL because generator does not yet emit outcome or error semantics metadata.

- [ ] **Step 3: generator를 확장한다.**

  `_component_schemas`가 outcome `response_model`도 수집하도록 하고, success/error와 별도로 `_outcome_response`를 추가한다. 401/403 error response에는 상태별 고정 mapping만 추가한다.

  ```python
  ERROR_RESPONSE_SEMANTICS = {
      401: "authentication_failure",
      403: "authorization_denied",
  }

  def _outcome_response(outcome: OutcomeResponseSpec) -> dict[str, Any]:
      return {
          "description": outcome.description,
          "content": {"application/json": {"schema": _schema_ref(outcome.response_model)}},
          "x-response-semantics": outcome.semantic,
      }
  ```

  오류 response 생성 시 `x-error-codes`는 유지하고, `ERROR_RESPONSE_SEMANTICS.get(error.status)`가 있을 때만 새 키를 병합한다.

- [ ] **Step 4: Task 3 검증 후 커밋한다.**

  Run: `python -m pytest -q --timeout=30 test/test_openapi_v1_generation.py test/test_api_route_specs.py`

  Expected: PASS.

  ```powershell
  git add app/contracts/openapi_v1.py test/test_openapi_v1_generation.py
  git commit -m "feat: document API response semantics"
  ```

### Task 4: Generated OpenAPI·체크리스트 갱신과 통합 검증

**Files:**
- Modify: `docs/api/openapi-v1.yaml`
- Modify: `docs/ops/project-readiness-master-checklist.md`

**Interfaces:**
- Consumes: `scripts/generate_openapi_v1.py`, 완료된 RouteSpec/OpenAPI 회귀.
- Produces: 최신 generated YAML과 #277 근거를 가진 H 완료 항목.

- [ ] **Step 1: OpenAPI YAML을 재생성한다.**

  Run:

  ```powershell
  python scripts/generate_openapi_v1.py
  python scripts/generate_openapi_v1.py --check
  ```

  Expected: 두 번째 명령이 exit code 0으로 종료되고 `docs/api/openapi-v1.yaml`만 generator 결과로 변경된다.

- [ ] **Step 2: H의 마지막 공통 계약 항목만 갱신한다.**

  ```markdown
  - [x] 전체 오류·권한 오류·부분 결과 응답 공통 계약 정리 — #277: 401/403 의미, 채팅 partial/unavailable, 분석 결과 pending OpenAPI·런타임 회귀 검증
  ```

  C, I, OCR 및 다른 H 항목의 상태는 변경하지 않는다.

- [ ] **Step 3: 변경 범위와 통합 회귀를 검증한다.**

  Run:

  ```powershell
  python -m pytest -q --timeout=30 test/test_api_route_specs.py test/test_openapi_v1_generation.py
  & "D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe" backend\manage.py test chatbot.test_guest_credential_boundary chatbot.test_security_hardening chatbot.test_chat_session_api_contract
  python scripts/generate_openapi_v1.py --check
  git diff --check
  git status -sb
  ```

  Expected: 모든 대상 테스트와 generated-file check가 PASS, 변경 파일은 이 계획의 File Structure 목록으로 한정된다.

- [ ] **Step 4: 문서·생성 산출물을 커밋한다.**

  ```powershell
  git add docs/api/openapi-v1.yaml docs/ops/project-readiness-master-checklist.md
  git commit -m "docs: complete common API response contract"
  ```

## Self-Review

- Spec coverage: 401/403 공통 의미는 Task 1·3, 채팅 409/503은 Task 2·3, 결과 조회 202 pending은 Task 2·3, analysis queue 409/202 유지 검증은 Task 2·3, YAML/checklist는 Task 4가 담당한다.
- Placeholder scan: 작업·파일·테스트·명령과 expected result를 모두 명시했으며 미정 구현 항목은 없다.
- Type consistency: `OutcomeResponseSpec`은 Task 2에서 정의하고 Task 3의 `_outcome_response` 및 component schema 수집이 같은 `response_model`을 사용한다.

## Execution Handoff

계획은 `docs/superpowers/plans/2026-07-21-common-api-response-semantics.md`에 저장한다. 이 프로젝트의 현재 작업 방식과 사용자 선호에 따라, 다음 단계는 **인라인 실행**으로 Task 1부터 진행한다.
