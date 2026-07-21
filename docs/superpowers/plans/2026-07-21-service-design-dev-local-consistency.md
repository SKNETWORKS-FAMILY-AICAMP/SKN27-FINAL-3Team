# Service Design and Local Development Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the service design document and local launcher with the merged DOCX-only and signed guest-credential policy, then lock that policy with minimal static regression tests.

**Architecture:** Runtime API, authentication middleware, React UI, document rendering, Docker, and the GitHub Actions workflow are unchanged. A single Python static-contract test reads the design document, launcher, and existing production gate; the document and PowerShell launcher receive only the smallest changes required to match current behavior.

**Tech Stack:** Markdown, PowerShell, Python `pytest`, Vite build verification.

## Global Constraints

- Restrict changes to `docs/service-design-spec-2026-07-21.md`, `dev-local.ps1`, one Python static regression test, and the already pending #258 checklist line.
- Do not change download APIs/UI, DOCX rendering, Django authentication, React, Docker/deployment/DB schema, or GitHub Actions workflow contents.
- Describe general reports, traffic-accident documents, and fine-notice objection forms as DOCX-only downloads.
- `X-Guest-Id` is optional identification, never standalone authority proof; protected guest requests require a signed `X-Guest-Credential` header.
- Do not put guest credentials in request body, query string, or `auth_context`; App JWT and guest credentials are non-substitutable.
- Use SQLite only when `DJANGO_DATABASE_ENGINE` is blank; preserve an explicit engine such as `postgres` for every child process.
- Do not alter the already merged `ReportActionAlert` repair or the separate UI mock-data follow-ups.

---

### Task 1: Add a failing current-policy static contract

**Files:**
- Create: `test/test_service_design_dev_local_contract.py`
- Read: `docs/service-design-spec-2026-07-21.md`
- Read: `dev-local.ps1`
- Read: `.github/workflows/production-gate.yml`

**Interfaces:**
- Consumes UTF-8 text files at the three paths above.
- Produces static `pytest` coverage that fails until the design document and launcher follow the current policy.

- [x] **Step 1: Write the failing test**

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_service_design_documents_docx_only_downloads_and_guest_header_boundary() -> None:
    spec = read_text("docs/service-design-spec-2026-07-21.md")

    for phrase in ("일반 분석 리포트", "교통사고 문서", "과태료 이의신청서", "DOCX 전용"):
        assert phrase in spec
    for obsolete_phrase in ("화면 PDF 저장", "로그인 후 이의신청서 PDF"):
        assert obsolete_phrase not in spec
    for phrase in (
        "X-Guest-Credential",
        "X-Guest-Id",
        "단독으로는 권한 증명이 아니다",
        "request body",
        "query string",
        "auth_context",
        "App JWT",
    ):
        assert phrase in spec


def test_dev_local_preserves_explicit_database_engine_and_gate_builds_frontend() -> None:
    launcher = read_text("dev-local.ps1")
    workflow = read_text(".github/workflows/production-gate.yml")

    assert "if ([string]::IsNullOrWhiteSpace($env:DJANGO_DATABASE_ENGINE))" in launcher
    assert '$env:DJANGO_DATABASE_ENGINE = "sqlite"' in launcher
    assert "`$env:DJANGO_DATABASE_ENGINE='sqlite';" not in launcher
    assert "working-directory: app/web" in workflow
    assert "npm ci" in workflow
    assert "npm run build" in workflow
```

- [x] **Step 2: Run the test and verify the intended RED result**

Run: `python -m pytest test/test_service_design_dev_local_contract.py -q --timeout=30`

Expected: failure caused by the old PDF/`X-Guest-Id`-only text and the unconditional child-process SQLite assignment.

- [x] **Step 3: Commit the red test**

```powershell
git add test/test_service_design_dev_local_contract.py
git commit -m "test: cover service design and local launcher policy"
```

### Task 2: Apply the minimum document and launcher correction

**Files:**
- Modify: `docs/service-design-spec-2026-07-21.md:62-70`
- Modify: `docs/service-design-spec-2026-07-21.md:86-101`
- Modify: `dev-local.ps1:10-18`
- Test: `test/test_service_design_dev_local_contract.py`

**Interfaces:**
- Consumes Task 1's assertions and the #260 merged header-based credential policy.
- Produces documentation that describes the existing behavior and a launcher that inherits explicit DB engine settings.

- [x] **Step 1: Replace the obsolete report-action bullet**

Use this text, without adding an API/UI action:

```markdown
- 하단에는 리포트 액션(로그인 후 저장, 일반 분석 리포트 DOCX 다운로드, 교통사고 문서 DOCX 다운로드, 과태료 이의신청서 DOCX 다운로드) 패널이 붙는다. PDF 다운로드는 제공하지 않으며, 공식 문서는 기존 확인 게이트를 통과한 뒤 내려받는다.
```

- [x] **Step 2: Replace the guest-state explanation**

Use this policy wording under the guest state and authentication sections:

```markdown
2. **guest(게스트 세션)** — `X-Guest-Id`는 선택적 식별 보조값이며 단독으로는 권한 증명이 아니다. 보호된 guest 경로는 서명된 `X-Guest-Credential`을 요청 header로 전달하고 서버 검증을 통과해야 한다. credential은 request body, query string, `auth_context`에 넣지 않는다.

App JWT(`Authorization: Bearer ...`)는 로그인 사용자의 권한을, guest credential은 비회원 guest 세션의 권한을 증명한다. 두 credential은 서로 대체할 수 없다.
```

- [x] **Step 3: Set SQLite in the parent only when no engine exists**

Insert immediately after `$root = $PSScriptRoot`:

```powershell
if ([string]::IsNullOrWhiteSpace($env:DJANGO_DATABASE_ENGINE)) {
    $env:DJANGO_DATABASE_ENGINE = "sqlite"
}
```

Remove only `` `$env:DJANGO_DATABASE_ENGINE='sqlite'; `` from the `Start-Process` command string. Retain `DJANGO_ENV_FILE`, all four process commands, and the remaining child-process behavior.

- [x] **Step 4: Run the focused test and verify GREEN**

Run: `python -m pytest test/test_service_design_dev_local_contract.py -q --timeout=30`

Expected: `2 passed`.

- [x] **Step 5: Commit the aligned document, script, and test**

```powershell
git add docs/service-design-spec-2026-07-21.md dev-local.ps1 test/test_service_design_dev_local_contract.py
git commit -m "fix: align service design and local database defaults"
```

### Task 3: Update merged evidence and run the full verification set

**Files:**
- Modify: `docs/ops/project-readiness-master-checklist.md:76` only if #258 is still `[~]`
- Verify: `app/web/package.json`
- Verify: `test/test_service_design_dev_local_contract.py`
- Verify: `test/test_consultation_v2_contract.py`
- Verify: `test/test_frontend_auth_session_contract.py`
- Verify: `test/test_api_route_specs.py`

**Interfaces:**
- Consumes merged PR #260 as #258's implementation evidence, Task 2's policy alignment, and existing frontend/auth contracts.
- Produces an accurate checklist and evidence that neither frontend nor backend runtime behavior changed.

- [x] **Step 1: Update only the pending #258 line**

```markdown
- [x] 유출·복제된 `guest_id`만으로 비회원 세션의 로그인 결합이나 접근이 가능하지 않도록 서버 검증 가능한 guest credential 경계 도입 — #258 / PR #260
```

- [x] **Step 2: Run the real frontend production build**

Run in `app/web`: `npm run build`

Expected: Vite completes with `✓ built in`.

- [x] **Step 3: Run focused document/frontend/auth regressions**

```powershell
python -m pytest test/test_service_design_dev_local_contract.py test/test_consultation_v2_contract.py test/test_frontend_auth_session_contract.py test/test_api_route_specs.py -q --timeout=30
```

Expected: all selected tests pass.

- [x] **Step 4: Run the complete Python regression suite**

Run: `python -m pytest -q --timeout=30`

Expected: all runnable tests pass; existing skips and non-failing dependency warnings may remain.

- [x] **Step 5: Review, commit the checklist, and push**

```powershell
git diff --check origin/dev...HEAD
git add docs/ops/project-readiness-master-checklist.md
git commit -m "docs: mark guest credential boundary complete"
git push origin fix/261-service-design-dev-local-consistency
```

## Self-Review

- Task 2 covers DOCX-only wording, signed guest header policy, non-substitutable credential policy, and conditional SQLite default.
- Task 3 covers the real frontend build, focused contracts, complete Python suite, and the #258 checklist evidence.
- No task changes React, runtime API, authentication middleware, renderer, Docker, database schema, or workflow content; the existing workflow is only asserted.
- Task 1 establishes RED before Task 2 changes any production documentation/script content; no placeholders remain.
