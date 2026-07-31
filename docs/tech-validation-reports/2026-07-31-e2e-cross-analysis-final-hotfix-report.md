# 교통분쟁 AI 상담 E2E 교차 분석 및 최종 핫픽스 권고

> 분석일: 2026-07-31
> 분석 대상 배포 기준: `origin/dev` / `691ed6bdd07ca944d0f4e4bf63397f8c21612b91`
> 분석 자료:
> 1. `E2E 테스트.txt`의 13개 테스트 시나리오와 즉시 실패 조건
> 2. `019fb6b0-c020-7c73-b013-f1663fbf0b89.zip`의 결과 보고서, AWS 로그 발췌, 스크린샷 14장
> 3. `2026-07-31-pilot-hotfix-checklist.md`
> 4. 현재 배포 기준 저장소의 라우팅·개인정보·인증·첨부·운영 모니터·프런트 코드

## 1. 최종 판정

**현재 배포본은 파일럿 공개 승인 불가(Release Blocked)다.**

- 평가 가능 12건 중 통과 3건, 실패 9건이며 ID 5는 인증 장애로 기능 미평가다.
- 즉시 실패 조건 3개가 확인됐다.
  - ID 8: 민감정보 입력을 차단하지 않고 Agent/RAG 흐름으로 보냄
  - ID 12: 해석 불가 입력을 임의의 일반 법령 검색으로 처리
  - ID 13: 이미 제공된 사고 사실을 반복 질문하고 상충 진술을 명시하지 않음
- 별도의 운영·보안 차단 사유가 있다.
  - Caddy 접근 로그에 `X-Guest-Credential` 전체 값 기록
  - CloudWatch 운영 상태가 테스트 내내 매분 `status=fail`, `monitor_configuration_invalid`
  - 법령 그래프 조회에서 `expire_date` 스키마 경고 반복
  - 로그인 상태 소실과 재로그인 403
- 기존 HFX-001~008은 이번 실패를 모두 포괄하지 않는다. 특히 개인정보, 입력 이해도, 일반 법령 오분류, 고지서 후속 질문, 인증 복구, 운영 로그 비밀값, 모니터 증적 배포가 별도 P0 항목으로 필요하다.

## 2. 증거 신뢰도 검토

### 확인된 사실

- ZIP 결과 보고서와 정제 로그의 job ID, 라우팅 intent, node code, HTTP 상태는 서로 일치한다.
- ID 6, 7, 8, 12 등 일부 화면은 실제 사용자 입력과 응답을 육안 확인할 수 있다.
- 현재 코드에서 다음 원인이 직접 확인된다.
  - 일반 입력의 기본 plan이 항상 `law_ground_search`를 실행한다.
  - 서비스 범위 제외 규칙은 intent를 고려하지 않고 `보행자`, `횡단보도` 문자열만으로 expert handoff를 반환한다.
  - 주민번호·면허번호 정규식 끝의 `\b`가 뒤에 한국어 조사(`이고`, `입니다`)가 붙으면 경계를 인식하지 못한다.
  - 새 상담 초기화가 `registeredAttachments`를 비우지 않는다.
  - Supervisor LLM 응답 계약에 same-message `fact_conflicts` 필드가 없다.
  - ops-monitor용 호스트 디렉터리는 만들지만 `run_summary.json`을 배포하는 스크립트가 없다.
  - Caddy는 전체 request header가 포함될 수 있는 기본 JSON access log를 사용하고 민감 header 삭제/마스킹 규칙이 없다.

### 증거 부족 또는 재수집 필요

스크린샷 14장 중 다음 7장은 대부분 빈 화면이거나 좌측 메뉴 일부만 보여 해당 케이스의 입력·응답 증거로 사용할 수 없다.

- `e2e-case-02.png`
- `e2e-case-04-attachment-login-blocked.png`
- `e2e-case-04-authenticated.png`
- `e2e-case-05-authentication-blocked.png`
- `e2e-case-10.png`
- `e2e-case-11.png`
- `e2e-case-13.png`

따라서 ID 2, 4, 5, 10, 11, 13의 판정은 보고서와 로그로는 상당 부분 지지되지만, “화면 증거까지 완결된 상태”는 아니다. 수정 후에는 입력·최종 응답·상태 배지·URL 또는 case ID가 한 화면에 나오도록 다시 캡처해야 한다.

또한 ID 4에 사용한 첨부는 실제 고지서 형식의 합성 문서가 아니라 UI 설계 이미지다. 분류 실패나 한계 안내 검증에는 사용할 수 있지만, 고지서 필드 추출·누락 정보 구분 정확도를 검증하는 대표 fixture로는 부적합하다.

## 3. 13개 시나리오 독립 판정

| ID | 독립 판정 | 확인된 문제 | 최종 수정 방향 |
|---|---|---|---|
| 1 | 통과 | 빈 입력에서 분석·메시지 생성 없음 | 전송 버튼 자체도 빈 입력에서는 disabled 처리하고 API 400/`needs_input` 계약 테스트 추가 |
| 2 | 실패 | 일반 법령 질문을 보행자 사고 expert handoff로 오분류 | 법령 intent를 먼저 확정하고, `보행자/횡단보도` 제외 규칙은 사고·충돌 문맥일 때만 적용 |
| 3 | 실패 | 일반 절차만 출력, 문서명·발급기관·기한·사진 요청 누락, 깨진 법령 원문 노출 | 고지서 intake slot gate 추가, 법령 검색 성공 여부와 무관하게 미충족 slot을 질문, raw `provision_text` 직접 노출 금지 |
| 4 | 실패 | 업로드·분류는 성공했으나 내부 문구만 표시, 확인/누락/근거/한계 없음 | 분류 → 사용자 확인 → OCR/고지서 분석 → 사용자용 병합의 2단계 상태 머신 구현 |
| 5 | 미평가 + 인증 실패 | 새로고침 후 guest로 복귀, Google code API 403 3회, 초안 기능 미진입 | 앱 시작 시 `/auth/me` 검증 및 token refresh, 인증 중 guest bootstrap 금지, 403 reason 기록, ID 5 기능은 수정 후 재시험 |
| 6 | 통과 | 네 필수 항목 질문, 과실 숫자 미제시 | 회귀 테스트로 고정 |
| 7 | 통과 | 긴급조치·증거보존·전문가 이관 우선, 과실 숫자 미제시 | 회귀 테스트로 고정 |
| 8 | 즉시 실패 | 민감번호를 차단하지 않고 `general_consultation → law_ground_search` 실행 | PII regex를 digit lookaround 기반으로 수정, 저장/라우팅/로그 전 단일 fail-closed gateway 적용 |
| 9 | 실패 | 욕설은 반복하지 않았으나 고지서 종류·기한·기관·첨부 질문 누락 | 욕설 제거 후 의도 보존, ID 3과 동일한 고지서 slot gate 적용 |
| 10 | 실패 | 욕설만 있는 입력에 “접수” 문구, 약 39초 대기, 문의 유형 질문 없음 | 저정보·욕설-only 입력 gate에서 즉시 `needs_clarification`, Worker/RAG 실행 금지 |
| 11 | 실패 | 오타 의도는 인식했으나 필수 정보 질문 누락, 약 33초 대기 | 오타 정규화 후 fine-notice slot gate, 단순 intake는 동기 응답으로 처리 |
| 12 | 즉시 실패 | 초성 입력을 `general_consultation → law_ground_search`로 처리 | 이해도 gate와 최소 의미 토큰 기준 추가, 임의 검색 금지 |
| 13 | 즉시 실패 | 상충 진술 미탐지, 이미 제공한 신호·차량 행동 재질문 | Supervisor 계약에 `fact_conflicts` 추가, same-message 충돌 탐지, 확인된 field는 질문에서 제외 |

## 4. 공통 원인 분석

### 4.1 라우팅이 “의미”보다 단일 키워드와 기본 Agent 실행에 의존

`supervisor_routing_policy.v1.json`은 `도로교통법`을 법령 질문으로 분류하지만, 이후 `service_scope_policy`가 intent와 무관하게 `보행자` 또는 `횡단보도`가 포함됐다는 이유만으로 expert handoff를 반환한다. 이것이 ID 2의 직접 원인이다.

반대로 이해할 수 없는 입력, 욕설-only 입력, 민감정보 입력은 기본 `general_consultation`으로 떨어지고 이 plan이 `law_ground_search`를 포함한다. 즉 “분류 불가”가 “법령 검색 실행”으로 바뀌는 구조가 ID 8, 10, 12를 만든다.

### 4.2 입력 검증 node가 형식만 보고 의미 품질을 검증하지 않음

현재 `input_context_validation`은 text 또는 attachment가 존재하는지만 확인한다. 다음 조건을 구분하지 않는다.

- 민감정보 포함
- 욕설만 존재
- 초성/무의미 문자열
- 지원 분야를 판단할 최소 정보 부족
- 내부 상충 진술

이 검증은 Agent plan 첫 node가 아니라 **저장·rate-limit 차감·라우팅보다 앞선 API 경계**에서 실행되어야 한다.

### 4.3 개인정보 정규식이 한국어 문장 경계를 놓침

현재 주민번호와 면허번호 패턴은 마지막에 `\b`를 사용한다. Python 정규식에서 숫자와 한글은 모두 word character이므로 다음 입력의 번호 끝에서 word boundary가 성립하지 않는다.

```text
900101-1234567이고
11-22-333333-44입니다
```

현재 코드로 동일 입력을 실행하면 `accepted`, 차단 category 없음으로 재현된다. 정규식은 `(?<!\d)`와 `(?!\d)`로 숫자 경계를 확인해야 하며, 라벨·조사·괄호·문장부호가 붙는 변형을 parameterized test로 고정해야 한다.

### 4.4 고지서 절차 흐름이 “검색 성공”을 “상담 완료”로 오인

`fine_notice_procedure`는 바로 `law_ground_search`를 실행하고, 검증된 법령 결과가 있으면 `_fine_notice_procedure_answer()`를 최종 답으로 사용한다. 이 함수는 일반 순서만 출력하고 문서명·발급기관·기한·첨부를 실제 pending question으로 만들지 않는다.

또한 법령 항목의 `summary` 또는 `provision_text`를 그대로 붙여 최대 3개를 렌더링하므로 OCR/RAG 조각이 깨져 있으면 사용자 화면에 그대로 나온다.

### 4.5 첨부 분류와 실제 고지서 분석 사이의 handoff가 없음

일반 image/PDF가 scan-ready이면 attachment purpose보다 `attachment_document_classification`이 우선한다. 분류 node가 성공해도 같은 요청에서 `fine_notice_analysis`로 재계획하지 않으며 최종 병합은 분류 Agent summary를 그대로 사용할 수 있다. 그래서 ID 4가 내부 처리 문구로 끝났다.

필요한 계약은 다음과 같다.

1. 안전 스캔
2. 문서 종류 분류
3. 사용자에게 분류 결과와 사용 목적 확인
4. 고지서로 확인되면 OCR/필드 추출
5. 확인 정보·누락 정보·근거·한계 생성
6. 사용자가 필드를 확인한 뒤에만 이의 검토/문서 단계 개방

### 4.6 인증·상담·첨부 상태가 하나의 원자적 session model로 움직이지 않음

- localStorage에 access token과 auth session을 저장하지만 앱 시작 시 `/auth/me`를 호출해 서버 상태를 재검증하는 흐름이 없다.
- `startNewConversation()`은 `sessionId`를 비우지만 `registeredAttachments`는 비우지 않는다.
- 인증 상태인 채 session ID가 비면 일부 흐름이 guest session bootstrap을 다시 호출할 수 있다.
- API 오류 시 local auth를 지우는 분기가 넓어, 한 번의 세션/리소스 오류가 전체 로그인 소실로 확대될 수 있다.

ID 5의 403 정확한 provider reason은 정제 로그에 없어 단일 원인으로 단정할 수 없지만, 위 상태 모델 결함과 첨부 누적은 코드로 확인된다.

### 4.7 상충 진술을 표현할 계약이 없음

사고 Supervisor LLM schema는 `collected_facts`, `missing_fields`, `next_questions`만 받으며 `fact_conflicts`를 받지 않는다. reducer는 이전 값과 새 후보 값이 다를 때만 충돌로 만든다. 한 메시지 안의 “녹색 신호로 직진”과 “빨간불 진입으로 보일 수 있음”은 하나의 `signal_priority` 문자열 또는 누락값으로 처리되기 쉽다.

### 4.8 운영 상태와 배포 증적이 연결되지 않음

ops-monitor는 `/run/operational-evidence/run_summary.json`을 읽도록 설계됐고 호스트 디렉터리를 read-only mount한다. 그러나 배포 스크립트는 디렉터리만 만들며 검증된 `run_summary.json`을 복사·원자 교체하는 단계가 없다. 이 상태에서 monitor가 매분 critical을 내는 것은 정상적인 결과다.

### 4.9 로그가 인증 credential을 보존

Caddy JSON access log에 request header 전체가 들어가며 `X-Guest-Credential`을 제외하는 설정이 없다. credential은 이미 로그에 기록됐으므로 단순 코드 수정만으로 끝나지 않는다.

- 로그 접근 권한 제한
- 기존 로그의 보존 기간/복제 대상 확인
- 해당 guest credential 무효화
- 신규 로그 필드 allowlist 또는 민감 header 삭제

가 함께 필요하다.

## 5. 기존 HFX 체크리스트의 적합성

| 기존 항목 | 이번 결과와의 관계 | 보완 필요 |
|---|---|---|
| HFX-001 리포트 작업대 | 이번 13개 상담 실패의 직접 원인은 아님 | 배포 브라우저 재검증은 유지 |
| HFX-002 사실 병합·반복 질문 | ID 13과 직접 관련 | same-message conflict contract와 exact E2E 문장 추가 |
| HFX-003 첨부 참조 가시성 | ID 4 및 첨부 누적과 관련 | 분류→OCR handoff와 새 상담 attachment reset까지 확대 |
| HFX-004 비회원 저장·새 상담 | ID 5와 일부 관련 | 인증 유지, session 교체, attachment lifecycle을 명시 |
| HFX-005 비정상·범위 밖 질문 | ID 10, 12와 일부 관련 | “문구”가 아니라 pre-routing input-quality gate로 상향 |
| HFX-006 과실→리포트 | ID 5 인증 장애로 end-to-end 증거 없음 | auth 수정 후 재시험 |
| HFX-007 Vision provider | 이번 무과금 텍스트 E2E와 별도 | 유료 승인 전 release gate와 분리 |
| HFX-008 신규 청킹·그래프 | Neo4j 경고와 연관 가능 | 현재 graph snapshot의 property/schema readiness도 별도 확인 |

### 반드시 추가할 핫픽스 항목

- **HFX-009 / P0 — 의도·서비스 범위 라우팅 정렬**
- **HFX-010 / P0 — 한국어 문맥 개인정보 차단과 로그 비밀값 제거**
- **HFX-011 / P0 — 저정보·욕설-only·해석 불가 입력 gate**
- **HFX-012 / P0 — 인증 session 복구와 새 상담 상태 원자화**
- **HFX-013 / P0 — 운영 run_summary 배포 및 monitor 정상화**
- **HFX-014 / P1 — 고지서 intake slot과 안전한 법령 응답**
- **HFX-015 / P1 — 첨부 분류→OCR→분석 handoff**
- **HFX-016 / P1 — 상충 진술 계약과 반복 질문 제거**
- **HFX-017 / P1 — polling timeout·partial 상태 UX**
- **HFX-018 / P1 — E2E 증거 캡처 품질과 상관관계 ID**

## 6. 최종 수정 순서

### 1단계 — P0 보안·안전 경계

1. `pii_masking.py`
   - 주민번호·면허번호 패턴의 `\b`를 digit lookaround로 교체
   - 공백, 하이픈, 조사, 괄호, 문장부호 변형 테스트 추가
2. `submit_chat_message`
   - PII/secret 차단을 persistence, history, usage 차감, routing보다 먼저 유지
   - 차단 응답은 원문을 포함하지 않는 400 `chat_input_rejected`
   - 프런트는 사용자 bubble/history에도 민감 원문을 남기지 않고 안전 안내로 교체
3. Caddy
   - request header 전체 기록을 중단하고 필요한 필드만 allowlist
   - 최소한 `Authorization`, `Cookie`, `X-Guest-Credential` 제거
   - 기존 노출 credential 폐기 및 로그 접근/보존 범위 점검

### 2단계 — P0 입력 gate와 라우팅

1. `input_understanding_gate.v1`을 Agent 실행 전 추가
2. 출력 상태를 `accepted`, `needs_clarification`, `blocked_sensitive`, `out_of_scope`로 제한
3. `general_consultation` 기본 plan에서 무조건 `law_ground_search` 제거
4. 일반 교통 법령 intent를 확정한 뒤 사고 제외 규칙을 적용하지 않도록 순서 변경
5. 보행자 제외는 `사고|충돌|접촉|과실` 문맥과 함께 있을 때만 적용
6. 욕설-only/초성-only는 동기 `needs_clarification`으로 종료

### 3단계 — P0 인증·상태·운영

1. 앱 부팅 시 저장 token이 있으면 `/auth/me`로 서버 상태 확인
2. access token 만료 전 refresh, refresh 실패와 resource/session 오류를 구분
3. 인증 상태에서는 guest bootstrap 호출 금지
4. 새 상담은 서버에서 새 session을 발급받은 뒤 다음을 한 번에 초기화
   - chat messages
   - intake
   - analysis/report
   - registered attachments
   - OCR confirmation
   - pending auth action
5. Google 403의 안전한 reason code를 history/운영 로그에 남김
6. 검증된 `run_summary.json`을 배포 release 디렉터리에서 operational-evidence로 원자 복사하고 monitor 시작 전 schema/freshness 검사
7. Neo4j seed 후 `expire_date` property/schema와 대표 쿼리 readiness 검사

### 4단계 — P1 상담 기능

1. 고지서 절차의 필수 slot
   - 문서명/처분 유형
   - 발급기관
   - 의견제출 또는 이의신청 기한
   - 고지서 첨부 여부
2. slot 미충족 시 법령 결과가 있어도 pending question을 반드시 반환
3. 법령 결과는 법령명·조문·검증된 짧은 요약만 표시하고 raw chunk/OCR fragment는 숨김
4. 첨부 상태 머신 구현
   - `classified_waiting_confirmation`
   - `ocr_running`
   - `ocr_needs_confirmation`
   - `analysis_ready`
   - `partial` / `failed`
5. Supervisor schema에 `fact_conflicts` 추가
6. 같은 메시지 안의 충돌을 field별로 보존하고 해당 field만 재질문
7. 이미 수집된 field는 `missing_fields`와 `next_questions`에서 제외

### 5단계 — P1 응답·관측성

1. Worker `success`와 사용자 과업 성공을 분리
   - Agent 실행 성공이어도 상담 목표 미충족이면 `needs_input` 또는 `partial`
2. 프런트 polling 30초 초과 시 일반 “접수” 문구로 덮지 말고
   - 계속 처리 중
   - 부분 결과
   - 재시도
   - correlation/job ID
   를 표시
3. 서버 재기동 중 job continuity와 idempotent result polling 검증

## 7. 필수 회귀 테스트

### 단위·계약 테스트

- 사용자 제공 13개 문장을 그대로 parameterized fixture로 저장
- PII 조사 결합 변형:
  - `900101-1234567이고`
  - `900101-1234567입니다`
  - `(900101-1234567)`
  - `11-22-333333-44입니다`
- 라우팅:
  - `횡단보도`가 포함된 일반 법령 질문 → `traffic_law_search`
  - 보행자 충돌 사고 → expert handoff
  - 욕설-only/초성-only → no Agent invocation
- 고지서:
  - 법령 검색 success여도 slot 미충족 → pending questions 존재
  - 깨진 raw chunk가 assistant answer에 없음
- 사고:
  - same-message 신호 충돌 → `fact_conflicts.signal_priority`
  - 제공된 vehicle action은 재질문하지 않음
- 인증:
  - 로그인→새로고침→`/auth/me`→동일 user/session
  - 로그인→새 상담→새 session, auth 유지, attachment 0개
- 운영:
  - 배포된 run summary가 없거나 stale이면 release precheck 실패
  - access log에 credential 원문 없음

### 배포 E2E

각 케이스마다 다음을 하나의 evidence bundle에 남긴다.

- release SHA/image digest
- 브라우저 입력·응답 화면
- HTTP status와 public response body
- routing intent
- node list
- final semantic status
- job/correlation ID
- 개인 식별자와 credential을 제거한 서버 로그

ID 4는 실제 고지서와 닮은 **합성 고지서 fixture**를 사용하고, ID 5는 인증 복구 후 첨부 기반 초안 생성까지 별도로 완료해야 한다.

## 8. 재배포 승인 기준

다음 조건을 모두 만족하기 전에는 재배포 승인하지 않는다.

- 13개 시나리오 전부 통과
- 즉시 실패 조건 0건
- ID 5 기능 판정 완료
- access log credential 원문 0건
- CloudWatch operational health 10분 연속 `status=ok`
- 법령/Neo4j readiness 경고 0건 또는 승인된 비차단 warning으로 명시
- 새 상담 후 첨부 0건, 로그인 상태 유지
- 모든 스크린샷이 입력과 최종 응답을 실제로 보여 줌
- 동일 release SHA에 대해 단위·통합·배포 E2E 증거가 연결됨

## 9. 가장 먼저 실행할 작업

첫 PR은 범위를 섞지 말고 다음 세 가지를 하나의 “안전 경계 핫픽스”로 묶는 것이 적절하다.

1. 한국어 조사 결합 PII regex 수정
2. 저정보/해석 불가 입력의 Agent 실행 차단
3. 일반 법령 질문에 사고 제외 규칙이 적용되지 않도록 intent-aware scope 평가

이 PR이 통과한 뒤 인증·새 상담 상태 PR, 고지서/첨부 handoff PR, 운영 모니터/로그 PR을 분리하면 재현과 회귀 검증이 가장 명확하다.
