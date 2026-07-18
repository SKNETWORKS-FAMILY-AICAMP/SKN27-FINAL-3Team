# Service Scope and Deadline Guardrails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop unsupported consultations before planning or reporting, and return one reusable deadline-guidance contract in final user results.

**Architecture:** A versioned JSON policy plus `service_scope_policy_service` will make all scope decisions before the Supervisor/LLM or plan. A separate deadline-guidance service will decorate verified `appeal_decision_flow` output; it must not recalculate or replace the existing statutory deadline logic.

**Tech Stack:** Python, Django API views, React, JSON policy configuration, pytest, Django test runner.

## Global Constraints

- Work only on `feat/223-service-scope-deadline-guardrails`; the user performs Git add/commit/push/PR/merge.
- Korean copy and deadline thresholds live in policy files, never in views or React event handlers.
- Scope guidance has no executable plan steps, queue work item, reporting payload, or report generation.
- Only explicit policy categories may be automated; unknown or excluded categories receive safe guidance.
- Preserve the existing privacy, attachment-scan, case-evidence, and statutory-deadline gates.

---

### Task 1: Versioned scope policy and evaluator

**Files:**

- Create: `app/config/service_scope_policy.v1.json`
- Create: `app/services/service_scope_policy_service.py`
- Test: `test/test_service_scope_policy_service.py`

**Consumes:** `user_text: str`, `attachments: list[dict[str, Any]]`, `routing_intent: str`.

**Produces:** `evaluate_service_scope(...) -> dict[str, Any]`:
`contract_version`, `decision` (`proceed`, `guidance_only`, `expert_handoff`), `scope_code`, `reason`, `limitations`, and `next_actions`.

- [ ] **Step 1: Write the failing tests**

```python
from app.services.service_scope_policy_service import evaluate_service_scope


def test_vehicle_pedestrian_collision_requires_expert_handoff() -> None:
    result = evaluate_service_scope(
        user_text="차가 보행자와 충돌한 사고의 과실을 확정해 주세요.",
        attachments=[],
        routing_intent="accident_initial_consultation",
    )

    assert result["decision"] == "expert_handoff"
    assert result["scope_code"] == "vehicle_pedestrian_collision"


def test_vehicle_to_vehicle_accident_can_proceed() -> None:
    result = evaluate_service_scope(
        user_text="교차로에서 두 차량이 충돌한 과실 쟁점을 정리해 주세요.",
        attachments=[],
        routing_intent="accident_initial_consultation",
    )

    assert result["decision"] == "proceed"


def test_fine_notice_analysis_is_in_scope() -> None:
    result = evaluate_service_scope(
        user_text="과태료 고지서를 받았습니다.",
        attachments=[{"attachment_id": "att_1", "purpose": "fine_notice"}],
        routing_intent="fine_notice_analysis",
    )

    assert result["decision"] == "proceed"
```

- [ ] **Step 2: Prove the tests fail**

Run: `D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q test/test_service_scope_policy_service.py`

Expected: import failure.

- [ ] **Step 3: Implement the declarative policy**

Use this policy structure, adding Korean `reason`, `limitations`, and `next_actions` for every excluded case:

```json
{
  "contract_version": "service_scope_policy.v1",
  "supported_intents": [
    "accident_initial_consultation",
    "fine_notice_analysis",
    "fine_notice_procedure",
    "traffic_law_search"
  ],
  "excluded_cases": [
    {
      "scope_code": "vehicle_pedestrian_collision",
      "decision": "expert_handoff",
      "keywords": ["보행자", "횡단보도"]
    },
    {
      "scope_code": "vehicle_cycle_collision",
      "decision": "expert_handoff",
      "keywords": ["자전거", "킥보드"]
    },
    {
      "scope_code": "facility_collision",
      "decision": "guidance_only",
      "keywords": ["시설물", "가드레일", "전봇대"]
    },
    {
      "scope_code": "civil_liability_determination",
      "decision": "guidance_only",
      "keywords": ["민사 과실 확정", "법적 확정 판결"]
    }
  ]
}
```

The service uses `lru_cache`, validates the policy version/types, normalizes text once, applies exclusions before supported intents, and returns `guidance_only` for any non-supported intent.

- [ ] **Step 4: Verify**

Run: `D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q test/test_service_scope_policy_service.py`

Expected: PASS.

### Task 2: Stop unsupported chat and direct plan execution

**Files:**

- Modify: `app/services/chat_orchestration_service.py:submit_message`
- Modify: `backend/chatbot/views.py:submit_chat_message,run_agent_plan`
- Modify: `test/test_chat_orchestration_service.py`
- Modify: `backend/chatbot/test_consultation_v2.py`

**Consumes:** the Task 1 evaluator immediately after `route_supervisor_input`.

**Produces:** `chat_message_accepted.v2` with `status: "scope_guidance"`, `service_scope`, no plan steps, and no reporting payload.

- [ ] **Step 1: Write failing regressions**

```python
def test_unsupported_accident_does_not_call_supervisor_or_create_plan(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.chat_orchestration_service.build_supervisor_state_with_optional_llm",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    response = submit_message({
        "session_id": "ses_scope",
        "user_text": "차와 보행자가 충돌한 사고 과실을 확정해 주세요.",
    })

    assert response["status"] == "scope_guidance"
    assert response["analysis_plan"]["steps"] == []
    assert response["reporting_payload"] is None
    assert response["service_scope"]["decision"] == "expert_handoff"
```

```python
def test_scope_guidance_chat_endpoint_does_not_enqueue_job(self):
    response = self.client.post(
        "/api/chat/messages/",
        data={"user_text": "보행자와 충돌한 사고 과실을 확정해 주세요."},
        content_type="application/json",
    )

    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.json()["execution_mode"], "scope_guidance")
    self.assertNotIn("work_item", response.json())
```

- [ ] **Step 2: Prove the tests fail**

Run: `D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q test/test_chat_orchestration_service.py backend/chatbot/test_consultation_v2.py`

Expected: excluded input reaches accident consultation or queueing.

- [ ] **Step 3: Implement one scope response builder**

In `chat_orchestration_service.py`, return a private `_scope_guidance_response` when the decision is not `proceed`:

```python
{
    "contract_version": "chat_message_accepted.v2",
    "status": "scope_guidance",
    "assistant_message": {"answer": scope["reason"], "summary": scope["reason"]},
    "service_scope": scope,
    "analysis_plan": {"contract_version": "analysis_plan.v2", "steps": []},
    "reporting_payload": None,
    "limitations": scope["limitations"],
}
```

In `submit_chat_message`, return it before usage/queue persistence with `execution_mode: "scope_guidance"`. In `run_agent_plan`, return the non-executed response when `submit_message` supplies `scope_guidance`, rather than passing an empty plan to `execute_agent_plan`.

- [ ] **Step 4: Verify the boundary and privacy regression**

Run: `D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q test/test_chat_orchestration_service.py backend/chatbot/test_consultation_v2.py test/test_chat_input_privacy.py`

Expected: PASS.

### Task 3: Deadline-guidance contract and user-visible priority card

**Files:**

- Create: `app/config/deadline_guidance_policy.v1.json`
- Create: `app/services/deadline_guidance_service.py`
- Modify: `app/services/supervisor_control_service.py:merge_final_response`
- Modify: `app/services/chat_orchestration_service.py:compose_agent_response`
- Modify: `app/services/analysis_job_query_service.py:load_analysis_result`
- Modify: `app/web/FrontendAppShell.jsx:CaseResultScreen`
- Test: `test/test_deadline_guidance_service.py`
- Modify: `test/test_supervisor_control_service.py`
- Modify: `test/test_chat_orchestration_service.py`
- Modify: `test/test_analysis_job_query_service.py`

**Consumes:** verified `appeal_decision_flow` fields `computed_deadline` and `deadline_passed`.

**Produces:** `deadline_guidance.v1` with `status` (`overdue`, `due_soon`, `normal`, `needs_confirmation`), `deadline`, `days_remaining`, `source_node_code`, `limitations`, and `next_actions`.

- [ ] **Step 1: Write failing service and merge tests**

```python
from datetime import date, timedelta

from app.services.deadline_guidance_service import build_deadline_guidance


def test_due_soon_deadline_is_explicitly_highlighted() -> None:
    result = build_deadline_guidance(
        {
            "computed_deadline": (date.today() + timedelta(days=3)).isoformat(),
            "deadline_passed": False,
        },
        source_node_code="appeal_decision_flow",
    )

    assert result["status"] == "due_soon"
    assert result["days_remaining"] == 3


def test_missing_deadline_requests_confirmation_without_guessing() -> None:
    result = build_deadline_guidance({}, source_node_code="appeal_decision_flow")

    assert result["status"] == "needs_confirmation"
    assert result["deadline"] is None
```

```python
def test_final_merge_places_deadline_card_before_agent_cards() -> None:
    merged = merge_final_response(
        {
            "agent_result_validation": {
                "structured_result": {"accepted_results": ["appeal_decision_flow"]}
            },
            "appeal_decision_flow": {
                "status": "success",
                "summary": "ok",
                "structured_result": {
                    "computed_deadline": "2099-01-01",
                    "deadline_passed": False,
                },
                "evidence": [],
            },
        },
    )

    assert merged["deadline_guidance"]["contract_version"] == "deadline_guidance.v1"
    assert merged["cards"][0]["card_type"] == "deadline_guidance"
```

- [ ] **Step 2: Prove the tests fail**

Run: `D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q test/test_deadline_guidance_service.py test/test_supervisor_control_service.py test/test_chat_orchestration_service.py`

Expected: import/contract failure.

- [ ] **Step 3: Implement policy-driven presentation metadata**

`deadline_guidance_policy.v1.json` owns `due_soon_days` and all Korean messages/actions. The service parses only ISO dates already emitted by the verified agent; missing/invalid dates return `needs_confirmation`.

`merge_final_response` inspects only accepted `appeal_decision_flow` output, preserves the normal agent result, adds `deadline_guidance`, and prepends a `deadline_guidance` card for `overdue`, `due_soon`, and `needs_confirmation`. `compose_agent_response` must preserve that object. `load_analysis_result` must retain the composed deadline card ahead of persisted cards, so async polling has the identical contract.

Pass `deadlineGuidance={analysisResponse?.deadline_guidance}` into `CaseResultScreen`. Render a top warning panel only from this contract; remove no existing cards and do not use static deadlines.

- [ ] **Step 4: Verify service, async result, and web build**

Run: `D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q test/test_deadline_guidance_service.py test/test_supervisor_control_service.py test/test_chat_orchestration_service.py test/test_analysis_job_query_service.py`

Expected: PASS.

Run in `D:\dev\project\SKN27-issue223-scope-deadline\app\web`: `npm run build`

Expected: PASS.

### Task 4: Tracker update and final regression

**Files:**

- Modify: `docs/ops/project-readiness-master-checklist.md`
- Modify: `backend/chatbot/test_production_hardening.py`

- [ ] **Step 1: Record proven #222 completion**

Change only the six complete A-2 fact/claim/evidence entries and recommended sequence item 2 to `[x] #221 / PR #222`. Do not mark the Supervisor end-to-end or real generative-agent items complete.

- [ ] **Step 2: Add API regression**

```python
def test_chat_scope_guidance_is_a_safe_client_response(self):
    response = self.client.post(
        "/api/chat/messages/",
        data={"user_text": "차와 보행자 충돌 사고의 과실을 확정해 주세요."},
        content_type="application/json",
    )

    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.json()["status"], "scope_guidance")
    self.assertEqual(response.json()["analysis_plan"]["steps"], [])
```

- [ ] **Step 3: Run backend regression**

Run: `D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe backend/manage.py test chatbot.test_consultation_v2 chatbot.test_production_hardening -v 1`

Expected: PASS.

- [ ] **Step 4: Run final scoped suite**

Run: `D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q test/test_service_scope_policy_service.py test/test_deadline_guidance_service.py test/test_chat_orchestration_service.py test/test_supervisor_control_service.py test/test_analysis_job_query_service.py`

Expected: PASS.

## Plan Self-Review

- Task 1 removes hardcoded scope matching; Task 2 guarantees excluded cases never create a Supervisor/agent/report workload; Task 3 exposes deadline urgency without changing legal computation; Task 4 records only verified tracker completion.
- Preserved: privacy, attachment scans, case-evidence gating, existing statutory date calculations, and existing supported-agent plans.
- Still open after this PR: full Supervisor-to-agent E2E, real generative runtime failure simulation, cross-user authorization E2E, OCR benchmarks, legal-data freshness, report API, and conversation-memory contracts.
