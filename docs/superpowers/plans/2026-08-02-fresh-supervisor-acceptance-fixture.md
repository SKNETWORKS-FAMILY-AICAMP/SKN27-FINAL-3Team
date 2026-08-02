# Fresh Supervisor Acceptance Fixture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce, review, and immutably publish one deterministic, PII-free Korean prior-notice PDF whose unexpired deadline lets the existing strict Supervisor report smoke test the real report path without changing application or release-gate behavior.

**Architecture:** Add a standalone local fixture builder under `scripts/` and keep it independent from the user-facing report renderers and runtime services. The builder owns a fixed semantic contract, emits an invariant one-page PDF plus PNG preview, and is covered by structural, text, privacy, and byte-determinism tests. Publication and the subsequent paid cutover remain explicit operator gates; neither is performed by the builder or tests.

**Tech Stack:** Python 3.14, ReportLab, `pypdf`, `pdfplumber`, PyMuPDF (`fitz`), pytest, PowerShell, AWS CLI/S3, existing `Deploy-Pilot.ps1` and SSM deployment path.

## Global Constraints

- Preserve the strict `--require-real-agent-results`, `--require-persisted-handoff`, and `--require-report` gates.
- Do not change appeal logic, Supervisor planning, report generation, OCR confirmation fields, or deployment transaction behavior.
- Do not call AWS, Google, OpenAI, an embedding provider, or any other paid/external service during Tasks 1-3.
- Do not use a real notice, user-provided file, official seal, signature, barcode, payment account, or real PII.
- Keep the generated PDF/PNG out of Git. Commit only source, tests, ignore rules, and design/plan/evidence documents.
- Do not overwrite any object at `canonical/acceptance/`; a pre-existing destination key is a hard stop.
- Do not acquire a Google one-time code until local review, S3 metadata, and remote SHA-256 all pass.
- Do not run an additional paid Supervisor smoke without a separate, explicit operator approval.
- Use the SSM-backed `Deploy-Pilot.ps1` path as the only cutover path; do not also approve the CodePipeline App Release action.
- If cutover fails, do not retry. Retrieve redacted stdout/stderr and snapshot transaction state first.
- A successful cutover is followed by the existing 10-minute acceptance window and all 13 required E2E scenarios; those validations are not replaced by this fixture work.

---

### Task 1: Specify the deterministic PDF contract in failing tests

**Files:**
- Create: `test/test_supervisor_acceptance_fixture_pdf.py`
- Create: `scripts/build_supervisor_acceptance_fixture.py`
- Modify: `.gitignore`
- Reference: `docs/superpowers/specs/2026-08-02-fresh-supervisor-acceptance-fixture-design.md`
- Reference: `test/test_synthetic_fine_notice_fixture.py`

**Interfaces:**
- Produces: `FixtureField(label: str, value: str)` and immutable module constants for the exact approved safety markings, semantic fields, output filename, and A4 page contract.
- Produces: `build_fixture_pdf() -> bytes`, `render_preview(pdf_bytes: bytes, output_path: Path) -> None`, and a CLI `main(argv: Sequence[str] | None = None) -> int`.
- The builder accepts only an output path and preview path; semantic case values are source-controlled constants and cannot be overridden from environment variables or CLI input.

- [ ] **Step 1: Add exact local artifact ignore rules**

Append only these two paths to `.gitignore`:

```gitignore
output/pdf/pilot-fine-notice-prior-notice-valid-through-20260831-v1.pdf
output/pdf/pilot-fine-notice-prior-notice-valid-through-20260831-v1.png
```

Verify:

```powershell
git check-ignore -v `
  output/pdf/pilot-fine-notice-prior-notice-valid-through-20260831-v1.pdf `
  output/pdf/pilot-fine-notice-prior-notice-valid-through-20260831-v1.png
```

Expected: both paths resolve to the new exact ignore rules; no broad `output/pdf/` rule is added.

- [ ] **Step 2: Write the failing fixed-content contract test**

Create `test/test_supervisor_acceptance_fixture_pdf.py`. Import the builder and assert the exact approved values:

```python
assert SAFETY_MARKINGS == (
    "테스트 전용 문서",
    "실제 효력 없음",
    "개인정보 없는 운영 검증용 fixture",
)
assert dict((field.label, field.value) for field in FIXTURE_FIELDS) == {
    "문서명": "과태료 부과 사전통지서",
    "처분 유형": "과태료",
    "통지 단계": "사전통지",
    "발급 기관": "테스트구청 교통행정과",
    "사건 번호": "TEST-20260802-001",
    "발급일": "2026-08-02",
    "의견 제출 기한": "2026-08-31",
    "위반 일시": "2026-07-31 10:30",
    "위반 장소": "테스트 도로 구간",
    "위반 내용": "주정차 위반 테스트 데이터",
    "적용 법령": "도로교통법 제32조",
    "과태료 금액": "120,000원",
    "수신인": "테스트 사용자",
    "차량 식별값": "TEST-0000",
}
```

Also assert `OPINION_DEADLINE > date(2026, 8, 2)` and that the default PDF/PNG names exactly match the approved immutable filename.

- [ ] **Step 3: Write failing deterministic and structural tests**

In two temporary directories, call `build_fixture_pdf()` twice and require identical bytes and SHA-256. Reopen the bytes with `pypdf.PdfReader` and assert:

```python
assert len(reader.pages) == 1
assert "/AcroForm" not in reader.trailer["/Root"]
assert "/Names" not in reader.trailer["/Root"]
assert "/OpenAction" not in reader.trailer["/Root"]
assert "/AA" not in reader.trailer["/Root"]
assert "/Annots" not in reader.pages[0]
assert reader.metadata.author == "SKN27 Traffic Pilot"
assert "Playdata" not in serialized_metadata
assert "C:\\" not in serialized_metadata
```

Require A4 dimensions within one point of `595.28 x 841.89`, non-empty bytes, and no `/JavaScript`, `/EmbeddedFile`, `/Launch`, or `file://` token in the raw PDF.

- [ ] **Step 4: Write failing extracted-text and PII safety tests**

Use `pdfplumber.open(BytesIO(pdf_bytes))` and require every safety marking, field label, and field value to appear in the extracted first-page text. Search extracted text and metadata for these forbidden patterns:

```python
FORBIDDEN_PATTERNS = (
    r"(?<!\d)01[016789][-\s]?\d{3,4}[-\s]?\d{4}(?!\d)",
    r"(?<!\d)\d{6}[-\s]?[1-4]\d{6}(?!\d)",
    r"\b\d{2}[-\s]?\d{6}[-\s]?\d{2}\b",
    r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
    r"(?:[A-Za-z]:\\|/Users/|/home/)",
    r"s3://",
    r"[?&](?:X-Amz-|signature=|token=)",
)
```

Explicitly assert the text does not contain `금천구청`, any 2025 date, an account-number label, `직인`, `서명란`, or a `서명:` field. Do not reject the required label `문서명` merely because it contains the same two-character substring.

- [ ] **Step 5: Write the failing PNG preview test**

Call `render_preview()` into a temporary `.png`, open it with PyMuPDF/Pixmap metadata or PIL only if already available, and require a single non-empty page image with width at least 1,100 pixels and height greater than width. Do not use OCR or an external renderer in this automated test.

- [ ] **Step 6: Run the focused test and verify RED**

```powershell
python -m pytest test/test_supervisor_acceptance_fixture_pdf.py -q
```

Expected: collection or assertions fail because `scripts/build_supervisor_acceptance_fixture.py` does not yet expose the required contract and renderer. The failure must not be caused by AWS credentials, network access, or a provider call.

---

### Task 2: Implement the isolated one-page Korean fixture builder

**Files:**
- Modify: `scripts/build_supervisor_acceptance_fixture.py`
- Verify: `test/test_supervisor_acceptance_fixture_pdf.py`
- Verify: `backend/chatbot/pdf_report_renderer.py` remains unchanged
- Verify: `backend/chatbot/pdf_template_renderer.py` remains unchanged

**Interfaces:**
- `build_fixture_pdf()` returns invariant PDF bytes without reading environment variables or the filesystem.
- `render_preview(pdf_bytes, output_path)` rasterizes page 1 at 2x scale with an alpha-free RGB pixmap.
- CLI defaults:
  - `--output output/pdf/pilot-fine-notice-prior-notice-valid-through-20260831-v1.pdf`
  - `--preview output/pdf/pilot-fine-notice-prior-notice-valid-through-20260831-v1.png`
- CLI stdout contains only a JSON evidence envelope with relative output paths, SHA-256, byte size, page count, and preview dimensions; it contains no credentials or absolute user path.

- [ ] **Step 1: Add the fixed model and deterministic canvas setup**

Implement frozen `FixtureField` values and use ReportLab `Canvas(..., pagesize=A4, pageCompression=1, invariant=1)`. Register the Korean CID font without a user font file:

```python
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

KOREAN_FONT = "HYSMyeongJo-Medium"
if KOREAN_FONT not in pdfmetrics.getRegisteredFontNames():
    pdfmetrics.registerFont(UnicodeCIDFont(KOREAN_FONT))
```

Set fixed metadata only:

```python
canvas.setTitle("SKN27 테스트 전용 과태료 부과 사전통지서")
canvas.setAuthor("SKN27 Traffic Pilot")
canvas.setSubject("PII-free operator-reviewed acceptance fixture")
canvas.setCreator("SKN27 deterministic acceptance fixture builder v1")
canvas.setKeywords("synthetic, pii-free, acceptance-fixture")
```

- [ ] **Step 2: Draw a legible one-page A4 notice**

Use fixed coordinates, font sizes, and colors. Draw:

1. a full-width red safety banner containing `테스트 전용 문서 · 실제 효력 없음`;
2. the title and `개인정보 없는 운영 검증용 fixture` subtitle;
3. a two-column labeled field table for all 14 exact semantic values;
4. a boxed explanatory footer stating that the document has no legal or payment effect.

Do not draw a seal, signature line, barcode, QR code, payment instructions, bank details, realistic address, or official-government logo. Keep the smallest text at 9pt or larger and all content inside 18mm A4 margins.

- [ ] **Step 3: Implement local preview and evidence output**

Use `fitz.open(stream=pdf_bytes, filetype="pdf")`, require one page, render at `fitz.Matrix(2, 2)`, and write the PNG. The CLI creates parent directories, writes the exact PDF bytes once, renders the preview, then prints a JSON object with `contract_version=supervisor_acceptance_fixture.v1`, `status=generated`, the two exact relative artifact paths, the computed 64-character lowercase hexadecimal `sha256`, positive integer `bytes`, `pages=1`, and positive integer `preview_width`/`preview_height`. Use the actual rendered dimensions in output; tests should require minimums rather than pin platform-neutral exact pixels.

- [ ] **Step 4: Run focused tests and verify GREEN**

```powershell
python -m pytest test/test_supervisor_acceptance_fixture_pdf.py -q
```

Expected: all fixture tests pass, including identical SHA-256 across two builds, exact Korean text extraction, one-page structure, no active content, no annotations/forms/attachments, and no PII/path leakage.

- [ ] **Step 5: Run adjacent PDF and synthetic-fixture regressions**

```powershell
python -m pytest `
  test/test_synthetic_fine_notice_fixture.py `
  test/test_supervisor_acceptance_fixture_pdf.py -q
python backend/manage.py test chatbot.tests
```

Expected: both commands pass. `chatbot.tests` must run through Django's test runner because direct pytest collection does not configure Django settings. The existing report/template rendering behavior remains unchanged.

- [ ] **Step 6: Verify source isolation and style**

```powershell
python -m ruff check `
  scripts/build_supervisor_acceptance_fixture.py `
  test/test_supervisor_acceptance_fixture_pdf.py
git diff --check
git diff --name-only
```

Expected: no style or whitespace errors; changes are limited to `.gitignore`, the new builder, new test, and approved design/plan documents.

---

### Task 3: Generate the artifact and stop for visual operator approval

**Files:**
- Generate, do not commit: `output/pdf/pilot-fine-notice-prior-notice-valid-through-20260831-v1.pdf`
- Generate, do not commit: `output/pdf/pilot-fine-notice-prior-notice-valid-through-20260831-v1.png`
- Modify after evidence exists: `docs/tech-validation-reports/2026-08-02-production-cutover-execution-log.md`

**Interfaces:**
- Consumes: the tested local builder only.
- Produces: a local PDF, a local PNG preview, and an evidence record containing SHA-256, byte size, extracted contract, structural checks, and the operator decision.

- [ ] **Step 1: Generate the exact local PDF and PNG**

```powershell
python scripts/build_supervisor_acceptance_fixture.py `
  --output output/pdf/pilot-fine-notice-prior-notice-valid-through-20260831-v1.pdf `
  --preview output/pdf/pilot-fine-notice-prior-notice-valid-through-20260831-v1.png
```

Expected: JSON `status=generated`, `pages=1`, a 64-character lowercase SHA-256, positive byte size, and portrait preview dimensions.

- [ ] **Step 2: Re-run artifact-level validation against the generated file**

Run the focused test again and a read-only evidence command that opens the exact generated PDF with `pypdf` and `pdfplumber`, prints only page count, extracted-field booleans, active-content booleans, SHA-256, and byte size. Do not print local absolute paths, environment values, or document bytes.

Expected: all fields/safety markings true; page count 1; form/annotation/attachment/JavaScript/link flags false.

- [ ] **Step 3: Inspect the rendered PNG at original detail**

Open `output/pdf/pilot-fine-notice-prior-notice-valid-through-20260831-v1.png` with the local image viewer and inspect:

- every Korean glyph is readable;
- all three safety markings are prominent;
- no clipping or overlap occurs;
- field labels match their values;
- smallest text is legible;
- the layout is clearly synthetic and cannot be mistaken for a usable official notice.

If any check fails, return to Task 2, add a failing regression, fix the builder, regenerate, and repeat this task.

- [ ] **Step 4: Record evidence and request explicit artifact approval**

Append the exact SHA-256, byte size, page count, automated result, visual result, and proposed immutable S3 key to `docs/tech-validation-reports/2026-08-02-production-cutover-execution-log.md`. Present the preview and evidence to the operator. Stop here until the operator explicitly approves this exact hash for publication.

- [ ] **Step 5: Prepare the local implementation commit only after GREEN evidence**

```powershell
git status --short
git add `
  .gitignore `
  scripts/build_supervisor_acceptance_fixture.py `
  test/test_supervisor_acceptance_fixture_pdf.py `
  docs/superpowers/plans/2026-08-02-fresh-supervisor-acceptance-fixture.md `
  docs/tech-validation-reports/2026-08-02-production-cutover-execution-log.md
git diff --cached --check
git diff --cached --name-only
git commit -m "test: add fresh supervisor acceptance fixture"
```

Expected: generated PDF/PNG do not appear in `git status` or the staged file list. Do not push or publish the artifact as part of this step.

---

### Task 4: Publish the exact approved bytes under a new immutable S3 key

**Files:**
- Read: `output/pdf/pilot-fine-notice-prior-notice-valid-through-20260831-v1.pdf`
- Modify after verification: `docs/tech-validation-reports/2026-08-02-production-cutover-execution-log.md`

**Interfaces:**
- Destination: `s3://skn27-pilot-908708651753-clean/canonical/acceptance/pilot-fine-notice-prior-notice-valid-through-20260831-v1.pdf`
- Required metadata: `ContentType=application/pdf`, `ServerSideEncryption=AES256`.
- Produces: read-back metadata and remote SHA-256 equal to the operator-approved local SHA-256.

- [ ] **Step 1: Confirm the publication approval is hash-specific**

Before any AWS write, repeat the local SHA-256 and byte size and require them to match the operator-approved evidence. If the bytes changed, return to Task 3 for a new visual review and approval.

- [ ] **Step 2: Fail closed if the destination already exists**

Call `aws s3api head-object` for the exact bucket/key. Continue only when AWS returns the specific not-found result. Any successful lookup, access-denied response, credentials error, or ambiguous network error is a hard stop; never use `--overwrite` semantics.

- [ ] **Step 3: Upload once with fixed metadata**

After the explicit publication approval, use `aws s3api put-object` with:

```powershell
--bucket skn27-pilot-908708651753-clean
--key canonical/acceptance/pilot-fine-notice-prior-notice-valid-through-20260831-v1.pdf
--body output/pdf/pilot-fine-notice-prior-notice-valid-through-20260831-v1.pdf
--content-type application/pdf
--server-side-encryption AES256
```

Do not attach usernames, local paths, authorization codes, provider data, or free-form metadata.

- [ ] **Step 4: Read back metadata and exact bytes**

Use `head-object` to require exact content length, `application/pdf`, and `AES256`. Download the object to a new file under `C:\tmp`, compute SHA-256, and require it to equal the approved local SHA-256. Delete only that exact temporary read-back file after verification.

- [ ] **Step 5: Record publication evidence and stop before paid work**

Record the S3 URI, VersionId if present, ETag, content length, encryption, approved local SHA, remote SHA, and exact-match result. Do not acquire a Google code or start cutover in this task.

---

### Task 5: Execute one separately approved strict cutover and complete acceptance

**Files:**
- Read: `deploy/aws-pilot/Deploy-Pilot.ps1`
- Read: `deploy/aws-pilot/runtime.env.example`
- Modify: `docs/tech-validation-reports/2026-08-02-production-cutover-execution-log.md`
- Modify as results warrant: `docs/tech-validation-reports/2026-07-31-pilot-hotfix-master-checklist.md`

**Interfaces:**
- Release tag: `908e844fd6fa`
- Manifest SHA: `9bb155067bdbff2792ff1ceb17002b99431454b31c52029f7cee8af75f2294ac`
- Fine-notice URI: the exact Task 4 immutable S3 URI.
- Google authorization code: a fresh one-time code placed in the existing SecureString parameter and never printed/read back.
- Deployment: existing SSM-backed `Deploy-Pilot.ps1`, with strict report gates unchanged.

- [ ] **Step 1: Revalidate private release state before spending anything**

Take a read-only SSM snapshot and require release directory `908e844fd6fa`, seed complete marker, release evidence, exact seed descriptor, healthy private services, `current=false`, and no production containers. Also require sufficient disk headroom. If any invariant changed, stop and diagnose before requesting a code or paid approval.

- [ ] **Step 2: Obtain a new Google one-time code**

Have the operator complete Google consent and enter the full callback URL through a secure prompt. Validate scheme/host/path and exactly one `code` query value, write only the code to the known SecureString parameter, overwrite the clipboard with a non-secret sentinel, and report parameter name/version without reading the value back.

- [ ] **Step 3: Obtain separate approval for one paid Supervisor/provider smoke**

State that the prior paid smoke was already consumed and request approval specifically for one additional execution against the Task 4 artifact SHA/S3 URI. Without that approval, stop while preserving private staged state.

- [ ] **Step 4: Run the existing final cutover exactly once**

Invoke `Deploy-Pilot.ps1` with release `908e844fd6fa`, the existing exact seed descriptor values, runtime environment path, fresh Google SecureString parameter, and the new S3 fixture URI. Retain all existing readiness, Google live-smoke, real-agent, persisted-handoff, and report gates. Do not also run/approve the CodePipeline App Release path.

Expected strict Supervisor result:

```text
job_success=true
all_agent_results_success=true
real_agent_results=true
persisted_handoff_consumed=true
report_ready=true
```

- [ ] **Step 5: On failure, snapshot and diagnose without retry**

Retrieve the exact SSM command ID, terminal status, timestamps, and credential-masked stdout/stderr. Snapshot `current`, production/stage containers/networks, release directory, seed/evidence markers, Google parameter deletion state, and disk. Do not rerun; a later attempt requires a new root-cause decision, new code, and new paid approval.

- [ ] **Step 6: On success, perform public and 10-minute acceptance**

Verify public HTTPS, backend/frontend health, release identity, Google session, report download, and operational evidence immediately and after the full 10-minute window. Record exact timestamps and evidence; transient queue warnings belong to the acceptance window rather than the deployment transaction unless the existing gate defines otherwise.

- [ ] **Step 7: Run and record all 13 required E2E scenarios**

Execute the master checklist’s 13 scenarios against the promoted release, including the original UI/E2E hotfix concerns: attachment follow-up recognition, Markdown answer rendering, separated clarification prompts, stable/truncated conversation title, authenticated UI state, unclipped sidebar/containers, report generation, draft/final download, polling semantics, and evidence continuity. A scenario is complete only with an expected/actual result and captured evidence; any failure reopens the corresponding hotfix item.

- [ ] **Step 8: Close the execution log and master checklist**

Record the promoted release, fixture SHA/S3 VersionId, SSM command IDs, strict smoke result, 10-minute acceptance, all 13 E2E results, residual risks, and rollback reference. Do not mark the master hotfix complete if any public, download, report, auth, layout, or E2E item is not GREEN.

---

## Final Verification Matrix

| Gate | Evidence | Required result |
| --- | --- | --- |
| Source contract | Focused pytest | Exact fields and markings pass |
| Determinism | Two independent builds | Identical SHA-256 |
| PDF safety | `pypdf` + raw token scan | One page; no form, annotation, attachment, link, JS, or local path |
| Text fidelity | `pdfplumber` | Every exact Korean label/value extracted |
| Visual quality | Original-detail PNG inspection | No glyph damage, clipping, overlap, or misleading official appearance |
| Git scope | `git status` and staged list | PDF/PNG absent; only planned source/docs staged |
| S3 immutability | `head-object` before upload | Destination absent |
| S3 integrity | metadata + downloaded SHA | `application/pdf`, `AES256`, exact size/SHA |
| Paid gate | Operator approval | One additional execution only |
| Strict Supervisor | Existing cutover output | All five strict booleans true |
| Public acceptance | Immediate + 10-minute checks | Healthy and release identity exact |
| E2E completion | Master checklist | 13/13 GREEN with evidence |

## Self-Review Checklist

- [ ] Every approved design field and safety marking is represented by an exact assertion.
- [ ] No placeholder path, bucket, release, manifest SHA, or S3 key remains.
- [ ] No existing runtime renderer or legal/report gate is modified.
- [ ] The generated artifact cannot be staged accidentally.
- [ ] Local tests are offline and cost-free.
- [ ] Visual approval, S3 publication, Google code, and paid smoke are four distinct gates.
- [ ] Failure handling forbids blind retries and preserves evidence.
- [ ] Post-cutover 10-minute acceptance and 13 E2E remain mandatory.
