# Phase 2-B3 StartCaseAnalysis Application Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract `POST /api/cases/<case_id>/analysis/jobs/` authorization, DTO validation, and repository-command orchestration into `StartCaseAnalysis` without changing the public, transaction, reusable Job, or Queue contracts.

**Architecture:** `consultation_case_analysis_jobs` remains the HTTP adapter: it reads request JSON, derives the request identity, enforces the existing login fence, maps application/repository/validation exceptions to existing HTTP envelopes, serializes `StartCaseAnalysisResponse`, and returns `202`. `app.application.cases.start_analysis` owns authorization-before-validation and delegates unchanged persistence to `chatbot.case_repository.start_case_analysis`.

**Tech Stack:** Django, Pydantic, Python dataclasses, Django `TestCase`, AST boundary assertions, Docker Compose, GitHub Actions.

## Global Constraints

- Base SHA: `6c7688a17241b2e396420faaa2e00abeaa300e78`.
- Implement P2-B3 only; Phase 3 repository/Queue split is deferred.
- Do not change `backend/chatbot/case_repository.py`, `start_case_analysis()`, `enqueue_analysis_job_work()`, `backend/chatbot/repositories.py`, models, migrations, worker/lease/claim code, frontend runtime, Explicit Mock Runtime, Dockerfile, Compose script, dependencies, or Terraform.
- Preserve `transaction.atomic()`, `select_for_update()`, owner recheck, readiness gate, reusable Job statuses, Analysis Plan node ordering, Queue payload privacy, Case status, active IDs, route, method, status, payload, and headers.
- `identity_payload` is the sole authority input; client-provided `owner_id` is never authoritative.
- Preserve authorization-before-validation and the existing repository error envelope.
- Use append-only commits. Do not amend, rebase, squash, reset, force-push, merge the Draft PR, alter the safety worktree, or remove the Phase 1 broken backup.

## Current Call Graph

```text
POST /api/cases/<case_id>/analysis/jobs/
  -> consultation_case_analysis_jobs
  -> _json_body / _payload_with_request_identity / login guard
  -> get_case_access_metadata / authorize_resource_access
  -> _validate_request_dto(StartCaseAnalysisRequest)
  -> start_case_analysis
  -> StartCaseAnalysisResponse / HTTP 202
```

## Target Call Graph

```text
POST /api/cases/<case_id>/analysis/jobs/
  -> consultation_case_analysis_jobs
  -> _json_body / _payload_with_request_identity / login guard
  -> StartCaseAnalysisCommand
  -> execute_start_case_analysis
  -> get_case_access_metadata / authorize_resource_access
  -> access_subject_from_payload(identity_payload)
  -> StartCaseAnalysisRequest.model_validate
  -> start_case_analysis
  -> StartCaseAnalysisResult
  -> StartCaseAnalysisResponse / HTTP 202
```

## Responsibility Boundary

- HTTP Adapter: login fence, request/identity extraction, `CaseAnalysisAccessDenied` mapping, existing `ValidationError` `422` mapping, `CaseRepositoryError` mapping, response serialization, and `202`.
- Application Command: copy `identity_payload`, metadata fallback, authorization, trusted owner derivation, `StartCaseAnalysisRequest` validation, and delegation.
- Repository: unchanged outer `transaction.atomic()`, Case lock, owner fence, risk/readiness/session gates, fact-version selection, reusable Job lookup, plan construction, Queue persistence, and Case projection update.
- Queue privacy: `server_execution_context.context.user_facts` and `server_execution_context.context.case_evidence` remain server-only; public/execution payloads expose neither raw private URI nor `mock://`.

## API Non-change Matrix

| Surface | Required result |
| --- | --- |
| Route/method | `POST /api/cases/<case_id>/analysis/jobs/` unchanged |
| Owner success | `202`, `case_analysis_job.v2`, one queued Job and WorkItem |
| Foreign invalid request | `403 object_access_denied` before validation, no Queue row |
| Owner invalid request | existing `422 request_validation_error.v1`, no Queue row |
| Missing Case | existing repository status/error code |
| Missing confirmed facts | `409 confirmed_facts_required`, no Queue row |
| Insufficient readiness | `409 fact_readiness_not_met`, existing details, no Queue row |
| High risk / no session | existing `case_conflict`, no Queue row |
| Exact duplicate | same Job and WorkItem for the same FactVersion |
| New FactVersion | new Job and WorkItem; active FactVersion updates |
| Failed Job | never reused |
| Queue exception | outer repository transaction rolls back Job, WorkItem, and Case projection |

## Tasks

### Task 1: Establish baseline and plan

**Files:**
- Create: `docs/superpowers/plans/2026-08-17-phase-02-b3-start-case-analysis-use-case.md`

- [ ] Confirm `dev` and `origin/dev` equal `6c7688a17241b2e396420faaa2e00abeaa300e78`, PR #403 is merged, and create the detached safety worktree.
- [ ] Create `refactor/phase-02-b3-start-case-analysis-use-case` from the Base.
- [ ] Commit only this plan with `docs: plan case analysis application extraction`.

### Task 2: RED characterization and boundary tests

**Files:**
- Create: `backend/chatbot/test_phase_02_case_analysis_use_case.py`

- [ ] Characterize owner success, authorization-before-validation, invalid owner request, missing Case, confirmed-facts/readiness/high-risk/no-session gates, latest FactVersion selection, duplicate reuse, new FactVersion, failed-Job non-reuse, Queue payload privacy, and transaction rollback after original enqueue.
- [ ] Use only canonical `local://attachment-staging/phase-02-b3/...` test evidence URIs; never add `mock://`.
- [ ] Assert the exact Job node order: `text_ml_case_search`, `law_ground_search`, `objection_report_generation`.
- [ ] Add AST boundary assertions for `app.application.cases.start_analysis` and direct-call absence in `consultation_case_analysis_jobs`.
- [ ] Run `python backend/manage.py test chatbot.test_phase_02_case_analysis_use_case --verbosity 2` and require a module/boundary failure caused by the absent Application Command.
- [ ] Commit with `test: characterize case analysis application boundary`.

### Task 3: Extract the Application Command and reduce the View

**Files:**
- Create: `app/application/cases/start_analysis.py`
- Modify: `backend/chatbot/views.py`
- Test: `backend/chatbot/test_phase_02_case_analysis_use_case.py`

- [ ] Define frozen `StartCaseAnalysisCommand(case_id, identity_payload, raw_payload)`, `StartCaseAnalysisResult(response)`, and `CaseAnalysisAccessDenied`.
- [ ] Implement exactly: metadata lookup/fallback, `authorize_resource_access`, access-denied exception, trusted owner derivation through `access_subject_from_payload`, `StartCaseAnalysisRequest.model_validate`, `model_dump(mode="python")`, unchanged `start_case_analysis` delegation, typed result.
- [ ] Replace View direct authorization, DTO validation, and repository calls with the command while retaining all HTTP-only mappings and response behavior.
- [ ] Run the new B3 suite and P2-B1/B2 regression until GREEN.
- [ ] Commit with `refactor: extract case analysis application command`.

### Task 4: Add sensitivity evidence and CI gates

**Files:**
- Create: `scripts/refactoring/verify_phase_02_b3_test_sensitivity.py`
- Create: `test/test_phase_02_b3_sensitivity_runner.py`
- Modify: `.github/workflows/production-gate.yml`

- [ ] Implement `phase_02_b3_sensitivity.v1` evidence with a passing original suite and runtime-only authorization, validation, and reusable-Job mutations that each fail through assertion.
- [ ] Require tracked-source status equality and record the PR Head through `PHASE_02_B3_SENSITIVITY_HEAD`.
- [ ] Add blocking `Phase 2 B3 case analysis application boundary` and `Phase 2 B3 sensitivity negative controls` steps, plus `phase-02-b3-sensitivity-evidence` upload, without `continue-on-error` or `|| true`.
- [ ] Run runner unit tests and the runner itself.
- [ ] Commit sensitivity tests with `test: add phase 2 b3 sensitivity evidence`, then CI with `ci: block case analysis boundary regressions`.

### Task 5: Verify and publish evidence

**Files:**
- Create: `docs/refactoring/receipts/phase-02-b3-start-case-analysis-use-case.md`

- [ ] Run focused B3/B2/B1 tests, Case regressions, Phase 0/1 core gates, full Django, collection, OpenAPI, frontend route, Ruff, frontend tests/build, Docker D1, and Compose D2.
- [ ] Record actual outcomes, D1/D2 evidence, trusted identity and Queue privacy preservation, rollback evidence, CI results, and deferred Phase 3/production DB scope.
- [ ] Commit with `docs: record case analysis extraction evidence`.
- [ ] Push `refactor/phase-02-b3-start-case-analysis-use-case`, create the specified Draft PR, and wait for blocking CI. Do not merge or convert the Draft PR to Ready.

## Sensitivity Contract

- Mutation A: patch Application authorization to allow the foreign invalid request; the existing `403` assertion must fail.
- Mutation B: patch `StartCaseAnalysisRequest.model_validate` to admit invalid owner payload; the existing `422` assertion must fail.
- Mutation C: patch reusable-Job lookup so an exact duplicate creates a new Job; same Job/WorkItem ID and one-row assertions must fail.
- Every mutation runs in a temporary child process. Evidence records observed exit codes and assertion failure kinds; it never hardcodes success/failure.

## Docker and Compose

- D1 image: `skn27-phase-02-b3-local`; validate runtime imports, Django check, command field contract, `ROOT_URLCONF=config.urls`, and Explicit Mock disabled.
- D2 script: `scripts/refactoring/run_phase_00_compose_gate.sh`; use only an external temporary Git Bash `python3` shim if required by WindowsApps, delete it afterward, and retain no Compose residue.

## Rollback and Deferred Scope

- Revert only the P2-B3 commits in reverse order if extraction must be withdrawn; do not modify repository persistence to compensate.
- P2-B3 `StartCaseAnalysis` is the only included slice. Phase 3 repository/Queue split, Queue redesign, production DB audit, model/migration, and frontend changes remain deferred.
