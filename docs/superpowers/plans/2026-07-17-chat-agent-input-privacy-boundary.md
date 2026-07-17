# 채팅·에이전트 실행 입력 보호 경계 구현 계획

> 이 작업은 #219의 승인된 범위만 구현한다. Git stage, commit, push, PR 생성과 머지는 사용자가 수행한다.

**목표:** `/api/chat/messages/`와 `/api/agent-plan/`에서 정책상 차단 입력을 부수 효과 전에 거부하고, 원문을 노출하지 않는 400 응답을 반환한다.

**구조:** 두 뷰는 요청 신원 보강 직후 `protect_chat_input_payload()`를 호출한다. `ChatInputRejected`는 #217 분석 API와 같은 `chat_input_privacy.v1` 오류 본문으로 변환한다. 분석 API 전용으로 이름 붙은 기존 응답 도우미는 세 경로가 함께 쓰는 공통 도우미로 일반화한다.

**기술:** Django `JsonResponse`, 기존 `app.security.chat_input_privacy`, Django `SimpleTestCase`, pytest/OpenAPI 생성 검증.

## 작업 1: 회귀 테스트를 먼저 추가

**수정:** `backend/chatbot/test_production_hardening.py`

- [x] `submit_chat_message()`에 차단 대상 입력을 전달한다.
- [x] 응답이 400, `error.code == "chat_input_rejected"`, `required_action == "remove_sensitive_input"`인지 확인한다.
- [x] 원문, `record_usage_event`, `submit_message`, `enqueue_analysis_job_work` 호출이 없음을 확인한다.
- [x] `run_agent_plan()`에 동일 입력을 전달해 400과 원문 비노출, `submit_message`, `execute_agent_plan`, `enqueue_analysis_job_work`, `persist_analysis_job_execution` 미호출을 확인한다.
- [x] 변경 전에는 플래너가 호출되어 두 테스트가 실패함을 확인한다.

## 작업 2: 최소 구현

**수정:** `backend/chatbot/views.py`

- [x] 두 진입점에서 신원 보강 직후 보호 함수를 호출한다.
- [x] `ChatInputRejected`를 공통 응답 도우미로 변환한다.
- [x] 기존 분석 작업 경로도 같은 도우미를 사용하도록 이름만 일반화한다.
- [x] 정상 요청, 첨부파일 차단, 사용량 제한, 큐 처리의 기존 순서와 동작은 변경하지 않는다.

## 작업 3: 계약 및 검증

**수정 여부 확인:** `app/contracts/api_route_specs.py`, `docs/api/openapi-v1.yaml`, `test/test_openapi_v1_generation.py`

- [x] 채팅/에이전트 라우트는 현재 deferred이므로 새 OpenAPI 계약을 이번 보안 PR에 추가하지 않는다.
- [x] 분석 작업 계약의 기존 `chat_input_rejected` 항목이 회귀하지 않는지 생성 테스트로 확인한다.
- [x] Django 대상 테스트, 프라이버시/계약 테스트, 전체 pytest를 실행한다.
- [x] 변경 파일과 문서의 공백 오류를 확인한다.

## 완료 기준

- 두 차단 회귀 테스트가 구현 전 실패하고 구현 후 통과한다.
- 거부 응답은 400이며 원문을 포함하지 않는다.
- 거부 시 사용량 기록, 플래너, 실행기, 큐/영속화가 호출되지 않는다.
- 전체 pytest와 CI가 통과한다.
