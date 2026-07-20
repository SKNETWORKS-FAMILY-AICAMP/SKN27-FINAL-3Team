# DOCX 전용 문서 다운로드 통합 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** fine_notice, traffic_accident, 일반 분석 리포트의 사용자 문서 다운로드를 호환 가능한 DOCX 전용 계약으로 통합한다.

**Architecture:** 보고서 생성 에이전트는 `document_variant`, `form_data`, `document_readiness`, `appeal_decision`을 계속 생산한다. 새 DOCX 렌더러는 이 공개 구조만 받아 문서 유형별 바이트를 만들고, 저장소/다운로드 계층은 하나의 DOCX MIME·파일명 계약으로 제공한다. fine_notice LLM 초안은 최소화·마스킹된 입력만 사용하며 실패하면 규칙 기반 문구로 내려간다.

**Tech Stack:** Python 3.13, Django, Pydantic, python-docx, OpenAI SDK(선택), pytest, React.

## Global Constraints

- 기준 브랜치는 `origin/dev`의 `8c7006f`이며 기존 `issue/objection-report-generation`은 읽기 전용 참고 구현이다.
- 기존 `document_variant`와 `traffic_accident.form_data`의 의미를 바꾸지 않는다.
- 새 응답 필드는 기존 클라이언트가 무시할 수 있도록 선택적으로 추가한다.
- `denied`, `not_applicable`, `deadline_passed`는 UI뿐 아니라 서버 다운로드 경계에서도 차단한다.
- LLM에는 마스킹·길이 제한을 마친 신청취지/신청이유 작성용 최소 사실만 전달한다.
- PDF 코드는 사용자 다운로드 DOCX 경로가 테스트로 검증된 뒤, 실제 의존성이 없는 부분만 제거한다.

---

## 파일 구조

- `ai/agents/objection_report_generation/agent.py`: fine_notice LLM/폴백, 문서 액션, appeal gate와 호환 구조화 결과를 만든다.
- `ai/agents/objection_report_generation/docx_renderer.py`: 공식 과태료 양식, 교통사고 양식, 일반 리포트의 DOCX 바이트를 렌더링한다.
- `backend/chatbot/repositories.py`: `Report`와 공개 reporting payload를 DOCX 다운로드 메타데이터로 변환한다.
- `backend/chatbot/views.py`: 권한·ready 상태·appeal gate를 확인한 뒤 DOCX만 반환한다.
- `app/web/FrontendAppShell.jsx`: 차단된 문서 액션을 실행하지 않고 DOCX 문구를 표시한다.
- `requirements.txt`: 배포 환경의 `python-docx` 의존성을 선언한다.
- `test/test_agent_node_service.py`, `backend/chatbot/test_supervisor_reporting_pipeline.py`, `backend/chatbot/test_report_api_contract.py`, `test/test_consultation_v2_contract.py`: 생성·다운로드·UI 계약의 회귀를 검증한다.
- `docs/ops/project-readiness-master-checklist.md`: 이슈 #238의 진행 상태를 `[~]`로 기록한다.

## Task 1: 체크리스트와 DOCX 공개 계약의 실패 테스트

**Files:**
- Modify: `docs/ops/project-readiness-master-checklist.md`
- Modify: `test/test_agent_node_service.py`
- Modify: `backend/chatbot/test_report_api_contract.py`

**Interfaces:**
- Consumes: `run_objection_report_generation(agent_input, context) -> dict[str, Any]`
- Produces: `structured_result["report_actions"]`의 DOCX 전용 action과 `structured_result["readiness"]`의 차단 상태.

- [ ] **Step 1: 진행 항목을 `[~]`로 기록한다.**

```md
- [~] DOCX 전용 한글 렌더링, 개인정보 마스킹, 권한 검증 및 PDF 사용자 다운로드 제거 — #238
- [~] fine_notice·traffic_accident·일반 분석 리포트의 문서별 DOCX 다운로드와 appeal gate E2E — #238
```

- [ ] **Step 2: fine_notice action과 gate의 기대 동작을 먼저 테스트한다.**

```python
def test_fine_notice_actions_are_docx_only_and_blocked_when_deadline_passed():
    output = run_objection_report_generation(_fine_notice_input(deadline_passed=True), _node_context())
    result = output["structured_result"]

    assert result["readiness"]["ready_for_download"] is False
    assert result["report_actions"] == []


def test_fine_notice_actions_offer_docx_when_the_appeal_gate_allows_download():
    output = run_objection_report_generation(_fine_notice_input(deadline_passed=False), _node_context())

    assert {action["type"] for action in output["structured_result"]["report_actions"]} == {
        "download_objection",
        "download_report",
        "copy_objection_draft",
    }
    assert all("PDF" not in action["label"] for action in output["structured_result"]["report_actions"])
    assert {action["document_format"] for action in output["structured_result"]["report_actions"] if action["type"].startswith("download_")} == {"docx"}
```

- [ ] **Step 3: 실행하여 현재 PDF/미차단 구현에서 실패하는지 확인한다.**

Run: `python -m pytest -q test/test_agent_node_service.py -k "docx_only or deadline_passed"`

Expected: action 라벨 또는 `document_format`/gate 기대값에서 FAIL.

- [ ] **Step 4: 최소 계약 구현 후 같은 테스트를 통과시킨다.**

```python
def _download_action(action_type: str, label: str, document_type: str) -> dict[str, str]:
    return {
        "type": action_type,
        "label": label,
        "document_type": document_type,
        "document_format": "docx",
    }
```

- [ ] **Step 5: 대상 테스트를 다시 실행한다.**

Run: `python -m pytest -q test/test_agent_node_service.py -k "docx_only or deadline_passed"`

Expected: PASS.

## Task 2: fine_notice 최소정보 LLM 초안과 규칙 기반 폴백

**Files:**
- Modify: `ai/agents/objection_report_generation/agent.py`
- Modify: `test/test_agent_node_service.py`

**Interfaces:**
- Consumes: fine notice의 구조화 결과와 `appeal_decision`.
- Produces: `petition_purpose`, `petition_reason`, `drafting_source` 및 fine_notice용 `form_data`.

- [ ] **Step 1: LLM 입력 마스킹과 폴백의 실패 테스트를 작성한다.**

```python
def test_fine_notice_draft_masks_contact_and_uses_rule_fallback_when_llm_is_unavailable(monkeypatch):
    monkeypatch.setattr(objection_agent, "_openai_client", lambda: None)
    output = run_objection_report_generation(_fine_notice_input(contact="010-1234-5678"), _node_context())
    result = output["structured_result"]

    assert result["drafting_source"] == "rule_based_fallback"
    assert result["petition_purpose"]
    assert result["petition_reason"]


def test_fine_notice_llm_request_excludes_contact_and_unneeded_identity(monkeypatch):
    captured = []
    monkeypatch.setattr(objection_agent, "_openai_client", lambda: _capturing_openai_client(captured))

    run_objection_report_generation(_fine_notice_input(contact="010-1234-5678"), _node_context())

    assert captured
    assert "010-1234-5678" not in captured[0]
    assert "주민등록번호" not in captured[0]
```

- [ ] **Step 2: 실패를 확인한다.**

Run: `python -m pytest -q test/test_agent_node_service.py -k "masks_contact or rule_fallback"`

Expected: 새 fine_notice 필드 또는 LLM 경계가 없어 FAIL.

- [ ] **Step 3: 최소화 입력과 폴백을 구현한다.**

```python
def _petition_prompt_payload(*, disposition_details, legal_grounds, user_facts, missing_fields, appeal_decision):
    return {
        "disposition_details": sanitize_pii(disposition_details),
        "legal_grounds": sanitize_pii(legal_grounds),
        "user_facts": _shorten(sanitize_pii(user_facts), 600),
        "missing_fields": list(missing_fields),
        "appeal_decision": {
            "merit": appeal_decision.get("merit"),
            "merit_relief_type": appeal_decision.get("merit_relief_type"),
        },
    }
```

- [ ] **Step 4: 새 테스트와 기존 objection agent 테스트를 실행한다.**

Run: `python -m pytest -q test/test_agent_node_service.py test/test_supervisor_reporting_handoff_service.py`

Expected: PASS.

## Task 3: 문서 유형별 DOCX 렌더링과 다운로드 메타데이터

**Files:**
- Create: `ai/agents/objection_report_generation/docx_renderer.py`
- Modify: `backend/chatbot/repositories.py`
- Modify: `requirements.txt`
- Modify: `backend/chatbot/test_supervisor_reporting_pipeline.py`

**Interfaces:**
- Consumes: `reporting_payload.document_variant`, `form_data`, `form_sections`, `petition_purpose`, `petition_reason`.
- Produces: `build_report_download_docx_body(report: Report, document_type: str) -> bytes` and metadata with DOCX MIME type.

- [ ] **Step 1: 일반·fine_notice·traffic_accident 다운로드가 DOCX임을 검증하는 실패 테스트를 작성한다.**

```python
def test_report_download_returns_docx_for_every_supported_document_variant(client, report_factory):
    for variant in ("general", "fine_notice", "traffic_accident"):
        report = report_factory(document_variant=variant)
        response = client.get(f"/api/reports/{report.report_id}/download/?document_type=report", **_owner_headers(report))

        assert response.status_code == 200
        assert response["Content-Type"].startswith("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        assert response["Content-Disposition"].endswith('.docx"')
        assert response.content[:2] == b"PK"
```

- [ ] **Step 2: 실패를 확인한다.**

Run: `python -m pytest -q backend/chatbot/test_supervisor_reporting_pipeline.py -k "docx_for_every"`

Expected: 현재 `application/pdf`와 `.pdf` 파일명 때문에 FAIL.

- [ ] **Step 3: 문서별 DOCX 렌더러와 저장소 메타데이터를 구현한다.**

```python
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

def build_report_download_docx_body(*, report_id: str, title: str, document_variant: str, payload: dict[str, Any]) -> bytes:
    document = Document()
    if document_variant == "traffic_accident":
        _render_traffic_accident_form(document, payload.get("form_data") or {})
    elif document_variant == "fine_notice":
        _render_fine_notice_form(document, payload)
    else:
        _render_general_report(document, title=title, sections=payload.get("sections") or [])
    return _save_to_bytes(document)
```

- [ ] **Step 4: `python-docx`를 배포 의존성으로 선언한다.**

```text
python-docx>=1.1,<2
```

- [ ] **Step 5: DOCX 다운로드 테스트를 다시 실행한다.**

Run: `python -m pytest -q backend/chatbot/test_supervisor_reporting_pipeline.py -k "docx_for_every"`

Expected: PASS.

## Task 4: 서버·UI appeal gate와 PDF 사용자 경로 제거

**Files:**
- Modify: `backend/chatbot/views.py`
- Modify: `backend/chatbot/repositories.py`
- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `backend/chatbot/test_supervisor_reporting_pipeline.py`
- Modify: `test/test_consultation_v2_contract.py`

**Interfaces:**
- Consumes: 보고서 `content.reporting_payload.document_readiness`와 `appeal_decision`.
- Produces: gate 차단 시 JSON `409` 또는 UI 비활성 상태, 허용 시 DOCX만 반환.

- [ ] **Step 1: 백엔드와 UI 양쪽의 차단 실패 테스트를 작성한다.**

```python
def test_download_rejects_denied_not_applicable_and_deadline_passed_reports(client, report_factory):
    for decision in ({"judgment_status": "denied"}, {"judgment_status": "not_applicable"}, {"deadline_passed": True}):
        report = report_factory(appeal_decision=decision)
        response = client.get(f"/api/reports/{report.report_id}/download/", **_owner_headers(report))

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "report_not_ready"
```

```python
def test_report_actions_do_not_offer_pdf_or_download_when_the_appeal_gate_blocks():
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")
    assert 'action.document_format === "docx"' in shell
    assert "appeal_gate" in shell
    assert "PDF 다운로드" not in shell
```

- [ ] **Step 2: 실패를 확인한다.**

Run: `python -m pytest -q backend/chatbot/test_supervisor_reporting_pipeline.py test/test_consultation_v2_contract.py -k "rejects_denied or do_not_offer_pdf"`

Expected: gate가 서버에서 통과하거나 PDF 문구가 남아 FAIL.

- [ ] **Step 3: 다운로드 전 공통 gate를 구현하고 UI 액션을 동일 정책으로 제한한다.**

```python
def report_download_block_reason(report: Report) -> str | None:
    decision = _reporting_payload(report).get("appeal_decision") or {}
    if decision.get("judgment_status") in {"denied", "not_applicable"} or decision.get("deadline_passed") is True:
        return "appeal_gate_blocked"
    return None
```

```jsx
const isDocxDownload = action.document_format === "docx";
const isBlocked = report?.content?.reporting_payload?.appeal_gate?.blocked === true;
if (!isDocxDownload || isBlocked) return;
```

- [ ] **Step 4: 대상 테스트를 다시 실행한다.**

Run: `python -m pytest -q backend/chatbot/test_supervisor_reporting_pipeline.py test/test_consultation_v2_contract.py -k "rejects_denied or do_not_offer_pdf"`

Expected: PASS.

## Task 5: 호환성 회귀 검증과 정리

**Files:**
- Modify only if confirmed unused: `backend/chatbot/pdf_report_renderer.py`, `backend/chatbot/pdf_template_renderer.py`, PDF helper imports.
- Test: `test/test_agent_node_service.py`, `backend/chatbot/test_report_api_contract.py`, `backend/chatbot/test_supervisor_reporting_pipeline.py`, `test/test_consultation_v2_contract.py`.

**Interfaces:**
- Preserves: `ReportDetailResponse`, 리포트 목록/상세 권한 계약, `document_variant`, `form_data`.
- Produces: PDF 사용자 경로가 없는 DOCX 전용 다운로드 및 검증 기록.

- [ ] **Step 1: PDF helper의 실제 호출 지점을 검사하고, 사용자 다운로드에만 연결된 코드를 목록화한다.**

Run: `rg -n "build_report_download_pdf_body|_report_objection_form_pdf_body|pdf_report_renderer|pdf_template_renderer|application/pdf" ai app backend test`

Expected: 각 일치 항목을 보존·교체·삭제 중 하나로 분류.

- [ ] **Step 2: 전체 관련 테스트를 실행한다.**

Run: `python -m pytest -q test/test_agent_node_service.py test/test_supervisor_reporting_handoff_service.py backend/chatbot/test_report_api_contract.py backend/chatbot/test_supervisor_reporting_pipeline.py test/test_consultation_v2_contract.py --timeout=30 -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 3: 전체 테스트와 정적 검사를 실행한다.**

Run: `python -m pytest -q --timeout=30 -p no:cacheprovider --basetemp .pytest-tmp-issue238-full`

Expected: PASS 또는 기존과 독립적인 실패를 분리·보고.

Run: `D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\ruff.exe check ai/agents/objection_report_generation backend/chatbot/repositories.py backend/chatbot/views.py test/test_agent_node_service.py backend/chatbot/test_supervisor_reporting_pipeline.py --select E9,F63,F7,F82`

Expected: `All checks passed!`.

- [ ] **Step 4: 공백 오류와 변경 범위를 검토한다.**

Run: `git diff --check`

Expected: 출력 없음.

Run: `git status -sb`

Expected: #238에 속하는 코드·테스트·체크리스트·계획 파일만 표시.

- [ ] **Step 5: 검증 증거를 확인한 뒤 하나의 의도적인 커밋으로 기록한다.**

```bash
git add ai/agents/objection_report_generation backend/chatbot app/web/FrontendAppShell.jsx requirements.txt test backend/chatbot/test_supervisor_reporting_pipeline.py docs/ops/project-readiness-master-checklist.md docs/superpowers/plans/2026-07-19-docx-download-unification.md
git commit -m "feat: unify document downloads as DOCX"
git push -u origin feat/238-docx-download-unification
```

## Plan Self-Review

- Spec coverage: 문서 variant 유지(Task 3), fine_notice LLM·폴백·마스킹(Task 2), 세 DOCX 경로(Task 3), PDF 사용자 경로 제거(Task 4·5), appeal gate(Task 1·4), 응답 호환성(Task 1·5), 체크리스트(Task 1)를 모두 포함한다.
- Placeholder scan: 각 작업에 파일, 인터페이스, 실패 테스트, 실행 명령, 최소 구현 또는 검증 기준을 명시했다.
- Type consistency: `document_variant`, `form_data`, `report_actions`, `document_format`, `appeal_decision`은 생성 에이전트→reporting payload→저장소→뷰→프런트엔드에서 같은 이름으로 전달한다.
