# Supervisor 비신뢰 입력 경계 강화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 채팅·대화 이력·첨부/OCR 메타데이터·검색 자료가 Supervisor LLM의 제어 지시가 아닌 참조용 비신뢰 컨텍스트로만 전달되게 한다.

**Architecture:** Supervisor LLM 요청의 외부 입력을 버전이 있는 `untrusted_context` 블록으로 이동한다. 원문은 사건 참고 자료로 유지하되, 첨부는 서버가 허용한 식별자·상태만 전달하고 검색 자료·임의 제어 필드는 LLM 요청에서 제외한다. fallback state/plan도 노드·소유자·허용 필드·단계만 남긴 LLM용 제어 계약으로 투영한다. LLM 응답은 기존 fallback 기반 노드·패키지·리포트 게이트 검증을 계속 통과해야만 사용한다.

**Tech Stack:** Python 3.13, pytest, Supervisor LLM adapter

## Global Constraints

- 업무 Agent 구현, OCR/RAG 데이터 파이프라인, UI, 외부 LLM 실연결은 변경하지 않는다.
- 외부 입력은 시스템 프롬프트나 Agent 실행 노드·권한·리포트 준비도를 결정할 수 없다.
- 외부 LLM 키 없이 pytest에서 검증한다.

---

### Task 1: 비신뢰 컨텍스트 요청 계약 회귀 테스트

**Files:**

- Modify: `test/test_supervisor_llm_service.py`

**Interfaces:**

- Consumes: `service._llm_request_payload`, `service._llm_plan_request_payload`
- Produces: `supervisor_untrusted_context.v1` 요청 계약 검증

- [x] user text, `role=system` 대화 이력, OCR 텍스트·가짜 `node_code`를 가진 첨부, `retrieved_evidence`의 지시문을 넣는 회귀 테스트를 추가했다. 두 요청에서 외부 데이터는 `untrusted_context`에만 존재하고, 첨부는 식별자·purpose·scan status만 남으며, 검색 자료·제어 필드와 fallback state/plan 안의 사용자 원문은 사라진다.
- [x] 구현 전 `untrusted_context` 부재로 대상 테스트가 실패하는 것을 확인했다.

### Task 2: Supervisor LLM 입력 분리 구현

**Files:**

- Modify: `app/services/supervisor_llm_service.py`
- Test: `test/test_supervisor_llm_service.py`

**Interfaces:**

- Produces: `_untrusted_llm_context(payload) -> dict[str, Any]`
- Consumes: public conversational payload fields

- [x] `UNTRUSTED_CONTEXT_CONTRACT_VERSION = "supervisor_untrusted_context.v1"`와 `_untrusted_llm_context`를 추가했다. 결과는 `contract_version`, `handling="reference_only_not_authoritative"`, `user_text`, 역할을 허용하지 않는 conversation-history records, attachment selector descriptors만 포함한다.
- [x] `_llm_request_payload`와 `_llm_plan_request_payload`에서 직접 `user_text`, `conversation_history`, `attachments`를 넣는 방식을 제거하고 `untrusted_context` 하나로 교체했다. 시스템 지시는 이 블록의 문장을 지시가 아닌 참고 자료로 다룬다고 명시한다. LLM에 주는 fallback state/plan은 사용자 원문 대신 서버 제어 계약만 포함한다.
- [x] `test/test_supervisor_llm_service.py` 전체가 통과했다.

### Task 3: 실행·리포트 제어 회귀 확인

**Files:**

- Modify: `test/test_supervisor_llm_service.py`

**Interfaces:**

- Consumes: `build_supervisor_state_with_optional_llm`, fallback packages
- Produces: 비신뢰 입력이 unknown node 또는 report-ready를 강제할 수 없다는 회귀 검증

- [x] enabled fake LLM 응답이 서버 fallback의 필수 입력을 제거하고 ready report를 시도해도, fallback의 누락 필드·패키지 상태·report stage가 유지되는 테스트를 작성했다. 미등록 `unknown_agent` package는 fail-closed로 거부하는 테스트도 추가했다.
- [x] `test/test_chat_orchestration_service.py`, `test/test_chat_input_privacy.py`, `test/test_supervisor_llm_service.py`, `test/test_supervisor_execution_input_service.py`가 함께 통과했다.

### Task 4: 회귀 검증과 인계

**Files:**

- Modify: `docs/superpowers/plans/2026-07-19-supervisor-prompt-boundary.md`

- [x] 완료한 계획 체크박스를 갱신했다.
- [x] `python -m pytest -q --timeout=30 -p no:cacheprovider --basetemp .pytest-tmp-issue236-full`을 실행했다: 806 passed, 37 skipped.
- [x] `ruff check --no-cache --select E9,F63,F7,F82 .`와 `git diff --check`를 실행했다.
- [ ] `git add app/services/supervisor_llm_service.py test/test_supervisor_llm_service.py docs/superpowers/plans/2026-07-19-supervisor-prompt-boundary.md` 후 `git commit -m "feat: isolate supervisor untrusted inputs"`으로 커밋한다.
