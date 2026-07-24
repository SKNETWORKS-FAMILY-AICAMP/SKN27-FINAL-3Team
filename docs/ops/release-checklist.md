# 운영 배포 체크리스트

| 항목 | 내용 |
|---|---|
| 기준 이슈 | `#43 chore-final-stabilization-and-release-readiness` |
| 적용 범위 | 표준 운영형 배포 준비 |
| 승인 원칙 | 문제가 발생했을 때 탐지, 피해 제한, 복구, 추적이 가능해야 한다. |

## 1. 배포 전 P0 확인

- [ ] 운영 책임자와 대체 담당자가 지정되어 있다.
- [ ] 배포 대상 브랜치, commit, tag를 식별할 수 있다.
- [ ] 비밀정보가 코드와 클라이언트에 포함되어 있지 않다.
- [ ] 사용자 인증과 서버 측 권한 검사 기준이 문서화되어 있다.
- [ ] 개인정보 수집, 보관, 삭제, 마스킹 기준이 문서화되어 있다.
- [ ] 백업 대상과 복구 절차가 문서화되어 있다.
- [x] 롤백 절차가 문서화되어 있다. — `docs/ops/rollback-plan.md`, `deploy/aws-pilot/Rollback-Pilot.ps1`

## 2. 배포 전 P1 확인

- [x] 자동 테스트가 통과했다. — `feat-runpod-serverless-vision` 기준 전체 `test/` 회귀 `960 passed, 38 skipped`, Django 전체 `368 passed`, RunPod 집중 회귀 `186 passed`, 배포·AWS pilot `80 passed`, Ruff·Compose·RunPod Dockerfile build check·Vite production build 통과
- [x] 정적 HTML 산출물이 UTF-8로 저장되어 있다. — `test_static_mvp_html_is_utf8_korean_service_screen` 및 PR #300 Vite production build 확인
- [x] 운영 문서가 `docs/ops/`에 존재한다.
- [~] 장애 대응 절차가 문서화되어 있다. — `operational-observability-runbook.md`에 queue·lease·Worker/provider·법령 데이터 알람별 확인·완화·복구를 연결; 실제 AWS ALARM/OK 훈련은 남음
- [~] 외부 API 장애 시 사용자 안내와 timeout 기준이 문서화되어 있다. — RunPod Serverless의 execution failed·cancelled·timeout·unavailable·invalid response 안전 코드, bounded polling, 중복 유료 제출 방지와 운영자 조치를 `vision-media-adapter-runbook.md`에 연결. 실제 restricted key·Endpoint·모델·비식별 실영상 확인은 사람 게이트
- [~] RunPod Vision 운영 설정이 준비되어 있다. — local/production/AWS pilot 환경 템플릿과 Compose 전달 계약, `workersMin=0`·`workersMax=1` 초기 비용 상한을 구현. private runtime에 실제 값을 입력하고 Endpoint smoke를 완료해야 운영 활성화 가능
- [ ] 과도한 요청과 비용 증가를 제한하는 계획이 있다.
- [~] 법령 데이터 최신성 게이트가 자동화되어 있다. — source별 run summary와 stale·missing·failed 차단 CLI·runbook은 PR #301로 `dev` 병합 완료(`8cc2fc8`); `feat-299-operational-observability`에서 read-only 운영 evidence·CloudWatch `LegalDataIssueCount` alarm을 연결. 운영 DB·실제 ALARM/OK 실증은 남음
- [~] 분석 결과의 실행 버전을 운영자가 조회할 수 있다. — model·prompt version/hash, Agent runtime·adapter·release version, embedding model, 검색 dataset version·시각을 `job_id`로 조회하는 command와 runbook 구현; 운영 release metadata 주입과 실제 DB smoke는 남음

## 3. 배포 승인 기록

| 항목 | 기록 |
|---|---|
| 배포 요청자 | 확인 필요 |
| 검토자 | 확인 필요 |
| 승인자 | 확인 필요 |
| 배포 commit | 확인 필요 |
| 배포 시간 | 확인 필요 |
| 롤백 기준 버전 | 확인 필요 |

## 4. 배포 후 smoke 점검

- [ ] 진입 화면이 열린다. — 2026-07-23 로컬 데스크톱 브라우저 사전 스모크 통과, 운영 배포 후 재확인 필요
- [ ] 챗봇 화면 영역이 표시된다. — 로컬에서 예시 선택·질문 전송·응답 표시 확인, 운영 배포 후 재확인 필요
- [ ] 과태료·범칙금 결과 영역이 표시된다.
- [ ] 과실비율 결과 영역이 표시된다.
- [ ] 마이페이지 또는 내 사건 영역이 표시된다.
- [ ] 오류가 사용자에게 내부 stack trace로 노출되지 않는다. — 로컬에서 안전한 한계·다음 행동 안내 확인, 운영 배포 후 재확인 필요
