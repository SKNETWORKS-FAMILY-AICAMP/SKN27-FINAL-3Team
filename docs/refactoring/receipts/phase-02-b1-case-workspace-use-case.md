# Phase 2-B1 Case Workspace Application Use Case Receipt

## Baseline

- Base SHA: `744a7ac9d1cd85959104620460ecabffb593faf5`
- Branch: `refactor/phase-02-b1-case-workspace-use-case`
- Worktree mode: main worktree on the B1 branch; detached safety worktree at `D:\dev\project\SKN27-FINAL-3Team-phase-02-b1-safety`
- Phase 1 merge commit: `744a7ac9d1cd85959104620460ecabffb593faf5`
- Scope: only `GET /api/cases/<case_id>/workspace/`

## Graph

Before:

```text
GET /api/cases/<case_id>/workspace/
  -> consultation_case_workspace
  -> get_case_access_metadata
  -> authorize_resource_access
  -> get_case_workspace
  -> ConsultationCaseWorkspaceResponse
  -> _json_response
```

After:

```text
GET /api/cases/<case_id>/workspace/
  -> consultation_case_workspace
  -> GetCaseWorkspaceQuery
  -> execute_get_case_workspace
  -> get_case_access_metadata / authorize_resource_access / get_case_workspace
  -> GetCaseWorkspaceResult
  -> ConsultationCaseWorkspaceResponse
  -> _json_response
```

## Responsibility Matrix

| Layer | Responsibility | Verified exclusion |
| --- | --- | --- |
| `backend/chatbot/views.py` | request identity, existing login mapping, query construction, exception-to-HTTP mapping, DTO/JSON response | no direct `authorize_resource_access`, `get_case_access_metadata`, or `get_case_workspace` call in `consultation_case_workspace` |
| `app/application/cases/get_workspace.py` | case metadata fallback, authorization, workspace loading, typed result/access-denied exception | no `django.http`, `HttpRequest`, `JsonResponse`, `csrf_exempt`, `require_http_methods`, `app.mock_runtime`, or `backend.chatbot.views` dependency |
| `backend/chatbot/case_repository.py` | existing metadata query and `case_workspace.v2` payload construction | unchanged |

## API Nonchange Matrix

| Contract surface | Result |
| --- | --- |
| `GET /api/cases/<case_id>/workspace/` route and method | NO change |
| success status and `case_workspace.v2` payload | NO change |
| `case`, `confirmed_facts`, `case_evidence`, `analysis_jobs`, `reports`, `attachments` | NO change |
| middleware unauthenticated transport contract | NO change: `401 / auth_required / login` |
| adapter login guard contract | NO change: `403 / login_required / login / case_workspace` |
| foreign-owner access contract | NO change: `403 / object_access_denied` with public `object_access.v1` payload |
| missing case contract | NO change: `404 / case_not_found` |
| OpenAPI, frontend route catalog, headers, Models, migrations | NO change |

## Authorization, Transaction, and Mock Boundaries

- Authorization remains `get_case_access_metadata(case_id)` followed by the existing `authorize_resource_access(metadata, identity_payload)`.
- Missing metadata retains the legacy fallback `{\"type\": \"case\", \"case_id\": case_id}`.
- `CaseWorkspaceAccessDenied` retains the existing `_object_access_denied_response` HTTP mapping.
- `CaseRepositoryError`, including `CaseNotFound`, propagates to the existing `_case_repository_error_response` mapping.
- Transaction behavior: NO changes.
- ORM behavior: NO changes outside existing repository reads.
- Mock import 0 in `app/application/cases/get_workspace.py`; AST boundary test verifies it.
- Public `mock_scenario` marker is absent from owner workspace characterization.

## Verification

| Check | Result |
| --- | --- |
| `python backend/manage.py test chatbot.test_phase_02_case_workspace_use_case --verbosity 2` | PASS, 6 tests |
| sensitivity | Original PASS; mutant FAIL; failure kind `boundary`; restored true |
| `python backend/manage.py test chatbot.test_consultation_v2 chatbot.test_resource_ownership_e2e chatbot.test_guest_login_session_ownership_e2e --verbosity 1` | 48 PASS, 5 Base-identical `pymupdf._extra` DLL errors |
| Phase 0/1 requested gate | 16 PASS, 9 Base-identical `attachment_document_classification_adapter` fixture-resolution errors |
| `python backend/manage.py test chatbot --verbosity 1` | current: 461 tests, 1 failure and 20 errors; Base: 455 tests, same 1 failure and 20 errors; six B1 tests are the only count delta |
| full Django Base failure signatures | `pymupdf._extra` DLL load, `attachment_document_classification_adapter` resolution, existing quarantine EICAR portability failure |
| `python -m pytest -q --timeout=30 test/test_phase_01_collection_baseline_contract.py` | PASS, 6 tests |
| `python scripts/refactoring/verify_pytest_collection_baseline.py` | Base-identical Windows `pymupdf._extra` collection errors; baseline v2 gate cannot pass locally |
| `python backend/manage.py check` | PASS |
| `python scripts/generate_openapi_v1.py --check` | PASS |
| `python scripts/generate_frontend_case_routes.py --check` | PASS |
| `ruff check --select E9,F63,F7,F82 .` | PASS |
| `node --test app/web/*.test.js` | PASS, 155 tests |
| `npm --prefix app/web run build` | PASS; existing chunk-size warning only |
| `git diff --check` | PASS before receipt creation |
| Docker D1 | BLOCKED: Docker client exists, but `dockerDesktopLinuxEngine` Server pipe is absent |
| Compose D2 | BLOCKED: Docker Server pipe is absent and WSL cannot execute `/bin/bash` |

## Docker and Compose Gate Status

- D1 image build did not begin because Docker could not connect to `npipe:////./pipe/dockerDesktopLinuxEngine`.
- D2 could not start because `bash scripts/refactoring/run_phase_00_compose_gate.sh` failed before script execution with WSL `execvpe(/bin/bash) failed: No such file or directory`.
- No push and no PR creation are authorized while D1/D2 are blocked.

## Deferred Scope

- P2B2 `ConfirmCaseFacts`
- P2B3 `StartCaseAnalysis`
- repository split
- queue redesign
- Production DB audit
- backup cleanup
