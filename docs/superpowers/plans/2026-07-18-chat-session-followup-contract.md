# 채팅 세션·역질문 연속성 계약 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 역질문 상태를 기존 채팅 세션에 안전하게 저장하고 다음 메시지에서 서버 원본 상태를 복원한다.

**Architecture:** 전용 병합 서비스가 저장된 서버 사실·질문·상담 의도를 현재의 개인정보 보호 완료 payload에 결합한다. Django 저장소는 `ChatSession.metadata`와 `ChatMessage`에 최소 스냅샷을 원자적으로 저장·조회하고, 표준 채팅 뷰는 권한 검증 뒤 복원 및 `needs_input`/`case_ready` 저장을 호출한다.

**Tech Stack:** Python 3, Django ORM, pytest, Django TestCase, 기존 ChatSession/ChatMessage JSON metadata.

## Global Constraints

- 새 DB 모델·마이그레이션·작업 큐·리포트를 만들지 않는다.
- `protect_chat_input_payload` 이후의 값만 저장한다.
- 기존 `conversation_save_policy.v1`의 `pending`, `saved`, `session_only` 의미를 바꾸지 않는다.
- 서버 확인 사실이 클라이언트의 `facts`, `fact_sources`, `conversation_history`보다 우선한다.
- `scope_guidance`, `supervisor_unavailable`, `high_risk_handoff`의 기존 조기 반환 의미를 변경하지 않는다.
- Git stage, commit, push, PR 생성·병합은 사용자가 수행한다.

---

### Task 1: 서버 우선 역질문 병합 서비스

**Files:**
- Create: `app/services/chat_session_followup_service.py`
- Create: `test/test_chat_session_followup_service.py`

**Interfaces:**
- Consumes: 현재의 안전 처리된 채팅 payload와 저장소가 반환한 `chat_session_followup_state.v1` 사전.
- Produces: `merge_chat_followup_payload(payload: dict[str, Any], stored_state: dict[str, Any] | None) -> dict[str, Any]`.
- Produces: `build_chat_followup_snapshot(payload: dict[str, Any], chat_response: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]`.

- [x] **Step 1: 실패하는 순수 서비스 테스트를 작성한다.**

```python
def test_merge_preserves_server_confirmed_fact_over_client_confirmed_conflict() -> None:
    merged = merge_chat_followup_payload(
        {"facts": {"road_layout": {"value": "직선도로", "confirmed": True}}},
        {"facts": {"road_layout": {"value": "교차로", "confirmed": True}}},
    )
    assert merged["facts"]["road_layout"]["value"] == "교차로"


def test_merge_uses_saved_question_before_new_user_answer() -> None:
    merged = merge_chat_followup_payload(
        {"user_text": "신호등 없는 사거리였습니다."},
        {"pending_questions": [{"field": "road_layout", "question": "도로 형태를 알려주세요."}]},
    )
    assert merged["conversation_history"][-2:] == [
        {"role": "assistant", "content": "도로 형태를 알려주세요."},
        {"role": "user", "content": "신호등 없는 사거리였습니다."},
    ]
```

- [x] **Step 2: 테스트가 기능 부재로 실패하는지 확인한다.**

Run: `D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider test/test_chat_session_followup_service.py`

Expected: `ModuleNotFoundError` 또는 대상 함수 import 오류.

- [x] **Step 3: 최소 병합·스냅샷 구현을 작성한다.**

```python
FOLLOWUP_STATE_VERSION = "chat_session_followup_state.v1"

def merge_chat_followup_payload(payload, stored_state):
    merged = deepcopy(payload)
    server_facts = _fact_records(stored_state.get("facts"))
    merged["facts"] = {**_client_non_conflicting_facts(payload, server_facts), **server_facts}
    merged["conversation_history"] = _server_history_with_current_turn(stored_state, payload)
    merged["fact_sources"] = _merge_sources(server_facts, payload.get("fact_sources"))
    merged["fact_conflicts"] = _merge_conflicts(stored_state, payload)
    return merged
```

`_client_non_conflicting_facts`는 서버에 있는 field의 클라이언트 값을 삭제한다. 저장된 질문은 assistant turn으로, 현재 `user_text`는 마지막 user turn으로 추가한다. snapshot은 facts, sources, conflicts, pending questions, 구조화된 consultation state 및 길이 제한된 안전한 history만 포함한다.

- [x] **Step 4: 순수 서비스 테스트를 통과시킨다.**

Run: `D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider test/test_chat_session_followup_service.py`

Expected: 모든 테스트 PASS.

### Task 2: 세션 상태 저장·조회 저장소 경계

**Files:**
- Modify: `backend/chatbot/repositories.py:839-889, 939-1050, 4671-4750`
- Modify: `backend/chatbot/test_consultation_v2.py:526-613`

**Interfaces:**
- Consumes: `persist_chat_followup_state(payload, chat_response)`는 개인정보 보호 완료 payload와 `needs_input`/`case_ready` 응답.
- Produces: `{message_id, session_id, conversation_save_state, followup_state_version}` persistence summary.
- Consumes: `load_chat_followup_state(session_id)`.
- Produces: 안전한 저장 상태 또는 `None`.

- [x] **Step 1: Django 통합 테스트를 먼저 작성한다.**

```python
response = self.client.post("/api/chat/messages/", data=partial_accident_payload, content_type="application/json")
self.assertEqual(response.json()["status"], "needs_input")
self.assertTrue(ChatSession.objects.filter(session_id=session_id).exists())
self.assertTrue(ChatMessage.objects.filter(session__session_id=session_id).exists())
self.assertFalse(AnalysisJob.objects.filter(session__session_id=session_id).exists())
self.assertFalse(AgentWorkItem.objects.filter(job__session__session_id=session_id).exists())
```

- [x] **Step 2: 실패가 현행 조기 반환 때문에 발생하는지 확인한다.**

Run: `D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe backend\manage.py test chatbot.test_consultation_v2 -v 1`

Expected: `ChatSession.DoesNotExist` 또는 저장된 `ChatMessage`가 없다는 assertion failure.

- [x] **Step 3: 저장소 함수를 최소 구현한다.**

```python
def persist_chat_followup_state(payload, chat_response):
    session = _get_or_create_session(
        chat_response.get("session_id"),
        owner_id=_owner_id(payload),
        guest_id=_payload_guest_id(payload),
    )
    with transaction.atomic():
        session = ChatSession.objects.select_for_update().get(pk=session.pk)
        session.metadata = {
            **_metadata_with_conversation_save_state(...),
            "chat_followup_state": build_chat_followup_snapshot(...),
        }
        session.save(update_fields=["metadata", "current_intent", "updated_at"])
        ChatMessage.objects.update_or_create(... role=MessageRole.USER ...)
```

`load_chat_followup_state`는 `ChatSession.metadata["chat_followup_state"]`가 지정한 계약 버전일 때만 반환한다. 저장 전후 모두 `_get_or_create_session`의 소유권 규칙을 재사용한다. AnalysisJob, AgentWorkItem, HistoryEvent를 생성하지 않는다.

- [x] **Step 4: 저장·작업 미생성 통합 테스트를 통과시킨다.**

Run: `D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe backend\manage.py test chatbot.test_consultation_v2 -v 1`

Expected: 대상 테스트 PASS.

### Task 3: 표준 채팅 진입점 연결과 권한 회귀

**Files:**
- Modify: `backend/chatbot/views.py:89-140, 1168-1250`
- Modify: `backend/chatbot/test_consultation_v2.py:526-613`
- Modify: `backend/chatbot/test_production_hardening.py`

**Interfaces:**
- Consumes: 권한 검사를 통과한 `identity_body`, `load_chat_followup_state`.
- Produces: 병합 payload를 `submit_message`에 전달하고, `needs_input`/`case_ready` 응답에 persistence summary를 포함한다.

- [x] **Step 1: 다음 두 API 회귀 테스트를 작성한다.**

```python
def test_followup_restores_server_question_and_fact_without_client_history(self):
    first = self.client.post("/api/chat/messages/", data=initial_payload, content_type="application/json")
    second = self.client.post(
        "/api/chat/messages/",
        data={"session_id": first.json()["session_id"], "user_text": "신호등 없는 사거리입니다."},
        content_type="application/json",
    )
    self.assertNotIn("road_layout", second.json()["consultation_state"]["v2"]["readiness"]["missing_fields"])


def test_other_owner_cannot_restore_followup_state(self):
    response = other_client.post("/api/chat/messages/", data={"session_id": owned_session_id, "user_text": "답변"}, content_type="application/json")
    self.assertEqual(response.status_code, 403)
```

또한 동일 session에 `facts: {road_layout: {value: ..., confirmed: true}}`와 가짜 `conversation_history`를 보내도 저장된 `road_layout`이 유지되는 테스트를 추가한다.

- [x] **Step 2: 현재 구현에서 복원 또는 서버 우선 assertion이 실패하는지 확인한다.**

Run: `D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe backend\manage.py test chatbot.test_consultation_v2 chatbot.test_production_hardening -v 1`

Expected: follow-up 상태가 복원되지 않아 새 회귀 테스트 FAIL.

- [x] **Step 3: 뷰를 연결한다.**

```python
if requested_session_id and session_access is not None:
    access = authorize_resource_access(session_access, identity_body)
    if not access["allowed"]:
        return _object_access_denied_response(request, access)
    identity_body = merge_chat_followup_payload(
        identity_body,
        load_chat_followup_state(requested_session_id),
    )

chat_response = submit_message(identity_body)
if chat_response["status"] in {"needs_input", "case_ready"}:
    chat_response["persistence"] = persist_chat_followup_state(identity_body, chat_response)
```

`high_risk_handoff`은 현행 조기 반환을 유지하고 follow-up persistence를 추가하지 않는다. 저장 실패 시 현재 chat planning 실패와 같은 환불·서버 오류 경로를 사용한다.

- [x] **Step 4: 상담·권한·scope 회귀를 통과시킨다.**

Run: `D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe backend\manage.py test chatbot.test_consultation_v2 chatbot.test_production_hardening -v 1`

Expected: 대상 테스트 PASS, scope guidance 테스트의 작업 미생성 assertion PASS.

### Task 4: 준비도 추적 및 최종 회귀

**Files:**
- Modify: `docs/ops/project-readiness-master-checklist.md:128-136, 177-184`
- Modify: `docs/superpowers/plans/2026-07-18-chat-session-followup-contract.md`

**Interfaces:**
- Consumes: #224 구현 및 테스트 증거.
- Produces: PR 전에는 `[~] #224` 진행 표시, 병합 후 다음 작업에서 `[x] #224 / PR 번호` 완료 표시.

- [x] **Step 1: #224와 직접 관련된 준비도 항목을 진행 상태로 표시한다.**

```markdown
- [~] #224 채팅 세션·역질문·서버 상태 복원 계약
4. [~] #224 사건 메모리·역질문·채팅 세션 계약
```

- [x] **Step 2: 변경 파일 검사를 실행한다.**

Run: `git diff --check`

Expected: 출력 없음.

- [x] **Step 3: 전체 관련 테스트를 실행한다.**

Run: `D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider test/test_chat_session_followup_service.py test/test_supervisor_control_service.py`

Expected: 모든 테스트 PASS.

Run: `D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe backend\manage.py test chatbot.test_consultation_v2 chatbot.test_production_hardening -v 1`

Expected: 모든 테스트 PASS.

- [x] **Step 4: 사용자에게 Git handoff를 제공한다.**

사용자가 변경 파일만 stage, commit, push하고 PR을 만들 수 있도록 정확한 PowerShell 명령과 PR 설명을 제공한다. PR 전에는 구현이 설계의 서버 우선·권한·개인정보·작업 미생성 기준을 모두 만족하는지 다시 검토한다.
