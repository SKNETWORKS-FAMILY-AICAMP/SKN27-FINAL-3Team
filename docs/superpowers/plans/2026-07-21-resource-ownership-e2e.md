# 세션·분석·첨부파일·리포트 소유권 E2E 검증 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 한 사용자의 세션에서 생성된 분석 Job·첨부파일·Worker Report·DOCX 문서는 소유자만 조회·변경·다운로드할 수 있고, 다른 인증 사용자는 모든 API 경계에서 안전한 `403 object_access_denied`만 받음을 자동 회귀 테스트로 고정한다.

**Architecture:** 새 Django `TestCase` 하나가 실제 인증 미들웨어, URL 라우팅, 뷰 권한 검사, DB 저장소, in-process Worker를 함께 통과시킨다. Supervisor와 개별 Agent adapter만 결정적 fixture로 대체하고, 외부 LLM·OCR·S3·별도 Worker 프로세스는 호출하지 않는다. 특정 work item ID를 `process_agent_work_item()`으로 처리해 앞선 채팅 work item과 실행 순서가 섞이지 않게 하며, owner와 attacker의 HTTP 결과를 같은 리소스 ID 집합으로 비교한다.

**Tech Stack:** Python 3.13+, Django `TestCase`/`Client`, unittest `patch`, PostgreSQL-compatible Django test DB, existing JWT test token helper, python-docx download renderer.

## Global Constraints

- 기준은 Issue #254 설계 문서 `docs/superpowers/specs/2026-07-20-resource-ownership-e2e-design.md`이며, 기존 `origin/dev` 응답 계약을 변경하지 않는다.
- 허용된 정상 다운로드는 `GET /api/reports/{report_id}/download/?document_type=objection_form`의 DOCX뿐이다. PDF를 새로 노출하거나 검증하지 않는다.
- 비소유자 응답은 모든 대상 경로에서 HTTP `403`, `error.code == "object_access_denied"`를 유지한다. 리소스 존재를 숨기는 `404`로 바꾸지 않는다.
- 비소유자 응답에는 owner ID, attachment/report의 storage URI·bucket·key·파일 경로, report 본문·요약, Worker 메타데이터·fingerprint, `Content-Disposition`, DOCX 바이트가 포함되면 안 된다. 공격자가 직접 보낸 ID 문자열은 예외다.
- 테스트는 실제 JWT 인증, URL 라우팅, view authorization, repository persistence, `process_agent_work_item(work_item_id)`를 사용한다. deterministic patch 대상은 `chatbot.views.submit_message`와 각 Agent adapter뿐이다.
- 외부 LLM, OCR, S3, 실제 별도 Worker 프로세스, 인증 provider 변경, DB 스키마/RLS 변경은 범위 밖이다.
- 테스트가 기존 권한 결함을 재현할 때만 `backend/chatbot/views.py` 또는 `backend/chatbot/repositories.py`를 최소 변경한다. 테스트를 맞추기 위한 계약 완화는 금지한다.
- 체크리스트는 별도 PR을 만들지 않는다. 구현 PR 링크와 CI 성공 결과를 받은 뒤, 같은 구현 브랜치에서만 `project-readiness-master-checklist.md`를 갱신한다.

---

## File Structure

- Create: `backend/chatbot/test_resource_ownership_e2e.py` — JWT owner/attacker client, deterministic supervisor/agent fixture, owner lifecycle, non-owner denial 및 비노출 assertion을 모은 회귀 테스트.
- Create: `docs/superpowers/plans/2026-07-21-resource-ownership-e2e.md` — 이 구현 계획과 검증·체크리스트 반영 조건.
- Modify only if a red test proves an authorization defect: `backend/chatbot/views.py` 또는 `backend/chatbot/repositories.py` — 기존 `authorize_resource_access()` 및 safe error 계약을 재사용하는 최소 수정.

### Task A: 소유권 E2E 테스트 기반과 공통 안전 assertion 추가

**Files:**

- Create: `backend/chatbot/test_resource_ownership_e2e.py`
- Reference: `backend/chatbot/test_analysis_job_queue.py`의 `_authenticated_client()`, `_server_authoritative_chat_response()` 패턴
- Reference: `backend/chatbot/test_report_api_contract.py`의 document confirmation 및 다운로드 header assertion

**Interfaces:**

- Consumes: `issue_access_token(user_id, auth_session_id, issued_at, expires_at) -> tuple[str, dict]`, Django `Client`, `AuthSession`, `UserAccount`.
- Produces: `_authenticated_client(user_id: str) -> Client`, `_assert_object_access_denied(testcase, response, supplied_ids: tuple[str, ...]) -> None`, `ResourceOwnershipE2ETests(TestCase)`.

- [ ] **Step 1: 새 테스트 파일에 JWT 인증 client와 비노출 assertion을 작성한다.**

```python
from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.services.google_auth_service import issue_access_token
from chatbot.models import (
    AgentWorkItem,
    AuthSession,
    AuthSessionStatus,
    ChatSession,
    ChatSessionStatus,
    UploadedFile,
    UploadedFileStatus,
    UserAccount,
)
from chatbot.repositories import process_agent_work_item


TEST_JWT_SIGNING_KEY = "resource-ownership-e2e-test-signing-key-is-long-enough"


def _authenticated_client(user_id: str) -> Client:
    issued_at = timezone.now()
    expires_at = issued_at + timedelta(hours=1)
    auth_session_id = f"auth_{user_id}"
    token, _claims = issue_access_token(
        user_id=user_id,
        auth_session_id=auth_session_id,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    user, _created = UserAccount.objects.get_or_create(user_id=user_id)
    AuthSession.objects.update_or_create(
        auth_session_id=auth_session_id,
        defaults={
            "user": user,
            "subject_type": "user",
            "subject_id": f"user:{user_id}",
            "status": AuthSessionStatus.ACTIVE,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "revoked_at": None,
        },
    )
    return Client(HTTP_AUTHORIZATION=f"Bearer {token}")


def _assert_object_access_denied(
    testcase: TestCase,
    response,
    *,
    owner_id: str,
    forbidden_fragments: tuple[str, ...],
) -> None:
    testcase.assertEqual(response.status_code, 403, response.content)
    body = response.json()
    testcase.assertEqual(body["error"]["code"], "object_access_denied")
    rendered = json.dumps(body, sort_keys=True)
    testcase.assertNotIn(owner_id, rendered)
    for fragment in forbidden_fragments:
        testcase.assertNotIn(fragment, rendered)
    testcase.assertNotIn("Content-Disposition", response.headers)
    testcase.assertNotEqual(
        response.headers.get("Content-Type"),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    testcase.assertFalse(response.content.startswith(b"PK"))
```

- [ ] **Step 2: 기반 파일이 초기에는 없어야 하므로 test discovery가 실패함을 확인한다.**

Run: `& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' -m pytest -q --timeout=30 backend/chatbot/test_resource_ownership_e2e.py`

Expected: test file not found 또는 수집할 테스트가 없다는 실패. 이 실패는 새 회귀 범위가 아직 구현되지 않았음을 뜻한다.

- [ ] **Step 3: 공통 fixture가 비밀값을 포함하지 않는지 확인한다.**

```python
class ResourceOwnershipE2ETests(TestCase):
    def setUp(self) -> None:
        self.owner_id = "usr_resource_owner"
        self.attacker_id = "usr_resource_attacker"
        self.owner_client = _authenticated_client(self.owner_id)
        self.attacker_client = _authenticated_client(self.attacker_id)
        self.private_fragments = (
            "s3://private-bucket",
            "private-bucket",
            "reports/owner.docx",
            "worker-private-fingerprint",
            "Owner-only report body",
        )
```

The fixture values intentionally make accidental leakage observable; no actual credential, local path, customer PII, OCR result, or remote storage call is used.

- [ ] **Step 4: 공통 helper가 있는 상태로 module collection을 통과시킨다.**

Run: `& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' -m pytest -q --timeout=30 backend/chatbot/test_resource_ownership_e2e.py`

Expected: collection succeeds; the fixture-only file reports no failing tests.

- [ ] **Step 5: 기반 작업을 커밋한다.**

```powershell
git add backend/chatbot/test_resource_ownership_e2e.py
git commit -m "test: add resource ownership e2e harness"
```

### Task B: 실제 owner API·Worker·DOCX 정상 경로를 하나의 테스트로 고정

**Files:**

- Modify: `backend/chatbot/test_resource_ownership_e2e.py`
- Reference: `backend/chatbot/test_supervisor_conversation_runtime_smoke.py`의 report-ready supervisor fixture와 Agent adapter patch pattern
- Reference: `backend/chatbot/test_supervisor_reporting_pipeline.py`의 `process_agent_work_item()` report persistence assertion

**Interfaces:**

- Consumes: `POST /api/chat/messages/`, `POST /api/analysis/jobs/`, `GET /api/analysis/jobs/{job_id}/`, `GET /api/analysis/results/{job_id}/`, `GET /api/files/{attachment_id}/`, `GET /api/reports/{report_id}/`, `POST /api/reports/{report_id}/document-confirmation/`, `GET /api/reports/{report_id}/download/?document_type=objection_form`.
- Produces: `test_owner_can_complete_bound_resource_lifecycle_and_download_docx() -> None`.

- [ ] **Step 1: 정상 owner lifecycle을 먼저 failing test로 작성한다.**

```python
def test_owner_can_complete_bound_resource_lifecycle_and_download_docx(self) -> None:
    session_id = "ses_resource_owner"
    attachment_id = "att_resource_owner"
    job_id = "job_resource_owner"

    with patch("chatbot.views.submit_message", side_effect=_fixture_submit_message):
        chat = self.owner_client.post(
            "/api/chat/messages/",
            data={"session_id": session_id, "user_text": "Create owner-bound session."},
            content_type="application/json",
        )
        accepted = self.owner_client.post(
            "/api/analysis/jobs/",
            data={"job_id": job_id, "session_id": session_id, "user_text": "Prepare official objection."},
            content_type="application/json",
        )
    self.assertEqual(chat.status_code, 202, chat.content)
    self.assertEqual(accepted.status_code, 202, accepted.content)
    work_item = AgentWorkItem.objects.get(job__job_id=job_id)

    with _patched_report_ready_agents():
        processed = process_agent_work_item(work_item.work_item_id)

    self.assertEqual(processed["status"], "success")
    job_detail = self.owner_client.get(f"/api/analysis/jobs/{job_id}/")
    job_result = self.owner_client.get(f"/api/analysis/results/{job_id}/")
    self.assertEqual(job_detail.status_code, 200, job_detail.content)
    self.assertEqual(job_result.status_code, 200, job_result.content)
```

- [ ] **Step 2: 위 테스트를 실행해 report-ready deterministic fixture가 아직 없어 실패하는지 확인한다.**

Run: `& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' -m pytest -q --timeout=30 backend/chatbot/test_resource_ownership_e2e.py::ResourceOwnershipE2ETests::test_owner_can_complete_bound_resource_lifecycle_and_download_docx`

Expected: FAIL because `_patched_report_ready_agents()` and the canonical report-ready response are not yet defined, or because no Report has been persisted.

- [ ] **Step 3: report-ready supervisor response와 deterministic adapter patches를 추가한다.**

```python
def _fixture_submit_message(payload: dict, **_kwargs) -> dict:
    session_id = str(payload["session_id"])
    message_id = f"msg_{session_id}_{payload.get('job_id') or 'chat'}"
    return _report_ready_chat_response(
        session_id=session_id,
        message_id=message_id,
        plan_id=f"plan_{message_id}",
    )


def _report_ready_chat_response(*, session_id: str, message_id: str, plan_id: str) -> dict:
    from app.services.chat_orchestration_service import _analysis_plan

    plan = _analysis_plan(
        session_id=session_id,
        message_id=message_id,
        routing_intent="fine_notice_analysis",
        supervisor_state={"contract_version": "supervisor_conversation_state.v2", "next_questions": []},
        report_requested=True,
    )
    packages = [
        {
            "schema_version": "agent_input_schema.v1",
            "node_code": node_code,
            "status": "ready",
            "required_inputs": ["user_text|attachments"],
            "payload": {"user_text": "fixture facts", "attachments": [], "slot_state": {"contract_version": "slot_filling_state.v1", "slots": {}}},
        }
        for node_code in ("fine_notice_analysis", "law_ground_search", "appeal_decision_flow", "objection_report_generation")
    ]
    return {
        "contract_version": "chat_message_accepted.v2",
        "session_id": session_id,
        "message_id": message_id,
        "routing_intent": "fine_notice_analysis",
        "status": "queued",
        "progress": {"status": "queued", "active_node": "fine_notice_analysis", "message": "Queued."},
        "assistant_message": {"answer": "Queued.", "summary": "Queued."},
        "analysis_plan": plan,
        "supervisor_state": {
            "contract_version": "supervisor_conversation_state.v2",
            "stage": "agent_execution_ready",
            "slot_state": {"contract_version": "slot_filling_state.v1", "slots": {}},
            "agent_input_packages": packages,
            "reporting_payload": {"contract_version": "reporting_payload.v2", "report_type": "fine_notice_objection"},
        },
        "reporting_payload": {"contract_version": "reporting_payload.v2", "report_type": "fine_notice_objection"},
        "attachments": [], "blocked_attachments": [], "limitations": [],
    }
```

Add this exact context manager beneath the fixture response. It keeps the worker orchestration and persistence real while replacing only the four Agent adapter calls.

```python
from contextlib import ExitStack, contextmanager


@contextmanager
def _patched_report_ready_agents():
    from ai.agents.appeal_decision_flow import graph as appeal_graph
    from ai.agents.fine_notice_analysis import graph as fine_notice_graph

    def run_fine_notice(_state):
        return {"agent_results": {"fine_notice_analysis": {"status": "success", "summary": "Fixture notice parsed.", "structured_result": {"ocr_status": "success", "fine_type": "fine", "notice_stage": "pre_notice", "violation_text": "Fixture violation.", "opinion_deadline": "2026-12-31", "issuing_authority": "Fixture Traffic Authority"}, "evidence": [{"source_type": "fixture", "source_reference": "ownership:notice"}], "next_actions": [], "limitations": []}}}

    def run_law(_agent_input, _adapter_context):
        return {"status": "success", "summary": "Fixture law result.", "structured_result": {"matched_laws": [{"law_name": "Road Traffic Act", "article": "Article 1", "summary": "Fixture provision.", "source_reference": "ownership:law"}]}, "evidence": [{"source_type": "law", "source_reference": "ownership:law"}], "next_actions": [], "limitations": []}

    def run_appeal(_state):
        return {"agent_results": {"appeal_judgment": {"status": "success", "summary": "Appeal review complete.", "structured_result": {"judgment_status": "success", "overall_possibility": "review_available", "guide": {"summary": "Review supporting evidence."}}, "evidence": [{"source_type": "law", "source_reference": "ownership:law"}], "next_actions": [], "limitations": []}}}

    def run_report(agent_input, _adapter_context):
        handoff = agent_input["context"]["supervisor_reporting_handoff"]
        return {"status": "success", "summary": "Official objection draft ready.", "structured_result": {"document_type": "objection_form", "document_variant": "fine_notice", "document_title": "Fine objection form", "form_sections": [{"title": "Petition", "items": ["Review the disposition."]}], "form_data": {"applicant_name": "Review required"}, "petition_purpose": "Review the disposition.", "petition_reason": "Review the verified facts and legal grounds.", "drafting_source": "rule_based_fixture", "appeal_gate": {"status": "ready"}, "document_readiness": {"status": "review_required"}, "report_actions": [{"action": "download_objection", "label": "Download objection form"}], "supervisor_handoff": {"contract_version": handoff["contract_version"], "handoff_id": handoff["handoff_id"], "gate_status": handoff["gate"]["status"], "source_fingerprint": handoff["source"]["fingerprint"], "source_result_ids": handoff["source"]["result_ids"]}}, "evidence": [{"source_type": "law", "source_reference": "ownership:law"}], "next_actions": ["review_objection_draft", "download_objection"], "limitations": []}

    with ExitStack() as stack:
        stack.enter_context(patch.object(fine_notice_graph, "invoke", side_effect=run_fine_notice))
        stack.enter_context(patch("ai.agents.law_ground_search.run_law_ground_search", side_effect=run_law))
        stack.enter_context(patch.object(appeal_graph, "invoke", side_effect=run_appeal))
        stack.enter_context(patch("ai.agents.objection_report_generation.run_objection_report_generation", side_effect=run_report))
        yield
```

Call it as `with _patched_report_ready_agents():` in the test. Its fixture keeps `appeal_gate.status == "ready"`, `document_variant == "fine_notice"`, and `document_type == "objection_form"`; none of the replacement functions performs network I/O.

- [ ] **Step 4: owner-bound attachment, Worker report binding, confirmation, and DOCX assertions을 테스트에 완성한다.**

```python
session = ChatSession.objects.get(session_id=session_id)
UploadedFile.objects.create(
    attachment_id=attachment_id,
    owner_id=self.owner_id,
    session=session,
    purpose="fine_notice",
    original_filename="fixture-notice.png",
    content_type="image/png",
    status=UploadedFileStatus.READY,
    scan_status="clean",
    storage_uri="s3://private-bucket/reports/owner.docx",
)
attachment = self.owner_client.get(f"/api/files/{attachment_id}/", {"session_id": session_id})
self.assertEqual(attachment.status_code, 200, attachment.content)

from chatbot.models import AnalysisJob, Report
job = AnalysisJob.objects.select_related("session").get(job_id=job_id)
report = Report.objects.select_related("session", "job").get(job=job)
self.assertEqual((job.owner_id, job.session.session_id), (self.owner_id, session_id))
self.assertEqual((report.owner_id, report.session.session_id, report.job_id), (self.owner_id, session_id, job.pk))

detail = self.owner_client.get(f"/api/reports/{report.report_id}/")
self.assertEqual(detail.status_code, 200, detail.content)
confirmation = self.owner_client.post(
    f"/api/reports/{report.report_id}/document-confirmation/",
    data={"facts_confirmed": True, "agency_confirmed": True, "deadline_confirmed": True, "attachments_confirmed": True},
    content_type="application/json",
)
self.assertEqual(confirmation.status_code, 201, confirmation.content)
download = self.owner_client.get(f"/api/reports/{report.report_id}/download/?document_type=objection_form")
self.assertEqual(download.status_code, 200, download.content)
self.assertEqual(download["Content-Type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
self.assertIn("attachment", download["Content-Disposition"].lower())
self.assertTrue(download.content.startswith(b"PK"))
```

- [ ] **Step 5: owner lifecycle 테스트를 통과시키고 임시 mock 호출을 점검한다.**

Run: `& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' -m pytest -q --timeout=30 backend/chatbot/test_resource_ownership_e2e.py::ResourceOwnershipE2ETests::test_owner_can_complete_bound_resource_lifecycle_and_download_docx`

Expected: PASS. 실제 외부 URL, S3 client, OCR, LLM provider 호출은 없어야 한다.

- [ ] **Step 6: owner success coverage를 커밋한다.**

```powershell
git add backend/chatbot/test_resource_ownership_e2e.py
git commit -m "test: cover owner resource lifecycle e2e"
```

### Task C: attacker 전 경계 차단과 정보 비노출을 표 기반 회귀 테스트로 고정

**Files:**

- Modify: `backend/chatbot/test_resource_ownership_e2e.py`
- Reference: `backend/chatbot/views.py`의 `submit_chat_message`, `analysis_jobs`, `attachment_detail`, `report_detail`, `download_report`

**Interfaces:**

- Consumes: Task B가 만든 owner `session_id`, `job_id`, `attachment_id`, `report_id` fixture.
- Produces: `test_attacker_cannot_access_or_mutate_any_owner_bound_resource() -> None`.

- [ ] **Step 1: attacker 요청 목록과 expected safe denial을 failing test로 작성한다.**

```python
requests = (
    ("job_list", lambda: self.attacker_client.get("/api/analysis/jobs/", {"session_id": session_id})),
    ("job_detail", lambda: self.attacker_client.get(f"/api/analysis/jobs/{job_id}/")),
    ("job_result", lambda: self.attacker_client.get(f"/api/analysis/results/{job_id}/")),
    ("attachment", lambda: self.attacker_client.get(f"/api/files/{attachment_id}/", {"session_id": session_id})),
    ("report_detail", lambda: self.attacker_client.get(f"/api/reports/{report_id}/")),
    ("chat_session_reuse", lambda: self.attacker_client.post("/api/chat/messages/", data={"session_id": session_id, "user_text": "attacker write"}, content_type="application/json")),
    ("save_state", lambda: self.attacker_client.post("/api/chat/save-state/", data={"session_id": session_id, "save_state": "saved"}, content_type="application/json")),
    ("analysis_submit", lambda: self.attacker_client.post("/api/analysis/jobs/", data={"job_id": "job_attacker_attempt", "session_id": session_id, "user_text": "attacker analysis"}, content_type="application/json")),
)
for name, request in requests:
    with self.subTest(boundary=name):
        _assert_object_access_denied(self, request(), owner_id=self.owner_id, forbidden_fragments=self.private_fragments)
```

- [ ] **Step 2: 테스트를 실행해 누락된 경계 또는 기존 response contract 차이를 확인한다.**

Run: `& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' -m pytest -q --timeout=30 backend/chatbot/test_resource_ownership_e2e.py::ResourceOwnershipE2ETests::test_attacker_cannot_access_or_mutate_any_owner_bound_resource`

Expected: 최초 실행은 아직 download assertion과 report fixture 연결이 없어 FAIL할 수 있다. 각 실패는 URL·status·`error.code`를 확인해 권한 결함과 fixture 결함을 구분한다.

- [ ] **Step 3: report download가 document resolver 전에 차단됨을 명시적으로 추가한다.**

```python
with patch("chatbot.views.get_report_download_metadata") as resolve_download:
    denied_download = self.attacker_client.get(
        f"/api/reports/{report_id}/download/?document_type=objection_form"
    )
_assert_object_access_denied(
    self,
    denied_download,
    owner_id=self.owner_id,
    forbidden_fragments=self.private_fragments,
)
resolve_download.assert_not_called()
```

- [ ] **Step 4: 실제 권한 결함일 때만 최소 수정한다.**

```python
# Preferred correction shape; retain the existing error contract.
access = authorize_resource_access(access_metadata, identity_payload)
if not access["allowed"]:
    return _object_access_denied_response(request, access)
```

Apply this only in the exact `views.py` boundary whose failing test proves it lacks authorization before data/document resolution. Reuse its existing resource metadata loader; do not add a second authorization policy, change a denial to 404, or include diagnostic storage fields in the response.

- [ ] **Step 5: attacker matrix와 owner test를 함께 통과시킨다.**

Run: `& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' -m pytest -q --timeout=30 backend/chatbot/test_resource_ownership_e2e.py`

Expected: PASS. 모든 attacker subtest는 `403 object_access_denied`; owner test만 `200/201/202` 및 DOCX attachment response를 허용한다.

- [ ] **Step 6: 소유권 경계 테스트와 필요한 최소 production 수정만 커밋한다.**

```powershell
git add backend/chatbot/test_resource_ownership_e2e.py backend/chatbot/views.py backend/chatbot/repositories.py
git commit -m "test: lock resource ownership e2e boundary"
```

If neither production file changed, stage only `backend/chatbot/test_resource_ownership_e2e.py` instead.

### Task D: 회귀 검증, 증빙 정리, 구현 PR 후 체크리스트 반영

**Files:**

- Modify after implementation PR review and CI success only: `project-readiness-master-checklist.md`
- Verify: `backend/chatbot/test_resource_ownership_e2e.py`, `backend/chatbot/test_analysis_job_queue.py`, `backend/chatbot/test_report_api_contract.py`, all repository tests.

**Interfaces:**

- Consumes: implementation branch commit set and the user-provided implementation PR link/CI result.
- Produces: clean test evidence and a same-PR checklist completion update; no standalone checklist branch or PR.

- [ ] **Step 1: 집중 회귀 테스트를 실행한다.**

Run: `& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' -m pytest -q --timeout=30 backend/chatbot/test_resource_ownership_e2e.py backend/chatbot/test_analysis_job_queue.py backend/chatbot/test_report_api_contract.py`

Expected: PASS. 이 결과는 API 인증, queue/worker persistence, report/document download 계약이 함께 깨지지 않았음을 증명한다.

- [ ] **Step 2: 전체 회귀와 diff hygiene를 확인한다.**

Run: `& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' -m pytest -q --timeout=30`

Expected: PASS with the repository’s current expected skipped tests only; no new failure.

Run: `git diff --check origin/dev...HEAD`

Expected: no output and exit code 0.

- [ ] **Step 3: 구현 PR에 포함할 검증 근거를 정리한다.**

```markdown
## 검증
- `backend/chatbot/test_resource_ownership_e2e.py`: owner API → targeted Worker → Report → confirmation → DOCX와 attacker 전 경계 `403 object_access_denied` 통과
- 집중 회귀: analysis queue 및 report API contract 통과
- 전체 `pytest -q --timeout=30` 통과
- 외부 LLM/OCR/S3/별도 Worker 호출 없음
```

- [ ] **Step 4: 사용자에게 구현 PR 링크와 CI 성공 결과를 받은 뒤에만 체크리스트를 같은 브랜치에서 갱신한다.**

```markdown
- [x] 세션·분석·첨부파일·리포트 소유권 E2E 검증 — Issue #254 / 구현 PR 링크 / CI 통과일
```

Before editing, verify the exact existing checklist heading and preserve all unrelated owners’ rows. Do not create `docs/*-checklist-complete` branch or a separate checklist-only PR.

- [ ] **Step 5: checklist update가 실제로 필요해진 경우에만 final documentation commit을 만든다.**

```powershell
git add project-readiness-master-checklist.md
git commit -m "docs: mark resource ownership e2e complete"
git push origin test/254-resource-ownership-e2e
```

## Plan Self-Review

- Spec coverage: owner session/job/attachment/report/DOCX flow is Task B; queue Worker result ownership is Task B; attacker read/write/download boundaries and privacy-safe response are Task C; no external provider usage and existing response contract are Global Constraints; checklist policy is Task D.
- Deliberate execution choice: targeted `process_agent_work_item(work_item_id)` is used instead of batch processing because `POST /api/chat/messages/` can create an earlier queue row. This still exercises the real Worker transaction while ensuring the selected analysis Job is the one that produces the asserted Report.
- Out of scope verified: no PDF path, provider/auth-schema/RLS rewrites, OCR/RAG quality change, or unrelated UI change is planned.
- Placeholder scan: this plan contains no unresolved implementation placeholder. The only conditional is the explicitly bounded production fix path, which is prohibited unless a red authorization test identifies its exact missing boundary.
