# G4 고지서·첨부·상충 진술 핫픽스 설계

## 1. 목적

G4는 마스터 체크리스트의 HFX-014, HFX-015, HFX-016을 구현해 다음 운영
E2E를 안정적으로 통과시키는 단계다.

- ID 3: 고지서 절차 질문에서 문서명·발급기관·기한·첨부 여부를 빠짐없이 확인
- ID 4: 첨부 분류부터 OCR 확인, 고지서 분석, 이의 절차 검토까지 안전하게 연결
- ID 9: 욕설을 제거하면서 고지서 상담 의도와 동일한 접수 질문 유지
- ID 11: 오타가 있어도 상담 의도를 유지하되 알 수 없는 사실을 추측하지 않음
- ID 13: 동일 메시지의 신호 상충을 보존하고 과실 숫자를 제시하지 않음

구현은 기존 안전 경계, 인증·새 상담 상태, 운영 증적 변경을 유지하면서 현재
브랜치 `feat-pilot-safety-hotfix`에서 순차 체크포인트로 진행한다.

## 2. 범위와 비범위

### 포함

- 고지서 상담의 서버 소유 필수 슬롯과 누락 질문 계약
- 법령 검색 결과와 독립적인 고지서 누락 슬롯 질문
- 고지서 첨부의 scan→분류→분류 확인→OCR→OCR 필드 확인→분석 상태 계약
- partial/failed 첨부 흐름의 안전한 다음 행동과 제한된 재시도 안내
- Supervisor의 `fact_conflicts` strict output 계약
- 동일 메시지 내 상충 사실 보존과 충돌 필드만 재질문
- 공개 API와 UI의 법령·OCR·저장소 정보 최소 공개 projection
- ID 3·4·9·11·13 및 안전 회귀 ID 6·7 자동 테스트

### 제외

- 일반 Worker polling timeout, 재기동 continuity, correlation UX 재설계
- 범용 job 상태 체계 변경
- 새로운 OCR 엔진, 법령 RAG, 과실 산정 모델 도입
- 운영 배포와 실제 13개 E2E 실행
- DB `UploadedFileStatus`의 의미 변경 또는 새 migration

제외 항목 중 polling·부분 실패 UX는 G5, 전체 회귀는 G6, 운영 배포와 실제
13개 E2E는 G7~G9에서 수행한다.

## 3. 구현 전략

G4를 다음 세 체크포인트로 나누고 각 체크포인트를 독립적으로 테스트하고
검토한다.

1. **G4-A / HFX-014:** 고지서 접수 슬롯과 안전한 법령 공개 응답
2. **G4-B / HFX-015:** 첨부 handoff 상태와 UI 표시
3. **G4-C / HFX-016:** Supervisor 상충 진술 계약

세 체크포인트는 같은 브랜치와 작업트리에서 순서대로 진행한다. 각 단계는
실패 테스트, 최소 구현, 집중 회귀, diff 검토의 순서를 지킨다. 최종 G4
게이트는 세 단계의 계약과 ID 6·7 안전 회귀를 함께 검증한다.

## 4. G4-A — 고지서 접수 계약

### 4.1 서버 소유 슬롯

고지서 상담의 필수 슬롯은 다음 네 개로 고정한다.

| 필드 | 의미 | 값이 없을 때 질문 |
|---|---|---|
| `document_disposition_type` | 문서명 또는 처분 유형 | 받은 문서의 이름 또는 처분 유형 |
| `issuing_authority` | 발급기관 | 고지서를 발급한 기관 |
| `response_deadline` | 의견제출·이의신청 기한 | 고지서에 적힌 제출 기한 |
| `attachment_available` | 고지서 사진·파일 첨부 가능 여부 | 사진이나 파일을 첨부할 수 있는지 |

슬롯 값은 사용자가 직접 제공했거나 사용자가 확인한 OCR 필드에서만 채운다.
오타 교정은 intent 판단에만 사용하며 기관, 처분 유형, 날짜를 새로 만들어
슬롯에 넣지 않는다. `attachment_available`도 실제 첨부 존재 또는 사용자의
명시적 답변으로만 확정한다.

### 4.2 질문과 라우팅

- `fine_notice_procedure`와 `fine_notice_analysis` 모두 같은 슬롯 계약을 사용한다.
- 법령 검색이 성공, partial, empty, failed 중 어느 상태여도 누락 슬롯 질문을
  응답의 `pending_questions`에 유지한다.
- 한 응답에서 같은 필드를 중복 질문하지 않는다.
- ID 3은 네 필드가 모두 없으므로 문서명·발급기관·기한·사진 요청을 모두
  포함한다.
- ID 9는 입력 이해도 gate가 제거한 욕설을 어떤 공개 응답에도 반복하지 않고
  ID 3과 같은 슬롯 수집 흐름을 유지한다.
- ID 11은 오타를 허용해 `fine_notice_procedure`로 라우팅하지만 기한이
  지났다고 판단하거나 처분 유형을 추측하지 않는다.

### 4.3 법령 공개 projection

법령 Agent와 내부 보고 단계는 검증과 추적을 위해 기존 내부 근거를 사용할 수
있다. 사용자에게 반환되는 고지서 법령 항목은 다음 값만 허용한다.

- `law_name`
- `article`
- `summary`: 검증된 짧은 요약, 최대 240자

공개 고지서 응답에서는 다음 값을 제거한다.

- `provision_text`
- raw OCR text
- RAG chunk 본문과 내부 retrieval metadata
- private storage URI와 signed URL
- 파일 시스템 경로
- 직접 연락처, 주민번호, 면허번호 등 PII

`summary`가 검증된 법령 결과에 없으면 `provision_text`를 그대로 대신 보여주지
않고 요약을 생략한다. 내부 evidence reference는 서버 저장과 감사 추적에는
남길 수 있지만 법령 카드 본문에는 표시하지 않는다.

## 5. G4-B — 첨부 handoff 계약

### 5.1 상태 모델

기존 `UploadedFileStatus`는 저장·악성코드 검사 상태이므로 변경하지 않는다.
대신 공개 응답에 별도 `attachment_workflow` 객체를 제공한다.

```json
{
  "contract_version": "attachment_workflow.v1",
  "attachment_id": "att_...",
  "state": "classified_waiting_confirmation",
  "next_action": "confirm_classification",
  "retryable": false,
  "missing_fields": [],
  "limitations": []
}
```

허용 상태와 의미는 다음과 같다.

| 상태 | 의미 | 사용자 행동 |
|---|---|---|
| `scan_running` | 업로드 파일 안전 검사 중 | 대기 |
| `classification_running` | 서버가 문서 종류 분류 중 | 대기 |
| `classified_waiting_confirmation` | 분류 결과를 사용자가 확인해야 함 | 분류 확인 |
| `ocr_running` | 확인된 고지서에 대해 OCR 진행 중 | 대기 |
| `ocr_needs_confirmation` | 추출 필드를 사용자가 확인·수정해야 함 | OCR 필드 확인 |
| `analysis_ready` | 확인된 OCR 필드로 고지서 분석 가능 | 분석 결과 확인 |
| `partial` | 일부 정보만 확보됨 | 누락 정보 보완 또는 허용된 재시도 |
| `failed` | 현재 단계 완료 불가 | 안전한 다음 행동 또는 허용된 재시도 |

상태는 서버가 현재 파일 snapshot, 분류 확인 기록, OCR 결과와 사용자 확인을
조합해 계산한다. 클라이언트는 `attachment_id`와 확인 의사만 보내며 분류
종류나 workflow state를 임의로 지정하지 못한다.

### 5.2 전이 규칙

1. clean scan 전에는 분류와 OCR을 실행하지 않는다.
2. 분류 결과는 현재 scan snapshot에 결합한다.
3. 분류 확인 전에는 OCR을 실행하지 않는다.
4. 고지서가 아닌 것으로 확인된 자료는 fine notice OCR로 보내지 않는다.
5. OCR 필드 확인 전에는 법령 검색, appeal 판단, report 생성을 허용하지 않는다.
6. 확인된 OCR 필드와 텍스트 접수 슬롯을 병합하되 사용자가 직접 입력한 확인
   값이 우선한다.
7. 분석 응답은 확인 정보, 누락 정보, 검증된 근거, 한계를 함께 반환한다.
8. report 요청은 필수 OCR 확인과 기존 report readiness gate가 모두 통과한
   경우에만 활성화한다.

### 5.3 partial·failed 처리

- 오류 응답에는 allowlist 기반 공개 `error_code`만 포함한다.
- `partial`은 이미 확보한 정보를 버리지 않고 `missing_fields`,
  `limitations`, `next_action`을 반환한다.
- `retryable=true`는 동일 단계의 재실행이 idempotent하고 추가 유료 호출 또는
  중복 저장 위험이 없을 때만 허용한다.
- 재시도할 수 없는 실패는 파일 재첨부, 분류 재실행, 필드 직접 입력 중 정확히
  하나 이상의 안전한 다음 행동을 제공한다.
- G4에서는 이 도메인 상태를 표시하지만 범용 polling 시간 제한과 백엔드
  재기동 복구 방식은 변경하지 않는다.

### 5.4 UI

UI는 `attachment_workflow.state`를 로컬 추론하지 않고 그대로 사용한다.
각 상태는 서로 다른 사용자 문구와 행동 버튼을 표시한다.

- 분류 확인 카드와 OCR 확인 카드는 동시에 표시하지 않는다.
- pending 상태에서는 아직 분석이 끝났다는 문구를 표시하지 않는다.
- `partial`과 `failed`는 누락 정보·한계와 다음 행동을 숨기지 않는다.
- 공개 UI에는 storage URI, 로컬 경로, raw OCR을 렌더링하지 않는다.

### 5.5 합성 fixture

ID 4 테스트에는 실제 고지서 형태를 모사한 합성 fixture를 사용한다. fixture는
가상의 발급기관, 처분명, 제출 기한과 비식별 사건번호만 포함하고 실존 인물,
전화번호, 주소, 차량번호, 주민번호를 포함하지 않는다. 테스트는 분류 결과를
무조건 신뢰하지 않고 사용자 확인 단계가 존재하는지 검증한다.

## 6. G4-C — 상충 진술 계약

### 6.1 Supervisor strict output

Supervisor conversation schema에 `fact_conflicts` 배열을 추가한다. 각 항목은
다음을 포함한다.

```json
{
  "field": "signal_priority",
  "candidates": [
    {
      "value": "사용자는 녹색 신호에 직진했다고 진술",
      "source_message_id": "msg_...",
      "confidence": 0.9
    },
    {
      "value": "블랙박스상 빨간불 진입으로 보일 가능성을 진술",
      "source_message_id": "msg_...",
      "confidence": 0.8
    }
  ]
}
```

- `field`는 `CORE_FACT_QUESTIONS`에 정의된 필드만 허용한다.
- 후보는 원문 전체가 아니라 해당 사실을 설명하는 최소 문장으로 제한한다.
- confidence는 0.0 이상 1.0 이하의 수치로 정규화한다.
- 같은 메시지에서 나온 후보도 서로 다른 값이면 충돌로 보존한다.
- 충돌 필드는 일반 `collected_facts`의 확정값으로 승격하지 않는다.

### 6.2 reducer와 질문

- 서버 reducer가 `fact_conflicts`를 검증하고 기존 conflict fact card 형식으로
  정규화한다.
- 충돌이 없는 수집 완료 필드는 그대로 유지한다.
- 누락 필드 질문보다 명시적 충돌 해소 질문을 우선한다.
- ID 13에서는 `vehicle_actions`를 다시 묻지 않고 `signal_priority`만
  재질문한다.
- 질문은 어떤 진술이 맞는지와 확인 가능한 영상·자료가 있는지를 묻되 한쪽을
  사실로 단정하지 않는다.

### 6.3 판단 차단

하나 이상의 material conflict가 있으면 다음을 금지한다.

- 과실비율 숫자 또는 범위 출력
- text/ML case search를 근거로 한 최종 과실 판단
- 사실 확정 상태로 case promotion

응답은 충돌 사실 카드, 출처, confidence, 한계, 충돌 필드 재질문을 유지한다.
사용자가 후속 답변으로 충돌을 해소하기 전에는 분석 준비 상태로 전환하지 않는다.

## 7. 데이터 흐름

### 텍스트 고지서

1. 입력 개인정보·이해도 gate
2. 고지서 intent 라우팅
3. 고지서 슬롯 추출과 누락 계산
4. 허용된 경우 법령 검색
5. 법령 공개 projection
6. 답변과 누락 슬롯 질문 병합

### 첨부 고지서

1. 업로드와 scan snapshot 생성
2. 문서 분류와 서버 기록
3. 사용자 분류 확인
4. 고지서 OCR
5. 사용자 OCR 필드 확인
6. 고지서 슬롯 병합
7. 법령·appeal 분석
8. 공개 projection과 report gate

### 상충 사고 진술

1. 입력 개인정보·이해도 gate
2. 사고 intent 라우팅
3. Supervisor fact candidate와 conflict 추출
4. 서버 reducer 검증
5. fact card와 readiness 계산
6. 충돌 필드 재질문, 분석 실행 차단

## 8. 테스트 설계

### G4-A

- 네 필수 슬롯의 순서와 질문 문구 계약
- 법령 검색 success·partial·empty·failed 모두에서 누락 질문 유지
- ID 3 exact input에 문서명·발급기관·기한·첨부 질문 존재
- ID 9 exact input에서 욕설 비노출과 동일 intake 유지
- ID 11 exact input에서 오타 허용, 임의 기한·기관·처분 추론 없음
- public 법령 항목에서 raw 필드와 private reference 비노출

### G4-B

- 허용 상태와 불법 상태 전이의 pure contract test
- 현재 clean snapshot에 결합된 분류만 확인 가능
- 분류 확인 전 OCR 차단
- OCR 확인 전 law/appeal/report 차단
- ID 4 합성 fixture의 전체 handoff
- 각 상태별 API와 UI 렌더링 계약
- partial/failed의 next action과 retryable 계약
- raw OCR, private storage path, PII 비노출

### G4-C

- strict schema의 `fact_conflicts` 필수 배열 계약
- same-message `signal_priority` 충돌 보존
- 충돌 후보의 source와 confidence 유지
- 이미 수집된 `vehicle_actions` 재질문 없음
- 충돌 필드만 재질문
- ID 13 exact input에서 과실 숫자와 분석 실행 0건

### G4 통합 게이트

- ID 3·4·9·11·13 exact-input 테스트
- ID 6·7 안전 회귀
- 관련 Python·Django·Node 테스트
- 전체 Node 테스트와 Vite production build
- 관련 전체 Python suite
- `git diff --check`

## 9. 커밋과 검토 경계

권장 커밋 경계는 다음과 같다.

1. `fix: enforce fine notice intake contracts`
2. `fix: expose safe attachment workflow states`
3. `fix: preserve supervisor fact conflicts`

각 커밋 전 집중 테스트와 diff review를 완료한다. 전체 G4 검증이 끝난 후에도
G5 polling 변경을 섞지 않는다. stage, commit, push는 사용자가 실행하는 현재
협업 방식을 유지한다.

## 10. 완료 조건

다음 조건을 모두 만족해야 G4를 검증 완료로 전환한다.

- ID 3·4·9·11·13 통과
- ID 6·7 안전 회귀 통과
- 첨부 상태별 API·UI contract 통과
- raw OCR·private storage path·PII 공개 노출 0건
- 충돌 해소 전 과실 숫자 0건
- G4 변경으로 발생한 테스트 실패 0건
- 마스터 체크리스트에 명령, 통과 수, warning, 남은 운영 검증 기록
