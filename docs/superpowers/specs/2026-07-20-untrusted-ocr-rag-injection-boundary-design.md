# 비신뢰 OCR/RAG 프롬프트 인젝션 경계 설계

## 목적

사용자 입력, 대화 이력, OCR 결과, RAG 검색 자료에 포함된 공격 문구가 Supervisor의 시스템 지시, 허용 Agent, 도구 호출 조건, 보고서 준비 상태를 바꾸지 못하도록 실제 Supervisor·Planner 호출 경계의 회귀 테스트로 고정한다.

## 현재 확인된 상태

- `app/services/supervisor_llm_service.py`의 시스템 프롬프트는 사용자·대화·첨부·검색 자료를 비신뢰 데이터로 선언하고, 정책·노드 allowlist·도구 권한을 변경할 수 없다고 명시한다.
- `_untrusted_llm_context()`는 사용자 텍스트와 대화 이력만 `reference_only_not_authoritative` 계약으로 감싼다. 첨부는 `attachment_id`, `purpose`, `scan_status`라는 제한된 설명자만 전달한다.
- OCR 원문과 RAG 원문은 `reference_only`로 전달하는 것이 아니라 Supervisor/Planner의 LLM 요청에서 **완전히 제외**한다. 이는 이슈의 비신뢰 경계 요구보다 더 좁고 안전한 현행 계약이다.
- 현재 `test/test_supervisor_llm_service.py`는 `_llm_request_payload()`와 `_llm_plan_request_payload()`를 직접 호출해 OCR/RAG 원문, `role`, `node_code`, `tool_call`, storage URI가 LLM 요청에 없음을 검사한다. 또한 실제 호출 함수에서 unknown Agent와 서버 필수 입력 보호를 각각 검증한다.
- 다만 현재 테스트는 실제 State/Planner 호출이 안전한 요청 DTO를 계속 사용한다는 점과, 비신뢰 문구가 공개 결과 DTO에 되돌아오지 않는다는 점을 함께 고정하지 않는다.

## 선택한 접근

Supervisor와 Planner의 실제 호출 함수를 실행하되 `_request_supervisor_json()`만 가짜 함수로 대체한다. 가짜 함수는 외부 Provider를 호출하지 않고 요청 DTO를 캡처한 뒤, 테스트가 제공한 후보 응답을 반환한다.

이 방식은 프롬프트 구성, 후보 응답 정규화, fallback allowlist 검증, fail-closed 처리까지 실제 실행 경로로 검증한다. OCR 정확도, RAG 검색 품질, 새로운 도구나 Provider 구현은 변경하지 않는다.

공개 DTO는 Supervisor 상태와 Planner 계획의 반환 계약으로 한정한다. 이 계약에서는 비신뢰 입력이 Agent/owner/node/stage/보고서 준비 여부·도구 관련 제어 필드로 반영되면 안 된다. 사용자 사실관계가 요약·질문·설명 같은 자유 텍스트에 인용될 수는 있으나 실행 권한이 아니며, 다음 LLM 호출에서는 다시 `untrusted_context`로만 전달된다. 원문 문자열의 부분 일치 차단은 정상 `fine_notice` 같은 서버 허용 식별자까지 막으므로 사용하지 않는다.

## 설계 범위

### A. Supervisor 상태 생성 호출 경계

악성 `user_text`, `conversation_history`, 첨부의 `ocr_text`, `purpose`, `scan_status`, `retrieved_evidence`에 다음과 같은 지시를 넣는다.

- `role=system` 승격 요구
- 임의 `unknown_agent` 호출 요구
- 관리자 도구 호출 요구
- `report_ready=true` 또는 문서 즉시 생성 요구

`build_supervisor_state_with_optional_llm()`을 호출한 뒤 가짜 Provider가 받은 요청을 검사한다.

- 시스템 프롬프트에는 공격 원문이 없고 비신뢰·참조 전용 규칙이 포함돼야 한다.
- 사용자·대화·제한된 첨부 설명자 원문은 `untrusted_context` 안에만 존재해야 하며, 시스템 프롬프트나 fallback 제어 계약으로 승격되면 안 된다.
- OCR 원문, RAG 원문, 첨부의 `role`/`node_code`/`tool_call`, storage URI는 LLM 요청 전체에 없어야 한다.
- `purpose`와 `scan_status`에 들어간 공격 문구는 `untrusted_context` 안에만 존재하고, 허용 Agent 목록·실행 단계·도구 관련 제어 영역에 영향을 주지 않아야 한다.
- 자유 텍스트가 공격 원문을 인용하더라도 Agent/owner/node/stage/보고서 준비 상태를 바꾸지 않아야 한다. fallback의 필수 입력이 남아 있으면 State는 `need_more_input`과 서버가 정한 패키지 상태를 유지해야 한다.
- 기존 `test_supervisor_llm_does_not_promote_server_required_input_to_ready`는 서버 필수 입력을 LLM이 완료 처리하지 못함을 계속 담당한다. 새 테스트는 이 기존 보장을 복제하지 않는다.

### B. Planner 호출과 fail-closed 경계

동일한 비신뢰 자료로 `build_analysis_plan_with_optional_llm()`을 호출한다. 가짜 Provider는 fallback에 없는 `unknown_agent`, 임의 Agent 소유자, 공격 문자열을 포함한 후보 계획을 반환한다.

- Planner 시스템 프롬프트와 `untrusted_context`의 분리 규칙은 A와 동일해야 한다. 현재 시스템에는 LLM function/tool-calling 실행기가 없으므로, 여기서의 도구 호출 보호는 비신뢰 `tool_call` 값이 요청 제어 계약·Agent 계획·실행 단계에 유입되지 않는다는 뜻이다.
- 후보 계획이 fallback allowlist 밖의 Agent를 요구하면 결과는 `llm_planner.status == "failed"`, `reason == "invalid_contract"`이어야 한다.
- 실패 결과의 `steps`와 `agent_input_packages`는 비어 있어 실제 Agent 실행이나 보고서 생성으로 이어지지 않아야 한다.
- Planner의 `input_summary` 등 설명 필드는 비신뢰 문구를 포함할 수 있으나, fallback 밖의 Agent·step·owner·실행 상태를 추가하거나 바꾸지 않아야 한다.

### C. 체크리스트 상태

`docs/ops/project-readiness-master-checklist.md`에서 다음 두 행만 변경한다.

```markdown
- [x] 운영 로그 개인정보 노출 회귀 테스트 — #249 / PR #250
- [~] 프롬프트 인젝션과 비신뢰 OCR/RAG 자료가 시스템 지시·도구 호출 조건으로 작동하지 않도록 하는 경계 — #251
```

PR 병합과 필수 CI 통과 전에는 #251 행을 `[x]`로 바꾸지 않는다.

## 변경 파일

- 수정: `test/test_supervisor_llm_service.py`
  - 실제 Supervisor 상태 생성 호출에서 캡처한 Provider 요청과 반환 DTO를 함께 검증하는 회귀 테스트를 추가한다.
  - 기존 unknown Agent Planner fail-closed 테스트를 악성 입력·요청 캡처·반환 DTO 검증까지 확장한다.
  - 기존 unknown Agent State 테스트와 서버 필수 입력 보호 테스트는 중복 추가하지 않고, 각각의 기존 책임을 유지한다.
- 수정: `docs/ops/project-readiness-master-checklist.md`
  - #249 완료와 #251 진행 상태를 반영한다.

현재 State/Planner 정규화가 이 제어 계약을 이미 보장하는지 먼저 회귀 테스트로 고정한다. 원문 부분 일치 차단은 정상 서버 식별자를 과차단하므로 서비스 코드에 추가하지 않는다. 새 테스트가 실제 제어 계약 위반을 재현하는 경우에만 그 최소 경계 코드를 수정하며, 도메인 Agent, OCR/RAG 검색 구현, 외부 Provider 설정은 변경하지 않는다.

## 테스트와 완료 기준

- 테스트는 `SUPERVISOR_LLM_ENABLED=1` 및 테스트용 API 키 환경에서 실행하되, `_request_supervisor_json()` 패치로 외부 네트워크 호출을 차단한다.
- `test/test_supervisor_llm_service.py`의 집중 테스트가 통과한다.
- 전체 `python -m pytest -q --timeout=30`이 통과한다.
- 공격 문자열은 시스템 프롬프트, fallback allowlist, Agent/owner/node/stage/보고서 준비 제어 필드, 결과 계획의 실행 가능 단계에 반영되지 않는다.
- 자유 텍스트에서의 사실관계 인용은 허용하되, 다음 호출에서도 `untrusted_context`로만 취급되고 실행 제어로 승격되지 않는다.
- #251 체크리스트 행은 PR 병합 전까지 `[~]` 상태다.

## 제외 범위

- OCR 추출 정확도, 법령/RAG 검색 품질, 도메인 판단 규칙 변경
- 개별 도메인 Agent의 프롬프트 전면 재설계
- 새 LLM Provider, 도구, 외부 데이터 소스 도입
- 기존 DB 원문 이관과 보존 정책 변경
