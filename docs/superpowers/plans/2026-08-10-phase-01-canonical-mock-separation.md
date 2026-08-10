# Phase 1 Canonical/Mock Runtime Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Canonical production requests must not import, dispatch to, persist, or expose an Explicit Mock runtime while existing local object-storage and Phase 0 production contracts remain available.

**Architecture:** Apply test-boundary-first separation. Move fixtures, sidecar JSON, mock attachment scenarios, mock analysis jobs, mock history, and mock agent execution to `app/mock_runtime/`; keep canonical code on neutral attachment staging and history-event contracts. Expose Explicit Mock HTTP routes only through an explicitly selected `config.mock_urls` URLConf that fail-closes unless both `EXPLICIT_MOCK_RUNTIME_ENABLED=True` and `DEBUG=True`.

**Tech Stack:** Python 3, Django URL resolver/tests, pytest, unittest, AST static checks, React/Vite frontend checks, GitHub Actions.

## Global Constraints

- Base commit: `9f05e8b67509c0a1f06bc39d631d6a7c94044a90`; working branch: `refactor/phase-01-canonical-mock-separation`.
- Never register `/api/mock/` in `backend/config/urls.py`; normal production uses only `config.urls`.
- `config.mock_urls` may resolve mock routes only when `EXPLICIT_MOCK_RUNTIME_ENABLED=True` and `DEBUG=True`; `DEBUG=False`, a disabled flag, default URLConf, and production settings fail closed.
- Canonical modules must not import `app.mock_runtime`, `analysis_job_mock_service`, `attachment_mock_service`, `history_event_mock_service`, `chatbot_mock_service`, `execute_mock_node`, `execute_mock_plan`, or `DL_MOCK_NODE_CODES`, including conditional or dynamic imports.
- Do not create a migration or remove `AnalysisJob.mock_scenario`; stop canonical write/read/serialization only. Production database audit remains `NOT_EXECUTED` unless independently authorised.
- Do not classify `mock_s3` or local object storage as Explicit Mock: it remains a Local Infrastructure Adapter implementing the production storage contract.
- Preserve all Phase 0 blocking gates. Do not use `skip`, `xfail`, weakened assertions, `continue-on-error`, paid provider calls, production mock switches, or public mock routes.
- Defer Phase 2/3 View/Application, queue, repository, storage, and bounded-context redesign. Do not change root Docker/Compose/Terraform/dependencies for this phase.

## Current Runtime Graph

1. `backend/config/urls.py` includes only canonical `api/` routes. This must remain true.
2. Canonical modules currently import `app.services.attachment_mock_service`, `history_event_mock_service`, and `analysis_job_mock_service`; `agent_node_service.py` holds mock dispatch globals and implementations.
3. `attachment_mock_service.py` contains both neutral staging/reference concerns and explicit fixtures; `history_event_mock_service.py` contains both history event construction and sidecar I/O. Extract the neutral portions before moving explicit behavior.
4. `AnalysisJob.mock_scenario` is a physical legacy column. Canonical repository/view code currently creates, reads, or returns it, and other canonical metadata currently writes `mock_status`/`canonical_mock` indicators.
5. Frontend production API entrypoints currently use `/api`; the static guard must ensure no production source or built artifact introduces `/api/mock/`.

---

### Task 1: Characterize import and URL boundaries first (RED)

**Files:**
- Create: `test/test_phase_01_runtime_import_boundaries.py`
- Create: `backend/chatbot/test_phase_01_mock_url_isolation.py`
- Modify: `backend/config/settings.py`
- Create: `backend/chatbot/mock_urls.py`
- Create: `backend/chatbot/mock_views.py`
- Create: `backend/config/mock_urls.py`

**Consumes:** existing `config.urls`, `chatbot.urls`, Django `override_settings`, `resolve`.

**Produces:** a fail-closed Explicit Mock URL contract and AST policy that later refactors cannot bypass.

- [ ] **Step 1: Write failing AST/import boundary tests**

```python
CANONICAL = (
    "backend/chatbot/views.py", "backend/chatbot/repositories.py",
    "backend/chatbot/file_scan_service.py", "app/services/chat_orchestration_service.py",
    "app/services/agent_node_service.py", "app/services/report_query_service.py",
)
FORBIDDEN = {"app.mock_runtime", "analysis_job_mock_service", "attachment_mock_service",
             "history_event_mock_service", "chatbot_mock_service", "execute_mock_node",
             "execute_mock_plan", "DL_MOCK_NODE_CODES"}
```

- [ ] **Step 2: Write failing URL isolation tests**

```python
with self.assertRaises(Resolver404):
    resolve("/api/mock/attachments/", urlconf="config.urls")
with override_settings(EXPLICIT_MOCK_RUNTIME_ENABLED=True, DEBUG=True):
    self.assertEqual(resolve("/api/mock/attachments/", urlconf="config.mock_urls").namespace, "mock")
with override_settings(EXPLICIT_MOCK_RUNTIME_ENABLED=True, DEBUG=False):
    with self.assertRaises(ImproperlyConfigured):
        resolve("/api/mock/attachments/", urlconf="config.mock_urls")
```

- [ ] **Step 3: Run RED tests**

Run: `python -m pytest test/test_phase_01_runtime_import_boundaries.py backend/chatbot/test_phase_01_mock_url_isolation.py -q`

Expected: FAIL because canonical imports and Explicit Mock URLConf do not yet meet the contract.

- [ ] **Step 4: Add the smallest URL-only settings and route scaffolding**

```python
# config/settings.py
EXPLICIT_MOCK_RUNTIME_ENABLED = os.environ.get("EXPLICIT_MOCK_RUNTIME_ENABLED", "0") == "1"

# config/mock_urls.py
if not (settings.EXPLICIT_MOCK_RUNTIME_ENABLED and settings.DEBUG):
    raise ImproperlyConfigured("Explicit Mock runtime is disabled outside local debug mode.")
urlpatterns = [path("api/", include("chatbot.urls")), path("api/mock/", include("chatbot.mock_urls"))]
```

- [ ] **Step 5: Re-run URL tests and commit characterization scaffolding**

Run: `python backend/manage.py test chatbot.test_phase_01_mock_url_isolation --verbosity 1`

Commit: `test: characterize phase 1 mock runtime boundaries`

### Task 2: Extract neutral attachment staging and history event contracts (GREEN)

**Files:**
- Create: `app/services/attachment_staging_service.py`
- Create: `app/services/history_event_contract.py`
- Modify: `backend/chatbot/repositories.py`
- Modify: `backend/chatbot/file_scan_service.py`
- Modify: `app/services/chat_orchestration_service.py`
- Modify: `app/services/agent_node_service.py`
- Modify: affected Phase 0 attachment/history tests

**Consumes:** production repository APIs and the Local Infrastructure Adapter.

**Produces:** `register_staged_attachment`, `resolve_staged_attachment_reference`, history builders/sanitizers, and neutral `staging_status`/`scan_status`/`storage_status` fields.

- [ ] **Step 1: Write failing focused tests for neutral contracts**

```python
record = register_staged_attachment(payload)
assert record["storage_status"] in {"staged", "available"}
assert "mock_status" not in record
assert sanitize_history_metadata({"mock_status": "success", "case_id": "c-1"}) == {"case_id": "c-1"}
```

- [ ] **Step 2: Run the targeted tests to confirm RED**

Run: `python -m pytest backend/chatbot/test_file_quarantine.py test/test_phase_01_runtime_import_boundaries.py -q`

- [ ] **Step 3: Move only neutral logic into the two new contracts and update canonical callers**

```python
from app.services.attachment_staging_service import (
    register_staged_attachment, resolve_staged_attachment_reference,
)
from app.services.history_event_contract import build_history_event, sanitize_history_metadata
```

- [ ] **Step 4: Run focused Phase 0 and import tests**

Run: `python backend/manage.py test chatbot.test_file_quarantine.FileQuarantinePipelineTests.test_multipart_registration_writes_only_to_quarantine --verbosity 1`

- [ ] **Step 5: Commit the neutral boundary**

Commit: `refactor: extract neutral attachment and history contracts`

### Task 3: Move Explicit Mock runtime and mock URLs behind the test boundary (GREEN)

**Files:**
- Create: `app/mock_runtime/__init__.py`
- Create: `app/mock_runtime/attachments.py`
- Create: `app/mock_runtime/analysis_jobs.py`
- Create: `app/mock_runtime/history.py`
- Create: `app/mock_runtime/agent_execution.py`
- Modify or remove: `app/services/*_mock_service.py`
- Modify: `backend/chatbot/mock_views.py`
- Modify: mock-only management commands and tests

**Consumes:** neutral contracts from Task 2.

**Produces:** Explicit Mock-only fixture, sidecar JSON, scenario, history, analysis-job, and agent functions that are never imported by canonical runtime modules.

- [ ] **Step 1: Write a failing mock runtime ownership test**

```python
from app.mock_runtime.agent_execution import DL_MOCK_NODE_CODES, execute_mock_node, execute_mock_plan
assert callable(execute_mock_node)
assert callable(execute_mock_plan)
```

- [ ] **Step 2: Run RED ownership/import tests**

Run: `python -m pytest test/test_phase_01_runtime_import_boundaries.py backend/chatbot/test_phase_01_mock_url_isolation.py -q`

- [ ] **Step 3: Move explicit implementations and update only mock/test/demo consumers**

Compatibility shims, if required by tests or local demo commands, must state that they are Explicit Mock compatibility only and are forbidden to canonical callers. Prefer deleting an unused shim.

- [ ] **Step 4: Verify mock URL calls use only `chatbot.mock_views`**

Run: `python backend/manage.py test chatbot.test_phase_01_mock_url_isolation --verbosity 1`

- [ ] **Step 5: Commit runtime isolation**

Commit: `refactor: isolate explicit mock runtime`

### Task 4: Remove canonical mock dispatch and persistence contamination (GREEN)

**Files:**
- Modify: `backend/chatbot/views.py`
- Modify: `backend/chatbot/api_response.py`
- Modify: `backend/chatbot/repositories.py`
- Modify: `backend/chatbot/file_scan_service.py`
- Modify: `app/services/agent_node_service.py`
- Modify: `app/services/report_query_service.py`
- Create: `backend/chatbot/test_phase_01_canonical_negative_reachability.py`
- Create: `backend/chatbot/test_phase_01_canonical_persistence.py`

**Consumes:** canonical repository/queue/worker interfaces and neutral contracts.

**Produces:** canonical requests that cannot call Explicit Mock code and never expose or persist the prohibited markers.

- [ ] **Step 1: Add failing canonical negative reachability and persistence tests**

```python
for marker in ("mock_scenario", "mock_status", "canonical_mock", "mock://", "mock_analysis_jobs", "mock_history_events"):
    assert marker not in canonical_response_text
    assert marker not in canonical_metadata_text
with patch("app.mock_runtime.analysis_jobs.create_analysis_job") as mock_call:
    call_canonical_api()
    mock_call.assert_not_called()
```

- [ ] **Step 2: Run RED tests and record the exact failures**

Run: `python backend/manage.py test chatbot.test_phase_01_canonical_negative_reachability chatbot.test_phase_01_canonical_persistence --verbosity 1`

- [ ] **Step 3: Remove canonical branches and writes without touching the legacy column/migration**

Replace `is_canonical_mock_request` with a request identity helper where necessary. Make canonical `api_surface` values truthful (`canonical` or `async_worker`), strip legacy mock input compatibility at the boundary, and use neutral status field names.

- [ ] **Step 4: Remove `DL_MOCK_NODE_CODES`, `execute_mock_node`, `execute_mock_plan`, and mock conditional dispatch from the production agent module**

Run: `python -m pytest test/test_phase_01_runtime_import_boundaries.py backend/chatbot/test_phase_01_canonical_negative_reachability.py backend/chatbot/test_phase_01_canonical_persistence.py -q`

- [ ] **Step 5: Commit canonical cleanup**

Commit: `refactor: remove canonical mock dependencies`

### Task 5: Enforce frontend, audit, CI, and documentation gates

**Files:**
- Create: `test/test_phase_01_frontend_mock_surface.py`
- Create: `scripts/refactoring/audit_phase_01_mock_persistence.py`
- Create: `docs/refactoring/phase-01/runtime-boundaries.md`
- Create: `docs/refactoring/phase-01/mock-consumer-migration.md`
- Create: `docs/refactoring/phase-01/mock-persistence-audit.md`
- Create: `docs/refactoring/receipts/phase-01-canonical-mock-separation.md`
- Modify: `.github/workflows/production-gate.yml`

**Consumes:** completed runtime boundary and test suite.

**Produces:** blocking CI checks, read-only local audit, Korean receipt, and clear consumer migration instructions.

- [ ] **Step 1: Write failing frontend source/bundle guard**

```python
assert "/api/mock/" not in production_source_text
assert "mock route" not in production_route_constants.lower()
```

- [ ] **Step 2: Implement a read-only count-only audit**

Run: `python scripts/refactoring/audit_phase_01_mock_persistence.py --format json`

The report must avoid user text, tokens, and storage URIs; record Local/Test result, `Production DB audit: NOT_EXECUTED`, and physical-column removal as deferred.

- [ ] **Step 3: Add Phase 1 tests as blocking workflow steps without removing Phase 0 gates**

Run: `python -m pytest test/test_phase_01_runtime_import_boundaries.py test/test_phase_01_frontend_mock_surface.py -q`

- [ ] **Step 4: Write Korean runtime-boundary, consumer migration, audit, and receipt documents**

Document canonical, Explicit Mock, Local Infrastructure Adapter distinctions, changed consumers, known debt, risks, rollback, and Phase 2/3 deferrals.

- [ ] **Step 5: Commit CI and documentation**

Commits: `test: enforce phase 1 canonical boundaries`; `ci: gate phase 1 runtime separation`; `docs: record phase 1 runtime separation evidence`.

### Task 6: Verify, scope-audit, publish, and observe CI

**Files:** no implementation changes expected; inspect only the allowed Phase 1 files above.

- [ ] **Step 1: Run required local verification**

```powershell
python backend/manage.py check
python backend/manage.py test chatbot.test_phase_00_core_user_flows chatbot.test_phase_00_ocr_law_flow chatbot.test_phase_00_report_lifecycle chatbot.test_file_quarantine.FileQuarantinePipelineTests.test_multipart_registration_writes_only_to_quarantine chatbot.test_consultation_v2.ConsultationCaseApiTests.test_fact_confirmation_precedes_real_worker_queue --verbosity 1
python backend/manage.py test chatbot.test_phase_01_mock_url_isolation chatbot.test_phase_01_canonical_negative_reachability chatbot.test_phase_01_canonical_persistence --verbosity 1
python -m pytest test/test_phase_01_runtime_import_boundaries.py test/test_phase_01_frontend_mock_surface.py -q
python scripts/refactoring/audit_phase_01_mock_persistence.py --format json
```

- [ ] **Step 2: Run preserved static, sensitivity, OpenAPI, frontend, Docker/import, and Compose gates**

Run their existing Phase 0 commands without `continue-on-error`. Record any pre-existing Windows EICAR limitation as known debt only after verifying it is unrelated to this patch.

- [ ] **Step 3: Audit scope and commits**

Run: `git diff --check 9f05e8b67509c0a1f06bc39d631d6a7c94044a90..HEAD`; inspect `git diff --name-only` against allowed Phase 1 files; verify no migration, root Docker/Compose/Terraform/dependency change, or Phase 2/3 architecture rewrite.

- [ ] **Step 4: Push and open Draft PR (do not merge)**

```bash
git push -u origin refactor/phase-01-canonical-mock-separation
gh pr create --base dev --head refactor/phase-01-canonical-mock-separation --draft --title "refactor: separate canonical and explicit mock runtimes"
gh pr checks --watch
```

- [ ] **Step 5: Report Korean receipt and terminal status**

Only emit `READY_FOR_PHASE_1_C` after Draft PR and all blocking CI gates pass. Never merge before independent Phase 1-C review.

## Rollback

Revert the individual Phase 1 commits in reverse order. The normal production URLConf was never changed to expose `/api/mock/`, no migration is created, and existing local object storage remains on its production adapter contract, so rollback does not require schema or storage data repair.

## Deferred Work

- Separate migration PR or Legacy Phase: physical removal of `AnalysisJob.mock_scenario` after production audit and data-retention decision.
- Phase 2: View/Application Use Case boundary redesign.
- Phase 3: queue, repository, storage, and bounded-context redesign.
