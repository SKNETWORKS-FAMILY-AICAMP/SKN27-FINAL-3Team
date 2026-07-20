# 비신뢰 OCR/RAG 프롬프트 인젝션 경계 설계

## 목적

사용자 입력, 대화 이력, OCR 결과, RAG 검색 자료에 포함된 공격 문구가 Supervisor의 시스템 지시, 허용 Agent, 도구 호출 조건, 보고서 준비 상태를 바꾸지 못하도록 실제 Supervisor·Planner 호출 경계의 회귀 테스트로 고정한다.

## 현재 확인된 상태

- `app/services/supervisor_llm_service.py`의 시스템 프롬프트는 사용자·대화·첨부·검색 자료를 비신뢰 데이터로 선언하고, 정책·노드 allowlist·도구 권한을 변경할 수 없다고 명시한다.
- `_untrusted_llm_context()`는 사용자 텍스트와 대화 이력을 `reference_only_not_authoritative` 계약으로 감싸며, 첨부는 `attachment_id`, `purpose`, `scan_status`만 전달한다.
- 현재 `test/test_supervisor_llm_service.py`는 `_llm_request_payload()`와 `_llm_plan_request_payload()`를 직접 호출해 OCR/RAG 원문, `role`, `node_code`, `tool_call`, storage URI가 공개 LLM 요청 제어 영역에 없음을 검사한다.
- 현재 단위 테스트만으로는 실제 `build_supervisor_state_with_optional_llm()`와 `build_analysis_plan_with_optional_llm()`이 이 안전한 요청 작성 경계를 계속 통과하는지는 보장하지 못한다.

## 선택한 접근

Supervisor와 Planner의 실제 호출 함수를 실행하되 `_request_supervisor_json()`만 가짜 함수로 대체한다. 가짜 함수는 외부 Provider를 호출하지 않고 요청 DTO를 캡처한 뒤, 테스트가 제공한 후보 응답을 반환한다.

이 방식은 프롬프트 구성, 후보 응답 정규화, fallback allowlist 검증, fail-closed 처리까지 실제 실행 경로로 검증한다. OCR 정확도, RAG 검색 품질, 새로운 도구나 Provider 구현은 변경하지 않는다.

## 설계 범위

### A. Supervisor 상태 생성 호출 경계

악성 `user_text`, `conversation_history`, 첨부의 `ocr_text`, `retrieved_evidence`에 다음과 같은 지시를 넣는다.

- `role=system` 승격 요구
- 임의 `unknown_agent` 호출 요구
- 관리자 도구 호출 요구
- `report_ready=true` 또는 문서 즉시 생성 요구

`build_supervisor_state_with_optional_llm()`을 호출한 뒤 가짜 Provider가 받은 요청을 검사한다.

- 시스템 프롬프트에는 공격 원문이 없고 비신뢰·참조 전용 규칙이 포함돼야 한다.
- 사용자·대화 원문은 `untrusted_context` 안에만 존재해야 한다.
- OCR 원문, RAG 원문, 첨부의 `role`/`node_code`/`tool_call`, storage URI는 LLM 요청의 제어 계약에 없어야 한다.
- 정상 후보 응답은 기존 fallback의 허용 Agent와 서버 필수 입력 상태를 벗어나지 않아야 한다.

### B. Planner 호출과 fail-closed 경계

동일한 비신뢰 자료로 `build_analysis_plan_with_optional_llm()`을 호출한다. 가짜 Provider는 fallback에 없는 `unknown_agent`와 임의 Agent 소유자를 포함한 후보 계획을 반환한다.

- Planner 시스템 프롬프트와 `untrusted_context`의 분리 규칙은 A와 동일해야 한다.
- 후보 계획이 fallback allowlist 밖의 Agent를 요구하면 결과는 `llm_planner.status == "failed"`, `reason == "invalid_contract"`이어야 한다.
- 실패 결과의 `steps`와 `agent_input_packages`는 비어 있어 실제 Agent 실행이나 보고서 생성으로 이어지지 않아야 한다.

### C. 체크리스트 상태

`docs/ops/project-readiness-master-checklist.md`에서 다음 두 행만 변경한다.

```markdown
- [x] 운영 로그 개인정보 노출 회귀 테스트 — #249 / PR #250
- [~] 프롬프트 인젝션과 비신뢰 OCR/RAG 자료가 시스템 지시·도구 호출 조건으로 작동하지 않도록 하는 경계 — #251
```

PR 병합과 필수 CI 통과 전에는 #251 행을 `[x]`로 바꾸지 않는다.

## 변경 파일

- 수정: `test/test_supervisor_llm_service.py`
  - 실제 Supervisor 상태 생성과 Planner 생성 함수를 통과하는 프롬프트 인젝션 회귀 테스트를 추가한다.
- 수정: `docs/ops/project-readiness-master-checklist.md`
  - #249 완료와 #251 진행 상태를 반영한다.

서비스 코드, 도메인 Agent, OCR/RAG 검색 구현, 외부 Provider 설정은 변경하지 않는다. 새 테스트가 현재 구현의 계약 위반을 재현하는 경우에만 그 최소 경계 코드를 별도 설계 검토 후 수정한다.

## 테스트와 완료 기준

- 테스트는 `SUPERVISOR_LLM_ENABLED=1` 및 테스트용 API 키 환경에서 실행하되, `_request_supervisor_json()` 패치로 외부 네트워크 호출을 차단한다.
- `test/test_supervisor_llm_service.py`의 집중 테스트가 통과한다.
- 전체 `python -m pytest -q --timeout=30`이 통과한다.
- 공격 문자열이 시스템 프롬프트, 허용 Agent 목록, 도구 호출 조건, 결과 계획의 실행 가능 단계에 반영되지 않는다.
- #251 체크리스트 행은 PR 병합 전까지 `[~]` 상태다.

## 제외 범위

- OCR 추출 정확도, 법령/RAG 검색 품질, 도메인 판단 규칙 변경
- 개별 도메인 Agent의 프롬프트 전면 재설계
- 새 LLM Provider, 도구, 외부 데이터 소스 도입
- 기존 DB 원문 이관과 보존 정책 변경
