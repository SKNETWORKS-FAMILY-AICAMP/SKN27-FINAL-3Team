# Report Routing and Final Answer Hotfix Plan

> **For implementation:** Use the `superpowers:executing-plans` skill to execute this plan task by task.

**Goal:** Route plain-text fine-notice draft requests into the verified fine-notice intake flow, and render persisted law-search results as a user-facing response rather than a retrieval-count summary.

**Architecture:** Keep the existing OCR confirmation gate before report generation. Promote only a `fine_notice_procedure` result when the existing report-intent detector confirms a document-generation request. At final merge, normalize the persisted law result through the canonical law contract before deriving the human-readable procedure answer.

**Tech Stack:** Python, pytest, Django service layer.

---

### Task 1: Lock the text-only report-intent routing contract

**Files:**
- Modify: `app/services/supervisor_routing_service.py`
- Modify: `app/services/chat_orchestration_service.py`
- Test: `test/test_chat_orchestration_service.py`

1. Add a test proving that a fine-notice draft request selects `fine_notice_analysis`, while its absent OCR confirmation keeps `objection_report_generation` out of the executable plan.
2. Run the test and observe the current `fine_notice_procedure` failure.
3. Add a narrowly-scoped routing promotion for detected report intent.
4. Run the test and confirm it passes.

### Task 2: Lock persisted raw law-result response rendering

**Files:**
- Modify: `app/services/supervisor_control_service.py`
- Test: `test/test_supervisor_control_service.py`

1. Add a test using the actual agent's `source_name` and `article_no` law-provision fields.
2. Assert that the response contains the law name and article, and not the retrieval-count summary.
3. Run the test and observe the failure before implementation.
4. Normalize the law result at final merge before generating procedure guidance.
5. Run the test and confirm it passes.

### Task 3: Verify the integrated contract

**Files:**
- Test: `test/test_chat_orchestration_service.py`
- Test: `test/test_supervisor_control_service.py`
- Test: `test/test_supervisor_plan_execution.py`

1. Run the focused pytest selection.
2. Run the broader Supervisor service tests if the focused selection passes.
3. Review `git diff --check` and `git status --short`.
4. Hand off the branch with the exact safety boundary: report generation still requires confirmed OCR fields and verified inputs.
