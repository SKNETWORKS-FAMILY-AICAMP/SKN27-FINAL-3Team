# 리포트 API 조회·다운로드 계약 및 문서 E2E Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 리포트 목록·상세·PDF 다운로드 경로를 안전한 공개 DTO와 OpenAPI v1 계약으로 승격하고, 목록 → 상세 → 다운로드를 권한 경계까지 포함해 Django HTTP E2E로 검증한다.

**Architecture:** 저장소는 기존 영속 조회·권한 메타데이터·PDF 렌더링 책임을 유지한다. 새 `report_query_service`는 저장소 레코드를 공개 DTO로 투영하는 단일 경계가 되고, 뷰는 HTTP·인증·권한·상태 코드 변환만 담당한다. 라우트 명세에는 JSON 이외의 성공 응답을 표현하는 일반 메타데이터를 추가해 PDF 경로도 특정 API용 조건문 없이 OpenAPI로 생성한다.

**Tech Stack:** Python 3.13, Django, Pydantic v2, Pytest, Django TestCase, PyYAML/OpenAPI 3.2, React/Vite 검증

## Global Constraints

- 변경 파일 목록을 확인한다.
- 의도하지 않은 파일 수정 여부를 확인한다.
- 변경 범위에 맞는 테스트와 관련 회귀 테스트를 실행한다.
- 타입 체크 또는 린트를 실행한다. 이 저장소에서는 `ruff check --select E9,F63,F7,F82 .`와 `npm run build`를 기본으로 한다.
- 핵심 기능을 직접 실행한다. #226에서는 Django HTTP E2E 목록 → 상세 → PDF 다운로드가 이에 해당한다.
- 인증·권한·개인정보·저장소 메타데이터 등 보안 경계를 재확인한다.
- 경로별 문자열/응답 조립 하드코딩을 추가하지 않고, 정책·DTO·서비스 모듈에 책임을 분리한다.
- `POST /api/reports/`, 리포트 생성 파이프라인, DB 모델/마이그레이션, 외부 스토리지, UI 재설계는 변경하지 않는다.
- 에이전트는 `git add`, `git commit`, `git push`, PR 생성·수정·병합을 하지 않는다. 검증이 끝난 뒤 사용자에게 정확한 변경 파일과 Git 명령만 전달한다.

---

## File Structure

| 파일 | 작업 | 책임 |
| --- | --- | --- |
| `app/contracts/report.py` | 생성 | 공개 리포트 목록·상세·오류 DTO와 허용 필드를 정의한다. |
| `app/services/report_query_service.py` | 생성 | 저장소 레코드를 공개 목록/상세 응답으로 투영하고 내부 필드를 차단한다. |
| `backend/chatbot/views.py` | 수정 | 리포트 GET HTTP 진입점에서 인증 실패, 권한, DTO 서비스, PDF 공개 헤더를 연결한다. |
| `backend/chatbot/test_report_api_contract.py` | 생성 | owner/other/anonymous/invalid-token/draft/unknown을 포함한 HTTP E2E를 검증한다. |
| `app/contracts/api_route_specs.py` | 수정 | 세 GET 리포트 경로 및 일반 성공 콘텐츠/헤더 명세를 등록한다. POST는 deferred로 남긴다. |
| `app/contracts/openapi_v1.py` | 수정 | 일반 성공 콘텐츠/헤더 명세를 OpenAPI 응답으로 생성한다. |
| `docs/api/openapi-v1.yaml` | 생성기로 갱신 | 정식 리포트 GET 경로와 PDF 바이너리 계약을 반영한다. |
| `test/test_report_query_service.py` | 생성 | DTO 투영이 내부 metadata/source/storage/fingerprint를 누출하지 않는지 검증한다. |
| `test/test_api_route_specs.py` | 수정 | 모델링된 리포트 GET과 deferred POST의 경계를 검증한다. |
| `test/test_openapi_v1_generation.py` | 수정 | 리포트 JSON/PDF/OpenAPI 오류·헤더 계약과 결정적 YAML 생성을 검증한다. |
| `docs/ops/project-readiness-master-checklist.md` | 수정 | #224/#225 완료, #226 진행 상태, 공통 PR 품질 게이트를 기록한다. |

## Public Contract and Module Interfaces

`app/contracts/report.py`는 `StrictResponse`와 같은 `extra="forbid"` 경계를 사용한다. 중첩 `reporting_payload`도 원문 전체가 아니라 아래 공개 키만 포함한다.

```python
class ReportApiContractModel(StrictResponse):
    pass

PUBLIC_REPORTING_PAYLOAD_KEYS = (
    "report_type",
    "screen_id",
    "stage",
    "title",
    "summary",
    "sections",
)

class ReportReportingPayload(ReportApiContractModel):
    report_type: ReportTypeValue | None = None
    screen_id: str | None = None
    stage: str | None = None
    title: str | None = None
    summary: str | None = None
    sections: list[dict[str, Any]] = Field(default_factory=list)

class ReportQuality(ReportApiContractModel):
    contract_version: str | None = None
    partial_report: bool = False
    review_required: bool = False
    limitation_count: int = Field(default=0, ge=0)
    limitations: list[str] = Field(default_factory=list)
    confidence_label: str | None = None

class ReportSummary(ReportApiContractModel):
    report_id: str = Field(min_length=1, max_length=64)
    report_type: ReportTypeValue
    screen_id: str = ""
    title: str = ""
    status: ReportStatusValue
    session_id: str | None = None
    job_id: str | None = None
    summary: str = ""
    download_url: str | None = None
    partial_report: bool = False
    created_at: datetime
    updated_at: datetime

class ReportListResponse(ReportApiContractModel):
    api_surface: str = Field(min_length=1, max_length=32)
    reports: list[ReportSummary]

class ReportDetailResponse(ReportApiContractModel):
    api_surface: str = Field(min_length=1, max_length=32)
    execution_mode: str = Field(min_length=1, max_length=32)
    report: ReportDetail

class ReportApiError(ReportApiContractModel):
    contract_version: str | None = None
    type: str | None = None
    code: Literal[
        "token_invalid", "token_expired", "guest_session_invalid", "login_required",
        "object_access_denied", "report_not_found", "report_not_ready",
    ]
    status: int = Field(ge=400, le=599)
    message: str = Field(min_length=1)

class ReportApiErrorResponse(ReportApiContractModel):
    error: ReportApiError
```

`ReportSummary`는 `report_id`, `report_type`, `screen_id`, `title`, `status`, `session_id`, `job_id`, `summary`, `download_url`, `partial_report`, `created_at`, `updated_at`만 가진다. `ReportDetail`은 그 필드에 `content.reporting_payload`, `content.contract_version`, `content.format`, `content.action`, 그리고 제한된 `metadata.report_quality`/`metadata.limitations`만 추가한다. `owner_id`, `source`, `request_fingerprint`, `content.source`, `content.quality`, `metadata.object_storage`, `storage_uri`, `job.mock_scenario`는 공개 DTO에 없다.

`app/services/report_query_service.py`의 공개 인터페이스는 다음으로 고정한다.

```python
def compose_report_list_response(
    records: Sequence[Mapping[str, Any]], *, api_surface: str
) -> dict[str, Any]: ...

def compose_report_detail_response(
    record: Mapping[str, Any], *, api_surface: str, execution_mode: str
) -> dict[str, Any]: ...

def report_api_surface(*, canonical: bool, source: object) -> str: ...

def report_execution_mode(*, source: object) -> str: ...
```

`compose_*` 함수는 입력을 변경하지 않고, Pydantic DTO로 검증한 뒤 `model_dump(mode="json")` 결과를 반환한다. 이 함수들이 저장소 레코드에서 공개 응답으로 넘어가는 유일한 투영 경계다.

`RouteSpec`의 일반 성공 응답 인터페이스는 다음으로 고정한다.

```python
@dataclass(frozen=True, slots=True)
class ResponseContentSpec:
    media_type: str
    response_model: type[BaseModel] | None = None
    schema: dict[str, Any] | None = None

@dataclass(frozen=True, slots=True)
class ResponseHeaderSpec:
    name: str
    description: str
    schema: dict[str, Any]
    required: bool = False
```

`RouteSpec.response_model`은 `type[BaseModel] | None`으로 만들되, `success_content`가 비어 있으면 반드시 JSON `response_model`이 있어야 한다. PDF 경로는 `ResponseContentSpec(media_type="application/pdf", schema={"type": "string", "format": "binary"})`와 `Content-Disposition` 헤더 명세를 사용한다. 기존 JSON 경로는 빈 `success_content`로 현재 생성 결과를 유지한다.

### Task 1: 공개 리포트 DTO와 안전한 조회 투영 서비스

**Files:**

- Create: `app/contracts/report.py`
- Create: `app/services/report_query_service.py`
- Create: `test/test_report_query_service.py`

**Interfaces:**

- Consumes: `Mapping[str, Any]` 형태의 `list_report_records` / `get_report_record_detail` 결과
- Produces: `compose_report_list_response`, `compose_report_detail_response`, `report_api_surface`, `report_execution_mode`
- Depends on: `ReportTypeValue`, `ReportStatusValue`, `StrictResponse` from `app/contracts/consultation_case.py`

- [ ] **Step 1: 공개 투영의 실패 테스트를 작성한다.**

```python
def test_detail_projection_preserves_ui_fields_and_drops_internal_storage_fields() -> None:
    from app.services.report_query_service import compose_report_detail_response

    raw = {
        "report_id": "rep_123",
        "report_type": "fault_ratio_analysis",
        "screen_id": "UI-REPORT-FAULT-001",
        "title": "Owner report",
        "status": "ready",
        "session_id": "ses_123",
        "job_id": "job_123",
        "summary": "Safe summary",
        "download_url": "/api/reports/rep_123/download/",
        "partial_report": False,
        "created_at": "2026-07-18T00:00:00+00:00",
        "updated_at": "2026-07-18T00:00:00+00:00",
        "content": {
            "contract_version": "analysis_report.v1",
            "reporting_payload": {
                "title": "Owner report",
                "sections": [{"title": "Facts", "items": ["Verified"]}],
                "provenance": {"fingerprint": "must-not-leak"},
                "source_node_codes": ["law_ground_search"],
            },
            "source": {"request_fingerprint": "must-not-leak"},
        },
        "metadata": {
            "report_quality": {"partial_report": False, "limitations": ["Verify facts"]},
            "object_storage": {"storage_uri": "s3://private/key"},
        },
        "owner_id": "usr_owner",
    }

    response = compose_report_detail_response(
        raw, api_surface="canonical", execution_mode="async_worker"
    )

    assert response["report"]["content"]["reporting_payload"]["sections"][0]["title"] == "Facts"
    assert "provenance" not in response["report"]["content"]["reporting_payload"]
    assert "source" not in response["report"]["content"]
    assert "object_storage" not in response["report"]["metadata"]
    assert "owner_id" not in response["report"]
```

- [ ] **Step 2: 테스트가 새 모듈 부재로 실패하는지 확인한다.**

Run:

```powershell
& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' -m pytest -q test/test_report_query_service.py
```

Expected: `ModuleNotFoundError` 또는 `ImportError`로 실패한다.

- [ ] **Step 3: 계약과 투영 서비스를 최소 구현한다.**

`report.py`에는 아래와 같이 공개 필드만 선언한다. `reporting_payload`의 동적 값은 이미 저장 전 정제된 사용자 표시 데이터이지만, 서비스가 명시 키를 다시 선택해 `source`, `provenance`, token/fingerprint류가 응답으로 되돌아오지 않게 한다.

```python
class ReportContent(StrictResponse):
    contract_version: str | None = None
    format: str | None = None
    action: str | None = None
    reporting_payload: ReportReportingPayload

class ReportMetadata(StrictResponse):
    report_quality: ReportQuality
    limitations: list[str] = Field(default_factory=list)

class ReportDetail(ReportSummary):
    content: ReportContent
    metadata: ReportMetadata
```

`report_query_service.py`에서는 `copy.deepcopy`로 입력을 보호하고, 보고서 표시 데이터를 다음과 같이 고정 키로 투영한다.

```python
def _public_reporting_payload(value: object) -> dict[str, Any]:
    payload = value if isinstance(value, Mapping) else {}
    return {
        key: deepcopy(payload[key])
        for key in PUBLIC_REPORTING_PAYLOAD_KEYS
        if key in payload
    }
```

`_public_report_quality`는 `contract_version`, `partial_report`, `review_required`, `limitation_count`, `limitations`, `confidence_label`만 허용하고 `agent_status_counts` 같은 내부 실행 세부값은 제외한다. 목록은 `ReportSummary`, 상세는 `ReportDetail`을 생성한 뒤 DTO 직렬화 결과만 반환한다.

- [ ] **Step 4: DTO 투영 테스트를 통과시키고 입력 불변성도 확인한다.**

Run:

```powershell
& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' -m pytest -q test/test_report_query_service.py
```

Expected: 목록의 정렬/공개 필드와 상세의 내부 필드 차단 테스트가 모두 `passed`가 된다.

- [ ] **Step 5: 변경 경계를 점검한다.**

Run:

```powershell
git -c safe.directory='D:/dev/project/SKN27-issue226-report-api' -C 'D:\dev\project\SKN27-issue226-report-api' diff -- app/contracts/report.py app/services/report_query_service.py test/test_report_query_service.py
```

Expected: 새 계약·서비스·단위 테스트만 포함하고, 저장소 모델·마이그레이션·UI 파일은 바뀌지 않는다.

### Task 2: 리포트 HTTP 권한·오류·다운로드 개인정보 경계

**Files:**

- Modify: `backend/chatbot/views.py:1687-1890`
- Create: `backend/chatbot/test_report_api_contract.py`

**Interfaces:**

- Consumes: Task 1의 `compose_report_list_response`, `compose_report_detail_response`, `report_api_surface`, `report_execution_mode`
- Consumes: 기존 `get_report_access_metadata`, `authorize_report_download_metadata`, `get_report_download_metadata`
- Produces: 리포트 GET 응답의 200/401/403/404/409 계약과 `Content-Disposition` PDF 다운로드

- [ ] **Step 1: Django HTTP E2E의 실패 테스트를 작성한다.**

새 테스트 모듈에는 `issue_access_token`, `UserAccount`, `AuthSession`을 이용한 owner/other `Client` helper를 둔다. `@override_settings(APP_JWT_SECRET=...)`를 적용하고, 다음 시나리오를 독립된 테스트로 작성한다.

```python
def test_owner_can_list_open_and_download_a_safe_report(self) -> None:
    listed = self.owner_client.get(f"/api/reports/?session_id={self.owner_session.session_id}")
    self.assertEqual(listed.status_code, 200)
    self.assertEqual(listed.json()["reports"][0]["report_id"], self.ready_report.report_id)

    detail = self.owner_client.get(f"/api/reports/{self.ready_report.report_id}/")
    self.assertEqual(detail.status_code, 200)
    self.assertNotIn("object_storage", detail.json()["report"]["metadata"])
    self.assertNotIn("source", detail.json()["report"]["content"])

    pdf = self.owner_client.get(f"/api/reports/{self.ready_report.report_id}/download/")
    self.assertEqual(pdf.status_code, 200)
    self.assertEqual(pdf["Content-Type"], "application/pdf")
    self.assertTrue(pdf.content.startswith(b"%PDF"))
    self.assertNotIn("X-Report-Storage-URI", pdf)
    self.assertNotIn("X-Report-Object-Key", pdf)
```

다른 테스트는 `other_client`의 상세/다운로드 403과 PDF renderer 미호출, 익명 403 `login_required`, malformed Bearer 401 `token_invalid` + `WWW-Authenticate`, 없는 ID 404, worker draft 다운로드 409 `report_not_ready`, `POST /api/reports/`의 409 `worker_report_action_required` 유지를 검증한다.

- [ ] **Step 2: 신규 HTTP 계약 테스트가 현재 응답 누출/401 공백 때문에 실패하는지 확인한다.**

Run:

```powershell
& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' backend/manage.py test chatbot.test_report_api_contract -v 2
```

Expected: 새 테스트는 상세 `object_storage` 노출, PDF 저장소 헤더 노출, malformed Bearer가 401이 아닌 login-required 경로를 타는 지점 중 하나 이상에서 실패한다.

- [ ] **Step 3: 뷰를 얇은 HTTP 경계로 변경한다.**

`views.py`에 다음 전용 helper를 추가한다. 이미 import된 `build_www_authenticate_header`와 `_get_current_auth_subject`를 재사용하므로 새 인증 포맷·오류 문자열을 만들지 않는다.

```python
def _report_auth_error_response(
    request: HttpRequest, *, session_id: str | None
) -> JsonResponse | None:
    status, payload = _get_current_auth_subject(
        authorization_header=request.headers.get("Authorization"),
        guest_id=request.headers.get("X-Guest-Id"),
        session_id=session_id,
    )
    if status < 400:
        return None
    response = _json_response(request, payload, status=status)
    if status == 401:
        response["WWW-Authenticate"] = build_www_authenticate_header(payload)
    return response
```

각 리포트 GET의 canonical 분기 전에 이 helper를 호출한다. 성공한 요청은 기존 `_request_access_payload`와 `access_subject_from_payload`를 계속 사용한다. 목록은 인증된 `user_id`만 `list_report_records(owner_id=...)`에 전달하고 Task 1 서비스로 응답을 조립한다. 상세는 기존 access metadata → owner authorization → DB detail 순서를 유지한 뒤 Task 1 서비스로 응답을 조립한다.

다운로드는 access metadata → owner authorization → ready gate → `get_report_download_metadata` → PDF 렌더링 순서를 그대로 유지한다. 다음 내부 헤더는 제거한다.

```python
"X-Report-Persistence"
"X-Report-Storage-Backend"
"X-Report-Storage-URI"
"X-Report-Object-Key"
"X-Report-Object-Policy"
"X-Report-Access-Decision"
```

기존 사용자 호환성이 있는 `X-API-Surface`, `X-Execution-Mode`, `X-Report-Document-Type`와 표준 `Content-Disposition`만 유지한다. 이 값은 소유권, URI, 객체 키, 스토리지 정책을 포함하지 않는다.

- [ ] **Step 4: E2E와 기존 권한 선검증 회귀를 통과시킨다.**

Run:

```powershell
& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' backend/manage.py test chatbot.test_report_api_contract chatbot.test_supervisor_reporting_pipeline -v 1
```

Expected: 목록 → 상세 → PDF 성공, 401/403/404/409 실패 계약, PDF 렌더링 전 403, 내부 저장소 응답 헤더 차단이 모두 `OK`가 된다.

- [ ] **Step 5: 프런트엔드 소비 필드와 변경 범위를 정적 확인한다.**

Run:

```powershell
rg -n 'content\?\.reporting_payload|metadata\?\.report_quality|report_id|session_id|job_id' app/web/FrontendAppShell.jsx
git -c safe.directory='D:/dev/project/SKN27-issue226-report-api' -C 'D:\dev\project\SKN27-issue226-report-api' diff -- backend/chatbot/views.py backend/chatbot/test_report_api_contract.py
```

Expected: 공개 DTO가 프런트에서 실제 쓰는 `report_id`, `session_id`, `job_id`, `content.reporting_payload`, `metadata.report_quality`를 유지하고, UI 코드 변경 없이 호환된다.

### Task 3: 일반화한 OpenAPI 성공 콘텐츠와 리포트 GET 승격

**Files:**

- Modify: `app/contracts/api_route_specs.py:1-130, 585-792`
- Modify: `app/contracts/openapi_v1.py:22-107`
- Modify: `test/test_api_route_specs.py`
- Modify: `test/test_openapi_v1_generation.py`
- Modify: `docs/api/openapi-v1.yaml` (생성기 결과)

**Interfaces:**

- Consumes: Task 1의 `ReportListResponse`, `ReportDetailResponse`, `ReportApiErrorResponse`
- Produces: `REPORT_API_ROUTE_SPECS`, `ResponseContentSpec`, `ResponseHeaderSpec`, OpenAPI PDF `application/pdf` success content
- Preserves: 현재 Case/Auth/File/Analysis JSON output and POST `/api/reports/` deferred entry

- [ ] **Step 1: 라우트 승격과 PDF 스키마의 실패 테스트를 작성한다.**

```python
def test_report_get_routes_are_modeled_while_report_post_remains_deferred() -> None:
    from app.contracts import api_route_specs as specs

    modeled = {(spec.method, spec.path): spec for spec in specs.REPORT_API_ROUTE_SPECS}
    assert set(modeled) == {
        ("GET", "/api/reports/"),
        ("GET", "/api/reports/{report_id}/"),
        ("GET", "/api/reports/{report_id}/download/"),
    }
    deferred = {(spec.method, spec.path) for spec in specs.DEFERRED_ROUTE_SPECS}
    assert ("POST", "/api/reports/") in deferred
    assert ("GET", "/api/reports/" ) not in deferred

def test_report_download_openapi_uses_binary_pdf_and_attachment_header() -> None:
    from app.contracts.openapi_v1 import build_openapi_document

    response = build_openapi_document()["paths"]["/api/reports/{report_id}/download/"]["get"]["responses"]["200"]
    assert response["content"]["application/pdf"]["schema"] == {"type": "string", "format": "binary"}
    assert response["headers"]["Content-Disposition"]["required"] is True
```

- [ ] **Step 2: 계약 테스트가 현재 deferred/JSON 고정 생성기 때문에 실패하는지 확인한다.**

Run:

```powershell
& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' -m pytest -q test/test_api_route_specs.py test/test_openapi_v1_generation.py
```

Expected: `REPORT_API_ROUTE_SPECS` 부재와 `/api/reports/...` OpenAPI path 부재로 실패한다.

- [ ] **Step 3: 일반 성공 콘텐츠/헤더 명세와 리포트 GET 스펙을 구현한다.**

`ResponseContentSpec.__post_init__`는 `response_model`과 `schema` 중 정확히 하나가 지정됐는지, 미디어 타입이 비어 있지 않은지 검증한다. `ResponseHeaderSpec.__post_init__`는 이름과 schema가 비어 있지 않은지 검증한다. `RouteSpec.__post_init__`는 JSON fallback 또는 `success_content` 중 하나가 존재하는지 검증한다.

`openapi_v1.py`는 다음 일반 helper로 성공 콘텐츠를 만들고, 모든 기존 JSON route에 대한 출력은 그대로 유지한다.

```python
def _success_response_content(spec: RouteSpec) -> dict[str, dict[str, Any]]:
    if not spec.success_content:
        assert spec.response_model is not None
        return {"application/json": {"schema": _schema_ref(spec.response_model)}}
    return {
        content.media_type: {"schema": _content_schema(content)}
        for content in spec.success_content
    }
```

`REPORT_API_ROUTE_SPECS`에는 다음을 등록한다.

```python
RouteSpec(
    operation_id="downloadReportDocument",
    method="GET",
    path="/api/reports/{report_id}/download/",
    route_name="canonical-download-report",
    view_name="download_report",
    request_model=None,
    response_model=None,
    success_status=200,
    success_content=(
        ResponseContentSpec(
            media_type="application/pdf",
            schema={"type": "string", "format": "binary"},
        ),
    ),
    success_headers=(
        ResponseHeaderSpec(
            name="Content-Disposition",
            description="Attachment filename for the rendered report document.",
            schema={"type": "string"},
            required=True,
        ),
    ),
    # 오류/인증/경로 파라미터는 같은 RouteSpec에 명시한다.
)
```

목록/상세는 `ReportListResponse`/`ReportDetailResponse` JSON 성공 모델을 사용한다. 세 GET 모두 `auth_required=True`, `session_id` query parameter를 포함하며, 다운로드에는 optional `document_type` query parameter도 포함한다. 오류 코드는 실제 runtime과 맞춰 401 `token_invalid`/`token_expired`/`guest_session_invalid`, 403 `login_required`/`object_access_denied`, 404 `report_not_found`, 409 `report_not_ready`를 경로별로 선언한다. `POST /api/reports/`의 deferred entry만 남긴다.

- [ ] **Step 4: 생성된 YAML을 갱신하고 계약 테스트를 통과시킨다.**

Run:

```powershell
& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' scripts/generate_openapi_v1.py
& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' -m pytest -q test/test_api_route_specs.py test/test_openapi_v1_generation.py
& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' scripts/generate_openapi_v1.py --check
```

Expected: YAML 생성은 결정적이고 `--check`가 exit code 0으로 끝난다. 세 GET path는 생성되고 POST는 생성되지 않는다.

- [ ] **Step 5: 스키마 회귀와 기존 API route 집합을 확인한다.**

Run:

```powershell
& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' -m pytest -q test/test_api_route_specs.py test/test_openapi_v1_generation.py test/test_report_query_service.py
```

Expected: 기존 Case/Auth/File/Analysis route와 JSON schema assertion은 변경 없이 통과하고, PDF path만 명세 기반 바이너리 응답을 갖는다.

### Task 4: 체크리스트 갱신과 PR 전 전체 품질 게이트

**Files:**

- Modify: `docs/ops/project-readiness-master-checklist.md`
- Verify: Task 1~3의 모든 파일과 기존 프런트엔드 빌드

**Interfaces:**

- Consumes: 구현된 report runtime/OpenAPI/E2E 결과
- Produces: PR 설명에 그대로 옮길 수 있는 변경 범위·검증·보안 확인 결과

- [ ] **Step 1: 마스터 체크리스트를 실제 상태만 반영해 갱신한다.**

다음 항목만 상태와 PR 번호에 맞게 변경한다. F 섹션의 #224 항목과 권장 실행 순서의 #224 항목은 둘 다 완료 상태로 맞춘다.

```markdown
- [x] #224 채팅 세션 기반 역질문 상태 저장·서버 우선 복원 계약 — #224 / PR #225
- [x] #224 사건 메모리·역질문·채팅 세션 계약 / PR #225
- [~] 리포트 목록·상세·다운로드 API 계약 및 문서 E2E — #226
- [~] 리포트 API 계약 — #226
```

상태 표기 아래에 공통 PR 품질 게이트 7개를 추가한다. 완료되지 않은 다른 로드맵 항목의 상태나 문구는 변경하지 않는다.

- [ ] **Step 2: 변경 목록과 의도하지 않은 파일을 확인한다.**

Run:

```powershell
git -c safe.directory='D:/dev/project/SKN27-issue226-report-api' -C 'D:\dev\project\SKN27-issue226-report-api' diff --name-status origin/dev...
git -c safe.directory='D:/dev/project/SKN27-issue226-report-api' -C 'D:\dev\project\SKN27-issue226-report-api' diff --check
git -c safe.directory='D:/dev/project/SKN27-issue226-report-api' -C 'D:\dev\project\SKN27-issue226-report-api' status -sb
```

Expected: File Structure 표의 파일 외 변경이 없고, whitespace 오류 및 예상 밖의 untracked artifact가 없다.

- [ ] **Step 3: 단위·계약·Django 회귀 테스트를 실행한다.**

Run:

```powershell
& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' -m pytest -q test/test_report_query_service.py test/test_api_route_specs.py test/test_openapi_v1_generation.py
& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' backend/manage.py test chatbot.test_report_api_contract chatbot.test_supervisor_reporting_pipeline -v 1
& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' backend/manage.py test chatbot -v 1
```

Expected: 모두 성공하며, 새 HTTP E2E가 목록 → 상세 → PDF와 401/403/404/409을 직접 실행한다.

- [ ] **Step 4: 정적 검사·생성물·프런트엔드 빌드를 실행한다.**

Run:

```powershell
& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' -m ruff check --select E9,F63,F7,F82 .
& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' scripts/generate_openapi_v1.py --check
npm run build
```

Run the last command from `D:\dev\project\SKN27-issue226-report-api\app\web`.

Expected: lint, generated OpenAPI drift check, Vite production build가 모두 exit code 0으로 끝난다.

- [ ] **Step 5: 보안/권한 최종 검토와 사용자 Git handoff를 준비한다.**

아래 증거를 PR 설명에 기록한다.

```markdown
- 타 사용자 상세/다운로드는 PDF 렌더링 전 403 `object_access_denied`
- malformed/expired Bearer는 401 인증 오류와 `WWW-Authenticate`
- 익명 사용자는 403 `login_required`; 없는 리포트는 404; worker draft PDF는 409
- 상세 JSON과 PDF 응답 헤더에 `storage_uri`, 객체 키, object-storage metadata, request fingerprint가 없음
- `POST /api/reports/`는 여전히 deferred이며 409 `worker_report_action_required`
```

Expected: Agent는 Git을 변경하지 않고, 사용자에게 stage 대상 파일 목록·검증 명령 결과·PR 제목/본문 초안만 전달한다.

## Plan Self-Review

### Spec coverage

| 설계 요구 | 구현 Task |
| --- | --- |
| 공개 목록/상세 DTO 및 저장소 메타데이터 차단 | Task 1 |
| 뷰/서비스/저장소 책임 분리 | Task 1, Task 2 |
| 목록 → 상세 → PDF Django HTTP E2E | Task 2, Task 4 |
| 401/403/404/409 안전 오류와 권한 선검증 | Task 2, Task 3 |
| PDF 내부 저장소 헤더 제거 | Task 2 |
| 세 GET route OpenAPI 승격, POST deferred 유지 | Task 3 |
| JSON/PDF 공통 OpenAPI 생성 구조 | Task 3 |
| OpenAPI YAML 생성/검증 | Task 3, Task 4 |
| 체크리스트 및 필수 품질 게이트 | Task 4 |
| 신규 DB/생성 흐름/UI 재설계 배제 | Global Constraints, Task 2, Task 4 |

### Type consistency

- `ReportListResponse`와 `ReportDetailResponse`는 Task 1에서 정의하고 Task 3 route spec에서 동일 이름으로 소비한다.
- `compose_report_list_response`와 `compose_report_detail_response`는 Task 1에서 정의하고 Task 2 뷰에서 동일 이름으로 소비한다.
- `ResponseContentSpec`와 `ResponseHeaderSpec`은 Task 3의 `RouteSpec`과 `openapi_v1`에서 동일 이름으로 소비한다.
- 모든 public URL과 PDF 미디어 타입은 route spec에 한 번만 선언하고, 뷰는 저장소/응답 생성에만 사용한다.

### Placeholder review

이 계획에는 미결정 작업 표식, 추후 구현 지시, 모호한 오류 처리 지시가 없다. 체크박스는 실행 순서 표기이며 구현 미결정 사항이 아니다.
