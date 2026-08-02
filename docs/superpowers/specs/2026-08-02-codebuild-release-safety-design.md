# CodeBuild Release Safety and Release-Class Design

## 목적

AWS Pilot CI/CD의 정상 배포 의미는 유지하면서 timeout·취소·rollback 관측성 결함을 먼저 수정하고, 후속 변경에서 앱 변경 유형에 따라 과도한 RAG evidence 재검증을 줄인다.

실제 AWS 변경은 두 개의 독립된 Terraform plan으로 나눈다. 1차 plan의 적용 및 검증이 끝나기 전에는 2차 release-class 변경을 적용하지 않는다.

## 현재 구조

현재 Pipeline은 `dev Source -> Build CodeBuild -> Manual Approval -> Release CodeBuild -> SSM 대상 EC2` 순서다.

- Build CodeBuild는 계약 테스트 후 commit SHA 기반 backend/frontend 이미지를 ECR에 push한다.
- Release CodeBuild는 수동 승인 후 지정된 Pilot EC2에 `AWS-RunShellScript`를 전송한다.
- 원격 스크립트는 migration, precedent seed, pgvector readiness, 법령 evidence 및 HTTPS health를 검사하고 실패 시 이전 앱 이미지와 evidence를 복구한다.
- 앱 변경 종류와 관계없이 동일한 검증 경로를 사용한다.

## 1차 변경: 배포 안전성 및 관측성

### IAM

Release CodeBuild 역할에 `ssm:CancelCommand`를 추가한다. Build CodeBuild 역할에는 추가하지 않는다. 기존 `SendCommand` 대상 제한과 나머지 최소 권한 정책은 유지한다.

`GetCommandInvocation`과 `CancelCommand`는 AWS API가 요구하는 resource scope를 사용하되, 다른 EC2·RDS·IAM·ECR push·Parameter Store 권한은 추가하지 않는다.

### Timeout 계층

다음 순서로 바깥 계층에 정리 시간을 확보한다.

1. SSM command `TimeoutSeconds`: 1,500초
2. Release runner polling deadline: 1,680초
3. Release CodeBuild `build_timeout`: 40분

Release CodeBuild `queued_timeout`은 실행 시간과 무관하므로 기존 30분을 유지한다.

### Timeout 처리

polling deadline을 넘기면 다음 순서로 처리한다.

1. 현재 SSM invocation 상태와 stdout/stderr를 best-effort로 수집한다.
2. `CancelCommand`를 실행한다.
3. 취소 API 성공·실패를 명확히 로그에 남긴다.
4. 비영 종료 코드로 Release CodeBuild를 실패시킨다.

로그 수집이나 취소 실패가 원래 timeout 사실을 덮어쓰면 안 된다.

### Rollback 관측성

원격 rollback은 원래 실패 코드를 보존한다. evidence 복원과 각 서비스 복구는 best-effort로 계속 시도하되, 단계별 실패를 누적한다.

최종 로그에는 다음 중 하나가 반드시 남아야 한다.

- `ROLLBACK_STATUS=complete`
- `ROLLBACK_STATUS=incomplete`

불완전 rollback이면 실패한 단계 이름을 함께 출력한다. 원격 명령은 원래 배포 실패와 관계없이 비영 상태를 유지한다. 별도의 AWS 서비스나 신규 알림 인프라는 1차 변경에서 추가하지 않는다.

### 테스트

계약 테스트는 다음을 검증한다.

- Release IAM에 `ssm:CancelCommand`가 있고 Build IAM에는 불필요한 SSM 권한이 없음
- `build_timeout = 40`, SSM 1,500초, polling 1,680초의 순서
- SSM request에 `TimeoutSeconds`가 포함됨
- timeout 시 결과 수집 후 취소가 실행됨
- rollback complete/incomplete 표식과 실패 단계 누적이 존재함
- Release 역할에 기존 금지 권한이 새로 생기지 않음

## 2차 변경: Release class 분리

### Release class

배포 유형은 다음 세 가지로 제한한다.

#### `frontend-only`

- frontend 이미지 변경만 허용한다.
- 현재 검증된 immutable operational evidence를 재사용한다.
- backend 이미지와 DB/RAG 상태를 변경하지 않는다.
- frontend 교체 후 HTTPS live/ready와 transaction health를 확인한다.

#### `backend-schema-free`

- backend 및 backend 이미지를 사용하는 worker 변경을 허용한다.
- `migrate --check`, precedent seed, pgvector readiness 및 release evidence 검증을 유지한다.
- DB migration, seed 적재, Compose/Caddy 및 Vision 변경은 허용하지 않는다.

#### `full-release`

- CodeBuild 경량 release runner로 실행하지 않는다.
- 기존 검토된 `Deploy-Pilot.ps1` 전체 절차를 사용한다.
- DB migration, seed, Vision, Compose, Caddy 또는 인프라 변경이 포함되면 이 유형을 선택한다.

### 유형 선택

변경 파일 자동 판별만으로 운영 배포 유형을 확정하지 않는다. 자동 검사는 잘못된 유형을 차단하는 보조 gate로 사용하고, 승인자가 release class를 명시적으로 선택해야 한다.

선택된 유형, source SHA, backend/frontend image digest, evidence 식별자 및 승인 결과를 release evidence에 기록한다.

### Rollback

- `frontend-only` rollback은 frontend 이미지와 frontend 관련 release 상태만 복구한다.
- `backend-schema-free` rollback은 backend/frontend/worker 이미지와 release evidence를 함께 복구한다.
- `full-release` rollback은 기존 전체 배포 runbook을 따른다.

## 배포 및 AWS 적용 순서

### 1차 plan

1. 테스트를 먼저 추가하고 실패를 확인한다.
2. IAM, timeout, runner 및 rollback logging을 수정한다.
3. 계약 테스트와 AWS Pilot 인프라 테스트를 실행한다.
4. Terraform fmt, validate를 실행한다.
5. 비공개 backend 및 tfvars가 있는 승인된 운영 checkout에서 saved plan을 생성한다.
6. plan에서 IAM과 CodeBuild 변경만 포함되는지 검토한다.
7. 명시적 승인 후 saved plan을 적용한다.
8. CodeBuild 정상 경로와 통제된 timeout 경로를 검증한다.

### 2차 plan

1. 1차 적용의 정상 release와 timeout·rollback evidence를 확인한다.
2. release class 입력·승인·계약 테스트를 추가한다.
3. class별 runner 경로를 구현한다.
4. 각 class의 정상·차단·rollback 시나리오를 검증한다.
5. 별도 Terraform plan을 생성하고 운영 계약 변경을 검토한다.
6. 명시적 승인 후 적용한다.

## 비범위

다음은 이번 설계에서 변경하지 않는다.

- GitHub `dev` source branch 정책
- ECR immutable commit tag 정책
- ECS, ASG 또는 다중 EC2 배포 도입
- DB 자동 migration
- 자동 seed loader 또는 paid smoke 실행
- Vision Worker 배포 방식
- 신규 배포 알림 서비스 도입
- Pipeline artifact 및 CloudWatch 장기 보존 정책 변경

## 성공 기준

1차 변경은 다음 조건을 모두 만족해야 한다.

- SSM timeout 시 CodeBuild가 command 취소를 시도할 권한을 보유한다.
- 원격 timeout이 CodeBuild timeout보다 먼저 종료된다.
- timeout 원인과 취소 결과가 로그에 함께 남는다.
- rollback이 불완전하면 성공처럼 보이지 않는다.
- 기존 앱 release 정상 경로와 최소 권한 금지 목록이 유지된다.
- Terraform plan에 예상하지 않은 런타임·DB·네트워크 리소스 변경이 없다.

2차 변경은 각 release class가 허용된 범위만 변경하고, 잘못 선택된 class가 fail-closed로 차단되며, release evidence에서 승인 유형과 실제 배포 대상을 추적할 수 있어야 한다.
