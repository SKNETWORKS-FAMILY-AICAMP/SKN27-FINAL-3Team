# AWS CodeBuild 제약 검토 보고서

## 1. 문서 목적

이 문서는 현재 프로젝트의 AWS CodeBuild 및 CodePipeline 구성에 적용된 제약을 검토하고, 다음 항목을 구분해 정리한다.

- 운영 안전을 위해 유지해야 하는 제약
- 지나치게 강하거나 운영을 불편하게 만드는 제약
- 구성과 실행 코드가 불일치하는 명백한 결함
- 개선 우선순위와 권고 변경안

분석 범위는 저장소의 Terraform, buildspec, 배포 스크립트, 계약 테스트 및 운영 문서다. 실제 AWS 계정에 적용된 Terraform state와 IAM 정책은 별도로 조회하지 않았으므로, 이 문서의 결론은 **저장소에 선언된 구성 기준**이다.

## 2. 현재 배포 구조 요약

현재 Pipeline은 다음 구조로 설계돼 있다.

```text
GitHub dev 브랜치
  -> Build CodeBuild
     - 인프라 및 계약 테스트
     - backend/frontend 이미지 빌드
     - commit SHA 기반 immutable ECR push
  -> 수동 승인
  -> Release CodeBuild
     - 지정된 Pilot EC2에 SSM 명령 전송
     - 사전 검증, 서비스 전환, health gate
     - 실패 시 이전 이미지와 evidence 복구
```

Build CodeBuild와 Release CodeBuild는 역할과 IAM 권한이 분리돼 있다. Build는 이미지 생성까지만 담당하고, Release는 이미 생성된 이미지를 지정된 단일 EC2에 반영한다.

## 3. 종합 판단

전체적인 보안 방향과 fail-closed 정책은 적절하다. 특히 빌드와 배포 역할 분리, 수동 승인, immutable image, 제한된 IAM, 배포 전 readiness 검증은 Pilot 운영 환경에 맞는 안전장치다.

다만 비정상 경로에는 다음 문제가 있다.

1. SSM 명령을 취소하는 코드가 있지만 해당 IAM 권한이 없다.
2. CodeBuild 제한 시간과 내부 SSM 제한 시간이 동일해 정상적인 취소 및 오류 수집 여유가 없다.
3. rollback 과정의 실패가 대부분 숨겨져 불완전 복구를 감지하기 어렵다.
4. 앱 이미지 배포가 RAG evidence 재생성과 강하게 결합돼 배포 실패 지점이 과도하게 많다.

즉, 정상 배포 경로가 과하게 엄격한 것이 핵심 문제라기보다 **timeout, 부분 장애, rollback 실패에 대한 통제와 관측성이 부족한 것**이 더 큰 문제다.

### 개선 적용 상태

- 저장소 구현: `ssm:CancelCommand`, 계층형 timeout 및 rollback 상태 기록 반영 완료
- 로컬 검증: 관련 AWS Pilot 테스트 121개, Bash 구문 및 Terraform validate 통과
- 실제 AWS 적용: 미적용
- 2차 release class 분리: 1차 AWS 적용 및 정상·timeout 운영 검증 후 진행

저장소 구현 완료와 실제 AWS 반영 완료를 같은 상태로 간주하지 않는다. 실제 적용은
비공개 backend와 tfvars로 생성한 saved Terraform plan을 검토한 뒤 별도 승인한다.

## 4. 즉시 수정해야 하는 문제

### 4.1 `ssm:CancelCommand` 권한 누락

#### 현재 상태

Release 스크립트는 SSM 명령이 1,800초를 초과하면 다음 명령을 실행한다.

```bash
aws ssm cancel-command
```

그러나 Release CodeBuild IAM에는 다음 권한만 선언돼 있다.

- `ssm:SendCommand`
- `ssm:GetCommandInvocation`

`ssm:CancelCommand`는 없다.

#### 위험

- CodeBuild가 실패한 뒤에도 EC2에서 SSM 명령이 계속 실행될 수 있다.
- 운영자는 배포 실패, rollback 진행, 원격 명령 지속 상태를 구분하기 어렵다.
- Pipeline을 재실행하면 기존 maintenance lock과 충돌할 수 있다.
- 실제 timeout 원인 대신 `AccessDenied`가 최종 오류로 노출될 수 있다.

#### 권고

- Release CodeBuild 역할에 `ssm:CancelCommand`를 추가한다.
- 가능한 범위에서 명령 및 대상 리소스 조건을 제한한다.
- 계약 테스트에 `ssm:CancelCommand` 존재 여부를 추가한다.
- timeout 테스트에서 실제 취소 경로가 실행되는지 검증한다.

### 4.2 CodeBuild와 SSM timeout이 모두 30분

#### 현재 상태

- Release CodeBuild `build_timeout`: 30분
- Release CodeBuild `queued_timeout`: 30분
- Release 스크립트 SSM polling timeout: 1,800초

#### 위험

안쪽과 바깥쪽 timeout이 동시에 만료되므로 스크립트가 다음 작업을 수행할 여유가 없다.

- SSM command 취소
- 최종 stdout/stderr 수집
- 명확한 timeout 메시지 출력
- rollback 결과 확인

CodeBuild가 먼저 강제 종료되면 원격 명령은 계속 실행될 수 있다.

#### 권고

timeout을 다음처럼 계층화한다.

```text
원격 SSM 명령 제한 < 스크립트 polling 제한 < CodeBuild 제한
```

권장 예시는 다음과 같다.

- SSM command `TimeoutSeconds`: 약 24~25분
- Release 스크립트 polling timeout: 약 27~28분
- Release CodeBuild timeout: 40분

정확한 값은 실제 배포 소요 시간의 p95를 측정한 뒤 조정한다.

### 4.3 rollback 실패가 숨겨짐

#### 현재 상태

rollback 함수의 여러 명령이 다음 형태로 실행된다.

```bash
command >/dev/null 2>&1 || true
```

best-effort 복구는 필요하지만 서비스별 복구 실패 여부가 최종 로그에 남지 않는다.

#### 위험

- backend는 복구됐지만 worker는 실패한 부분 복구 상태를 놓칠 수 있다.
- 원래 배포 실패와 rollback 실패를 분리해 판단하기 어렵다.
- Pipeline에는 단순 실패만 표시되고 수동 개입 필요 여부가 드러나지 않는다.

#### 권고

- 원래 배포 실패 코드를 별도로 보존한다.
- rollback 단계별 성공 여부를 기록한다.
- `ROLLBACK_OK` 또는 실패 항목 배열을 사용해 결과를 누적한다.
- rollback이 불완전하면 명확한 별도 메시지와 종료 코드를 사용한다.
- CloudWatch/SNS 알림에 `deployment_failed`와 `rollback_incomplete`를 구분한다.

## 5. 과도하거나 운영을 불편하게 만드는 제약

### 5.1 동일 commit SHA 이미지 재빌드 불가

#### 현재 상태

ECR에 동일한 12자리 commit SHA 태그가 존재하면 빌드를 건너뛴다. 기존 이미지를 덮어쓰지 않는 immutable 정책이다.

#### 장점

- 동일 태그가 서로 다른 이미지를 가리키는 문제를 방지한다.
- release와 Git commit의 대응 관계가 명확하다.
- rollback 및 감사 추적이 쉬워진다.

#### 운영상 제약

- 잘못된 build argument로 생성된 이미지를 동일 commit에서 고칠 수 없다.
- 외부 의존성이나 빌드 환경 문제로 잘못 생성된 이미지도 재사용된다.
- frontend의 `VITE_GOOGLE_CLIENT_ID`가 바뀌어도 동일 SHA는 재빌드되지 않는다.

#### 판단 및 권고

immutable 정책 자체는 유지하는 것이 맞다. 다만 예외 절차가 필요하다.

- 정상 수정은 새 commit을 만들어 새 SHA 이미지로 배포한다.
- 기존 immutable 태그를 덮어쓰는 기능은 추가하지 않는다.
- 긴급 상황의 이미지 폐기 및 재생성 절차를 문서화한다.
- 필요하면 이미지 digest, build argument, source SHA를 provenance artifact로 저장한다.

### 5.2 앱 배포와 RAG operational evidence 재생성의 강한 결합

#### 현재 상태

backend/frontend 앱 배포에서도 다음 절차를 수행한다.

- 법령 seed descriptor 확인
- S3 seed bundle 다운로드
- manifest SHA256 검증
- legal operational evidence 생성 및 검증
- release/shared evidence 원자적 교체

#### 장점

- 앱 release SHA와 운영 evidence의 대응 관계를 보장한다.
- 검증되지 않은 법령 데이터 상태에서 앱만 전환되는 것을 방지한다.

#### 운영상 문제

- frontend 스타일 변경도 seed S3 장애 때문에 실패할 수 있다.
- 앱과 데이터 evidence의 수명주기가 강하게 결합된다.
- 다운로드와 검증 시간이 30분 timeout 위험을 높인다.
- RAG와 무관한 변경도 pgvector 및 seed 상태에 종속된다.

#### 권고

즉시 제거하기보다 evidence 계약을 별도로 설계한다.

- immutable seed manifest가 이미 검증된 경우 전체 다운로드를 재사용하거나 캐시할 수 있는지 검토한다.
- 앱 변경 유형별로 필요한 gate를 분리할 수 있는지 검토한다.
- evidence가 반드시 release SHA별로 생성돼야 하는지 운영·감사 요구사항을 재확인한다.
- 계약을 변경하기 전까지 현재 fail-closed 동작은 유지한다.

### 5.3 DB migration을 허용하지 않는 앱 배포 경로

#### 현재 상태

Release는 `migrate --check`만 실행한다. 적용되지 않은 migration이 있으면 배포가 실패하며 migration을 자동 실행하지 않는다.

#### 판단

단일 EC2 Pilot 환경에서 자동 migration을 바로 허용하지 않는 것은 합리적이다. 다만 현재 경로는 실제로는 모든 앱 배포가 아니라 **schema 변경이 없는 앱 배포**만 지원한다.

#### 권고

- 운영 문서와 Pipeline 이름에서 `schema-free release` 범위를 명확히 표현한다.
- migration 포함 release는 현재 전체 배포 절차를 유지한다.
- 장기적으로 expand/contract 방식의 호환 가능한 migration만 허용하는 별도 승인 경로를 검토한다.

### 5.4 동일 release 재승인을 실패 처리

#### 현재 상태

대상 SHA가 현재 `RELEASE_TAG`와 같으면 오류로 종료한다.

#### 문제

- 중복 승인이나 Pipeline 재시도가 운영 장애처럼 표시된다.
- 이미 성공한 배포와 실제 실패를 구분하기 어렵다.

#### 권고

다음 조건을 모두 만족하면 성공적인 no-op으로 처리하는 방안을 검토한다.

- 현재 release tag가 대상 SHA와 동일함
- 실행 중인 이미지 digest가 기대값과 동일함
- operational evidence가 존재하고 유효함
- live/ready 및 transaction gate가 정상임

상태가 불완전하다면 no-op 성공으로 처리하지 말고 recovery 절차로 전환해야 한다.

### 5.5 기존 컨테이너가 없으면 Pipeline 복구 불가

#### 현재 상태

rollback snapshot 생성을 위해 기존 backend와 frontend 컨테이너가 모두 존재해야 한다.

#### 장점

- rollback 가능한 이미지가 확보되지 않은 상태에서 전환하는 것을 막는다.

#### 문제

- frontend 또는 backend가 이미 삭제된 부분 장애 상태에서 Pipeline으로 복구할 수 없다.
- 최초 배포에 사용할 수 없다.

#### 권고

- 일반 release 경로의 현재 제약은 유지한다.
- 최초 배포와 부분 장애 복구를 위한 별도 승인된 recovery 절차를 문서화한다.
- recovery 경로에서는 ECR digest 및 이전 승인 release 정보를 기준으로 복구 이미지를 결정한다.

## 6. 재현성과 공급망 측면의 부족한 부분

### 6.1 CodeBuild 관리형 이미지가 digest로 고정되지 않음

현재 빌드 환경은 다음 이동 태그를 사용한다.

```text
aws/codebuild/amazonlinux-x86_64-standard:5.0
```

애플리케이션 외부 이미지는 digest를 요구하면서 빌드 환경은 이동 태그이므로 완전한 재현성은 보장되지 않는다.

AWS 관리형 이미지 특성상 현실적인 예외일 수 있으므로 다음 순서가 적절하다.

1. 관리형 CodeBuild 이미지를 digest 정책의 예외로 명시한다.
2. 빌드 환경 변경을 감지할 수 있도록 CodeBuild image/runtime 정보를 artifact에 기록한다.
3. 규제 또는 재현성 요구가 높아지면 검증된 커스텀 CodeBuild 이미지를 ECR digest로 고정한다.

### 6.2 매 실행 시 PyPI에서 pytest 설치

#### 현재 상태

buildspec은 매번 다음 패키지를 설치한다.

```text
pytest==9.1.1
```

#### 문제

- PyPI 또는 외부 네트워크 장애가 이미지 빌드를 차단한다.
- 패키지 hash가 고정되지 않았다.
- 캐시가 없어 매번 설치 비용이 발생한다.

#### 권고

- 테스트 의존성을 hash가 포함된 lock 파일로 관리한다.
- 필요하면 내부 package mirror를 사용한다.
- 검증된 커스텀 빌드 이미지에 테스트 도구를 포함하는 방안을 검토한다.
- CodeBuild cache는 비용과 invalidation 정책을 정한 후 도입한다.

## 7. 로그와 운영 증거 보존

현재 보존 정책은 다음과 같다.

- CodeBuild CloudWatch 로그: 기본 30일
- Pipeline artifact 현재 버전: 14일
- Pipeline artifact 이전 버전: 7일
- 미완료 multipart upload: 1일

일반 CI 로그에는 합리적이지만 수동 승인된 운영 배포 증거로는 짧을 수 있다.

### 권고

- 일반 CI 로그는 30일을 유지할 수 있다.
- 운영 승인 및 Release CodeBuild 로그는 90일 이상을 검토한다.
- SSM command ID, 대상 release SHA, 이미지 digest, 승인 정보, stdout/stderr, rollback 결과를 별도 운영 evidence로 보관한다.
- 장기 보존이 필요하면 versioning과 lifecycle이 적용된 별도 S3 경로를 사용한다.

## 8. 유지해야 하는 제약

다음 제약은 현재 Pilot 구조에서 적절하므로 유지하는 것이 좋다.

- `dev` 브랜치만 운영 Pipeline의 소스로 사용
- Build와 Release CodeBuild의 역할 및 IAM 분리
- 운영 반영 전 수동 승인
- Git SHA 기반 immutable 이미지 태그
- ECR 조회 오류를 이미지 부재로 간주하지 않는 fail-closed 처리
- Build 역할에서 EC2, RDS, SSM, Secrets Manager, IAM 변경 권한 제거
- Release 역할의 SSM 대상을 지정된 Pilot EC2로 제한
- 배포 전 `migrate --check`
- precedent seed version 및 pgvector readiness 검증
- backend/frontend HTTPS live/ready 확인
- transaction health gate 통과 후 완료 처리
- paid smoke, seed loader, Vision, Compose 및 Caddy 변경을 경량 앱 배포에서 제외
- maintenance lock을 통한 동시 배포 방지
- 실패 시 이미지와 operational evidence를 함께 복구
- Pipeline artifact bucket의 public access 차단, 암호화 및 versioning

## 9. 개선 우선순위

| 우선순위 | 항목 | 판단 | 권고 조치 |
|---|---|---|---|
| P0 | `ssm:CancelCommand` 권한 누락 | 명백한 결함 | IAM 및 계약 테스트 수정 |
| P0 | CodeBuild와 SSM timeout이 모두 30분 | 복구 경쟁 조건 | 계층형 timeout 적용 |
| P1 | rollback 실패가 숨겨짐 | 운영 위험 | 단계별 결과 기록 및 경보 |
| P1 | 운영 배포 로그 보존 부족 | 감사·장애 분석 위험 | Release evidence 장기 보존 |
| P2 | 앱 배포와 RAG evidence 재생성 결합 | 과한 결합 | evidence 계약 재설계 검토 |
| P2 | 동일 SHA 재실행을 실패 처리 | 운영 편의성 문제 | 검증된 no-op 성공 처리 검토 |
| P2 | 기존 컨테이너가 없으면 복구 불가 | recovery 경로 부재 | 별도 recovery runbook 작성 |
| P3 | PyPI 실시간 설치 | 재현성·가용성 문제 | lock/hash 또는 내부 mirror |
| P3 | 관리형 CodeBuild 이미지 이동 태그 | 재현성 문제 | 예외 문서화 또는 커스텀 이미지 |

## 10. 권장 실행 순서

### 1단계: 즉시 수정

1. Release CodeBuild IAM에 `ssm:CancelCommand`를 추가한다.
2. 관련 계약 테스트를 추가한다.
3. SSM, polling, CodeBuild timeout을 계층화한다.
4. timeout 및 취소 시나리오를 테스트한다.

### 2단계: rollback 관측성 개선

1. rollback 단계별 성공 여부를 로그에 남긴다.
2. 불완전 rollback을 별도 상태로 분류한다.
3. SNS 또는 운영 경보에 수동 개입 필요 여부를 포함한다.
4. SSM command 결과와 rollback evidence를 장기 보관한다.

### 3단계: 운영 편의성과 결합도 개선

1. 동일 SHA 재실행의 안전한 no-op 조건을 정의한다.
2. 최초 배포 및 부분 장애 recovery runbook을 만든다.
3. 앱 release와 RAG evidence 생성의 결합 필요성을 재검토한다.
4. schema-free release와 migration release를 명확히 분리한다.

### 4단계: 재현성 강화

1. Python 테스트 의존성을 lock/hash로 관리한다.
2. 빌드 provenance에 CodeBuild runtime 정보를 기록한다.
3. 필요할 경우 커스텀 CodeBuild 이미지와 내부 package mirror를 도입한다.

## 11. 검증 기준

개선 작업은 최소한 다음 시나리오로 검증해야 한다.

1. 정상 backend/frontend release 성공
2. SSM 명령 timeout 후 실제 command 취소 확인
3. CodeBuild가 원격 취소와 최종 로그 수집을 마친 뒤 종료되는지 확인
4. backend health 실패 시 이전 release 복구 확인
5. worker 복구 실패 시 `rollback_incomplete`가 명확히 기록되는지 확인
6. 동일 SHA 재실행 정책 확인
7. migration이 포함된 release가 경량 배포에서 차단되는지 확인
8. Vision, RAG loader, paid smoke가 경량 배포에서 실행되지 않는지 확인
9. 운영 evidence에 source SHA, image digest, SSM command ID 및 rollback 결과가 남는지 확인

## 12. 관련 파일

- `infra/terraform-pilot/codebuild.tf`
- `infra/terraform-pilot/codepipeline.tf`
- `infra/terraform-pilot/variables.tf`
- `buildspec.pilot.yml`
- `buildspec.pilot-app-release.yml`
- `deploy/aws-pilot/Build-And-Push-ImmutableImages.sh`
- `deploy/aws-pilot/Release-PilotApp-FromPipeline.sh`
- `deploy/aws-pilot/README.ko.md`
- `test/test_codebuild_pilot_contract.py`
