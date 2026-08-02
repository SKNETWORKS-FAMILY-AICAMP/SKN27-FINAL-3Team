# Pilot Case-Ready, OCR, Persisted Report Hotfix Design

> 기준일: 2026-08-03
> 기준 브랜치: `origin/dev`
> 기준 SHA: `dd9931b3af369de41a4a9c563d4ced07ed29612e`
> 상태: 사용자 승인 범위를 구현 가능한 설계로 고정

## 1. 목표

과실 상담이 `case_ready`에 도달했을 때 임시 리포트 화면만 보여 주는 현재 단절을 해소한다. 사용자가 명시적으로 시작한 경우에만 로그인된 사건으로 전환하고, 사실 확정, 분석 작업, 영속 리포트, 교통사고 이의신청서 초안까지 기존 API를 통해 연결한다.

제공된 ZIP의 문서는 서로 다른 두 OCR 시나리오로 사용한다.

1. 교통사고사실확인원 계열은 과실 상담 사건의 증거 및 사실 확인 입력으로 사용한다.
2. 과태료 통지·납부고지서 계열은 기존 과태료 OCR 및 이의신청 흐름의 회귀 입력으로 사용한다.

최종 완료 판정은 자동 테스트와 로컬 빌드만으로 내리지 않는다. 배포된 빌드 `https://skn27-traffic-pilot.duckdns.org/`에서 실제 파일을 업로드해 전체 흐름을 직접 실행하고, 영속 데이터 식별자와 화면 결과가 모두 확인되어야 한다.

## 2. 입력 자료와 문서군

원본 ZIP: `과태료 고지서 과실비율 확인서.zip`

### 2.1 교통사고사실확인원 계열

- `22-11-18-_.png`
  - 전체 서식이 보이는 교통사고사실확인원 이미지
  - 정상 또는 일부 필드 누락 OCR 시나리오
- `15-07-18-.jpg`
  - 사고 내용 일부만 보이는 잘린 이미지
  - 문서 불완전, 필수 필드 누락, 재업로드 안내 시나리오

### 2.2 과태료 계열

- `form2_별지154_위반사실통지및과태료사전통지서.pdf`
  - 과태료 `사전통지` 문서 시나리오
- `form3_별지152_과태료납부고지서원부_운전자.pdf`
  - 과태료 `1차 고지서` 문서 시나리오

두 문서군은 같은 사건이나 같은 분석 요청에 함께 넣지 않는다. 각 문서군은 해당 라우팅 의도와 OCR 계약으로 독립 검증한다.

## 3. 현재 코드에서 확인한 경계

### 3.1 이미 존재하는 서버 기능

- `POST /api/cases/`: 로그인 소유자의 상담 세션을 사건으로 전환한다.
- `POST /api/cases/{case_id}/facts/confirm/`: 확인된 사실 버전을 생성한다.
- `POST /api/cases/{case_id}/analysis/jobs/`: 확인된 사실과 사건 증거를 분석 작업으로 큐잉한다.
- 사건 분석 계획은 이미 `text_ml_case_search`, `law_ground_search`, `objection_report_generation`을 포함한다.
- 분석 요청은 `fault_ratio_analysis` reporting payload를 사용한다.
- 사건에 연결된 scan-ready 첨부 ID는 case evidence의 material source로 사용된다.
- 영속 리포트 조회와 문서 확인·다운로드 API가 이미 존재한다.

따라서 이번 핫픽스에서는 백엔드 Agent, OCR, RAG, 보고서 생성 엔진을 변경하지 않는다.

### 3.2 현재 단절

- 프런트 API client에는 Case API 메서드가 있지만 `FrontendAppShell`에서 호출하지 않는다.
- `case_ready`는 자동으로 사건이나 Worker 작업을 만들지 않는다.
- 현재 리포트 화면은 `report_id`와 서버 `content.reporting_payload`가 없으면 임시 preview다.
- 임시 preview의 `작성 중` 표시는 영속 리포트 생성 증거가 아니다.

## 4. 고정 범위

### 4.1 포함

- `case_ready` 응답에서 확인된 핵심 사실 요약 표시
- `로그인 후 사건 생성·분석 시작` 명시적 CTA
- 로그인 전 CTA 선택 상태 보존과 로그인 후 재개
- 상담 세션의 사건 전환
- 확인된 사실 버전 생성
- 기존 사건 분석 작업 시작
- 기존 job/result API polling
- terminal result에서 `report_id` 확인
- report detail 재조회와 persisted report 표시
- 교통사고 이의신청서 초안 확인·다운로드 진입
- 제공 문서 4개의 분리된 OCR 시나리오
- 마스킹된 기대 결과를 사용하는 자동 회귀 테스트
- Vite production build
- 배포된 빌드에서 실제 파일 업로드 기반 브라우저 E2E

### 4.2 제외

- `ai/**` 및 `etl/**` OCR·RAG·Agent 판단 로직 변경
- 새로운 모델 provider, node code, routing intent 도입
- DB model 또는 migration 변경
- 인증·소유권·파일 검역 정책 변경
- Pipeline, 배포 스크립트, Terraform 변경
- 제공 원본 문서의 저장소 커밋
- 제공된 네 파일과 같은 파일의 진단 재시도를 벗어난 OpenAI Vision 유료 호출
- 서로 다른 문서군을 하나의 사건으로 결합
- 현재 범위와 무관한 UI 수정 또는 리팩터링

## 5. 권장 사용자 흐름

### 5.1 과실 상담 사건 흐름

1. 사용자가 과실 상담을 진행한다.
2. 필요한 경우 교통사고사실확인원 이미지를 업로드한다.
3. 파일은 기존 업로드, scan, 분류, OCR 경계를 통과한다.
4. 상담이 `case_ready`에 도달하면 프런트는 확인된 핵심 사실과 자료 상태를 표시한다.
5. 사용자가 `로그인 후 사건 생성·분석 시작`을 누른다.
6. 비로그인 상태면 Google 로그인으로 이동하고, 성공 후 같은 상담과 pending action을 복구한다.
7. 프런트가 기존 Case API를 순서대로 호출한다.
   - create case
   - confirm facts
   - start analysis
8. job/result polling으로 terminal 상태를 기다린다.
9. `report_id`가 확인되면 report detail을 다시 조회한다.
10. `report_id`와 `content.reporting_payload`가 모두 있는 persisted report만 최종 리포트로 표시한다.
11. 사용자 확인 gate를 거쳐 교통사고 이의신청서 초안 다운로드 진입을 제공한다.

사용자의 CTA 클릭 전에는 사건, 사실 버전, 분석 작업을 자동 생성하지 않는다.

### 5.2 과태료 OCR 흐름

1. 과태료 PDF를 각각 독립 상담에 업로드한다.
2. scan과 문서 분류를 통과한다.
3. 기존 `fine_notice_analysis` OCR 결과를 표시한다.
4. 사용자가 OCR 필드를 확인 또는 수정한다.
5. 확인된 OCR만 법률·이의가능성·보고서 후속 흐름에 사용한다.
6. `사전통지`와 `1차 고지서`가 서로 다른 단계로 유지되는지 확인한다.

## 6. 프런트 상태 설계

`case_ready` 연결은 독립적인 상태 모델로 관리한다.

```text
idle
  -> login_required
  -> creating_case
  -> confirming_facts
  -> starting_analysis
  -> polling
  -> loading_report
  -> ready
  -> failed
```

상태마다 현재 진행 단계와 재시도 가능 여부를 표시한다. 중복 클릭과 중복 요청을 막되, 기존 Case API의 idempotency를 그대로 사용한다.

필수 상태 값은 다음으로 제한한다.

- source session ID
- case ID
- fact version ID
- analysis job ID
- persisted report ID
- pending auth action
- 현재 단계 및 사용자용 오류

임시 reporting payload는 `ready` 판정에 사용하지 않는다.

## 7. 사실 및 첨부 연결

- 상담의 네 핵심 사실을 `confirmed_facts.v1` 입력으로 변환한다.
- 사용자가 화면에서 최종 확인한 값만 `facts`로 보낸다.
- OCR 결과 또는 업로드 자료를 사용한 사실에는 attachment ID 기반 source를 연결한다.
- scan-ready 상태가 아닌 첨부는 material source로 취급하지 않는다.
- 충돌이 남은 사실은 숨기지 않고 `conflicts`로 전달한다.
- 개인정보 원문, OCR raw text, 모델 응답 전문은 새 프런트 상태나 테스트 fixture에 저장하지 않는다.

## 8. 제공 파일 기반 OCR 시나리오

### OCR-A-01: 전체 교통사고사실확인원

- 입력: `22-11-18-_.png`
- 기대 분류: `traffic_accident_confirmation`
- 기대 결과: 대상 문서 인식, 허용 필드 추출, 개인정보 마스킹
- 허용 terminal 상태: `success` 또는 명시적 누락 필드가 있는 `partial`
- 금지: 보이지 않는 값을 추정해 채움, 개인정보 원문 노출

### OCR-A-02: 잘린 사고 내용 이미지

- 입력: `15-07-18-.jpg`
- 기대 결과: 불완전 문서 또는 필수 필드 누락을 명시
- 허용 terminal 상태: `partial` 또는 `failed`
- 기대 행동: 전체 1page 이미지 재업로드 안내
- 금지: 정상 완료 또는 누락 필드 임의 생성

### OCR-F-01: 과태료 사전통지서

- 입력: `form2_별지154_위반사실통지및과태료사전통지서.pdf`
- 기대 분류: `fine_notice`
- 기대 단계: `사전통지`
- 기대 결과: 법조, 위반 내용, 일시·장소, 금액, 기한, 발급기관 필드의 추출 또는 명시적 누락

### OCR-F-02: 과태료 납부고지서

- 입력: `form3_별지152_과태료납부고지서원부_운전자.pdf`
- 기대 분류: `fine_notice`
- 기대 단계: `1차 고지서`
- 기대 결과: 법조, 위반 내용, 일시·장소, 금액, 납부기한, 발급기관 필드의 추출 또는 명시적 누락

모델 OCR은 비결정적일 수 있으므로 자동 테스트는 개인정보가 제거된 필수 필드, 단계, 상태, 누락 처리 계약을 검증한다. 실제 값 판독 품질은 배포 빌드 브라우저 E2E에서 별도로 기록한다.

## 9. 오류 처리

- 로그인 실패: 사건을 만들지 않고 같은 CTA를 다시 제공한다.
- 사건 생성 실패: 사실 확정이나 분석을 호출하지 않는다.
- 사실 확정 실패: 분석을 호출하지 않는다.
- readiness gate 실패: 누락 사실 또는 자료를 사용자에게 표시한다.
- 분석 실패: 임시 preview를 최종 리포트로 표시하지 않는다.
- report ID 누락: `리포트 생성 완료`로 표시하지 않는다.
- report detail 누락: 재조회 행동을 제공하고 빈 리포트 화면으로 이동하지 않는다.
- OCR partial/failed: 확인되지 않은 값을 후속 분석에 넘기지 않는다.
- 브라우저 E2E 실패: 실패 단계와 요청 식별자를 기록하고 다음 핫픽스로 넘어가지 않는다.

## 10. 예상 파일 경계

### 프런트 구현

- `app/web/FrontendAppShell.jsx`
- `app/web/styles.css`
- `app/web/apiClient.js` — 기존 메서드로 부족한 조회 계약이 있을 때만 최소 수정
- 신규 순수 workflow helper와 단위 테스트
- 관련 consultation, auth, report frontend contract tests

### 계약·회귀 테스트

- 기존 Case API가 현재 계약대로 동작함을 확인하는 focused Django 테스트
- 프런트가 API 호출 순서, 실패 차단, polling, persisted report 판정을 지키는 Node 테스트
- 제공 파일 자체는 저장소 fixture로 복사하지 않는다.
- fixture에는 문서 종류와 마스킹된 기대 필드만 둔다.

다음 경로는 수정하지 않는다.

- `ai/**`
- `etl/**`
- `backend/chatbot/case_repository.py`
- `backend/chatbot/repositories.py`
- `backend/chatbot/models.py`
- `backend/chatbot/migrations/**`
- `deploy/**`
- `infra/**`
- `buildspec*.yml`

기존 서버 계약이 예상과 달라 위 경로 수정이 필요해지면 구현을 중단하고 근거와 필요한 변경을 사용자에게 먼저 보고한다.

## 11. 테스트 및 빌드

구현은 실패 테스트, 최소 구현, 집중 회귀, 전체 회귀 순서로 진행한다.

### 11.1 프런트 단위 테스트

- `case_ready`가 아니면 CTA를 표시하지 않는다.
- CTA 전에는 Case API를 호출하지 않는다.
- 로그인 전 pending action을 보존한다.
- create, confirm, start 순서를 지킨다.
- 앞 단계 실패 시 뒤 단계 호출을 차단한다.
- 중복 클릭이 사건 또는 job을 중복 생성하지 않는다.
- terminal job에서 persisted report ID를 찾는다.
- report detail이 없는 임시 payload를 최종 리포트로 표시하지 않는다.
- OCR 문서군별 상태와 사용자 행동을 구분한다.

### 11.2 서버 회귀

- `case_ready` 채팅 자체는 Worker를 자동 생성하지 않는다.
- 로그인 소유자만 사건을 생성한다.
- 확인된 사실 없이는 분석을 시작하지 않는다.
- 사건 분석 계획에 기존 세 노드가 유지된다.
- 성공 작업이 case-linked persisted report를 생성한다.

### 11.3 빌드

- 관련 Node tests
- 관련 root pytest
- 관련 Django tests
- 전체 root pytest
- 전체 Django chatbot tests
- Vite production build
- `git diff --check`

## 12. 배포 빌드 브라우저 E2E

배포된 최종 SHA에서 다음을 직접 실행한다.

### 12.1 과실 상담 및 사고 문서

1. 새 상담에서 과실 상담 네 핵심 사실을 입력한다.
2. 전체 교통사고사실확인원 PNG를 업로드한다.
3. scan, 분류, OCR 결과와 마스킹을 확인한다.
4. `case_ready`와 핵심 사실 요약을 확인한다.
5. 명시적 CTA로 로그인 및 사건 생성을 시작한다.
6. case ID, fact version ID, job ID가 순차 생성되는지 확인한다.
7. terminal job과 persisted report ID를 확인한다.
8. 리포트 상세에 사건·분석 결과가 표시되고 `확인된 자료 없음` placeholder가 남지 않는지 확인한다.
9. 교통사고 이의신청서 초안 진입과 확인 gate를 확인한다.
10. 잘린 JPG는 별도 상담에서 partial/failed 및 재업로드 안내를 확인한다.

### 12.2 과태료 문서

1. PDF 두 개를 각각 별도 상담에 업로드한다.
2. `사전통지`와 `1차 고지서` 분류를 확인한다.
3. OCR 확인 카드의 마스킹된 주요 필드를 원본과 대조한다.
4. OCR 확인 후 기존 후속 분석과 이의신청서 흐름을 확인한다.

### 12.3 브라우저 통과 조건

- 브라우저 console error 0건
- 잘못된 fallback 응답 0건
- 사용자 CTA 전 server mutation 0건
- case ID, fact version ID, job ID, report ID 모두 확인
- persisted report detail 확인
- 임시 리포트를 최종 리포트로 오인하는 표시 0건
- 문서군 오분류 0건
- 개인정보 원문이 리포트·로그·테스트 출력에 새로 노출되는 사례 0건
- 이의신청서 초안 진입 확인

브라우저 E2E에서 하나라도 실패하면 통과로 판정하지 않고 같은 핫픽스에서 원인을 수정한 뒤 빌드·배포·재검증한다.

## 13. 유료 OCR 승인 경계

자동 테스트에서는 OCR provider를 mock해 비용을 발생시키지 않는다. 사용자는 2026-08-03 제공된 네 파일의 배포 빌드 OCR과 같은 파일에 필요한 진단 재시도를 승인했으므로 별도 비용 승인을 다시 요청하지 않는다.

배포 전에는 다음 작업을 수행한다.

- fixture 및 테스트 작성
- 프런트 연결 구현
- mock 기반 회귀
- production build

배포 후에는 제공된 네 파일만 실행하며 다른 샘플이나 모델을 임의로 추가하지 않는다. 실패 재호출은 같은 파일의 원인 확인에 필요한 범위로 제한한다.

## 14. 완료 판정

다음 조건을 모두 만족해야 이 핫픽스를 완료로 판정한다.

1. `case_ready` 명시적 CTA와 로그인 복구가 동작한다.
2. 기존 Case API 호출 순서와 실패 차단이 자동 테스트로 고정된다.
3. 사건, 사실 버전, 분석 job, persisted report가 실제로 연결된다.
4. 사고·과태료 문서 4개의 분리된 OCR 시나리오가 동작한다.
5. 관련 전체 회귀와 Vite production build가 통과한다.
6. 배포된 최종 SHA에서 실제 브라우저 E2E가 통과한다.
7. persisted report와 이의신청서 초안이 실제 화면에서 확인된다.
8. 백엔드 엔진, 배포 인프라, 범위 외 파일 변경이 없다.
