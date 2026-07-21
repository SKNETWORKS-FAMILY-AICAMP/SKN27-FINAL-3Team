# 비회원·로그인 전환 세션 소유권 E2E 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 비회원 세션이 같은 guest ID의 로그인 사용자에게만 연결되고, 사건 생성으로 Job·첨부파일·Report가 원자적으로 귀속되는 기존 정책을 API E2E 회귀 테스트로 고정한다.

**Architecture:** 새 Django `TestCase`는 실제 guest-session, 채팅, 분석 Job, 파일, Google code, Case API와 실제 in-process Worker 영속화를 사용한다. 외부 Agent adapter만 결정론적 대역으로 교체하고, mismatch·재로그인·다른 인증 사용자의 요청은 실제 HTTP 경계와 DB 스냅샷으로 무변경 및 정보 비노출을 검증한다.

**Tech Stack:** Django TestCase/Client, Django ORM, `unittest.mock`, in-process `process_agent_work_item`, Pydantic API DTO, Ruff, pytest.

## Global Constraints

- `guest_id`는 현재 임시 capability이며, 유출·복제된 동일 ID의 재사용 방어는 이 이슈 범위가 아니다.
- 로그인은 세션 인증 연결이고, Job·첨부파일·Report의 영구 귀속은 `POST /api/cases/` 사건 생성에서만 확인한다.
- Google OAuth, LLM, OCR, S3, 별도 Worker 프로세스는 호출하지 않는다.
- 인증 provider, JWT 형식, DB 스키마, guest credential 형식, 프론트엔드 로그인 UI를 변경하지 않는다.
- production code는 새 테스트가 기존 계약 위반을 재현할 때만 최소 수정한다. 테스트가 통과하면 production code를 변경하지 않는다.
- checklist 완료 표기는 구현 PR 링크와 CI 통과 결과를 사용자에게 받은 뒤, 이 브랜치에서만 반영한다. 별도 checklist PR은 만들지 않는다.

---

## 파일 구조

- Create: `backend/chatbot/test_guest_login_session_ownership_e2e.py` — #256의 정상 전환, mismatch·재로그인 무변경, 비소유자 접근·변경 차단을 한 파일에 둔다.
- Modify only if a red test proves an existing boundary defect: `backend/chatbot/views.py` 또는 `backend/chatbot/repositories.py` — 해당 실패 URL의 최소 권한/직렬화 경계만 수정한다.
- Modify after implementation PR 검토와 CI 통과: `docs/ops/project-readiness-master-checklist.md` — #256을 `[x]`로 바꾼다.

## Task 1: 재현 가능한 guest 자료·로그인·Worker fixture를 테스트 모듈에 만든다

**Files:**

- Create: `backend/chatbot/test_guest_login_session_ownership_e2e.py`
- Reference: `backend/chatbot/test_resource_ownership_e2e.py`, `backend/chatbot/test_google_oauth_live_contract.py`, `backend/chatbot/test_file_quarantine.py`

**Interfaces:**

- Consumes: guest session API, Google code mock contract, `process_agent_work_item(work_item_id)`.
- Produces: `_create_guest_resources() -> dict[str, str]`, `_login_owner(resources) -> tuple[Client, str]`, `_resource_snapshot() -> dict[str, object]`.

- [ ] **Step 1: TestCase와 인증·Google payload helper를 먼저 작성한다.**

```python
TEST_JWT_SIGNING_KEY = "guest-login-ownership-e2e-signing-key-is-long-enough"


def _google_login_payload(*, guest_id: str, session_id: str, code: str) -> dict[str, str]:
    return {
        "provider": "google",
        "code": f"mock_google_code:{code}",
        "purpose": "LOGIN",
        "scope": "openid email profile",
        "email": f"{code}@example.test",
        "display_name": f"{code} user",
        "guest_id": guest_id,
        "session_id": session_id,
    }


@override_settings(APP_JWT_SECRET=TEST_JWT_SIGNING_KEY)
class GuestLoginSessionOwnershipE2ETests(TestCase):
    def _google_login(self, *, guest_id: str, session_id: str, code: str):
        return Client(raise_request_exception=False).post(
            "/api/auth/google/code/",
            data=_google_login_payload(
                guest_id=guest_id,
                session_id=session_id,
                code=code,
            ),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XmlHttpRequest",
        )
```

- [ ] **Step 2: guest API로 세션과 첨부파일을 만들고, chat/job/Worker fixture를 작성한다.**

```python
guest = Client().post(
    "/api/auth/guest-session/",
    data={"session_id": "ses_guest_login_owner"},
    content_type="application/json",
)
self.assertEqual(guest.status_code, 200, guest.content)
guest_id = guest.json()["guest"]["guest_id"]
guest_client = Client(HTTP_X_GUEST_ID=guest_id)
upload = guest_client.post(
    "/api/files/",
    data={
        "session_id": "ses_guest_login_owner",
        "purpose": "fine_notice",
        "file": SimpleUploadedFile(
            "guest-notice.txt", b"guest notice fixture", content_type="text/plain"
        ),
    },
)
self.assertEqual(upload.status_code, 200, upload.content)
```

Define `_fixture_submit_message()` and `_patched_report_ready_agents()` in this new file. They must follow the existing #255 fixture contract: `fine_notice_analysis`, `law_ground_search`, `appeal_decision_flow`, and `objection_report_generation` return deterministic success data with `document_variant == "fine_notice"`, `document_type == "objection_form"`, and `appeal_gate.status == "ready"`. Patch only `chatbot.views.submit_message` and those four Agent adapter entry points. Create the guest chat and job through `POST /api/chat/messages/` and `POST /api/analysis/jobs/`, then process the selected `AgentWorkItem` with `process_agent_work_item(work_item_id)`.

- [ ] **Step 3: resource snapshot helper를 작성한다.**

```python
def _resource_snapshot() -> dict[str, object]:
    return {
        "auth_sessions": list(
            AuthSession.objects.order_by("auth_session_id").values(
                "auth_session_id", "user_id", "guest_id", "subject_id", "status"
            )
        ),
        "sessions": list(
            ChatSession.objects.order_by("session_id").values("session_id", "owner_id", "case_id")
        ),
        "jobs": list(
            AnalysisJob.objects.order_by("job_id").values("job_id", "owner_id", "case_id", "session_id")
        ),
        "files": list(
            UploadedFile.objects.order_by("attachment_id").values(
                "attachment_id", "owner_id", "case_id", "session_id"
            )
        ),
        "reports": list(
            Report.objects.order_by("report_id").values("report_id", "owner_id", "case_id", "session_id")
        ),
        "cases": list(Case.objects.order_by("case_id").values("case_id", "owner_id")),
    }
```

- [ ] **Step 4: focused module import를 실행한다.**

Run: `& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' backend/manage.py test chatbot.test_guest_login_session_ownership_e2e -v 1`

Expected: test discovery succeeds. 아직 test method가 없거나 fixture가 미완성이면 실패 원인을 fixture 단계로 한정한다.

- [ ] **Step 5: fixture를 커밋한다.**

```powershell
git add backend/chatbot/test_guest_login_session_ownership_e2e.py
git commit -m "test: add guest login ownership e2e fixture"
```

## Task 2: 정상 guest → 로그인 → 사건 생성 귀속 흐름을 테스트 우선으로 고정한다

**Files:**

- Modify: `backend/chatbot/test_guest_login_session_ownership_e2e.py`
- Reference: `backend/chatbot/repositories.py:_bind_chat_session_auth_context`, `backend/chatbot/case_repository.py:create_case`

**Interfaces:**

- Consumes: Task 1의 guest resource fixture와 Google login helper.
- Produces: `test_owner_can_bind_guest_session_and_promote_resources_to_case()`.

- [ ] **Step 1: 정상 흐름 test를 작성한다.**

```python
def test_owner_can_bind_guest_session_and_promote_resources_to_case(self) -> None:
    resources = self._create_guest_resources()
    owner_client, owner_id = self._login_owner(resources)

    session = ChatSession.objects.get(session_id=resources["session_id"])
    self.assertEqual(session.owner_id, owner_id)
    self.assertEqual(session.metadata["auth_context"]["guest_id"], resources["guest_id"])

    for response in (
        owner_client.get(f"/api/analysis/jobs/{resources['job_id']}/"),
        owner_client.get(f"/api/analysis/results/{resources['job_id']}/"),
        owner_client.get(
            f"/api/files/{resources['attachment_id']}/",
            {"session_id": resources["session_id"]},
        ),
        owner_client.get(f"/api/reports/{resources['report_id']}/"),
    ):
        self.assertEqual(response.status_code, 200, response.content)

    saved = owner_client.post(
        "/api/chat/save-state/",
        data={"session_id": resources["session_id"], "conversation_save_state": "saved"},
        content_type="application/json",
    )
    self.assertEqual(saved.status_code, 200, saved.content)

    created = owner_client.post(
        "/api/cases/",
        data={
            "session_id": resources["session_id"],
            "title": "Guest ownership promotion fixture",
            "case_type": "accident_fault",
            "consultation_state": {"risk_gate": {"level": "standard"}},
        },
        content_type="application/json",
    )
    self.assertEqual(created.status_code, 201, created.content)
```

- [ ] **Step 2: test가 실제 계약 결함을 드러내는지 실행한다.**

Run: `& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' backend/manage.py test chatbot.test_guest_login_session_ownership_e2e.GuestLoginSessionOwnershipE2ETests.test_owner_can_bind_guest_session_and_promote_resources_to_case -v 1`

Expected: 새 E2E가 기존 흐름의 누락을 발견하면 RED가 된다. 이미 완성된 계약이면 PASS이며 production code를 추가하지 않는다.

- [ ] **Step 3: Case 귀속과 workspace assertions를 완성한다.**

```python
case_id = created.json()["case"]["case_id"]
case = Case.objects.get(case_id=case_id)
for model, key in (
    (ChatSession, "session_id"),
    (AnalysisJob, "job_id"),
    (UploadedFile, "attachment_id"),
    (Report, "report_id"),
):
    record = model.objects.get(**{key: resources[key]})
    self.assertEqual(record.owner_id, owner_id)
    self.assertEqual(record.case_id, case.id)

workspace = owner_client.get(f"/api/cases/{case_id}/workspace/")
self.assertEqual(workspace.status_code, 200, workspace.content)
self.assertEqual(workspace.json()["workspace"]["case"]["case_id"], case_id)
```

- [ ] **Step 4: 실패가 production authorization/transaction defect일 때만 최소 수정한다.**

Fix only the function named in the failing traceback. Preserve `google_guest_session_mismatch`, `google_session_already_owned`, `object_access_denied`, and `case_owner_mismatch`; do not introduce a new response code, automatic merge, or schema field.

- [ ] **Step 5: owner 흐름을 다시 실행하고 커밋한다.**

Run: `& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' backend/manage.py test chatbot.test_guest_login_session_ownership_e2e.GuestLoginSessionOwnershipE2ETests.test_owner_can_bind_guest_session_and_promote_resources_to_case -v 1`

Expected: PASS; owner는 `200/201`만 받고 guest-created 자원은 같은 Case에 연결된다.

```powershell
git add backend/chatbot/test_guest_login_session_ownership_e2e.py backend/chatbot/views.py backend/chatbot/repositories.py backend/chatbot/case_repository.py
git commit -m "test: cover guest login resource promotion e2e"
```

Stage only files that actually changed.

## Task 3: guest mismatch와 이미 소유된 세션 재로그인의 무변경을 고정한다

**Files:**

- Modify: `backend/chatbot/test_guest_login_session_ownership_e2e.py`
- Reference: `backend/chatbot/views.py:_google_code_session_binding_error`

**Interfaces:**

- Consumes: Task 1의 `_resource_snapshot()` 및 로그인 helper.
- Produces: `test_other_guest_cannot_bind_owner_session()`과 `test_owned_session_relogin_is_rejected_without_mutation()`.

- [ ] **Step 1: 다른 guest ID의 pre-provider 차단 test를 작성한다.**

```python
before = _resource_snapshot()
with patch("app.services.google_auth_service.urllib_request.urlopen") as exchange:
    denied = self._google_login(
        guest_id="gst_other_guest",
        session_id=resources["session_id"],
        code="other-guest",
    )
self.assertEqual(denied.status_code, 403, denied.content)
self.assertEqual(denied.json()["error"]["auth"]["reason"], "google_guest_session_mismatch")
exchange.assert_not_called()
self.assertEqual(_resource_snapshot(), before)
```

- [ ] **Step 2: test를 실행해 mismatch 경계를 확인한다.**

Run: `& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' backend/manage.py test chatbot.test_guest_login_session_ownership_e2e.GuestLoginSessionOwnershipE2ETests.test_other_guest_cannot_bind_owner_session -v 1`

Expected: PASS with `403 google_guest_session_mismatch`, zero provider calls, and an identical snapshot.

- [ ] **Step 3: 소유 세션 재로그인의 무변경 test를 작성한다.**

```python
_owner_client, _owner_id = self._login_owner(resources)
before = _resource_snapshot()
with patch("app.services.google_auth_service.urllib_request.urlopen") as exchange:
    denied = self._google_login(
        guest_id=resources["guest_id"],
        session_id=resources["session_id"],
        code="owner-relogin",
    )
self.assertEqual(denied.status_code, 403, denied.content)
self.assertEqual(denied.json()["error"]["auth"]["reason"], "google_session_already_owned")
exchange.assert_not_called()
self.assertEqual(_resource_snapshot(), before)
```

- [ ] **Step 4: 두 test를 함께 실행하고, red가 실제 계약 불일치일 때만 해당 login boundary를 수정한다.**

Run: `& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' backend/manage.py test chatbot.test_guest_login_session_ownership_e2e.GuestLoginSessionOwnershipE2ETests.test_other_guest_cannot_bind_owner_session chatbot.test_guest_login_session_ownership_e2e.GuestLoginSessionOwnershipE2ETests.test_owned_session_relogin_is_rejected_without_mutation -v 1`

Expected: PASS. `urllib_request.urlopen` 호출, AuthSession 추가, 기존 resource snapshot 변경 중 하나라도 발생하면 실패다.

- [ ] **Step 5: 차단 회귀 test를 커밋한다.**

```powershell
git add backend/chatbot/test_guest_login_session_ownership_e2e.py backend/chatbot/views.py backend/chatbot/repositories.py
git commit -m "test: lock guest login binding denial"
```

Stage only files that actually changed.

## Task 4: 다른 인증 사용자의 조회·변경·Case 생성 차단과 비노출을 고정한다

**Files:**

- Modify: `backend/chatbot/test_guest_login_session_ownership_e2e.py`
- Reference: `backend/chatbot/views.py`, `backend/chatbot/case_repository.py`

**Interfaces:**

- Consumes: Task 2에서 생성된 `session_id`, `job_id`, `attachment_id`, `report_id`, `case_id`.
- Produces: `test_other_user_cannot_read_mutate_or_promote_owner_resources()`.

- [ ] **Step 1: 안전한 거부 assertion helper를 작성한다.**

```python
def _assert_safe_denial(self, response, *, code: str, forbidden: tuple[str, ...]) -> None:
    self.assertEqual(response.status_code, 403, response.content)
    body = response.json()
    self.assertEqual(body["error"]["code"], code)
    rendered = json.dumps(body, sort_keys=True)
    for secret in forbidden:
        self.assertNotIn(secret, rendered)
    self.assertNotIn("Content-Disposition", response.headers)
    self.assertFalse(response.content.startswith(b"PK"))
```

- [ ] **Step 2: 다른 인증 사용자 request matrix를 failing test로 작성한다.**

```python
attempts = (
    ("job_detail", "object_access_denied", lambda: attacker.get(f"/api/analysis/jobs/{job_id}/")),
    ("job_result", "object_access_denied", lambda: attacker.get(f"/api/analysis/results/{job_id}/")),
    ("attachment", "object_access_denied", lambda: attacker.get(f"/api/files/{attachment_id}/", {"session_id": session_id})),
    ("report", "object_access_denied", lambda: attacker.get(f"/api/reports/{report_id}/")),
    ("workspace", "object_access_denied", lambda: attacker.get(f"/api/cases/{case_id}/workspace/")),
    ("save_state", "object_access_denied", lambda: attacker.post("/api/chat/save-state/", data={"session_id": session_id, "conversation_save_state": "saved"}, content_type="application/json")),
    ("case_create", "case_owner_mismatch", lambda: attacker.post("/api/cases/", data={"session_id": session_id, "case_type": "accident_fault"}, content_type="application/json")),
)
before = _resource_snapshot()
forbidden = (
    owner_id,
    resources["guest_id"],
    "guest-notice.txt",
    "s3://",
    "Official objection draft ready.",
)
for name, code, request in attempts:
    with self.subTest(boundary=name):
        self._assert_safe_denial(request(), code=code, forbidden=forbidden)
self.assertEqual(_resource_snapshot(), before)
```

- [ ] **Step 3: attack matrix를 실행하고 failure 원인을 분류한다.**

Run: `& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' backend/manage.py test chatbot.test_guest_login_session_ownership_e2e.GuestLoginSessionOwnershipE2ETests.test_other_user_cannot_read_mutate_or_promote_owner_resources -v 1`

Expected: 모든 subtest는 기존 403 error code를 반환하고 snapshot은 동일하다. 실패 시 authorization 누락, error serialization 노출, 또는 fixture 오류 중 하나로 분류한다.

- [ ] **Step 4: red가 증명한 production defect만 최소 수정하고 test를 green으로 만든다.**

Do not change a denial to `404`, add a bypass for the authenticated user, or serialize owner/storage/Report data in an error. The fix must be before resource retrieval, state mutation, document resolution, or Case creation side effect in the failed endpoint.

- [ ] **Step 5: attack matrix를 커밋한다.**

```powershell
git add backend/chatbot/test_guest_login_session_ownership_e2e.py backend/chatbot/views.py backend/chatbot/repositories.py backend/chatbot/case_repository.py
git commit -m "test: lock guest login ownership boundaries"
```

Stage only files that actually changed.

## Task 5: 회귀 검증과 구현 PR 후 checklist 완료 반영

**Files:**

- Verify: `backend/chatbot/test_guest_login_session_ownership_e2e.py`, `backend/chatbot/test_resource_ownership_e2e.py`, `backend/chatbot/test_google_oauth_live_contract.py`, `backend/chatbot/test_consultation_v2.py`
- Modify after user provides implementation PR link and successful CI: `docs/ops/project-readiness-master-checklist.md`

**Interfaces:**

- Consumes: Task 1–4 commit set, implementation PR link, CI result.
- Produces: reproducible test evidence and one same-PR checklist completion update.

- [ ] **Step 1: focused and adjacent Django tests를 실행한다.**

Run: `& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' backend/manage.py test chatbot.test_guest_login_session_ownership_e2e chatbot.test_resource_ownership_e2e chatbot.test_google_oauth_live_contract chatbot.test_consultation_v2 -v 1`

Expected: PASS. guest/login binding, resource ownership, Google pre-provider guard, Case promotion contract가 함께 유지된다.

- [ ] **Step 2: 전체 chatbot, 루트 pytest, lint와 diff hygiene를 실행한다.**

Run: `& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' backend/manage.py test chatbot -v 1`

Expected: PASS with no new chatbot failure.

Run: `& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' -m pytest -q --timeout=30`

Expected: PASS with only the repository’s expected skips.

Run: `& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' -m ruff check backend/chatbot/test_guest_login_session_ownership_e2e.py`

Expected: `All checks passed!`

Run: `git diff --check origin/dev...HEAD`

Expected: no output and exit code 0.

- [ ] **Step 3: PR 검증 근거를 정리한다.**

```md
## 검증
- guest session → 실제 Job/in-process Worker Report → matching Google login → Case promotion E2E 통과
- mismatch guest와 이미 소유된 세션 재로그인은 provider 미호출 및 DB snapshot 무변경
- 다른 인증 사용자의 Job·첨부파일·Report·Case 조회 및 상태 변경·Case 생성은 기존 403 계약으로 차단
- 외부 Google OAuth/LLM/OCR/S3/별도 Worker 호출 없음
```

- [ ] **Step 4: 사용자에게 구현 PR 링크와 CI 통과 결과를 받은 뒤에만 checklist를 완료로 갱신한다.**

```md
- [x] 비회원·로그인 사용자 전환과 세션 소유권의 일관성 검증 — #256 / 구현 PR 링크
```

The follow-up signed guest credential row remains `[ ]`; do not close or downgrade it in this issue.

- [ ] **Step 5: checklist 변경이 발생하면 이 브랜치에만 문서 커밋·push한다.**

```powershell
git add docs/ops/project-readiness-master-checklist.md
git commit -m "docs: mark guest login ownership e2e complete"
git push origin test/256-guest-login-session-ownership-e2e
```

## Plan Self-Review

- Spec coverage: Task 1 creates the actual guest, Job, attachment, and in-process Worker Report path; Task 2 validates matching-login access and explicit Case promotion; Task 3 verifies mismatch/relogin pre-provider denial and DB immutability; Task 4 covers the exact authenticated-attacker read/write/create matrix and privacy-safe errors; Task 5 covers the required regressions, CI handoff, and checklist policy.
- Deliberate policy boundary: no test claims to distinguish an attacker who possesses the owner guest ID. The separate checklist row remains open for a future server-verifiable guest credential.
- Production scope: no production code change is planned. A production edit is allowed only after a failing E2E test identifies the exact current contract boundary that violates the approved issue.
- Placeholder scan: the plan has no unresolved implementation placeholder. Conditional production fixes are explicitly limited by the failing endpoint and its existing response contract.
