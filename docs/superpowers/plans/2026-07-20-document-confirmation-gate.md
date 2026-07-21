# 공식 이의신청서 최종 확인 게이트 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 일반 분석 리포트의 다운로드를 제거하고, 소유자가 네 가지 항목을 최종 확인한 공식 이의신청서 DOCX만 다운로드하게 한다.

**Architecture:** `Report.metadata`에 문서 입력 지문과 확인 시각을 저장하고, 리포트 상세 조립 시 지문을 다시 계산해 안전한 상태만 공개한다. 다운로드 뷰는 일반 문서 요청을 거절하고, 공식 문서 요청에는 기존 소유권·appeal gate 다음으로 최종 확인을 검사한다. 프런트엔드는 일반 DOCX 동선을 없애고 확인 API 성공 후에만 공식 DOCX를 실행한다.

**Tech Stack:** Django, Django ORM JSONField, Pydantic v2 DTO/OpenAPI 생성기, React JSX, pytest/Django TestCase.

## Global Constraints

- `fine_notice`와 `traffic_accident`의 `objection_form`만 사용자 DOCX 다운로드를 제공한다.
- 일반 분석 리포트는 화면 열람·저장만 제공하며 일반 DOCX 렌더링·다운로드 동선은 제공하지 않는다.
- appeal gate가 차단되면 최종 확인과 공식 DOCX 다운로드를 모두 `409 appeal_gate_blocked`로 차단한다.
- 확인 기록에는 SHA-256 지문·시각·내부 소유자 ID·네 Boolean만 저장한다. 원문 개인정보를 새 API·저장소에 복제하지 않는다.
- 기존 리포트 목록·상세 DTO의 기존 필드는 유지하며 `document_confirmation`은 선택 필드로만 추가한다.
- 모든 동작 변경은 실패 테스트를 먼저 실행해 RED를 확인한 뒤 구현한다.

---

### Task 1: 문서 확인 DTO와 OpenAPI 계약

**Files:**
- Modify: `app/contracts/report.py:35-170`
- Modify: `app/contracts/api_route_specs.py:62-70, 781-910`
- Modify: `backend/chatbot/urls.py:46-49`
- Test: `test/test_api_route_specs.py`
- Test: `test/test_openapi_v1_generation.py`

**Interfaces:**
- Produces `ReportDocumentConfirmation`, `ConfirmReportDocumentRequest`, `ConfirmReportDocumentResponse`.
- Produces `POST /api/reports/{report_id}/document-confirmation/` with 201, 403, 404, 409, and 422 responses.

- [ ] **Step 1: 새 DTO와 새 OpenAPI 경로를 요구하는 실패 테스트를 작성한다.**

```python
def test_report_contract_exposes_document_confirmation_request_and_response() -> None:
    assert contracts.ConfirmReportDocumentRequest.model_validate(
        {
            "facts_confirmed": True,
            "agency_confirmed": True,
            "deadline_confirmed": True,
            "attachments_confirmed": True,
        }
    )
    assert "document_confirmation" in contracts.ReportReportingPayload.model_fields


def test_openapi_exposes_document_confirmation_route() -> None:
    assert "/api/reports/{report_id}/document-confirmation/" in build_openapi_document()["paths"]
```

- [ ] **Step 2: RED를 확인한다.**

Run: `python -m pytest -q test/test_api_route_specs.py test/test_openapi_v1_generation.py -p no:cacheprovider`

Expected: `ConfirmReportDocumentRequest` 또는 새 경로 부재로 FAIL.

- [ ] **Step 3: 최소 DTO·URL·RouteSpec을 구현한다.**

```python
class ReportDocumentConfirmation(ReportApiContractModel):
    required: bool = False
    confirmed: bool = False
    stale: bool = False
    confirmed_at: datetime | None = None


class ConfirmReportDocumentRequest(StrictRequest):
    facts_confirmed: Literal[True]
    agency_confirmed: Literal[True]
    deadline_confirmed: Literal[True]
    attachments_confirmed: Literal[True]


class ConfirmReportDocumentResponse(ReportApiContractModel):
    contract_version: Literal["document_confirmation.v1"]
    document_confirmation: ReportDocumentConfirmation
```

Add `document_confirmation` as an optional `ReportReportingPayload` field. Add the POST Django path and a RouteSpec with `request_model=ConfirmReportDocumentRequest`, `response_model=ConfirmReportDocumentResponse`, and documented `appeal_gate_blocked` / `document_confirmation_required` error codes. Extend `ReportApiError.code` with `document_download_not_available`, `document_confirmation_required`, and `appeal_gate_blocked`.

- [ ] **Step 4: GREEN을 확인한다.**

Run: `python -m pytest -q test/test_api_route_specs.py test/test_openapi_v1_generation.py -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 5: 커밋한다.**

```powershell
git add app/contracts/report.py app/contracts/api_route_specs.py backend/chatbot/urls.py test/test_api_route_specs.py test/test_openapi_v1_generation.py
git commit -m "feat: add document confirmation API contract"
```

### Task 2: 확인 지문·상태 저장과 공개 투영

**Files:**
- Modify: `backend/chatbot/repositories.py:109-110, 4077-4185, 4205-4255, 8540-8551`
- Modify: `app/services/report_query_service.py:18-35, 70-110`
- Test: `backend/chatbot/test_supervisor_reporting_pipeline.py`
- Test: `backend/chatbot/test_report_api_contract.py`

**Interfaces:**
- Produces `get_report_document_confirmation_state(report: Report) -> dict[str, object]`.
- Produces `confirm_report_document(report_id: str, *, owner_id: str) -> dict[str, object]`.
- Stores only the input digest in `Report.metadata["document_confirmation"]`.

- [ ] **Step 1: 확인 전·확인 후·입력 변경 후 stale 공개 상태의 실패 테스트를 작성한다.**

```python
def test_report_detail_projects_stale_confirmation_without_fingerprint() -> None:
    report = _ready_objection_report()
    assert confirm_report_document(report.report_id, owner_id=report.owner_id)["confirmed"] is True
    report.content["reporting_payload"]["petition_reason"] = "changed reason"
    report.save(update_fields=["content", "updated_at"])

    state = get_report_record_detail(report.report_id)["content"]["reporting_payload"]["document_confirmation"]
    assert state == {"required": True, "confirmed": False, "stale": True, "confirmed_at": None}
```

- [ ] **Step 2: RED를 확인한다.**

Run: `python -m pytest -q backend/chatbot/test_supervisor_reporting_pipeline.py backend/chatbot/test_report_api_contract.py -p no:cacheprovider`

Expected: confirmation helper 또는 public state 부재로 FAIL.

- [ ] **Step 3: 지문·확인 저장·공개 상태를 구현한다.**

```python
def _report_document_input_fingerprint(report: Report) -> str:
    payload = _reporting_payload_for_download(report)
    document_input = {
        "document_variant": _report_document_variant(report, payload),
        "form_data": _dict_or_empty(payload.get("form_data")),
        "sections": _list_or_empty(payload.get("sections")),
        "petition_purpose": _text(payload.get("petition_purpose")),
        "petition_reason": _text(payload.get("petition_reason")),
    }
    canonical = json.dumps(document_input, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

Implement `confirm_report_document` in `transaction.atomic()` using `select_for_update()`. It rejects a non-official document variant or blocked appeal before writing. `get_report_document_confirmation_state` recalculates the current fingerprint on every read and returns only `{required, confirmed, stale, confirmed_at}`. Attach it in `get_report_record_detail` and add the field to `PUBLIC_REPORTING_PAYLOAD_KEYS`.

- [ ] **Step 4: GREEN을 확인한다.**

Run: `python -m pytest -q backend/chatbot/test_supervisor_reporting_pipeline.py backend/chatbot/test_report_api_contract.py -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 5: 커밋한다.**

```powershell
git add backend/chatbot/repositories.py app/services/report_query_service.py backend/chatbot/test_supervisor_reporting_pipeline.py backend/chatbot/test_report_api_contract.py
git commit -m "feat: persist document confirmation state"
```

### Task 3: 확인 API와 공식 DOCX 전용 서버 게이트

**Files:**
- Modify: `backend/chatbot/views.py:15-35, 1819-1918`
- Modify: `backend/chatbot/repositories.py:4104-4155, 8540-8551`
- Test: `backend/chatbot/test_supervisor_reporting_pipeline.py`
- Test: `test/test_consultation_v2_contract.py`

**Interfaces:**
- Consumes `ConfirmReportDocumentRequest` and `confirm_report_document`.
- Produces `document_confirmation_required`, `document_download_not_available`, and `appeal_gate_blocked` report errors.
- `get_report_download_metadata(..., document_type="objection_form")` is the only DOCX body producer.

- [ ] **Step 1: 일반 다운로드 거절·확인 전 공식 DOCX 차단·확인 후 DOCX 허용의 실패 테스트를 작성한다.**

```python
def test_download_requires_current_document_confirmation() -> None:
    report = _ready_objection_report()
    assert _download_as_owner(report, document_type="report").status_code == 409
    blocked = _download_as_owner(report, document_type="objection_form")
    assert b'"code": "document_confirmation_required"' in blocked.content

    confirm_report_document(report.report_id, owner_id=report.owner_id)
    allowed = _download_as_owner(report, document_type="objection_form")
    assert allowed.status_code == 200
    assert allowed.content.startswith(b"PK")
```

Also test `denied`, `not_applicable`, and deadline-passed reports return `appeal_gate_blocked` from both confirmation and official download; test owner mismatch before any writer call.

- [ ] **Step 2: RED를 확인한다.**

Run: `python -m pytest -q backend/chatbot/test_supervisor_reporting_pipeline.py test/test_consultation_v2_contract.py -p no:cacheprovider`

Expected: general DOCX is still supplied and confirmation-required assertion FAIL.

- [ ] **Step 3: 뷰와 다운로드 분기를 구현한다.**

```python
@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def report_document_confirmation(request: HttpRequest, report_id: str) -> JsonResponse:
    body = _json_body(request)
    identity_payload = _payload_with_request_identity(request, body)
    # Reuse report login/owner authorization before validation and write.
    validated, validation_response = _validate_request_dto(request, ConfirmReportDocumentRequest, body)
    if validation_response is not None:
        return validation_response
    confirmation = confirm_report_document(report_id, owner_id=str(subject["user_id"]))
    return _json_response(request, {"contract_version": "document_confirmation.v1", "document_confirmation": confirmation}, status=201)
```

Normalize only documented objection aliases to `REPORT_DOWNLOAD_TYPE_OBJECTION_FORM`; return `None` for every other value. In `download_report`, authorize first, reject a non-official type with `document_download_not_available`, then enforce ready state, appeal gate, and current confirmation before rendering. The mock branch follows the same document-type restriction. Set summary `download_url` to `None` so a general direct-download link cannot be exposed.

- [ ] **Step 4: GREEN을 확인한다.**

Run: `python -m pytest -q backend/chatbot/test_supervisor_reporting_pipeline.py test/test_consultation_v2_contract.py -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 5: 커밋한다.**

```powershell
git add backend/chatbot/views.py backend/chatbot/repositories.py backend/chatbot/test_supervisor_reporting_pipeline.py test/test_consultation_v2_contract.py
git commit -m "feat: gate official document downloads"
```

### Task 4: 최종 확인 UI와 일반 DOCX 동선 제거

**Files:**
- Modify: `app/web/apiClient.js:86-104`
- Modify: `app/web/FrontendAppShell.jsx:417-580, 2094-2185, 2869-2895`
- Test: `test/test_consultation_v2_contract.py`

**Interfaces:**
- Produces `api.confirmReportDocument({ reportId, sessionId, identity, confirmation })`.
- Consumes `reporting_payload.document_confirmation`.
- Calls `downloadReport` only with `documentType: "objection_form"`.

- [ ] **Step 1: 일반 DOCX 버튼 부재와 확인 API 사용을 요구하는 실패 테스트를 작성한다.**

```python
def test_frontend_only_downloads_confirmed_objection_docx() -> None:
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")
    client = read_text(ROOT / "app" / "web" / "apiClient.js")
    assert 'onRunReportAction("download_report")' not in shell
    assert "분석 리포트 DOCX" not in shell
    assert "confirmReportDocument" in client
    assert "document_confirmation" in shell
```

- [ ] **Step 2: RED를 확인한다.**

Run: `python -m pytest -q test/test_consultation_v2_contract.py -p no:cacheprovider`

Expected: existing `download_report` buttons and generic DOCX label cause FAIL.

- [ ] **Step 3: API 클라이언트·확인 상태·패널을 최소 구현한다.**

```javascript
confirmReportDocument({ reportId, sessionId, identity, confirmation } = {}) {
  return postJson(
    joinApiPath(apiBase, `reports/${encodeURIComponent(reportId || "")}/document-confirmation/`),
    confirmation,
    identity,
  );
},
```

Keep only `download_objection`. Render controlled checkboxes for facts, agency, deadline, and attachments; keep submit disabled until all four are true. When appeal is blocked, disable confirmation and download with the existing reason. Show stale as a re-confirmation notice. After confirmation succeeds, refresh `getReportDetail` and permit official DOCX only when `confirmed` is true.

- [ ] **Step 4: GREEN을 확인한다.**

Run: `python -m pytest -q test/test_consultation_v2_contract.py -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 5: 커밋한다.**

```powershell
git add app/web/apiClient.js app/web/FrontendAppShell.jsx test/test_consultation_v2_contract.py
git commit -m "feat: require confirmation before objection DOCX"
```

### Task 5: 체크리스트와 최종 회귀 검증

**Files:**
- Modify: `docs/ops/project-readiness-master-checklist.md:160-162`
- Modify: `docs/superpowers/plans/2026-07-20-document-confirmation-gate.md`
- Test: `test/test_api_route_specs.py`
- Test: `test/test_openapi_v1_generation.py`
- Test: `test/test_consultation_v2_contract.py`
- Test: `backend/chatbot/test_supervisor_reporting_pipeline.py`

- [ ] **Step 1: 체크리스트 상태를 갱신한다.**

```markdown
- [~] 문서 생성 전 사용자 최종 확인: 사실관계, 관할기관, 기한, 첨부자료 — #241
- [x] DOCX 전용 한글 렌더링, 개인정보 마스킹, 권한 검증 및 PDF 사용자 다운로드 제거 — #238
- [x] fine_notice·traffic_accident·일반 분석 리포트의 문서별 DOCX 다운로드와 appeal gate E2E — #238
```

- [ ] **Step 2: 관련 회귀 검증을 실행한다.**

Run: `python -m pytest -q test/test_api_route_specs.py test/test_openapi_v1_generation.py test/test_consultation_v2_contract.py backend/chatbot/test_report_api_contract.py backend/chatbot/test_supervisor_reporting_pipeline.py -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 3: 전체 테스트 스위트를 실행한다.**

Run: `python -m pytest -q --timeout=30 -p no:cacheprovider --basetemp .pytest-tmp-issue241-final`

Expected: all collected tests pass; known skips are reported without failures.

- [ ] **Step 4: 변경 범위와 요구사항을 대조하고 커밋·푸시한다.**

Run: `git diff origin/dev...HEAD --check; git status -sb`

Expected: whitespace error 없음, #241 의도 파일만 변경, pytest 임시 디렉터리는 커밋 대상이 아님.

```powershell
git add docs/ops/project-readiness-master-checklist.md docs/superpowers/plans/2026-07-20-document-confirmation-gate.md
git commit -m "docs: track document confirmation gate"
git push -u origin feat/241-document-confirmation-gate
```

## Self-Review

- Spec coverage: 일반 다운로드 제거, 공식 DOCX 제한, 네 항목 확인, 소유권·appeal gate, 지문 기반 stale, 공개 DTO, UI, 체크리스트, 전체 검증을 Task 1~5에 각각 배정했다.
- Placeholder scan: `TBD`, `TODO`, 모호한 후속 구현 표기를 두지 않았고, 모든 변경에 대상 파일·테스트·명령을 적었다.
- Type consistency: 공개 상태는 `ReportDocumentConfirmation`, 요청은 `ConfirmReportDocumentRequest`, 저장·검증 헬퍼는 `confirm_report_document`와 `get_report_document_confirmation_state`로 모든 작업에서 일관되게 사용한다.

## Execution Handoff

계획은 `docs/superpowers/plans/2026-07-20-document-confirmation-gate.md`에 저장한다. 사용자가 기존에 요청한 인라인 실행 방식으로, 각 Task에서 RED → GREEN → 회귀 검증 순서를 지켜 진행한다.
