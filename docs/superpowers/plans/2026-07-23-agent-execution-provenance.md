# Agent 실행 재현성 증적 구현 계획

> 이 계획은 GitHub issue #299의 두 번째 독립 단계다. 첫 단계인 법령 적재
> `run_summary`와 freshness gate는 PR #301로 `dev`에 병합되었다.

## 목표

운영자가 `job_id` 하나로 다음 정보를 확인할 수 있게 한다.

- Supervisor 모델·프롬프트 버전
- Agent adapter·계약 버전
- 검색 데이터 버전·기준일·검색 시각
- `job_id`·`execution_id`·invocation·retrieval 연결
- 성공·부분 실패·실패 상태와 안전한 오류 코드

원문 사용자 입력, OCR 전문, API key, 내부 경로는 증적에 포함하지 않는다.

## 설계

1. `supervisor_llm_service`가 conversation/planner metadata에 명시적 prompt
   version을 기록한다.
2. `agent_node_service`의 모든 mock/sync 실행 envelope에
   `agent_execution_provenance.v1`을 기록한다.
3. 법령 검색 응답은 배포 시 주입되는 `LEGAL_DATASET_VERSION`과
   `LEGAL_DATASET_VERIFIED_AT`, 검색 기준일과 검색 시각을 반환한다.
4. repository는 안전하게 축약된 provenance를 `AgentResult.raw_output`,
   `AgentInvocation.metadata`, `RetrievalEvent.metadata`에 보관한다.
5. `get_analysis_job_provenance(job_id)`와 Django management command
   `show_analysis_job_provenance`를 제공한다.
6. 조회 결과는 원문 query와 사용자 입력을 제외하고 식별자·버전·상태·
   source reference만 반환한다.

## 작업 순서

### 1. 계약 테스트

- Supervisor 모델 metadata가 prompt version을 포함하는지 검증
- 모든 Agent execution envelope가 provenance를 포함하는지 검증
- 법령 검색 결과가 dataset version과 기준 시각을 포함하는지 검증
- persistence와 운영 조회 결과가 job/execution/retrieval을 연결하는지 검증
- 조회 결과에 원문 query·비밀값이 노출되지 않는지 검증

### 2. 런타임 metadata

- 버전 상수와 provenance 생성 helper 구현
- 성공·계약 거부·adapter 실패를 포함한 모든 실행 경로에 적용
- 법령 RAG 결과에 데이터 provenance 적용

### 3. 저장·조회

- 기존 JSONField에 안전한 버전 snapshot 저장
- operator-facing repository query 구현
- JSON management command와 사람이 읽는 기본 출력 구현

### 4. 운영 문서와 체크리스트

- 명령 예시, 필수 비밀값이 아닌 배포 metadata 환경변수, 판독법 문서화
- master/release checklist와 통합 검증 보고서 갱신

### 5. 검증

- 집중 테스트
- 전체 `test/` 회귀
- Django 관련 회귀
- Ruff, compileall, `git diff --check`

## 사람 작업

- 운영 배포 artifact가 확정된 뒤 `LEGAL_DATASET_VERSION`,
  `LEGAL_DATASET_VERIFIED_AT`, release version 값을 승인·주입
- 운영 DB와 실제 공급자를 사용하는 최종 smoke
