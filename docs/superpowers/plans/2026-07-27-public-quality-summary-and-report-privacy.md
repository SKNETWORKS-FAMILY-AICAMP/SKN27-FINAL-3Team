# Public Quality Summary And Report Privacy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe public quality-summary contract that is shared by chat results and reports while preventing internal provenance, storage, debug, and implementation metadata from leaking to users.

**Architecture:** The server owns a new allowlist-based public quality projection. `law_ground_search` structured results are sanitized before they reach public DTOs, repository/report detail paths reuse the same safe quality shape, and the frontend reads only the public summary plus conditional limitations. Operator provenance stays on its existing private path. The incident-image feature is documented as out of scope and remains disabled.

**Tech Stack:** Python 3, Django repositories and service-layer projections, React/Vite frontend shell, pytest string-contract tests, PowerShell git workflow

## Global Constraints

- Include only user-response and report public quality information, legal freshness, retrieval limits, partial result state, and fallback status.
- Exclude operator provenance API removal or reduction.
- Exclude actual image generation provider integration, storage, moderation, and cost approval.
- Exclude report template redesign, OCR/Vision accuracy work, and live human deployment smoke.
- Always show a minimal public quality summary.
- Show detailed limitations only when `partial`, `blocked`, `failed`, `empty`, stale, fallback, or `limitations > 0`.
- Never expose raw query text, local paths, Python file names, `storage_uri`, `source_storage_uri`, signed URLs, bucket/key, SQL table names, raw `data_provenance`, embedding provider/model/dimensions, prompt version/hash, release/runtime version, raw exception text, stack traces, trace IDs, cookies, access tokens, or debug blobs in user-facing payloads or reports.
- Preserve operator provenance on its current private path.
- Keep incident-scene image insertion documented as currently unimplemented and explicitly out of the implementation scope.

---

## File Structure

- Modify: `app/services/agent_node_service.py`
  Builds the public-safe `law_ground_search` structured result and strips unsafe retrieval metadata before it reaches public consumers.
- Modify: `app/services/analysis_job_query_service.py`
  Projects only the new public quality summary and safe `law_ground_search` fields into completed analysis results.
- Modify: `backend/chatbot/repositories.py`
  Reuses the same allowlist rules for report detail and persistence payloads so report DTOs match chat DTO safety.
- Modify: `app/web/FrontendAppShell.jsx`
  Renders always-on minimal quality information and conditionally expanded limitations from the new public summary.
- Modify: `docs/ops/project-readiness-master-checklist.md`
  Updates `C` and `I` to distinguish public quality disclosure from operator provenance.
- Test: `test/test_analysis_job_query_service.py`
  Covers analysis result projection and user-facing filtering.
- Test: `test/test_law_ground_contract.py`
  Covers public-safe `law_ground_search` result shape and retrieval filtering.
- Test: `backend/chatbot/test_report_api_contract.py`
  Verifies report detail DTOs expose only public quality fields.
- Test: `backend/chatbot/test_supervisor_reporting_pipeline.py`
  Verifies report persistence strips private provenance-like metadata and keeps safe limitations only.
- Test: `backend/chatbot/test_analysis_job_provenance.py`
  Verifies operator provenance still contains private evidence on the operator-only path.
- Test: `test/test_frontend_report_api_contract.py`
  Verifies the frontend reads only public report detail fields.
- Test: `test/test_ui_v3_frontend_contract.py`
  Verifies the UI always shows a minimal quality summary and conditionally shows detailed limitations.

### Task 1: Sanitize `law_ground_search` For Public Results

**Files:**
- Modify: `app/services/agent_node_service.py`
- Modify: `app/services/analysis_job_query_service.py`
- Test: `test/test_law_ground_contract.py`
- Test: `test/test_analysis_job_query_service.py`

**Interfaces:**
- Consumes: existing `structured_result.retrieval`, `structured_result.matched_laws`, repository `agent_results`
- Produces: `structured_result.public_quality_summary: dict[str, Any] | None`
- Produces: `structured_result.retrieval` reduced to user-safe fields only
- Produces: `_project_public_quality_summary(value: Any) -> dict[str, Any] | None`
- Produces: `_project_public_law_ground_structured_result(value: Any) -> dict[str, Any]`

- [ ] **Step 1: Write the failing service tests**

```python
def test_completed_result_projects_only_safe_public_quality_summary() -> None:
    from app.services.analysis_job_query_service import load_analysis_result

    outcome = load_analysis_result(
        "job_quality",
        load_job=lambda _job_id: {
            "job_id": "job_quality",
            "status": "partial",
            "agent_results": [
                {
                    "node_code": "law_ground_search",
                    "status": "partial",
                    "structured_result": {
                        "matched_laws": [{"law_name": "Road Traffic Act", "source_reference": "law:1"}],
                        "retrieval": {
                            "status": "partial",
                            "backend": "postgres_pgvector",
                            "result_count": 1,
                            "retrieved_at": "2026-07-27T09:00:00+09:00",
                            "effective_at": "2026-07-20",
                            "query": "must-not-leak",
                            "embedding": {"model": "text-embedding-3-large"},
                            "sql_tables": ["law_embeddings"],
                        },
                        "public_quality_summary": {
                            "status": "partial",
                            "partial_result": True,
                            "review_required": True,
                            "freshness": {
                                "effective_at": "2026-07-20",
                                "retrieved_at": "2026-07-27T09:00:00+09:00",
                                "limitation": "Latest revision may not be reflected.",
                            },
                            "retrieval": {
                                "backend_label": "법령 근거 검색",
                                "result_count": 1,
                                "used_fallback": False,
                            },
                            "limitation_count": 1,
                            "limitations": ["Latest revision may not be reflected."],
                        },
                    },
                    "limitations": ["Latest revision may not be reflected."],
                }
            ],
        },
        compose_response=lambda _payload: {
            "contract_version": "analysis_result.v2",
            "job_id": "job_quality",
            "status": "partial",
        },
    )

    node = outcome.payload["supervisor_execution"]["node_results"][0]
    assert node["structured_result"]["public_quality_summary"]["retrieval"]["backend_label"] == "법령 근거 검색"
    assert "query" not in repr(node)
    assert "law_embeddings" not in repr(node)
    assert "text-embedding-3-large" not in repr(node)
```

```python
def test_law_ground_contract_excludes_private_retrieval_fields_from_public_metadata() -> None:
    from app.services.agent_node_service import _retrieval_metadata

    retrieval = _retrieval_metadata(
        {
            "status": "ready",
            "backend": "postgres_pgvector",
            "result_count": 2,
            "retrieved_at": "2026-07-27T09:00:00+09:00",
            "effective_at": "2026-07-20",
            "query": "private query",
            "embedding": {"model": "text-embedding-3-large"},
            "data_provenance": {"dataset_version": "sha256:private"},
            "sql_tables": ["law_embeddings"],
        }
    )

    assert retrieval == {
        "status": "ready",
        "backend": "postgres_pgvector",
        "result_count": 2,
        "retrieved_at": "2026-07-27T09:00:00+09:00",
        "effective_at": "2026-07-20",
    }
```

- [ ] **Step 2: Run the targeted tests to verify RED**

Run: `python -m pytest test/test_analysis_job_query_service.py test/test_law_ground_contract.py -q`

Expected: FAIL because the public quality summary and allowlist filtering do not exist yet.

- [ ] **Step 3: Implement the minimal server-side public quality projection**

```python
def _retrieval_metadata(rag_search: dict[str, Any]) -> dict[str, Any]:
    allowed_fields = (
        "contract_version",
        "status",
        "backend",
        "result_count",
        "retrieved_at",
        "effective_at",
        "error_code",
        "fallback_from",
        "attempted_backends",
    )
    return {field: rag_search.get(field) for field in allowed_fields if field in rag_search}


def _project_public_quality_summary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "status": value.get("status"),
        "partial_result": bool(value.get("partial_result")),
        "review_required": bool(value.get("review_required")),
        "freshness": _project_mapping(value.get("freshness"), ("effective_at", "retrieved_at", "limitation")),
        "retrieval": _project_mapping(value.get("retrieval"), ("backend_label", "result_count", "used_fallback")),
        "limitation_count": int(value.get("limitation_count") or 0),
        "limitations": list(value.get("limitations") or []),
    }
```

```python
def _project_public_law_ground_structured_result(value: Any) -> dict[str, Any]:
    structured = _project_mapping(value, ("matched_laws", "law_provisions", "freshness", "public_quality_summary"))
    retrieval = _project_mapping(_dict_or_empty(value).get("retrieval"), ("status", "backend", "result_count", "retrieved_at", "effective_at", "fallback_from", "attempted_backends"))
    if retrieval:
        structured["retrieval"] = retrieval
    return structured
```

- [ ] **Step 4: Run the targeted tests to verify GREEN**

Run: `python -m pytest test/test_analysis_job_query_service.py test/test_law_ground_contract.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/agent_node_service.py app/services/analysis_job_query_service.py test/test_analysis_job_query_service.py test/test_law_ground_contract.py
git commit -m "feat: add public law quality summary projection"
```

### Task 2: Reuse The Public Quality Contract In Report DTOs

**Files:**
- Modify: `backend/chatbot/repositories.py`
- Test: `backend/chatbot/test_report_api_contract.py`
- Test: `backend/chatbot/test_supervisor_reporting_pipeline.py`
- Test: `backend/chatbot/test_analysis_job_provenance.py`

**Interfaces:**
- Consumes: `Report.metadata.report_quality`, `Report.content.reporting_payload`, persisted worker payloads
- Produces: `_public_report_quality(value: dict[str, Any]) -> dict[str, Any]`
- Produces: `_public_reporting_payload(value: dict[str, Any]) -> dict[str, Any]`
- Produces: report detail responses that expose only safe quality fields
- Preserves: `get_analysis_job_provenance(job_id: str) -> dict[str, Any] | None` behavior

- [ ] **Step 1: Write the failing report DTO and provenance tests**

```python
def test_report_detail_exposes_only_public_quality_summary_fields(self) -> None:
    response = self.owner_client.get(f"/api/reports/{self.report.report_id}/")
    detail = response.json()["report"]

    quality = detail["metadata"]["report_quality"]
    assert quality["limitation_count"] == 1
    assert quality["limitations"] == ["Verify facts"]
    assert "agent_status_counts" not in quality
    assert "dataset_version" not in json.dumps(detail)
    assert "storage_uri" not in json.dumps(detail)
```

```python
def test_operator_provenance_keeps_private_dataset_and_embedding_details() -> None:
    result = get_analysis_job_provenance(self.job.job_id)

    assert result["retrievals"][0]["data_provenance"]["dataset_version"] == "sha256:verified-dataset"
    assert result["retrievals"][0]["embedding"]["model"] == "text-embedding-3-large"
```

- [ ] **Step 2: Run the targeted tests to verify RED**

Run: `python -m pytest backend/chatbot/test_report_api_contract.py backend/chatbot/test_supervisor_reporting_pipeline.py backend/chatbot/test_analysis_job_provenance.py -q`

Expected: FAIL because report detail still exposes broader `report_quality` content than the new public contract allows.

- [ ] **Step 3: Implement minimal repository allowlist projections**

```python
def _public_report_quality(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": _text(value.get("contract_version")) or "report_quality.v2",
        "partial_report": bool(value.get("partial_report")),
        "review_required": bool(value.get("review_required")),
        "limitation_count": int(value.get("limitation_count") or 0),
        "limitations": _safe_public_limitations(value.get("limitations")),
        "confidence_label": _text(value.get("confidence_label")) or None,
        "public_quality_summary": _public_quality_summary(value.get("public_quality_summary")),
    }
```

```python
def _public_reporting_payload(value: dict[str, Any]) -> dict[str, Any]:
    payload = _project_mapping(value, _REPORTING_PAYLOAD_FIELDS)
    if isinstance(payload.get("sections"), list):
        payload["sections"] = [_public_report_section(section) for section in payload["sections"] if isinstance(section, dict)]
    return payload
```

- [ ] **Step 4: Run the targeted tests to verify GREEN**

Run: `python -m pytest backend/chatbot/test_report_api_contract.py backend/chatbot/test_supervisor_reporting_pipeline.py backend/chatbot/test_analysis_job_provenance.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/chatbot/repositories.py backend/chatbot/test_report_api_contract.py backend/chatbot/test_supervisor_reporting_pipeline.py backend/chatbot/test_analysis_job_provenance.py
git commit -m "feat: reuse public quality summary in report dto"
```

### Task 3: Update The Frontend To Consume Only Public Quality Fields

**Files:**
- Modify: `app/web/FrontendAppShell.jsx`
- Test: `test/test_frontend_report_api_contract.py`
- Test: `test/test_ui_v3_frontend_contract.py`

**Interfaces:**
- Consumes: `node.structured_result.public_quality_summary`
- Consumes: `currentReport.metadata.report_quality.public_quality_summary` or equivalent safe report quality payload
- Produces: always-on minimal quality badges and timestamps
- Produces: conditional expanded limitations and fallback warnings

- [ ] **Step 1: Write the failing frontend contract tests**

```python
def test_frontend_report_views_consume_public_quality_summary_only() -> None:
    shell = (ROOT / "app" / "web" / "FrontendAppShell.jsx").read_text(encoding="utf-8")

    assert "public_quality_summary" in shell
    assert "reportQuality?.public_quality_summary" in shell
    assert "retrieval.embedding" not in shell
    assert "data_provenance" not in shell
```

```python
def test_result_screen_always_shows_minimum_quality_summary_and_conditionally_expands_limitations() -> None:
    shell = _shell()

    assert "qualitySummary?.freshness?.effective_at" in shell
    assert "qualitySummary?.freshness?.retrieved_at" in shell
    assert "qualitySummary?.limitation_count" in shell
    assert "shouldShowQualityDetails" in shell
```

- [ ] **Step 2: Run the targeted tests to verify RED**

Run: `python -m pytest test/test_frontend_report_api_contract.py test/test_ui_v3_frontend_contract.py -q`

Expected: FAIL because the frontend still reads raw `retrieval` and plain `report_quality` fields directly.

- [ ] **Step 3: Implement the minimal frontend quality-summary rendering**

```jsx
const qualitySummary = structuredResult.public_quality_summary || null;
const shouldShowQualityDetails =
  qualitySummary?.partial_result ||
  qualitySummary?.review_required ||
  ["partial", "blocked", "failed", "empty"].includes(String(qualitySummary?.status || "").toLowerCase()) ||
  (qualitySummary?.limitation_count || 0) > 0 ||
  qualitySummary?.freshness?.limitation;
```

```jsx
const reportQualitySummary =
  reportQuality?.public_quality_summary ||
  null;

{reportQualitySummary?.freshness?.effective_at && (
  <span className="tag">기준일 {formatDate(reportQualitySummary.freshness.effective_at)}</span>
)}
```

- [ ] **Step 4: Run the targeted tests to verify GREEN**

Run: `python -m pytest test/test_frontend_report_api_contract.py test/test_ui_v3_frontend_contract.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/web/FrontendAppShell.jsx test/test_frontend_report_api_contract.py test/test_ui_v3_frontend_contract.py
git commit -m "feat: render public quality summary in frontend"
```

### Task 4: Update Checklist And Run Final Regression For This Scope

**Files:**
- Modify: `docs/ops/project-readiness-master-checklist.md`
- Test: `test/test_analysis_job_query_service.py`
- Test: `test/test_law_ground_contract.py`
- Test: `backend/chatbot/test_report_api_contract.py`
- Test: `backend/chatbot/test_supervisor_reporting_pipeline.py`
- Test: `backend/chatbot/test_analysis_job_provenance.py`
- Test: `test/test_frontend_report_api_contract.py`
- Test: `test/test_ui_v3_frontend_contract.py`

**Interfaces:**
- Consumes: the completed public quality summary contract from Tasks 1-3
- Produces: updated checklist language for `C` and `I`
- Produces: final regression evidence for the public quality + privacy boundary scope

- [ ] **Step 1: Write the failing checklist-facing regression assertions**

```python
def test_frontend_report_views_consume_public_quality_summary_only() -> None:
    shell = (ROOT / "app" / "web" / "FrontendAppShell.jsx").read_text(encoding="utf-8")
    assert "public_quality_summary" in shell
```

```python
def test_owner_reads_strict_public_list_and_detail_contracts(self) -> None:
    detail = self.owner_client.get(f"/api/reports/{self.report.report_id}/").json()["report"]
    assert "storage_uri" not in json.dumps(detail, sort_keys=True)
    assert "dataset_version" not in json.dumps(detail, sort_keys=True)
```

- [ ] **Step 2: Run the full scoped regression set**

Run:

```bash
python -m pytest test/test_analysis_job_query_service.py test/test_law_ground_contract.py backend/chatbot/test_report_api_contract.py backend/chatbot/test_supervisor_reporting_pipeline.py backend/chatbot/test_analysis_job_provenance.py test/test_frontend_report_api_contract.py test/test_ui_v3_frontend_contract.py -q
```

Expected: PASS after Tasks 1-3 are complete. If any failure remains, fix production code before editing docs.

- [ ] **Step 3: Update the master checklist wording**

```markdown
- [x] 사용자 결과에 기준일과 최신성 제한사항 표시 — 공개 품질 요약 계약으로 기준일·조회 시각·최신성 제한을 안전한 범위에서 노출한다.
- [~] 사용자 응답/리포트에 보이는 공개 품질 정보 — operator provenance와 분리된 공개 DTO, 내부 메타데이터 비노출, 조건부 상세 제한 노출까지 구현. live 사람 smoke는 남음.
```

- [ ] **Step 4: Re-run the scoped regression set after the checklist edit**

Run:

```bash
python -m pytest test/test_analysis_job_query_service.py test/test_law_ground_contract.py backend/chatbot/test_report_api_contract.py backend/chatbot/test_supervisor_reporting_pipeline.py backend/chatbot/test_analysis_job_provenance.py test/test_frontend_report_api_contract.py test/test_ui_v3_frontend_contract.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/ops/project-readiness-master-checklist.md
git add test/test_analysis_job_query_service.py test/test_law_ground_contract.py
git add backend/chatbot/test_report_api_contract.py backend/chatbot/test_supervisor_reporting_pipeline.py backend/chatbot/test_analysis_job_provenance.py
git add test/test_frontend_report_api_contract.py test/test_ui_v3_frontend_contract.py
git commit -m "docs: record public quality summary readiness"
```

## Plan Self-Review

### Spec coverage

- Public quality summary contract: Task 1 and Task 2
- User-facing allowlist and private-field stripping: Task 1 and Task 2
- Shared chat/report rendering semantics: Task 3
- Checklist update for `C` and `I`: Task 4
- Incident-image scope held out as unimplemented: covered by scope constraints and no implementation tasks added

### Placeholder scan

- No `TODO`, `TBD`, or “implement later” placeholders remain.
- Each task includes exact files, interfaces, tests, commands, and commit messages.

### Type consistency

- `public_quality_summary` is the same field name across service, repository, frontend, and tests.
- `partial_result`, `review_required`, `limitation_count`, `limitations`, `freshness`, and `retrieval` are reused consistently across tasks.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-27-public-quality-summary-and-report-privacy.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
