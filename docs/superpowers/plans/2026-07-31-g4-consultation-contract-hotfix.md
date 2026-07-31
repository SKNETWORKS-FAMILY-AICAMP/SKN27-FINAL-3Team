# G4 Consultation Contract Hotfix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make fine-notice intake, attachment handoff, and conflicting accident facts satisfy HFX-014~016 and exact E2E IDs 3, 4, 9, 11, and 13 without regressing the safety boundaries covered by IDs 6 and 7.

**Architecture:** Add three focused server-owned contracts: a pure fine-notice intake reducer, a pure attachment workflow-state projector, and a normalized Supervisor fact-conflict contract. Existing routing, scan persistence, classification confirmation, OCR confirmation, Agent execution, authentication, and report gates remain authoritative; orchestration composes the new contracts, and the React UI renders server states without inferring them.

**Tech Stack:** Python 3, pytest, Django test client, strict JSON schema for Supervisor output, React 19, Node test runner, Vite.

## Global Constraints

- Work on branch `feat-pilot-safety-hotfix`, whose G3 head is `dfd12f4e`.
- Use the approved design in `docs/superpowers/specs/2026-07-31-g4-fine-notice-attachment-conflict-design.md`.
- Implement every behavior test-first and observe the focused RED failure before editing production code.
- The fine-notice required slots are exactly `document_disposition_type`, `issuing_authority`, `response_deadline`, and `attachment_available`.
- Never infer an issuing authority, disposition type, deadline, or attachment availability from an unclear or typo-only statement.
- Public fine-notice law items contain only `law_name`, `article`, and an optional verified `summary` of at most 240 characters.
- Never expose raw OCR, `provision_text`, RAG chunk text, private storage URI, signed URL, local path, or PII in a public response or UI state.
- The attachment workflow states are exactly `scan_running`, `classification_running`, `classified_waiting_confirmation`, `ocr_running`, `ocr_needs_confirmation`, `analysis_ready`, `partial`, and `failed`.
- The client may confirm only an `attachment_id`; classification and workflow state remain server-owned.
- A material `fact_conflicts` entry blocks fault-ratio numbers, analysis execution, and case promotion until the conflict is resolved.
- When a conflict exists, ask only conflict-field questions; do not repeat already collected non-conflicting fields.
- Do not change generic polling timeout/restart behavior; that belongs to G5/HFX-017.
- Do not change `UploadedFileStatus` or add a database migration.
- Do not deploy, merge, push, or run production E2E in G4.
- Stage and commit remain user-owned; each task ends with an explicit review checkpoint and suggested commit command.

---

### Task 1: Add the server-owned fine-notice intake reducer

**Files:**
- Create: `app/services/fine_notice_intake_service.py`
- Create: `test/test_fine_notice_intake_service.py`

**Interfaces:**
- Consumes: `payload: Mapping[str, Any]` after privacy sanitation and attachment scan gating.
- Produces: `reduce_fine_notice_intake(payload: Mapping[str, Any]) -> dict[str, Any]`.
- Produces contract `fine_notice_intake.v1` with `slots`, `missing_fields`, and `next_questions`.
- Exports `FINE_NOTICE_REQUIRED_SLOTS: tuple[str, ...]` and `FINE_NOTICE_QUESTIONS: dict[str, str]`.

- [ ] **Step 1: Write reducer RED tests**

  Add exact required-slot and source tests:

  ```python
  from app.services.fine_notice_intake_service import reduce_fine_notice_intake


  def test_empty_fine_notice_intake_requests_all_required_slots() -> None:
      intake = reduce_fine_notice_intake(
          {
              "message_id": "msg_e2e_3",
              "user_text": "과태료 고지서를 받았는데 이의신청이나 의견제출은 어떤 순서로 하면 되나요?",
              "attachments": [],
          }
      )

      assert intake["contract_version"] == "fine_notice_intake.v1"
      assert intake["missing_fields"] == [
          "document_disposition_type",
          "issuing_authority",
          "response_deadline",
          "attachment_available",
      ]
      assert [item["field"] for item in intake["next_questions"]] == intake["missing_fields"]
  ```

  Add tests proving:

  - `fine_notice_slots` values are accepted with `source_type="user_structured_input"`;
  - confirmed OCR values are accepted with `source_type="user_confirmed_ocr"`;
  - an actual attachment sets only `attachment_available=True`;
  - an OCR candidate with `confirmed=False` does not fill any slot;
  - typo-heavy ID 11 does not invent authority, type, or deadline;
  - a conversation answer is mapped only when the immediately preceding assistant question has an exact `FINE_NOTICE_QUESTIONS` value;
  - unsupported slot keys and blank values are discarded.

- [ ] **Step 2: Run the focused tests and record RED**

  ```powershell
  python -m pytest test/test_fine_notice_intake_service.py -q
  ```

  Expected: collection fails because `fine_notice_intake_service` does not exist.

- [ ] **Step 3: Implement the minimal reducer**

  Implement these public constants and function:

  ```python
  FINE_NOTICE_REQUIRED_SLOTS = (
      "document_disposition_type",
      "issuing_authority",
      "response_deadline",
      "attachment_available",
  )

  FINE_NOTICE_QUESTIONS = {
      "document_disposition_type": "받은 문서의 이름 또는 처분 유형을 알려주세요.",
      "issuing_authority": "고지서를 발급한 기관을 알려주세요.",
      "response_deadline": "고지서에 적힌 의견제출 또는 이의신청 기한을 알려주세요.",
      "attachment_available": "고지서 사진이나 파일을 첨부할 수 있나요?",
  }

  def reduce_fine_notice_intake(payload: Mapping[str, Any]) -> dict[str, Any]:
      source_message_id = str(
          payload.get("message_id") or payload.get("session_id") or "current"
      ).strip()
      slots: dict[str, dict[str, Any]] = {}

      explicit = payload.get("fine_notice_slots")
      explicit = explicit if isinstance(explicit, Mapping) else {}
      for field in FINE_NOTICE_REQUIRED_SLOTS:
          value = _slot_value(explicit.get(field))
          if value is not None:
              slots[field] = _slot_record(
                  value,
                  source_type="user_structured_input",
                  source_message_id=source_message_id,
              )

      confirmation = payload.get("ocr_confirmation")
      confirmation = confirmation if isinstance(confirmation, Mapping) else {}
      confirmed_fields = confirmation.get("fields")
      confirmed_fields = (
          confirmed_fields
          if confirmation.get("confirmed") is True
          and isinstance(confirmed_fields, Mapping)
          else {}
      )
      for field in FINE_NOTICE_REQUIRED_SLOTS[:-1]:
          if field in slots:
              continue
          value = _slot_value(confirmed_fields.get(field))
          if value is not None:
              slots[field] = _slot_record(
                  value,
                  source_type="user_confirmed_ocr",
                  source_message_id=source_message_id,
              )

      if "attachment_available" not in slots and any(
          isinstance(item, Mapping)
          and str(item.get("attachment_id") or "").strip()
          for item in payload.get("attachments") or []
      ):
          slots["attachment_available"] = _slot_record(
              True,
              source_type="server_attachment",
              source_message_id=source_message_id,
          )

      pending_field = ""
      question_to_field = {
          question: field for field, question in FINE_NOTICE_QUESTIONS.items()
      }
      for index, turn in enumerate(payload.get("conversation_history") or []):
          if not isinstance(turn, Mapping):
              continue
          role = str(turn.get("role") or "").strip()
          content = str(turn.get("content") or "").strip()
          if role == "assistant":
              pending_field = question_to_field.get(content, "")
          elif role == "user" and pending_field and pending_field not in slots:
              value = _slot_value(content)
              if value is not None:
                  slots[pending_field] = _slot_record(
                      value,
                      source_type="user_confirmation",
                      source_message_id=str(
                          turn.get("message_id") or f"history:{index}"
                      ),
                  )
              pending_field = ""

      missing = [field for field in FINE_NOTICE_REQUIRED_SLOTS if field not in slots]
      return {
          "contract_version": "fine_notice_intake.v1",
          "slots": slots,
          "missing_fields": missing,
          "next_questions": [
              {"field": field, "question": FINE_NOTICE_QUESTIONS[field]}
              for field in missing
          ],
      }

  def _slot_value(value: Any) -> str | bool | None:
      if isinstance(value, bool):
          return value
      normalized = str(value or "").strip()
      return normalized if normalized else None

  def _slot_record(
      value: str | bool,
      *,
      source_type: str,
      source_message_id: str,
  ) -> dict[str, Any]:
      return {
          "value": value,
          "source_type": source_type,
          "source_message_id": source_message_id,
          "confidence": 1.0,
          "confirmed": True,
      }
  ```

  Build every stored slot as:

  ```python
  {
      "value": normalized_value,
      "source_type": "user_structured_input",
      "source_message_id": source_message_id,
      "confidence": 1.0,
      "confirmed": True,
  }
  ```

  Do not add an unrestricted free-text entity extractor. Read only explicit
  `fine_notice_slots`, confirmed OCR fields, current attachment presence, and
  exact question/answer turns.

- [ ] **Step 4: Run Task 1 GREEN tests**

  ```powershell
  python -m pytest test/test_fine_notice_intake_service.py -q
  ```

  Expected: all tests pass.

- [ ] **Step 5: Review and user-owned commit checkpoint**

  ```powershell
  git diff --check
  git diff -- app/services/fine_notice_intake_service.py test/test_fine_notice_intake_service.py
  ```

  Confirm the service has no legal routing, Agent execution, persistence, or UI
  responsibility. Suggested later commit boundary:

  ```text
  fix: enforce fine notice intake contracts
  ```

---

### Task 2: Wire fine-notice intake through orchestration and UI input

**Files:**
- Modify: `app/services/chat_orchestration_service.py`
- Modify: `app/services/supervisor_control_service.py`
- Modify: `app/web/consultationIntake.js`
- Modify: `app/web/consultationIntake.test.js`
- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `test/test_chat_orchestration_service.py`
- Modify: `test/test_supervisor_control_service.py`

**Interfaces:**
- Consumes: `reduce_fine_notice_intake` from Task 1.
- Adds request field `fine_notice_slots: Record<string, string | boolean>`.
- Adds response field `fine_notice_intake: fine_notice_intake.v1`.
- Adds the same contract under `supervisor_state.fine_notice_intake` so queued and persisted work retain the server-owned state.

- [ ] **Step 1: Add exact-input RED orchestration tests**

  Add ID 3, ID 9, and ID 11 tests:

  ```python
  def test_e2e_3_requests_every_required_fine_notice_slot() -> None:
      response = submit_message(
          {
              "session_id": "ses_e2e_3",
              "message_id": "msg_e2e_3",
              "user_text": "과태료 고지서를 받았는데 이의신청이나 의견제출은 어떤 순서로 하면 되나요?",
          }
      )

      assert response["routing_intent"] == "fine_notice_procedure"
      assert [item["field"] for item in response["pending_questions"]] == [
          "document_disposition_type",
          "issuing_authority",
          "response_deadline",
          "attachment_available",
      ]
  ```

  For ID 9, assert the same field list and assert `"개소리"` is absent from
  `repr(response)`. For ID 11, assert the same missing values, no fabricated
  deadline/authority in `fine_notice_intake.slots`, and no past-deadline claim
  in the assistant answer.

  Extend the verified-law-result test to assert the same pending questions are
  retained after a successful `law_ground_search`.

- [ ] **Step 2: Add UI intake RED tests**

  Replace the three old fine-notice fields with the four approved fields:

  ```javascript
  assert.deepEqual(
    FINE_NOTICE_FIELDS.map(({ key, serverKey }) => [key, serverKey]),
    [
      ["documentDispositionType", "document_disposition_type"],
      ["issuingAuthority", "issuing_authority"],
      ["responseDeadline", "response_deadline"],
      ["attachmentAvailable", "attachment_available"],
    ]
  );
  ```

  Assert `buildConsultationRequestContext` emits:

  ```javascript
  {
    consultation_type: "fine_notice",
    facts: {},
    fine_notice_slots: {
      document_disposition_type: "과태료 사전통지서",
      issuing_authority: "가상시청",
      response_deadline: "2026-08-07",
      attachment_available: "yes",
    },
  }
  ```

- [ ] **Step 3: Run Task 2 RED tests**

  ```powershell
  python -m pytest test/test_chat_orchestration_service.py test/test_supervisor_control_service.py -q
  node --test app/web/consultationIntake.test.js
  ```

  Expected: Python responses have no `fine_notice_intake`; the UI still emits
  violation date/location/type rather than the approved four-slot contract.

- [ ] **Step 4: Integrate the reducer in orchestration**

  After routing and before Supervisor planning:

  ```python
  fine_notice_intake = (
      reduce_fine_notice_intake(
          {**payload, "user_text": user_text, "attachments": attachments}
      )
      if routing_intent in {"fine_notice_procedure", "fine_notice_analysis"}
      else None
  )
  ```

  Add a small merge helper:

  ```python
  def _merge_fine_notice_questions(
      existing: Any,
      intake: Mapping[str, Any] | None,
  ) -> list[dict[str, Any]]:
      intake_questions = [
          dict(item)
          for item in (intake or {}).get("next_questions") or []
          if isinstance(item, Mapping) and str(item.get("field") or "").strip()
      ]
      other_questions = [
          dict(item)
          for item in existing or []
          if isinstance(item, Mapping) and str(item.get("field") or "").strip()
      ]
      merged: list[dict[str, Any]] = []
      seen: set[str] = set()
      for item in [*intake_questions, *other_questions]:
          field = str(item["field"]).strip()
          if field not in seen:
              seen.add(field)
              merged.append(item)
      return merged
  ```

  It must deduplicate by `field`, preserve the four approved field order, and
  return fine-notice questions even when law search succeeds. Add
  `fine_notice_intake` to the synchronous response, Supervisor state, analysis
  plan context, and composed persisted response.

- [ ] **Step 5: Align safe procedure guidance**

  Replace `notice_received` and `notice_details` fallback questions in
  `_verified_result_unavailable_guidance` with the reducer’s exact four
  questions. Keep the general procedural answer and existing limitations; do
  not calculate a deadline or predict objection success.

- [ ] **Step 6: Update the frontend intake contract**

  In `consultationIntake.js`, add:

  ```javascript
  export const FINE_NOTICE_FIELDS = [
    {
      key: "documentDispositionType",
      serverKey: "document_disposition_type",
      label: "문서명·처분 유형",
      question: "받은 문서의 이름 또는 처분 유형",
    },
    {
      key: "issuingAuthority",
      serverKey: "issuing_authority",
      label: "발급기관",
      question: "고지서를 발급한 기관",
    },
    {
      key: "responseDeadline",
      serverKey: "response_deadline",
      label: "제출 기한",
      question: "의견제출 또는 이의신청 기한",
    },
    {
      key: "attachmentAvailable",
      serverKey: "attachment_available",
      label: "첨부 가능 여부",
      question: "고지서 사진이나 파일을 첨부할 수 있는지",
    },
  ];
  ```

  `buildConsultationRequestContext` must emit `fine_notice_slots` only for
  non-empty values. Pass that object as `fine_notice_slots` in
  `submitServiceMessage`. Render `attachmentAvailable` as a yes/no/unknown
  select; do not infer it from a selected but not registered local file.

- [ ] **Step 7: Run Task 2 GREEN tests**

  ```powershell
  python -m pytest test/test_fine_notice_intake_service.py test/test_chat_orchestration_service.py test/test_supervisor_control_service.py -q
  node --test app/web/consultationIntake.test.js
  ```

  Expected: all tests pass and IDs 3, 9, and 11 share the same safe intake
  contract.

- [ ] **Step 8: Review and user-owned commit checkpoint**

  Inspect only Task 1–2 changes and run `git diff --check`. Confirm accident
  intake fields and G1 profanity/typo routing remain unchanged. Present the
  suggested commit:

  ```text
  fix: enforce fine notice intake contracts
  ```

---

### Task 3: Add a safe public law-result projection

**Files:**
- Create: `app/services/public_law_projection_service.py`
- Create: `test/test_public_law_projection_service.py`
- Modify: `app/services/supervisor_control_service.py`
- Modify: `app/services/analysis_job_query_service.py`
- Modify: `test/test_analysis_job_query_service.py`
- Modify: `test/test_chat_orchestration_service.py`

**Interfaces:**
- Produces `project_public_law_items(structured_result: Mapping[str, Any]) -> list[dict[str, str]]`.
- Produces law items containing only `law_name`, `article`, and optional `summary`.
- Internal Agent results and evidence references remain unchanged.

- [ ] **Step 1: Write projection RED tests**

  Use a source with a private reference, signed URL, raw provision, and an
  independent verified summary:

  ```python
  public = project_public_law_items(
      {
          "matched_laws": [
              {
                  "law_name": "도로교통법",
                  "article": "제160조",
                  "summary": "과태료 부과와 관련된 적용 조문입니다.",
                  "provision_text": "원문 전체가 여기에 있다고 가정합니다.",
                  "source_reference": "s3://private/law?sig=secret",
              }
          ]
      }
  )

  assert public == [
      {
          "law_name": "도로교통법",
          "article": "제160조",
          "summary": "과태료 부과와 관련된 적용 조문입니다.",
      }
  ]
  assert "provision_text" not in repr(public)
  assert "source_reference" not in repr(public)
  ```

  Add a case where `summary == provision_text` and assert `summary` is omitted.
  Add a case where summary exceeds 240 characters and assert it is omitted
  rather than blindly truncated from raw text. Require a non-empty internal
  evidence reference before accepting an item as verified.

- [ ] **Step 2: Run projection tests and record RED**

  ```powershell
  python -m pytest test/test_public_law_projection_service.py test/test_analysis_job_query_service.py -q
  ```

  Expected: module is missing and current public projection exposes
  `provision_text` and `source_reference`.

- [ ] **Step 3: Implement the projector**

  Implement:

  ```python
  PUBLIC_LAW_FIELDS = ("law_name", "article", "summary")
  MAX_PUBLIC_LAW_SUMMARY_LENGTH = 240

  def project_public_law_items(
      structured_result: Mapping[str, Any],
  ) -> list[dict[str, str]]:
      raw_items = structured_result.get("matched_laws")
      if not isinstance(raw_items, list) or not raw_items:
          raw_items = structured_result.get("law_provisions")
      public: list[dict[str, str]] = []
      for raw in raw_items if isinstance(raw_items, list) else []:
          if not isinstance(raw, Mapping):
              continue
          source_reference = str(raw.get("source_reference") or "").strip()
          if not source_reference:
              continue
          law_name = _first_text(raw, "law_name", "source_name", "title")
          article = _first_text(raw, "article", "article_no", "section_ref")
          if not law_name or not article:
              continue
          item = {"law_name": law_name, "article": article}
          summary = str(raw.get("summary") or "").strip()
          provision_text = str(raw.get("provision_text") or "").strip()
          if (
              summary
              and summary != provision_text
              and len(summary) <= MAX_PUBLIC_LAW_SUMMARY_LENGTH
          ):
              item["summary"] = summary
          if item not in public:
              public.append(item)
      return public[:3]

  def _first_text(value: Mapping[str, Any], *keys: str) -> str:
      for key in keys:
          text = str(value.get(key) or "").strip()
          if text:
              return text
      return ""

  ```

  Resolve names from `law_name|source_name|title` and articles from
  `article|article_no|section_ref`. Accept a summary only when it is distinct
  from `provision_text`, within the size bound, and the source item has a
  non-empty evidence reference. The reference may remain private for internal
  verification, but never copy it into public output.

- [ ] **Step 4: Use the projector at both public response boundaries**

  In `_fine_notice_procedure_answer`, render only projected items and remove
  the `item.get("provision_text")` fallback. In
  `analysis_job_query_service`, replace `_PUBLIC_LAW_ITEM_FIELDS` projection
  for persisted public law results with `project_public_law_items`.

  Keep general internal law Agent DTOs unchanged so reporting and validation
  still have their evidence.

- [ ] **Step 5: Run Task 3 GREEN and privacy regressions**

  ```powershell
  python -m pytest test/test_public_law_projection_service.py test/test_analysis_job_query_service.py test/test_chat_orchestration_service.py test/test_law_ground_contract.py test/test_ocr_privacy_contract.py test/test_privacy_boundaries.py -q
  ```

  Expected: zero public raw-text/private-reference leaks and no internal law
  contract regression.

- [ ] **Step 6: Review checkpoint**

  Search the changed public-response tests for:

  ```powershell
  rg -n "provision_text|ocr_text|raw_text|s3://|file://|sig=" app/services test
  git diff --check
  ```

  Test fixtures may contain sentinel strings; production public projections
  must not return them.

---

### Task 4: Add the server-owned attachment workflow-state projector

**Files:**
- Create: `app/services/attachment_workflow_service.py`
- Create: `test/test_attachment_workflow_service.py`
- Modify: `app/services/chat_orchestration_service.py`
- Modify: `app/services/analysis_job_query_service.py`
- Modify: `backend/chatbot/views.py`
- Modify: `backend/chatbot/test_attachment_classification_confirmation_flow.py`
- Modify: `test/test_chat_orchestration_service.py`
- Modify: `test/test_analysis_job_query_service.py`

**Interfaces:**
- Produces `build_attachment_workflows(*, attachments: Sequence[Mapping[str, Any]], structured_results: Mapping[str, Any] | None = None, active_node: str = "", overall_status: str = "", ocr_confirmation: Mapping[str, Any] | None = None) -> list[dict[str, Any]]`.
- Adds public response field `attachment_workflows`.
- Each item follows `attachment_workflow.v1` and contains only
  `attachment_id`, `state`, `next_action`, `retryable`, `missing_fields`, and
  `limitations`.

- [ ] **Step 1: Write state-table RED tests**

  Parameterize every allowed state:

  ```python
  @pytest.mark.parametrize(
      ("inputs", "expected_state", "expected_action"),
      [
          ({"scan_status": "pending"}, "scan_running", "wait_for_scan"),
          ({"scan_status": "clean"}, "classification_running", "wait_for_classification"),
          (
              {"classification": {"requires_confirmation": True}},
              "classified_waiting_confirmation",
              "confirm_classification",
          ),
          ({"active_node": "fine_notice_analysis"}, "ocr_running", "wait_for_ocr"),
          (
              {"ocr": {"requires_confirmation": True}},
              "ocr_needs_confirmation",
              "confirm_ocr_fields",
          ),
          (
              {"ocr_confirmation": {"confirmed": True}, "analysis_status": "success"},
              "analysis_ready",
              "review_analysis",
          ),
      ],
  )
  def test_attachment_workflow_state_table(inputs, expected_state, expected_action):
      attachment = {
          "attachment_id": "att_notice",
          "status": inputs.get("status", "ready"),
          "scan_status": inputs.get("scan_status", "clean"),
      }
      structured = {}
      if "classification" in inputs:
          structured["attachment_document_classification"] = {
              "attachment_id": "att_notice",
              **inputs["classification"],
          }
      if "ocr" in inputs:
          structured["fine_notice_analysis"] = {
              "attachment_id": "att_notice",
              **inputs["ocr"],
          }
      result = build_attachment_workflows(
          attachments=[attachment],
          structured_results=structured,
          active_node=inputs.get("active_node", ""),
          overall_status=inputs.get("analysis_status", ""),
          ocr_confirmation=inputs.get("ocr_confirmation"),
      )
      assert result[0]["state"] == expected_state
      assert result[0]["next_action"] == expected_action
  ```

  Add `partial` and `failed` cases asserting non-empty `limitations` and
  `next_action`. Assert unknown statuses fail closed to `failed`. Assert output
  excludes storage URI, filename, OCR text, structured result, and arbitrary
  error messages.

- [ ] **Step 2: Run state tests and record RED**

  ```powershell
  python -m pytest test/test_attachment_workflow_service.py -q
  ```

  Expected: module is missing.

- [ ] **Step 3: Implement the pure state projector**

  Export:

  ```python
  ATTACHMENT_WORKFLOW_STATES = frozenset(
      {
          "scan_running",
          "classification_running",
          "classified_waiting_confirmation",
          "ocr_running",
          "ocr_needs_confirmation",
          "analysis_ready",
          "partial",
          "failed",
      }
  )

  def build_attachment_workflows(
      *,
      attachments: Sequence[Mapping[str, Any]],
      structured_results: Mapping[str, Any] | None = None,
      active_node: str = "",
      overall_status: str = "",
      ocr_confirmation: Mapping[str, Any] | None = None,
  ) -> list[dict[str, Any]]:
      structured = (
          structured_results if isinstance(structured_results, Mapping) else {}
      )
      classification = structured.get("attachment_document_classification")
      classification = classification if isinstance(classification, Mapping) else {}
      ocr = structured.get("fine_notice_analysis")
      ocr = ocr if isinstance(ocr, Mapping) else {}
      confirmation = (
          ocr_confirmation if isinstance(ocr_confirmation, Mapping) else {}
      )
      workflows: list[dict[str, Any]] = []
      for attachment in attachments:
          attachment_id = str(attachment.get("attachment_id") or "").strip()
          if not attachment_id:
              continue
          upload_status = str(attachment.get("status") or "").lower()
          scan_status = str(attachment.get("scan_status") or "").lower()
          state = "classification_running"
          action = "wait_for_classification"
          retryable = False
          limitations: list[str] = []
          missing_fields: list[str] = []

          if upload_status in {"rejected", "deleted"} or scan_status in {
              "infected",
              "failed",
              "rejected",
          }:
              state, action = "failed", "reattach_file"
              limitations = ["현재 파일은 안전한 분석 대상으로 사용할 수 없습니다."]
          elif scan_status not in {"clean", "ready"}:
              state, action = "scan_running", "wait_for_scan"
          elif classification.get("requires_confirmation") is True:
              state, action = (
                  "classified_waiting_confirmation",
                  "confirm_classification",
              )
          elif classification.get("status") == "partial":
              state, action, retryable = (
                  "partial",
                  str(classification.get("next_action") or "rerun_classification"),
                  True,
              )
              limitations = ["자료 종류를 확정하지 못했습니다."]
          elif ocr.get("requires_confirmation") is True:
              state, action = "ocr_needs_confirmation", "confirm_ocr_fields"
              missing_fields = [
                  str(item)
                  for item in ocr.get("missing_fields") or []
                  if str(item).strip()
              ]
          elif active_node == "fine_notice_analysis":
              state, action = "ocr_running", "wait_for_ocr"
          elif overall_status == "failed":
              state, action = "failed", "retry_or_reupload"
              limitations = ["고지서 분석을 완료하지 못했습니다."]
          elif overall_status == "partial":
              state, action = "partial", "provide_missing_information"
              limitations = ["일부 고지서 정보를 추가로 확인해야 합니다."]
          elif (
              confirmation.get("confirmed") is True
              and overall_status == "success"
          ):
              state, action = "analysis_ready", "review_analysis"

          workflows.append(
              {
                  "contract_version": "attachment_workflow.v1",
                  "attachment_id": attachment_id,
                  "state": state,
                  "next_action": action,
                  "retryable": retryable,
                  "missing_fields": missing_fields,
                  "limitations": limitations,
              }
          )
      return workflows
  ```

  Use explicit precedence:

  1. rejected/deleted/failed scan → `failed`;
  2. incomplete scan → `scan_running`;
  3. classification confirmation requested → `classified_waiting_confirmation`;
  4. classification unavailable/partial → `partial`;
  5. classification node active or absent after clean scan → `classification_running`;
  6. OCR confirmation requested → `ocr_needs_confirmation`;
  7. fine-notice analysis active → `ocr_running`;
  8. valid OCR confirmation plus successful analysis → `analysis_ready`;
  9. public partial/failed execution status → matching terminal state.

- [ ] **Step 4: Attach workflow state to synchronous and persisted responses**

  In `submit_message` and `compose_agent_response`, call the projector with
  server-owned attachments, structured results, active node, status, and the
  normalized OCR confirmation. In `analysis_job_query_service`, allowlist only
  the six public workflow fields and rebuild from persisted server data when
  the stored response predates `attachment_workflow.v1`.

  Extend the 409 classification-confirmation error in `backend/chatbot/views.py`
  with:

  ```python
  "attachment_workflows": [
      {
          "contract_version": "attachment_workflow.v1",
          "attachment_id": attachment_id,
          "state": "failed",
          "next_action": "rerun_attachment_classification",
          "retryable": True,
          "missing_fields": [],
          "limitations": ["현재 파일과 일치하는 분류 확인 기록이 없습니다."],
      }
  ]
  ```

  Do not include the raw caught exception.

- [ ] **Step 5: Add API transition tests**

  Extend the classification-confirmation Django tests to prove:

  - the client cannot send its own classification or workflow state;
  - stale snapshot confirmation returns `failed` with a safe next action;
  - successful fine-notice confirmation routes to OCR but not law/appeal/report;
  - OCR confirmation is still required before later nodes are queued.

- [ ] **Step 6: Run Task 4 GREEN tests**

  ```powershell
  python -m pytest test/test_attachment_workflow_service.py test/test_chat_orchestration_service.py test/test_analysis_job_query_service.py -q
  python backend/manage.py test chatbot.test_attachment_classification_confirmation_flow --verbosity 1
  ```

  Expected: all state and API transitions pass.

- [ ] **Step 7: Review checkpoint**

  Confirm `UploadedFileStatus`, models, migrations, generic polling loops, and
  paid-call retry policy are unchanged. Suggested later commit:

  ```text
  fix: expose safe attachment workflow states
  ```

---

### Task 5: Render attachment workflow states and add a synthetic notice fixture

**Files:**
- Create: `app/web/attachmentWorkflowUi.js`
- Create: `app/web/attachmentWorkflowUi.test.js`
- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `test/test_ui_v3_attachment_contract.py`
- Create: `test/fixtures/fine_notice/synthetic_fine_notice.json`
- Create: `test/test_synthetic_fine_notice_fixture.py`
- Modify: `test/test_chat_orchestration_service.py`

**Interfaces:**
- Produces `buildAttachmentWorkflowUi(workflows) -> Array<AttachmentWorkflowUi>`.
- UI model fields: `attachmentId`, `state`, `tone`, `title`, `description`,
  `action`, and `retryable`.
- Fixture contains synthetic fields only and no real PII.

- [ ] **Step 1: Write UI mapping RED tests**

  Assert every state has distinct, non-success copy:

  ```javascript
  const ui = buildAttachmentWorkflowUi([
    {
      attachment_id: "att_notice",
      state: "ocr_needs_confirmation",
      next_action: "confirm_ocr_fields",
      retryable: false,
      missing_fields: ["response_deadline"],
      limitations: [],
    },
  ]);

  assert.equal(ui[0].state, "ocr_needs_confirmation");
  assert.equal(ui[0].action, "confirm_ocr_fields");
  assert.match(ui[0].title, /OCR/);
  assert.doesNotMatch(ui[0].description, /완료|성공/);
  ```

  Assert `partial` and `failed` retain limitations and next action; unknown
  fields, URIs, and raw OCR are not copied into the UI model.

- [ ] **Step 2: Write fixture RED tests**

  Create a JSON contract test requiring exactly these safe fields:

  ```python
  assert set(fixture) == {
      "fixture_version",
      "document_disposition_type",
      "issuing_authority",
      "response_deadline",
      "synthetic_case_number",
  }
  assert fixture["fixture_version"] == "synthetic_fine_notice.v1"
  ```

  Reject phone-number, resident-ID, driver-license, email, `s3://`, local path,
  and signed-query patterns. Use values such as `가상시청`,
  `과태료 사전통지서`, `2026-08-07`, and `SYN-2026-0001`.

- [ ] **Step 3: Run Task 5 RED tests**

  ```powershell
  node --test app/web/attachmentWorkflowUi.test.js
  python -m pytest test/test_synthetic_fine_notice_fixture.py test/test_ui_v3_attachment_contract.py -q
  ```

  Expected: UI helper and fixture are missing.

- [ ] **Step 4: Implement the pure UI mapper**

  Export a frozen state-copy table and fail closed:

  ```javascript
  const WORKFLOW_COPY = Object.freeze({
    scan_running: {
      tone: "pending",
      title: "파일 안전 검사 중",
      description: "검사가 끝난 뒤 자료 분류를 진행합니다.",
    },
    classification_running: {
      tone: "pending",
      title: "자료 종류 확인 중",
      description: "분류 결과를 확인하기 전에는 OCR을 시작하지 않습니다.",
    },
    classified_waiting_confirmation: {
      tone: "attention",
      title: "자료 분류 확인 필요",
      description: "자료 종류를 확인하면 다음 분석을 진행합니다.",
    },
    ocr_running: {
      tone: "pending",
      title: "고지서 항목 추출 중",
      description: "추출값 확인 전에는 법령·이의 절차 판단을 진행하지 않습니다.",
    },
    ocr_needs_confirmation: {
      tone: "attention",
      title: "OCR 추출값 확인 필요",
      description: "추출된 고지서 항목을 확인하거나 수정해 주세요.",
    },
    analysis_ready: {
      tone: "success",
      title: "고지서 분석 준비 완료",
      description: "확인된 정보와 누락 정보, 근거와 한계를 검토해 주세요.",
    },
    partial: {
      tone: "attention",
      title: "일부 정보 확인 필요",
      description: "확보하지 못한 정보를 보완한 뒤 계속할 수 있습니다.",
    },
    failed: {
      tone: "danger",
      title: "자료 처리 확인 필요",
      description: "안내된 다음 행동으로 다시 진행해 주세요.",
    },
  });
  ```

- [ ] **Step 5: Render one workflow panel**

  In `FrontendAppShell.jsx`, derive UI only from
  `analysisResponse.attachment_workflows`. Render one
  `AttachmentWorkflowPanel` and use its state to decide whether the existing
  classification or OCR confirmation card is visible. Never display both
  cards. Render `partial/failed` limitations and the server-provided safe action
  label; do not invent retryability in React.

- [ ] **Step 6: Add the synthetic fixture and ID 4 handoff test**

  Add an orchestration test using:

  ```text
  첨부한 고지서를 분석해서 의견제출 또는 이의신청을 검토할 수 있는지 알려주세요.
  ```

  Simulate, in order, clean scan, fine-notice classification, classification
  confirmation, OCR confirmation request, confirmed OCR fields from the
  synthetic fixture, and analysis readiness. Assert no law/appeal/report step
  appears before OCR confirmation and that the final public response contains
  confirmed information, missing information, evidence summary, and
  limitations without fixture-private/raw fields.

- [ ] **Step 7: Run Task 5 GREEN tests**

  ```powershell
  node --test app/web/attachmentWorkflowUi.test.js app/web/consultationIntake.test.js
  python -m pytest test/test_synthetic_fine_notice_fixture.py test/test_ui_v3_attachment_contract.py test/test_chat_orchestration_service.py -q
  ```

  Expected: all tests pass.

- [ ] **Step 8: Review and user-owned commit checkpoint**

  Inspect UI copy for false completion language and inspect the fixture for real
  identifiers. Suggested later commit:

  ```text
  fix: expose safe attachment workflow states
  ```

---

### Task 6: Add `fact_conflicts` to the Supervisor strict contract

**Files:**
- Create: `app/services/fact_conflict_service.py`
- Create: `test/test_fact_conflict_service.py`
- Modify: `app/services/supervisor_llm_contract.py`
- Modify: `app/services/supervisor_llm_service.py`
- Modify: `app/services/supervisor_control_service.py`
- Modify: `app/services/chat_orchestration_service.py`
- Modify: `app/services/consultation_v2_service.py`
- Modify: `test/test_supervisor_llm_service.py`
- Modify: `test/test_supervisor_control_service.py`
- Modify: `test/test_chat_orchestration_service.py`

**Interfaces:**
- Supervisor output adds required `fact_conflicts: list[FactConflict]`.
- `FactConflict` contains `field` and at least two `candidates`.
- Produces `normalize_fact_conflicts(value: Any) -> list[dict[str, Any]]`.
- Produces `detect_same_message_fact_conflicts(user_text: str, source_message_id: str) -> list[dict[str, Any]]`.

- [ ] **Step 1: Write strict-schema RED tests**

  Assert `conversation_response_format` requires `fact_conflicts` and its item
  schema requires:

  ```python
  {
      "field": "signal_priority",
      "candidates": [
          {
              "value": "녹색 신호에 직진했다는 진술",
              "source_message_id": "msg_e2e_13",
              "confidence": 0.9,
          },
          {
              "value": "빨간불에 진입한 것으로 보일 수 있다는 진술",
              "source_message_id": "msg_e2e_13",
              "confidence": 0.8,
          },
      ],
  }
  ```

  Add normalization tests rejecting unknown fields, fewer than two candidates,
  blank values, duplicate normalized values, non-finite confidence, confidence
  outside 0.0–1.0, raw reasoning keys, and extra schema keys.

- [ ] **Step 2: Write same-message conflict RED tests**

  Use the exact ID 13 input:

  ```python
  conflicts = detect_same_message_fact_conflicts(
      "저는 녹색 신호에 직진했고 상대는 신호위반 좌회전이었습니다. 그런데 블랙박스에는 제가 빨간불에 진입한 것처럼 보일 수도 있습니다. 과실이 몇 대 몇인가요?",
      "msg_e2e_13",
  )
  assert [item["field"] for item in conflicts] == ["signal_priority"]
  assert all(
      candidate["source_message_id"] == "msg_e2e_13"
      for candidate in conflicts[0]["candidates"]
  )
  ```

  Add non-conflict cases containing only green, only red, and generic
  “신호가 잘 안 보임”. The deterministic detector is a narrow safety net for
  opposed green-versus-red self-signal statements; the Supervisor contract
  handles other conflict types.

- [ ] **Step 3: Run Task 6 RED tests**

  ```powershell
  python -m pytest test/test_fact_conflict_service.py test/test_supervisor_llm_service.py test/test_supervisor_control_service.py test/test_chat_orchestration_service.py -q
  ```

  Expected: conflict module and strict field are missing; ID 13 loses the
  same-message contradiction.

- [ ] **Step 4: Implement conflict normalization and detection**

  In `fact_conflict_service.py`, import the allowed fields from
  `CORE_FACT_QUESTIONS`, normalize candidates, clamp nothing, and reject the
  entire invalid conflict rather than guessing. Return deterministic ordering
  by core-field order.

  The signal detector must:

  - require a first-person/self-vehicle marker near both opposed signal claims;
  - recognize `녹색|초록불` and `빨간불|적색`;
  - preserve uncertainty wording as a separate candidate;
  - return short normalized descriptions, never the entire user message.

- [ ] **Step 5: Extend the strict schema and LLM prompt**

  Add `fact_conflicts` to:

  - `conversation_response_format`;
  - `required_output_keys`;
  - `SUPERVISOR_CONVERSATION_SYSTEM_PROMPT`;
  - `_llm_state_candidate_error`;
  - `_normalize_llm_state`;
  - fallback and fail-closed Supervisor states.

  The server must normalize candidate conflicts before accepting them. It must
  not trust model-provided source identifiers that differ from the current
  request message ID.

- [ ] **Step 6: Merge deterministic and LLM conflicts in orchestration**

  Before reducing accident facts:

  ```python
  fact_conflicts = normalize_fact_conflicts(
      [
          *detect_same_message_fact_conflicts(user_text, source_message_id),
          *list(accident_supervisor_state.get("fact_conflicts") or []),
          *list(payload.get("fact_conflicts") or []),
      ],
      default_source_message_id=source_message_id,
  )
  conflict_fields = {item["field"] for item in fact_conflicts}
  fact_candidates = [
      item
      for item in extracted_candidates
      if item.get("field") not in conflict_fields
  ]
  ```

  Pass normalized conflicts to `reduce_consultation_fact_state`. Preserve
  candidate value, source message ID, and confidence in the conflict fact card.

- [ ] **Step 7: Ask only conflict fields and keep analysis blocked**

  In `build_consultation_state_v2`, when conflicts exist:

  ```python
  next_questions = [
      {
          "field": conflict["field"],
          "reason": "conflicting_claim",
          "question": CONFLICT_QUESTIONS[conflict["field"]],
      }
      for conflict in normalized_conflicts
  ]
  next_action = "resolve_fact_conflicts"
  ready_for_fault_range = False
  ```

  Do not append ordinary missing-field questions until conflicts are resolved.
  `evaluate_case_promotion` must return `ask_more`, and orchestration must return
  no executable analysis steps.

- [ ] **Step 8: Add ID 13 exact-input assertions**

  Assert:

  - routing is `accident_initial_consultation`;
  - one `signal_priority` conflict exists;
  - `vehicle_actions` remains a collected claim/card;
  - pending questions contain only `signal_priority`;
  - source and confidence exist on both conflict candidates;
  - `analysis_plan.steps == []`;
  - no `ratio_range`;
  - no Korean or Arabic fault-ratio pattern such as `\d+\s*[:대]\s*\d+`;
  - no text/ML case-search Agent invocation.

- [ ] **Step 9: Run Task 6 GREEN tests**

  ```powershell
  python -m pytest test/test_fact_conflict_service.py test/test_supervisor_llm_service.py test/test_supervisor_control_service.py test/test_chat_orchestration_service.py -q
  ```

  Expected: all tests pass.

- [ ] **Step 10: Review and user-owned commit checkpoint**

  Confirm strict-schema keys, prompt keys, normalization keys, reducer keys, and
  UI fact-card keys use the same `fact_conflicts`/`candidates` names. Suggested
  commit:

  ```text
  fix: preserve supervisor fact conflicts
  ```

---

### Task 7: Run G4 API/UI security and exact-scenario integration gates

**Files:**
- Modify only when a RED test proves a G4 regression:
  `backend/chatbot/test_production_hardening.py`
- Modify only when a RED test proves a G4 regression:
  `backend/chatbot/test_supervisor_reporting_pipeline.py`
- Modify only when a RED test proves a G4 regression:
  `test/test_privacy_boundaries.py`
- Modify only when a RED test proves a G4 regression:
  `test/test_ocr_privacy_contract.py`

**Interfaces:**
- Produces one local exact-scenario result for IDs 3, 4, 9, 11, and 13.
- Preserves ID 6 and ID 7 safety behavior.

- [ ] **Step 1: Run the exact G4 scenario suite**

  ```powershell
  python -m pytest test/test_fine_notice_intake_service.py test/test_public_law_projection_service.py test/test_attachment_workflow_service.py test/test_fact_conflict_service.py test/test_chat_orchestration_service.py test/test_supervisor_control_service.py test/test_supervisor_llm_service.py test/test_analysis_job_query_service.py test/test_synthetic_fine_notice_fixture.py -q
  ```

  Expected: zero failures.

- [ ] **Step 2: Run Django attachment/report boundary tests**

  ```powershell
  python backend/manage.py test chatbot.test_attachment_classification_confirmation_flow chatbot.test_production_hardening chatbot.test_supervisor_reporting_pipeline --verbosity 1
  ```

  Expected: zero failures; no pre-confirmation report or cross-session
  attachment confirmation.

- [ ] **Step 3: Run frontend G4 tests**

  ```powershell
  node --test app/web/consultationIntake.test.js app/web/attachmentWorkflowUi.test.js
  python -m pytest test/test_ui_v3_attachment_contract.py -q
  ```

  Expected: zero failures and all eight workflow states have public UI copy.

- [ ] **Step 4: Run safety and privacy regressions**

  ```powershell
  python -m pytest test/test_input_understanding_service.py test/test_service_scope_policy_service.py test/test_privacy_boundaries.py test/test_ocr_privacy_contract.py test/test_chat_input_privacy.py -q
  ```

  Explicitly confirm exact safety IDs 6 and 7 remain non-numeric/expert-gated
  according to their existing contracts.

- [ ] **Step 5: Review all G4 public payloads**

  Search production and captured response fixtures:

  ```powershell
  rg -n "provision_text|ocr_text|raw_text_redacted|storage_uri|s3://|file://|X-Guest-Credential|Authorization" app/services app/web backend/chatbot test
  ```

  Classify each match as internal-only implementation, intentional sentinel
  fixture, or public leak. Any public leak is RED and must be fixed in its
  owning task before proceeding.

---

### Task 8: Run full local regression, build, and checklist evidence

**Files:**
- Modify: `docs/tech-validation-reports/2026-07-31-pilot-hotfix-master-checklist.md`
- Modify: `docs/tech-validation-reports/2026-07-31-e2e-cross-analysis-final-hotfix-report.md` only if a finding or mitigation materially changes.
- Verify all G4 production and test files.

**Interfaces:**
- Produces local G4 gate state `GREEN`, `RED`, or `BLOCKED`.
- Produces exact commands, counts, warnings, changed files, and remaining
  production-only validation.

- [ ] **Step 1: Run the full Python suite**

  ```powershell
  python -m pytest -q
  ```

  Expected: zero failures. Compare against the G3 baseline of `1335 passed`,
  `37 skipped`, `4 subtests passed`, and one existing
  `LangChainPendingDeprecationWarning`; explain every count or warning change.

- [ ] **Step 2: Run all frontend tests**

  ```powershell
  node --test app/web/*.test.js
  ```

  Expected: at least the G3 baseline 52 tests plus new G4 tests, zero failures.

- [ ] **Step 3: Run the production frontend build**

  ```powershell
  npm run build
  ```

  Working directory: `app/web`.

  Expected: Vite exits 0 with no unresolved imports, syntax errors, or new
  build warnings requiring action.

- [ ] **Step 4: Run static diff checks**

  ```powershell
  git diff --check
  git status --short
  git diff --stat
  ```

  Inspect every changed file for unrelated G5 polling work, generated build
  artifacts, secrets, raw OCR/legal text, private paths, and accidental
  migration files.

- [ ] **Step 5: Update the master checklist**

  Mark HFX-014~016 and G4 items only when backed by passing commands. Record:

  - current branch and SHA;
  - exact test/build command;
  - pass/fail/skip counts;
  - warnings;
  - exact-input coverage for IDs 3, 4, 9, 11, and 13;
  - safety regression result for IDs 6 and 7;
  - public leak review result;
  - remaining G5/G7~G9 work.

- [ ] **Step 6: Final G4 review checkpoint**

  G4 is locally GREEN only when:

  - IDs 3, 4, 9, 11, and 13 pass;
  - IDs 6 and 7 pass;
  - all attachment workflow API/UI states pass;
  - raw OCR, private storage path, and PII public leaks are zero;
  - ID 13 emits no fault-ratio number and starts no analysis Agent;
  - full pytest, frontend tests, and production build pass;
  - `git diff --check` is clean.

- [ ] **Step 7: Present the user-owned Git handoff**

  Present changed files, validation counts, residual risks, and the recommended
  three commit boundaries:

  ```text
  fix: enforce fine notice intake contracts
  fix: expose safe attachment workflow states
  fix: preserve supervisor fact conflicts
  ```

  Wait for the user to review, stage, commit, and push. Do not merge or deploy;
  G5, G6, and the G7 production approval gate remain open.

---

## G4 Exit Criteria

- The fine-notice reducer always exposes the four approved required slots and
  asks for every missing value independently of law-search status.
- ID 9 retains fine-notice intent without reflecting profanity.
- ID 11 retains fine-notice intent without inventing facts.
- Public fine-notice legal results contain only safe law name, article, and
  verified short summary.
- The server exposes all eight attachment workflow states and the UI renders
  them without local state inference.
- Classification and OCR confirmations remain server-gated and snapshot-bound.
- Partial and failed attachment states expose safe next actions and truthful
  retryability.
- The synthetic fine-notice fixture contains no real PII or private paths.
- Supervisor strict output carries normalized `fact_conflicts`.
- ID 13 preserves the `signal_priority` conflict, retains `vehicle_actions`,
  asks only the conflict field, and emits no fault-ratio number.
- IDs 6 and 7 remain safe.
- Focused tests, full pytest, all frontend tests, Vite build, and diff checks
  are GREEN.
- Production deployment and all 13 deployed E2Es remain open for G7~G9.
