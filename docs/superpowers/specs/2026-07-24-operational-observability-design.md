# 운영 관측과 CloudWatch 경보 설계

## 목적

운영자가 개인정보, 사용자 원문, OCR 전문, 프롬프트 또는 공급자 원문 오류를
조회하지 않고도 분석 큐와 Worker, 외부 공급자, 법령 데이터 갱신 상태를
확인하고 장애 대응 절차로 이동할 수 있게 한다.

이 단계는 이슈 #299의 운영 관측 범위를 코드와 배포 계약 수준에서 완성한다.
실제 운영 부하에 따른 최종 임계값 확정, 운영 이메일 입력, SNS 구독 확인과
운영 계정에서의 알람 발생 증적은 사람 승인 단계로 남긴다.

## 현재 구조와 제약

- 배포 단위는 단일 EC2의 Docker Compose 파일럿이다.
- 분석 큐의 기준 데이터는 PostgreSQL의 `AgentWorkItem`,
  `AnalysisJob`, `AgentInvocation`이다.
- 기존 Terraform은 EC2 `StatusCheckFailed` 알람만 만든다.
- 애플리케이션 컨테이너 로그는 로컬 `json-file` 드라이버를 사용한다.
- 새 외부 Python 의존성과 애플리케이션의 AWS SDK 직접 호출을 추가하지 않는다.
- 운영 관측 산출물에는 사용자 식별자, 질문, 첨부 이름·경로, OCR 결과,
  프롬프트, 비밀값과 공급자 응답을 포함하지 않는다.

## 검토한 접근

### 1. DB 상태 집계와 구조화 로그 기반 CloudWatch 연결 — 채택

Django 서비스가 안전한 운영 상태 snapshot을 만들고 관리 명령이 JSON 한 줄로
출력한다. 전용 모니터 컨테이너가 이를 주기적으로 실행하고 해당 컨테이너의
로그만 CloudWatch Logs로 보낸다. Terraform metric filter가 숫자 필드를
CloudWatch 지표로 변환하고 알람과 선택적 SNS 이메일 구독에 연결한다.

장점은 로컬에서 DB 집계와 개인정보 경계를 완전히 테스트할 수 있고,
애플리케이션 코드가 AWS API에 결합되지 않는다는 점이다. 단일 EC2 파일럿에도
별도 서버리스 구성 없이 적용할 수 있다.

### 2. 애플리케이션의 `PutMetricData` 직접 호출 — 제외

CloudWatch 지표 생성은 단순하지만 애플리케이션 런타임에 AWS SDK, IAM 쓰기
권한과 네트워크 실패 처리가 추가된다. 관측 실패가 본 서비스 실행 경계에
영향을 줄 수 있어 현재 파일럿에는 적합하지 않다.

### 3. EventBridge와 Lambda 기반 외부 점검 — 제외

애플리케이션과 격리되는 장점이 있으나 VPC/RDS 접근, 자격 증명, 배포 단위와
비용이 늘어난다. 현재 단일 EC2 파일럿의 범위를 넘어선다.

## 운영 상태 계약

새 서비스는 `operational_health.v1` snapshot을 생성한다.

필수 최상위 필드는 다음과 같다.

- `contract_version`
- `event_type`: 항상 `operational_health`
- `observed_at`
- `status`: `pass`, `warn`, `fail`
- `queue`
- `worker`
- `providers`
- `legal_data`
- `alerts`

`queue`는 대기 건수와 가장 오래된 대기 시간, 실행 중 건수와 lease 기준을
넘긴 실행 건수를 포함한다. `worker`는 재시도 대기 건수, 관측 구간 내 최종
실패 건수, timeout 계열 실패 건수를 포함한다. `providers`는 외부 공급자
역할별 실패 건수만 포함하고 원문 오류는 포함하지 않는다. `legal_data`는
검증된 `run_summary`의 상태, stale·missing·failed source 수와
`dataset_version`만 포함한다.

`alerts`는 다음 안전한 코드만 사용한다.

- `queue_backlog`
- `queue_oldest_age_exceeded`
- `worker_lease_stale`
- `worker_retrying`
- `worker_failure`
- `worker_timeout`
- `provider_failure`
- `legal_data_missing`
- `legal_data_stale`
- `legal_data_refresh_failed`
- `monitor_configuration_invalid`

오류 코드와 agent node/provider 역할은 허용 목록으로 정규화한다. 알 수 없는
값은 `unknown`으로 집계하며 원문 문자열을 전달하지 않는다.

## 데이터 흐름

1. `build_operational_health_snapshot()`이 PostgreSQL 상태와 선택적인 법령
   `run_summary`를 읽는다.
2. `observe_operational_health` 관리 명령이 snapshot을 JSON 한 줄로 출력한다.
3. `--loop --interval-seconds 60` 모드는 매 주기 새 snapshot을 출력한다.
4. `ops-monitor` Compose 서비스가 관리 명령을 지속 실행한다.
5. `ops-monitor` 로그만 전용 CloudWatch Log Group으로 전송한다.
6. Terraform metric filter가 snapshot의 숫자 필드를 사용자 지정 지표로
   변환한다.
7. CloudWatch 알람은 임계값을 넘거나 모니터 heartbeat가 사라지면 ALARM이
   된다.
8. 운영 알림 이메일이 설정된 경우 SNS topic이 해당 주소로 확인 메일을 보낸다.
   구독 링크 확인 전에는 이메일 알림이 전달되지 않는다.

## 임계값과 사람 승인

코드 저장소에는 파일럿용 보수적 초기값을 Terraform 변수로 제공한다.

- 가장 오래된 queued 작업: 300초
- stale running lease: 300초
- 최근 Worker 최종 실패: 1건 이상
- 최근 provider 실패: 1건 이상
- stale·missing·failed 법령 source: 1개 이상
- monitor heartbeat 누락: 3개 관측 주기

이 값은 최종 운영 임계값이 아니다. 실제 부하 측정 결과를 보고
`terraform.tfvars`에서 확정하며 변경 이력을 남긴다.

`operational_alert_email`은 선택값이다. 비어 있으면 지표와 알람은 생성하지만
SNS 이메일 구독은 만들지 않는다. 값이 있으면 AWS가 최초 1회 확인 메일을
보내며 사람이 링크를 눌러야 한다. 주소는 코드, 예제 파일, 이슈 또는 PR에
기록하지 않는다.

## 장애 처리

- DB 조회 실패 시 모니터는 종료하지 않고 `status=fail`,
  `monitor_configuration_invalid`만 출력한다.
- 법령 `run_summary`가 없거나 스키마가 잘못되면 각각
  `legal_data_missing`, `monitor_configuration_invalid`로 구분한다.
- snapshot 생성 실패가 분석 API나 Worker를 중단시키지 않는다.
- CloudWatch 로그 전송은 Docker `non-blocking` 모드와 bounded buffer를
  사용한다. 전송 실패가 본 서비스 요청을 차단하지 않으며, heartbeat 누락
  알람으로 모니터 경로 이상을 드러낸다.
- 운영자는 알람 코드에서 runbook의 동일한 코드로 이동하고,
  기존 `job_id` 기반 provenance 명령으로 개별 실행을 조회한다.

## 배포 변경

- `backend/chatbot/operational_observability.py`: 안전한 snapshot 생성
- `backend/chatbot/management/commands/observe_operational_health.py`:
  단발·반복 실행 명령
- `deploy/aws-pilot/docker-compose.pilot.yml`: `ops-monitor` 서비스와
  CloudWatch logging 설정
- `infra/terraform-pilot/observability.tf`: Log Group, metric filter,
  alarms, SNS topic과 조건부 email subscription
- `infra/terraform-pilot/variables.tf`: 조정 가능한 임계값과 선택적 이메일
- `infra/terraform-pilot/iam.tf`: 해당 Log Group에만 쓰는 최소 로그 권한
- `docs/ops/operational-observability-runbook.md`: 알람별 확인·대응·복구
- 체크리스트와 통합 검증 보고서: 구현 증적과 사람 게이트 구분

DB schema migration은 추가하지 않는다.

## 테스트 전략

1. queue가 비어 있을 때 모든 수치가 0이고 `pass`인지 검증한다.
2. 오래된 queued와 stale running lease가 서로 다른 알람을 생성하는지
   검증한다.
3. retry, 최종 실패, timeout과 provider 실패가 관측 구간 안에서 정확히
   집계되는지 검증한다.
4. 법령 run summary의 pass, stale, missing, failed, invalid schema를
   검증한다.
5. snapshot 전체에 사용자 원문, 이메일, 파일명·경로, 프롬프트, 비밀값과
   임의 provider 오류 문자열이 포함되지 않는지 회귀 검증한다.
6. 관리 명령의 단발 JSON 출력과 잘못된 인자 종료를 검증한다.
7. Compose 서비스, CloudWatch log driver, IAM 최소 권한, metric filter,
   알람 변수와 조건부 SNS 구독을 정적 계약 테스트로 검증한다.
8. 기존 전체 Python, Django, frontend build와 Terraform validate를 다시
   실행한다.

## 완료와 남는 사람 작업

코드 단계 완료 조건은 로컬/CI 테스트 통과, Terraform validate, runbook과
체크리스트 갱신, PR 병합이다.

사람은 운영 배포 시 다음만 수행한다.

1. 원하면 실제 알림 이메일을 비공개 `terraform.tfvars`에 입력한다.
2. AWS가 보낸 SNS 구독 확인 링크를 누른다.
3. 실제 부하 측정 결과에 따라 임계값 변경을 승인한다.
4. 운영 계정에서 테스트 알람 수신과 복구를 확인한다.
