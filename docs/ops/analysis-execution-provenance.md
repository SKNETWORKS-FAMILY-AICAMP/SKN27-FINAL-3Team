# 분석 실행 재현성 조회 Runbook

## 목적

운영자가 사용자 원문이나 비밀값을 조회하지 않고 `job_id`를 기준으로 모델,
프롬프트, Agent runtime, 검색 데이터 버전과 실행 상태를 확인한다.

## 배포 metadata

다음 값은 비밀값이 아니지만 검증된 release 증적에서만 가져온다.

- `APP_RELEASE_VERSION`: immutable release tag 또는 commit
- `LEGAL_DATASET_VERSION`: freshness validation을 통과한
  `run_summary.json`의 `dataset_version`
- `LEGAL_DATASET_VERIFIED_AT`: 같은 run summary의 `finished_at`

PowerShell에서 검증된 run summary 값을 확인한다.

```powershell
$RunSummary = Get-Content `
  output\law_ingestion\reports\run_summary.json -Raw |
  ConvertFrom-Json
$RunSummary.dataset_version
$RunSummary.finished_at
```

운영 runtime 환경에 값을 넣은 뒤 새 release를 시작한다. 실행 중인 컨테이너에서
임의로 시각이나 버전을 바꾸지 않는다.

## 작업별 조회

운영 애플리케이션 컨테이너 또는 동일한 운영 DB 설정을 사용하는 관리 셸에서
다음 명령을 실행한다.

```powershell
python backend\manage.py show_analysis_job_provenance `
  --job-id <JOB_ID> `
  --format json
```

기본 텍스트 출력은 빠른 현장 확인용이다.

```powershell
python backend\manage.py show_analysis_job_provenance `
  --job-id <JOB_ID>
```

JSON 결과의 주요 필드는 다음과 같다.

- `supervisor.conversation`: provider, model, prompt version/hash
- `supervisor.planner`: provider, model, prompt version/hash
- `executions`: invocation·execution ID, Agent/runtime/release version, 상태,
  안전한 오류 코드
- `retrievals`: 검색 event·execution 연결, embedding provider·model·차원,
  source reference, 검색 데이터 버전, 검증 시각, 적용 기준일, 검색 시각

## 개인정보·비밀정보 경계

조회 결과에는 다음을 포함하지 않는다.

- 사용자 질문 원문과 대화 원문
- OCR 전문과 첨부파일 내용
- API key, token, cookie
- 객체 저장소 내부 경로
- 검색 query 원문과 검색된 법령 전문

필요한 근거는 `source_refs`로 식별하고 승인된 별도 데이터 조회 절차를 사용한다.

## 판독 및 다음 조치

- `release_version`이 `unversioned`면 배포 metadata 주입 실패이므로 release
  증적으로 인정하지 않는다.
- `dataset_version`이 `unconfigured`이거나 비어 있으면 검색 결과 재현 증적으로
  인정하지 않는다.
- `verified_at`이 freshness 승인 시각보다 오래되면 법령 적재와 검증을 다시
  실행한다.
- execution이 `partial` 또는 `failed`면 `error_code`, `retryable`,
  `completed_at`을 확인하고 장애 runbook으로 연결한다.
- 존재하지 않는 `job_id`는 `analysis_job_not_found`로 종료한다.
