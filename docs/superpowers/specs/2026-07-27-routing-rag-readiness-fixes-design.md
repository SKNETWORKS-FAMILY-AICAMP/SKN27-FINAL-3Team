# Routing, Checklist, And Readiness Execution Design

## 목적

2026-07-26 이슈 메모 5건을 현재 코드와 대조해 실제로 남아 있는 사용자 영향 버그를 우선 수정하고, `docs/ops/project-readiness-master-checklist.md`의 미완료 항목 중 사람 승인, 유료 호출 승인, 외부 실환경 검증 없이 코드·테스트·문서로 진행 가능한 항목을 순차 구현 대상으로 편입한다.

## 현재 확인된 상태

- `law_ground_search` LLM fallback은 구현체가 존재하지만 `app/services/agent_node_service.py`의 `_run_law_ground_search_adapter()`가 추출기를 주입하지 않아 런타임에서 실행되지 않는다.
- pgvector 검색은 `score`를 계산하지만 최소 유사도 기준이 없어, 관련성이 낮은 top-k 결과도 그대로 근거처럼 노출될 수 있다.
- `app/web/FrontendAppShell.jsx`의 `startNewConversation()`은 새 상담 시작 시 `sessionId`를 초기화하지 않아 이전 follow-up routing intent가 다음 질문에 재사용될 수 있다.
- `app/services/supervisor_routing_service.py`와 `app/config/supervisor_routing_policy.v1.json`의 키워드 매칭은 단순 부분 문자열 OR 규칙이라 `"벌금 걱정"` 같은 표현이 사고 상담 문맥에서도 `fine_notice_procedure`로 오분류될 수 있다.
- `appeal_decision_flow`는 “어느 plan에도 연결되지 않는다”는 과거 메모와 달리, 현재 코드는 `fine_notice_analysis`에서 OCR 확인이 완료되면 `law_ground_search`, `appeal_decision_flow`를 동적으로 삽입한다. 따라서 이 항목은 순수 런타임 결함이 아니라 정책·문서·테스트 정합화 문제로 다뤄야 한다.
- 마스터 체크리스트에는 이미 구현이 일부 반영된 `[~]` 항목과, 아직 코드 레벨 작업이 시작되지 않은 `[ ]` 항목이 혼재해 있다. 이 둘을 사람 게이트 여부 기준으로 재분류해 실행 순서를 만든다.

## 체크리스트 분류 기준

### 이번 실행 범위에 포함

- 코드 변경, 테스트 추가, 문서화로 닫을 수 있는 항목
- 실제 외부 서비스 호출 없이 mock, fixture, 계약 테스트, runbook, infra code, static validation으로 전진 가능한 항목
- 이미 부분 구현된 항목을 `[~]`에서 더 앞으로 밀 수 있는 정합화, 자동화, 사용자 노출 개선

### 이번 실행 범위에서 제외

- 명시적인 사람 승인, 유료 호출 승인, 외부 계정/비밀값 입력이 필요한 항목
- 실운영 RDS, CloudFront, Google OAuth, RunPod, AWS SNS/Alarm 수신처럼 외부 환경에서 최종 증적을 남겨야 닫히는 항목
- 발표자료 최종 검수, 유료화 판단처럼 제품 또는 사업 의사결정이 필요한 항목

## 선택한 접근

이번 브랜치는 두 층으로 처리한다.

1. 실제 미해결 런타임 결함 4개를 우선 수정한다.
2. `appeal_decision_flow`는 현재 런타임 동작을 기준으로 정책, 테스트, 체크리스트 설명을 정합화한다.

그 다음 레이어로, 사람 게이트를 제외한 체크리스트 미완료 항목을 우선순위 트랙으로 순차 구현한다. 기존 구현 또는 기존 설계와 충돌하지 않는 한 사용자 확인 없이 진행하고, 충돌하는 경우에만 확인을 받는다.

## 구현 트랙

### Track 1. 즉시 수정 가능한 런타임 결함

- `law_ground_search` LLM fallback 연결
- pgvector similarity threshold 도입
- 새 상담 시작 시 `sessionId` 초기화
- `"벌금 걱정"` 라우팅 오분류 방지
- `appeal_decision_flow`의 현재 동적 연결 상태를 테스트와 체크리스트에 정합화

### Track 2. 장기 대화 맥락과 사건 메모리

- 체크리스트 43, 167, 169, 170, 171에 대응한다.
- 목표는 긴 채팅에서도 사건 맥락이 유지되는 구조화 메모리를 도입하는 것이다.
- 범위는 사건 메모리 데이터 구조, 요약·압축 정책, 소실 방지 회귀 테스트, 기존 follow-up state와의 경계 정리다.

### Track 3. 법령 최신성 사용자 노출과 회귀

- 체크리스트 119, 120에 대응한다.
- 이미 존재하는 `dataset_version`, `effective_at`, `retrieved_at`, source summary를 사용자 결과와 운영 회귀 테스트에 연결한다.
- 운영 DB 실증, 유료 재임베딩, 실제 적재 실행은 제외하고, 사용자 노출 계약과 로컬·fixture 회귀를 먼저 닫는다.

### Track 4. OCR/Vision adapter 경계와 테스트셋 정리

- 체크리스트 162, 207의 코드·테스트 가능한 부분에 대응한다.
- PDF 고지서, 사고 사진, 블랙박스 영상, 지원하지 않는 파일, 분류 불명 파일의 5개 E2E 시나리오를 adapter 경계까지 검증한다.
- 실제 provider 품질 벤치마크나 실영상 smoke는 사람 게이트로 남기되, 결과 공개 방식과 mock·fixture 기반 품질 지표 DTO는 정리한다.

### Track 5. 구조화 입력 UX와 접근성 준비

- 체크리스트 149, 153의 구현 가능한 부분에 대응한다.
- 사고 유형, 사실관계, 주장, 첨부 목적, 누락 정보 확인을 구조화 입력 UI로 분리한다.
- 실기기 검증 자체는 사람 게이트지만, 접근성 속성, 키보드 이동, 명도 대비, 반응형 구조는 코드와 정적 테스트로 먼저 보강한다.

### Track 6. CloudFront 2차 고도화의 코드 측 준비

- 체크리스트 237~250, 256, 257, 259의 코드 작성·검증 가능 부분에 대응한다.
- Terraform 구성, cache policy, SPA rewrite, deploy artifact 보관·복원 자동화, origin 보호 설정, state·secret 최소권한, 정적 검증과 contract test를 구현한다.
- 도메인 확정, ACM 발급, DNS validation, 실제 배포 apply, 실브라우저 QA는 제외한다.

## 설계

### A. 라우팅과 세션 경계

- `startNewConversation()`에서 `sessionId`를 명시적으로 비운다.
- `supervisor_routing_service`는 기존 문자열 리스트를 그대로 지원하면서, 일부 키워드에 대해 모든 토큰이 있어야 매칭되는 AND 그룹을 함께 지원한다.
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

### D. 장기 메모리와 요약·압축

- 기존 `conversation_summary`, `chat_followup_state`, `supervisor_state`를 분리된 책임으로 유지하되, 사건 단위의 구조화 메모리를 새 계층으로 추가한다.
- 구조화 메모리는 최소한 당사자, 차량, 장소, 일시, 사고 유형, 사용자 주장, 확인 사실, 첨부, 검색 근거, 미확인 항목, 기한, 현재 단계로 구성한다.
- 긴 대화 압축은 자유 텍스트 요약이 아니라 이 구조화 메모리를 우선 보존하고, 자유 서술은 보조 정보로 축약한다.
- 요약 과정이 판단 근거와 출처를 잃지 않는지 회귀 테스트를 추가한다.

### E. 사용자 노출 최신성

- 검색 결과와 최종 응답에 기준일, 조회 시각, 최신성 제한사항을 노출할 수 있는 DTO 필드를 정리한다.
- 이미 저장되는 metadata를 우선 재사용하고, 누락 필드만 최소 확장한다.
- 사용자에게는 일반화된 과장 경고가 아니라 실제 source metadata에 근거한 제한사항만 보여준다.

### F. 구조화 입력과 접근성

- 기존 자유 텍스트 입력을 유지하되, 사고 상담 첫 진입에서 선택형 사고 유형과 구조화 사실·주장 입력 패널을 제공한다.
- 첨부 목적, 누락 정보 확인, 후속 질문 이유는 기존 흐름과 연결한다.
- 접근성은 ARIA, focus order, 키보드 조작, contrast token 정리를 우선 코드 레벨에서 보강한다.

### G. CloudFront 코드 준비

- `infra/terraform-pilot`에 private frontend bucket, OAC, distribution, cache policy, origin request policy, rewrite, alarm 자산을 추가한다.
- deploy script와 release artifact는 hash asset immutable, `index.html` no-cache, 최소 invalidation, rollback artifact 보관을 지원해야 한다.
- 아직 실배포하지 않더라도 `fmt`, `validate`, 테스트, 정적 diff 점검까지는 로컬에서 통과 가능한 상태를 목표로 한다.

## 변경 파일

- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `app/services/supervisor_routing_service.py`
- Modify: `app/config/supervisor_routing_policy.v1.json`
- Modify: `app/services/agent_node_service.py`
- Modify: `app/services/legal_rag_service.py`
- Modify: `docs/ops/project-readiness-master-checklist.md`
- Modify: chat/session/memory 관련 서비스와 테스트
- Modify: `infra/terraform-pilot` 및 배포 스크립트
- Modify: 구조화 입력 UI 관련 `app/web` 컴포넌트와 스타일
- Add or modify tests around:
  - `test/test_supervisor_routing_service_quick_examples.py`
  - `test/test_agent_node_service.py`
  - `test/test_chat_orchestration_service.py`
  - `test/test_frontend_auth_session_contract.py`
  - `test` coverage for legal RAG query filtering
  - 사건 메모리·요약 보존 회귀
  - CloudFront/Terraform/deploy contract
  - 구조화 입력 UI와 접근성 회귀

## 체크리스트 갱신 원칙

- 이미 현재 코드에 반영된 항목은 “새 버그”처럼 다시 `[ ]`로 열지 않는다.
- 이번 브랜치에서 수정하는 4개 런타임 결함은 관련 섹션에 근거와 함께 반영한다.
- `appeal_decision_flow`는 “미연결”로 적지 않고, 현재 `fine_notice_analysis + OCR 확인 완료` 경로에서 연결된다는 사실과 남은 후속 작업만 적는다.
- 부분 완료 `[~]` 항목은 실제로 전진한 범위만 문장으로 좁혀 적고, 사람 게이트가 남아 있으면 `[x]`로 올리지 않는다.
- 실환경 검증이 없어 닫을 수 없는 항목은 구현 코드를 추가하더라도 체크리스트에서는 준비 완료 또는 부분 완료로만 이동시킨다.

## 테스트 전략

- 라우팅 회귀: 기존 빠른 예시가 깨지지 않는지와 `"벌금 걱정"` 사고 문맥 오분류가 사라지는지 확인한다.
- 세션 회귀: 새 상담 시작 후 이전 `routing_intent`가 재사용되지 않는 시나리오를 검증한다.
- `law_ground_search` 회귀: adapter가 추출기를 실제 주입하는지, 저관련도 결과가 threshold 아래에서 제거되는지 검증한다.
- fine notice 플로우 회귀: OCR 확인 완료 시 `appeal_decision_flow`가 계획에 포함되고, 보고서 게이트 설명이 현재 실행 모델과 모순되지 않는지 검증한다.
- 사건 메모리 회귀: 장기 대화 압축 후에도 확인 사실, 주장, 근거, 기한, 미확인 항목이 소실되지 않는지 검증한다.
- 최신성 회귀: 사용자 노출 결과에 기준일과 제한사항이 붙고, 변경된 법령·과실 기준 fixture에 대해 회귀 테스트가 도는지 검증한다.
- UI 회귀: 구조화 입력 흐름과 접근성 속성이 기존 상담 시작 흐름을 깨지 않는지 검증한다.
- 인프라 회귀: Terraform validation, policy contract, 배포 artifact·rollback 로직이 정적 테스트로 검증되는지 확인한다.

## 제외 범위

- CloudFront/OAuth live smoke 같은 사람 게이트
- RunPod 실영상 smoke
- `appeal_decision_flow`의 노드 그래프 자체 재설계
- Supervisor 라우팅의 전면적인 모델 기반 재구성
- 유료 호출 승인, 외부 비밀값 발급·입력, 운영 RDS 실제 적재, DNS·ACM 실배포, 발표자료 최종 검수, 유료화 기획 결정
