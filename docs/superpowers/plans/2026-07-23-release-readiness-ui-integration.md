# Release Readiness UI Integration Implementation Plan

> **Goal:** Preserve the approved PR #296 visual direction, integrate it with
> PR #293's merged `dev`, fix the known runtime and pgvector readiness defects,
> and leave a verified release candidate with only credential/account/traffic
> actions for a human operator.

## Baseline

- Worktree: `C:\tmp\SKN27-release-readiness-integration`
- Branch: `feat-release-readiness-integration`
- Dev baseline: `d326ae8`
- Design commit: `6acf96b`
- UI source: `origin/Issue/UI-v3-followup` (`e0420de`)

## Task 1: Import PR #296 without rewriting its branch

**Files:** the six files changed by PR #296.

1. Merge `origin/Issue/UI-v3-followup` into the integration branch with
   `--no-commit`.
2. Resolve conflicts in favor of the approved UI while retaining newer
   attachment and pgvector contracts from `dev`.
3. Confirm the merge contains only the expected PR #296 files before fixes.

**Verification**

```powershell
git status --short
git diff --name-status --cached
git diff --check
```

## Task 2: Reproduce and fix the chat attachment runtime regression

**Files**

- Modify: `app/web/FrontendAppShell.jsx`
- Modify/Add: `test/test_service_scope_frontend_contract.py` or a focused
  frontend source-contract test beside it

1. Add failing assertions showing that the attachment menu options are defined
   and child UI uses the parent `onAttachmentFile` boundary.
2. Run the focused test and retain the expected failure.
3. Define the menu configuration with accept MIME values and canonical purpose.
4. Pass the selected option through the existing parent file handler.
5. Remove direct child access to `setSelectedUploadFile`.
6. Verify PDF/image/video purposes, unsupported MIME rejection, remove and
   reselect behavior.

**Verification**

```powershell
.\.venv\Scripts\python.exe -m pytest test\test_service_scope_frontend_contract.py -q
npm --prefix app\web run build
```

## Task 3: Harden approved home, mypage, report, and streaming interactions

**Files**

- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `app/web/styles.css`
- Modify/Add: focused frontend contract tests under `test/`

1. Add tests for keyboard carousel handling and current-state semantics.
2. Add pure deadline calculation cases for missing, invalid, past, and
   user-sourced dates.
3. Correct pagination selection when filtering or moving pages.
4. Verify report-list collapse labels and server-driven document confirmation.
5. Ensure streaming timers stop updating an unmounted component and empty
   answers settle immediately.
6. Check reduced-motion, visible focus, responsive breakpoints, and text
   contrast rules in the generated UI.

**Verification**

```powershell
.\.venv\Scripts\python.exe -m pytest test\test_*frontend* -q
npm --prefix app\web run build
```

## Task 4: Fix PR #293 review-case provider fail-closed readiness

**Files**

- Modify:
  `etl/fault_cases/src/review_case/search/pgvector/create_index.py`
- Modify:
  `backend/chatbot/management/commands/verify_pgvector_rag_readiness.py`
- Modify/Add: the focused pgvector readiness tests already covering #291

1. Add a failing test requiring `embedding_provider` in the review-case count
   query and HNSW partial-index predicate.
2. Add provider to the SQL predicate and bound parameters.
3. Verify readiness reports actual matched metadata and cannot label rows from
   another provider as the configured OpenAI space.
4. Confirm migration and rerun-safe tests still pass.

**Verification**

```powershell
.\.venv\Scripts\python.exe -m pytest test -q -k "review_case and (pgvector or readiness or index)"
```

## Task 5: Reconcile checklist items with executable evidence

**Files**

- Modify: `docs/ops/project-readiness-master-checklist.md`
- Modify as needed: relevant runbooks, deployment scripts, and focused tests
- Add: a dated verification report under `docs/superpowers/reports/`

1. Re-evaluate every unchecked item against current code and merged PRs.
2. Close only items backed by a command, test, artifact, or explicit contract.
3. Implement release-blocking code/automation gaps that are bounded and can be
   verified without production credentials.
4. Keep quality-dataset, paid embedding, real AWS account, and final traffic
   operations open with exact owner inputs and commands.
5. Link evidence and remaining human gates from the checklist.

## Task 6: Run release-candidate verification

Run from the integration worktree, recording exact outcomes.

```powershell
git diff --check origin/dev...HEAD
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe backend\manage.py check
npm --prefix app\web run build
```

Also run repository-provided OpenAPI, Terraform, Docker, secret/PII, migration,
seed, smoke, timeout/retry, and rollback checks discovered in project scripts.
Do not claim unavailable external/live checks as passed.

## Task 7: Publish and merge

1. Review the complete diff against `origin/dev`.
2. Commit logically separated fixes and evidence.
3. Push `feat-release-readiness-integration`.
4. Create a `dev` PR with test evidence and remaining human gates.
5. Verify GitHub CI and review state.
6. Merge only when required checks pass and the expected head SHA is unchanged.
7. Re-fetch `dev` and verify the merge commit.

## Human-only handoff

- Actual AWS, Google, and OpenAI account/credential issuance and entry
- Billing and paid re-embedding approval
- Domain, DNS, and production OAuth ownership
- Production database migration/re-embedding execution approval
- Final production traffic cutover and post-deploy business sign-off
