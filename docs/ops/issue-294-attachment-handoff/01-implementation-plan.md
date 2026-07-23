# Attachment OCR Classification Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scan-ready image and PDF attachments are classified as fine notices, accident evidence, or unknown; users confirm that classification before the existing fine-notice or case-analysis Agent paths can run.

**Architecture:** Add an `attachment_document_classification` Supervisor node before existing fine-notice and accident flows. The node reads only canonical scan-ready bytes, emits a narrow privacy-safe classification result, and stores a server-owned confirmation record on `UploadedFile.metadata`. A confirmation request resolves that record server-side: fine notices retain the existing OCR confirmation gate; accident evidence enters the existing Case Workspace fact-confirmation path, which already queues `text_ml_case_search` and `law_ground_search` only after confirmed facts.

**Tech Stack:** Django, Pydantic contracts, existing OpenAI Vision provider boundary, PostgreSQL JSON metadata, Supervisor routing policy JSON, React, Vite, pytest, Django tests.

## Global Constraints

- Work only on `feat/294-chat-attachment-agent-handoff` and PR #295; do not create an Issue, pull request, branch, or worktree.
- Do not add a model provider or external vendor. Reuse the existing approved OpenAI Vision dependency already used by fine-notice OCR.
- Send bytes only for canonical `scan_ready`, `status=ready`, `scan_status=clean` image/PDF attachments; video remains on `vision_media_analysis`.
- Persist and log only attachment ID, scan revision, execution ID, category, confidence band, status, safe error code, action, and timestamps. Never persist or log OCR text, bytes, storage URI, PII, tokens, or secrets.
- A classification confirmation is not a fine-notice OCR confirmation and is not accident-fact confirmation. Each existing gate remains mandatory.
- `unknown`, low confidence, scan failures, and adapter failures must not invoke law, precedent, appeal, report, or fault analysis Agents.
- Use TDD: create a focused test, run it red, write minimal code, then run it green before the next behavior.

---

### Task 1: Define the public classification-confirmation contract and the first-pass routing plan

**Files:**

- Modify: `app/contracts/chat_session.py`
- Modify: `app/config/supervisor_routing_policy.v1.json`
- Modify: `app/services/supervisor_routing_service.py`
- Modify: `app/services/chat_orchestration_service.py`
- Test: `test/test_chat_orchestration_service.py`

**Interfaces:**

- Consumes: canonical attachment metadata (`attachment_id`, `type`, `content_type`, `purpose`, scan gate fields).
- Produces: `attachment_document_classification` plan and `AttachmentClassificationConfirmationRequest`.
- Does not execute: a classification adapter, law search, appeal, report generation, or case analysis.

- [ ] **Step 1: Add red routing tests**

Add these tests to `test/test_chat_orchestration_service.py`:

```python
def test_image_or_pdf_first_pass_queues_document_classification_before_declared_purpose() -> None:
    response = submit_message({
        "session_id": "ses_document_classification",
        "user_text": "첨부 자료를 확인해 주세요.",
        "attachments": [{
            "attachment_id": "att_document",
            "purpose": "fine_notice",
            "type": "pdf",
            "content_type": "application/pdf",
            "status": "ready",
            "scan_status": "clean",
        }],
    })

    assert response["routing_intent"] == "attachment_document_classification"
    assert [step["node_code"] for step in response["analysis_plan"]["steps"]] == [
        "input_context_validation",
        "attachment_document_classification",
        "agent_result_validation",
        "final_response_merge",
    ]


def test_traffic_accident_confirmation_keeps_its_specialized_ocr_route() -> None:
    response = submit_message({
        "session_id": "ses_specialized_ocr",
        "user_text": "사실확인원을 읽어 주세요.",
        "attachments": [{
            "attachment_id": "att_confirmation",
            "purpose": "traffic_accident_confirmation",
            "type": "image",
            "content_type": "image/png",
            "status": "ready",
            "scan_status": "clean",
        }],
    })

    assert response["routing_intent"] == "traffic_accident_confirmation_ocr"
```

- [ ] **Step 2: Run the focused tests and observe the missing route**

Run:

```powershell
python -m pytest test/test_chat_orchestration_service.py -k "document_classification or specialized_ocr" -q
```

Expected: the new image/PDF test fails because the policy selects `fine_notice_analysis` or the declared-purpose route; the specialized OCR regression remains green.

- [ ] **Step 3: Add the contract and route policy**

In `app/contracts/chat_session.py`, add the strict request shape without accepting a client-provided category:

```python
class AttachmentClassificationConfirmationRequest(ChatContractRequest):
    confirmed: bool = False
    attachment_id: str = Field(min_length=1, max_length=64)


class ChatMessageRequest(ChatContractRequest):
    # Keep all existing fields.
    attachment_classification_confirmation: AttachmentClassificationConfirmationRequest | None = None
```

In `app/config/supervisor_routing_policy.v1.json`, add the node to `plans` and `public_agent_node_codes`:

```json
"attachment_document_classification": [
  "input_context_validation",
  "attachment_document_classification",
  "agent_result_validation",
  "final_response_merge"
]
```

In `app/services/supervisor_routing_service.py`, add an image/PDF predicate before ordinary purpose rules. It must exclude `traffic_accident_confirmation` and every `blackbox_video` attachment:

```python
DOCUMENT_CLASSIFICATION_TYPES = frozenset({"image", "pdf"})
SPECIALIZED_DOCUMENT_PURPOSES = frozenset({"traffic_accident_confirmation"})


def requires_attachment_document_classification(attachments: list[dict[str, Any]]) -> bool:
    return any(
        isinstance(item, dict)
        and _text(item.get("type")).lower() in DOCUMENT_CLASSIFICATION_TYPES
        and _text(item.get("purpose")) not in SPECIALIZED_DOCUMENT_PURPOSES
        for item in attachments
    )
```

Make `route_supervisor_input` return `attachment_document_classification` when this predicate is true, before iterating `intent_rules`.

In `app/services/chat_orchestration_service.py`, normalize the confirmation as a narrow `{confirmed, attachment_id}` object and pass it into the later trusted-resolution helper introduced in Task 3. On first pass, do not set `report_requested` and do not add law, appeal, or report nodes.

- [ ] **Step 4: Run the focused tests green**

Run:

```powershell
python -m pytest test/test_chat_orchestration_service.py -k "document_classification or specialized_ocr" -q
```

Expected: PASS; image/PDF first-pass plans contain only the classification node, while specialized traffic-accident-confirmation OCR remains unchanged.

- [ ] **Step 5: Commit the routing contract change**

```powershell
git add app/contracts/chat_session.py app/config/supervisor_routing_policy.v1.json app/services/supervisor_routing_service.py app/services/chat_orchestration_service.py test/test_chat_orchestration_service.py
git commit -m "feat(#294): route documents through attachment classification"
```

### Task 2: Implement the canonical scan-ready OCR/document-classification adapter

**Files:**

- Create: `ai/agents/attachment_document_classification/__init__.py`
- Create: `ai/agents/attachment_document_classification/agent.py`
- Create: `app/services/attachment_document_classification_adapter.py`
- Modify: `app/services/agent_node_service.py`
- Test: `test/test_attachment_document_classification_adapter.py`
- Test: `test/test_agent_node_service.py`

**Interfaces:**

- Consumes: one canonical scan-ready image/PDF attachment and its bytes.
- Produces: `classification`, `confidence_band`, `requires_confirmation`, `next_action`, and an optional safe `error_code`.
- Does not produce: OCR text, visual descriptions, a fault ratio, legal advice, storage locations, or evidence payloads containing file paths.

- [ ] **Step 1: Write red adapter tests**

Create `test/test_attachment_document_classification_adapter.py` with a provider-boundary test and a sanitization test:

```python
def test_classify_document_normalizes_only_the_allowed_result_fields(monkeypatch):
    monkeypatch.setattr(adapter, "_request_classification", lambda *_args: {
        "classification": "fine_notice",
        "confidence": 0.93,
        "ocr_text": "010-1234-5678 / private text",
        "storage_uri": "s3://private/document.pdf",
    })

    result = adapter.classify_document_bytes(b"image-bytes", "image/png")

    assert result == {
        "status": "success",
        "structured_result": {
            "classification": "fine_notice",
            "confidence_band": "high",
            "requires_confirmation": True,
            "next_action": "confirm_classification",
        },
        "evidence": [],
        "next_actions": ["confirm_classification"],
        "limitations": [],
    }


def test_classify_document_returns_safe_unknown_when_provider_cannot_classify(monkeypatch):
    monkeypatch.setattr(adapter, "_request_classification", lambda *_args: {"classification": "other"})

    result = adapter.classify_document_bytes(b"image-bytes", "image/png")

    assert result["status"] == "partial"
    assert result["structured_result"]["classification"] == "unknown"
    assert result["structured_result"]["next_action"] == "change_purpose"
```

Add a `test/test_agent_node_service.py` test that supplies a canonical scan-ready image, patches `classify_document_bytes`, and verifies that the execution trace says `canonical_scan_ready_image_or_pdf`, the output contains no `s3://` value, and `validate_agent_output_envelope` accepts it.

- [ ] **Step 2: Run the adapter tests red**

Run:

```powershell
python -m pytest test/test_attachment_document_classification_adapter.py test/test_agent_node_service.py -k "document_classification" -q
```

Expected: FAIL because the adapter, node registry entry, and sync dispatcher do not yet exist.

- [ ] **Step 3: Create the provider adapter and node integration**

Implement `ai/agents/attachment_document_classification/agent.py` with only these allowed normalized values:

```python
CLASSIFICATIONS = frozenset({"fine_notice", "accident_evidence", "unknown"})
CONFIDENCE_BANDS = ((0.85, "high"), (0.60, "medium"), (0.00, "low"))


def normalize_classification(raw: Mapping[str, Any]) -> dict[str, str | bool]:
    classification = str(raw.get("classification") or "unknown").strip()
    if classification not in CLASSIFICATIONS:
        classification = "unknown"
    confidence = _bounded_float(raw.get("confidence"))
    confidence_band = next(label for threshold, label in CONFIDENCE_BANDS if confidence >= threshold)
    if classification == "unknown" or confidence_band == "low":
        return {
            "classification": "unknown",
            "confidence_band": confidence_band,
            "requires_confirmation": False,
            "next_action": "change_purpose",
        }
    return {
        "classification": classification,
        "confidence_band": confidence_band,
        "requires_confirmation": True,
        "next_action": "confirm_classification",
    }
```

`app/services/attachment_document_classification_adapter.py` must:

1. Accept bytes only for `image/jpeg`, `image/png`, `image/webp`, or `application/pdf`.
2. Convert a PDF to at most ten page images using the already installed `fitz` dependency.
3. Invoke the existing OpenAI client with an instruction to return only `classification` and numeric `confidence` JSON.
4. Return the normalized contract above; catch provider/parser exceptions as `status="failed"`, `error_code="document_classification_failed"`, and `next_action="retry_upload"`.

In `app/services/agent_node_service.py`, add `attachment_document_classification` to `NODE_REGISTRY`, `PRODUCTION_AGENT_TIMEOUT_SECONDS`, `_sync_adapter_node_codes`, `_run_sync_adapter`, and `_adapter_error_trace`. Add `_run_attachment_document_classification_adapter` that selects one image/PDF only when all canonical fields pass:

```python
def _is_scan_ready_classification_attachment(attachment: dict[str, Any]) -> bool:
    return bool(
        attachment.get("metadata_source") == "canonical_scan_gate"
        and attachment.get("resolution_status") == "scan_ready"
        and attachment.get("status") == "ready"
        and attachment.get("scan_status") == "clean"
        and attachment.get("type") in {"image", "pdf"}
        and str(attachment.get("storage_uri") or "").startswith("s3://")
    )
```

Read bytes through `_attachment_object_storage_bytes`, call the adapter, and pass its output through `_complete_adapter_output` with the safe trace fields only. Before returning the node output, add the selected canonical `attachment_id` to `structured_result`; it is the only attachment reference the confirmation UI may submit back to the server.

- [ ] **Step 4: Run adapter and registry tests green**

Run:

```powershell
python -m pytest test/test_attachment_document_classification_adapter.py test/test_agent_node_service.py -k "document_classification" -q
```

Expected: PASS; no test output or structured result contains raw OCR text, file bytes, or storage URI.

- [ ] **Step 5: Commit the real adapter connection**

```powershell
git add ai/agents/attachment_document_classification app/services/attachment_document_classification_adapter.py app/services/agent_node_service.py test/test_attachment_document_classification_adapter.py test/test_agent_node_service.py
git commit -m "feat(#294): add scan-ready document classification adapter"
```

### Task 3: Persist server-owned classification results and validate confirmation requests

**Files:**

- Create: `backend/chatbot/attachment_classification_service.py`
- Modify: `backend/chatbot/file_scan_service.py`
- Modify: `app/services/agent_node_service.py`
- Modify: `app/services/chat_orchestration_service.py`
- Test: `backend/chatbot/tests.py`
- Test: `test/test_chat_orchestration_service.py`

**Interfaces:**

- Consumes: clean `UploadedFile`, the classification adapter output, scan snapshot hash, session ID, and a confirmation containing only `attachment_id`.
- Produces: a trusted `{attachment_id, classification, confidence_band}` decision or a safe failure reason.
- Stores: `metadata["attachment_document_classification"]`; no schema migration is needed because `UploadedFile.metadata` already exists.

- [ ] **Step 1: Write red persistence and forgery tests**

Add Django tests that create a clean `UploadedFile` with a promoted snapshot hash and assert:

```python
def test_classification_record_uses_the_current_scan_snapshot_and_excludes_sensitive_fields(self):
    record = persist_attachment_document_classification(
        attachment_id=self.upload.attachment_id,
        storage_uri=self.upload.storage_uri,
        execution_id="exec_classification",
        structured_result={
            "classification": "accident_evidence",
            "confidence_band": "high",
            "requires_confirmation": True,
            "ocr_text": "must not persist",
        },
    )

    self.upload.refresh_from_db()
    stored = self.upload.metadata["attachment_document_classification"]
    assert record["classification"] == "accident_evidence"
    assert "ocr_text" not in stored
    assert "storage_uri" not in stored
    assert stored["scan_snapshot_sha256"] == "snapshot-current"


def test_confirmation_rejects_a_client_category_and_a_stale_scan_record(self):
    with self.assertRaises(AttachmentClassificationConfirmationError) as raised:
        resolve_confirmed_attachment_classification(
            session_id=self.session.session_id,
            attachment_id=self.upload.attachment_id,
        )

    self.assertEqual(raised.exception.code, "classification_stale_or_unavailable")
```

Add a `test_chat_orchestration_service.py` test that passes a forged client category and proves it cannot add `law_ground_search` or `text_ml_case_search` without a trusted record.

- [ ] **Step 2: Run the persistence tests red**

Run:

```powershell
python backend/manage.py test chatbot.tests -v 1
python -m pytest test/test_chat_orchestration_service.py -k "classification_confirmation" -q
```

Expected: FAIL because no metadata record or trusted resolver exists.

- [ ] **Step 3: Implement idempotent persistence and server-side resolution**

In `backend/chatbot/file_scan_service.py`, include the scan snapshot hash in the canonical handoff only for server-to-server execution:

```python
"scan_snapshot_sha256": _text(
    _dict(metadata.get("object_storage_write")).get("snapshot_sha256")
),
```

In `backend/chatbot/attachment_classification_service.py`, implement these functions:

```python
def persist_attachment_document_classification(
    *, attachment_id: str, storage_uri: str, execution_id: str, structured_result: Mapping[str, Any]
) -> dict[str, Any]:
    """Lock a clean attachment and store only the narrow classification record."""


def resolve_confirmed_attachment_classification(
    *, session_id: str, attachment_id: str
) -> dict[str, str]:
    """Return a current, high/medium-confidence server record and mark it confirmed."""
```

`persist_attachment_document_classification` must lock by `attachment_id`, require `READY`, `clean`, matching `storage_uri`, and matching current scan snapshot. It must reuse an identical successful record for the same snapshot and classification, otherwise replace only the classification metadata object. The stored object is exactly:

```python
{
    "contract_version": "attachment_document_classification.v1",
    "scan_snapshot_sha256": current_snapshot_hash,
    "status": "success" | "partial" | "failed",
    "classification": "fine_notice" | "accident_evidence" | "unknown",
    "confidence_band": "high" | "medium" | "low",
    "requires_confirmation": bool,
    "next_action": "confirm_classification" | "change_purpose" | "retry_upload",
    "error_code": "",
    "execution_id": execution_id,
    "classified_at": iso_timestamp,
    "confirmed_at": None,
}
```

The resolver must require the same session, current clean snapshot, `status="success"`, `requires_confirmation=True`, and a category of `fine_notice` or `accident_evidence`; it records `confirmed_at` and returns the category. It must reject `unknown`, low confidence, stale records, deleted files, and mismatched sessions with `AttachmentClassificationConfirmationError`.

Call the persistence function from `_run_attachment_document_classification_adapter` after the adapter yields a normalized output. Convert a persistence exception into `classification_result_persistence_failed`, with no confirmation card and no downstream plan.

In `app/services/chat_orchestration_service.py`, call the resolver only after scan-gate enrichment and only when the normalized confirmation has `confirmed=True`. Do not read a category from the request body.

- [ ] **Step 4: Run persistence and forgery tests green**

Run:

```powershell
python backend/manage.py test chatbot.tests -v 1
python -m pytest test/test_chat_orchestration_service.py -k "classification_confirmation" -q
```

Expected: PASS; a user can confirm only the server-stored current classification, while forged or stale confirmation cannot open downstream Agents.

- [ ] **Step 5: Commit the persistence boundary**

```powershell
git add backend/chatbot/attachment_classification_service.py backend/chatbot/file_scan_service.py app/services/agent_node_service.py app/services/chat_orchestration_service.py backend/chatbot/tests.py test/test_chat_orchestration_service.py
git commit -m "feat(#294): persist trusted attachment classifications"
```

### Task 4: Route confirmed categories into their existing gated analysis flows

**Files:**

- Modify: `app/services/chat_orchestration_service.py`
- Modify: `app/services/agent_node_service.py`
- Test: `test/test_chat_orchestration_service.py`
- Test: `backend/chatbot/test_supervisor_reporting_pipeline.py`

**Interfaces:**

- Consumes: trusted confirmation from Task 3 and existing fine OCR/case fact confirmation contracts.
- Produces: existing `fine_notice_analysis` first pass, or existing accident consultation/Case Workspace state.
- Preserves: fine-notice `ocr_confirmation`, accident fact confirmation, high-risk handoff, and the Case Worker plan `text_ml_case_search -> law_ground_search`.

- [ ] **Step 1: Add red end-to-end routing tests**

Add these focused assertions:

```python
def test_confirmed_fine_classification_still_requires_fine_ocr_confirmation():
    response = submit_message(trusted_fine_confirmation_payload())
    node_codes = [step["node_code"] for step in response["analysis_plan"]["steps"]]

    assert response["routing_intent"] == "fine_notice_analysis"
    assert node_codes == [
        "input_context_validation",
        "fine_notice_analysis",
        "agent_result_validation",
        "final_response_merge",
    ]


def test_confirmed_accident_evidence_enters_fact_confirmation_without_searching():
    response = submit_message(trusted_accident_confirmation_payload())

    assert response["routing_intent"] == "accident_initial_consultation"
    assert response["analysis_plan"]["steps"] == []
    assert response["consultation_state"]["attachment_evidence_refs"] == [
        {"attachment_id": "att_accident", "classification": "accident_evidence"}
    ]


def test_case_analysis_after_confirmed_facts_uses_existing_text_and_law_agents(self):
    queued = start_case_analysis(self.case.case_id, owner_id=self.owner_id, payload={
        "fact_version_id": self.confirmed_fact_version.fact_version_id,
    })

    assert queued["analysis_plan"]["node_codes"][:2] == [
        "text_ml_case_search", "law_ground_search"
    ]
```

- [ ] **Step 2: Run the route tests red**

Run:

```powershell
python -m pytest test/test_chat_orchestration_service.py -k "confirmed_fine_classification or confirmed_accident_evidence" -q
python backend/manage.py test chatbot.test_supervisor_reporting_pipeline -v 1
```

Expected: FAIL because confirmed categories are not yet converted into server-created routes and accident evidence references are absent.

- [ ] **Step 3: Implement the two safe handoffs**

In `app/services/chat_orchestration_service.py`, derive `routing_intent` only from the trusted resolver result:

```python
classification = _resolve_confirmed_attachment_classification(payload, attachments)
if classification["classification"] == "fine_notice":
    routing_intent = "fine_notice_analysis"
elif classification["classification"] == "accident_evidence":
    routing_intent = "accident_initial_consultation"
```

For the fine path, add a server-created `confirmed_classification="fine_notice"` field only to the local attachment object used for Agent selection. Update `_fine_notice_state` and `_has_fine_notice_attachment` to accept that field only when `metadata_source == "canonical_scan_gate"`; keep the current OCR confirmation checks unchanged.

For the accident path, add this non-factual evidence reference to `consultation_state` and `supervisor_state`:

```python
"attachment_evidence_refs": [
    {"attachment_id": attachment_id, "classification": "accident_evidence"}
]
```

Do not convert the attachment into a fact, do not set `facts_confirmed`, and do not create an Agent plan in this request. The existing `create_case` promotion already copies the consultation state into `Case.metadata["consultation_state"]` and attaches the session's clean uploads to the Case; retain that behavior. The existing `start_case_analysis` must continue to require confirmed facts before queueing `text_ml_case_search` and `law_ground_search`.

- [ ] **Step 4: Run the route tests green**

Run:

```powershell
python -m pytest test/test_chat_orchestration_service.py -k "confirmed_fine_classification or confirmed_accident_evidence" -q
python backend/manage.py test chatbot.test_supervisor_reporting_pipeline -v 1
```

Expected: PASS; fine classification cannot bypass OCR confirmation, accident classification cannot bypass facts, and confirmed Case analysis preserves the existing text/law Agent order.

- [ ] **Step 5: Commit the downstream handoffs**

```powershell
git add app/services/chat_orchestration_service.py app/services/agent_node_service.py test/test_chat_orchestration_service.py backend/chatbot/test_supervisor_reporting_pipeline.py
git commit -m "feat(#294): hand off confirmed document categories safely"
```

### Task 5: Add classification-confirmation UI and remove the misleading default-purpose behavior

**Files:**

- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `app/web/apiClient.js`
- Test: `test/test_frontend_auth_session_contract.py`

**Interfaces:**

- Consumes: `structured_results.attachment_document_classification` and the current attachment list.
- Produces: `{attachment_classification_confirmation: {confirmed: true, attachment_id}}` with no client category.
- Preserves: drag-and-drop, video auto-selection, existing editable fine OCR confirmation card, safe server retry messages, and async result polling.

- [ ] **Step 1: Write red frontend contract tests**

Add tests asserting the shell contains all of the following:

```python
assert "attachment_document_classification" in shell
assert "attachment_classification_confirmation" in shell
assert "classificationResult?.requires_confirmation === true" in shell
assert "attachment_id: classificationResult.attachment_id" in shell
assert "classification: classificationResult" not in shell
assert "setAttachmentPurpose(\"blackbox_video\")" in shell
```

Add a source-contract test that an image/PDF upload shows "OCR 분류 대기" but does not automatically send `purpose: "fine_notice"` as an authoritative classification.

- [ ] **Step 2: Run the frontend tests red**

Run:

```powershell
python -m pytest test/test_frontend_auth_session_contract.py -q
```

Expected: FAIL because no classification result state, confirmation card, or classification confirmation request exists.

- [ ] **Step 3: Implement the card and request wiring**

In `FrontendAppShell.jsx`:

1. Add `classificationResult` from `analysisResponse?.structured_results?.attachment_document_classification`.
2. Add `pendingAttachmentClassificationConfirmation` state.
3. Add `submitAttachmentClassificationConfirmation()` that sends only:

```javascript
const confirmation = {
  confirmed: true,
  attachment_id: classificationResult.attachment_id,
};
void submitServiceMessage({
  userText: "첨부 자료 분류 결과를 확인했습니다. 다음 절차를 진행해 주세요.",
  attachmentClassificationConfirmation: confirmation,
});
```

4. Extend `submitServiceMessage` and `api.submitChatMessage` payload plumbing to include `attachment_classification_confirmation`.
5. Render an `AttachmentClassificationConfirmationCard` only for a high/medium-confidence, confirmation-required result. It must say the category is a material classification, not a fault or legal conclusion; show a retry/purpose-change action for `unknown`, low confidence, or failure.
6. Change the initial image/PDF purpose label to `unknown` or `supporting_evidence`; keep `blackbox_video` as the automatic video purpose. The server classification, not this label, determines the route.

- [ ] **Step 4: Run frontend tests and production build green**

Run:

```powershell
python -m pytest test/test_frontend_auth_session_contract.py -q
npm run build
```

Run the npm command from `app/web`.

Expected: all frontend source-contract tests pass and Vite finishes successfully.

- [ ] **Step 5: Commit the UI confirmation flow**

```powershell
git add app/web/FrontendAppShell.jsx app/web/apiClient.js test/test_frontend_auth_session_contract.py
git commit -m "feat(#294): confirm attachment classification in chat"
```

### Task 6: Make classification execution observable without storing sensitive content

**Files:**

- Modify: `backend/chatbot/repositories.py`
- Modify: `backend/chatbot/tests.py`
- Modify: `backend/chatbot/test_analysis_job_queue.py`
- Modify: `docs/ops/project-readiness-master-checklist.md`

**Interfaces:**

- Consumes: classification node execution and existing `AgentInvocation` persistence.
- Produces: Agent invocation metadata with classification status/error code and traceable job/execution identifiers.
- Does not expose: `structured_result` values beyond the already sanitized classification contract.

- [ ] **Step 1: Write red observability tests**

Add a Django test that runs a queued classification work item and asserts:

```python
invocation = AgentInvocation.objects.get(job__job_id=job_id, node_code="attachment_document_classification")
assert invocation.status == "success"
assert invocation.error_code == ""
assert invocation.metadata["status_timeline"][-1]["status"] == "success"
serialized = json.dumps(invocation.metadata, ensure_ascii=False)
assert "ocr_text" not in serialized
assert "s3://" not in serialized
assert "010-1234-5678" not in serialized
```

Add a failure test for `document_classification_failed` that checks the invocation is retryable and contains the safe error code only.

- [ ] **Step 2: Run observability tests red**

Run:

```powershell
python backend/manage.py test chatbot.test_analysis_job_queue chatbot.tests -v 1
```

Expected: FAIL because the new node is not yet persisted and its classification metadata is not explicitly redacted.

- [ ] **Step 3: Whitelist classification metadata in Agent invocation persistence**

In `backend/chatbot/repositories.py`, extend `_agent_invocation_metadata` with a node-specific projection:

```python
if node_code == "attachment_document_classification":
    metadata["attachment_document_classification"] = {
        key: structured_result.get(key)
        for key in ("classification", "confidence_band", "requires_confirmation", "next_action", "error_code")
        if key in structured_result
    }
```

Apply `sanitize_pii` to the projected object, do not copy adapter input, attachment metadata, or arbitrary structured result keys, and retain the existing job/execution/status timeline fields. Update the readiness checklist only after the tests below pass: mark the classification handoff implemented, retain actual provider smoke and all real-environment checks as incomplete where they are not executed.

- [ ] **Step 4: Run observability tests green**

Run:

```powershell
python backend/manage.py test chatbot.test_analysis_job_queue chatbot.tests -v 1
```

Expected: PASS; successful and failed classification calls are traceable without raw material or secret leakage.

- [ ] **Step 5: Commit observability and checklist evidence**

```powershell
git add backend/chatbot/repositories.py backend/chatbot/tests.py backend/chatbot/test_analysis_job_queue.py docs/ops/project-readiness-master-checklist.md
git commit -m "feat(#294): trace attachment classification safely"
```

### Task 7: Regenerate contracts and run the five attachment handoff acceptance paths

**Files:**

- Modify: `docs/api/openapi.v1.yaml`
- Modify: `docs/ops/project-readiness-master-checklist.md`
- Test: `test/test_chat_orchestration_service.py`
- Test: `test/test_agent_node_service.py`
- Test: `test/test_attachment_document_classification_adapter.py`
- Test: `test/test_frontend_auth_session_contract.py`
- Test: `backend/chatbot/tests.py`

**Interfaces:**

- Consumes: the completed API contract, routing policy, adapter, persisted confirmation, UI flow, and existing Vision path.
- Produces: checked OpenAPI output and evidence for PDF fine notice, accident photo, video, unsupported file, and unknown classification behavior.

- [ ] **Step 1: Add acceptance tests for every required path**

Add or extend tests with these exact assertions:

```python
# PDF fine notice: classification -> confirmed category -> fine OCR, no law/appeal until OCR confirmation.
assert "law_ground_search" not in first_pass_node_codes

# Accident photo: confirmed category -> fact confirmation state, no search plan.
assert accident_response["analysis_plan"]["steps"] == []

# Video: Vision path remains the only media analysis node.
assert "vision_media_analysis" in video_node_codes
assert "attachment_document_classification" not in video_node_codes

# Unsupported file: intake rejects it before any analysis request.
assert upload_response.status_code == 400

# Unknown classification: safe result has no confirmation and no downstream nodes.
assert unknown_result["structured_result"]["classification"] == "unknown"
assert unknown_result["structured_result"]["next_action"] == "change_purpose"
```

- [ ] **Step 2: Run acceptance tests red if any path is not covered**

Run:

```powershell
python -m pytest test/test_chat_orchestration_service.py test/test_agent_node_service.py test/test_attachment_document_classification_adapter.py test/test_frontend_auth_session_contract.py -q
python backend/manage.py test chatbot -v 1
```

Expected: all newly added tests are present; any missing implementation behavior fails before the final fix.

- [ ] **Step 3: Regenerate and check the OpenAPI contract**

Run:

```powershell
python scripts/generate_openapi_v1.py
python scripts/generate_openapi_v1.py --check
```

Expected: `docs/api/openapi.v1.yaml` includes `attachment_classification_confirmation`; the check exits zero.

- [ ] **Step 4: Run full verification**

Run:

```powershell
python -m pytest test/test_chat_orchestration_service.py test/test_agent_node_service.py test/test_attachment_document_classification_adapter.py test/test_frontend_auth_session_contract.py -q
python backend/manage.py test chatbot -v 1
npm run build
git diff --check
```

Run the npm command from `app/web`. Expected: every command exits zero. A strict provider/Vision checkpoint smoke is not represented as passing unless it runs in an environment with its real configuration and checkpoint.

- [ ] **Step 5: Commit generated contract and final test evidence**

```powershell
git add docs/api/openapi.v1.yaml docs/ops/project-readiness-master-checklist.md test/test_chat_orchestration_service.py test/test_agent_node_service.py test/test_attachment_document_classification_adapter.py test/test_frontend_auth_session_contract.py backend/chatbot/tests.py
git commit -m "test(#294): verify attachment classification handoff"
```

## Final Review Gates

- [ ] Issue #294 intent is met: image/PDF classification is real, confirmed, and connected to existing fine/case flows.
- [ ] Existing fine OCR confirmation, accident fact confirmation, specialized traffic-accident OCR, video Vision, and report guards are unchanged unless explicitly specified above.
- [ ] No result calls a mock classification output a real analysis result.
- [ ] Tests cover all five attachment scenarios and sensitive-data redaction.
- [ ] Generated OpenAPI is current and the working tree has no unrelated changes.
- [ ] CI is green for the final head commit; a real-provider or Vision checkpoint smoke remains visibly unverified unless actually run.
