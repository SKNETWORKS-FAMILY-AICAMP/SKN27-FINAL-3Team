# P0 Safety Boundary Hotfix Implementation Plan

> **Execution rule:** Implement each behavior test-first. Observe the focused test fail for the intended reason before editing production code.

**Goal:** Fix HFX-009, HFX-010, and HFX-011 so the exact E2E inputs for IDs 2, 8, 10, and 12 stop at the correct safety boundary without accidental expert handoff, sensitive-data propagation, or Agent/RAG execution.

**Baseline:** `origin/dev` and branch start SHA `61e0c56ba8a783423cb8a830e5d7088001e5593b`

**Branch:** `feat-pilot-safety-hotfix`

**Architecture:** Keep privacy rejection as the first fail-closed boundary. Add a deterministic `input_understanding_gate.v1` between privacy sanitation and routing. Make service-scope exclusions intent/context-aware. Keep the server-owned routing and plan policy authoritative, and return synchronous clarification responses with empty plans so backend views never enqueue Worker jobs.

**Approved scope:** HFX-009, HFX-010, HFX-011 only. Caddy access-log redaction remains in G3/HFX-013. Authentication, attachment/OCR, report, polling, deployment, and production E2E behavior remain untouched in this phase.

## Task 1: HFX-009 — Make exclusions intent and context aware

**Files**

- Modify: `test/test_service_scope_policy_service.py`
- Modify: `test/test_chat_orchestration_service.py`
- Modify: `app/services/service_scope_policy_service.py`
- Modify: `app/config/service_scope_policy.v1.json`
- Modify: `app/config/supervisor_routing_policy.v1.json`

**Contract**

- ID 2 exact input routes to `traffic_law_search`.
- A law question mentioning a pedestrian or crosswalk does not become an accident expert handoff.
- Actual pedestrian collision/fault context remains `expert_handoff`.
- `general_consultation` does not contain `law_ground_search`.

- [x] Add a failing service-scope test using the exact ID 2 text and assert `decision == "proceed"` and `scope_code == "traffic_law_reference"`.
- [x] Add a failing orchestration test using the exact ID 2 text and assert the plan contains only the traffic-law search path and no expert handoff.
- [x] Add a failing policy test asserting `plan_node_codes("general_consultation")` excludes `law_ground_search`.
- [ ] Run:

  ```powershell
  python -m pytest test/test_service_scope_policy_service.py test/test_chat_orchestration_service.py -q
  ```

  Expected RED: ID 2 receives `vehicle_pedestrian_collision`; general plan includes law search.

- [x] Add optional `applicable_intents` and `required_context_keywords` fields to excluded-case policy entries and validate both as non-empty string lists when present.
- [x] Apply pedestrian, cycle, and facility exclusions only to accident intents and matching accident context.
- [x] Preserve criminal, unsupported-domain, and high-risk behavior.
- [x] Remove `law_ground_search` from the `general_consultation` plan while retaining boundary nodes.
- [x] Re-run the focused tests and confirm GREEN.
- [ ] Run regression:

  ```powershell
  python -m pytest test/test_public_consultation_routing_service.py test/test_service_scope_policy_service.py test/test_chat_orchestration_service.py -q
  ```

## Task 2: HFX-010 — Block Korean-suffixed resident and driver IDs

**Files**

- Modify: `test/test_pii_masking.py`
- Modify: `test/test_chat_input_privacy.py`
- Modify: `backend/chatbot/test_production_hardening.py`
- Modify: `app/security/pii_masking.py`
- Modify only if the new UI regression proves necessary: `app/web/FrontendAppShell.jsx`
- Modify only if needed for a pure UI helper: `app/web/chatPrivacyUi.js`, `app/web/chatPrivacyUi.test.js`

**Contract**

- Resident IDs and driver-license IDs match with Korean particles, parentheses, whitespace, and punctuation.
- Adjacent extra digits do not create partial false positives.
- ID 8 is rejected before usage accounting, planning, persistence, or Worker queueing.
- Public metadata contains category names and counts only; it never contains raw matched values.
- The UI does not permanently append the rejected sensitive user text to conversation state.

- [x] Add parameterized RED tests for:
  - `900101-1234567이고`
  - `900101-1234567입니다`
  - `(900101-1234567)`
  - `11-22-333333-44입니다`
  - the exact ID 8 sentence
  - leading/trailing adjacent extra-digit non-matches
- [x] Add an API-level RED test by extending the existing privacy rejection test to the exact ID 8 input. Assert HTTP 400, raw identifiers absent, and `record_usage_event`, planner, and enqueue all not called.
- [ ] Run:

  ```powershell
  python -m pytest test/test_pii_masking.py test/test_chat_input_privacy.py backend/chatbot/test_production_hardening.py -q
  ```

  Expected RED: Korean-suffixed ID 8 reaches accepted/queue behavior.

- [x] Replace resident and driver-license outer `\b` anchors with digit boundaries `(?<!\d)` and `(?!\d)`.
- [x] Keep existing masking token and metadata contract unchanged.
- [x] Add the smallest UI error-state helper only if a focused regression proves the rejected raw text remains after the API error; do not alter request payload contracts.
- [x] Re-run focused tests and confirm GREEN.
- [ ] Run privacy regressions:

  ```powershell
  python -m pytest test/test_pii_masking.py test/test_chat_input_privacy.py test/test_privacy_boundaries.py test/test_ocr_privacy_contract.py backend/chatbot/test_operational_log_privacy.py -q
  ```

## Task 3: HFX-011 — Add `input_understanding_gate.v1`

**Files**

- Add: `app/services/input_understanding_service.py`
- Add: `test/test_input_understanding_service.py`
- Modify: `app/services/chat_orchestration_service.py`
- Modify: `backend/chatbot/views.py`
- Modify: `test/test_chat_orchestration_service.py`
- Modify: `backend/chatbot/test_production_hardening.py`

**Contract**

- Status is one of `accepted`, `needs_clarification`, `blocked_sensitive`, `out_of_scope`.
- ID 10 and ID 12 return `needs_clarification`, an empty `analysis_plan.steps`, and no Agent/Worker invocation.
- ID 9 remains `fine_notice_procedure`; profanity is not repeated to downstream planning or assistant output.
- ID 11 remains `fine_notice_procedure`.
- `needs_clarification` receives a neutral Korean prompt asking whether the issue is a fine notice, accident, or traffic-law question.

- [x] Add RED unit tests for the exact ID 9–12 texts.
- [x] Add RED orchestration tests asserting:
  - ID 10/12: `status == "needs_clarification"`, empty plan, no law node.
  - ID 9/11: `routing_intent == "fine_notice_procedure"`.
  - sanitized ID 9 text passed to Supervisor does not contain the profanity phrase.
- [x] Add a RED backend view test patching `enqueue_analysis_job_work` and assert it is not called for ID 10/12.
- [ ] Run:

  ```powershell
  python -m pytest test/test_input_understanding_service.py test/test_chat_orchestration_service.py backend/chatbot/test_production_hardening.py -q
  ```

  Expected RED: gate module/status does not exist and low-information inputs still queue law search.

- [x] Implement a deterministic gate with:
  - Unicode Korean compatibility-jamo detection
  - bounded profanity/emotional-noise removal
  - domain-intent signal preservation
  - no raw rejected text in decision metadata
- [x] Invoke the gate after privacy sanitation and attachment resolution but before routing.
- [x] Build a synchronous `needs_clarification` response with no executable steps or reporting payload.
- [x] Teach `backend/chatbot/views.py` to return clarification responses before Worker payload construction and enqueueing.
- [x] Keep usage behavior aligned with the existing `needs_input` path; do not silently change quota policy in this phase.
- [x] Re-run focused tests and confirm GREEN.

## Task 4: P0 integration and evidence gate

**Files**

- Modify: `docs/tech-validation-reports/2026-07-31-pilot-hotfix-master-checklist.md`
- Verify all production/test files changed in Tasks 1–3.

- [x] Run exact-input P0 suite:

  ```powershell
  python -m pytest test/test_input_understanding_service.py test/test_pii_masking.py test/test_chat_input_privacy.py test/test_service_scope_policy_service.py test/test_public_consultation_routing_service.py test/test_chat_orchestration_service.py backend/chatbot/test_production_hardening.py -q
  ```

- [x] Run related privacy, Supervisor, and contract regressions:

  ```powershell
  python -m pytest test/test_privacy_boundaries.py test/test_ocr_privacy_contract.py test/test_supervisor_control_service.py test/test_supervisor_plan_execution.py test/test_supervisor_production_contract.py backend/chatbot/test_operational_log_privacy.py -q
  ```

- [x] Run all frontend tests:

  ```powershell
  node --test
  ```

  Working directory: `app/web`

- [x] Run production frontend build:

  ```powershell
  npm run build
  ```

  Working directory: `app/web`

- [x] Run `git diff --check`.
- [x] Review the diff for raw PII/profanity fixtures outside test files, contract drift, new logs, and accidental HFX-012~018 edits.
- [x] Record commands, counts, warnings, and changed files in the master checklist.
- [x] Mark G1 complete only when exact IDs 2, 8, 10, and 12 plus safety regressions 7, 9, and 11 pass with no Worker invocation where prohibited.

## Verification result

- P0/Privacy/Routing/Supervisor: `179 passed`
- Django Production API and log privacy: `34 tests`, `OK`
- Frontend: `45 passed`
- Vite production build: success
- `git diff --check`: clean
- Intentional runner correction: Django modules were run with `backend/manage.py test`, not collected as plain pytest modules.

## Commit boundaries

1. `fix: align traffic scope routing with intent`
2. `fix: block Korean-suffixed identity numbers`
3. `fix: stop unclear chat input before agent routing`
4. `docs: record P0 hotfix verification evidence`

No commit, push, PR, merge, or deployment is performed until the phase diff and tests are reviewed. Production deployment remains gated by G7 user approval.
