# Caddy credential access-log 사고 대응 Runbook

## 목적과 적용 조건

이 절차는 Caddy access log에 `Authorization`, `Cookie`,
`X-Guest-Credential` 등 요청 인증 헤더가 기록됐거나 기록됐을 가능성을
발견했을 때 사용한다. 현재 Caddy 설정은 `request>headers delete`로 모든
요청 헤더를 access log에서 제거하지만, 수정 전 로그는 별도 사고 범위로
취급한다.

자격증명 교체, 로그 삭제, 보존기간 변경은 모두 **운영 승인**과 변경 창이
필요하다. 로컬 테스트나 문서 검토만으로 실행하지 않는다.

## 1. 즉시 격리와 범위 확인

1. 사고 ID, 발견 시각, 영향 release SHA, dataset version을 기록한다.
2. 원문 로그를 이슈·PR·채팅에 붙이지 않는다. 검색 결과는 일치 건수와
   최초·최종 시각만 기록한다.
3. `skn27-pilot_caddy_logs` Docker volume의 실제 이름과 mount를 다음
   읽기 전용 명령으로 확인한다.

   ```bash
   docker volume inspect skn27-pilot_caddy_logs
   docker compose --project-name skn27-pilot \
     --env-file .compose.env --env-file .production-compose.env \
     -f docker-compose.pilot.yml ps caddy
   ```

4. 다음 복제·보존 경로를 각각 확인하고 “없음”도 증적으로 남긴다.

   - EC2/EBS snapshot과 AMI에 포함된 `caddy_logs` volume 데이터
   - host 또는 Docker volume backup
   - 로그 수집 agent, CloudWatch Logs 전달, 구독 filter와 export
   - 외부 SIEM, S3 archive, cross-account 또는 cross-region replication

5. 인스턴스 SSM 접속 권한, IAM role/사용자, backup·CloudWatch 접근자와
   사고 구간의 CloudTrail을 확인한다. 접근자 식별자와 건수만 남기며
   조회한 실제 header 값은 기록하지 않는다.

## 2. APP_JWT_SECRET 교체

`APP_JWT_SECRET`은 app JWT와 서명된 guest credential 검증에 함께
사용된다. 따라서 교체하면 기존 app token과 기존 guest credential이 모두
무효화되어야 한다.

1. 32자 이상의 새 값을 승인된 비밀 생성기로 만든다.
2. 실제 token 값을 명령행 인자, shell history, SSM command comment 또는
   배포 로그에 넣지 않는다.
3. Terraform output `runtime_env_parameter_name`이 가리키는 SSM
   `SecureString`의 전체 runtime env를 승인된 비밀 입력 경로에서
   갱신한다. `APP_JWT_SECRET`의 실제 값은 로컬 파일, Git diff, 터미널
   캡처에 남기지 않는다.
4. 기존 `Deploy-Pilot.ps1`의 SSM materialization 방식과 동일하게 새
   runtime env를 release에 반영한다.
5. 같은 backend image/runtime env를 쓰는 실행 서비스 `backend`,
   `agent-worker`, `file-scan-worker`, `ops-monitor`를 모두 재생성한다.
   `rag-loader`는 상시 서비스가 아니므로 다음 유지보수 실행이 새 env를
   읽는지 확인한다.
6. 교체 전 별도로 보관한 비식별 검증용 app JWT와 guest credential로
   보호 API를 호출해 각각 HTTP `401`인지 확인한다. 응답 본문과 token은
   증적에 저장하지 않는다.
7. 새 로그인과 새 guest 세션으로 발급된 자격증명이 정상 동작하는지
   최소 smoke를 수행한다.

## 3. 노출 로그 처리

1. 1절 inventory에서 확인한 모든 사본에 동일한 incident retention
   결정을 적용한다. local volume만 삭제하고 backup, replication 또는
   CloudWatch 사본을 남겨서는 안 된다.
2. 법무·보안·감사 담당자가 보존을 요구하면 암호화된 제한 저장소로
   격리하고 접근자를 최소화한다. 분석 결과에는 일치 건수만 남긴다.
3. 삭제 승인을 받은 경우 Caddy를 중지하고
   `skn27-pilot_caddy_logs`의 정확한 Docker volume을 다시 확인한 뒤
   승인된 삭제 작업으로 제거·재생성한다. 이름이 다르거나 mount가
   불명확하면 중단한다.
4. EBS snapshot, AMI, backup, S3 archive, CloudWatch 또는 외부 SIEM의
   사본도 각 시스템의 승인된 삭제·만료 절차로 처리한다.
5. Caddy 재기동 후 `/api/health/live/`와 `/api/health/ready/`를 확인한다.

## 4. credential canary와 zero match 검증

1. 운영 승인 창에서 실제 자격증명과 형태만 비슷한 일회성 비식별
   `credential canary` 세 개를 만든다.
2. 같은 요청에 canary를 각각 `Authorization`, `Cookie`,
   `X-Guest-Credential` header로 보내고 요청 시각과 HTTP status만
   기록한다.
3. `caddy_logs` volume과 1절에서 확인한 모든 전달·backup 대상에서 각
   canary를 검색한다.
4. 세 canary 모두 `zero match`여야 통과다. 하나라도 발견되면 트래픽
   확대와 최종 배포 승인을 중단하고 1절부터 다시 수행한다.
5. 실제 token 값을 증적에 복사하지 않는다. 실제 token 값을 명령행,
   screenshot, CI artifact 또는 채팅에 넣지 않는다.

## 5. 종료 증적

다음 필드만 incident/change record에 남긴다.

- incident ID와 승인자 식별자
- 영향 release SHA와 dataset version
- 발견·회전·서비스 재생성·로그 처리·검증 시각
- 조사한 volume/CloudWatch/backup/replication resource 식별자
- 접근자 수, 검색 대상 수, 일치 건수
- 기존 app JWT `401` 건수와 기존 guest credential `401` 건수
- credential canary별 zero match 결과
- 새 자격증명 smoke의 HTTP status

secret, token, cookie, header 원문, 사용자 식별정보, 요청 본문은 종료
증적에 포함하지 않는다.
