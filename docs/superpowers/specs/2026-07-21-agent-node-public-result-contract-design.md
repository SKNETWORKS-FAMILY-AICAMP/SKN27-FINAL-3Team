# Agent 노드 공개 결과 DTO 계약 설계

## 목적

Issue #268은 공통 `AgentAdapterOutput`이 Supervisor, Worker, 저장소를 거친 뒤
`GET /api/analysis/results/{job_id}/`에서 화면용 결과 계약으로만 공개되는지를
고정한다. 개별 OCR, RAG, Vision, 과실비율 Agent의 구현이나 결과 생성 규칙은
변경하지 않는다.

## 확인된 현재 상태

- 결과 조회 API는 `app.services.analysis_job_query_service.load_analysis_result()`를
  거친다.
- `analysis_plan`, `node_execution`, `chat_response`는 현재 결과 조회 응답에
  포함되지 않는다.
- 반면 저장된 `supervisor_state`, `supervisor_execution`, `reporting_payload`는
  통째로 복사된다. 앞으로 내부 필드가 추가되면 결과 조회 API까지 노출될 수 있다.
- 프런트엔드는 결과 조회 값 중 보고서 미리보기, 대기 질문, 보고서 Agent 존재 여부,
  Worker 폴링, 과실·법령 요약에 필요한 일부 필드를 사용한다.
- DOCX 다운로드는 결과 조회 payload의 `form_data`가 아니라 서버에 저장된 Report를
  기준으로 수행한다. 따라서 결과 조회 API에서 `form_data`를 유지할 필요가 없다.

## 결정

결과 조회 API에 별도 버전을 만들거나 개별 Agent의 하위 결과 구조를 다시 정의하지
않는다. `analysis_result.v2`를 유지하면서, 조회 서비스가 저장 레코드와 Agent 병합
결과에서 **화면에 필요한 값만 명시적으로 투영**한다.

이 선택은 다음을 함께 만족한다.

- Worker 원본 실행 봉투와 Supervisor 내부 계획을 공개 결과에서 분리한다.
- 현재 UI가 실제로 쓰는 보고서·폴링·노드 요약 정보는 보존한다.
- Agent마다 다른 `structured_result`의 사용자 표시 내용은 유지해 개별 Agent 계약과
  충돌하지 않는다.
- OpenAPI 모델의 `extra="allow"` 설정에 보안 경계를 맡기지 않고, 런타임 조회
  서비스에서 실제 경계를 강제한다.

## 공개 DTO 경계

### 공통 결과 필드

완료 결과와 대기 결과 모두 다음 화면용 필드를 유지한다.

- `contract_version`, `job_id`, `status`, `assistant_message`
- `cards`, `pending_questions`, `report_links`, `attachments`
- `evidence`, `limitations`, `next_actions`, `deadline_guidance`
- `work_item`, `progress_state`
- 화면 안전 안내가 존재할 때의 `service_scope`

대기 상태는 Composer를 호출하지 않으며, 빈 사용자 표시 컬렉션과 Worker 상태 요약만
반환한다. `structured_results`는 화면이 사용하지 않는 Agent 결과의 중복 집계이므로
대기·완료 결과 모두에서 공개하지 않는다.

### `reporting_payload` 투영

보고서 화면과 DOCX 확인 게이트가 쓰는 다음 값만 유지한다.

- `contract_version`, `stage`, `report_id`, `report_type`, `title`, `summary`
- `sections`, `document_cards`, `document_variant`
- `document_confirmation`, `report_actions`, `appeal_gate`

`form_data`, `document_readiness`, `appeal_decision`, 초안 생성 내부 정보 및 그 밖의
집계 보조값은 결과 조회 API에서 제외한다. 다운로드·확인 API는 서버 저장 Report를
다시 읽으므로 이 변경에 의존하지 않는다.

### `supervisor_state` 투영

다음 화면 상태만 유지한다.

- `contract_version`, `stage`, `conversation_summary`
- `collected_facts`, `missing_fields`, `next_questions`
- `agent_input_packages`의 각 항목 중 `node_code`만

특히 `agent_input_packages[].payload`와 Supervisor 입력 원문은 공개하지 않는다.
프런트엔드는 이 목록에서 보고서 생성 Agent의 존재 여부만 판단한다.

### `supervisor_execution` 투영

Worker 원본 실행 레코드 대신 화면·폴링용 요약만 유지한다.

- 상위: `contract_version`, `execution_mode`, `job_id`, `work_item`
- 노드별: `node_code`, `status`, `summary`, `structured_result`, `evidence`,
  `next_actions`, `limitations`

`structured_result`는 과실비율·법령 결과 패널이 실제로 표시하는 Agent별 사용자 결과
본문이므로 유지한다. 대신 실행 ID, plan ID, AI session ID, session/message ID,
adapter 설정·모드, plan step, 원본 Agent 입력과 같은 Worker 운영 정보는 제외한다.

### 명시적 제외 필드

다음 필드는 결과 조회 API에서 항상 제외한다.

- `analysis_plan`, `node_execution`, `chat_response`
- `supervisor_reporting_handoff`, `reporting_pipeline`, `supervisor_handoff`
- 상위 `structured_results`
- `supervisor_state`의 입력 payload 및 `reporting_payload.form_data`
- Worker의 원본 실행 식별자·계획·adapter 설정·입력 데이터

이 규칙은 초기 채팅 응답이나 `/api/analysis/jobs/{job_id}/` 상세 조회의 기존 운영
계약을 변경하지 않는다. Issue #268의 범위는 완료·대기 결과 조회 API다.

## 구현 경로

1. `analysis_job_query_service.py`에 작은 투영 helper를 둔다. 입력을 수정하지 않고
   새 dict와 list만 만들어 결과 조회 응답을 조립한다.
2. 완료 결과는 Composer가 만든 사용자 안내·기한·근거를 유지한 뒤, 저장된 표시 데이터와
   위 중첩 투영을 합친다.
3. 대기 결과도 `work_item`과 `progress_state`를 화면·폴링에 필요한 요약 형태로
   투영한다.
4. 프런트 코드, 개별 Agent, DB 스키마, Worker 실행, 리포트 렌더러는 수정하지 않는다.

## 호환성 및 위험 완화

- **과도한 하위 필드 제거 위험**: Agent별 `structured_result`를 전역 키 목록으로
  제한하지 않는다. 화면이 쓰는 노드 결과 본문은 유지하고 실행 봉투만 제거한다.
- **보고서 동작 위험**: 결과 화면은 `form_data`를 보내지 않으며, 다운로드 시 Report
  상세/다운로드 API가 서버 저장 데이터를 읽는다. 관련 기존 테스트와 프런트 빌드로
  확인한다.
- **Worker 폴링 위험**: `work_item.work_item_id`, `work_item.job_id`, 상태와
  `progress_state.job_status`를 보존한다.
- **외부 소비자 위험**: 삭제 대상은 공식 `AnalysisResult` 모델에 정의되지 않은
  부가 내부 값이다. `analysis_result.v2`와 화면 소비 필드는 유지한다.

## 검증 계획

1. `test/test_analysis_job_query_service.py`
   - 실제 `AgentAdapterOutput` 형태의 fixture를 사용한다.
   - 사용자 안내, 제한사항, 다음 행동, 기한 안내, 보고서·폴링에 필요한 필드가 보존되는지
     검증한다.
   - sentinel 내부 값을 넣어 Worker 원본·Supervisor 입력·보고서 form data가 결과에
     나오지 않는지 검증한다.
   - 입력 저장 dict가 투영 과정에서 변경되지 않는지 검증한다.
2. 기존 Django 결과 조회 API 테스트에 실제
   `GET /api/analysis/results/{job_id}/` 경로 검증을 추가하거나 보강한다.
   - 소유권·인증 경계를 우회하지 않는다.
   - 결과 응답에서 금지 필드가 없고 필요한 노드 표시 결과가 남는지 확인한다.
3. 관련 Python 계약·큐·소유권 테스트와 `app/web`의 `npm run build`를 실행한다.

로컬 가상환경에 `python-docx`가 없으면 Agent 노드 전체 테스트 수집이 실패할 수 있다.
이는 DTO 설계 오류가 아니라 개발 의존성 누락이므로, 프로젝트 의존성이 준비된
가상환경에서 전체 관련 테스트를 실행한다.

## 체크리스트와 제외 범위

모든 검증이 통과한 경우에만 같은 PR에서
`docs/ops/project-readiness-master-checklist.md`의 `에이전트 노드 API 계약`을 완료
처리한다.

다음은 이번 작업에서 변경하지 않는다.

- OCR, RAG, Vision, 과실비율 Agent 구현 및 Provider 호출
- UI 구조·디자인·더미 데이터 모드
- DB 스키마, 배포, Docker, 리포트 생성 및 DOCX 정책
- Guest credential·소유권 정책 및 이미 존재하는 보안 경계

## 완료 기준

1. 결과 조회 API가 화면용 DTO만 반환한다.
2. 내부 실행·계획·입력·보고서 form data가 결과 API에 없다.
3. 제한사항, 다음 행동, 기한 안내, 보고서 게이트, Worker 폴링, 노드 결과 표시가 유지된다.
4. 실제 API 경로를 포함한 회귀 테스트와 프런트 프로덕션 빌드가 통과한다.
