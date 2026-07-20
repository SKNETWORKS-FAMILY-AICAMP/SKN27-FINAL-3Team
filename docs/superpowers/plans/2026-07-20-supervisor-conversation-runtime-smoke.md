# Supervisor Conversation Runtime Smoke Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

Goal: Add a strict runtime smoke from the public chat endpoint through Worker and Reporting, while preventing generic report-download guidance.

Architecture: A new Django management command submits one sanitized fixture through chatbot.views.submit_chat_message, processes the returned work item with the existing Worker, then checks the public result DTO and persisted Reporting bundle. Tests inject fake Supervisor and Agent adapters, so CI never calls external LLMs, S3, or paid providers.

Tech Stack: Python 3.13, Django TestCase and RequestFactory, pytest, Vite.

## Global Constraints

- Never modify, merge, or delete issue/objection-report-generation.
- General analysis reports have no download_report action or download file.
- Official objection DOCX requires the existing appeal gate and final confirmation.
- Strict provider-capable execution requires --allow-paid-provider-call and a clean S3 canonical/acceptance fixture.
- JSON, documents, and captured evidence must not contain PII, prompts, provider raw output, secrets, or storage URIs.
- CI must use fake providers and adapters only.

---

### Task 1: Keep general reports view-only

Files:
- Modify: ai/agents/objection_report_generation/agent.py:1185-1201
- Modify: test/test_agent_node_service.py:118-141

Interfaces:
- Consumes: _next_actions(missing_fields, appeal_blocked=False)
- Produces: review_objection_draft, download_objection, review_report_screen

- [ ] Step 1: add the failing regression test.

    def test_objection_agent_next_actions_keep_general_report_view_only():
        next_actions = objection_agent._next_actions([], appeal_blocked=False)
        assert "review_report_screen" in next_actions
        assert "download_report" not in next_actions

- [ ] Step 2: run:
  D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q test\test_agent_node_service.py -k general_report_view_only

  Expected: failure because the current output contains download_report.

- [ ] Step 3: replace only the final normal-path element in _next_actions.

    return [
        "review_objection_draft",
        "download_objection",
        "review_report_screen",
    ]

- [ ] Step 4: run:
  D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q test\test_agent_node_service.py

  Expected: selected tests pass and no report action exposes download_report.

- [ ] Step 5: commit:
  git add ai/agents/objection_report_generation/agent.py test/test_agent_node_service.py
  git commit -m "fix: keep general reports view-only"

### Task 2: Add the public-chat runtime smoke command

Files:
- Create: backend/chatbot/management/commands/smoke_supervisor_conversation_runtime.py
- Create: backend/chatbot/test_supervisor_conversation_runtime_smoke.py

Interfaces:
- Consumes: chatbot.views.submit_chat_message(request), repositories.process_agent_work_item(work_item_id), canonical result read endpoint
- Produces: supervisor_conversation_runtime_smoke.v1 JSON and CommandError when a required check fails

- [ ] Step 1: add a failing success-path test.

    def test_command_uses_public_chat_then_persists_worker_reporting_bundle(self):
        result = self._run_smoke_with_fake_supervisor_and_adapters()
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["chat"]["status"], "queued")
        self.assertEqual(result["chat"]["execution_mode"], "async_worker")
        self.assertTrue(result["checks"]["persisted_handoff_consumed"])
        self.assertTrue(result["checks"]["report_ready"])
        self.assertTrue(result["checks"]["public_result_loaded"])

- [ ] Step 2: run:
  D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe backend\manage.py test chatbot.test_supervisor_conversation_runtime_smoke.SupervisorConversationRuntimeSmokeTests.test_command_uses_public_chat_then_persists_worker_reporting_bundle -v 1

  Expected: command module import fails before it exists.

- [ ] Step 3: implement the minimum command.

    result = {
        "contract_version": "supervisor_conversation_runtime_smoke.v1",
        "status": "pass" if not failed_checks else "fail",
        "chat": {
            "http_status": status_code,
            "status": body["status"],
            "execution_mode": body["execution_mode"],
        },
        "llm": safe_llm_status,
        "checks": checks,
        "failed_checks": failed_checks,
    }

  The command rejects a missing paid-call consent or invalid clean fixture before creating a session, job, work item, report, or paid guard. In strict mode it requires --require-llm-used, --require-real-agent-results, --require-persisted-handoff, and --require-report. It must submit through the canonical chat view, process only its returned work item, and read the canonical result DTO.

- [ ] Step 4: run:
  D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe backend\manage.py test chatbot.test_supervisor_conversation_runtime_smoke -v 1

  Expected: fake Supervisor and Agent adapters complete without external network or paid calls.

- [ ] Step 5: commit:
  git add backend/chatbot/management/commands/smoke_supervisor_conversation_runtime.py backend/chatbot/test_supervisor_conversation_runtime_smoke.py
  git commit -m "test: add supervisor conversation runtime smoke"

### Task 3: Verify fallback, safe failure, and DOCX policy

Files:
- Modify: backend/chatbot/test_supervisor_conversation_runtime_smoke.py
- Modify: test/test_consultation_v2_contract.py
- Modify: backend/chatbot/test_supervisor_reporting_pipeline.py:2034-2075

Interfaces:
- Consumes: LLM statuses used, disabled, failed; public supervisor_unavailable response; existing confirmation and download view
- Produces: fallback-not-strict evidence, queue-free 503 evidence, confirmed official DOCX, and rejected general-report download

- [ ] Step 1: add failing tests.

    def test_disabled_llm_is_reported_but_fails_require_llm_used(self):
        result = self._run_smoke_with_disabled_supervisor()
        self.assertEqual(result["llm"]["status"], "disabled")
        self.assertIn("llm_used", result["failed_checks"])

    def test_failed_supervisor_returns_503_without_followup_rows(self):
        response = self._post_public_chat_with_failed_supervisor()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "supervisor_unavailable")
        self.assertFalse(AnalysisJob.objects.exists())
        self.assertFalse(AgentWorkItem.objects.exists())
        self.assertFalse(Report.objects.exists())

- [ ] Step 2: run:
  D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe backend\manage.py test chatbot.test_supervisor_conversation_runtime_smoke -v 1

  Expected: assertions fail before fallback and blocked checks exist.

- [ ] Step 3: add minimal checks.

    checks["fallback_not_strict"] = llm_status != "used" and "llm_used" in failed_checks
    checks["planning_failure_has_no_followup_rows"] = not any(
        (job_exists, work_item_exists, report_exists, paid_guard_exists)
    )
    checks["official_docx_after_confirmation"] = content.startswith(b"PK")
    checks["general_download_unavailable"] = general_response.status_code == 409

  The DOCX test must use an owned official fixture and call the existing confirmation API or repository before document_type=objection_form. It must not bypass confirmation. The general-report test must keep receiving document_download_not_available and must assert that neither next_actions nor report_actions contains download_report.

- [ ] Step 4: run:
  D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q test\test_consultation_v2_contract.py test\test_agent_node_service.py
  D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe backend\manage.py test chatbot.test_supervisor_conversation_runtime_smoke chatbot.test_supervisor_reporting_pipeline -v 1

  Expected: selected tests pass; official fixture DOCX begins with PK; general report download remains 409.

- [ ] Step 5: commit:
  git add backend/chatbot/test_supervisor_conversation_runtime_smoke.py test/test_consultation_v2_contract.py backend/chatbot/test_supervisor_reporting_pipeline.py
  git commit -m "test: verify supervisor runtime failure boundaries"

### Task 4: Document the operation and evidence workflow

Files:
- Create: docs/ops/supervisor-conversation-runtime-smoke.md
- Modify: docs/ops/non-dl-analysis-reporting-smoke.md
- Modify: docs/ops/project-readiness-master-checklist.md
- Test: test/test_consultation_v2_contract.py

Interfaces:
- Consumes: command flags and supervisor_conversation_runtime_smoke.v1 JSON
- Produces: strict command, safe-output constraints, failure interpretation, evidence capture checklist, separated #229 and #247 checklist rows

- [ ] Step 1: add a failing documentation contract test.

    def test_runtime_smoke_runbook_requires_explicit_paid_consent_and_safe_output():
        content = read_text(ROOT / "docs" / "ops" / "supervisor-conversation-runtime-smoke.md")
        assert "--allow-paid-provider-call" in content
        assert "supervisor_conversation_runtime_smoke.v1" in content
        assert "storage URI" not in content.lower()

- [ ] Step 2: run:
  D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q test\test_consultation_v2_contract.py -k runtime_smoke_runbook

  Expected: failure because the runbook does not exist.

- [ ] Step 3: create the runbook and update tracking.

  Include strict command, clean fixture prerequisite, no-secret rule, success/fallback/blocked interpretation, official DOCX confirmation proof, general-download rejection proof, screenshot/file evidence checklist. Replace stale general-PDF wording in the non-DL runbook with DOCX-only official-document policy. Mark #229 / PR #230 handoff complete and add #247 as in progress until final verification passes.

- [ ] Step 4: run:
  D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q test\test_consultation_v2_contract.py
  git diff --check origin/dev...HEAD

  Expected: selected tests pass with no whitespace error.

- [ ] Step 5: commit:
  git add docs/ops/supervisor-conversation-runtime-smoke.md docs/ops/non-dl-analysis-reporting-smoke.md docs/ops/project-readiness-master-checklist.md test/test_consultation_v2_contract.py
  git commit -m "docs: document supervisor runtime evidence"

### Task 5: Final verification and user evidence

Files:
- Verify only: changed files and ignored local evidence under tmp/supervisor-runtime-smoke/

- [ ] Step 1: run focused verification.

  D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q test\test_agent_node_service.py test\test_consultation_v2_contract.py --timeout=30
  D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe backend\manage.py test chatbot.test_supervisor_conversation_runtime_smoke chatbot.test_supervisor_reporting_pipeline -v 1

  Expected: all selected tests pass.

- [ ] Step 2: run broader regression and frontend build.

  D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q --timeout=30
  npm.cmd --prefix app\web run build

  Expected: full suite passes and Vite production build succeeds.

- [ ] Step 3: capture user evidence.

  Run fake-fixture success, fallback, and blocked flows; save screenshots only under ignored tmp/supervisor-runtime-smoke/. Inspect the generated official DOCX before handoff. Do not generate or retain a general-report download file because its absence is the expected result.

- [ ] Step 4: inspect final scope.

  git diff --check origin/dev...HEAD
  git status -sb

  Expected: no whitespace errors and only intended tracked changes.

