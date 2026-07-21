# 서비스 설계 문서 및 로컬 개발 설정 정합성 보완 설계

## 목적

PR #259가 추가한 서비스 설계 문서와 로컬 개발 실행 스크립트를, PR #260에서 확정된 DOCX 전용 다운로드 및 signed guest credential 경계에 맞춘다. 이 작업은 동작을 새로 설계하거나 UI를 개편하지 않고, 문서·개발 스크립트·최소 회귀 테스트의 불일치만 제거한다.

## 범위와 제외 범위

변경 대상은 다음으로 한정한다.

- `docs/service-design-spec-2026-07-21.md`
- `dev-local.ps1`
- 설계 문서·개발 스크립트·기존 프런트 빌드 단계를 고정하는 최소 Python 정적 계약 테스트
- 필요한 경우 `docs/ops/project-readiness-master-checklist.md`의 #258 완료 표기

다음은 변경하지 않는다.

- 리포트 다운로드 API, DOCX 렌더러, 프런트 리포팅 동작
- guest credential 발급·검증, Django middleware, OAuth·App JWT 코드
- UI 구조·스타일·이미지·사용자 흐름·더미 데이터 모드
- Docker, 배포, DB 스키마, 런타임 서비스 구성, CI workflow의 중복 빌드 단계
- 이미 병합된 `ReportActionAlert` JSX 수정

## A. 다운로드 정책 문서화

`서비스 설계서`의 리포트 액션 설명을 다음 정책으로 통일한다.

- 일반 분석 리포트, 교통사고 문서, 과태료 이의신청서에서 제공하는 다운로드 문서는 DOCX 전용이다.
- UI가 PDF 저장 또는 PDF 이의신청서 다운로드를 제공하는 것처럼 읽히는 표현을 제거한다.
- 문서는 실제 다운로드 가능 여부와 제출 전 확인 게이트를 설명할 수 있지만, API·UI 동작을 새로 약속하거나 변경하지 않는다.

## B. guest 인증 문서화

인증 및 세션 모델의 guest 설명을 다음 서버 검증 경계로 갱신한다.

- `X-Guest-Credential`은 서명된 guest credential이며, 보호된 guest 경로는 이를 header로 전달해 서버 검증을 통과해야 한다.
- `X-Guest-Id`는 선택적 식별 보조값이다. credential 없이 단독으로는 권한 증명이 아니며, 전달됐을 때는 검증된 credential claim과 일치해야 한다.
- guest credential은 request body, query string, `auth_context`에 넣지 않는다. 요청 header로만 전달한다.
- App JWT는 로그인 사용자의 권한을, guest credential은 비회원 guest 세션의 권한을 증명한다. 어느 하나를 다른 하나의 대체 수단으로 사용하지 않는다.
- 이 문서 작업은 현재 인증 구현을 다시 수정하지 않는다.

## C. `dev-local.ps1` DB 엔진 보존

SQLite는 로컬 개발의 기본값으로만 사용한다.

1. 스크립트 시작 시 `DJANGO_DATABASE_ENGINE`이 null·빈 문자열·공백뿐인 경우에만 `sqlite`를 설정한다.
2. 값이 `postgres` 등으로 명시돼 있으면 변경하지 않는다.
3. `Start-Dev`가 만드는 각 PowerShell 창은 이미 확정된 부모 환경값을 상속한다. 자식 명령 문자열에서 SQLite를 다시 강제 설정하지 않는다.

이 방식은 Docker·배포·DB 스키마·런타임 서비스 설정을 바꾸지 않는다.

## D. 재발 방지 테스트

새로운 단일 정적 계약 테스트 파일에서 다음을 검증한다.

- 서비스 설계서가 DOCX 전용과 guest credential header 경계를 명시하고, 금지된 PDF UI 표현을 포함하지 않는다.
- `dev-local.ps1`이 공백인 환경값에만 SQLite를 기본값으로 넣고, 자식 프로세스 명령에서 DB 엔진을 덮어쓰지 않는다.
- 기존 `production-gate.yml`에 `app/web`의 `npm ci`와 `npm run build`가 포함돼 있다.

검증은 `app/web`의 실제 `npm run build`, 새 정적 테스트, 기존 DOCX·guest credential 계약 테스트, 전체 Python 회귀 테스트를 실행한다.

## E. 체크리스트

현재 `dev`에서 #258 항목이 진행 중(`[~]`)이라면, 이 PR 안에서만 `#258 / PR #260` 완료 상태로 갱신한다. 체크리스트만을 위한 별도 PR은 만들지 않는다.

## UI/UX 점검 결과와 후속 분리

PR #259 UI와 PR #260 credential 경계를 함께 점검했다. 실제 로컬 backend와 마이그레이션된 SQLite 환경에서는 홈 CTA → guest session → 상담 화면, 사이드바 접기, 리포팅 DOCX 확인 패널이 연결된다.

다만 다음은 #261의 명시적 제외 범위인 UI 코드 문제이므로 이 작업에서 수정하지 않는다.

- 개발용 `fillAllScreensWithMockData()`가 `sections[].content` 형식을 쓰지만 리포팅 미리보기는 `sections[].items`를 읽어, 더미 리포트 섹션이 비어 보인다.
- 더미 `reportList`에 `report_id`가 없어 `ReportingScreen`에서 React unique key 경고가 발생한다.
- 더미 모드가 실제 App JWT 없이 `authSessionId`를 채워 Google 로그인 상태처럼 보인다.
- 제출 전 확인 문구가 `사실관계을(를)`처럼 조사를 중복 표기한다.

이 항목들은 별도 UI 정합성 이슈로 처리하며, #261의 문서·스크립트·정적 검증 범위를 넓히지 않는다.

## 완료 기준

- 설계 문서가 DOCX 전용과 guest credential 정책을 현재 #260 구현과 동일하게 설명한다.
- `dev-local.ps1`이 명시된 DB 엔진을 보존한다.
- 프런트 프로덕션 빌드와 관련 계약 테스트가 통과한다.
- 변경 범위가 문서, 개발 스크립트, 최소 회귀 테스트, 필요한 체크리스트 갱신으로 제한된다.
