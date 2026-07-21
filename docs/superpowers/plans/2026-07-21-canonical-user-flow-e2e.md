# Canonical User Flow E2E Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 확인된 사실과 사용자 주장을 분리해 공개하고, 세션·업로드·스캔·Supervisor 큐·Worker·분석 결과·DOCX 다운로드를 연결하는 대표 사용자 흐름 E2E 회귀 검증을 추가한다.

**Architecture:** `analysis_job_query_service`가 영속된 `supervisor_state.case_evidence.claims`에서 허용된 필드만 추려 top-level `user_claims`로 투영한다. 새 Django E2E는 App JWT의 실제 `/api/` 요청과 실제 저장·큐·Worker·문서 렌더링 경로를 사용하되, 외부 LLM/OCR/RAG 호출만 결정적 fixture로 대체한다.

**Tech Stack:** Python 3.13, Django `TestCase`/`Client`, Pydantic DTO, pytest 정적 계약 테스트, python-docx 기반 DOCX 렌더링.

## Global Constraints

- `user_claims`는 기존 분석 결과에만 추가하는 additive field이며 기존 HTTP 상태·필드·인증·DB schema를 바꾸지 않는다.
- 각 claim은 `field`, 문자열 `value`, 선택적 `source_type`만 공개한다. `source_ref`, `source_message_id`, 원문 채팅, Worker/Agent 입력·출력·저장 경로는 공개하지 않는다.
- 대표 흐름의 공식 다운로드 성공 조건은 `document_type=objection_form`의 DOCX MIME 타입과 `PK` 본문뿐이다. PDF 목 테스트와 PDF 경로는 수정하지 않는다.
- E2E는 App JWT 한 경로만 사용한다. guest credential 전환·수명은 기존 guest E2E의 책임으로 유지한다.
- 외부 OCR·RAG·LLM 품질과 UI 변경은 이 작업 범위에서 제외한다.
- 체크리스트는 모든 새 테스트와 관련 회귀 테스트가 통과한 경우에만 I의 대표 사용자 흐름 한 항목만 완료 처리한다.

---

### Task 1: 공개 `user_claims` DTO와 안전한 결과 투영

**Files:**

- Modify: `app/contracts/analysis_job.py:49-55`
- Modify: `app/services/analysis_job_query_service.py:16-27, 155-179`
- Test: `test/test_analysis_job_query_service.py`
- Test: `test/test_openapi_v1_generation.py`

**Interfaces:**

- Consumes: `job["supervisor_state"]["case_evidence"]["claims"]`, where every claim record is `{ "value": str, "evidence_source": {"source_type": str, ...} }`.
- Produces: `AnalysisResult.user_claims: list[AnalysisUserClaim]` and `load_analysis_result(...).payload["user_claims"]`.

- [ ] **Step 1: Write failing projection tests**

Add one focused test to `test/test_analysis_job_query_service.py`. It supplies both a public claim and private provenance, then asserts the exact public projection.

```python
def test_completed_result_projects_claims_without_private_provenance() -> None:
    from app.services.analysis_job_query_service import load_analysis_result

    outcome = load_analysis_result(
        "job_claim_boundary",
        load_job=lambda _job_id: {
            "job_id": "job_claim_boundary",
            "status": "success",
            "supervisor_state": {
                "collected_facts": [{"field": "notice_number", "value": "N-2026"}],
                "case_evidence": {
                    "claims": {
                        "incident_location": {
                            "value": "교차로 진입 전 정지했습니다.",
                            "evidence_source": {
                                "source_type": "user_statement",
                                "source_ref": "s3://private/claim.txt",
                                "source_message_id": "msg_private",
                            },
                        }
                    }
                },
            },
            "agent_results": [],
        },
        compose_response=lambda _payload: {"contract_version": "analysis_result.v2"},
    )

    assert outcome.payload["user_claims"] == [
        {
            "field": "incident_location",
            "value": "교차로 진입 전 정지했습니다.",
            "source_type": "user_statement",
        }
    ]
    assert "case_evidence" not in outcome.payload["supervisor_state"]
    assert "source_ref" not in repr(outcome.payload)
    assert "source_message_id" not in repr(outcome.payload)
```

Update `test_completed_result_preserves_persisted_presentation_fields` so its exact expected payload includes `"user_claims": []`.

Also add this OpenAPI regression test to `test/test_openapi_v1_generation.py`.

```python
def test_analysis_result_schema_exposes_optional_sanitized_user_claims() -> None:
    from app.contracts.openapi_v1 import build_openapi_document

    schema = build_openapi_document()["components"]["schemas"]
    result = schema["AnalysisResult"]
    assert result["properties"]["user_claims"] == {
        "items": {"$ref": "#/components/schemas/AnalysisUserClaim"},
        "type": "array",
    }
    assert "user_claims" not in result.get("required", [])
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```powershell
python -m pytest -q --timeout=30 test/test_analysis_job_query_service.py -k claims
python -m pytest -q --timeout=30 test/test_openapi_v1_generation.py -k user_claims
```

Expected: FAIL because `user_claims` and `AnalysisUserClaim` are absent.

- [ ] **Step 3: Add the additive DTO and projection helper**

In `app/contracts/analysis_job.py`, insert the model before `AnalysisResult` and add the defaulted field.

```python
class AnalysisUserClaim(AnalysisJobContractModel):
    field: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=2000)
    source_type: str | None = Field(default=None, min_length=1, max_length=64)


class AnalysisResult(AnalysisJobSummary):
    contract_version: str = Field(min_length=1, max_length=64)
    user_claims: list[AnalysisUserClaim] = Field(default_factory=list)
```

In `app/services/analysis_job_query_service.py`, add the helper and attach it only to completed results.

```python
def _project_user_claims(supervisor_state: Any) -> list[dict[str, str | None]]:
    if not isinstance(supervisor_state, dict):
        return []
    case_evidence = supervisor_state.get("case_evidence")
    if not isinstance(case_evidence, dict):
        return []
    claims = case_evidence.get("claims")
    if not isinstance(claims, dict):
        return []

    projected: list[dict[str, str | None]] = []
    for field in sorted(claims):
        claim = claims.get(field)
        if not isinstance(field, str) or not field.strip() or not isinstance(claim, dict):
            continue
        value = claim.get("value")
        if not isinstance(value, str) or not value.strip():
            continue
        evidence_source = claim.get("evidence_source")
        source_type = (
            evidence_source.get("source_type").strip()
            if isinstance(evidence_source, dict)
            and isinstance(evidence_source.get("source_type"), str)
            and evidence_source["source_type"].strip()
            else None
        )
        projected.append(
            {"field": field.strip(), "value": value.strip(), "source_type": source_type}
        )
    return projected
```

Add `"user_claims": _project_user_claims(job.get("supervisor_state"))` to the completed-result `result.update(...)` block. Do not add it to the pending payload because no terminal Supervisor state is ready.

- [ ] **Step 4: Run projection and existing query-service tests**

Run:

```powershell
python -m pytest -q --timeout=30 test/test_analysis_job_query_service.py test/test_api_route_specs.py test/test_openapi_v1_generation.py
```

Expected: PASS. The complete result includes a sorted, provenance-sanitized claim list; pending output and its existing 202 OpenAPI semantic metadata remain unchanged.

- [ ] **Step 5: Commit the contract boundary**

```powershell
git add app/contracts/analysis_job.py app/services/analysis_job_query_service.py test/test_analysis_job_query_service.py test/test_openapi_v1_generation.py
git commit -m "feat: expose sanitized analysis user claims"
```

### Task 2: Canonical App-JWT user-flow E2E

**Files:**

- Create: `backend/chatbot/test_canonical_user_flow_e2e.py`
- Reuse behavior from: `backend/chatbot/test_resource_ownership_e2e.py:30-263`
- Reuse behavior from: `backend/chatbot/file_scan_service.py:69-106`
- Test: `backend/chatbot/test_canonical_user_flow_e2e.py`

**Interfaces:**

- Consumes: `/api/chat/sessions/`, `/api/files/`, `/api/chat/messages/`, `/api/analysis/results/{job_id}/`, `/api/reports/{report_id}/document-confirmation/`, `/api/reports/{report_id}/download/`.
- Produces: four deterministic tests: successful DOCX lifecycle, pending result, partial result, and foreign-owner denial.

- [ ] **Step 1: Write the four failing E2E test methods**

Create a `CanonicalUserFlowE2ETests(TestCase)` class under `@override_settings(APP_JWT_SECRET=TEST_JWT_SIGNING_KEY)`. Its test names and required assertions are:

```python
def test_owner_completes_canonical_flow_and_downloads_docx(self) -> None:
    resources = self._queue_clean_fine_notice_flow()
    self._process_ready_worker(resources["work_item_id"])
    result = self.owner_client.get(f"/api/analysis/results/{resources['job_id']}/")
    assert result.status_code == 200
    assert result.json()["result"]["user_claims"] == [{
        "field": "incident_location",
        "value": "교차로 진입 전 정지했습니다.",
        "source_type": "user_statement",
    }]
    assert "execution_payload" not in result.content.decode()
    assert "raw_output" not in result.content.decode()
    assert "source_ref" not in result.content.decode()
    # Confirm then request objection_form; require DOCX MIME, attachment, and PK.

def test_result_is_pending_before_worker_processing(self) -> None:
    resources = self._queue_clean_fine_notice_flow()
    response = self.owner_client.get(f"/api/analysis/results/{resources['job_id']}/")
    assert response.status_code == 202
    assert response.json()["result"]["status"] == "queued"
    assert "user_claims" not in response.json()["result"]

def test_partial_worker_result_keeps_safe_limitations_and_no_docx_link(self) -> None:
    resources = self._queue_clean_fine_notice_flow()
    self._process_partial_worker(resources["work_item_id"])
    response = self.owner_client.get(f"/api/analysis/results/{resources['job_id']}/")
    assert response.status_code == 200
    assert response.json()["result"]["status"] == "partial"
    assert response.json()["result"]["limitations"]
    assert response.json()["result"]["next_actions"]
    assert response.json()["result"]["report_links"] == []

def test_other_owner_cannot_read_result_report_or_docx(self) -> None:
    resources = self._complete_owner_flow()
    for response in (
        self.attacker_client.get(f"/api/analysis/results/{resources['job_id']}/"),
        self.attacker_client.get(f"/api/reports/{resources['report_id']}/"),
        self.attacker_client.get(
            f"/api/reports/{resources['report_id']}/download/?document_type=objection_form"
        ),
    ):
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "object_access_denied"
        assert not response.content.startswith(b"PK")
        assert "Content-Disposition" not in response.headers
```

- [ ] **Step 2: Run the new module and verify it fails**

Run:

```powershell
python backend/manage.py test chatbot.test_canonical_user_flow_e2e
```

Expected: FAIL because the module, fixture helpers, and `user_claims` projection do not yet exist.

- [ ] **Step 3: Add deterministic, real-boundary test helpers**

Implement four private helpers in the new test module.

```python
def _authenticated_client(user_id: str) -> Client:
    # Issue an App JWT, upsert the active AuthSession, return Client(Authorization=Bearer ...).

def _queue_clean_fine_notice_flow(self) -> dict[str, str]:
    # POST /api/chat/sessions/, multipart POST /api/files/ with SimpleUploadedFile,
    # call process_uploaded_file_scans(limit=1), then GET attachment and require clean.
    # Patch only chatbot.views.submit_message to a deterministic Supervisor response
    # containing collected_facts and case_evidence.claims; POST /api/chat/messages/
    # and require 202 plus a persisted AgentWorkItem.

@contextmanager
def _patched_ready_agents():
    # Patch fine_notice, law, appeal, and objection-report adapters with the same
    # deterministic ready outputs as ResourceOwnershipE2ETests. Keep report
    # creation, persistence, and DOCX rendering unpatched.

def _process_ready_worker(self, work_item_id: str) -> None:
    # Use process_agent_work_item(work_item_id) inside _patched_ready_agents().
```

For the partial helper, retain the required fine-notice and appeal fixture outputs, but make the selected legal-search result a safe `failed` result with a user-facing limitation and next action. Assert the current Reporting gate leaves `report_links` empty; do not create a report or DOCX for this branch.

- [ ] **Step 4: Run the module, then the directly related Django regression modules**

Run:

```powershell
python backend/manage.py test chatbot.test_canonical_user_flow_e2e chatbot.test_resource_ownership_e2e chatbot.test_guest_login_session_ownership_e2e chatbot.test_supervisor_reporting_pipeline chatbot.test_report_api_contract
```

Expected: PASS. The success path returns DOCX only; pending, partial, and ownership denial retain their existing semantics.

- [ ] **Step 5: Commit the canonical journey coverage**

```powershell
git add backend/chatbot/test_canonical_user_flow_e2e.py
git commit -m "test: cover canonical user flow e2e"
```

### Task 3: Checklist evidence and final verification

**Files:**

- Modify: `docs/ops/project-readiness-master-checklist.md:185`
- Modify: `docs/superpowers/specs/2026-07-21-canonical-user-flow-e2e-design.md:5, 104-110`
- Test: all Task 1–3 test modules and the repository suite

**Interfaces:**

- Consumes: passing unit, schema, and Django E2E tests from Tasks 1–3.
- Produces: one evidence-backed I checklist completion line with `#279`; all other I entries remain unchanged.

- [ ] **Step 1: Update only the justified checklist entry**

Replace the existing unchecked I line with:

```md
- [x] 대표 사용자 흐름 E2E: 자료 입력, 사실/주장 분리, OCR, Supervisor 계획, 법령·판례 검색, 한계 표시, 리포트 생성·다운로드 — #279
```

Change the design-document status to `구현 완료 — 검증 대기` before final tests, then to `구현·검증 완료` only after every listed command passes. Do not change the OCR/검색 품질 또는 운영 관측 항목.

- [ ] **Step 2: Run the focused full regression set**

Run:

```powershell
python -m pytest -q --timeout=30 test/test_analysis_job_query_service.py test/test_api_route_specs.py test/test_openapi_v1_generation.py
python backend/manage.py test chatbot.test_canonical_user_flow_e2e chatbot.test_resource_ownership_e2e chatbot.test_guest_login_session_ownership_e2e chatbot.test_supervisor_reporting_pipeline chatbot.test_report_api_contract
```

Expected: PASS.

- [ ] **Step 3: Run the complete Python suite**

Run:

```powershell
python -m pytest -q --timeout=30
```

Expected: PASS with only the repository’s already-approved skips/warnings, if any.

- [ ] **Step 4: Inspect the final diff and commit checklist evidence**

Run:

```powershell
git diff --check origin/dev...HEAD
git status -sb
```

Then commit only the checklist and final design status.

```powershell
git add docs/ops/project-readiness-master-checklist.md docs/superpowers/specs/2026-07-21-canonical-user-flow-e2e-design.md
git commit -m "docs: record canonical flow e2e coverage"
```
