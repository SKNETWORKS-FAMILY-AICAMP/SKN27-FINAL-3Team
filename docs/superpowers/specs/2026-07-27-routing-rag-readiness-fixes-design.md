# Routing And RAG Readiness Fixes Design

## 목적

2026-07-26 이슈 메모 5건을 현재 코드와 대조해, 실제로 남아 있는 사용자 영향 버그를 우선 수정하고 `docs/ops/project-readiness-master-checklist.md`를 현재 상태에 맞게 갱신한다.

## 현재 확인된 상태

- `law_ground_search` LLM fallback은 구현체가 존재하지만 `app/services/agent_node_service.py`의 `_run_law_ground_search_adapter()`가 추출기를 주입하지 않아 런타임에서 실행되지 않는다.
- pgvector 검색은 `score`를 계산하지만 최소 유사도 기준이 없어, 관련성이 낮은 top-k 결과도 그대로 근거처럼 노출될 수 있다.
- `app/web/FrontendAppShell.jsx`의 `startNewConversation()`은 새 상담 시작 시 `sessionId`를 초기화하지 않아 이전 follow-up routing intent가 다음 질문에 재사용될 수 있다.
- `app/services/supervisor_routing_service.py`와 `app/config/supervisor_routing_policy.v1.json`의 키워드 매칭은 단순 부분 문자열 OR 규칙이라 `"벌금 걱정"` 같은 표현이 사고 상담 문맥에서도 `fine_notice_procedure`로 오분류될 수 있다.
- `appeal_decision_flow`는 “어느 plan에도 연결되지 않는다”는 과거 메모와 달리, 현재 코드는 `fine_notice_analysis`에서 OCR 확인이 완료되면 `law_ground_search`, `appeal_decision_flow`를 동적으로 삽입한다. 따라서 이 항목은 순수 런타임 결함이 아니라 정책/문서/테스트 정합화 문제로 다뤄야 한다.

## 선택한 접근

이번 브랜치는 두 층으로 처리한다.

1. 실제 미해결 런타임 결함 4개를 우선 수정한다.
2. `appeal_decision_flow`는 현재 런타임 동작을 기준으로 정책, 테스트, 체크리스트 설명을 정합화한다.

더 큰 구조 변경은 제외한다. 예를 들어 `appeal_decision_flow`를 모든 fine notice 계열 intent의 정적 기본 plan으로 승격하거나, 라우팅 전반을 LLM 분류기로 교체하는 작업은 이번 범위에 넣지 않는다.

## 설계

### A. 라우팅과 세션 경계

- `startNewConversation()`에서 `sessionId`를 명시적으로 비운다.
- `supervisor_routing_service`는 기존 문자열 리스트를 그대로 지원하면서, 일부 키워드에 대해 “모든 토큰이 있어야 매칭”되는 AND 그룹을 함께 지원한다.
- `fine_notice_procedure`의 `"벌금 걱정"` 단일 문자열은 AND 그룹으로 바꿔 사고 상담 문맥 오분류를 줄인다.

이 변경은 기존 attachment 우선 규칙과 기본 라우팅 순서를 바꾸지 않는다.

### B. law_ground_search 런타임 보강

- `_run_law_ground_search_adapter()`에서 `OpenAILawKeywordExtractor`를 실제로 연결한다.
- API 키가 없거나 추출기가 실패해도 현재 fallback-safe 동작을 유지해야 하므로, 추출기 주입은 “가능하면 사용, 불가하면 기존 동작 유지” 형태여야 한다.
- `legal_rag_service`에 `LEGAL_RAG_MIN_SIMILARITY_SCORE` 환경값을 추가하고 기본값을 둔다.
- `_query_pgvector_rows()`는 최소 유사도 기준 미만 결과를 SQL에서 걸러 `status="empty"` 경로가 자연스럽게 작동하도록 한다.

이 변경은 embedding 모델, DB schema, seed loader, report DTO를 바꾸지 않는다.

### C. appeal_decision_flow 정합화

- 현재 코드는 `fine_notice_analysis`에서 OCR 확인이 완료되면 `appeal_decision_flow`를 동적으로 plan에 삽입하므로, 이 사실을 기준으로 테스트와 체크리스트 설명을 맞춘다.
- 정적 `plans` JSON을 즉시 크게 바꾸기보다, 현재 동적 삽입 규칙이 `report_required_nodes` 및 실행 결과와 모순되지 않는지 검증하는 테스트를 추가한다.
- 체크리스트에는 “미연결”로 기록하지 않고, 현재 연결 범위와 남은 사람 게이트 또는 후속 구조 개선 범위를 구분해 적는다.

## 변경 파일

- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `app/services/supervisor_routing_service.py`
- Modify: `app/config/supervisor_routing_policy.v1.json`
- Modify: `app/services/agent_node_service.py`
- Modify: `app/services/legal_rag_service.py`
- Modify: `docs/ops/project-readiness-master-checklist.md`
- Add or modify tests around:
  - `test/test_supervisor_routing_service_quick_examples.py`
  - `test/test_agent_node_service.py`
  - `test/test_chat_orchestration_service.py`
  - `test/test_frontend_auth_session_contract.py`
  - `test` coverage for legal RAG query filtering

## 체크리스트 갱신 원칙

- 이미 현재 코드에 반영된 항목은 “새 버그”처럼 다시 `[ ]`로 열지 않는다.
- 이번 브랜치에서 수정하는 4개 런타임 결함은 관련 섹션에 근거와 함께 반영한다.
- `appeal_decision_flow`는 “미연결”로 적지 않고, 현재 `fine_notice_analysis + OCR 확인 완료` 경로에서 연결된다는 사실과 남은 후속 작업만 적는다.

## 테스트 전략

- 라우팅 회귀: 기존 빠른 예시가 깨지지 않는지와 `"벌금 걱정"` 사고 문맥 오분류가 사라지는지 확인한다.
- 세션 회귀: 새 상담 시작 후 이전 `routing_intent`가 재사용되지 않는 시나리오를 검증한다.
- law_ground_search 회귀: adapter가 추출기를 실제 주입하는지, 저관련도 결과가 threshold 아래에서 제거되는지 검증한다.
- fine notice 플로우 회귀: OCR 확인 완료 시 `appeal_decision_flow`가 계획에 포함되고, 보고서 게이트 설명이 현재 실행 모델과 모순되지 않는지 검증한다.

## 제외 범위

- CloudFront/OAuth live smoke 같은 사람 게이트
- RunPod 실영상 smoke
- `appeal_decision_flow`의 노드 그래프 자체 재설계
- Supervisor 라우팅의 전면적인 모델 기반 재구성
