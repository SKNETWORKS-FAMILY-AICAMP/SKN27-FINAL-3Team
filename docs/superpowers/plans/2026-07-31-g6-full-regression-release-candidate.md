# G6 Full Regression and Release Candidate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the complete hotfix branch is locally release-candidate ready by running the approved safety, ownership, consultation, deployment, frontend, Django, Agent/RAG/graph, build, and Compose gates without deploying or invoking paid/live providers.

**Architecture:** G6 is an evidence-only integration gate. It runs narrow suites first so failures have a clear subsystem owner, then expands to the full Python, Django, Node, production-build, and rendered-Compose gates. Results are recorded against one immutable branch SHA in the master checklist and a dedicated evidence report; code changes are allowed only for a reproduced regression and must follow a separate RED/GREEN cycle.

**Tech Stack:** Git, Python 3.14, pytest, Django test runner, Node test runner, React 19, Vite 7.3.6, Docker 29.4.3, Docker Compose 5.1.4, PowerShell 7.

## Global Constraints

- Branch is `feat-pilot-safety-hotfix` and starting SHA is `65d2fdc8b50ea55f44b5a88178095f8824a5d8f1`.
- Remote `dev` must remain `61e0c56ba8a783423cb8a830e5d7088001e5593b`; if it moves, stop before RC designation and report the divergence.
- Run no `--run-live`, `--run-aws`, paid Agent, OpenAI, RunPod, external OAuth, production database, production object storage, or production Neo4j calls.
- Do not deploy, merge, create a PR, rotate credentials, purge logs, alter production data, or execute the 13 production E2Es.
- Do not stage, commit, or push; Git publication remains user-owned.
- A failing focused gate stops the expansion for that subsystem until its cause is classified.
- Do not change product behavior merely to make a test pass. Any required implementation fix gets its own RED/GREEN evidence and checklist entry.
- The only expected warning is the existing `LangChainPendingDeprecationWarning`; any new warning is a G6 finding.
- Ignored pilot Compose fixture files may be created only when absent, from `runtime.env.example`, and must be removed immediately after `docker compose config`.

---

### Task 1: Freeze and record the G6 baseline

**Files:**
- Create: `docs/tech-validation-reports/2026-07-31-g6-full-regression-evidence.md`
- Modify: `docs/tech-validation-reports/2026-07-31-pilot-hotfix-master-checklist.md`

**Interfaces:**
- Consumes: local branch HEAD, upstream SHA, remote `dev` SHA, tool versions.
- Produces: one baseline record used by every later G6 command.

- [x] **Step 1: Verify branch and worktree state**

```powershell
git status --short --branch
git rev-parse HEAD
git rev-parse origin/feat-pilot-safety-hotfix
git ls-remote origin refs/heads/dev
```

Expected: clean worktree; local and upstream feature SHA are identical; remote `dev` is `61e0c56b...`.

- [x] **Step 2: Record runtime versions and start time**

```powershell
Get-Date -Format o
python --version
node --version
npm --version
docker --version
docker compose version
```

Expected: every command exits 0. Record exact versions rather than inferring them from lockfiles.

- [x] **Step 3: Create the evidence report**

Write the baseline SHA, timestamp, commands, and constraints to `docs/tech-validation-reports/2026-07-31-g6-full-regression-evidence.md`. Do not record environment-variable values or credentials.

---

### Task 2: Run safety, routing, authentication, and ownership gates

**Files:**
- Verify: `test/test_chat_input_privacy.py`
- Verify: `test/test_privacy_boundaries.py`
- Verify: `test/test_pii_masking.py`
- Verify: `test/test_input_understanding_service.py`
- Verify: `test/test_public_consultation_routing_service.py`
- Verify: `test/test_service_scope_policy_service.py`
- Verify: `test/test_chat_orchestration_service.py`
- Verify: `test/test_auth_error_contract.py`
- Verify: `test/test_auth_session_service.py`
- Verify: `test/test_chat_session_contract.py`
- Verify: `test/test_frontend_auth_session_contract.py`
- Verify: `test/test_guest_credential_service.py`
- Verify: `test/test_history_api_contract.py`
- Verify: `test/test_mypage_api_contract.py`

**Interfaces:**
- Consumes: G1/G2 safety and ownership contracts.
- Produces: zero-failure evidence for input, PII, routing, session, guest, history, and resource-boundary behavior.

- [x] **Step 1: Run safety and routing pytest modules**

```powershell
python -m pytest test/test_chat_input_privacy.py test/test_privacy_boundaries.py test/test_pii_masking.py test/test_input_understanding_service.py test/test_public_consultation_routing_service.py test/test_service_scope_policy_service.py test/test_chat_orchestration_service.py -q
```

Expected: exit 0, zero failures, no raw PII or credential values in output.

- [x] **Step 2: Run authentication and ownership pytest modules**

```powershell
python -m pytest test/test_auth_error_contract.py test/test_auth_session_service.py test/test_chat_session_contract.py test/test_frontend_auth_session_contract.py test/test_guest_credential_service.py test/test_history_api_contract.py test/test_mypage_api_contract.py -q
```

Expected: exit 0 and zero failures.

---

### Task 3: Run fine-notice, attachment, Supervisor, polling, and evidence gates

**Files:**
- Verify: `test/test_fine_notice_intake_service.py`
- Verify: `test/test_attachment_workflow_service.py`
- Verify: `test/test_fact_conflict_service.py`
- Verify: `test/test_supervisor_control_service.py`
- Verify: `test/test_supervisor_execution_input_service.py`
- Verify: `test/test_supervisor_plan_execution.py`
- Verify: `test/test_analysis_progress_service.py`
- Verify: `test/test_analysis_job_query_service.py`
- Verify: `test/test_e2e_evidence_bundle_service.py`

**Interfaces:**
- Consumes: G4/G5 consultation, workflow, semantic polling, and evidence contracts.
- Produces: zero-failure evidence across HFX-014 through HFX-018.

- [x] **Step 1: Run consultation and Supervisor modules**

```powershell
python -m pytest test/test_fine_notice_intake_service.py test/test_attachment_intake_policy.py test/test_attachment_workflow_service.py test/test_synthetic_fine_notice_fixture.py test/test_fact_conflict_service.py test/test_supervisor_control_service.py test/test_supervisor_execution_input_service.py test/test_supervisor_plan_execution.py -q
```

Expected: exit 0 and zero failures.

- [x] **Step 2: Run polling and evidence modules**

```powershell
python -m pytest test/test_analysis_progress_service.py test/test_analysis_job_query_service.py test/test_e2e_evidence_bundle_service.py -q
```

Expected: exit 0; semantic worker/task separation and evidence allowlists remain enforced.

---

### Task 4: Run operations, deployment, Agent, RAG, and graph gates

**Files:**
- Verify: `test/test_aws_pilot_infrastructure.py`
- Verify: `test/test_deployment_readiness_artifacts.py`
- Verify: `test/test_production_hardening_contract.py`
- Verify: `test/test_agent_execution_service.py`
- Verify: `test/test_agent_node_service.py`
- Verify: `test/test_legal_rag_service.py`
- Verify: `test/test_law_graph_seed.py`
- Verify: `test/test_pgvector_rag_readiness.py`

**Interfaces:**
- Consumes: G1/G3 deployment, observability, Agent, RAG, Neo4j, and fallback contracts.
- Produces: local static/contract evidence only; it does not assert live provider or production readiness.

- [x] **Step 1: Run operational and deployment contract tests**

```powershell
python -m pytest test/test_aws_pilot_infrastructure.py test/test_deployment_readiness_artifacts.py test/test_production_hardening_contract.py test/test_codebuild_pilot_contract.py test/test_runtime_image_dependency_boundary.py test/test_runtime_worker_and_registry_contract.py test/test_legal_operational_evidence.py test/test_legal_run_summary_validation.py -q
```

Expected: exit 0 and zero failures.

- [x] **Step 2: Run Agent, RAG, and graph contract tests**

```powershell
python -m pytest test/test_agent_execution_service.py test/test_agent_node_service.py test/test_supervisor_llm_service.py test/test_legal_rag_service.py test/test_legal_rag_evaluation.py test/test_law_ground_contract.py test/test_law_graph_seed.py test/test_legal_graph_seed_commands.py test/test_pgvector_rag_readiness.py test/unit/test_legal_law_graph_relations.py test/unit/test_legal_reference_drift_check.py -q
```

Expected: exit 0; live/provider cases remain skipped unless explicitly local and synthetic.

---

### Task 5: Run complete frontend and Django integration gates

**Files:**
- Verify: every `app/web/*.test.js`
- Verify: every discoverable `backend/chatbot/test*.py`

**Interfaces:**
- Consumes: all frontend UI contracts and Django integration/E2E contracts.
- Produces: complete local Node and Django counts for the RC SHA.

- [x] **Step 1: Run all frontend Node tests**

Run from `app/web`:

```powershell
node --test *.test.js
```

Expected: exit 0 and zero failures.

- [x] **Step 2: Run complete Django chatbot discovery**

```powershell
python backend/manage.py test chatbot --verbosity 1
```

Expected: exit 0. External/live tests must skip or use mocked adapters; no production resource may be contacted.

---

### Task 6: Run full Python regression and production build

**Files:**
- Verify: all pytest-discovered files under repository configuration.
- Verify: `app/web` Vite production bundle.

**Interfaces:**
- Consumes: every prior focused gate.
- Produces: final Python count and production frontend compilation evidence.

- [x] **Step 1: Run the full pytest suite**

```powershell
python -m pytest -q
```

Expected baseline: at least `1449 passed`, `37 skipped`, `4 subtests passed`, zero failures, and only the existing LangChain pending-deprecation warning.

- [x] **Step 2: Build the production frontend**

Run from `app/web`:

```powershell
npm run build
```

Expected: Vite exits 0 and generated `dist` remains ignored/untracked.

---

### Task 7: Render local and pilot Compose configurations

**Files:**
- Verify: `docker-compose.yml`
- Verify: `deploy/aws-pilot/docker-compose.pilot.yml`
- Temporarily create and remove: `deploy/aws-pilot/.runtime.env`
- Temporarily create and remove: `deploy/aws-pilot/.edge.env`

**Interfaces:**
- Consumes: checked-in Compose and sanitized example environment configuration.
- Produces: parser/render evidence without starting, pulling, building, or contacting services.

- [x] **Step 1: Validate local Compose**

```powershell
docker compose -f docker-compose.yml config --quiet
```

Expected: exit 0. Do not run `up`, `build`, `pull`, or `run`.

- [x] **Step 2: Prepare ignored synthetic pilot env fixtures**

First assert both target files are absent. Then copy `deploy/aws-pilot/runtime.env.example` to both ignored filenames. Never overwrite an existing operational file.

```powershell
Test-Path deploy/aws-pilot/.runtime.env
Test-Path deploy/aws-pilot/.edge.env
```

Expected before creation: both `False`.

- [x] **Step 3: Validate pilot Compose and remove fixtures**

Run from `deploy/aws-pilot` with `runtime.env.example` as interpolation input:

```powershell
docker compose --env-file runtime.env.example -f docker-compose.pilot.yml config --quiet
```

Expected: exit 0. Remove only the two fixtures created in Step 2, then confirm both are absent and `git status --short` contains no generated files.

---

### Task 8: Review the complete branch and designate the RC SHA

**Files:**
- Modify: `docs/tech-validation-reports/2026-07-31-g6-full-regression-evidence.md`
- Modify: `docs/tech-validation-reports/2026-07-31-pilot-hotfix-master-checklist.md`
- Review: full branch diff `origin/dev...HEAD`

**Interfaces:**
- Consumes: exact command outputs and all branch changes since `origin/dev`.
- Produces: G6 `GREEN`, `RED`, or `BLOCKED`, residual-risk record, and release-candidate SHA.

- [x] **Step 1: Review scope and diff integrity**

```powershell
git diff --check origin/dev...HEAD
git diff --stat origin/dev...HEAD
git diff --name-status origin/dev...HEAD
git status --short --branch
```

Confirm no credentials, `.env` files, generated `dist`, production evidence, unapproved migration, or unrelated user change is included.

- [x] **Step 2: Reconfirm the remote base and branch SHA**

```powershell
git ls-remote origin refs/heads/dev
git rev-parse HEAD
git rev-parse origin/feat-pilot-safety-hotfix
Get-Date -Format o
```

If remote `dev` moved, record G6 as `BLOCKED` pending an explicit integration decision. Otherwise use the verified HEAD as the RC SHA.

- [x] **Step 3: Update G6 evidence and master checklist**

Record every command, exit status, pass/skip count, warning classification, build result, Compose result, review result, start/end time, and residual live-production work. Mark only G6 local gates complete; keep G7 approval, G8 deployment, and G9 13 E2Es open.

- [x] **Step 4: Present the user-owned Git handoff**

Recommend one documentation-only commit if no code fix was required:

```text
docs: record full hotfix regression evidence
```

Do not stage, commit, push, merge, deploy, or create a PR.

## G6 Exit Criteria

- Every focused suite has zero failures.
- Complete Node, Django, and pytest suites have zero failures.
- Vite production build succeeds.
- Local and pilot `docker compose config --quiet` succeed without starting services.
- No new unclassified warning remains.
- Full `origin/dev...HEAD` diff is reviewed with no actionable finding.
- Remote `dev` remains the approved base or divergence is explicitly resolved.
- The exact verified branch HEAD is recorded as the release-candidate SHA.
- G7/G8/G9 remain pending and no production mutation has occurred.
