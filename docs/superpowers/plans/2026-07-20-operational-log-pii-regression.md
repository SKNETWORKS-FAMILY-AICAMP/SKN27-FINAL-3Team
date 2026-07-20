# Operational Log PII Regression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent raw PII, storage locations, and secrets from appearing in the Supervisor runtime-smoke output or the chat, file-scan, document-generation, and Worker operational boundaries.

**Architecture:** Keep the current logger and Worker contracts. Normalize the Supervisor smoke `reason` with an allowlist, then make current non-disclosure behavior executable through captured logger records and persisted Worker state. Do not add global logging, cloud logging configuration, or external calls.

**Tech Stack:** Python 3.13, Django `TestCase`, standard-library logging capture, `unittest.mock`, pytest, Django test runner.

## Global Constraints

- Do not modify OCR, law-search, RAG, or other team-owned domain rules.
- Do not add global `LOGGING`, CloudWatch, retention, object-storage, or provider configuration.
- Run only fake-client, patched, or test-database paths; no provider, S3, paid-service, or production-data call is permitted.
- The sentinel exception contains: a person name, phone number, resident-registration number, street address, vehicle number, original filename, Windows path, S3 URI, and secret-like token.
- Allowed operational outputs are fixed status/reason codes, exception class names, fixed failure messages, category/count metadata, and opaque IDs.
- Allowed smoke reason codes are exactly `ok`, `disabled`, `missing_config`, `provider_unavailable`, and `invalid_contract`. Any other value becomes `unspecified`.

---

### Task 1: Normalize the Supervisor runtime-smoke reason

**Files:**
- Modify: `backend/chatbot/management/commands/smoke_supervisor_conversation_runtime.py:174-177`
- Modify: `backend/chatbot/test_supervisor_conversation_runtime_smoke.py:18-34`

**Contract:** `supervisor_state["llm"]` may contain `status`, `reason`, `provider`, and `model`; the public `supervisor_conversation_runtime_smoke.v1` envelope exposes only `status` and a safe reason code.

- [ ] **Step 1: Add a failing raw-reason regression test before changing production code.**

  Replace the current `_safe_llm` assertion with these three assertions in `SupervisorConversationRuntimeSmokeTests`:

  ```python
  def test_smoke_output_normalizes_untrusted_reason_and_excludes_identifiers(self) -> None:
      from chatbot.management.commands import smoke_supervisor_conversation_runtime as smoke

      raw_reason = (
          "Kim Hye-rim 010-1234-5678 900101-1234567 123 Test-ro "
          "12A3456 fine-notice.png C:\\private\\fine-notice.png "
          "s3://private-bucket/fine-notice.png sk-private-token gpt-private"
      )

      result = smoke._safe_llm(
          {
              "llm": {
                  "status": "failed",
                  "reason": raw_reason,
                  "provider": "provider-private",
                  "model": "gpt-private",
              }
          }
      )

      self.assertEqual(result, {"status": "failed", "reason": "unspecified"})
      self.assertNotIn("Kim Hye-rim", repr(result))
      self.assertNotIn("s3://private-bucket", repr(result))
      self.assertNotIn("gpt-private", repr(result))

  def test_smoke_output_preserves_allowed_reason_code(self) -> None:
      from chatbot.management.commands import smoke_supervisor_conversation_runtime as smoke

      self.assertEqual(
          smoke._safe_llm({"llm": {"status": "failed", "reason": "missing_config"}}),
          {"status": "failed", "reason": "missing_config"},
      )

  def test_smoke_output_maps_disabled_state_to_disabled_reason(self) -> None:
      from chatbot.management.commands import smoke_supervisor_conversation_runtime as smoke

      self.assertEqual(
          smoke._safe_llm(
              {"llm": {"status": "disabled", "reason": "SUPERVISOR_LLM_ENABLED is off"}}
          ),
          {"status": "disabled", "reason": "disabled"},
      )
  ```

  The first test must fail on the current code because it returns `raw_reason` unchanged.

- [ ] **Step 2: Run only the failing test and record the intended failure.**

  ```powershell
  & 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' backend\manage.py test chatbot.test_supervisor_conversation_runtime_smoke.SupervisorConversationRuntimeSmokeTests.test_smoke_output_normalizes_untrusted_reason_and_excludes_identifiers -v 1
  ```

- [ ] **Step 3: Add the allowlist and normalize `_safe_llm`.**

  Add directly above `_safe_llm`:

  ```python
  SAFE_LLM_REASON_CODES = frozenset(
      {"ok", "disabled", "missing_config", "provider_unavailable", "invalid_contract"}
  )


  def _safe_llm_reason(status: object, reason: object) -> str:
      if str(status or "").strip().lower() == "disabled":
          return "disabled"
      normalized_reason = str(reason or "").strip().lower()
      if normalized_reason in SAFE_LLM_REASON_CODES:
          return normalized_reason
      return "unspecified"
  ```

  Replace `_safe_llm` with:

  ```python
  def _safe_llm(supervisor_state) -> dict:
      llm = supervisor_state.get("llm") if isinstance(supervisor_state, dict) else {}
      llm = llm if isinstance(llm, dict) else {}
      status = str(llm.get("status") or "")
      return {"status": status, "reason": _safe_llm_reason(status, llm.get("reason"))}
  ```

  This deliberately leaves the envelope shape as two fields and never copies `provider` or `model`.

- [ ] **Step 4: Run the focused test and the complete smoke module.**

  ```powershell
  & 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' backend\manage.py test chatbot.test_supervisor_conversation_runtime_smoke -v 1
  ```

  Expected: all smoke-output, queue, Worker, and report assertions pass with no provider call.

- [ ] **Step 5: Commit the isolated production behavior change.**

  ```powershell
  git add backend/chatbot/management/commands/smoke_supervisor_conversation_runtime.py backend/chatbot/test_supervisor_conversation_runtime_smoke.py
  git commit -m "fix: sanitize supervisor smoke reason"
  ```

### Task 2: Add operational-output PII regression coverage

**Files:**
- Create: `backend/chatbot/test_operational_log_privacy.py`
- Read only: `backend/chatbot/views.py:780-1077`, `backend/chatbot/file_scan_service.py:68-100`, `ai/agents/objection_report_generation/agent.py:645-707`, `backend/chatbot/repositories.py:7335-7520`

**Contract:** Captured logger output and persisted Worker failure data must exclude every sentinel marker. Logs retain only the existing fixed error-class messages; Worker data retains only fixed messages, opaque IDs, and `RuntimeError` as an error code.

- [ ] **Step 1: Create the test module’s imports, sentinel data, and helper methods.**

  ```python
  from __future__ import annotations

  import json
  from types import SimpleNamespace
  from unittest.mock import patch

  from django.test import RequestFactory, TestCase

  from chatbot.models import (
      AgentWorkItem,
      AgentWorkItemStatus,
      AnalysisJob,
      AnalysisJobStatus,
      ChatSession,
      ChatSessionStatus,
      UploadedFile,
      UploadedFileStatus,
  )


  SENSITIVE_MARKERS = (
      "Kim Hye-rim",
      "010-1234-5678",
      "900101-1234567",
      "123 Test-ro",
      "12A3456",
      "fine-notice.png",
      "C:\\private\\fine-notice.png",
      "s3://private-bucket/fine-notice.png",
      "sk-private-token",
  )


  def _private_exception() -> RuntimeError:
      return RuntimeError(" | ".join(SENSITIVE_MARKERS))


  class OperationalLogPrivacyTests(TestCase):
      def assert_no_raw_markers(self, value: object) -> None:
          serialized = repr(value)
          for marker in SENSITIVE_MARKERS:
              self.assertNotIn(marker, serialized)

      def _uploaded_file_for_scan(self) -> UploadedFile:
          session = ChatSession.objects.create(
              session_id="ses_operational_scan",
              owner_id="usr_operational_scan",
              status=ChatSessionStatus.ACTIVE.value,
          )
          return UploadedFile.objects.create(
              attachment_id="att_operational_scan",
              owner_id=session.owner_id,
              session=session,
              purpose="fine_notice",
              file_type="image",
              original_filename=SENSITIVE_MARKERS[5],
              content_type="image/png",
              size_bytes=1,
              storage_uri=SENSITIVE_MARKERS[7],
              privacy_risk=False,
              status=UploadedFileStatus.UPLOADED.value,
              scan_status="not_started",
          )
  ```

- [ ] **Step 2: Add the three logger-boundary tests.**

  ```python
  def test_analysis_job_reservation_failure_logs_only_error_type(self) -> None:
      from chatbot import views

      request = RequestFactory().post(
          "/api/analysis/jobs/",
          data=json.dumps({"session_id": "ses_log", "job_id": "job_log"}),
          content_type="application/json",
      )
      with (
          patch("chatbot.views._is_canonical_mock_request", return_value=True),
          patch("chatbot.views.reserve_analysis_job_request", side_effect=_private_exception()),
          self.assertLogs("chatbot.views", level="WARNING") as captured,
      ):
          response = views.analysis_jobs(request)

      self.assertEqual(response.status_code, 503)
      self.assertIn("analysis job reservation failed error_type=RuntimeError", captured.output[0])
      self.assert_no_raw_markers(captured.output)

  def test_file_scan_failure_log_excludes_uploaded_file_identifiers(self) -> None:
      from chatbot import file_scan_service

      uploaded_file = self._uploaded_file_for_scan()
      with (
          patch("chatbot.file_scan_service._source_snapshot_for_scan", return_value=b""),
          patch("chatbot.file_scan_service.build_file_scan_result", side_effect=_private_exception()),
          self.assertLogs("chatbot.file_scan_service", level="WARNING") as captured,
      ):
          file_scan_service.scan_uploaded_file(uploaded_file)

      self.assertIn("file scan failed error_type=RuntimeError", captured.output[0])
      self.assert_no_raw_markers(captured.output)

  def test_objection_draft_provider_failure_log_excludes_prompt_and_exception_text(self) -> None:
      from ai.agents.objection_report_generation import agent

      failing_client = SimpleNamespace(
          chat=SimpleNamespace(
              completions=SimpleNamespace(
                  create=lambda **_kwargs: (_ for _ in ()).throw(_private_exception())
              )
          )
      )
      with (
          patch.object(agent, "_openai_client", return_value=failing_client),
          self.assertLogs("ai.agents.objection_report_generation.agent", level="WARNING") as captured,
      ):
          result = agent._draft_petition_text(
              disposition_details={"violation_text": SENSITIVE_MARKERS[0]},
              legal_grounds=[],
              user_facts=" ".join(SENSITIVE_MARKERS),
              missing_fields=[],
              appeal_decision={},
          )

      self.assertIsNone(result)
      self.assertIn("objection petition drafting failed; error_class=RuntimeError", captured.output[0])
      self.assert_no_raw_markers(captured.output)
  ```

- [ ] **Step 3: Run the logger tests as characterization coverage.**

  ```powershell
  & 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' backend\manage.py test chatbot.test_operational_log_privacy.OperationalLogPrivacyTests.test_analysis_job_reservation_failure_logs_only_error_type chatbot.test_operational_log_privacy.OperationalLogPrivacyTests.test_file_scan_failure_log_excludes_uploaded_file_identifiers chatbot.test_operational_log_privacy.OperationalLogPrivacyTests.test_objection_draft_provider_failure_log_excludes_prompt_and_exception_text -v 1
  ```

  Expected: PASS before any logger production change. These tests lock the safe existing behavior and use no network path.

- [ ] **Step 4: Add the persisted Worker failure-state test.**

  ```python
  def test_worker_failure_persists_only_fixed_operational_values(self) -> None:
      from chatbot import repositories

      session = ChatSession.objects.create(
          session_id="ses_worker_log",
          owner_id="usr_worker_log",
          status=ChatSessionStatus.ACTIVE.value,
      )
      job = AnalysisJob.objects.create(
          job_id="job_worker_log",
          session=session,
          owner_id=session.owner_id,
          status=AnalysisJobStatus.RUNNING.value,
      )
      work_item = AgentWorkItem.objects.create(
          work_item_id="work_worker_log",
          job=job,
          status=AgentWorkItemStatus.RUNNING.value,
          attempt_no=1,
          max_attempts=1,
      )
      with (
          patch("chatbot.repositories.write_analysis_job_progress", return_value={}),
          patch("chatbot.repositories.write_chat_session_state", return_value=None),
      ):
          result = repositories._fail_agent_work_item(
              work_item.work_item_id,
              _private_exception(),
              expected_attempt_no=1,
          )

      work_item.refresh_from_db()
      job.refresh_from_db()
      event = job.events.latest("created_at")
      self.assertEqual(result["error_code"], "RuntimeError")
      self.assertEqual(work_item.result["message"], "Agent worker execution failed.")
      self.assertEqual(job.progress_message, "Agent worker item failed.")
      self.assert_no_raw_markers(
          {
              "result": result,
              "work_item": work_item.result,
              "job": job.progress_message,
              "event": event.metadata,
          }
      )
  ```

- [ ] **Step 5: Run the entire new test module and commit it.**

  ```powershell
  & 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' backend\manage.py test chatbot.test_operational_log_privacy -v 1
  git add backend/chatbot/test_operational_log_privacy.py
  git commit -m "test: cover operational log pii boundaries"
  ```

### Task 3: Record readiness state and run regression verification

**Files:**
- Modify: `docs/ops/project-readiness-master-checklist.md:57`
- Verify: `backend/chatbot/test_operational_log_privacy.py`, `backend/chatbot/test_supervisor_conversation_runtime_smoke.py`, `test/test_chat_input_privacy.py`, `test/test_ocr_privacy_contract.py`

**Contract:** The checklist uses `[~]` for implementation/PR in progress; it must not claim a merge or CI result before those occur.

- [ ] **Step 1: Change only the operational-log row to `[~]` and append `#249`.**

  Preserve the existing Korean row label and its surrounding ordering. Do not mark it `[x]` until the PR is merged into `dev` and required CI succeeds.

- [ ] **Step 2: Run the focused privacy and smoke suites.**

  ```powershell
  & 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' backend\manage.py test chatbot.test_operational_log_privacy chatbot.test_supervisor_conversation_runtime_smoke -v 1
  & 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' -m pytest -q test/test_chat_input_privacy.py test/test_ocr_privacy_contract.py --timeout=30
  ```

  Expected: PASS with no provider, S3, or paid-service invocation.

- [ ] **Step 3: Run full regression and scope checks.**

  ```powershell
  & 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' -m pytest -q --timeout=30
  git diff --check origin/dev...HEAD
  git status -sb
  ```

  Expected: full pytest passes, whitespace is clean, and only #249 design/plan/test/smoke-command/checklist files differ from `origin/dev`.

- [ ] **Step 4: Commit the readiness update.**

  ```powershell
  git add docs/ops/project-readiness-master-checklist.md
  git commit -m "docs: track operational log pii regression"
  ```
