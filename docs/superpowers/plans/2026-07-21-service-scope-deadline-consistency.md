# Service Scope and Deadline Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep unsafe or unsupported requests out of execution while showing every verified deadline and every safe next action consistently in the chat and result views.

**Architecture:** The versioned scope policy remains the source of truth. The orchestration layer preserves policy or final-merge safe guidance without changing existing response fields. The frontend derives compact display-only guidance from those compatible fields, validates deadline payloads before rendering, and keeps official DOCX generation outside this work.

**Tech Stack:** Python 3, pytest contract tests, React JSX, CSS, Vite production build, versioned JSON policies.

## Global Constraints

- Do not change official DOCX forms, renderers, report download routes, appeal gates, authentication, ownership, Agent routing, OCR/RAG providers, DB schema, Docker, deployment, or CI workflows.
- Preserve existing API fields and add `next_actions` only as a backward-compatible field.
- `criminal_review` must stop in `expert_handoff`; it must not create an Agent plan, reporting payload, or download path.
- Render a deadline panel only for a valid `deadline_guidance.v1` payload with `overdue`, `due_soon`, `normal`, or `needs_confirmation`.
- `normal` deadlines use `role="status"`; other deadline states use `role="alert"`.
- Do not mark checklist items complete until Python contracts and `app/web` production build pass.

---

## File Structure

- `app/config/service_scope_policy.v1.json`: versioned keyword-to-safe-decision policy; gains the criminal-review boundary.
- `app/services/chat_orchestration_service.py`: retains safe `next_actions` when constructing scope and final Agent responses.
- `app/web/FrontendAppShell.jsx`: converts compatible response fields into compact guidance panels, filters empty deadline objects, and renders the common information notice.
- `app/web/styles.css`: adds neutral deadline and compact safe-guidance styles without changing page layout.
- `test/test_service_scope_policy_service.py`: tests the policy classification matrix.
- `test/test_chat_orchestration_service.py`: tests scope short-circuiting and final-response action preservation.
- `test/test_deadline_guidance_frontend_contract.py`: tests valid-only and all-status deadline rendering.
- `test/test_service_scope_frontend_contract.py`: tests the scope/partial-result UI contract and common notice.
- `docs/ops/project-readiness-master-checklist.md`: records validated #264 completion and OCR work that remains an 이혜림 후순위.

## Task 1: Policy boundary and response-contract preservation

**Files:**
- Modify: `app/config/service_scope_policy.v1.json`
- Modify: `app/services/chat_orchestration_service.py:282-377,464-500`
- Modify: `test/test_service_scope_policy_service.py`
- Modify: `test/test_chat_orchestration_service.py`

**Interfaces:**
- Consumes: `evaluate_service_scope(user_text, attachments, routing_intent) -> dict[str, Any]`.
- Produces: a `service_scope_policy.v1` result with `decision`, `scope_code`, `reason`, `limitations`, and `next_actions`; `chat_message_accepted.v2` responses preserve top-level `next_actions`.

- [ ] **Step 1: Write failing criminal-boundary tests**

```python
def test_criminal_review_requires_expert_handoff() -> None:
    result = evaluate_service_scope(
        user_text="사고 상대방을 형사 고소할 수 있는지 판단해 주세요.",
        attachments=[],
        routing_intent="accident_initial_consultation",
    )

    assert result["scope_code"] == "criminal_review"
    assert result["decision"] == "expert_handoff"
    assert result["limitations"]
    assert result["next_actions"]


def test_criminal_scope_guidance_does_not_create_execution_or_report() -> None:
    response = submit_message(
        {"session_id": "ses_criminal", "user_text": "형사처벌과 고발 가능성을 판정해 주세요."}
    )

    assert response["status"] == "scope_guidance"
    assert response["service_scope"]["scope_code"] == "criminal_review"
    assert response["next_actions"] == response["service_scope"]["next_actions"]
    assert response["analysis_plan"]["status"] == "blocked"
    assert response["analysis_plan"]["steps"] == []
    assert response["reporting_payload"] is None
```

- [ ] **Step 2: Run the new tests and verify RED**

Run: `python -m pytest test/test_service_scope_policy_service.py test/test_chat_orchestration_service.py -q --timeout=30`

Expected: the criminal policy assertion fails because `criminal_review` is absent, and the top-level `next_actions` assertion fails because the field is absent.

- [ ] **Step 3: Add the minimum policy and response fields**

Add this excluded entry before the unrelated-consultation catch-all:

```json
{
  "scope_code": "criminal_review",
  "decision": "expert_handoff",
  "keywords": ["형사", "고소", "고발", "구속"],
  "reason": "형사상 책임이나 처벌 가능성의 판단은 이 서비스에서 제공하지 않습니다.",
  "limitations": [
    "형사상 결론이나 법률 자문을 대신할 수 없으며, 구체적 사실관계와 증거의 확인이 필요합니다."
  ],
  "next_actions": [
    "사고 경위와 증빙자료를 보존한 뒤 필요한 경우 변호사 또는 관계 기관에 상담해 주세요."
  ]
}
```

Add only these compatible fields while retaining existing keys:

```python
# _scope_guidance_response()
"next_actions": list(service_scope["next_actions"]),

# compose_agent_response() final-output branch
"next_actions": list(merged.get("next_actions") or []),
```

- [ ] **Step 4: Add a failing final-response preservation test**

```python
def test_composed_agent_response_preserves_final_next_actions() -> None:
    response = compose_agent_response(
        {
            "job_id": "job_next_actions",
            "executions": [
                {
                    "node_code": "final_response_merge",
                    "agent_output": {
                        "status": "partial",
                        "summary": "추가 근거 확인이 필요합니다.",
                        "structured_result": {
                            "assistant_message": {"answer": "추가 근거 확인이 필요합니다."},
                            "next_actions": ["고지서 원문을 확인해 주세요."],
                        },
                    },
                }
            ],
        }
    )

    assert response["next_actions"] == ["고지서 원문을 확인해 주세요."]
```

- [ ] **Step 5: Run the targeted backend tests and verify GREEN**

Run: `python -m pytest test/test_service_scope_policy_service.py test/test_chat_orchestration_service.py -q --timeout=30`

Expected: all selected tests pass; existing high-risk and supported-scope tests remain green.

- [ ] **Step 6: Commit the backend boundary task**

```powershell
git add app/config/service_scope_policy.v1.json app/services/chat_orchestration_service.py test/test_service_scope_policy_service.py test/test_chat_orchestration_service.py
git commit -m "feat: preserve service scope safety guidance"
```

## Task 2: Test-first frontend guidance and valid deadline handling

**Files:**
- Create: `test/test_service_scope_frontend_contract.py`
- Modify: `test/test_deadline_guidance_frontend_contract.py`
- Modify: `app/web/FrontendAppShell.jsx:114-125,1381-1400,1970-2180,2831-2918,3133-3140`
- Modify: `app/web/styles.css:35-70`

**Interfaces:**
- Consumes: `analysisResponse.service_scope`, `analysisResponse.limitations`, `analysisResponse.next_actions`, and `analysisResponse.deadline_guidance`.
- Produces: `SafetyGuidancePanel`, `ServiceInformationNotice`, and valid-only `DeadlineGuidancePanel` rendering without changing report or download actions.

- [ ] **Step 1: Write failing static frontend-contract tests**

```python
def test_frontend_renders_scope_and_partial_result_safe_guidance() -> None:
    shell = (ROOT / "app" / "web" / "FrontendAppShell.jsx").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "web" / "styles.css").read_text(encoding="utf-8")

    assert "function SafetyGuidancePanel({ guidance })" in shell
    assert "const serviceScope = analysisResponse?.service_scope || null;" in shell
    assert "const responseNextActions = stringList(analysisResponse?.next_actions);" in shell
    assert "<SafetyGuidancePanel guidance={chatSafetyGuidance} />" in shell
    assert "<SafetyGuidancePanel guidance={resultSafetyGuidance} />" in shell
    assert "function ServiceInformationNotice()" in shell
    assert ".safety-guidance-panel" in styles


def test_frontend_only_renders_valid_deadline_guidance_and_treats_normal_as_neutral() -> None:
    shell = (ROOT / "app" / "web" / "FrontendAppShell.jsx").read_text(encoding="utf-8")

    assert "function isDeadlineGuidance(value)" in shell
    assert "const deadlineGuidance = isDeadlineGuidance(analysisResponse?.deadline_guidance)" in shell
    assert "{deadlineGuidance && (" in shell
    assert 'role={guidance.status === "normal" ? "status" : "alert"}' in shell
    assert 'deadlineGuidance.status !== "normal"' not in shell
```

- [ ] **Step 2: Run the frontend-contract tests and verify RED**

Run: `python -m pytest test/test_deadline_guidance_frontend_contract.py test/test_service_scope_frontend_contract.py -q --timeout=30`

Expected: the new test file fails because the safety components and valid deadline guard do not exist; the existing deadline test needs updating from the old nullable-object contract.

- [ ] **Step 3: Add the smallest display helpers and panels**

At module scope, define:

```jsx
const DEADLINE_GUIDANCE_STATUSES = new Set(["overdue", "due_soon", "normal", "needs_confirmation"]);

function stringList(value) {
  return Array.isArray(value) ? value.map((item) => String(item || "").trim()).filter(Boolean) : [];
}

function isDeadlineGuidance(value) {
  return Boolean(
    value &&
      value.contract_version === "deadline_guidance.v1" &&
      DEADLINE_GUIDANCE_STATUSES.has(value.status)
  );
}
```

Derive `serviceScope`, `responseLimitations`, `responseNextActions`, and `deadlineGuidance` in `FrontendAppShell`; pass a normalized `chatSafetyGuidance` to `ChatScreenV2` and `resultSafetyGuidance` to `CaseResultScreen`. `SafetyGuidancePanel` renders only a title, reason, string-list limitations, and string-list actions. `ServiceInformationNotice` renders the exact text `이 서비스는 법률 자문이나 개별 사건의 확정 판단을 대신하지 않으며, 확인할 사실과 근거를 정리합니다.`

Render `ServiceInformationNotice` in `CaseResultScreen` and `ReportingScreen`. Render `SafetyGuidancePanel` below the latest assistant message and at the top of `CaseResultScreen` only when its guidance has a reason, limitation, or action. Do not render it in the DOCX pipeline.

Render `DeadlineGuidancePanel` whenever `deadlineGuidance` is valid. Change its role to:

```jsx
role={guidance.status === "normal" ? "status" : "alert"}
```

Use `deadlineGuidance?.deadline` before `findReportText(...)` for the fine-result deadline metric.

- [ ] **Step 4: Add minimal neutral and guidance styles**

Add `.deadline-guidance-panel--normal` with a neutral border/background, then add `.safety-guidance-panel` and `.service-information-notice` using the existing panel spacing, border-radius, and typography tokens. Do not alter grid, navigation, button, image, or mock-data styles.

- [ ] **Step 5: Run frontend contract tests and production build to verify GREEN**

Run:

```powershell
python -m pytest test/test_deadline_guidance_frontend_contract.py test/test_service_scope_frontend_contract.py -q --timeout=30
npm run build
```

Working directory for the second command: `app/web`.

Expected: contract tests pass and Vite emits a production build without JSX syntax errors.

- [ ] **Step 6: Commit the UI-contract task**

```powershell
git add app/web/FrontendAppShell.jsx app/web/styles.css test/test_deadline_guidance_frontend_contract.py test/test_service_scope_frontend_contract.py
git commit -m "feat: surface safe scope and deadline guidance"
```

## Task 3: Checklist evidence and full verification

**Files:**
- Modify: `docs/ops/project-readiness-master-checklist.md`

**Interfaces:**
- Consumes: passing Task 1 and Task 2 tests plus a successful frontend build.
- Produces: evidence-backed #264 checklist state; OCR evaluation work remains explicitly open.

- [ ] **Step 1: Run the complete #264 regression set**

Run:

```powershell
python -m pytest test/test_service_scope_policy_service.py test/test_chat_orchestration_service.py test/test_deadline_guidance_service.py test/test_deadline_guidance_frontend_contract.py test/test_service_scope_frontend_contract.py test/test_supervisor_control_service.py -q --timeout=30
```

Expected: all selected tests pass. If the project test environment is unavailable, stop before the checklist edit and resolve the environment without changing product code.

- [ ] **Step 2: Update only validated checklist rows**

Replace the six unchecked service-safety rows with `[x]` rows referencing `#264` only after Step 1 passes. Keep the OCR rows incomplete, but append these ownership markers:

```markdown
- [?] OCR 모델 비용·성능·속도 비교 기반 — 이혜림 후순위: 실제 Provider 실행과 집계 결과 필요
- [ ] 기관 양식·저해상도·촬영 각도·손상·흐림 문서 평가 세트 — 이혜림 후순위: 정답지 포함 Golden set 필요
- [ ] 문서 유형별 OCR 및 필드 추출 정확도 측정 — 이혜림 후순위: 실제 정답 대비 평가 결과 필요
```

Do not change the low-confidence OCR UX row because it remains the separate UI/UX scope.

- [ ] **Step 3: Re-run the checklist-adjacent regression set and build**

Run the Step 1 pytest command again, then run `npm run build` from `app/web`.

Expected: all tests and the production build remain green after documentation-only changes.

- [ ] **Step 4: Review and commit the completed scope**

```powershell
git diff --check
git status -sb
git diff --stat origin/dev...HEAD
git add docs/ops/project-readiness-master-checklist.md
git commit -m "docs: record service scope safety verification"
```

The final review must verify that only the planned policy, orchestration, frontend, test, design/plan, and checklist files changed.
