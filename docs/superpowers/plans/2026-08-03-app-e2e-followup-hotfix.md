# App E2E Follow-up Hotfix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 최신 `origin/dev` `cec0416a`에서 과태료 슬롯 누적, 첨부 처리 경계, 법령 표 조각, 로그인 사용자 새로고침 복원을 최소 수정하고 persisted report·이의신청서 연결을 회귀 검증한다.

**Architecture:** 서버에 저장된 follow-up 질문 필드와 영속 DB를 권위값으로 사용한다. 첨부 처리에는 성공을 추정하는 타이머를 추가하지 않고 공개 DTO에 안전한 단계별 경계를 노출하며 실제 API→worker 통합 테스트로 연결을 검증한다. `GET /api/auth/resume/`은 인증된 사용자 소유의 최신 상담을 기존 공개 analysis DTO로 조합하고 프론트는 `/auth/me/` 성공 뒤에만 이를 hydrate한다.

**Tech Stack:** Python 3.14, Django, pytest, React 19, Node test runner, Vite

## Global Constraints

- 기준 SHA는 최신 `origin/dev` `cec0416a58d6a30d8179506419774ab5589c89cd`다.
- `ai/**`, OCR/Vision 모델, 프롬프트, 법령 검색 엔진은 변경하지 않는다.
- AWS Vision wiring은 최신 `dev` 기준선으로만 유지하고 인프라 활성화·배포는 수행하지 않는다.
- OCR 원문, 개인정보, S3 URI, 내부 오류 문자열을 공개 응답에 추가하지 않는다.
- 인증 정보 삭제는 명시적인 HTTP `401/403`에서만 수행한다.
- persisted report와 이의신청서 초안은 선행 연결을 통과한 뒤 기존 엔진을 변경하지 않고 검증한다.

---

### Task 1: 과태료 슬롯 누적과 저장 질문 필드

**Files:**
- Modify: `app/services/supervisor_input_normalization_service.py`
- Modify: `app/services/chat_session_followup_service.py`
- Modify: `app/services/fine_notice_intake_service.py`
- Test: `test/test_supervisor_input_normalization_service.py`
- Test: `test/test_chat_session_followup_service.py`
- Test: `test/test_fine_notice_intake_service.py`
- Test: `test/test_chat_orchestration_service.py`

**Interfaces:**
- Consumes: `ChatSession.metadata.chat_followup_state.pending_questions[*].field`, 현재 `user_text`, 저장된 `fine_notice_intake.slots`.
- Produces: `merged["pending_questions"]`와 `fine_notice_intake.v1`의 누적 `slots`, 실제 누락 필드만 포함한 `next_questions`.

- [ ] **Step 1: `서울시` 일반 기관 표현의 실패 테스트를 작성한다**

```python
def test_normalization_accepts_seoul_city_alias_without_inventing_official_name():
    normalized = normalize_supervisor_input(
        user_text="사전통지서, 서울시, 2026-08-10, 첨부 가능",
        source_message_id="msg_seoul_city",
    )
    slots = fine_notice_intake_slots(normalized)
    assert slots["issuing_authority"]["value"] == "서울시"
    assert "서울특별시" not in repr(slots)
```

- [ ] **Step 2: 테스트가 현재 `issuing_authority` 누락으로 실패하는지 확인한다**

Run: `python -m pytest -q test/test_supervisor_input_normalization_service.py -k seoul_city_alias`
Expected: FAIL because `AUTHORITY_PATTERN` does not accept `서울시`.

- [ ] **Step 3: 승인된 일반 표현만 최소 확장한다**

```python
AUTHORITY_PATTERN = re.compile(
    r"(?:서울시|[가-힣]{2,20}(?:경찰서|시청|구청|군청|도로교통공단)"
    r"|[가-힣]{2,10}(?:특별시|광역시|특별자치시|특별자치도))"
)
```

- [ ] **Step 4: 저장 질문의 `field`가 문구와 무관하게 후속 단답을 받는 실패 테스트를 작성한다**

```python
def test_pending_question_field_routes_short_followup_without_exact_prompt_text():
    result = reduce_fine_notice_intake({
        "message_id": "msg_followup",
        "user_text": "서울시",
        "pending_questions": [{
            "field": "issuing_authority",
            "question": "확인 안내를 포함한 다른 발급기관 문구",
        }],
    })
    assert result["slots"]["issuing_authority"]["value"] == "서울시"
    assert "issuing_authority" not in result["missing_fields"]
```

- [ ] **Step 5: 저장 follow-up merge가 `pending_questions`를 전달하지 않아 테스트가 실패하는지 확인한다**

Run: `python -m pytest -q test/test_chat_session_followup_service.py test/test_fine_notice_intake_service.py -k pending_question_field`
Expected: FAIL because the field is reduced to exact assistant text history.

- [ ] **Step 6: 서버 pending field와 현재 사용자 답변을 reducer에 연결한다**

```python
merged["pending_questions"] = _dict_list(state.get("pending_questions"))

pending_field = _authoritative_pending_field(payload.get("pending_questions"))
current_value = _slot_value(pending_field, payload.get("user_text"))
if pending_field and pending_field not in slots and current_value is not None:
    slots[pending_field] = _slot_record(
        current_value,
        source_type="user_confirmation",
        source_message_id=source_message_id,
    )
```

- [ ] **Step 7: 한 문장 네 슬롯, 부분 입력, 새로고침 후 단답 회귀를 실행한다**

Run: `python -m pytest -q test/test_supervisor_input_normalization_service.py test/test_fine_notice_intake_service.py test/test_chat_session_followup_service.py test/test_chat_orchestration_service.py`
Expected: PASS.

### Task 2: 첨부 처리 공개 경계와 실제 worker 연결

**Files:**
- Modify: `app/services/analysis_job_query_service.py`
- Test: `test/test_analysis_job_query_service.py`
- Test: `backend/chatbot/test_attachment_classification_confirmation_flow.py`

**Interfaces:**
- Consumes: 공개 projection 전의 canonical attachment 상태, job `status`/`active_node`, 안전한 Agent result envelope.
- Produces: `attachment_processing.v1` 목록. 각 항목은 `attachment_id`, `upload`, `scan`, `classification`, `confirmation`, `downstream_analysis`의 상태 코드만 포함한다.

- [ ] **Step 1: 공개 경계 projection 실패 테스트를 작성한다**

```python
def test_pending_attachment_result_exposes_safe_processing_boundaries():
    outcome = load_analysis_result(
        "job_classification",
        load_job=lambda _job_id: {
            "job_id": "job_classification",
            "status": "running",
            "active_node": "attachment_document_classification",
            "attachments": [{
                "attachment_id": "att_notice",
                "status": "ready",
                "scan_status": "clean",
                "storage_uri": "s3://private/notice.pdf",
            }],
            "agent_results": [],
        },
        compose_response=lambda _job: {},
    )
    assert outcome.payload["attachment_processing"] == [{
        "contract_version": "attachment_processing.v1",
        "attachment_id": "att_notice",
        "upload": "registered",
        "scan": "completed",
        "classification": "running",
        "confirmation": "not_ready",
        "downstream_analysis": "not_started",
    }]
    assert "s3://" not in repr(outcome.payload["attachment_processing"])
```

- [ ] **Step 2: 현재 DTO에 경계 목록이 없어 실패하는지 확인한다**

Run: `python -m pytest -q test/test_analysis_job_query_service.py -k processing_boundaries`
Expected: FAIL with missing `attachment_processing`.

- [ ] **Step 3: 상태 코드 allowlist projection을 구현한다**

```python
def _attachment_processing_for_job(job: dict[str, Any]) -> list[dict[str, str]]:
    results = {
        str(item.get("node_code") or ""): item
        for item in job.get("agent_results") or []
        if isinstance(item, dict)
    }
    active_node = str(job.get("active_node") or "")
    job_status = str(job.get("status") or "")
    projected = []
    for attachment in job.get("attachments") or []:
        if not isinstance(attachment, dict) or not attachment.get("attachment_id"):
            continue
        classification = results.get("attachment_document_classification", {})
        classification_result = classification.get("structured_result", {})
        classification_status = (
            "completed"
            if classification.get("status") == "success"
            else "running"
            if active_node == "attachment_document_classification"
            and job_status in {"queued", "running"}
            else "failed"
            if classification.get("status") in {"partial", "failed"}
            else "not_started"
        )
        projected.append({
            "contract_version": "attachment_processing.v1",
            "attachment_id": str(attachment["attachment_id"]),
            "upload": "registered",
            "scan": "completed"
            if attachment.get("scan_status") == "clean"
            else "running",
            "classification": classification_status,
            "confirmation": "required"
            if classification_result.get("requires_confirmation") is True
            else "not_ready",
            "downstream_analysis": "not_started",
        })
    return projected
```

- [ ] **Step 4: upload→scan→classification worker→분류 확인→OCR queue 통합 테스트를 작성한다**

```python
def test_clean_notice_worker_persists_classification_and_confirmation_queues_ocr(self):
    session_id, attachment_id = self._upload_clean_photo()
    queued = self.client.post(
        "/api/chat/messages/",
        data={
            "session_id": session_id,
            "user_text": "첨부한 자료를 확인해 주세요.",
            "attachments": [{"attachment_id": attachment_id}],
        },
        content_type="application/json",
    )
    with patch(
        "app.services.attachment_document_classification_adapter.classify_document_bytes",
        return_value={
            "status": "success",
            "structured_result": {
                "classification": "fine_notice",
                "confidence_band": "high",
                "requires_confirmation": True,
                "next_action": "confirm_classification",
            },
            "evidence": [],
            "next_actions": ["confirm_classification"],
            "limitations": [],
        },
    ):
        process_agent_work_item(queued.json()["work_item"]["work_item_id"])
    result = self.client.get(
        f"/api/analysis/results/{queued.json()['work_item']['job_id']}/"
    ).json()["result"]
    assert result["attachment_workflows"][0]["state"] == "classified_waiting_confirmation"
```

- [ ] **Step 5: 통합 테스트를 실행해 최초 정지 경계를 판정한다**

Run: `python backend/manage.py test chatbot.test_attachment_classification_confirmation_flow --verbosity 2`
Expected: PASS through the local deterministic worker. If it fails, change only the first failing production boundary; if it passes, preserve AI/model code and ship the safe public boundary diagnostics.

### Task 3: 유니코드 법령 표 조각 제거

**Files:**
- Modify: `app/services/public_law_projection_service.py`
- Test: `test/test_public_law_projection_service.py`

**Interfaces:**
- Consumes: 검증된 `matched_laws[*]`의 선택적 `summary`.
- Produces: 법령명·조문은 유지하고 ASCII/Unicode 표 조각 summary만 제외한 공개 법령 항목.

- [ ] **Step 1: Unicode box-drawing summary 실패 테스트를 작성한다**

```python
def test_public_law_projection_omits_unicode_box_drawing_table_summary():
    public = project_public_law_items({"matched_laws": [{
        "law_name": "도로교통법 시행령",
        "article": "별표10",
        "summary": "┏━━━━━━┳━━━━━━┓\n┃ 구분 ┃ 금액 ┃\n├──────┼──────┤",
        "source_reference": "law:verified:appendix-10",
    }]})
    assert public == [{"law_name": "도로교통법 시행령", "article": "별표10"}]
```

- [ ] **Step 2: 현재 ASCII pipe 필터만으로 테스트가 실패하는지 확인한다**

Run: `python -m pytest -q test/test_public_law_projection_service.py -k unicode_box`
Expected: FAIL because the malformed summary remains.

- [ ] **Step 3: Unicode Box Drawing 범위와 반복 경계만 거부한다**

```python
_BOX_DRAWING_RE = re.compile(r"[\u2500-\u257f]")

def _contains_table_fragment(value: str) -> bool:
    return bool(_BOX_DRAWING_RE.search(value)) or _contains_pipe_table_fragment(value)
```

- [ ] **Step 4: 정상 짧은 설명과 법령명·조문 보존 회귀를 실행한다**

Run: `python -m pytest -q test/test_public_law_projection_service.py test/test_supervisor_control_service.py`
Expected: PASS.

### Task 4: 인증 사용자 Resume Manifest와 프론트 hydration

**Files:**
- Create: `app/services/resume_manifest_service.py`
- Create: `app/web/resumeManifest.js`
- Create: `app/web/resumeManifest.test.js`
- Create: `backend/chatbot/test_resume_manifest.py`
- Modify: `backend/chatbot/repositories.py`
- Modify: `backend/chatbot/views.py`
- Modify: `backend/chatbot/urls.py`
- Modify: `app/web/apiClient.js`
- Modify: `app/web/authSession.js`
- Modify: `app/web/authSession.test.js`
- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `test/test_api_route_specs.py`
- Modify: `test/test_frontend_auth_session_contract.py`

**Interfaces:**
- Consumes: 인증된 `user_id`, 최신 소유 `ChatSession`, 공개 analysis job detail, 안전한 attachment 요약, report 참조.
- Produces: `resume_manifest.v1`과 프론트 `hydrateResumeManifest()` 결과.

- [ ] **Step 1: 인증·소유권·안전 projection API 실패 테스트를 작성한다**

```python
def test_resume_manifest_returns_only_latest_owned_session_and_safe_references(self):
    response = self.owner_client.get("/api/auth/resume/")
    self.assertEqual(response.status_code, 200)
    manifest = response.json()
    self.assertEqual(manifest["contract_version"], "resume_manifest.v1")
    self.assertEqual(manifest["session"]["session_id"], "ses_owner_latest")
    self.assertNotIn("s3://", repr(manifest))
    self.assertNotIn("raw_ocr_text", repr(manifest))

def test_resume_manifest_requires_authenticated_user(self):
    self.assertEqual(Client().get("/api/auth/resume/").status_code, 401)
```

- [ ] **Step 2: route 부재로 RED인지 확인한다**

Run: `python backend/manage.py test chatbot.test_resume_manifest --verbosity 2`
Expected: FAIL with route not found.

- [ ] **Step 3: 최신 소유 세션 조회와 순수 manifest 조합을 구현한다**

```python
def get_latest_owned_chat_session_record(owner_id: str) -> dict[str, Any] | None:
    session = (
        ChatSession.objects.filter(owner_id=owner_id)
        .prefetch_related("messages", "uploaded_files", "analysis_jobs", "reports")
        .order_by("-updated_at")
        .first()
    )
    if session is None:
        return None
    latest_job = session.analysis_jobs.order_by("-updated_at").first()
    return {
        "session": {
            "session_id": session.session_id,
            "status": session.status,
            "current_intent": session.current_intent,
            "updated_at": session.updated_at.isoformat(),
        },
        "conversation_messages": [
            {
                "message_id": message.message_id,
                "role": message.role,
                "content": message.content,
                "created_at": message.created_at.isoformat(),
            }
            for message in session.messages.order_by("created_at")
            if message.role in {"user", "assistant"}
        ],
        "followup_state": load_chat_followup_state(session.session_id) or {},
        "attachments": [uploaded_file_to_api(item) for item in session.uploaded_files.all()],
        "latest_job_id": latest_job.job_id if latest_job else None,
        "reports": [
            _report_record_summary(report)
            for report in session.reports.order_by("-updated_at")
        ],
    }

def build_resume_manifest(*, session_record, analysis_detail=None):
    if not isinstance(session_record, dict):
        return {
            "contract_version": "resume_manifest.v1",
            "has_resume": False,
            "session": None,
            "conversation_messages": [],
            "pending_questions": [],
            "facts": {},
            "attachments": [],
            "latest_analysis": None,
            "reports": [],
        }
    followup = session_record.get("followup_state")
    followup = followup if isinstance(followup, dict) else {}
    return {
        "contract_version": "resume_manifest.v1",
        "has_resume": True,
        "session": _project_session(session_record.get("session")),
        "conversation_messages": _project_messages(
            session_record.get("conversation_messages")
        ),
        "pending_questions": _project_pending_questions(
            followup.get("pending_questions")
        ),
        "facts": _project_facts(followup.get("facts")),
        "attachments": _project_attachments(session_record.get("attachments")),
        "latest_analysis": analysis_detail
        if isinstance(analysis_detail, dict)
        else None,
        "reports": _project_reports(session_record.get("reports")),
    }
```

- [ ] **Step 4: `GET /api/auth/resume/`를 user-only로 등록한다**

```python
path("auth/resume/", views.auth_resume, name="auth-resume")
```

`auth_resume`는 `_request_access_payload`와 기존 auth error envelope를 사용하고 `subject_type == "user"`일 때만 manifest를 조회한다.

- [ ] **Step 5: transient refresh 오류가 저장 인증을 지우지 않는 실패 테스트를 작성한다**

```javascript
test("clears stored authentication only for explicit 401 or 403 rejection", () => {
  assert.equal(shouldClearAuthentication(new Error("timeout")), false);
  assert.equal(shouldClearAuthentication({ status: 503 }), false);
  assert.equal(shouldClearAuthentication({ status: 401 }), true);
  assert.equal(shouldClearAuthentication({ status: 403 }), true);
});
```

- [ ] **Step 6: 현재 refresh effect가 모든 오류에서 삭제해 RED인지 확인한다**

Run: `node --test app/web/authSession.test.js`
Expected: FAIL because no public rejection predicate exists and the effect does not branch.

- [ ] **Step 7: `/auth/me/` 성공 뒤 manifest hydration을 구현한다**

```javascript
const manifest = await api.getResumeManifest({ identity: recoveredIdentity });
const hydrated = hydrateResumeManifest(manifest);
setSessionId(hydrated.sessionId);
setChatMessages(hydrated.chatMessages);
setRegisteredAttachments(hydrated.attachments);
setAnalysisResponse(hydrated.analysisResponse);
setReportList(hydrated.reports);
setCurrentReport(hydrated.currentReport);
if (hydrated.hasResume) setActiveRoute("chatbot");
```

- [ ] **Step 8: 자동 refresh catch는 `shouldClearAuthentication(error)`일 때만 logout하고 나머지는 상태를 보존한다**

```javascript
} catch (error) {
  if (!refreshEffectActive) return;
  if (!shouldClearAuthentication(error)) {
    setStatusMessage("로그인 갱신을 일시적으로 완료하지 못했습니다. 현재 상담은 유지됩니다.");
    return;
  }
  clearStoredAuthSession();
  // existing explicit logout state reset
}
```

- [ ] **Step 9: API·Node·프론트 계약 테스트를 실행한다**

Run: `python backend/manage.py test chatbot.test_resume_manifest --verbosity 1`
Run: `node --test app/web/authSession.test.js app/web/resumeManifest.test.js`
Run: `python -m pytest -q test/test_api_route_specs.py test/test_frontend_auth_session_contract.py`
Expected: PASS.

### Task 5: persisted report·이의신청서와 전체 회귀

**Files:**
- Test only: existing suites under `backend/chatbot/`, `test/`, `app/web/`.

**Interfaces:**
- Consumes: OCR/분류 확인 이후 persisted `report_id`와 report detail/document card 계약.
- Produces: 변경 없음. 기존 report/Case 엔진이 연결된다는 검증 증거만 남긴다.

- [ ] **Step 1: persisted report와 이의신청서 다운로드 연결을 검증한다**

Run: `python backend/manage.py test chatbot.test_canonical_user_flow_e2e chatbot.test_supervisor_reporting_pipeline --verbosity 1`
Expected: report 생성, 상세 조회, document confirmation, objection form 생성 PASS.

- [ ] **Step 2: 이미 통과한 앱 핫픽스 회귀를 실행한다**

Run: `python -m pytest -q test/test_chat_orchestration_service.py test/test_supervisor_control_service.py test/test_analysis_job_query_service.py test/test_public_law_projection_service.py`
Expected: PASS.

- [ ] **Step 3: 프론트 전체 Node 테스트와 프로덕션 빌드를 실행한다**

Run: `node --test app/web/*.test.js`
Expected: PASS.

Run: `npm --prefix app/web run build`
Expected: Vite production build PASS.

- [ ] **Step 4: Django system check와 변경 파일 diff를 검토한다**

Run: `python backend/manage.py check`
Expected: no issues.

Run: `git diff --check`
Expected: no whitespace errors.

## Self-Review

- Spec coverage: 직접 결함 4개와 persisted report/초안 연결 검증을 각각 Task 1~5에 매핑했다.
- Scope guard: `ai/**`, OCR/Vision 모델, AWS 적용·배포, 기존 report 엔진 변경은 계획에 없다.
- Privacy: Resume Manifest와 첨부 경계 DTO는 allowlist projection만 사용하고 URI/OCR/내부 오류를 제외한다.
- Type consistency: 프론트는 `resume_manifest.v1`의 `session`, `conversation_messages`, `latest_analysis`, `attachments`, `reports`를 `hydrateResumeManifest()`로만 소비한다.
- Placeholder scan: 금지된 placeholder 표현 없이 각 구현 단계에 호출 시그니처와 핵심 분기를 명시했다.
