# Pilot 브라우저 수동 E2E 실패·차단 핫픽스 재검증 보고서

## 1. 범위와 현재 결론

- 실행 일자: 2026-08-03~2026-08-04 (KST)
- 대상 URL: `https://skn27-traffic-pilot.duckdns.org/`
- 최종 브라우저 재검증 revision: `e49aa53ed28790c3ea1e474f21f0f1519ff108a2`
- 최종 CodePipeline execution: `11ae78ee-29c0-477f-bb83-f952a520f0af` / `Succeeded`
- 범위: 최초 보고서에서 `FAIL` 또는 `BLOCKED`였던 항목만 재검증
- 개인정보 원문, raw OCR, 토큰, 쿠키, 인증 헤더, private storage URI는 기록하지 않음

| ID | 최초 판정 | 핫픽스 | 현재 판정 | 브라우저 근거 |
|---|---|---|---|---|
| F-01 | J01 법령 상담 오분류·polling 지연 | 현재 입력 우선 재라우팅, semantic polling 보존 | **RESOLVED** | 일반 법령 질문과 사고 상담 뒤 법령 전환 모두 PASS |
| F-02 | J02 첨부 가능 문장 반복 질문 | 실제 자연어 alias 추가 | **RESOLVED** | 최초 실패 문장 그대로 네 슬롯 충족, 반복 질문 없음 |
| F-03 | PDF·JPG 분류 확인 카드 누락 | 공개 결과 allowlist와 확인 workflow 연결 | **RESOLVED** | PDF 2종·JPG에서 분류 카드, 확인, OCR/Vision 전진 PASS |
| F-04 | 사실확인원 PNG 분류 대기 고정·OCR 실패 | 전용 OCR workflow와 공개 결과 연결, 모델 파라미터 수정 | **RESOLVED** | PNG가 일반 분류를 우회하고 OCR 3/3 및 허용 필드 표시 |
| F-05 | J08 인증·상담 reload 미복원 | 저장 tuple read-back, transient 복구, resume manifest 보강 | **RETEST REQUIRED** | 인증·사용자 메시지 복원은 PASS. 실제 등록 첨부 없이 reload해 첨부·report 복원은 미검증이며, raw worker 문구 노출은 별도 FAIL |
| B-01 | persisted report·이의신청서 차단 | 확인된 분류·OCR 사실·report 재연결, polling 연장 | **INVALID RETEST** | 파일 선택 뒤 `첨부` 등록 버튼을 누르지 않아 OCR·report 선행 계약 자체가 실행되지 않음 |

현재 코드·CI·운영 배포는 여섯 항목의 수정분과 PR #394·#395를 포함한다.
인증된 외부 Chrome 재시험은 파일 선택과 서버 첨부 등록을 혼동해 F-05와
B-01의 완료 조건을 실행하지 못했다. 따라서 두 항목을 제품 `FAIL`로 확정할
수 없으며, 실제 `첨부` 등록 뒤 정상 순서로 다시 검증해야 한다.

## 2. 배포 및 자료 무결성

### 2.1 선행 운영 배포 (#388 기준)

| 검증 항목 | 결과 |
|---|---|
| CodePipeline execution | `22cbbfd3-4ae6-496a-879c-389e9ca6a3c7` / `Succeeded` |
| Source revision | `359b52c1f495ad916786e152d2a0288e6727d97e` |
| Build execution | `skn27-pilot-build:92d65533-f790-4a25-ba8b-2a32a80e69c2` / `Succeeded` |
| Deploy execution | `skn27-pilot-pilot-app-release:aca6b394-5751-4bbb-abf6-2ae50058a6e9` / `Succeeded` |
| `/api/health/` | `ok=true`, service `skn27-api` |
| `/api/health/ready/` | database `ready`, cache `ready` |
| backend/frontend image | 모두 `359b52c1f495` |
| agent/file-scan worker, ops-monitor image | 모두 backend `359b52c1f495` |
| operational evidence release | `359b52c1f495` |
| legal evidence sources | 35개 source 모두 `success` |

SSM 검증은 실행 컨테이너의 image reference, `.compose.env`의 release tag와
비식별 운영 증거 상태만 출력했다. 계정·세션·토큰 값은 조회하거나 기록하지
않았다.

PR #395 최종 배포와 브라우저 판정은 이 보고서의 12절을 최신 기준으로 삼는다.

### 2.2 입력 파일 식별값

| 파일 | SHA-256 | 재검증 여정 |
|---|---|---|
| `form2_별지154_위반사실통지및과태료사전통지서.pdf` | `E10856495BE492276194D0B187A8C090C5C3F935FF24403B3179207B738B8F49` | J03 |
| `form3_별지152_과태료납부고지서원부_운전자.pdf` | `C8B9721719E14D46733A32E07099515F94EA824E0464D7F039D12DCDA547FC6B` | J04 |
| `15-07-18-.jpg` | `91DC04770F8BFA48544788C0EC0D2AB972B19D6122E3C9E37596CC00A0623D83` | J06 JPG |
| `22-11-18-_.png` | `E2CC01C0D67410AF5C3A93BA6786DF272EAE14D3CDF3672D48110619F05FAB6B` | J06 PNG |

원본은 테스트 입력으로만 사용했고 저장소에 복사하지 않았다.

## 3. 핫픽스 묶음과 검증 게이트

| PR | Merge SHA | 해결 범위 | 원격 게이트 |
|---|---|---|---|
| [#384](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/pull/384) | `30022acbdec30e8692aa599066a89e5b836c54e8` | F-01~F-04, F-05 관측·복구 기반 | production-gate·regression-signal PASS |
| [#385](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/pull/385) | `cb8aab2797c15951d667f4ab91d5f705676fd95c` | 인증 verification outage 중 동작 복구 | production-gate·regression-signal PASS |
| [#386](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/pull/386) | `dd6056fe8b2be8352c5ae163c5a65f20fefd9db5` | 운영 OCR 모델의 token 파라미터 호환 | production-gate·regression-signal PASS |
| [#387](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/pull/387) | `fcf9500459021cc4d0483dd94893b8e9522fa990` | 분류 확인 상태의 다음 턴 연속성 | production-gate·regression-signal PASS |
| [#388](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/pull/388) | `359b52c1f495ad916786e152d2a0288e6727d97e` | 429·404·인증 응답의 깨진 한글 복원과 재발 방지 | production-gate·regression-signal PASS |
| [#394](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/pull/394) | `a507c9050a0577c63c712389fdad060d9627927f` | 확인된 OCR·사용자 사실의 후속 분석 전달 | production-gate·regression-signal PASS |
| [#395](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/pull/395) | `e49aa53ed28790c3ea1e474f21f0f1519ff108a2` | 완료 report·첨부 reload 복원, 90초 polling, 법령 근거 경계 | production-gate·regression-signal PASS |

최종 핫픽스 로컬 검증:

- `python -m pytest -q`: 1,614 passed, 37 skipped, 4 subtests passed
- `python backend/manage.py test chatbot --verbosity 1`: 400 passed
- `python backend/manage.py test chatbot.test_file_quarantine --verbosity 0`: 36 passed
- `node --test *.test.js`: 146 passed
- `npm run build`: production build 성공

PR #395 추가 로컬 검증:

- `python -m pytest -q`: 1,621 passed, 37 skipped, 4 subtests passed
- `python backend/manage.py test chatbot -v 1`: 408 passed
- frontend Node test: 151 passed
- `npm --prefix app/web run build`: production build 성공
- `git diff --check`, Ruff 검사: PASS

## 4. F-01 — J01 일반 법령 상담

### 최초 원인

이전 사고 follow-up intent가 현재 입력보다 우선될 수 있었고, 프런트 polling이
semantic terminal 결과를 보존하지 못하는 경로가 있었다.

### 수정

- `backend/chatbot/views.py`: 저장된 follow-up과 현재 입력 route를 함께 계산
- `app/services/chat_session_followup_service.py`: 현재 입력이 명확히 전환되면
  과거 domain intent를 고정하지 않음
- `app/services/chat_orchestration_service.py`: 현재 content route 우선 규칙 보강
- `app/web/workerPolling.js`: 마지막 semantic 상태와 안전한 terminal 결과 보존

### 브라우저 재검증

1. 횡단보도·보행자 표현이 포함된 일반 법령 질문이 사고 intake로 전환되지
   않고 법령 근거·한계 답변으로 완료됐다.
2. 같은 상담에서 사고 문맥 뒤 일반 법령 질문으로 전환해도 현재 질문 route가
   적용됐다.
3. polling 지연 문구 대신 terminal 답변을 받았다.

판정: **RESOLVED**.

## 5. F-02 — J02 첨부 가능 문장 반복 질문

### 수정

`app/config/supervisor_input_normalization_policy.v1.json`에 브라우저 실패 문장과
동일 계열인 `고지서 첨부가 가능합니다` 표현을 추가하고 정확한 회귀 테스트를
작성했다.

### 브라우저 재검증

다음 문장을 한 번에 입력했다.

`과태료 사전통지서이고 서울시에서 발급했으며 의견제출 기한은 2026-08-12입니다. 고지서 첨부가 가능합니다.`

문서 종류·기관·기한·첨부 가능 네 슬롯이 모두 유지됐고 첨부 가능 여부를 다시
묻지 않았다. 판정: **RESOLVED**.

## 6. F-03 — PDF·JPG 분류 확인 카드

### 수정

- `app/services/analysis_job_query_service.py`: 분류·OCR/Vision 공개 결과를
  allowlist로 투영하되 private storage와 raw 결과는 제외
- `app/services/attachment_workflow_service.py`: 공개 workflow와 확인 대상 연결
- `app/web/FrontendAppShell.jsx`: 확인 카드와 다음 분석 단계의 동일 계약 사용

### 브라우저 재검증

| 입력 | 실제 결과 | 판정 |
|---|---|---|
| J03 사전통지서 PDF | 분류 카드 → 사용자 확인 → OCR 확인 카드, 단계 `사전통지` | PASS |
| J04 납부고지서 PDF | 분류 카드 → 사용자 확인 → OCR 확인 카드, 단계 `1차 고지서` | PASS |
| J06 사고 JPG | `사고 현장·증거 사진` 분류 → 사용자 확인 → Vision partial 안전 결과 | PASS |

세 입력 모두 분류 확인 전 후속 분석이 실행되지 않았고, 확인 뒤에만 다음
단계로 전진했다. 판정: **RESOLVED**.

## 7. F-04 — 사실확인원 PNG 전용 OCR

### 추가로 확정된 운영 원인

workflow 수정 뒤 전용 OCR 자체가 실패해 운영 agent 결과를 비식별 집계로
확인했다. provider는 현재 모델에서 `max_tokens`를 거부하고
`max_completion_tokens`를 요구했다. 운영 모델과 같은 설정의 sanitized probe도
동일 400을 재현했다.

### 수정

- `app/services/attachment_workflow_service.py`: `traffic_accident_confirmation_ocr`
  목적은 일반 분류 대기를 우회하고 전용 OCR 상태를 사용
- `etl/fault_cases/src/OCR/traffic_accident_confirmation_ocr/agent.py`:
  `max_completion_tokens=1600` 사용
- `test/test_traffic_accident_ocr_runtime.py`: provider 요청 인자 회귀 검사

### 브라우저 재검증

PNG는 일반 분류 카드 없이 전용 OCR로 진행했고 `검증 점수: 3/3`을 표시했다.
공개 허용 필드로 사고 일시, 지역, 사고 유형, 원인과 사고 개요가 표시됐으며
이름·주소·식별번호·전화번호·차량번호 원문은 노출되지 않았다.

판정: **RESOLVED**.

## 8. F-05 — J08 인증·상담 reload 복원

### 수정

- `app/web/authSession.js`: 저장 직후 민감값 없는 tuple read-back, 불완전 저장
  탐지, 명시적 401/403에서만 인증 제거
- `app/web/FrontendAppShell.jsx`: 일시적 `/auth/me/` 실패에서 인증·상담 문맥을
  보존하고 verification outage 상태에서 안전한 동작 허용
- `app/web/authSession.test.js`: 저장·read-back·refresh·transient failure·명시적
  인증 거부 회귀 테스트

### 브라우저 재검증 정정

1. 외부 Chrome Google 인증과 `로그아웃`, 빈 상담의 `로그인 상담 중`은 PASS.
2. 동일 탭 reload 뒤 인증과 사용자 메시지는 복원됐다.
3. 파일 선택 뒤 별도 `첨부` 버튼을 누르지 않아 서버 등록 첨부가 존재하지
   않았다. 이 상태의 reload 첨부 소실은 resume 결함의 증거가 아니다.
4. 의미 있는 최신 AI 답변 대신 `Agent worker item completed.` 또는
   `Agent worker item completed with partial results.`가 노출됐다.
5. 저장 사건과 persisted report는 0건이었지만, 미등록 첨부로 실행한 job이므로
   report 복원 판정에는 사용할 수 없다.

현재 판정: **RETEST REQUIRED**. 인증·사용자 메시지는 PASS, raw worker 문구
노출은 FAIL이다. 실제 등록 첨부·완료 report의 reload 복원은 미검증이다.

## 9. B-01 — persisted report·이의신청서 연속성

### 재시험에서 추가로 발견한 직접 원인

J03 분류와 OCR은 각각 확인됐지만 다음 요청에서 서버가 canonical attachment를
재구성할 때 이미 확인된 분류 record를 다시 붙이지 않았다. 프런트가 OCR 확인만
보내면 서버는 분류 미확인으로 판단했고 다음과 같이 무한 왕복했다.

`분류 확인 → OCR 확인 → 분류 확인 → OCR 확인`

### 수정

- `backend/chatbot/attachment_classification_service.py`:
  `confirmed_attachment_classification_handoff` 추가
- `backend/chatbot/file_scan_service.py`: 현재 scan snapshot과 일치하고
  `confirmed_at`이 있는 서버 record만 다음 턴 canonical handoff에 재연결
- 공개 handoff는 `source`, `classification`, `confidence_band` 세 필드로 제한
- scan snapshot이 바뀌면 빈 결과를 반환해 stale 확인을 fail-closed 처리

### 회귀 근거

- 실제 OCR 확인 요청처럼 클라이언트가 분류 확인을 다시 보내지 않아도 서버의
  현재 확인 record가 재연결되는 Django E2E 회귀 테스트 PASS
- 미확인 record와 변경된 scan snapshot은 전달되지 않는 안전성 테스트 PASS
- 최종 PR #387의 production-gate와 regression-signal PASS
- 최종 운영 배포와 모든 runtime image tag 일치

### 최종 재시험 중 확인한 업로드 한도

인증 직후 J03 파일을 다시 첨부할 때 서버가 `rate_limit_exceeded` 429를 반환했다.
비식별 운영 조회 결과 요청은 `user`/`free`/`file_upload` 정책에 귀속됐고
`used_count=30`, `limit_count=30`이었다. 따라서 인증 전 guest 카운터가 잘못
적용된 결함이나 파일 형식·스토리지 실패가 아니라, 반복 E2E로 무료 계정의
24시간 업로드 한도를 실제 소진한 정상 차단이다. 자동 초기화 시각은
2026-08-04 00:12 KST다.

다만 이 429에서 사용자 문구가 `?? ??? ??????.`로 깨져 노출되는 별도 결함과
같은 파일의 다른 사용자 응답·이력 문구 손상 13곳을 추가로 확인했다. PR #388은
의미가 보존된 한국어 문구로 14곳을 복원했고, rate-limit 정확 문구 검사와
`views.py` 연속 물음표 금지 회귀 검사를 추가했다. 이는 한도 정책이나 카운터를
변경하지 않는 표시 계층 핫픽스다.

### 브라우저 재시험 무효 원인

실제 실행은 `PDF 파일 선택 → 메시지 전송`이었고, 중간의 `첨부` 버튼을
누르지 않았다. 코드상 파일 선택은 `selectedUploadFile`만 설정하며, `첨부`
버튼이 `registerAttachmentMetadata`를 호출해야 `registeredAttachments`에
서버 attachment가 추가되고 scan·분류·OCR 자동 분석이 시작된다.

- `OCR 분류 대기열에 연결했습니다`와 `선택됨 · OCR 대기`는 서버 업로드 완료가
  아니라 파일 선택 단계의 로컬 안내 문구였다.
- 메시지 payload는 `registeredAttachments`만 전송하므로 실제 attachment 목록은
  비어 있었다.
- 분류·OCR 카드 미표시, 필수 사실 재질문, report 0건은 이 잘못된 선행 상태의
  파생 결과이며 PR #395 회귀로 판정할 수 없다.
- date input 누락은 자동화 입력 이벤트와 React 상태의 불일치 가능성이 있어
  사람 입력 또는 실제 컴포넌트 이벤트 테스트로 별도 재현해야 한다.

현재 판정: **INVALID RETEST**. 올바른 재시험 순서는
`파일 선택 → 첨부 버튼 → scan clean → 분류 확인 → OCR 확인 → 사용자 사실 →
report·초안 → reload`이다.

## 10. 완료 감사 기준

| 요구사항 | 현재 증거 | 상태 |
|---|---|---|
| F-01~F-04 최초 실패 입력의 실제 브라우저 재시험 | 각 절의 동일 입력·파일 결과 | 충족 |
| 네 fixture 파일 실제 브라우저 사용 | PDF 2종·JPG·PNG의 파일명·SHA와 결과 | 충족 |
| latest dev와 배포 pipeline revision 일치 | `origin/dev`, pipeline source 모두 `e49aa53e…` | 충족 |
| 관련 전체 자동화·빌드·CI 통과 | Python, Django, frontend, build, 두 GitHub gate | 충족 |
| 분류/OCR 확인 이후 persisted report 생성 | 서버 첨부 등록을 건너뛴 실행이라 판정 불가 | **재시험 필요** |
| 동일 탭 reload 인증·상담·보고서 복원 | 인증·사용자 메시지 PASS, 등록 첨부·report는 미검증 | **재시험 필요** |
| 개인정보·비밀값·raw OCR 비노출 | 보고서·공개 브라우저 결과 점검 | 충족 |

전체 완료는 두 재시험 행이 올바른 순서의 실제 브라우저 실행에서 충족된 뒤에만
선언한다.

## 11. 증거 인덱스

### 브라우저

- E-J01-RETEST: 일반 법령 질문과 사고 문맥 뒤 법령 전환 DOM
- E-J02-RETEST: 최초 실패 문장의 네 슬롯 충족 DOM
- E-J03-RETEST: 사전통지서 분류·OCR 확인 DOM
- E-J04-RETEST: 납부고지서 `1차 고지서` 확인 DOM
- E-J06-JPG-RETEST: JPG 분류·Vision partial 안전 결과 DOM
- E-J06-PNG-RETEST: 전용 OCR 3/3과 개인정보 마스킹 DOM
- E-J08-RETEST: 인증 후 reload DOM — 인증·사용자 메시지 PASS, raw worker 문구 FAIL, 등록 첨부·report 미검증
- E-B01-RETEST: 파일 선택 뒤 `첨부` 버튼을 건너뛴 무효 실행 DOM

브라우저 증거는 현재 Codex 작업의 DOM snapshot으로 보존하며 민감 원문을
저장소에 복사하지 않는다.

### 코드·운영

- PR #384~#387의 base diff, merge SHA와 GitHub checks
- `backend/chatbot/test_attachment_classification_confirmation_flow.py`
- `backend/chatbot/tests.py`의 `AttachmentClassificationPersistenceTests`
- `app/web/authSession.test.js`
- `test/test_analysis_job_query_service.py`
- `test/test_attachment_workflow_service.py`
- `test/test_traffic_accident_ocr_runtime.py`
- CodePipeline, CodeBuild, 공개 health/ready, SSM runtime image/evidence 검증

## 12. 2026-08-04 PR #395 최종 운영 판정

### 배포 일치

- PR #395 merge SHA: `e49aa53ed28790c3ea1e474f21f0f1519ff108a2`
- production-gate `offline-verification`: SUCCESS
- `regression-signal`: SUCCESS
- CodePipeline execution `11ae78ee-29c0-477f-bb83-f952a520f0af`: Succeeded
- pipeline source revision과 PR merge SHA 일치

### 항목별 결과

| 항목 | 판정 | 브라우저 관찰 사실 |
|---|---|---|
| 인증 사용자 빈 상담 문구 | PASS | `로그인 상담 중` 표시 |
| PDF 파일 선택 | PASS | 파일 chooser와 로컬 선택 상태 표시 |
| PDF 서버 첨부 등록 | 미실행 | 선택 뒤 별도 `첨부` 버튼을 누르지 않음 |
| 90초 worker polling | 제한적 PASS | 첨부 없는 text job은 terminal 상태까지 표시 |
| 법령 source 이름 경계 | 미검증 | 확인된 OCR 법령이 없는 job이라 PR #395 경계를 실행하지 못함 |
| 분류·OCR 확인 전진 | 미검증 | 서버 첨부 미등록 |
| 필수 사실 소비 | 미검증 | OCR 확인 선행 계약 미실행 |
| persisted report | 미검증 | report 생성 선행 계약 미실행 |
| 이의신청서 초안 | 미검증 | report 생성 선행 계약 미실행 |
| reload 첨부 복원 | 미검증 | 서버 등록 첨부가 존재하지 않음 |
| reload 최신 AI 복원 | FAIL | 의미 답변 대신 worker 완료 상태 문구 노출 |

### 최종 결론

PR #395의 배포와 자동화 게이트, 인증 문구는 확인됐다. 그러나 이번 실행은 서버
첨부 등록을 건너뛰어 `OCR 확인 → 사실 전달 → persisted report → 이의신청서
초안 → reload 복원`을 실제로 시작하지 못했다. 따라서 F-05와 B-01의 제품
판정은 **RETEST REQUIRED**다. 별도로, no-display/partial job reload에서 raw
worker 완료 문구가 assistant 답변으로 노출되는 결함은 확정했다.
