# Release Readiness Integration Verification

검증일: 2026-07-23
대상 브랜치: `feat-release-readiness-integration`
기준: `origin/dev`의 PR #293 병합 커밋 `d326ae8`
후속 검증: PR #300 병합 커밋 `3fd0fcdddbc2b8e30e7993dbcfe6376535bec68a`

## 결론

PR #296의 승인된 홈·상담·마이페이지·리포팅 UI 방향을 최신 `dev`에 통합했고,
첨부·기한·스트리밍·pgvector readiness 회귀를 수정했다. 미병합 #279 대표 사용자
흐름을 함께 통합하면서 최신 안전 게이트에 맞지 않던 E2E fixture를 수정했다.

추가 점검에서 UI가 노출하던 사고 현장 사진이 1차 문서 분류 뒤 멈추는 공백을
확인했다. 사용자는 서버에 저장된 분류를 `attachment_id`로만 확인할 수 있고,
확인된 사고 사진은 영상 Vision 경로가 아닌 사진 전용 사례·법령 검색 계획으로
이어지도록 보완했다. 오래되거나 없는 분류는 `409`로 닫힌다.

현재 릴리스 후보는 코드·정적 배포 자동화 관점에서 준비되었다. 실제 비밀값,
운영 계정, 유료 재임베딩, 운영 데이터와 장치가 필요한 live 검증, 최종 트래픽
전환은 아래 사람 실행 게이트로 남긴다.

후속 브라우저 QA에서 UI 병합 회귀로 발생한 흰 화면, 첫 화면 아래로 밀린 입력창,
과태료 질문의 잘못된 라우팅과 검증 근거 부재 시 무의미한 응답을 수정했다.
PR #300은 병합 전 CI를 사용자가 확인한 뒤 `dev`에 병합되었다.

## 통합 내용

- PR #296 전체 UI 방향 유지
  - 회전형 홈, 다크 테마, 새 상담·마이페이지·리포팅 화면
  - 키보드 포커스, reduced motion, 반응형 스타일 계약
- 첨부 회귀 수정
  - 정의되지 않은 첨부 옵션과 자식 컴포넌트의 직접 상태 변경 제거
  - MIME·용도·영상 handoff·drag-and-drop 경계 복원
- 마이페이지·리포팅 안전성
  - 사용자 확인 날짜만 기한 계산에 사용
  - 서버가 요구한 공식 문서 확인 게이트 유지
- PR #293 pgvector readiness 보강
  - 심의사례 count/index/readiness에 embedding provider 조건 추가
  - Docker와 AWS pilot 기본 임베딩 공간을
    `openai/text-embedding-3-large/1024`로 통일
- #279 대표 사용자 흐름
  - 세션 → 업로드 → 스캔 → Supervisor → Worker → 공개 분석 결과
    → 리포트 확인 → DOCX 다운로드
  - 확인 사실과 사용자 주장을 별도 공개 DTO로 투영
  - 부분 법령 결과에서는 보고서를 생성하지 않고 한계와 다음 행동을 유지
  - 타 사용자 결과·리포트·DOCX 접근 차단
- 사고 사진 분류 확인
  - 클라이언트는 분류값을 제출하지 않고 `attachment_id`만 확인
  - 서버의 현재 scan snapshot에 결합된 분류만 다음 계획의 권한으로 사용
  - 사진은 `text_ml_case_search`·`law_ground_search`로, 영상은 기존
    `vision_media_analysis` 경로로 분리

## 실행 증거

### 프런트엔드

- `npm --prefix app\web run build -- --configLoader runner`
  - 32 modules transformed
  - CSS 84.49 kB, JS 293.77 kB
  - 성공
- 사고 사진 확인 UI 추가 후 별도 outDir build
  - 32 modules transformed
  - CSS 84.49 kB, JS 297.02 kB
  - 성공
- UI·라우팅·Agent·OpenAPI 집중 회귀
  - `99 passed in 12.24s`
- 결과 안전 표시
  - #279의 `user_claims`를 확인 사실과 별도 패널로 표시
  - 역질문 항목별 필요한 이유 표시
  - 법령 시행 기준일·검색 적용 기준일·조회 시각 표시
- PR #300 실제 브라우저 QA와 런타임 보강
  - 데스크톱 로컬 브라우저에서 초기 화면, 입력창, 예시 질문 선택, 질문 전송,
    응답 표시를 사용자 화면으로 확인
  - 정의되지 않은 빠른 질문 변수로 인한 흰 화면 제거
  - 입력 composer를 첫 화면 안에 배치
  - 어린이보호구역 과태료 질문을 `fine_notice_procedure`로 라우팅
  - 검증된 법령 검색 결과가 없을 때 단정하지 않고 기관·기한·상황 기록·
    응급 증빙·다음 행동을 안내하는 안전한 fallback 적용
  - 집중 회귀 `48 passed`, Ruff 통과, Vite production build
    `32 modules transformed` 성공

### Python·Django

- PR #296·배포 집중 회귀: `146 passed in 11.57s`
- 수집 가능한 전체 Python 회귀:
  - `964 passed`, `38 skipped in 83.61s`
  - JUnit: `D:\dev\project\SKN27-FINAL-3Team\.pytest-release-integration-final3.xml`
- 통합 worktree 자체 최종 Python 회귀:
  - `877 passed`, `38 skipped in 79.48s`
  - JUnit: `D:\dev\project\SKN27-FINAL-3Team\.pytest-release-integration-final8.xml`
- 배포·AWS pilot·OpenAPI·UI 계약: `98 passed in 6.91s`
- Django 보존·큐·채팅 계약·대표 사용자 흐름: `55 tests`, 성공
- 사고 사진 분류 확인 + #279 대표 흐름: `5 tests`, 성공
- Django 전체 앱 회귀: `357 tests`, 성공
- 게스트 로그인·세션 소유권 E2E: 격리된 임시 object/upload 저장소에서
  `3 tests in 1.458s`, 성공
- `backend\manage.py check`: 문제 없음
- OpenAPI 생성물 check: 최신
- 변경 Python Ruff: 통과
- `git diff --check`: 통과

### 배포 자동화

- `docker-compose config --quiet`: 구성 유효
- AWS pilot 정적 회귀에서 다음을 확인
  - immutable image digest와 deployment manifest
  - 8 GiB host capacity preflight와 bounded logs
  - SSM bounded polling·timeout·cancel
  - 현재/rollback 동시 실행 잠금
  - 실패 배포 자동 복구와 이전 release 재기동
  - 현재 SSM secret 재조회 후 rollback
- 배포 전 체크리스트: `docs/ops/release-checklist.md`
- 롤백 절차: `docs/ops/rollback-plan.md`,
  `deploy/aws-pilot/Rollback-Pilot.ps1`

## 환경상 실행하지 못한 항목

- 인앱 브라우저 자동 제어는 이 세션의 `127.0.0.1`을 정책상 거부했다.
  대신 사용자가 같은 로컬 앱을 직접 조작하고 화면을 공유해 데스크톱 상담
  기본 흐름을 검증했다. 모바일·첨부 분류/OCR·리포트 다운로드의 실제 브라우저
  스모크는 아직 남아 있다.
- 현재 로컬 Python 3.14에는 `pyarrow`가 없어
  `etl/fault_cases/rag_runtime`의 3개 모듈을 수집할 수 없다.
  Python 3.13 CI에서 최종 수집·실행해야 한다.
- 실제 AWS, OpenAI, Google, 운영 PostgreSQL/Neo4j, Vision checkpoint 없이
  live/유료/provider 품질을 성공으로 주장하지 않는다.

## 사람 실행 게이트

다음 항목은 값 발급·비용·운영 소유권·실데이터 변경 또는 최종 승인 권한이
필요하므로 운영 담당자가 실행한다.

1. 운영 비밀값 입력
   - Django secret, allowed hosts
   - PostgreSQL/Redis
   - Google OAuth client/secret/redirect
   - APP JWT·OAuth state secret
   - OpenAI와 법령 수집 API
   - S3·scanner·Vision checkpoint
2. AWS 계정·결제·도메인·DNS·OAuth 운영 소유권 승인
3. 운영 DB backup 후 법령·심의사례를
   `openai/text-embedding-3-large/1024`로 적재·재임베딩
4. 운영 DB readiness, 대표 검색 latency, 법령 seed와 rollback 결과 확인
5. 실제 OCR golden set, Vision 원본 영상, 검색 평가 세트의 품질 승인
6. 모바일과 실제 파일로 첨부 → 분류/OCR 확인 → 결과 → 리포트 다운로드
   브라우저 스모크. 데스크톱 텍스트 상담의 진입 → 예시 선택 → 전송 → 응답은
   PR #300에서 확인 완료
7. 운영 트래픽 전환, CloudWatch 알림 확인, 사후 모니터링과 사업 승인

## 파일럿 범위 밖 후속 항목

다음은 현재 공개 파일럿의 안전한 범위에서 제외하며, 운영 배포를 막는 기능으로
노출하지 않는다.

- 사고 유형·사실·주장을 별도 폼으로 받는 고급 구조화 입력 UI
- 장기 대화 자동 압축과 정보 소실 품질 평가
- 사용자 직접 분석 작업 취소 API
- 실제 동시 부하·비용·CloudWatch 임계값 튜닝
- OCR·Vision·검색의 대규모 golden set 품질 고도화

이 항목들은 서비스 범위 표시를 유지한 상태에서 별도 P1 이슈로 관리한다.

### GitHub 후속 이슈

1. #298 `[P1] 구조화 사건 입력과 장기 대화 메모리 고도화`
   - 구조화 입력 UI, 서버 우선 사건 상태, 장기 대화 압축 시
     사실·주장·출처·미확인·기한 보존, 모바일·접근성 검증
2. #299 `[P1] 운영 데이터 최신성·관측·재현성 증적 보강`
   - source별 재색인 run summary, 큐·외부 장애 관측,
     모델·프롬프트·Agent·검색 데이터 버전, CloudWatch 임계값
   - PR #301에서 법령 source별 `legal_ingestion_run_summary.v2`,
     결정적 data version, stale·missing·failed 검증 CLI와 운영 runbook을
     첫 독립 단계로 `dev` 병합 완료(`8cc2fc8`)
   - 후속 브랜치 `feat-299-execution-provenance`에서 모델·프롬프트·Agent·
     검색 데이터 버전과 실행별 운영 조회 증적을 구현
   - Supervisor model·prompt version/hash, Agent runtime·adapter·release
     version, 검색 embedding model과 dataset version·검증/기준/조회 시각을
     기존 JSON metadata 경계에 저장
   - `show_analysis_job_provenance --job-id <JOB_ID> --format json`으로
     원문 query·OCR 전문·비밀값 없이 조회
   - 로컬 검증: 전체 `test/` 회귀 `897 passed, 38 skipped`, Django
     Worker/DB·operator 조회 통합 `40 passed`, Ruff 통과
   - 운영 release metadata 주입, 운영 DB smoke, 실제 외부 공급자
     성공·부분 실패·실패 trace와 CloudWatch 연결은 남음
