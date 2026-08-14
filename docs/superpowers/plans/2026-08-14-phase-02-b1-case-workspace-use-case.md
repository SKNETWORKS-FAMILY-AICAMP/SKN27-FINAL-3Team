# Phase 2-B1 Case Workspace Application Use Case Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `GET /api/cases/<case_id>/workspace/`의 정책·repository orchestration을 `GetCaseWorkspace` application use case로 추출하면서 기존 HTTP 계약을 byte-for-byte 의미적으로 유지한다.

**Architecture:** `consultation_case_workspace`는 request identity 추출, login response, application 결과를 기존 DTO/JSON response로 변환하는 HTTP Adapter만 맡는다. 새 application use case는 case metadata 조회, authorization, workspace 읽기를 순서대로 수행하고 access denial을 typed exception으로 반환한다. repository 구현과 `get_case_workspace`의 payload 조립은 변경하지 않는다.

**Tech Stack:** Python 3, Django test runner, dataclasses, AST, GitHub Actions, Node.js test runner, Docker, Docker Compose.

## Global Constraints

- Base SHA는 `744a7ac9d1cd85959104620460ecabffb593faf5`이며 safety worktree는 detached 상태로 보존한다.
- B1은 `GET /api/cases/<case_id>/workspace/` 한 vertical slice만 다룬다.
- `consultation_cases`, fact confirmation, case analysis, `submit_chat_message`, `analysis_jobs`, `download_report`, Models, migrations, transaction, route, OpenAPI, frontend, worker/queue, mock runtime, Docker/Compose 설정, dependencies, Terraform은 변경하지 않는다.
- `backend/chatbot/case_repository.py` 및 `get_case_workspace`의 behavior는 변경하지 않는다.
- 기존 Phase 0/1 gate를 약화하지 않으며 skip, xfail, `continue-on-error`를 추가하지 않는다.
- append-only commit만 사용하며 amend, rebase, squash, reset, force push, merge, Ready 전환을 하지 않는다.
- backup 및 safety worktree를 삭제·수정·복사하지 않는다.

## Current and Target Graph

현재 graph:

```text
GET /api/cases/<case_id>/workspace/
  -> consultation_case_workspace
  -> get_case_access_metadata
  -> authorize_resource_access
  -> get_case_workspace
  -> ConsultationCaseWorkspaceResponse
  -> _json_response
```

대상 graph:

```text
GET /api/cases/<case_id>/workspace/
  -> consultation_case_workspace (HTTP Adapter)
  -> GetCaseWorkspaceQuery
  -> execute_get_case_workspace (Application)
  -> get_case_access_metadata / authorize_resource_access / get_case_workspace
  -> GetCaseWorkspaceResult
  -> ConsultationCaseWorkspaceResponse
  -> _json_response
```

## Responsibilities and Interface

| Layer | Responsibility | Must not own |
| --- | --- | --- |
| `backend/chatbot/views.py` | identity extraction, login guard, request-to-query conversion, exception-to-existing HTTP response mapping, DTO serialization | direct metadata lookup, authorization call, workspace repository call |
| `app/application/cases/get_workspace.py` | case metadata fallback, authorization, workspace loading, typed result/access denial | `HttpRequest`, `JsonResponse`, decorator, mock runtime, direct view import, ORM write, transaction |
| `backend/chatbot/case_repository.py` | existing metadata and `case_workspace.v2` payload read behavior | B1 application policy changes |

```python
@dataclass(frozen=True)
class GetCaseWorkspaceQuery:
    case_id: str
    identity_payload: Mapping[str, Any]

@dataclass(frozen=True)
class GetCaseWorkspaceResult:
    workspace: dict[str, Any]

class CaseWorkspaceAccessDenied(Exception):
    def __init__(self, access: dict[str, Any]) -> None: ...

def execute_get_case_workspace(
    query: GetCaseWorkspaceQuery,
) -> GetCaseWorkspaceResult: ...
```

The application validates `query.case_id`, uses `get_case_access_metadata(case_id)`, falls back to `{"type": "case", "case_id": case_id}` only when metadata is absent, calls `authorize_resource_access(metadata, identity_payload)`, raises `CaseWorkspaceAccessDenied(access)` when denied, then calls `get_case_workspace(case_id)` and wraps the result. `CaseRepositoryError` propagates to the adapter unchanged.

## Changed Files

| Path | Change |
| --- | --- |
| `docs/superpowers/plans/2026-08-14-phase-02-b1-case-workspace-use-case.md` | this executable plan |
| `app/application/__init__.py` | application package marker |
| `app/application/cases/__init__.py` | cases package marker |
| `app/application/cases/get_workspace.py` | B1 query, result, access-denied exception, execution function |
| `backend/chatbot/views.py` | only `consultation_case_workspace` orchestration extraction |
| `backend/chatbot/test_phase_02_case_workspace_use_case.py` | HTTP characterization, application boundary, AST responsibility tests |
| `.github/workflows/production-gate.yml` | blocking B1 test step |
| `docs/refactoring/receipts/phase-02-b1-case-workspace-use-case.md` | verification and scope receipt |

## API Nonchange Matrix

| Contract surface | B1 change |
| --- | --- |
| `GET /api/cases/<case_id>/workspace/` route | NO |
| HTTP method | NO |
| status codes | NO |
| response payload and headers | NO |
| authentication and ownership semantics | NO |
| OpenAPI and frontend route catalog | NO |
| `case_workspace.v2` composition | NO |
| database writes, transaction boundaries, queue/worker | NO |
| explicit mock runtime and Phase 1 canonical boundaries | NO |

## Tasks

### Task 1: Commit the B1 plan before implementation

**Files:**
- Create: `docs/superpowers/plans/2026-08-14-phase-02-b1-case-workspace-use-case.md`

- [ ] **Step 1: Verify the plan names only the eight allowed changed paths and B1 route.**

Run: `git diff --check -- docs/superpowers/plans/2026-08-14-phase-02-b1-case-workspace-use-case.md`

Expected: exit code 0.

- [ ] **Step 2: Commit only the plan.**

Run: `git add docs/superpowers/plans/2026-08-14-phase-02-b1-case-workspace-use-case.md; git commit -m "docs: plan phase 2 case workspace extraction"`

Expected: one append-only documentation commit.

### Task 2: Characterize current HTTP contract and write RED boundary tests

**Files:**
- Create: `backend/chatbot/test_phase_02_case_workspace_use_case.py`
- Read: `backend/chatbot/views.py`, `backend/chatbot/case_repository.py`, `backend/chatbot/repositories.py`, `app/contracts/consultation_case.py`, `backend/chatbot/api_response.py`

**Consumes:** Existing `consultation_case_workspace` flow and repository fixtures.

**Produces:** A test module that captures owner, unauthenticated, foreign-owner, and missing-case behavior without guessing status/error fields.

- [ ] **Step 1: Record the existing call order.**

The adapter order is `_request_access_payload`, `access_subject_from_payload`, `_case_login_required_response`, then B1 application call; existing response conversion remains `_object_access_denied_response`, `_case_repository_error_response`, `ConsultationCaseWorkspaceResponse`, `_json_response`.

- [ ] **Step 2: Write HTTP characterization tests.**

```python
response = self.client.get(f"/api/cases/{case_id}/workspace/", **owner_headers)
payload = response.json()
self.assertEqual(response.status_code, 200)
self.assertEqual(payload["workspace"]["contract"]["version"], "case_workspace.v2")
for key in ("case", "confirmed_facts", "case_evidence", "analysis_jobs", "reports", "attachments"):
    self.assertIn(key, payload["workspace"])
```

Capture unauthenticated and missing-case responses from the current route before asserting their concrete status, error code, and required action. Assert foreign-owner denial payload matches the existing ownership boundary and contains no `workspace`.

- [ ] **Step 3: Write application import and dependency boundary tests.**

```python
module = importlib.import_module("app.application.cases.get_workspace")
self.assertTrue(callable(module.execute_get_case_workspace))
```

Parse `app/application/cases/get_workspace.py` and reject imports/references to `django.http`, `HttpRequest`, `JsonResponse`, `csrf_exempt`, `require_http_methods`, `app.mock_runtime`, and `backend.chatbot.views`. Parse only `consultation_case_workspace` with AST and reject direct calls to `authorize_resource_access`, `get_case_access_metadata`, and `get_case_workspace`.

- [ ] **Step 4: Verify RED.**

Run: `python backend/manage.py test chatbot.test_phase_02_case_workspace_use_case --verbosity 2`

Expected: current HTTP characterization passes; only application import/symbol assertions fail with `ModuleNotFoundError` because `app.application.cases.get_workspace` does not exist.

- [ ] **Step 5: Commit the characterization tests.**

Run: `git add backend/chatbot/test_phase_02_case_workspace_use_case.py; git commit -m "test: characterize case workspace application boundary"`

Expected: one append-only test commit retaining the observed current HTTP contract.

### Task 3: Add the minimal application use case and extract the adapter

**Files:**
- Create: `app/application/__init__.py`
- Create: `app/application/cases/__init__.py`
- Create: `app/application/cases/get_workspace.py`
- Modify: `backend/chatbot/views.py` only in `consultation_case_workspace`
- Test: `backend/chatbot/test_phase_02_case_workspace_use_case.py`

**Consumes:** `GetCaseWorkspaceQuery`, existing `get_case_access_metadata`, `authorize_resource_access`, `get_case_workspace`, and existing `CaseRepositoryError` mapping in the view.

**Produces:** `execute_get_case_workspace(query) -> GetCaseWorkspaceResult` and `CaseWorkspaceAccessDenied(access)`.

- [ ] **Step 1: Add package markers and the use case.**

```python
metadata = get_case_access_metadata(query.case_id)
if metadata is None:
    metadata = {"type": "case", "case_id": query.case_id}
access = authorize_resource_access(metadata, query.identity_payload)
if not access["allowed"]:
    raise CaseWorkspaceAccessDenied(access)
return GetCaseWorkspaceResult(workspace=load_case_workspace(query.case_id))
```

Use `from chatbot.case_repository import get_case_access_metadata, get_case_workspace as load_case_workspace` and `from chatbot.repositories import authorize_resource_access`. Do not catch `CaseRepositoryError` in application code.

- [ ] **Step 2: Make the view a HTTP Adapter.**

Construct `GetCaseWorkspaceQuery(case_id=case_id, identity_payload=identity_payload)`, call `execute_get_case_workspace`, translate `CaseWorkspaceAccessDenied` through `_object_access_denied_response(request, exc.access)`, retain the existing `CaseRepositoryError` branch, and serialize `result.workspace` through the unchanged DTO and `_json_response`.

- [ ] **Step 3: Verify GREEN and regressions.**

Run: `python backend/manage.py test chatbot.test_phase_02_case_workspace_use_case --verbosity 2`

Expected: PASS.

Run: `python backend/manage.py test chatbot.test_consultation_v2 chatbot.test_resource_ownership_e2e chatbot.test_guest_login_session_ownership_e2e --verbosity 1`

Expected: PASS.

- [ ] **Step 4: Prove test sensitivity and restore exactly.**

Temporarily mutate the view to call `get_case_workspace` directly or temporarily remove application authorization, run the targeted test, verify a boundary/auth failure, restore with `apply_patch`, and rerun the targeted test to PASS. Record only original PASS, mutant FAIL, failure kind, and restored true in the receipt.

- [ ] **Step 5: Commit implementation.**

Run: `git add app/application/__init__.py app/application/cases/__init__.py app/application/cases/get_workspace.py backend/chatbot/views.py; git commit -m "refactor: extract case workspace application use case"`

Expected: one append-only implementation commit.

### Task 4: Add blocking CI and record evidence

**Files:**
- Modify: `.github/workflows/production-gate.yml`
- Create: `docs/refactoring/receipts/phase-02-b1-case-workspace-use-case.md`

**Consumes:** passing B1 test module and final commit SHA.

**Produces:** a blocking CI test step and auditable B1 receipt.

- [ ] **Step 1: Add the blocking workflow step.**

```yaml
- name: Phase 2 B1 case workspace application boundary
  run: |
    python backend/manage.py test \
      chatbot.test_phase_02_case_workspace_use_case \
      --verbosity 1
```

Do not add `continue-on-error` or any pass-through conditional.

- [ ] **Step 2: Write the receipt.**

Include baseline/base SHA/branch/worktree mode/Phase 1 merge commit; before/after graph; responsibility and API nonchange matrices; auth and transaction conclusions; `mock import 0`; sensitivity record; all local, D1, and D2 commands; and deferred `P2B2`, `P2B3`, repository split, queue redesign, Production DB audit, and backup cleanup.

- [ ] **Step 3: Commit CI and receipt separately.**

Run: `git add .github/workflows/production-gate.yml; git commit -m "ci: block case workspace boundary regressions"`

Expected: one append-only CI commit.

Run: `git add docs/refactoring/receipts/phase-02-b1-case-workspace-use-case.md; git commit -m "docs: record case workspace extraction evidence"`

Expected: one append-only receipt commit.

### Task 5: Run all required verification and publish a Draft PR

**Files:** no further source changes.

- [ ] **Step 1: Run local quality and regression gates.**

Run the slice tests, case ownership regressions, Phase 0/1 gate, full Django suite, collection baseline contract and verifier, `python backend/manage.py check`, OpenAPI route test, frontend route tests/build, Ruff, and `git diff --check`. Compare Windows-only full-suite observations with the Base head; a B1 case authorization failure is never environment-specific.

- [ ] **Step 2: Run container gates.**

Run the D1 image build/import/settings smoke commands and `bash scripts/refactoring/run_phase_00_compose_gate.sh`. Do not push if D1 or D2 fails; D2 must show worker consumption, local staging, mock URI 0, and `cleanup_success` with no residual services.

- [ ] **Step 3: Confirm changed-path allowlist.**

Run: `git diff --name-only 744a7ac9d1cd85959104620460ecabffb593faf5..HEAD`

Expected: only the eight files listed in Changed Files. Any necessary additional path is `BLOCKED_BY_PHASE_2_B1_SCOPE`.

- [ ] **Step 4: Push and create the Draft PR.**

Run: `git push -u origin refactor/phase-02-b1-case-workspace-use-case`

Create a Draft PR to `dev` titled `refactor: extract case workspace application use case`. Its body contains only B1 scope, route, before/after graphs, API nonchange matrix, authorization/transaction statements, Phase 1 mock preservation, local verification, D1/D2 results, and P2B2/P2B3 exclusion. Keep it Draft and unmerged; do not rerun CI manually.

## Rollback

Use a normal revert commit for any committed B1 regression. Before push, restore an uncommitted temporary mutation with the exact inverse `apply_patch` and verify `git diff --check`. Do not use `git reset`, `git rebase`, `git commit --amend`, force push, or worktree deletion.

## Deferred Scope

- P2B2 `ConfirmCaseFacts`
- P2B3 `StartCaseAnalysis`
- repository split and queue/worker redesign
- Production DB audit
- backup cleanup

## Self-Review

- [x] The plan covers one B1 vertical slice and names every allowed changed path.
- [x] Every production function has a preceding RED test and expected failure mode.
- [x] The adapter/application/repository separation, API nonchange contract, sensitivity proof, rollback, CI, D1/D2, and Draft PR constraints are explicit.
