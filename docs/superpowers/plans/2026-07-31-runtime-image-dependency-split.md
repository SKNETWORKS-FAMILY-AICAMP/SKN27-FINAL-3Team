# Runtime Image Dependency Split Implementation Plan

> **For implementers:** Execute this plan task-by-task. Keep the runtime-image change separate from RAG chunking and Vision deployment changes.

**Goal:** Shrink the Pilot backend image by removing unused local embedding dependencies from the default runtime dependency set, while preserving local embedding development and both Vision build paths.

**Architecture:** `requirements.txt` remains the only requirements file installed by the root Pilot `Dockerfile`. A new opt-in requirements file layers local `sentence-transformers` tooling on top for developer/ETL use. Production remains OpenAI-embedding based. RunPod Vision and the optional AWS GPU Vision image retain their existing independent requirements and Dockerfiles.

**Tech stack:** Python 3.13, Django, OpenAI embeddings, Docker, AWS CodeBuild/ECR, pytest, npm.

## Confirmed design constraints

- The Pilot compose configuration explicitly uses OpenAI for general and legal-RAG query embeddings. The backend must not require `sentence-transformers` in that configuration.
- `app/services/legal_rag_service.py` may continue to lazy-load the local provider when an operator explicitly selects it. `backend/chatbot/readiness.py` already fails clearly if that provider is selected without the optional package.
- The root `Dockerfile` must continue installing only `requirements.txt`; it must not copy or install the optional local-embedding file.
- `deploy/runpod-vision/Dockerfile` and `deploy/aws-vision/Dockerfile` are separate Vision paths. Neither, nor `requirements-vision-runpod.txt`, may be changed by this image-size PR.
- RAG chunk design PR #328, RAG seed/Neo4j ingestion, and GPU instance activation are out of scope. They require separate review and runtime verification.
- Existing old/legacy Docker containers on EC2 are deployment-drift cleanup, not a reason to broaden this source PR.

## Task 1: Establish and implement the dependency boundary

**Files:**

- Create: `test/test_runtime_image_dependency_boundary.py`
- Modify: `requirements.txt`
- Create: `requirements-local-embedding.txt`

- [ ] **Step 1: Write the failing boundary test.**

  Add tests that assert all of the following:

  - Default `requirements.txt` does not include `sentence-transformers`, `transformers`, `huggingface-hub`, or `safetensors`.
  - `requirements-local-embedding.txt` begins with `-r requirements.txt` and includes the four local embedding packages.
  - The root `Dockerfile` installs `requirements.txt` and does not reference `requirements-local-embedding.txt`.
  - `deploy/runpod-vision/Dockerfile` still uses `requirements-vision-runpod.txt`.
  - `deploy/aws-vision/Dockerfile` still has its PyTorch CUDA base and uses `requirements-vision-runpod.txt`.

- [ ] **Step 2: Run the test to verify it fails.**

  Run: `python -m pytest -q --timeout=30 test/test_runtime_image_dependency_boundary.py`

  Expected: failure because the default file still contains local-model dependencies and the opt-in file does not yet exist.

- [ ] **Step 3: Implement the smallest safe change.**

  Remove only these four entries from `requirements.txt`:

  - `sentence-transformers==5.5.1`
  - `transformers==4.57.6`
  - `huggingface-hub>=0.34.0`
  - `safetensors>=0.4.5`

  Create `requirements-local-embedding.txt` containing:

  ```text
  -r requirements.txt
  sentence-transformers==5.5.1
  transformers==4.57.6
  huggingface-hub>=0.34.0
  safetensors>=0.4.5
  ```

  Do not modify the root Dockerfile, runtime environment defaults, RAG service logic, or either Vision Dockerfile.

- [ ] **Step 4: Run the focused boundary test.**

  Run: `python -m pytest -q --timeout=30 test/test_runtime_image_dependency_boundary.py`

  Expected: all dependency-boundary tests pass.

## Task 2: Document the opt-in local embedding workflow

**Files:**

- Modify: `README.md`
- Modify: `test/test_runtime_image_dependency_boundary.py`

- [ ] **Step 1: Add a failing documentation assertion.**

  Extend the boundary test to require `README.md` to mention `requirements-local-embedding.txt` and identify it as an optional/local-development installation.

- [ ] **Step 2: Run the documentation test to verify it fails.**

  Run: `python -m pytest -q --timeout=30 test/test_runtime_image_dependency_boundary.py`

  Expected: failure because the README has no opt-in instruction yet.

- [ ] **Step 3: Add the narrow README instruction.**

  Near the existing Python installation section, document that developers who intentionally run local `sentence-transformers` embedding experiments or local ETL can additionally run `python -m pip install -r requirements-local-embedding.txt`. State that Pilot production uses OpenAI embeddings and does not install this optional set.

- [ ] **Step 4: Re-run the boundary test.**

  Run: `python -m pytest -q --timeout=30 test/test_runtime_image_dependency_boundary.py`

  Expected: all tests pass.

## Task 3: Run source-level regression verification

**Files:**

- Verify only; no expected source edits.

- [ ] **Step 1: Run Python regression tests.**

  Run:

  ```powershell
  python -m pytest -q --timeout=30 `
    test/test_runtime_image_dependency_boundary.py `
    test/test_legal_rag_service.py `
    test/test_aws_pilot_infrastructure.py `
    test/test_production_hardening_contract.py
  ```

  Expected: all pass. This validates the OpenAI/local provider boundary, Pilot infrastructure contract, and preservation of both Vision build definitions.

- [ ] **Step 2: Run canonical backend E2E tests.**

  Run:

  ```powershell
  python backend/manage.py test `
    chatbot.test_canonical_user_flow_e2e `
    chatbot.test_guest_login_session_ownership_e2e `
    chatbot.test_resource_ownership_e2e `
    chatbot.test_supervisor_conversation_runtime_smoke `
    --verbosity 1
  ```

  Expected: guest session, conversation ownership, report confirmation, and artifact flow remain intact. If a named module differs, locate the existing equivalent test before substituting it; do not silently skip the coverage category.

- [ ] **Step 3: Run frontend production build.**

  Run in `frontend`: `npm run build`

  Expected: successful static build. This source change should not alter UI output, but it detects repository-wide build drift before handoff.

- [ ] **Step 4: Inspect the diff and hand off for user-owned commit/PR.**

  Run: `git diff --check` and `git diff -- requirements.txt requirements-local-embedding.txt README.md test/test_runtime_image_dependency_boundary.py`

  Expected: no whitespace errors and no changes to RAG runtime defaults or Vision files. Suggested commit message: `fix: separate local embedding dependencies from runtime`.

## Task 4: Verify the deployed image and key live flows after merge

**Files:**

- Verify only; deployment remains through the existing CodePipeline approval path.

- [ ] **Step 1: Confirm the CodeBuild source revision and deployed image tags.**

  Confirm the release uses the merge commit from this PR and record the backend image size before and after. The success criterion is a materially smaller backend image, not a fixed byte value.

- [ ] **Step 2: Confirm service health.**

  Check the public liveness and readiness endpoints. Confirm backend, frontend, PostgreSQL/RDS connectivity, and Redis readiness are healthy before browser testing.

- [ ] **Step 3: Execute live guest journeys and retain evidence.**

  Exercise:

  - a general traffic/administrative question;
  - a fine/penalty question with a response grounded in the loaded RAG seed;
  - a fault-ratio question; because new chunk design #328 is intentionally out of scope, a clear controlled limitation is acceptable, while a blank response or endless clarification loop is not;
  - conversation-to-report confirmation and download of one generated DOCX artifact.

  Capture request status, response/result shape, timestamps, and server logs for every failure. Do not use live Google OAuth or start GPU Vision capacity for this verification.

- [ ] **Step 4: Report separate follow-ups, not hidden scope expansion.**

  If E2E exposes a conversation UX bug, RAG seed gap, OAuth problem, or Vision capacity need, create a distinct hotfix item with its own branch. Do not patch it inside this dependency-boundary PR.

## Acceptance criteria

- The Pilot runtime image no longer installs local transformer/PyTorch dependency chains implicitly.
- Developer local embedding remains reproducible through an explicit optional requirements file.
- Production OpenAI RAG configuration, local-provider readiness guard, RunPod Vision, and AWS Vision build paths remain compatible.
- Targeted source tests, canonical backend E2E tests, and frontend production build are green before PR handoff.
- After deployment, backend image-size improvement and live guest/report flow evidence are recorded separately from RAG chunking and GPU activation work.
