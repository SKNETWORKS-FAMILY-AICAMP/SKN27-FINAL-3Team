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

- `Rollback-Pilot.ps1`은 애플리케이션 release만 이전 release로 되돌린다. pgvector 데이터나
  DB migration을 자동 되돌리지 않는다.
- 배포 뒤에는 error rate, pgvector unavailable 비율, no-result 비율, p50/p95 latency와 HNSW index
  상태를 관찰한다.
- 운영 데이터와 클라우드 리소스 삭제는 이 저장소 변경과 별개로 승인된 변경 창에서 수행한다.

## CodePipeline 앱 이미지 승인 배포

`pilot_app_release_enabled=true`는 기존 Source/Build Pipeline 뒤에
`ApprovePilotAppRelease` 승인 단계를 추가한다. 이 경로는 Build가 성공해 ECR에
immutable commit tag가 올라간 경우에만 사용한다.

1. CodePipeline의 Build 결과에서 대상 backend/frontend commit tag를 확인한다.
2. 해당 코드가 앱 이미지 변경만 포함하는지 확인한 뒤 `ApprovePilotAppRelease`를 승인한다.
3. Deploy CodeBuild와 SSM command 결과에서 `migrate --check`, backend/frontend
   restart, HTTPS live/ready 확인이 모두 성공했는지 확인한다.
4. 실패하면 Pipeline은 실패로 종료되며 release runner가 이전 `RELEASE_TAG`로
   rollback 한다. SSM 결과와 Deploy CodeBuild log를 보관하고, 새 승인은 문제를
   해결한 commit에서만 다시 진행한다.

이 경로는 RAG seed, paid smoke, Vision Worker, DB schema 변경, Compose 또는 Caddy
변경을 실행하지 않는다. 위 항목이나 법령/그래프 적재가 필요한 release는 반드시
기존 `Deploy-Pilot.ps1`의 검토된 전체 절차를 사용한다.

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
- deployment gate는 fail-closed이다. `.compose.env`에는 이미지 주소와 release tag만 두고,
  application secret은 `.runtime.env`에서만 주입한다.
- acceptance window 동안에는 pgvector readiness와 서비스 health를 확인하고, 승인된 경우에만
  stop/destroy 또는 teardown을 수행한다.
- 단일 production runtime smoke 안의 non-DL provider 실행과 Supervisor provider 실행은
  각각 `-AllowPaidNonDlSmoke`, `-AllowPaidSupervisorSmoke`로 명시 승인해야 한다.
  같은 promotion에서 별도 유료 smoke를 중복 실행하지 않으며 승인자·실행 시각·결과를
  release evidence에 남긴다.
