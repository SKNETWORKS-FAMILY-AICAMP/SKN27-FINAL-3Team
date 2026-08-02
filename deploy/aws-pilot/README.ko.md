# Pilot 배포 운영 문서

Pilot 런타임은 Caddy, HAProxy, frontend, backend, agent worker, file-scan worker,
Redis, ClamAV 및 PostgreSQL/pgvector를 사용한다. 검색은 법령, review case,
fault-ratio precedent 모두 PostgreSQL pgvector로만 수행한다.

## 배포 전 필수 조건

1. 데이터베이스 백업을 완료한다.
2. review case와 fault-ratio precedent의 source DB 적재·임베딩·HNSW 생성을 완료한다.
3. 법령 seed bundle을 검증하고 아래 명령으로 세 도메인의 상태가 `ready`인지 확인한다.

   ```powershell
   python backend/manage.py verify_pgvector_rag_readiness --format json
   ```

4. `runtime.env.example`을 저장소 밖의 안전한 위치에 복사해 모든 `REPLACE_` 값을 채운다.

## 배포 흐름

1. `Deploy-Pilot.ps1 -StageForInitialRagBootstrap`으로 Redis·ClamAV·backend만 격리 stage한다.
2. `Load-Rag-Seed-Pilot.ps1`으로 법령 seed를 적재한다. 이 명령은 manifest 무결성을 검사하고
   `verify_pgvector_rag_readiness`, 법령 smoke, text-ML `--require-pgvector` smoke를 순서대로 실행한다.
3. `Deploy-Pilot.ps1`으로 promotion한다. readiness, object-storage, supervisor, HTTP smoke를 확인한다.

## Caddy host-network cutover

When Docker host-port publishing is unavailable, the Compose-managed Caddy
service uses host networking and resolves only the private `edge-rate-limit`
address. It runs as UID/GID `10001`; the deployment installs the matching IMDS
firewall script before Compose starts, so Caddy cannot reach EC2 metadata.

1. Record the existing public IPv4 TCP 80 and 443 security-group rules, then
   revoke only those two rules while the release is staged.
2. Complete the release stage with
   `-AllowCaddyOfflineForHostNetworkCutover`, then run normal promotion. Use
   that switch only while those public ingress rules remain blocked. Verify
   Caddy, backend readiness, `/api/health/live/`, and `/api/health/ready/`
   from the host.
3. Restore only the recorded TCP 80 and 443 rules after those checks pass, then
   perform the public health check.
4. If any check fails, keep public ingress blocked and use `Rollback-Pilot.ps1`;
   do not start a manual host-network Caddy container.

## 롤백과 관찰

- `Rollback-Pilot.ps1`은 대상 release의 법령 operational evidence를 먼저 검증하고,
  애플리케이션과 shared evidence를 함께 전환한다. transaction gate 실패 시 명령 시작 전
  release·shared evidence·`current` 링크를 복원한다. pgvector 데이터나 DB migration은
  자동 되돌리지 않는다.
- 배포 뒤에는 error rate, pgvector unavailable 비율, no-result 비율, p50/p95 latency와 HNSW index
  상태를 관찰한다.
- 운영 데이터와 클라우드 리소스 삭제는 이 저장소 변경과 별개로 승인된 변경 창에서 수행한다.

## CodePipeline 앱 이미지 승인 배포

`pilot_app_release_enabled=true`는 기존 Source/Build Pipeline 뒤에
`ApprovePilotAppRelease` 승인 단계를 추가한다. 이 경로는 Build가 성공해 ECR에
immutable commit tag가 올라간 경우에만 사용한다.

현재 운영 SHA `818199aee975`에 seed descriptor가 없으면 app-release pipeline을
먼저 승인하지 않는다. 승인된 URI·manifest 경로·SHA로
`Recover-PilotOperationalEvidence.ps1`을 실행하고 transaction gate와
`Confirm-PilotOperationalAcceptance.ps1 -ReleaseTag 818199aee975`의 600초 연속
통과를 확인한 뒤 아래 절차를 진행한다.

1. CodePipeline의 Build 결과에서 대상 backend/frontend commit tag를 확인한다.
2. 해당 코드가 앱 이미지 변경만 포함하는지 확인한 뒤 `ApprovePilotAppRelease`를 승인한다.
3. Deploy CodeBuild와 SSM command 결과에서 evidence 검증·원자 전환,
   transaction gate, `migrate --check`, backend/frontend
   restart, HTTPS live/ready 확인이 모두 성공했는지 확인한다.
4. 후보 SHA에 `Confirm-PilotOperationalAcceptance.ps1`을 실행해 600초 연속
   acceptance를 확인한 뒤에만 G8 smoke와 13개 E2E를 시작한다.
5. 실패하면 Pipeline은 실패로 종료되며 release runner가 실제 이전 `RELEASE_TAG`와
   명령 시작 전 evidence를
   rollback 한다. SSM 결과와 Deploy CodeBuild log를 보관하고, 새 승인은 문제를
   해결한 commit에서만 다시 진행한다.

Release timeout은 안쪽 단계가 먼저 종료되도록 계층화한다. SSM command는 최대
1,500초, release runner polling은 최대 1,680초, Deploy CodeBuild는 최대 40분이다.
polling timeout이 발생하면 runner는 SSM stdout/stderr를 수집한 뒤 command 취소를
시도한다. Deploy CodeBuild log에서 `SSM_CANCEL_STATUS=complete` 또는
`SSM_CANCEL_STATUS=incomplete`를 확인한다.

원격 전환 실패 시 rollback은 evidence 복원과 서비스별 복구를 끝까지 시도한다.
`ROLLBACK_STATUS=complete`는 모든 복구 단계가 성공했다는 의미이고,
`ROLLBACK_STATUS=incomplete steps=...`는 나열된 단계에 수동 개입이 필요하다는
의미다. incomplete 상태에서는 Pipeline을 다시 승인하지 말고 대상 EC2의 현재
release tag, backend/frontend/worker 컨테이너와 shared evidence를 먼저 확인한다.

이 경로는 RAG seed, paid smoke, Vision Worker, DB schema 변경, Compose 또는 Caddy
변경을 실행하지 않는다. 위 항목이나 법령/그래프 적재가 필요한 release는 반드시
기존 `Deploy-Pilot.ps1`의 검토된 전체 절차를 사용한다.

evidence-only 복구와 acceptance watcher에는 유료 공급자 또는 seed loader 실행
switch가 없다. immutable seed 검증 실패를 자동 적재로 우회하지 말고, 전체 seed
reload나 유료 smoke가 정말 필요할 때만 별도 승인받는다.

활성화는 코드 merge만으로 되지 않는다. 검토된 Terraform plan에서
`ci_enabled=true`와 `pilot_app_release_enabled=true`를 함께 설정해야 한다.

## 공통 운영 통제

- 비용 가드레일: Pilot은 `t3a.large` 이상의 8 GiB x86 인스턴스를 사용하며, ClamAV 재적재와
  운영 headroom을 위해 메모리 50%, 디스크 80%, 경보 임계치 100%를 관찰한다.
- RDS snapshot 정책은 기본적으로 final snapshot을 남긴다. `disposable` 환경에서만 명시적으로
  final snapshot 생략을 승인한다. shared RDS의 seed 변경은 법령 loader의 atomic transaction 범위만
  보장하며, source DB 임베딩 작업과 함께 변경 창에서 수행한다.
- 배포/롤백/teardown은 SSM을 통해 실행하고, IMDS 접근은 backend·worker만 허용한다. credential proxy를
  도입하는 경우에도 이 제한을 유지한다.
- 이미지 digest는 `docker buildx imagetools inspect`로 확인한다. release cleanup은
  `docker image rm`으로 current와 rollback tag를 제외한 이미지에만 수행한다.
- `Terraform 1.11`의 native S3 lockfile을 사용한다. PostgreSQL maintenance image는
  `postgres:16.14-alpine3.24`의 검토된 digest여야 한다.
- 통합 gate #173과 Google OAuth live exchange gate #192를 포함하며, normal promotion은
  단일 `smoke_supervisor_conversation_runtime`으로 public chat, 배포된 Worker loop,
  실제 non-DL Agent 결과와 reporting handoff gate #193을 promotion 전에 검증한다.
- 모든 외부 이미지 주소는 `@sha256:` digest여야 하며, PostgreSQL maintenance에는
  `POSTGRES_MAINTENANCE_IMAGE_REF`를 사용한다. Docker volume은 release 전환 동안 유지한다.
- image cleanup은 latest 3 releases와 rollback tag를 보존한다.
- 경량 app release도 backend/frontend의 current, target, 최근 immutable SHA 3개를
  보존하고 과거 release tag만 정리한다. Docker volume과 운영 RAG 디렉터리는 정리하지 않는다.
- 경량 app release는 target image pull 후 RAG seed의 S3 실제 크기와 5 GiB 운영 여유를
  합산해 확인하며, 가용 디스크가 부족하면 seed 다운로드 전에 실패한다.
- deployment gate는 fail-closed이다. `.compose.env`에는 이미지 주소와 release tag만 두고,
  application secret은 `.runtime.env`에서만 주입한다.
- acceptance window 동안에는 pgvector readiness와 서비스 health를 확인하고, 승인된 경우에만
  stop/destroy 또는 teardown을 수행한다.
- 단일 production runtime smoke 안의 non-DL provider 실행과 Supervisor provider 실행은
  각각 `-AllowPaidNonDlSmoke`, `-AllowPaidSupervisorSmoke`로 명시 승인해야 한다.
  같은 promotion에서 별도 유료 smoke를 중복 실행하지 않으며 승인자·실행 시각·결과를
  release evidence에 남긴다.
