# Fresh Supervisor Acceptance Fixture Design

## Status

- Design direction approved by the operator on 2026-08-02.
- This document authorizes local fixture preparation only.
- S3 publication and an additional paid provider smoke remain separate operator gates.

## Problem Statement

The initial public cutover for release `908e844fd6fa` reached the real Supervisor runtime smoke after all infrastructure, RAG, readiness, object-storage, Caddy, and Google OAuth checks passed. The smoke then completed its worker loop with a partial analysis instead of a ready report.

The failure is deterministic:

- SSM command `94f21b37-3c54-424a-b3e8-774f18f1f775` used `pilot-fine-notice-prior-notice.pdf`.
- The OCR result contained `notice_stage=사전통지` and `opinion_deadline=2025-02-07`.
- On 2026-08-02, `appeal_decision_flow` correctly produced `deadline_passed=true` and `judgment_status=denied`.
- The reporting handoff correctly became `draft` with `required_result_partial`.
- `objection_report_generation` did not execute, so the strict `--require-report` release gate failed.
- The deployment transaction rolled back to `current=none`; no public release was promoted.

The other existing canonical fixtures are not valid substitutes:

- `pilot-fine-notice-pedestrian-penalty.pdf` is a 2025 pedestrian traffic citation (`범칙금`), not the required fine-notice objection flow.
- `pilot-fine-notice-driver-ledger.pdf` has 2025 dates, while the current smoke request explicitly confirms `notice_stage=사전통지`.

The root cause is therefore an expired acceptance artifact, not an application, worker, provider, RAG, or Caddy failure.

## Decision

Create one new operator-reviewed, synthetic, PII-free prior-notice PDF with an unexpired opinion-submission deadline. Keep all production logic and strict release gates unchanged.

Rejected alternatives:

1. Do not accept `denied` or `partial` as a successful release smoke. That would stop proving that reporting works.
2. Do not inject a date that contradicts the PDF through the smoke command. That would weaken document-to-report fidelity.
3. Do not rebuild the application solely to change the smoke contract. The runtime contract is correct; the artifact is stale.

## Fixture Contract

### Identity and paths

- Local output: `output/pdf/pilot-fine-notice-prior-notice-valid-through-20260831-v1.pdf`
- S3 destination after approval: `s3://skn27-pilot-908708651753-clean/canonical/acceptance/pilot-fine-notice-prior-notice-valid-through-20260831-v1.pdf`
- The destination key is immutable for this acceptance run. Existing objects must not be overwritten.
- Expected content type: `application/pdf`
- Expected server-side encryption: `AES256`

### Visible safety markings

The first page must show all of the following prominently:

- `테스트 전용 문서`
- `실제 효력 없음`
- `개인정보 없는 운영 검증용 fixture`

The document must not use a real person, address, phone number, resident number, license number, vehicle number, bank account, or real case identifier.

### Required semantic fields

The rendered document must contain these exact values so the real OCR and downstream agents receive a coherent scenario:

| Field | Value |
| --- | --- |
| Document title | `과태료 부과 사전통지서` |
| Fine type | `과태료` |
| Notice stage | `사전통지` |
| Issuing authority | `테스트구청 교통행정과` |
| Charge number | `TEST-20260802-001` |
| Issue date | `2026-08-02` |
| Opinion deadline | `2026-08-31` |
| Violation date/time | `2026-07-31 10:30` |
| Violation location | `테스트 도로 구간` |
| Violation | `주정차 위반 테스트 데이터` |
| Applicable law | `도로교통법 제32조` |
| Fine amount | `120,000원` |
| Recipient | `테스트 사용자` |
| Vehicle reference | `TEST-0000` |

The layout should be a readable one-page A4 notice. It should look structured enough for OCR but must not imitate an official seal, signature, barcode, payment account, or other feature that could make it usable as a real notice.

## Data and Execution Flow

1. Generate the PDF locally from a deterministic builder.
2. Reopen it with `pypdf` and require exactly one page.
3. Extract all page text with `pdfplumber` and require every safety marking and semantic field above.
4. Render the page to PNG and inspect Korean glyphs, clipping, overlap, margins, hierarchy, and watermark visibility.
5. Compute the local SHA-256 and record the byte size.
6. Present the PDF and verification evidence to the operator.
7. Only after explicit approval, upload it to the exact new S3 key with `Content-Type=application/pdf` and `ServerSideEncryption=AES256`.
8. Read back object metadata and object bytes, then require the remote SHA-256 to equal the approved local SHA-256.
9. Acquire a new Google one-time authorization code. The previously used code was deleted after the failed transaction.
10. Obtain explicit approval for one additional paid Supervisor/provider smoke.
11. Run the existing final `Deploy-Pilot.ps1` cutover with the new fixture URI and no change to strict gates.
12. On success, take a public post-cutover snapshot, complete the 10-minute acceptance window, and run the 13 required E2E scenarios.

## Failure Handling

- If local text or visual verification fails, do not upload the PDF.
- If the fixture deadline is not later than the execution date, do not start a paid smoke.
- If the S3 key already exists, stop instead of overwriting it.
- If remote metadata or SHA-256 differs from the approved local artifact, stop before acquiring a Google code.
- If the cutover fails, do not rerun it. Retrieve the exact SSM stdout/stderr, confirm transaction state, and require a fresh Google code before any later attempt.
- Never relax `--require-real-agent-results`, `--require-persisted-handoff`, or `--require-report` to work around a fixture result.

## Security and Privacy

- The artifact contains synthetic data only.
- The PDF must not contain embedded attachments, JavaScript, forms, external links, or hidden metadata with local usernames or paths.
- The builder must use a Korean-capable local font without embedding any user-provided document.
- Google authorization codes, provider keys, and runtime environment values must never appear in the PDF, build logs, Git history, or S3 metadata.
- The generated PDF is an operational acceptance artifact, not user-facing legal guidance and not a substitute for a real notice.

## Verification Evidence Required Before Publication

- PDF page count: `1`
- No AcroForm field tree and no page annotations
- All required safety markings extracted exactly
- All required semantic values extracted exactly
- Korean text visually legible with no broken glyphs
- No clipping, overlap, or unreadable small text
- SHA-256 and byte size recorded
- The generated PDF remains a local/S3 operational artifact identified by SHA-256 and is not committed to Git
- Git diff contains only the builder, its deterministic validation test, and the spec/plan documents
- No secret or PII patterns detected

## Scope Boundaries

Included:

- Local deterministic fixture builder
- Local PDF artifact
- Automated structural/text validation
- Visual QA
- Operator-reviewed S3 publication workflow
- Reuse of the existing strict public cutover command

Excluded:

- Changes to appeal legal logic
- Changes to Supervisor planning or reporting gates
- Acceptance of partial/denied jobs as release success
- Automatic S3 publication
- Automatic paid provider execution
- General redesign of all acceptance fixtures
- The post-deployment 13 E2E scenarios, which remain mandatory after successful cutover

## Acceptance Criteria

This fixture work is complete only when:

1. The local PDF satisfies every structural, textual, visual, privacy, and hash check.
2. The operator explicitly approves the rendered PDF.
3. The exact approved bytes exist at the new immutable S3 key with verified metadata and SHA-256.
4. A separately approved cutover uses that exact URI.
5. The strict Supervisor smoke reports `job_success`, `all_agent_results_success`, `real_agent_results`, `persisted_handoff_consumed`, and `report_ready` as true.
