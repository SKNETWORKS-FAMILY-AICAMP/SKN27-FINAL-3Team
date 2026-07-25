# Supervisor LLM 계약 복구 설계

## 목적

파일럿에서 `SUPERVISOR_LLM_ENABLED=1`일 때 실제
`/api/chat/messages/` 요청이 `invalid_contract`로 거절되어 503이 되는 P0 문제를
해결한다. 단순 프롬프트 보강이 아니라 운영 fallback, 모델 응답, 서버 정규화,
검증기, 배포 smoke를 하나의 일관된 계약으로 맞춘다.

서비스 복구 과정에서도 기존 fail-closed 정책을 유지한다. 즉, 모델 응답을
검증하지 못하면 임의의 fallback 결과로 성공시키지 않고
`supervisor_unavailable`을 반환한다.

## 확인된 원인

현재 운영 fallback은 `supervisor_conversation_state.v2`이며 일반 상담과 법령
검색에서는 `reporting_payload`가 `None`이다. 또한 Agent 패키지에 `owner`와
`missing_fields`를 생성하지 않는다.

반면 LLM 후보 검증기는 다음 내용을 무조건 요구한다.

- `supervisor_conversation.v1`
- 모든 Agent 패키지의 non-empty `owner`
- 모든 Agent 패키지의 list `missing_fields`
- `reporting_payload.v1` dict

따라서 모델이 운영 fallback을 정확히 복사해도 검증을 통과할 수 없다.
기존 `smoke_supervisor_llm`은 production orchestration이 아니라
`chatbot_mock_service.submit_message`를 호출하고, 테스트 fixture도 검증기가
원하는 필드를 미리 포함하므로 이 모순을 발견하지 못했다.

## 선택한 해결 방향

### 1. 서버가 권한성 필드를 소유한다

모델은 다음처럼 판단이 필요한 제한된 값만 반환한다.

- 대화 요약과 수집 사실
- 누락 필드와 다음 질문
- 선택된 `node_code`
- 각 노드에 전달할 `payload`
- 분석 계획의 단계와 사용자 입력 요약

다음 필드는 모델이 생성하거나 덮어쓸 수 없고 서버가 canonical Agent Registry와
운영 fallback에서 주입한다.

- `schema_version`
- `owner`
- `status`
- `required_inputs`
- `missing_fields`
- `scenario`
- `stage`
- `conversation_turn_count`
- `slot_state`
- 최종 `contract_version`
- 최종 `reporting_payload`

모델이 임의의 owner나 미등록 노드를 보내더라도 채택하지 않는다. 후보에 허용되는
노드 집합은 운영 fallback이 선택한 노드 집합과 정확히 같아야 한다.

### 2. 운영 fallback을 canonical 상태로 먼저 보강한다

LLM 요청 전에 운영 fallback의 각 Agent 패키지를
`agent_node_service.NODE_REGISTRY`로 보강한다.

- `owner`: Registry의 canonical owner
- `missing_fields`: 패키지 또는 상위 상태에서 계산된 list
- `status`: 누락 필드가 있으면 `waiting_for_fields`, 없으면 `ready`

Registry에 없는 노드, owner가 없는 노드, dict가 아닌 payload는 요청 전에
실패시킨다. 이 보강은 LLM 응답 성공 여부와 무관하게 같은 규칙을 사용한다.
OCR 확인 후 서버가 추가하는 `law_ground_search`와 `appeal_decision_flow` 패키지도
같은 보강 함수를 반드시 통과시킨다.

사고 초기 상담처럼 fallback의 Agent 패키지가 빈 배열인 경로는 빈 배열 자체가
정상 계약이다. 이 경로에 임의의 노드를 추가하지 않으며 fallback의
`need_more_input` 또는 `need_fact_confirmation` stage를 서버가 보존한다.

### 3. strict JSON Schema Structured Output을 사용한다

OpenAI 호환 호출의 `response_format={"type":"json_object"}`를 제거하고
`json_schema`와 `strict: true`를 사용한다.

대화 상태와 분석 계획은 서로 다른 schema를 사용한다.

- `supervisor_conversation_response_v2`
- `supervisor_analysis_plan_response_v2`

모든 object는 `additionalProperties: false`를 사용하고, 배열 항목의 필수
필드와 타입을 명시한다. `collected_facts`, `missing_fields`,
`next_questions`, `agent_input_packages`는 항상 배열이다.

모델 출력 schema는 내부 응답 계약이다. 최종 서비스 응답의
`supervisor_conversation_state.v2`나 `reporting_payload.v2`를 v1으로
낮추지 않는다.

OpenAI 호환 provider가 strict schema를 지원하지 않아 요청을 거절하면
`json_object`로 자동 완화하지 않고 provider failure로 fail-closed 처리한다.
OpenAI의 structured refusal 응답도 일반 JSON content로 파싱하지 않고
`provider_refusal`로 분리해 fail-closed 처리한다.

### 4. reporting payload는 서버가 전적으로 소유한다

모델 응답 schema에는 `reporting_payload`를 포함하지 않는다. 일반 상담, 법령
검색처럼 fallback의 `reporting_payload`가 `None`이면 최종 상태도 `None`을
유지한다.

보고서 생성 경로처럼 fallback에 reporting payload가 있으면 해당 object를
그대로 최종 상태에 보존한다. 모델이 보고서 생성 권한을 새로 만들거나 제거할 수
없다. 이 방식은 `None`과 `reporting_payload.v2`를 모델에게 다시 복사시키는
불필요한 이중 계약을 제거한다.

### 5. 정규화와 검증 순서

대화 상태 처리 순서는 다음과 같다.

1. production fallback 상태 생성
2. Registry를 이용한 fallback Agent 패키지 보강
3. 보강한 fallback에 맞는 동적 strict schema 생성
4. provider 호출
5. refusal 확인, JSON 파싱과 schema 이후의 도메인 검증
6. 후보의 사용자 판단 필드만 fallback 사본에 병합
7. Registry와 fallback으로 권한성 필드 재주입
8. 최종 상태 계약 검증
9. 성공이면 orchestration 진행, 실패면 기존 503 처리

분석 계획도 동일하게 fallback 노드와 단계 집합을 기준으로 후보를 제한한다.

## 관측성과 오류 처리

`invalid_contract`와 provider 오류는 기존처럼
`supervisor_unavailable`로 변환한다. 다만 경고 로그에 다음과 같은 안전한
진단 코드만 남긴다.

- `candidate_not_object`
- `unexpected_node_set`
- `invalid_collected_facts`
- `invalid_missing_fields`
- `reporting_presence_mismatch`
- `registry_owner_missing`
- `provider_structured_output_error`
- `provider_refusal`

로그에는 사용자 입력, 첨부파일 내용, 전체 모델 응답, API key, OAuth code,
private URL을 기록하지 않는다.

## 회귀 테스트

### 서비스 단위 테스트

- OpenAI 요청이 `json_schema`와 `strict: true`를 사용하는지 확인
- 대화 상태와 계획이 서로 다른 schema를 선택하는지 확인
- 모든 object의 추가 필드가 차단되는지 확인
- 모델 schema에서 `reporting_payload`가 제외되는지 확인
- fallback reporting이 `None`일 때 최종 상태도 `None`인지 확인
- reporting payload가 있을 때 `reporting_payload.v2`를 보존하는지 확인
- owner가 Registry에서 주입되는지 확인
- 모델이 보낸 위조 owner가 무시되는지 확인
- `missing_fields`가 항상 list인지 확인
- 빈 Agent 패키지와 `need_fact_confirmation` stage가 보존되는지 확인
- OCR 확인 후 서버가 추가한 패키지도 동일하게 보강되는지 확인
- structured refusal이 안전하게 fail-closed 되는지 확인
- 안전한 오류 코드만 로그에 남고 사용자 원문과 비밀값은 남지 않는지 확인

### production orchestration 회귀 테스트

mock 서비스가 아니라 실제
`app.services.chat_orchestration_service.submit_message()`를 호출한다. provider
네트워크 호출만 deterministic 후보로 대체하고 아래 네 경로를 검증한다.

1. `general_consultation`
2. `traffic_law_search`
3. `fine_notice_procedure`
4. `fine_notice_analysis`

각 경로에서 `invalid_contract`나 `supervisor_unavailable`이 발생하지 않고,
최종 패키지에 Registry owner와 list `missing_fields`가 존재해야 한다.
별도 경계 테스트로 `accident_initial_consultation`의 빈 패키지와
fine-notice OCR 확인 후 패키지 추가 경로도 검증한다.

### 배포 gate

파일럿 배포가 mock 기반 `smoke_supervisor_llm`만 실행하지 않도록 변경한다.
이미 존재하는 `smoke_supervisor_conversation_runtime`을 production
orchestration smoke로 사용하고, readiness metadata도 같은 명령을 가리킨다.

유료 provider 호출이나 실제 fixture가 필요한 smoke는 기존처럼 명시적 동의와
fixture 입력을 요구한다. 이 P0 수정 작업에서 새 유료 호출을 실행하지 않는다.

## 배포 및 롤백

1. P0 전용 브랜치에서 RED 회귀 테스트를 먼저 추가한다.
2. 계약 정규화와 strict schema를 구현한다.
3. 관련 Python 테스트, Django 테스트, frontend build, pilot Compose 검증을
   통과시킨다.
4. PR을 dev에 병합한다.
5. 병합된 dev에서 중단했던 AWS 비공개 배포를 재개한다.

배포 후 production runtime smoke가 실패하면 현재 release를
`/opt/skn27-pilot/current`로 승격하지 않고 기존 release로 롤백한다.
긴급 복구가 필요한 경우에만 Compose에서
`SUPERVISOR_LLM_ENABLED=0`인 별도 release를 배포한다.

## 범위 밖

- 503 fail-closed 정책을 성공 fallback으로 바꾸는 작업
- Agent Registry owner를 모델이 선택하도록 허용하는 작업
- 기존 외부 v2 상태 계약을 v1으로 낮추는 작업
- 이번 수정 과정에서 OpenAI 유료 embedding 또는 리뷰 사례 생성을 실행하는 작업
