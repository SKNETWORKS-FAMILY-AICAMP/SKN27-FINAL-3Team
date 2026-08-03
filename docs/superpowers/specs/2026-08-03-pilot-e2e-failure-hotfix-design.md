# Pilot E2E Failure Hotfix Design

## Goal

Fix every failure and downstream blocker recorded in
`docs/tech-validation-reports/2026-08-03-pilot-browser-manual-e2e-scenario-report.md`,
then prove the connected production browser journey through persisted report and appeal draft.

## Approved architecture

### Public agent results

Keep raw `structured_results` private. Add a versioned `public_results` projection built from
persisted agent results with node-specific allowlists. The public projection must support:

- attachment classification confirmation,
- fine-notice OCR confirmation,
- traffic-accident confirmation OCR presentation and CaseReady evidence,
- appeal-decision UI fields used by the existing frontend.

Private storage URIs, raw OCR, model/provider output, trace data, exception text, and sensitive
identity fields must remain absent. Both completed-result and restore/detail responses use the
same projector. The frontend consumes `public_results`, never raw `structured_results`.

### Attachment workflow

`traffic_accident_confirmation` attachments bypass generic document classification. Their
workflow is derived directly from `traffic_accident_confirmation_ocr` and uses the existing
`ocr_running`, `analysis_ready`, `partial`, and `failed` states.

### Fine-notice natural language

Extend the deterministic normalization policy for the observed `고지서 첨부가 가능합니다`
family. Preserve negation and uncertainty guards; do not add substring truth inference in the
reducer.

### Follow-up topic switching

Separate forced server routing, current-message content routing, and stored continuation routing.
A specific current-message route switches topic and does not inherit incompatible pending
questions, facts, fine-notice slots, or conversation history. Short ambiguous answers continue the
stored route. Server-confirmed attachment classification remains forced.

### Worker timeout

Do not increase a fixed polling count as a root-cause fix. Preserve job identity on polling
exhaustion, expose a recoverable status-check action, and record public correlation/job state so a
worker failure can be tied to queue, execution, or result persistence.

### Authentication persistence

Make storage writes return a result and verify the authenticated tuple by read-back without
logging token or session values. Distinguish storage failure, restore not started, verification
unavailable, reauthentication required, and resume failure. Transient verification failures retain
stored context and offer retry; 401/403 clears authenticated credentials while preserving guest and
chat lineage.

## Error handling and privacy

- Every public projector fails closed and returns only explicitly allowed scalar/nested fields.
- Attachment results are correlated by `attachment_id`.
- Unknown attachment purposes or statuses remain failed/blocked, never successful.
- Authentication telemetry contains booleans and reason codes only.
- Polling exhaustion is not represented as a terminal analysis failure unless the server reports a
  terminal failure.

## Verification

Use red-green TDD for every behavior change. Required gates are focused Python and Node tests,
full pytest, production Vite build, deployment from the resulting revision, and repeated browser
verification of J01, J02, J03, J04, J06, J08, persisted report, and appeal draft.

