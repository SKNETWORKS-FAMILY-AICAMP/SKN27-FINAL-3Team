# 2026-08-02 Production Cutover Execution Log

## 목적과 범위

- 실행 경로: AWS Systems Manager(SSM) 단일 경로
- 대상 release: `76c713ec92d6`
- 대상 manifest SHA-256: `9bb155067bdbff2792ff1ceb17002b99431454b31c52029f7cee8af75f2294ac`
- 범위: 초기 public cutover, Google live smoke 1회, paid non-DL smoke 1회, paid Supervisor smoke 1회, 배포 후 13개 E2E
- 기록 원칙: 각 SSM command ID, UTC 시각, 상태, 종료 코드, 자격증명 마스킹 stdout/stderr, 오류 원인과 후속 조치를 기록한다.
- 보안 원칙: Google authorization code, 비밀번호, secret, token, credential 값은 문서와 사용자 메시지에 기록하지 않는다.

## 기준 Git 상태

- 캡처 시각: `2026-08-02T01:55:58.2533878Z`
- 브랜치: `feat-neo4j-exception-observability-hotfix`
- HEAD: `8091ce9c08c8310e6d6c7f9c459331fb6546568e`
- AWS account: `908708651753`
- 리전: `ap-northeast-2`
- pilot instance: `i-08457b1c0bef7d17b`
- 로컬 미커밋 변경:
  - `deploy/aws-pilot/Deploy-Pilot.ps1`
  - `deploy/aws-pilot/Load-Rag-Seed-Pilot.ps1`
  - `test/test_aws_pilot_infrastructure.py`

## 배포 스크립트 사전 회귀 검증

### 이전 public cutover 실패

- SSM command: `38b3d89f-61f6-4c7e-91f3-996382c35c1e`
- 상태: `Failed`
- 종료 코드: `1`
- 마스킹 stderr: `couldn't find env file: /usr/bin/.compose.env`
- 확정 원인: `Deploy-Pilot.ps1`의 normal promotion 분기가 release directory로 이동하기 전에 상대 경로 `.compose.env`를 사용하는 Compose evidence validation을 실행했다. SSM 기본 작업 디렉터리가 `/usr/bin`이므로 `/usr/bin/.compose.env`를 잘못 조회했다.
- 영향: stage shutdown, public symlink cutover, Google code 교환, paid provider smoke 전에 중단됐다. 따라서 공개 서비스와 유료 호출은 실행되지 않았다.
- 수정: evidence validation 앞에 `cd $RELEASE_DIR`를 추가했다.
- 검증:
  - focused regression: `1 passed`
  - PowerShell parser: `PASS`
  - deployment contract suite: `130 passed`
  - `git diff --check`: 통과

## 실행 기록

### S0 — 사전 상태 스냅샷

- SSM command: `037afeec-70cd-4c80-8ed4-fface64c101f`
- 실행 시각: `2026-08-02T01:57:08.878Z`
- 상태: `Success`
- 종료 코드: `0`
- 확인 결과:
  - release directory: 존재
  - initial marker: 존재
  - release evidence: 존재
  - seed descriptor: 존재
  - descriptor manifest SHA-256: 기대값과 일치
- 관측상 주의점: 최초 조회는 잘못 가정한 Compose project명 `skn27-pilot-stage-76c713ec92d6`으로 필터링해 stage 컨테이너를 0개로 표시했다. `readlink -f` 역시 링크 존재 여부 판정에 부적절했다.
- 판정: 원격 상태 문제가 아니라 스냅샷 조회 조건 문제이므로 정확한 project marker와 `test -L` 기반 추가 진단을 실행했다.

### 로컬 진단 명령 구성 오류 2건

- 상태: SSM command 생성 전 로컬 PowerShell parser가 차단
- 원인: Docker label format과 `$PROJECT`를 포함한 중첩 따옴표를 PowerShell 문자열 안에서 잘못 구성했다.
- 운영 영향: 없음. SSM command ID가 생성되지 않았고 원격 명령도 실행되지 않았다.
- 조치: label 출력 의존성을 제거하고 release path와 project marker 기반 고정 문자열 조합으로 변경했다.

### S1 — current 링크 및 실제 stage 진단

- SSM command: `136ca1e1-565b-4ff3-b868-f2554ee4b9f9`
- 실행 시각: `2026-08-02T01:58:32.918Z`
- 상태: `Success`
- 종료 코드: `0`
- 확인 결과:
  - `/opt/skn27-pilot/current`: 없음
  - 실제 stage project: `skn27-stage-76c713ec92d6`
  - initial marker: release tag, manifest SHA-256, stage project가 모두 exact match
  - complete marker: manifest SHA-256 exact match
  - stage backend: healthy
  - stage law-neo4j: healthy
  - stage redis: healthy
  - stage clamav: healthy
- 추가 관측:
  - `skn27-pilot-*` 이름의 3일 전 구형 컨테이너 일부가 unhealthy 또는 exited 상태로 남아 있다.
  - 이 컨테이너들은 `current` 링크가 없는 상태이며 이번 exact stage와 분리되어 있다.
- 판정: 초기 public cutover 전 private stage는 정상이며 exact seed/release marker를 보유한다. 구형 컨테이너 존재 여부는 cutover 스크립트의 host port 해제와 production Compose 전환 과정에서 다시 검증한다.

### S2 — public cutover 재시도

- SSM command: `5863d1f4-4ebb-48b2-8f43-0479ebf136a8`
- 요청 시각: `2026-08-02T11:01:39.408+09:00`
- 상태: `Failed`
- 로컬에서 확인된 선행 단계:
  - Google 일회용 code를 SSM SecureString으로 저장: 성공
  - 클립보드 삭제: 성공
  - parameter metadata 존재 확인: 성공
  - deployment bundle 업로드: 성공
  - deployment manifest 업로드: 성공
- 실패 후 Google code parameter metadata: 없음. 배포 스크립트의 `finally` 정리가 정상 수행된 것으로 판정한다.
- stdout/stderr: 보안 검토가 새 command ID에 대한 별도 명시 승인을 요구해 아직 조회하지 않았다.
- 전체 로그 조회 결과:
  - 법령 evidence validation: `success`
  - stage backend, law-neo4j, redis, clamav: 정상 종료 및 제거
  - 최초 실패: `_script.sh: line 39: cd: /opt/skn27-pilot/current: No such file or directory`
  - 종료 코드: `1`
- 확정 원인: `/opt/skn27-pilot/current` symlink가 없는 초기 배포에서 `readlink -f`가 경로 문자열 자체를 반환했다. 스크립트가 이를 이전 release로 오판해 stage 종료 후 존재하지 않는 `/opt/skn27-pilot/current`로 이동했다.
- 영향 범위: public symlink promotion, Google live smoke, paid non-DL smoke, paid Supervisor smoke 전에 실패했다. 유료 호출은 실행되지 않았다.
- TDD 수정:
  - absent current symlink를 no previous release로 처리하는 regression test가 수정 전 RED임을 확인했다.
  - `readlink` 직후 실제 symlink가 아니면 `PREVIOUS_RELEASE=''`로 정규화했다.
  - focused regression: `1 passed`
  - PowerShell parser: `PASS`
  - deployment contract suite: `131 passed`

## 현재 게이트

- `G0 Git/로컬 상태`: 확인 완료
- `G1 release/seed/evidence`: 통과
- `G2 private stage health`: 통과
- `G3 Google 일회용 코드`: 새 코드 필요
- `G4 public cutover 및 live/paid smoke`: 대기
- `G5 배포 후 13개 E2E`: 대기

### S3 — 실패 후 보존 상태 확인

- SSM command: `99be99eb-1878-486b-a2c1-0b1da50b566a`
- 상태: `Success`
- 종료 코드: `0`
- 확인 결과:
  - current link: 없음
  - release directory: 보존
  - initial marker: 보존
  - complete marker: exact manifest SHA-256 일치
  - seed descriptor: 보존
  - stage running containers: `0`
- 판정: 재시도에 필요한 불변 release/seed 증거는 보존됐고, 이전 실패가 남긴 실행 중 stage는 없다.

### D1 — 디스크 용량 진단

- SSM command: `45f329b1-28c9-4180-af4b-d3397a743e9f`
- 상태: `Success`
- 종료 코드: `0`
- filesystem: `80G` 중 `69G` 사용, `12G` 가용, 사용률 `86%`
- inode: 사용률 `4%`
- Docker images: `41.94GB`, 이 중 `41.26GB` reclaimable
- Docker volumes: `7.448GB`, 이 중 `7.37GB` reclaimable
- 판정: 디스크 압박과 정리 여지는 크지만 현재 가용 공간과 inode가 남아 있으므로 이 수치만으로 새 cutover 실패를 `ENOSPC`로 확정할 수 없다. 실패 command의 stderr에서 `no space left on device` 여부를 확인하기 전에는 Docker prune이나 volume 삭제를 실행하지 않는다.

### S4 — capability 수정 전 public cutover 재시도

- SSM command: `4b07a613-d56d-4716-83c0-cbfe3815b47b`
- 상태: `Failed`
- 종료 코드: `1`
- evidence validation: 2회 성공
- image pull: 성공
- production network 및 Redis container 생성: 성공
- 최초 서비스 실패: production Redis 재시작 루프
- 최종 오류: `Redis did not become ready during bootstrap.`
- public symlink, Google live smoke, paid smoke: 실행 전 실패
- 실패 후 Google code parameter: 자동 삭제 확인

### D2 — Redis 재시작 원인 확정

- volume/permission snapshot: `4beb7607-fa95-4fc7-afc5-0ae45101b124`
  - volume 및 persistence 파일 존재
  - Redis 데이터 UID/GID: `999:1000`
  - 구형 Redis는 별도 volume/network 사용
- persistence integrity:
  - 잘못된 진단 옵션 command `66ff0562-14c9-4489-b35a-e39d1ec6e8b5`: 데이터 검사 전 종료, 원본 변경 없음
  - read-only open 제약 command `dc4b8ee5-4666-44c2-b483-cf5e419e8497`: 원본 변경 없음
  - tmpfs 복사본 검사 `8d9b9fcc-bef5-4472-9607-1eb403a32054`: AOF/RDB 모두 valid
- OOM/event snapshot: `0708ecc1-35f6-4c05-9bed-d5963aae834b`
  - kernel OOM 기록 없음
- 동일 설정 격리 재현: `c0e4470e-5c6e-4497-9a41-ed683a786378`
  - 종료 코드 `1`
  - 로그: `find: ./appendonlydir: Permission denied`
- image entrypoint 확인: `790a38c7-60c1-4fb3-b99d-a882922ce9d5`
  - Redis UID/GID: `999:1000`
  - entrypoint가 root로 `find`/`chown` 후 Redis 사용자로 강등
- capability 가설 검증: `edf14d65-a146-480f-a1ab-5d4149e1176c`
  - `CHOWN`, `DAC_OVERRIDE` 추가 시 Redis 7.4.9 정상 기동
  - `PING=PONG`
- 확정 원인: Compose가 `cap_drop: ALL`을 적용하면서 Redis entrypoint의 기존 `700` persistence directory 탐색과 소유권 정리에 필요한 `DAC_OVERRIDE`, `CHOWN`을 복원하지 않았다. 최초 빈 volume 기동은 성공하지만 stop/start 후 실패하는 재기동 전용 결함이다.
- TDD 수정:
  - Redis capability contract RED 확인
  - Redis에만 `CHOWN`, `DAC_OVERRIDE` 추가
  - focused test `1 passed`
  - deployment contract suite `131 passed`
  - PowerShell parser 및 `git diff --check` 통과

### S5 — Redis capability 로컬 수정 후 cutover 재시도

- SSM command: `6524d02e-39ee-4500-a639-0e003c906da3`
- 상태: `Failed`
- 종료 코드: `1`
- 결과: production Redis가 이전과 동일한 재시작 루프에 진입
- 원격 staged compose 확인:
  - SSM `7fc9bf63-4775-42fe-9794-9792b91ac390`: staged compose SHA-256 `430549fcc55c69c8b9b88946109e0b8b3553f65829d820c33e65fdccd8abc2fa`
  - SSM `1aaf25b8-9e8d-4400-949d-fd7d182a1c81`: Redis `cap_add: [SETGID, SETUID]`
- 확정 원인: normal promotion은 새 bundle을 S3에 업로드하지만 이미 seed/evidence가 완료된 release directory를 다시 materialize하지 않는다. 따라서 로컬 capability 수정이 staged release에 반영되지 않았고, 이전 Redis 결함이 그대로 재현됐다.
- 판정: 이 실패는 capability 수정 자체의 실패가 아니라 immutable staged artifact와 local orchestration fix 사이의 반영 경로 부재다.

### H1 — controlled staged Compose hotpatch

- 최초 hotpatch `5ec35b43-1e8f-4b46-ab00-de7e935615a0`: ZIP entry를 `deploy/aws-pilot/docker-compose.pilot.yml`로 잘못 지정해 파일 교체 전 종료. rollback 상태, 운영 영향 없음.
- bundle path 확인 `c7ff177a-a831-4a8c-9018-245e63c324fb`: 정확한 entry는 ZIP root의 `docker-compose.pilot.yml`.
- 두 번째 hotpatch `cb00e02b-872a-4789-8ce4-8e17a0b8cab6`: CRLF 파일에 exact-line `grep -Fx` guard를 사용해 파일 교체 전 종료. rollback 상태.
- guard 진단 `fdd0a536-58c9-4415-99bf-b0846352265b`:
  - target/backup SHA: `430549fcc55c69c8b9b88946109e0b8b3553f65829d820c33e65fdccd8abc2fa`
  - bundle Compose SHA: `0eb3afad2328285e8c13a52bd49ba2321c51511b6249b7f5ca829a9639fad405`
  - bundle Redis capability: 수정값 확인
  - residual production containers: 없음
  - Compose config: 통과
- CRLF-safe hotpatch `1b7c8533-f812-4486-b35b-ab6bad3194ab`:
  - 상태: `Success`, 종료 코드 `0`
  - 기존 Compose 백업 SHA 검증
  - bundle Compose exact SHA 검증
  - 원자적 단일 파일 교체
  - 실제 stage Redis volume로 production Compose Redis 기동
  - `REDIS_PREFLIGHT=PONG`
  - preflight 컨테이너 및 network 정상 제거
  - staged Compose 최종 SHA: `0eb3afad2328285e8c13a52bd49ba2321c51511b6249b7f5ca829a9639fad405`
- 비차단 경고: Redis가 host `vm.overcommit_memory=1` 권고를 출력했다. 이번 기동과 PING에는 영향이 없었으며 cutover 후 운영 hardening 항목으로 추적한다.

### S6 — Redis hotpatch 후 public cutover 및 live smoke

- SSM command: `a36264d8-313c-4018-ab01-0aa8a16ce3ec`
- 상태: `Failed`
- 종료 코드: `1`
- 실행 시각: `2026-08-02T02:46:41.811Z` ~ `2026-08-02T02:49:11.811Z`
- 통과한 게이트:
  - 법령 evidence validation 2회: `success`
  - production Redis, ClamAV, Neo4j, backend, frontend, edge rate limit, Caddy: healthy
  - production readiness: 통과
  - object storage smoke: 통과
  - Google OAuth authorization-code live smoke: exchange HTTP `200`, replay rejection 확인
  - agent/file-scan worker 기동: 성공
- 최초 실패:
  - command: `smoke_supervisor_conversation_runtime`
  - 예외: `chatbot.repositories.SessionBindingError`
  - reason: `session_unbound`
  - 종료: `failed to run commands: exit status 1`
- 타임아웃 판정:
  - SSM 상태는 `TimedOut`이 아니라 `Failed`이고 명시적인 Python 예외로 종료됐다.
  - 배포 polling 제한은 `1800`초, Supervisor smoke 자체 제한은 `600`초다.
  - `law_ground_search_sync` 이후 object storage와 Google OAuth smoke가 통과했으므로 해당 readiness 항목에서 멈춘 것이 아니다.
- 확정 원인:
  - Supervisor smoke fixture가 세션을 `metadata.guest_id`로 생성했다.
  - 현재 repository 소유권 계약은 `metadata.auth_context.guest_id`만 canonical guest binding으로 인정한다.
  - 따라서 요청의 검증된 guest identity와 기존 smoke 세션을 결합하지 않고 fail-closed 처리했다.
- TDD 수정:
  - chat 제출 직전 실제 smoke session의 canonical `auth_context`를 검사하는 regression test 추가
  - 수정 전 RED: `auth_context`가 `None`
  - smoke fixture에 `auth_state`, `subject_id`, `subject_type`, `guest_id`를 포함한 `auth_context` 저장
  - focused GREEN: `1 test`, `OK`
  - 관련 Supervisor/guest/session 회귀: `28 tests`, `OK`
  - 전체 Django chatbot 회귀: `388 tests`, `OK`
  - AWS pilot deployment contract: `99 passed`
  - `git diff --check`: 통과
- release 경계:
  - 수정 파일은 backend image에 포함되는 management command이므로 기존 `76c713ec92d6` 이미지를 SSM으로 재시도하는 것만으로는 수정이 반영되지 않는다.
  - 다음 단계는 수정된 backend image를 포함한 새 immutable release를 만든 뒤, 단일 SSM deployment 경로로 cutover를 다시 실행하는 것이다.
  - Google authorization code는 재시도 시 새 일회용 code가 필요하다.

### S7 — 새 immutable release 및 exact seed 복구

- 대상 release: `d8de5915f463`
- backend image digest: `sha256:df535682fe4b0eabcf33a065449f599a52f5ce3efedd36caab298bafff72c069`
- frontend image digest: `sha256:39777a3ab78dc26260322c60073f0dfad431de38a84b8cf683bbd561e9737517`
- exact seed manifest SHA-256: `9bb155067bdbff2792ff1ceb17002b99431454b31c52029f7cee8af75f2294ac`
- seed S3 URI: `s3://skn27-pilot-908708651753-clean/_rag-seed/9bb155067bdbff2792ff1ceb17002b99431454b31c52029f7cee8af75f2294ac/`
- seed maintenance SSM command: `86b9e317-2bfd-4c44-8b4f-f9e848d0b865`
  - 상태: `Success`, 종료 코드 `0`
  - manifest hash 및 artifact count 검증: 통과
  - 법령 chunk/embedding: `98,664 / 98,664`
  - 상담사례 embedding: `904`
  - 판례 seed: `825 cases / 3,339 blocks`
  - Neo4j: 법령 source `35`, version `341`, chunk `98,664`, relation `309,132`
  - 법령 검색 및 text-ML 검색 smoke: `pass`
  - 법령 evidence: missing/failed/stale source `0`, release version exact match
- post-seed snapshot SSM command: `79e1165b-af01-4127-914a-0efa2bad982a`
  - private 서비스 4개: 모두 healthy
  - complete marker, release evidence, exact descriptor: 존재 및 일치
  - public current link: 없음
  - forbidden public 서비스: `0`

### S8 — Caddy volume initializer capability 실패

- public cutover SSM command: `2777e14d-598d-4daa-83a4-c8e4265ade20`
- 상태: `Failed`, 종료 코드 `1`
- 실행 시각: `2026-08-02T04:25:49.578Z` ~ `2026-08-02T04:27:56.578Z`
- 통과한 게이트:
  - release-bound 법령 evidence validation 2회: `success`
  - production Redis, ClamAV, law-Neo4j, backend, frontend, edge-rate-limit: healthy 또는 정상 시작
- 최초 실패:
  - service: `caddy-volume-init`
  - 결과: `service "caddy-volume-init" didn't complete successfully: exit 1`
- 실패 경계:
  - Google code exchange 전
  - paid Supervisor/non-DL smoke 전
  - public current symlink 생성 전
  - 따라서 이 실행의 유료 provider 호출은 `0`이며 public release는 생성되지 않았다.
- rollback 및 capability 진단 SSM command: `44ccdb10-96ae-4c8c-8a41-89f513c92363`
  - current link: 없음
  - production/stage container: `0 / 0`
  - release, stage marker, complete marker, release evidence: 보존
  - shared evidence: rollback으로 제거
  - Caddy data/config/log volume root: 모두 mode `750`, owner `10001:10001`
  - 현재 initializer와 같은 `cap_drop: ALL`, `cap_add: CHOWN` 조건: 세 경로 모두 traverse 실패
  - 기본 root capability 조건: 세 경로 모두 traverse 성공
- 확정 원인:
  - `caddy-volume-init`는 기존 Caddy volume을 `chown -R`하지만 `CHOWN`만 복원한다.
  - mode `750`, owner `10001:10001`인 기존 volume을 root UID `0`이 재귀 탐색하려면 `DAC_OVERRIDE`가 필요하다.
  - 최초 빈 volume이 아니라 재사용 volume에서만 발생하는 capability 회귀다.
- TDD 수정:
  - initializer에 `CHOWN`과 `DAC_OVERRIDE`가 모두 필요하다는 contract test를 먼저 변경했다.
  - 수정 전 RED: actual `{'CHOWN'}`, expected `{'CHOWN', 'DAC_OVERRIDE'}`
  - `docker-compose.pilot.yml`의 `caddy-volume-init.cap_add`에 `DAC_OVERRIDE` 한 개만 추가했다.
  - focused GREEN: `1 passed`
  - AWS pilot/deployment readiness/CodeBuild contract: `131 passed`
  - 최소 capability 운영 증명 SSM command: `6384c75a-0ffb-4ac7-973a-7761cb87f92f`
    - `cap_drop: ALL`, `cap_add: CHOWN, DAC_OVERRIDE`, 실제 Caddy volume read-only 조건
    - data/config/log 세 경로 재귀 탐색: 모두 성공
    - `minimal_capability_proof=pass`
- release 경계:
  - normal promotion은 기존 staged release의 Compose를 새 로컬 bundle로 덮어쓰지 않는다.
  - 따라서 수정은 새 immutable release로 병합·빌드·stage한 뒤 재검증해야 하며, 기존 `d8de5915f463`의 blind retry는 금지한다.

### S9 — strict Supervisor smoke의 만료된 acceptance fixture 판정

- 대상 release: `908e844fd6fa`
- public cutover SSM command: `94f21b37-3c54-424a-b3e8-774f18f1f775`
- 트랜잭션 결과: strict Supervisor gate 실패 후 rollback, public current link 없음
- cutover 중 통과한 항목:
  - release-bound 법령 evidence와 production readiness
  - IMDS allow/deny 및 object-storage smoke
  - Google OAuth 실제 code 교환과 replay 거부
  - production Redis, ClamAV, Neo4j, backend, frontend, Caddy health
  - 비동기 worker queue/consume 및 실제 LLM 사용
- strict 실패 항목:
  - `job_success=false`
  - `all_agent_results_success=false`
  - `real_agent_results=false`
  - `persisted_handoff_consumed=false`
  - `report_ready=false`
- DB 계약 증거:
  - job `job_d6c8df8da85a`, work item `awork_job_d6c8df8da85a`
  - work item 자체는 `success`, job은 `partial`
  - `fine_notice_analysis` 및 `law_ground_search`는 `success`
  - `appeal_decision_flow` 및 `agent_result_validation`은 `partial`
  - report row 없음, display result 존재, provider/agent error code 없음
- 확정 원인:
  - 사용 fixture `pilot-fine-notice-prior-notice.pdf`의 OCR 결과는 `notice_stage=사전통지`, `opinion_deadline=2025-02-07`이었다.
  - 2026-08-02 기준 기한 경과로 `deadline_passed=true`, `judgment_status=denied`가 정상 산출됐다.
  - handoff는 `required_result_partial`로 `draft`가 되었고 report node는 실행되지 않았다.
  - 따라서 infrastructure, provider, worker, RAG, Caddy 실패가 아니라 만료된 acceptance artifact가 strict report 경로를 충족하지 못한 것이다.
- 보존 원칙:
  - partial/denied를 성공으로 완화하지 않는다.
  - PDF와 다른 미래 날짜를 smoke 입력에 주입하지 않는다.
  - 새 PII-free, test-only, 미래 기한 사전통지 PDF를 새 immutable key로 검토·게시한다.
  - 앞선 paid provider smoke 1회는 이미 소비됐으며 추가 실행은 별도 승인 대상이다.

### S10 — 새 synthetic prior-notice fixture 로컬 검증

- 설계: `docs/superpowers/specs/2026-08-02-fresh-supervisor-acceptance-fixture-design.md`
- 구현 계획: `docs/superpowers/plans/2026-08-02-fresh-supervisor-acceptance-fixture.md`
- 로컬 PDF: `output/pdf/pilot-fine-notice-prior-notice-valid-through-20260831-v1.pdf`
- 로컬 preview: `output/pdf/pilot-fine-notice-prior-notice-valid-through-20260831-v1.png`
- SHA-256: `8b73612a4cf513ccce69cadd0701b2ede85171589d69c6d354ec6414a549d3cd`
- byte size: `5,618`
- page count: `1`
- 자동 검증:
  - TDD RED: 모듈 부재 및 빈 계약에서 예상 실패 확인
  - focused fixture contract: `5 passed`
  - synthetic fixture + 새 fixture: `7 passed`
  - Django chatbot PDF 인접 회귀: `40 tests`, `OK`
  - Ruff 및 `git diff --check`: 통과
  - `pypdf`: A4 1페이지, AcroForm/annotation/names tree/open action 없음
  - raw PDF: JavaScript/embedded-file/file-link token 없음
  - `pdfplumber`: 안전 표시 3개, 필드 라벨 14개, 필드 값 14개 exact match
  - generated PDF/PNG: 정확한 `.gitignore` 규칙으로 Git 제외 확인
- 육안 검증:
  - 1191 x 1684 portrait PNG에서 한글 글리프 모두 판독 가능
  - 표, 배너, 푸터, 마진의 clipping/overlap 없음
  - `테스트 전용 문서`, `실제 효력 없음`, `개인정보 없는 운영 검증용 fixture`가 명확함
  - 실제 기관 로고, 직인, 서명란, barcode, 계좌/납부 정보, 실제 PII 없음
- 승인 후보 S3 key:
  - `s3://skn27-pilot-908708651753-clean/canonical/acceptance/pilot-fine-notice-prior-notice-valid-through-20260831-v1.pdf`
- 현재 게이트:
  - 운영자가 SHA-256 `8b73612a4cf513ccce69cadd0701b2ede85171589d69c6d354ec6414a549d3cd`의 게시를 명시 승인했다.
  - publish preflight에서 AWS account `908708651753`, local SHA/size, destination key 미존재를 확인했다.
  - 새 immutable key에 1회 게시하고 다음을 read-back 검증했다.
    - VersionId: `p8Gfro4G268nYpoZ.9NHzu74D6GPVqCS`
    - ETag: `"0970d18aa0050e5d70a7f2a97dd5e93e"`
    - Content-Type: `application/pdf`
    - server-side encryption: `AES256`
    - content length: `5,618`
    - remote SHA-256: `8b73612a4cf513ccce69cadd0701b2ede85171589d69c6d354ec6414a549d3cd`
    - local/remote exact match: `true`
  - 원격 byte read-back용 임시 파일은 exact match 확인 후 제거했다.
  - Google code는 아직 발급·저장하지 않았다.
  - 추가 paid Supervisor/provider smoke는 별도 명시 승인 전에는 실행하지 않는다.
