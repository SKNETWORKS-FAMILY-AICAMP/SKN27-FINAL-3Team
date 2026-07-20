# 비신뢰 OCR/RAG 프롬프트 인젝션 경계 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 비신뢰 OCR/RAG·대화·첨부 자료가 LLM 요청 또는 반환 DTO의 실행 제어로 승격되지 않는 것을 실제 Supervisor/Planner 호출 경로에서 회귀 테스트로 고정한다.

**Architecture:** 실제 State/Planner 함수를 실행하고 `_request_supervisor_json()`만 가짜 Provider로 대체한다. OCR/RAG 원문과 제어 메타데이터는 LLM 요청에서 제외하며, 사용자·대화·제한된 첨부 설명자는 `untrusted_context`로만 전달한다. 자유 텍스트의 사실관계 인용은 허용하되 Agent·owner·node·stage·보고서 준비 상태는 fallback 계약이 결정한다.

**Tech Stack:** CI Python 3.13, 로컬 프로젝트 가상환경 Python 3.14, pytest, `app.services.supervisor_llm_service`

## Global Constraints

- Provider, S3, 실제 OCR/RAG, 테스트 외 DB 호출은 하지 않는다. `_request_supervisor_json()`만 patch한다.
- OCR/RAG 원문·storage URI·`role`·`node_code`·`tool_call`은 LLM 요청 전체에 포함하지 않는다.
- `purpose`와 `scan_status`는 `untrusted_context`의 참조용 설명자로만 허용한다.
- 자유 텍스트에 사용자 사실관계가 포함되어도 실행 권한으로 해석하지 않는다. Agent·owner·node·stage·보고서 준비 상태·실행 단계는 fallback 계약을 벗어나면 안 된다.
- 로컬 검증은 `D:\\dev\\project\\SKN27-FINAL-3Team\\.venv\\Scripts\\python.exe`를 사용한다. bare `python`에는 `python-docx`가 없어 전체 pytest 수집이 중단된다.
- #249는 `[x]`, #251은 PR 병합과 필수 CI 통과 전까지 `[~]`다.

---

### Task 1: 실제 Supervisor 요청과 상태 제어 경계 검증

**Files:**
- Modify: `test/test_supervisor_llm_service.py`

**Interfaces:**
- Consumes: `build_supervisor_state_with_optional_llm(payload, scenario, fallback_builder)`
- Produces: 요청 DTO 캡처와 State의 fallback 제어 고정을 검증하는 테스트

- [x] **Step 1: 비신뢰 입력 payload와 요청 검증 보조 함수를 추가한다.**

```python
payload = _untrusted_injection_payload()
captured: list[dict] = []

def fake_request(_config, request_payload):
    captured.append(request_payload)
    return candidate

_assert_captured_request_is_untrusted_only(captured[0], payload)
```

검증 항목은 시스템 프롬프트의 비신뢰 규칙, `untrusted_context` 내부의 사용자·대화·제한된 첨부 설명자, OCR/RAG 원문·storage URI·`role`·`node_code`·`tool_call`의 요청 부재다.

- [x] **Step 2: 악성 문맥이 서버 제어를 바꾸지 못하는 State 테스트를 추가한다.**

```python
candidate = _valid_state_candidate()
candidate["conversation_summary"] = payload["user_text"]

state = service.build_supervisor_state_with_optional_llm(
    payload=payload,
    scenario="fine_notice",
    fallback_builder=_fallback_builder,
)

assert state["llm"]["status"] == "used"
assert state["stage"] == "need_more_input"
assert [item["node_code"] for item in state["agent_input_packages"]] == [
    "fine_notice_analysis",
    "objection_report_generation",
]
assert [item["owner"] for item in state["agent_input_packages"]] == [
    "workzion2",
    "hi20260204-maker",
]
assert all(item["status"] == "waiting_for_fields" for item in state["agent_input_packages"])
assert state["reporting_payload"]["stage"] == "need_more_input"
```

- [x] **Step 3: 정상 첨부 목적값이 서버 허용 Agent를 과차단하지 않는 회귀 테스트를 추가한다.**

```python
state = service.build_supervisor_state_with_optional_llm(
    payload={
        "user_text": "과태료 고지서를 확인해 주세요.",
        "attachments": [
            {
                "attachment_id": "att_notice",
                "purpose": "fine_notice",
                "scan_status": "clean",
            }
        ],
    },
    scenario="fine_notice",
    fallback_builder=_fallback_builder,
)

assert state["llm"]["status"] == "used"
assert state["agent_input_packages"][0]["node_code"] == "fine_notice_analysis"
assert state["agent_input_packages"][0]["owner"] == "workzion2"
```

### Task 2: Planner의 allowlist·fail-closed 경계 검증

**Files:**
- Modify: `test/test_supervisor_llm_service.py`

**Interfaces:**
- Consumes: `build_analysis_plan_with_optional_llm(payload, scenario, requested_status, fallback_plan, supervisor_state)`
- Produces: unknown Agent의 fail-closed와 참조 텍스트의 비실행성을 검증하는 Planner 테스트

- [x] **Step 1: 기존 unknown-Agent Planner 테스트를 악성 payload와 요청 캡처로 확장한다.**

```python
plan = service.build_analysis_plan_with_optional_llm(
    payload=_untrusted_injection_payload(),
    scenario="fine_notice",
    requested_status="success",
    fallback_plan=_fallback_plan(),
    supervisor_state=_fallback_builder({}, "fine_notice"),
)

assert plan["llm_planner"]["status"] == "failed"
assert plan["llm_planner"]["reason"] == "invalid_contract"
assert plan["steps"] == []
assert plan["agent_input_packages"] == []
_assert_captured_request_is_untrusted_only(captured[0], payload)
```

- [x] **Step 2: 자유 텍스트를 포함한 정상 후보가 allowlist 밖 패키지를 만들지 않는지 검증한다.**

```python
candidate = deepcopy(_fallback_plan())
candidate["input_summary"] = {"summary": payload["user_text"]}

plan = service.build_analysis_plan_with_optional_llm(
    payload=payload,
    scenario="fine_notice",
    requested_status="success",
    fallback_plan=fallback_plan,
    supervisor_state=_fallback_builder({}, "fine_notice"),
)

assert plan["llm_planner"]["status"] == "used"
assert [item["node_code"] for item in plan["agent_input_packages"]] == [
    "fine_notice_analysis",
    "law_ground_search",
]
assert {item["node_code"] for item in plan["steps"]} == {
    "input_context_validation",
    "fine_notice_analysis",
    "law_ground_search",
    "agent_result_validation",
}
```

- [x] **Step 3: 집중 pytest를 실행한다.**

Run: `& 'D:\\dev\\project\\SKN27-FINAL-3Team\\.venv\\Scripts\\python.exe' -m pytest -q --timeout=30 test/test_supervisor_llm_service.py`

Expected: PASS. 요청 격리, State 필수 입력 유지, unknown Agent fail-closed, Planner allowlist 보존, 정상 `fine_notice` 흐름을 확인한다.

### Task 3: 체크리스트 반영과 전체 회귀 검증

**Files:**
- Modify: `docs/ops/project-readiness-master-checklist.md:57-58`
- Test: `test/test_supervisor_llm_service.py` 및 전체 pytest

- [x] **Step 1: 체크리스트의 두 행을 갱신한다.**

```markdown
- [x] 운영 로그 개인정보 노출 회귀 테스트 — #249 / PR #250
- [~] 프롬프트 인젝션과 비신뢰 OCR/RAG 자료가 시스템 지시·도구 호출 조건으로 작동하지 않도록 하는 경계 — #251
```

- [x] **Step 2: 문서 형식과 집중 테스트를 검증한다.**

Run: `git diff --check`

Expected: 종료 코드 0.

- [x] **Step 3: 전체 pytest를 실행한다.**

Run: `& 'D:\\dev\\project\\SKN27-FINAL-3Team\\.venv\\Scripts\\python.exe' -m pytest -q --timeout=30`

Expected: PASS.

## Self-Review

- Spec coverage: 실제 State/Planner 호출, OCR/RAG 원문 미전달, `role`/`node_code`/`tool_call` 격리, 필수 입력 유지, unknown Agent fail-closed, 정상 첨부 목적값 비과차단, #249/#251 체크리스트, 집중·전체 pytest를 반영했다.
- Scope: 원문 문자열 차단처럼 정상 법률 사실관계를 훼손하는 정책은 제외하고, 실행 제어 계약만 검증한다.
- Type consistency: 테스트는 기존 `dict`, `list`, fake Provider와 기존 fallback helper 계약만 사용한다.
