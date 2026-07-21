# Agent Node Public Result Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `GET /api/analysis/results/{job_id}/`가 Worker 내부 실행 데이터 대신 화면용 Agent 결과 DTO만 반환하도록 고정한다.

**Architecture:** `analysis_job_query_service`가 Composer 결과와 저장 결과를 새 공개 DTO로 투영한다. 중첩 Supervisor·보고서·Worker 객체는 명시적 허용 필드만 복사하고, Agent별 사용자 표시 결과인 노드 `structured_result`는 보존한다. Django API 경로와 단위 테스트가 같은 계약을 검증한다.

**Tech Stack:** Python 3, Django, pytest, React/Vite 생산 빌드

## Global Constraints

- `analysis_result.v2`와 현재 프런트가 소비하는 표시·폴링 필드는 유지한다.
- 개별 OCR/RAG/Vision/과실비율 Agent, DB 스키마, Worker 실행, DOCX 정책, UI 구조를 변경하지 않는다.
- 결과 조회 API에서 Worker 계획·입력·실행 원문·보고서 `form_data`를 노출하지 않는다.
- 기존 auth·소유권 검증을 우회하지 않는다.
- 체크리스트는 모든 검증이 통과한 경우에만 같은 PR에서 갱신한다.

---

## 파일 구조

- Modify: `app/services/analysis_job_query_service.py`
  - 결과 조회 전용 public projection helper와 pending/completed 결과 조립.
- Modify: `test/test_analysis_job_query_service.py`
  - 실제 AgentAdapterOutput 형태 fixture를 통한 허용·제외·불변성 단위 회귀 테스트.
- Modify: `backend/chatbot/test_analysis_job_queue.py`
  - 인증된 실제 `GET /api/analysis/results/{job_id}/` 경로의 공개 DTO 검증.
- Modify: `backend/chatbot/tests.py`
  - mock 결과 경로의 legacy 상위 `agent_results` 기대값을 node 표시 결과 계약으로 정정.
- Modify: `docs/ops/project-readiness-master-checklist.md`
  - 최종 검증 성공 뒤 `에이전트 노드 API 계약` 완료 처리.

## Task 1: 공개 DTO 계약 테스트를 먼저 고정한다

**Files:**

- Modify: `test/test_analysis_job_query_service.py`
- Modify: `backend/chatbot/test_analysis_job_queue.py`
- Modify: `backend/chatbot/tests.py`

**Interfaces:**

- Consumes: `load_analysis_result(job_id, load_job, compose_response)`
- Produces: 구현이 만족해야 할 public 결과 필드와 금지 필드 회귀 계약

- [ ] **Step 1: 실제형 Agent output fixture를 만든다.**

  `test/test_analysis_job_query_service.py`에 다음과 같은 terminal job fixture를 둔다.

  ```python
  stored = {
      "job_id": "job_public_contract",
      "status": "success",
      "agent_results": [
          {
              "node_code": "law_ground_search",
              "status": "success",
              "summary": "관련 법령을 찾았습니다.",
              "structured_result": {"matched_laws": [{"title": "도로교통법"}]},
              "evidence": [{"source_reference": "law:1"}],
              "next_actions": ["근거를 확인해 주세요."],
              "limitations": ["개별 판단은 확인이 필요합니다."],
          }
      ],
      "reporting_payload": {
          "title": "이의신청 초안",
          "sections": [{"title": "신청 이유", "content": "표시용 내용"}],
          "form_data": {"applicant_name": "internal-only"},
      },
      "supervisor_state": {
          "stage": "agent_execution_ready",
          "agent_input_packages": [
              {"node_code": "objection_report_generation", "payload": {"secret": "hidden"}}
          ],
      },
      "supervisor_execution": {
          "job_id": "job_public_contract",
          "plan_id": "plan_internal",
          "node_results": [
              {
                  "node_code": "law_ground_search",
                  "status": "success",
                  "structured_result": {"matched_laws": [{"title": "도로교통법"}]},
                  "agent_input": {"secret": "hidden"},
              }
          ],
      },
      "supervisor_reporting_handoff": {"secret": "hidden"},
      "reporting_pipeline": {"secret": "hidden"},
  }
  ```

- [ ] **Step 2: 실패하는 단위 계약 테스트를 추가한다.**

  ```python
  original = deepcopy(stored)
  outcome = load_analysis_result(
      "job_public_contract",
      load_job=lambda _job_id: stored,
      compose_response=lambda _payload: {
          "contract_version": "analysis_result.v2",
          "assistant_message": {"answer": "분석 결과"},
          "structured_results": {"law_ground_search": {"internal": True}},
          "limitations": ["개별 판단은 확인이 필요합니다."],
          "next_actions": ["근거를 확인해 주세요."],
          "deadline_guidance": {"contract_version": "deadline_guidance.v1"},
      },
  )

  assert outcome.payload["supervisor_state"]["agent_input_packages"] == [
      {"node_code": "objection_report_generation"}
  ]
  assert outcome.payload["supervisor_execution"]["node_results"][0]["structured_result"] == {
      "matched_laws": [{"title": "도로교통법"}]
  }
  assert "form_data" not in outcome.payload["reporting_payload"]
  assert "plan_id" not in outcome.payload["supervisor_execution"]
  assert "agent_input" not in outcome.payload["supervisor_execution"]["node_results"][0]
  assert "structured_results" not in outcome.payload
  assert "agent_results" not in outcome.payload
  assert "supervisor_reporting_handoff" not in outcome.payload
  assert "reporting_pipeline" not in outcome.payload
  assert stored == original
  ```

- [ ] **Step 3: pending DTO 테스트를 보강한다.**

  `work_item`의 `work_item_id`, `job_id`, `status`, 재시도 수와 `progress_state`의
  `job_status`가 남고, 임의 내부 키는 사라지는 실패 테스트를 추가한다.

  ```python
  assert outcome.payload["work_item"] == {
      "contract_version": "agent_worker_queue.v1",
      "work_item_id": "work_1",
      "job_id": "job_queued",
      "status": "queued",
  }
  assert outcome.payload["progress_state"]["job_status"] == "queued"
  assert "worker_payload" not in outcome.payload["work_item"]
  ```

- [ ] **Step 4: 실패를 확인한다.**

  Run:

  ```powershell
  python -m pytest -p no:timeout -p no:cacheprovider test/test_analysis_job_query_service.py -q
  ```

  Expected: 새 공개 DTO 테스트가 현재 통째로 복사되는 `form_data`, `plan_id`, 입력
  payload 또는 상위 `structured_results` 때문에 실패한다.

- [ ] **Step 5: 실제 API와 mock 기대값을 추가·정정한다.**

  `backend/chatbot/test_analysis_job_queue.py`의 인증된 queue→worker→result 흐름에서
  결과 body에 `analysis_plan`, `node_execution`, `chat_response`, 상위
  `agent_results`, `structured_results`가 없고, `supervisor_execution.node_results`의
  `node_code`, `status`, `summary`, `structured_result`는 남는지 검증한다.

  `backend/chatbot/tests.py`의 mock 결과 테스트는 상위 `agent_results` 존재 assertion을
  제거하고 동일 Agent 표시 정보가 `supervisor_execution.node_results`에 있는지 검증한다.

- [ ] **Step 6: 테스트 변경을 커밋한다.**

  ```powershell
  git add test/test_analysis_job_query_service.py backend/chatbot/test_analysis_job_queue.py backend/chatbot/tests.py
  git commit -m "test: define public analysis result dto contract"
  ```

## Task 2: 결과 조회 서비스에 명시적 투영을 구현한다

**Files:**

- Modify: `app/services/analysis_job_query_service.py`
- Test: `test/test_analysis_job_query_service.py`

**Interfaces:**

- Consumes: Composer 결과와 `get_analysis_job_record()`가 반환하는 저장 job dict
- Produces: `load_analysis_result()`의 `AnalysisJobQueryOutcome.payload`

- [ ] **Step 1: 필드 집합과 범용 복사 helper를 정의한다.**

  ```python
  _REPORTING_PAYLOAD_FIELDS = (
      "contract_version", "stage", "report_id", "report_type", "title", "summary",
      "sections", "document_cards", "document_variant", "document_confirmation",
      "report_actions", "appeal_gate",
  )
  _SUPERVISOR_STATE_FIELDS = (
      "contract_version", "stage", "conversation_summary", "collected_facts",
      "missing_fields", "next_questions",
  )
  _NODE_RESULT_FIELDS = (
      "node_code", "status", "summary", "structured_result", "evidence",
      "next_actions", "limitations",
  )

  def _project_mapping(value: Any, fields: tuple[str, ...]) -> dict[str, Any]:
      if not isinstance(value, dict):
          return {}
      return {field: deepcopy(value[field]) for field in fields if field in value}
  ```

- [ ] **Step 2: 중첩 public projection helper를 구현한다.**

  ```python
  def _project_supervisor_state(value: Any) -> dict[str, Any]:
      projected = _project_mapping(value, _SUPERVISOR_STATE_FIELDS)
      packages = value.get("agent_input_packages") if isinstance(value, dict) else None
      if isinstance(packages, list):
          projected["agent_input_packages"] = [
              {"node_code": item["node_code"]}
              for item in packages
              if isinstance(item, dict) and isinstance(item.get("node_code"), str)
          ]
      return projected

  def _project_supervisor_execution(value: Any) -> dict[str, Any]:
      source = value if isinstance(value, dict) else {}
      projected = _project_mapping(
          source,
          ("contract_version", "execution_mode", "job_id", "work_item"),
      )
      projected["node_results"] = [
          _project_mapping(item, _NODE_RESULT_FIELDS)
          for item in source.get("node_results", [])
          if isinstance(item, dict)
      ]
      return projected
  ```

  Add analogous helpers for reporting payload, work item, and progress state. Work item
  retains `contract_version`, `work_item_id`, `job_id`, `status`, `attempt_no`,
  `max_attempts`, `next_run_at`, and projected progress state. Progress state retains
  `contract_version`, `state`, `work_item_status`, `job_status`, `attempt_no`,
  `max_attempts`, `retryable`, `retry_after_seconds`, and `next_run_at`.

- [ ] **Step 3: pending·completed 응답을 새 DTO로 조립한다.**

  ```python
  def _public_result_base(*, job_id: str, status: str, composed: dict[str, Any]) -> dict[str, Any]:
      return {
          "contract_version": str(composed.get("contract_version") or "analysis_result.v2"),
          "job_id": job_id,
          "status": status,
          "assistant_message": deepcopy(composed.get("assistant_message")),
          "evidence": deepcopy(composed.get("evidence") or []),
          "limitations": deepcopy(composed.get("limitations") or []),
          "next_actions": deepcopy(composed.get("next_actions") or []),
          "deadline_guidance": deepcopy(composed.get("deadline_guidance") or {}),
      }
  ```

  Use this base for completed results, then add merged cards, persisted display fields,
  and the nested projection helpers. Build pending results from an empty display base and
  projected worker state. Do not mutate `job` or `compose_response()` output.

- [ ] **Step 4: unit tests가 통과하는지 확인한다.**

  Run:

  ```powershell
  python -m pytest -p no:timeout -p no:cacheprovider test/test_analysis_job_query_service.py -q
  ```

  Expected: 모든 query-service 테스트 통과.

- [ ] **Step 5: 구현을 커밋한다.**

  ```powershell
  git add app/services/analysis_job_query_service.py test/test_analysis_job_query_service.py
  git commit -m "feat: project public analysis result dto"
  ```

## Task 3: 통합 회귀 검증과 체크리스트 갱신을 완료한다

**Files:**

- Modify: `docs/ops/project-readiness-master-checklist.md`
- Test: `backend/chatbot/test_analysis_job_queue.py`
- Test: `backend/chatbot/test_resource_ownership_e2e.py`
- Test: `backend/chatbot/test_guest_login_session_ownership_e2e.py`
- Test: `app/web` production build

**Interfaces:**

- Consumes: Task 1~2의 공개 결과 DTO
- Produces: API·소유권·프런트 빌드 검증 근거와 Issue #268 체크리스트 완료 상태

- [ ] **Step 1: 결과 API와 소유권 회귀 테스트를 실행한다.**

  ```powershell
  python -m pytest -p no:timeout -p no:cacheprovider `
    test/test_analysis_job_query_service.py `
    backend/chatbot/test_analysis_job_queue.py `
    backend/chatbot/test_resource_ownership_e2e.py `
    backend/chatbot/test_guest_login_session_ownership_e2e.py -q
  ```

  Expected: 대상 테스트 전부 통과. `python-docx`가 없는 로컬 가상환경이면 프로젝트
  의존성이 설치된 가상환경으로 전환한 뒤 같은 명령을 재실행한다.

- [ ] **Step 2: 프런트 생산 빌드를 실행한다.**

  ```powershell
  npm run build
  ```

  Working directory: `app/web`

  Expected: Vite production build 성공.

- [ ] **Step 3: 체크리스트를 갱신한다.**

  `docs/ops/project-readiness-master-checklist.md`에서 `에이전트 노드 API 계약` 항목만
  `[x]`로 바꾸고 Issue `#268`과 검증 범위를 짧게 기록한다. OCR 평가·모델 선정·UI/UX
  후순위 항목은 변경하지 않는다.

- [ ] **Step 4: 최종 변경을 커밋한다.**

  ```powershell
  git add backend/chatbot/test_analysis_job_queue.py backend/chatbot/tests.py docs/ops/project-readiness-master-checklist.md
  git commit -m "test: verify public agent result contract"
  ```

- [ ] **Step 5: 작업 브랜치를 푸시한다.**

  ```powershell
  git push origin test/268-agent-node-public-result-contract
  ```

## 계획 자체 검토

- Spec coverage: public DTO 투영, pending/completed 경계, Supervisor·보고서·Worker 내부
  제외, 실제 API 경로, 소유권 회귀, 프런트 빌드, 체크리스트 갱신을 각각 Task 1~3에
  배정했다.
- Placeholder scan: 구현 대상·테스트·명령·허용 필드를 모두 명시했고 미정 항목은 없다.
- Type consistency: 모든 테스트는 `load_analysis_result()`와
  `supervisor_execution.node_results`를 기준으로 하며, 구현 helper의 입력은 `Any`, 출력은
  `dict[str, Any]`로 통일한다.
