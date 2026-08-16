# Phase 2-B2 ConfirmCaseFacts Application Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract `POST /api/cases/<case_id>/facts/confirm/` authorization, DTO validation, and repository-command orchestration into `ConfirmCaseFacts` without changing its public or persistence contract.

**Architecture:** `consultation_case_fact_confirmation` remains the HTTP adapter: it reads the request, derives identity, applies the existing login guard, maps exceptions to existing HTTP envelopes, serializes `ConfirmCaseFactsResponse`, and returns `201`. `app.application.cases.confirm_facts` owns the authorization-before-validation sequence and calls the unchanged `chatbot.case_repository.confirm_case_facts` transaction.

**Tech Stack:** Django, Pydantic, Python dataclasses, Django `TestCase`, AST boundary assertions, Docker Compose, GitHub Actions.

## Global Constraints

- Base SHA: `6f597b7e6ca21edadefe4f1c753d309d610129e7`.
- Implement P2-B2 only; P2-B3 `StartCaseAnalysis` is out of scope.
- Do not change `backend/chatbot/case_repository.py`, models, migrations, queue/worker code, frontend runtime, Dockerfile, Compose, dependencies, Terraform, or Explicit Mock Runtime.
- Preserve authorization-before-validation, `transaction.atomic`, `select_for_update`, request fingerprinting, exact replay, version increments, and `confirmed_facts_idempotency.v1` behavior.
- Preserve route, method, status, payload, headers, and existing error envelopes.
- Do not modify `consultation_case_workspace`, `consultation_case_analysis_jobs`, `analysis_jobs`, or `submit_chat_message`.
- Use append-only commits; do not amend, rebase, squash, reset, force-push, merge the Draft PR, or remove the safety worktree.

## Current Call Graph

```text
POST /api/cases/<case_id>/facts/confirm/
  -> consultation_case_fact_confirmation
  -> _json_body / _payload_with_request_identity / login guard
  -> get_case_access_metadata / authorize_resource_access
  -> _validate_request_dto(ConfirmCaseFactsRequest)
  -> confirm_case_facts
  -> ConfirmCaseFactsResponse / HTTP 201
```

## Target Call Graph

```text
POST /api/cases/<case_id>/facts/confirm/
  -> consultation_case_fact_confirmation
  -> _json_body / _payload_with_request_identity / login guard
  -> ConfirmCaseFactsCommand
  -> execute_confirm_case_facts
  -> get_case_access_metadata / authorize_resource_access
  -> ConfirmCaseFactsRequest.model_validate
  -> confirm_case_facts
  -> ConfirmCaseFactsResult
  -> ConfirmCaseFactsResponse / HTTP 201
```

## Responsibility and Interface

```python
@dataclass(frozen=True)
class ConfirmCaseFactsCommand:
    case_id: str
    identity_payload: Mapping[str, Any]
    raw_payload: Mapping[str, Any]

@dataclass(frozen=True)
class ConfirmCaseFactsResult:
    fact_version: dict[str, Any]

class CaseFactConfirmationAccessDenied(Exception):
    def __init__(self, access: dict[str, Any]) -> None: ...

def execute_confirm_case_facts(
    command: ConfirmCaseFactsCommand,
) -> ConfirmCaseFactsResult: ...
```

application command는 `ConfirmCaseFactsRequest`, 기존 repository functions, `access_subject_from_payload`, `authorize_resource_access`를 import한다. `ValidationError`를 import하거나 처리하지 않으며, 전파된 validation error의 기존 HTTP `422` envelope mapping은 View가 담당한다. Django HTTP type, decorator, `app.mock_runtime`, view, ORM model, transaction API를 import해서는 안 된다.

The repository remains the sole owner of `transaction.atomic`, `select_for_update`, exact replay, request fingerprints, fact-version creation, `Case.current_fact_version`, `active_fact_version_id`, `active_analysis_job_id`, and `confirmed_facts_idempotency.v1` metadata.

## API Non-change Matrix

| Surface | Required result |
| --- | --- |
| Route/method | `POST /api/cases/<case_id>/facts/confirm/` unchanged |
| Owner success | `201`, `confirmed_facts.v1`, existing fact version schema |
| Foreign owner | `403`, existing `object_access_denied` envelope before validation |
| Owner invalid request | `422`, `request_validation_error.v1` details unchanged |
| Missing Case | existing `consultation_case_error.v2` / `case_not_found` |
| Exact replay | same `fact_version_id`, no extra version |
| Changed payload | next `version_no`, updated active fact version, existing active-job reset |
| Queue effects | confirmation alone creates no `AnalysisJob`, `AgentWorkItem`, or queue dispatch |

## Tasks

### Task 1: Establish the plan baseline

**Files:**
- Create: `docs/superpowers/plans/2026-08-15-phase-02-b2-confirm-case-facts-use-case.md`

- [ ] Verify `dev` and `origin/dev` equal `6f597b7e6ca21edadefe4f1c753d309d610129e7` and create the detached safety worktree.
- [ ] Create `refactor/phase-02-b2-confirm-case-facts-use-case` from that Base.
- [ ] Commit only this plan with `docs: plan case fact confirmation extraction`.

### Task 2: Add RED characterization tests

**Files:**
- Create: `backend/chatbot/test_phase_02_case_fact_confirmation_use_case.py`

**Interfaces:**
- Consumes: existing route, `Case`, `ConfirmedFactVersion`, `AnalysisJob`, `AgentWorkItem`, authenticated test client.
- Produces: HTTP/persistence/boundary regression coverage for `ConfirmCaseFacts`.

- [ ] Write tests for owner success, exact replay, changed payload, foreign-owner invalid payload, owner invalid payload, missing Case, and no queue side effects.
- [ ] Add an AST test that requires `app.application.cases.confirm_facts` and forbids HTTP, Mock, ORM, and transaction dependencies; require the target view to exclude direct authorization, metadata, validation, and repository calls.
- [ ] Run `python backend/manage.py test chatbot.test_phase_02_case_fact_confirmation_use_case --verbosity 2`.
- [ ] Confirm RED fails only because `app.application.cases.confirm_facts` does not exist.
- [ ] Commit with `test: characterize case fact confirmation boundary`.

### Task 3: Extract the application command and validation response helper

**Files:**
- Create: `app/application/cases/confirm_facts.py`
- Modify: `backend/chatbot/views.py`
- Test: `backend/chatbot/test_phase_02_case_fact_confirmation_use_case.py`

**Interfaces:**
- Consumes: `ConfirmCaseFactsCommand` raw payload and identity payload.
- Produces: `ConfirmCaseFactsResult` or `CaseFactConfirmationAccessDenied` / `ValidationError` / existing `CaseRepositoryError`.

- [ ] Implement the dataclasses and `CaseFactConfirmationAccessDenied`.
- [ ] Implement `execute_confirm_case_facts` in this exact order: metadata lookup/fallback, `authorize_resource_access`, access-denied exception, `ConfirmCaseFactsRequest.model_validate`, `model_dump(mode="python")`, unchanged `confirm_case_facts` call, typed result.
- [ ] Extract `_request_validation_error_response(request, error)` from `_validate_request_dto` without changing its public `422` payload.
- [ ] Replace the target view's direct authorization, validation, and repository calls with the application command and existing HTTP mappings.
- [ ] Run the focused test suite until it is GREEN.
- [ ] Commit with `refactor: extract case fact confirmation application command`.

### Task 4: Preserve regressions and block boundary drift

**Files:**
- Modify: `.github/workflows/production-gate.yml`
- Test: `backend/chatbot/test_consultation_v2.py`, `backend/chatbot/test_phase_02_case_workspace_use_case.py`, `backend/chatbot/test_phase_02_case_fact_confirmation_use_case.py`

- [ ] Add the blocking `Phase 2 B2 case fact confirmation application boundary` step without `continue-on-error` or `|| true`.
- [ ] Run focused B2, existing fact-confirmation queue characterization, and P2-B1 suites.
- [ ] Perform two temporary negative controls: remove application authorization; bypass validated payload/application boundary. Each must fail its relevant test, then restore the original source exactly.
- [ ] Commit with `ci: block case fact confirmation boundary regressions`.

### Task 5: Verify, record evidence, and publish Draft PR

**Files:**
- Create: `docs/refactoring/receipts/phase-02-b2-confirm-case-facts-use-case.md`

- [ ] Run case, Phase 0/1, full Django, collection, static, frontend, Docker D1, and Compose D2 gates.
- [ ] Record only actual outcomes, Base-identical Windows observations, D1/D2 evidence, CI, and deferred P2-B3/production DB scope.
- [ ] Commit with `docs: record case fact confirmation extraction evidence`.
- [ ] Push the feature branch and create a Draft PR titled `refactor: extract case fact confirmation application use case`.
- [ ] Verify blocking CI and report `READY_FOR_PHASE_2_B2_REVIEW` only when all required gates pass.

## P2 Delta trusted identity 보완

`identity_payload`는 `ConfirmCaseFactsCommand`의 단일 authority input이다. application은 validation 전에 이 payload를 authorize하고 `access_subject_from_payload(identity_payload)["subject"]`를 호출한 뒤 authenticated `user_id`만 `confirm_case_facts`에 전달한다. View는 `owner_id`를 전달하지 않고 client payload `owner_id`는 authority가 아니며, 변경하지 않은 repository ownership check는 defense-in-depth fence로 유지한다.

`P2-B2` sensitivity는 `scripts/refactoring/verify_phase_02_b2_test_sensitivity.py`를 사용한다. temporary child process에서 runtime-only authorization 및 validation bypass를 실행하고 tracked source를 보존하며 `phase_02_b2_sensitivity.v1`를 기록한다. 이는 Phase 0 sensitivity evidence와 구분된다.

## Sensitivity

- Mutation A: application authorization을 allow로 runtime-patch한다. authorization이 더 이상 먼저 수행되지 않으므로 foreign-owner invalid-payload assertion은 실패해야 한다.
- Mutation B: invalid raw input이 repository에 도달하도록 `ConfirmCaseFactsRequest.model_validate`를 runtime-patch한다. owner invalid-payload `422` assertion은 실패해야 한다.
- 각 mutation은 external temporary child process에서 실행한다. tracked source는 변경하지 않고 실행 전후 Git status가 일치해야 하며, mutation 없이 focused suite가 통과해야 한다.

## Docker and Compose

- D1 image: `skn27-phase-02-b2-p2-delta-local`; CI-equivalent import, Django check, Django-aware B2 application import를 실행한다.
- D2 script: `scripts/refactoring/run_phase_00_compose_gate.sh`; use an external temporary Git Bash `python3` shim only if the WindowsApps alias remains unresolved. Remove the shim after execution and commit no local evidence.

## Rollback

Revert only the B2 commits in reverse order if the extraction must be withdrawn. Do not alter `backend/chatbot/case_repository.py` or rewrite history.

## Out of Scope

- P2-B3 `StartCaseAnalysis`
- Repository split and queue redesign
- Production DB audit
- Model/migration or frontend changes
