# 운영 관측과 CloudWatch 알람 Runbook

## 범위

이 문서는 `operational_health.v1` snapshot과 CloudWatch 알람을 사용해 분석
큐, Worker, 외부 공급자와 법령 데이터 최신성 이상을 확인하고 복구하는
절차다. snapshot은 집계 수치와 허용된 안전 코드만 포함한다.

사용자 질문, 이메일, 첨부 파일명·경로, OCR 결과, prompt, API key, signed
URL, 공급자 응답과 원문 예외는 CloudWatch Logs에 기록하지 않는다.

## 즉시 상태 확인

애플리케이션 컨테이너 또는 동일한 운영 DB 설정을 사용하는 관리 환경에서
다음 명령을 실행한다.

```powershell
python backend/manage.py observe_operational_health --once
```

개별 분석 작업의 버전·실패 단계가 필요하면 알람이나 운영 로그에 사용자
원문을 추가하지 말고 승인된 `job_id`로 기존 조회 명령을 사용한다.

```powershell
python backend/manage.py show_analysis_job_provenance --job-id <JOB_ID> --format json
```

운영 배포의 `ops-monitor` 컨테이너는 60초마다 같은 snapshot을 JSON 한 줄로
출력한다. CloudWatch Log Group 이름은 Terraform output으로 조회한다.

```powershell
terraform -chdir=infra/terraform-pilot output -raw operational_log_group_name
```

## 알람 코드별 대응

| 코드 | 먼저 확인 | 완화와 복구 확인 |
|---|---|---|
| `queue_backlog` | `queued_count`, agent-worker 실행 여부, DB 연결 | 새 요청 증가 여부를 확인하고 Worker를 정상화한다. 대기 수가 감소하는지 다음 3회 snapshot에서 확인한다. |
| `queue_oldest_age_exceeded` | `oldest_queued_age_seconds`, 가장 오래된 작업의 승인된 `job_id` | 중복 Worker를 시작하지 말고 lease·idempotency 상태를 확인한다. 값이 임계값 아래로 내려가는지 확인한다. |
| `worker_lease_stale` | `stale_running_count`, Worker 프로세스와 DB 시간 | 기존 lease 만료·재회수 계약을 따른다. 동일 작업을 수동으로 중복 실행하지 않는다. |
| `worker_retrying` | `retrying_count`, `next_run_at`, 안전한 `error_code` | 공급자·입력·용량 원인을 확인한다. 유료 호출은 자동 반복하지 않고 승인 후 새 작업으로 검증한다. |
| `worker_failure` | `recent_failure_count`, provenance의 실패 단계 | 사용자 원문 대신 `job_id` 조회 결과의 안전 코드와 다음 행동을 확인한다. 한 건의 성공으로 전체 복구를 선언하지 않는다. |
| `worker_timeout` | `recent_timeout_count`, adapter timeout과 실제 latency | timeout을 무조건 늘리지 않는다. 입력 크기와 공급자 latency·Worker 용량을 먼저 확인한다. |
| `provider_failure` | `providers.roles`, 공급자 상태 페이지와 runtime 설정 | API key를 로그나 명령행에 출력하지 않는다. 공급자 복구 뒤 비식별 smoke 한 건으로 확인한다. |
| `legal_data_missing` | `/run/operational-evidence/run_summary.json` 존재 여부와 승인된 source 목록 | 검증된 `legal_ingestion_run_summary.v2`만 원자적으로 배치한다. 파일을 임의로 생성해 알람만 끄지 않는다. |
| `legal_data_stale` | `stale_source_count`, 마지막 검증일과 승인된 최대 age | 갱신 파이프라인과 `validate_run_summary.py`를 다시 실행한다. 새 dataset version을 검증한 후 교체한다. |
| `legal_data_refresh_failed` | `failed_source_count`, ETL의 안전한 실패 보고서 | 실패 source를 수정한 뒤 전체 검증을 다시 실행한다. 부분 결과를 성공으로 표시하지 않는다. |
| `legal_data_provenance_mismatch` | summary의 안전한 `dataset_version`, `release_version`과 현재 runtime 설정 | 다른 release의 summary를 복사해 알람만 끄지 않는다. 해당 release의 immutable RAG seed에서 증적을 다시 생성하고 cutover 전 strict validation을 재실행한다. |
| `monitor_configuration_invalid` | DB 연결, JSON schema, 양수 임계값, monitor 컨테이너 상태 | 원문 예외를 CloudWatch에 복사하지 않는다. 설정을 수정하고 단발 명령이 정상 snapshot을 반환하는지 확인한다. |

## 법령 run summary 반영

운영 monitor는 호스트의
`/opt/skn27-pilot/operational-evidence/run_summary.json`을 read-only로
읽는다. 다음 조건을 모두 통과한 파일만 반영한다.

1. 계약이 `legal_ingestion_run_summary.v2`다.
2. 승인된 required source가 모두 존재한다.
3. `missing_sources`, `failed_sources`, `stale_sources`가 비어 있다.
4. `dataset_version`, `release_version`, 검증 시각이 운영 release 기록과
   일치한다.

검증 명령 예시는 다음과 같다.

```powershell
python -m etl.legal.validate_run_summary `
  --summary output/law_ingestion/reports/run_summary.json `
  --max-age-hours 168 `
  --expected-dataset-version <APPROVED_DATASET_VERSION> `
  --expected-release-version <APPROVED_RELEASE_VERSION> `
  --required-source <APPROVED_SOURCE_ID>
```

파일은 승인된 비공개 S3 배포 artifact와 SSM 경로를 통해 인스턴스로
전달하고, 임시 파일을 `0444`로 만든 뒤 같은 파일시스템에서
`run_summary.json`으로 원자적 rename한다. 내용을 이슈, PR, 채팅 또는
명령행 인자로 복사하지 않는다.

반영 후 `observe_operational_health --once`에서 `legal_data.status=success`,
`issue_count=0`, 예상 `dataset_version`과 `release_version`인지 확인한다.

## 현재 운영 복구와 두 단계 인수 게이트

2026-08-01 incident 당시 운영 SHA `818199aee975`에는 새 app release가 요구하는
seed source descriptor가 없었다. invalid candidate marker/descriptor 격리와 기존
legal 97,394건 exact seed 복구는 완료됐지만, 새 app release는 NEW++ active seed와
SSM version까지 일치해야 한다. 따라서 database maintenance보다 새 앱을 먼저
배포하지 않는다. 다음 순서를 고정하며 한 단계가 실패하면 다음 단계로 진행하지
않는다.

1. 이 구현을 `dev`에 병합하고 로컬 회귀 결과와 대상 SHA를 고정한다.
2. 승인된 S3 URI, manifest 상대 경로, manifest SHA-256을 사용해 현재 운영
   SHA `818199aee975`에 `Recover-PilotOperationalEvidence.ps1`을 실행한다.
   이 명령은 현재 실행 이미지와 release를 확인하고 release-local/shared
   evidence 및 descriptor를 원자적으로 복구한 뒤 transaction gate를
   실행한다.
3. 현재 운영 SHA에 다음 명령을 실행해 acceptance gate가 `600초` 동안
   연속 `pass`인지 확인한다. `queue_backlog` 같은 일시 경고는
   `decision=reset`으로 연속 시간을 0으로 되돌리고, critical/fail은 즉시
   실패한다.

   ```powershell
   ./deploy/aws-pilot/Confirm-PilotOperationalAcceptance.ps1 `
     -ReleaseTag 818199aee975 `
     -AcceptanceSeconds 600 `
     -MaxWaitSeconds 1200
   ```

4. 고정 bootstrap
   `sha256:af0a4a40f983dcdaeaaeb57e54962a514338b8644c33a6a807f1e6214878b2db`를
   `Maintain-PilotDatabase.ps1`로 stage·promote한다. 이 경로는 provider를
   호출하지 않으며 `3,339 blocks / 825 cases / 2,560 dimensions`, app read-only
   접근과 SSM `PRECEDENT_NEWPLUSPLUS_SEED_VERSION` 일치를 검증한다.
5. 위 복구와 600초 관찰, NEW++ maintenance가 모두 성공한 뒤에만
   app-release pipeline 승인을 수행한다. target backend image는 container 교체 전에
   `verify_precedent_newplusplus_seed`와 `verify_pgvector_rag_readiness`를 통과해야
   하며, 후보 배포는 release-bound evidence를 검증·원자 승격하고 transaction
   gate를 통과해야 한다.
6. 후보 SHA에도 `Confirm-PilotOperationalAcceptance.ps1`을 실행해 다시
   600초 연속 `pass`를 확인한다.
7. 그 다음에만 G8 운영 smoke와 배포 후 `13개 E2E`를 시작한다.

복구와 acceptance 명령에는 유료 공급자 동의 switch나 seed 적재 명령이
없다. 승인된 immutable seed의 URI·경로·SHA 검증이 실패하면 자동 적재로
우회하지 않고 중단한다. 전체 seed reload 또는 유료 smoke가 필요하면 정확한
명령과 비용 범위를 제시하고 별도 명시 승인을 받은 뒤 수행한다.

수동 복구가 필요하면 `Rollback-Pilot.ps1`을 사용한다. 이 명령은 대상
release의 evidence를 서비스 변경 전에 검증하고, shared evidence를 원자
전환한 뒤 transaction gate를 통과한 경우에만 `current` 링크를 바꾼다.
실패 시 명령 시작 전 release, shared evidence의 존재/내용, 심볼릭 링크를
복원한다. DB migration과 seed 데이터 자체는 자동으로 되돌리지 않는다.

NEW++ seed pointer만 되돌릴 때는 `Rollback-PilotPrecedentSeed.ps1`에 현재 active
seed version과 해당 command를 포함한 immutable release tag를 명시한다. 실제
active가 다르거나 verified previous가 없으면 `ACTIVE_SEED_CHANGED` 또는
`PREVIOUS_SEED_UNAVAILABLE`로 중단한다. 성공 시 DB pointer, SSM expected version,
master/app read-only verification까지 일치시킨다. 이 명령은 app image나 legal
97,394 seed를 변경하지 않는다.

app 검증과 readiness는 `blocks` active view, `active_seed`, `seed_releases`만
조회하며 inactive `block_versions` 권한을 요구하지 않는다. rollback journal이
`verified`면 정상 완료다. DB 교환 뒤 오류가 발생했지만 original DB pointer와 SSM을
되돌려 재검증한 `compensated`는 marker/profile을 안전하게 정리한 뒤에도 명령을
실패로 보고하므로 원인을 조사해야 한다. `recovery_required`, 중간 상태, journal
probe 실패, timeout·cancel 미확정이면 database-maintenance profile과 marker를
유지하며 운영 traffic을 재개하지 않는다.

## CloudWatch와 SNS

Terraform은 다음을 만든다.

- 전용 CloudWatch Log Group과 30일 기본 보존
- monitor heartbeat, queue age, stale lease, Worker/provider 실패,
  법령 데이터 문제 metric filter
- 각 metric의 ALARM/OK 알림을 전달하는 SNS topic
- `operational_alert_email`이 있을 때만 생성되는 email subscription

실제 이메일 주소는 커밋하지 않은 `terraform.tfvars`에만 입력한다.

```hcl
operational_alert_email = "private-team-address"
```

Terraform 적용 후 AWS가 보낸 SNS 구독 확인 메일에서 **구독 확인** 링크를
사람이 한 번 눌러야 이메일이 전달된다. 확인 전 `PendingConfirmation`은
정상적인 중간 상태이며, 주소나 확인 링크를 이슈에 붙이지 않는다.

이메일을 입력하지 않아도 Log Group, metric과 alarm은 생성된다. 다만 실제
운영 트래픽 전환 전에는 승인된 수신 채널 하나와 ALARM/OK 수신을 확인한다.

## 임계값 보정

저장소의 값은 파일럿 초기값이다.

- oldest queue age: 300초
- stale running·Worker 실패·provider 실패·법령 문제: 0 초과
- heartbeat: 1분 주기 3회 누락

최종 임계값은 실제 부하 결과의 정상 p95/p99 처리 시간, cold start, 공급자
latency와 비용 한도를 검토한 뒤 `terraform.tfvars`에서 승인한다. 실제 부하
증적 없이 알람 소음을 줄이기 위해 임계값만 높이지 않는다.

## 배포 후 검증

1. `ops-monitor`가 running인지 확인한다.
2. CloudWatch Log Group에 `operational_health.v1` 한 줄이 매분 생성되는지
   확인한다.
3. snapshot에 금지된 사용자 원문·secret·경로가 없는지 표본 확인한다.
4. 비식별 테스트 작업으로 queue가 증가했다가 정상적으로 0이 되는지 확인한다.
5. 운영 승인 창에서 임계값을 일시적으로 낮춘 테스트 alarm을 발생시켜
   ALARM 메일을 확인한다.
6. 임계값을 승인값으로 복구하고 OK 메일을 확인한다.
7. 실행 시각, release tag, alarm 이름, ALARM/OK 수신 시각만 증적으로
   기록한다.

실제 AWS 계정, 운영 이메일, 운영 DB와 외부 공급자가 없는 로컬/CI 검증은
Terraform·Compose 계약과 개인정보 비노출 회귀까지만 증명한다.
