# G5 Polling Semantics and E2E Evidence Design

## 1. Goal

G5 implements HFX-017 and HFX-018 without changing the worker queue, paid
Agent retry policy, database schema, or production deployment process.

The user must see the actual analysis state instead of a generic accepted
message, while developers and later production E2E runs receive stable,
privacy-safe evidence identifiers.

## 2. Scope

### Included

- A server-owned public progress contract for:
  `queued`, `running`, `partial`, `failed`, `needs_input`, and `success`.
- Separation of worker completion from semantic user-task completion.
- Safe public `retryable` and next-action guidance.
- Stable `job_id` and correlation reference for developer diagnostics.
- Polling exhaustion and transport-error behavior that preserves the latest
  known result.
- Database-backed polling continuity when transient progress cache state is
  absent after a backend restart.
- A privacy-safe E2E evidence bundle builder and validator for G9 capture.

### Excluded

- A new worker retry or requeue endpoint.
- Automatic replay of paid Agent calls.
- Changes to `AnalysisJobStatus`, `AgentWorkItemStatus`, models, or migrations.
- Changes to the worker lease, retry backoff, or generic queue loop.
- Production screenshots, image digests, deployment, and the 13 live E2Es.
  G5 defines and validates their bundle format; G8 and G9 collect the real
  evidence.

## 3. Chosen Architecture

### 3.1 Server-owned semantic progress

Create a pure service:

```python
build_analysis_progress(
    job: Mapping[str, Any],
    *,
    composed_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]
```

It returns:

```json
{
  "contract_version": "analysis_progress.v1",
  "semantic_status": "running",
  "terminal": false,
  "retryable": true,
  "next_action": "continue_polling",
  "user_message": "분석이 진행 중입니다. 확인된 결과는 완료되는 대로 표시됩니다.",
  "job_id": "job_...",
  "correlation_id": "work_..."
}
```

The allowlisted semantic statuses are exactly:

- `queued`
- `running`
- `partial`
- `failed`
- `needs_input`
- `success`

`job_id` comes from the persisted `AnalysisJob`. `correlation_id` reuses the
latest persisted `work_item_id`; no new identifier or migration is introduced.
Only identifier-shaped values are accepted.

### 3.2 Status precedence

The projector uses the following precedence:

1. A canonical job status of `queued` remains `queued`.
2. A canonical job status of `running`, or a work item status of `running` or
   `retrying`, becomes `running`.
3. Confirmable pending questions, fact conflicts, or attachment workflow states
   `classified_waiting_confirmation` and `ocr_needs_confirmation` become
   `needs_input` once the job is not actively queued or running.
4. A canonical `failed` job becomes `failed`.
5. A canonical `partial` job, any accepted partial Agent result, or a result
   carrying limitations becomes `partial`.
6. `success` is emitted only when the canonical job is `success` and the
   composed user result contains an actual assistant answer, structured result,
   card, or report link.
7. A worker item marked `success` cannot by itself produce semantic `success`.
   If the user result is absent, the outcome is `partial`.

`retryable` is true only for:

- `queued` or `running`, where the safe action is read-only polling;
- `failed` or `partial` when the persisted work item or domain workflow
  explicitly says retry is allowed.

`needs_input` is not treated as a retry. Its action is to answer the existing
question or confirmation request.

### 3.3 Public query integration

`load_analysis_result` and `load_analysis_job_detail` attach the same
`analysis_progress.v1` projection to queued, running, and terminal responses.
The projection is rebuilt from the canonical database record when transient
cache data is missing.

Public progress never exposes:

- raw worker payload or exception text;
- storage URIs or signed URLs;
- credentials, headers, or identity claims;
- raw OCR, RAG chunks, or provider responses.

### 3.4 Frontend behavior

Create a pure `analysisProgressUi.js` mapper. It:

- accepts only `analysis_progress.v1`;
- maps every semantic status to an explicit Korean label, tone, and safe
  message;
- returns the server-provided retry flag and next action without inventing
  success;
- fails closed on unknown versions or statuses.

The polling loop continues only while semantic status is `queued` or `running`.
When its local polling budget is exhausted, it returns the latest known result
with a safe delayed-status message and `retryable=true`. It must not replace
the result with “상담 내용을 접수했습니다.”

A transport error also preserves the latest result. The raw exception is
restricted to development diagnostics. The user sees only the safe progress
message.

The UI displays semantic status and retry availability. `job_id` and
`correlation_id` are sent only to `logDeveloperDiagnostic`; they are not
rendered in the user-facing status message.

### 3.5 Restart continuity

The existing database rows remain authoritative. A Django integration test
creates a persisted job and work item, omits or clears transient progress-cache
state, and then reads the analysis result through the public API. The returned
contract must retain the same job and work-item correlation reference and
continue with `queued` or `running`.

This verifies restart continuity without modifying queue processing or
pretending to restart a process inside a unit test.

## 4. E2E Evidence Bundle

Create a pure service:

```python
build_e2e_evidence_bundle(payload: Mapping[str, Any]) -> dict[str, Any]
validate_e2e_evidence_bundle(payload: Mapping[str, Any]) -> list[str]
```

The bundle contract is `pilot_e2e_evidence.v1` and contains:

```json
{
  "contract_version": "pilot_e2e_evidence.v1",
  "test_id": "ID-04-authenticated",
  "exact_input": "사용자가 실행한 정확한 입력",
  "executed_at": "2026-07-31T18:00:00+09:00",
  "account_type": "authenticated",
  "release": {
    "sha": "40-character git SHA",
    "frontend_image_digest": "sha256:...",
    "backend_image_digest": "sha256:..."
  },
  "browser_evidence": {
    "input_response_screenshot": "relative evidence artifact name"
  },
  "http": {
    "status_code": 200,
    "public_response": {}
  },
  "execution": {
    "routing_intent": "fine_notice_analysis",
    "node_list": [],
    "semantic_status": "needs_input",
    "job_id": "job_...",
    "correlation_id": "work_..."
  },
  "sanitized_logs": []
}
```

Validation fails when any required field is absent, the release SHA or digest
format is invalid, the semantic status is unknown, the screenshot reference is
an absolute/private path, or the HTTP status is not an integer.

Before returning a bundle, `exact_input`, `public_response`, and
`sanitized_logs` pass through `app.security.pii_masking.sanitize_pii`.
Credential-shaped fields are masked. Signed URLs, authorization headers, local
paths, and storage URIs are rejected rather than copied into the bundle.

G5 tests use synthetic values only. G9 supplies the real release SHA, immutable
image digests, screenshot artifact, public response, and sanitized operational
logs.

## 5. Error Handling

- Unknown persisted states fail closed to semantic `failed` with
  `retryable=false` and a generic safe message.
- Malformed progress contracts are ignored by the frontend mapper.
- Polling timeout is not declared a task failure; it is delayed status
  confirmation and remains retryable.
- Transport failure does not erase the last server response.
- Evidence validation returns field-specific error codes and never echoes the
  rejected secret or PII value.

## 6. Test Strategy

### Python unit and contract tests

- Every semantic status and precedence branch.
- Worker `success` without a user result becomes `partial`.
- Canonical success with a user result becomes `success`.
- `needs_input` overrides terminal partial presentation when confirmation is
  required.
- Unknown state fails closed.
- Job and work-item identifiers are the only diagnostic identifiers exposed.
- Evidence bundle accepts a complete synthetic bundle.
- Each required evidence field has a failing validation case.
- PII, credentials, signed URLs, raw OCR, and local paths never survive.

### Frontend tests

- All six statuses map to distinct public presentation.
- Unknown contracts produce no UI model.
- Poll budget exhaustion retains the last result and never emits the generic
  accepted fallback.
- Retry is displayed only when the server contract allows it.
- Developer diagnostics receive job/correlation references while public text
  does not contain them.

### Django integration

- Queued and running result endpoints return HTTP 202 with the progress
  contract.
- Terminal partial, failed, needs-input, and success results return HTTP 200.
- A persisted job remains pollable when transient cache state is absent.
- Ownership and guest-credential checks remain unchanged.

### Final G5 gate

- Focused Python, Django, and Node tests pass.
- Full Python and frontend suites pass.
- Vite production build succeeds.
- `git diff --check` is clean.
- No model, migration, paid retry, deployment, or G6/G7 work is included.

## 7. Operational Boundary

G5 is locally complete when the semantic progress and evidence bundle
contracts are GREEN. It does not claim that production evidence exists.
Actual screenshot capture, image digests, deployment logs, and all 13 E2Es
remain required in G8 and G9.
