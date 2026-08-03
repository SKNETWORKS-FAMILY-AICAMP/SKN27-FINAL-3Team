# Pilot Final Acceptance Hotfix Design

## 1. Goal

Fix only the four production defects confirmed during the pilot browser review, merge them into one final `dev` SHA, deploy that SHA once, and repeat the complete browser acceptance flow. If deployed validation fails, reproduce and fix only the failed step before rebuilding and redeploying.

## 2. Approved Scope

1. Prevent structured consultation labels from being stored as follow-up fact values.
2. Do not offer case analysis until material evidence is ready and usable.
3. Do not present an empty reporting payload as an actively progressing report.
4. Do not expose malformed pipe-delimited law fragments in public assistant answers.

## 3. Excluded Scope

- Do not modify `ai/**`, `etl/**`, models, migrations, AWS pipeline definitions, deployment scripts, or infrastructure.
- Do not change Case API, report API, OCR provider, legal retrieval engine, persistence model, privacy policy, or retention behavior.
- Do not add new consultation types, report types, OCR fields, routing intents, UI pages, or background jobs.
- Do not refactor unrelated frontend or service code.
- Do not change the existing material-evidence requirement enforced by the Case API.

## 4. Delivery Structure

Use one branch based on the latest `origin/dev`: `feat-pilot-final-acceptance-hotfix`.

Keep the four fixes in separate commits so each behavior can be reviewed and reverted independently. After all local checks pass, merge the branch into `dev`, build and deploy the resulting final SHA once, then run the complete external-Chrome acceptance suite.

Alternatives considered:

- Four separate branches and deployments: strongest isolation, but it creates multiple release SHAs and repeats the production approval cycle.
- Direct production-driven patching: starts quickly, but mixes diagnosis and deployment and makes regression attribution difficult.
- One branch with four isolated commits: preserves review boundaries while producing one final release SHA. This is the selected approach.

## 5. Follow-up Fact Transport

### Current failure

`FrontendAppShell` uses the structured request text for the current `user_text` and the current user turn in `conversation_history`. When the server is waiting for one core fact, `supervisor_control_service._question_answer_candidates` treats that entire text as the confirmed answer. The result contains `[상담 유형]`, `[사고 유형]`, and `[자유 입력]` inside the fact value.

### Design

Add a pure frontend transport selector in `consultationIntake.js`.

- Initial consultation requests keep the existing structured request text.
- When the current server response contains a pending follow-up question, the transport text for `user_text` and the current `conversation_history` turn is the user's trimmed display text only.
- Existing `consultation_type`, `facts`, and `fine_notice_slots` remain separate request fields and are not changed.
- The visible chat message remains the display text.
- No server reducer or Supervisor engine change is required.

### Acceptance

- A structured initial request still contains its approved sections.
- A follow-up answer such as `2차로 회전교차로` reaches the server exactly as that text.
- The resulting `road_layout` fact never contains the structured section labels.
- Existing initial accident and fine-notice normalization tests continue to pass.

## 6. Case-Ready Material Evidence Gate

### Current failure

`buildCaseReadyViewModel` can return `eligible: true` while `confirmationPayload.sources` is empty. The frontend offers `사건 생성·분석 시작`, but the Case API correctly rejects analysis with `fact_readiness_not_met` because all four values remain unverified claims.

### Design

- Build material sources before calculating eligibility.
- Require at least one ready attachment or accepted target-document OCR evidence source for `eligible: true`.
- `uploaded`, `scanning`, rejected, missing, or stale attachments do not satisfy the gate.
- Keep the backend material-evidence policy unchanged.
- Map `fact_readiness_not_met` to one fixed public message that tells the user to finish the attachment safety check. Other failures keep the existing safe generic message.
- Never expose raw server error details, OCR text, storage URIs, or internal identifiers in the message.

### Acceptance

- Four confirmed facts with no source are ineligible.
- Four confirmed facts with an uploaded but non-ready attachment are ineligible.
- Four confirmed facts with a ready attachment are eligible.
- Accepted target-document OCR evidence remains eligible even when the upload state in React is stale.
- A readiness rejection does not claim that report generation is in progress.

## 7. Reporting Workbench Truthfulness

### Current failure

Any truthy `reporting_payload` is treated as a report. A skeletal payload can therefore render a canvas whose stage falls back to `draft` (`작성 중`) and whose metadata falls back to `확인된 자료 없음`. The page itself does not poll for a missing report, so waiting does not complete that placeholder.

### Design

Add a pure meaningful-payload predicate in `reportWorkbenchState.js` and reuse it at both live-response and workbench boundaries.

A temporary payload is meaningful only when it contains at least one of:

- a non-empty summary;
- a non-empty `sections` array;
- a non-empty `document_cards` array.

A persisted report with `report_id` and `content.reporting_payload` remains valid under the existing persisted-report contract.

An empty or skeletal payload is not a report and renders the existing not-started, needs-information, or not-reportable state derived from Supervisor state. Do not add a new polling loop. Existing chat worker polling and explicit report-list refresh remain unchanged.

### Acceptance

- `{}` and `{ report_type: "general" }` are not report previews.
- A payload with a summary, section, or document card is a valid temporary preview.
- A persisted report detail remains available.
- `작성 중` is not shown unless an actual payload stage supplies a real report state.
- General legal guidance cannot open an empty report canvas.

## 8. Public Law Summary Sanitation

### Current failure

Verified law retrieval can return a short summary containing broken `|` table fragments. `_fine_notice_procedure_answer` places that summary inside a Markdown bullet. `SafeMarkdown` correctly treats the invalid GFM input as paragraphs, exposing the raw pipes and truncated table text.

### Design

Sanitize at the existing public projection boundary in `public_law_projection_service.py`, not inside the legal retrieval engine and not inside the general Markdown renderer.

- A public law summary containing pipe-delimited table fragments is omitted.
- The verified `law_name` and `article` remain visible.
- Normal readable summaries continue to be projected.
- Raw provision text, internal references, paths, and sensitive text remain excluded by the current allowlist.
- Do not attempt to reconstruct legal table semantics from malformed fragments.

### Acceptance

- A law item with a malformed pipe summary produces a readable law/article bullet without raw pipes.
- A normal short prose summary remains visible.
- Valid Markdown tables produced by other assistant answers continue to render through `SafeMarkdown`.

## 9. Error Handling and Privacy

- All new user messages are fixed Korean copy selected by public error code or local state.
- Do not place raw exception messages, request payloads, OCR values, storage locations, tokens, cookies, or identity data in UI messages or diagnostics.
- Existing high-risk, conflict, and document-confirmation gates remain unchanged.

## 10. Verification and Release Loop

Each fix follows red-green-refactor with a focused failing test before production changes.

Local verification order:

1. Focused Node or Python test for the current fix.
2. Related frontend and Supervisor contract suites.
3. All frontend Node tests.
4. Vite production build.
5. Root pytest regression.
6. Django chatbot regression.
7. `git diff --check` and excluded-path scope audit.

Release verification uses only the final merged `dev` SHA:

1. Confirm Source and Build for that SHA.
2. Approve and deploy that SHA once.
3. Run external Chrome with a fresh session per scenario.
4. Recheck fine-notice accumulation, accident initial and follow-up facts, authentication restore, and law answer rendering.
5. Run the four approved OCR documents separately.
6. Complete `case_ready → case → confirmed facts → analysis job → persisted report → objection draft`.
7. Require zero failed API calls and zero console errors on accepted paths.
8. If a step fails, add one failing test for that exact step, apply the smallest in-scope fix, rerun its focused regression plus the full connected journey, rebuild, and redeploy a new final SHA.

## 11. Completion Criteria

The hotfix is complete only when:

- all four confirmed defects have automated regression coverage;
- all local regression and production build checks pass;
- the deployed SHA is recorded;
- all four OCR scenarios pass their allowed outcomes;
- the connected persisted-report and objection-draft journey passes;
- authentication refresh and session restoration pass;
- no confirmed blocker remains in the final browser acceptance report.
