# Supervisor 입력 정규화 정책 설계

> 작성일: 2026-08-03  
> 상태: 사용자 승인 설계  
> 대상: 사고 과실상담, 과태료·범칙금, 의견제출·이의신청

## 1. 목적

Supervisor가 채팅 원문에서 각 Agent의 input schema에 필요한 사실과 쟁점을 만들 때
오탈자, 띄어쓰기, 조사·어미, 구어체 때문에 값을 놓치거나 잘못 확정하지 않도록 한다.
프롬프트의 자유로운 해석에 의존하지 않고, 버전이 있는 제한 도메인 규칙을 결정적으로
적용한다.

이 계층은 사용자 문장의 법률적 결론을 판단하지 않는다. 사고 사실, 고지서 정보,
사용자가 원하는 절차, 다투는 사실과 검색 쟁점만 구조화한다.

## 2. 범위

### 2.1 사고 과실상담

- `road_layout`
- `vehicle_actions.self`
- `vehicle_actions.other`
- `signal_priority`
- `collision_location`

### 2.2 과태료·범칙금

- `fine_type`
- `notice_stage`
- `issuing_authority`
- `notice_date`
- `due_date`
- `amount`
- `alleged_violation`

### 2.3 의견제출·이의신청

- `requested_action`
- `disputed_facts`
- `objection_reason`
- `evidence_references`
- `deadline_clarification_required`
- `legal_issue_terms`

### 2.4 제외 범위

- 일반 한국어 전체에 대한 범용 형태소 분석
- 교통 이외 법률 분야
- 위법 여부, 과실비율, 승소 가능성의 자동 판단
- 확인되지 않은 법령명·조문·판례 생성
- OCR 원문 또는 LLM 후보를 사용자 확정값보다 우선하는 처리

## 3. 아키텍처

```text
사용자 입력
→ 기존 개인정보·입력 유효성 검사
→ 제한 도메인 입력 정규화
→ Supervisor 사실 병합
→ Supervisor 라우팅
→ 각 Agent input schema
```

정규화 계층은 다음 세 부분으로 구성한다.

1. 사람용 Wiki MD
   - `docs/policies/supervisor-input-normalization/` 아래에 공통, 사고,
     과태료·범칙금, 이의신청 문서를 분리한다.
   - 규칙의 목적과 용어 정의
   - 정상 표현, 오탈자, 구어체, 부정·불확실 표현 예시
   - 자동 교정 금지 사례
2. 실행용 JSON 정책
   - `app/config/supervisor_input_normalization_policy.v1.json`을 단일 실행 기준으로 둔다.
   - 계약 버전
   - 도메인별 허용 schema와 field
   - 정규 표현, 유사어, 승인된 오탈자, 조사·어미
   - 정규화 값과 교정 수준
3. 결정적 정규화 서비스
   - `app/services/supervisor_input_normalization_service.py`가 정책을 검증하고 적용한다.
   - 외부 LLM을 호출하지 않는다.
   - JSON 정책에 있는 값만 schema 후보로 생성한다.
   - 원문 근거 구간, 적용 규칙, 신뢰도와 처리 상태를 반환한다.

기존 `input_understanding_gate.v1` 뒤, Supervisor LLM과 사실 병합 앞에 정규화
서비스를 둔다. 민감정보가 차단 또는 제거된 입력만 정규화한다.

## 4. 공개 계약

정규화 결과 계약은 `normalized_supervisor_input.v1`로 고정한다.

```json
{
  "contract_version": "normalized_supervisor_input.v1",
  "policy_version": "supervisor_input_normalization_policy.v1",
  "candidates": [
    {
      "domain": "fine_notice",
      "schema": "fine_notice_intake",
      "field": "notice_stage",
      "value": "first_notice",
      "source_span": {"start": 0, "end": 7},
      "source_text": "1챠 고지서",
      "normalized_expression": "1차 고지서",
      "rule_id": "fine_notice.notice_stage.first_notice.typo_01",
      "confidence": 0.99,
      "decision": "auto_applied",
      "negated": false,
      "uncertain": false
    }
  ],
  "clarifications": []
}
```

`source_text`는 기존 안전 입력의 일부만 가리킨다. 운영 로그에는 원문이나
`source_text`를 기록하지 않고 `policy_version`, `rule_id`, `domain`, `field`,
`decision`만 기록한다.

## 5. 처리 순서

1. Unicode와 공백을 정규화하되 원문 인덱스 대응을 유지한다.
2. 문장부호, 줄바꿈, 접속 표현을 기준으로 문장 구간을 나눈다.
3. 짧은 토큰보다 등록된 긴 도메인 표현을 우선 탐색한다.
4. 정책에 등록된 조사·어미를 분리한다.
5. 표현을 `entity`, `action`, `state`, `modifier`, `negation`,
   `uncertainty`, `particle`로 분류한다.
6. 정확한 표현, 승인된 유사어, 승인된 오탈자 순으로 매칭한다.
7. 등록되지 않은 가까운 표현은 단일 후보일 때만 확인 후보로 만든다.
8. 부정과 불확실성 범위를 적용한다.
9. 허용된 schema·field·value인지 검증한다.
10. 신뢰도와 의미 변경 위험에 따라 자동 적용, 사용자 확인, 재질문으로 나눈다.

일반 형태소 분석 라이브러리는 추가하지 않는다. 교통분쟁 정책에 등록된 의미 단위만
분리하며, 범용 문법 분석 결과를 성공 조건으로 삼지 않는다.

## 6. 교정 및 확인 정책

### 6.1 자동 적용

- 등록된 정확한 표현
- 등록된 유사어
- 정책에서 명시적으로 승인된 오탈자
- 후보가 하나이며 법적 단계나 사실 의미를 바꾸지 않는 경우

자동 적용하더라도 원문 근거, 정규화 표현, `rule_id`를 보존한다.

### 6.2 사용자 확인

- 정책에 없는 표현이 한 개의 등록 용어와 충분히 가까운 경우
- 구어체를 정규 schema 값으로 바꾸면서 의미가 축약되는 경우
- 주체가 본인 차량인지 상대 차량인지 문맥 확인이 필요한 경우

### 6.3 재질문

- 후보가 여러 개인 경우
- 과태료와 범칙금, 사전통지와 부과처럼 법적 단계가 달라질 수 있는 경우
- 금액·날짜·차량 행동을 추측해야 하는 경우
- 부정 범위 또는 불확실성 범위를 안전하게 결정할 수 없는 경우

## 7. 사실 우선순위와 충돌

```text
사용자가 직접 확정한 값
> 확인된 OCR·공식 문서 사실
> 높은 신뢰도의 규칙 정규화값
> LLM이 제안한 미확정 후보
```

이 순서는 자동 병합 우선순위다. 확인된 공식 문서와 사용자의 확정 진술이 서로
다르면 우선순위만으로 한쪽을 폐기하지 않고 아래 충돌 규칙을 적용한다.

- 정규화 후보는 사용자 확정값을 덮어쓰지 않는다.
- 확인된 공식 문서와 사용자 진술이 다르면 한쪽을 선택하지 않고 충돌로 보존한다.
- 미확정 LLM 후보와 사용자 후속 확정 답변이 다르면 사용자 답변을 우선한다.
- `좌회전하지 않았다`는 `left_turn` 확정값으로 승격하지 않는다.
- `좌회전한 것 같다`는 불확실 후보로 남긴다.

## 8. Supervisor와 Agent 연결

- Supervisor 라우팅은 정규화된 도메인 후보를 참고하되 기존 첨부 목적과 명시적
  사용자 요청의 우선순위를 유지한다.
- 사실 병합기는 `auto_applied` 후보만 미확정 규칙 사실로 받을 수 있다.
- `confirmation_required`와 `clarification_required` 후보는 Agent input schema로
  전달하지 않는다.
- 법령 Agent에는 확정 사실과 `legal_issue_terms`만 전달한다.
- 정규화 계층은 법령명, 조문, 법적 결론을 생성하지 않는다.
- LLM 후보는 정책에 정의된 schema·field·value allowlist를 통과해야 하며,
  통과하더라도 미확정 후보로만 취급한다.

## 9. 오류 처리와 개인정보

- 정책 파일 누락, 계약 버전 불일치, 중복 `rule_id`, 미등록 schema·field·value는
  테스트 또는 서버 시작 시 실패시킨다.
- 런타임 정규화 오류가 발생하면 원문 상담은 유지하되 자동 schema 입력을 중단한다.
- 허용되지 않은 값은 조용히 통과시키지 않고 재질문 대상으로 만든다.
- 운영 로그에는 사용자 원문, OCR 원문, 금액, 날짜, 개인식별정보를 기록하지 않는다.
- 관측 정보는 정책 버전, 규칙 ID, 처리 상태, 필드명, 오류 코드로 제한한다.

## 10. Wiki와 정책 변경 규칙

- Wiki MD는 사람이 검토하는 설명서다.
- JSON 정책이 실행의 유일한 기준이다.
- 정책 변경 시 계약 또는 정책 버전을 증가시킨다.
- Wiki 예시와 회귀 테스트를 같은 변경에 포함한다.
- 문서와 JSON이 충돌하면 서버는 JSON을 적용하며 테스트가 문서 불일치를 탐지한다.
- 운영 중 동적 편집이나 관리자 UI는 이번 범위에 포함하지 않는다.

## 11. 테스트 전략

### 11.1 규칙 단위 테스트

- 정확한 표현, 조사·어미, 띄어쓰기, 구어체
- 승인된 오탈자와 미등록 유사 표현
- 부정, 불확실성, 복수 후보
- 주체 구분과 긴 표현 우선 매칭

### 11.2 Supervisor 병합 테스트

- 규칙 후보가 사용자 확정값을 덮지 않는다.
- 확인이 필요한 후보가 Agent에 전달되지 않는다.
- 공식 문서와 사용자 진술의 충돌을 보존한다.
- 확정 후속 답변이 미확정 LLM 후보보다 우선한다.

### 11.3 Agent 계약 테스트

- 사고, 과태료·범칙금, 이의신청 schema에 허용값만 전달한다.
- 법령 Agent에는 확정 사실과 검색 쟁점만 전달한다.
- 미등록 field와 value는 fail-closed 처리한다.

### 11.4 회귀와 빌드

- 전체 Python 회귀
- Django chatbot 회귀
- 프론트엔드 테스트와 프로덕션 빌드
- 정책 파일 패키징 및 운영 이미지 포함 여부 검증

## 12. 실제 파일 및 브라우저 완료 기준

구현과 로컬 회귀, 프로덕션 빌드가 완료된 뒤 사용자가 제공한 사실확인원과
과태료 고지서 파일을 실제 배포 브라우저에 업로드한다.

```text
OCR
→ 입력 정규화
→ 사용자 사실 확인
→ case_ready
→ 사건 생성
→ 사실 확정
→ 분석 실행
→ persisted report
→ 이의신청서 초안
```

동일 흐름에서 `확정 사용자 답변 > 미확정 LLM 후보` 핫픽스도 다시 확인한다.
다음 조건을 모두 만족해야 통과로 판정한다.

- 오탈자·구어체가 합의된 3단계 기준으로 처리된다.
- 부정·불확실 표현이 확정 사실로 잘못 승격되지 않는다.
- 법적 단계가 불명확하면 재질문한다.
- 확정 답변이 거짓 충돌 없이 유지된다.
- OCR 근거가 사건에 연결된다.
- 저장된 리포트와 이의신청서 초안이 실제 사건 자료를 사용한다.
- 브라우저와 서버에 처리되지 않은 계약 오류가 없다.

두 검증이 모두 통과하기 전에는 다음 핫픽스로 넘어가지 않는다.

## 13. 구현 경계

- 이 기능은 Supervisor 입력 정규화와 관련 계약·정책·테스트만 변경한다.
- OCR, Vision, RAG, 법률 판단 알고리즘의 내부 동작은 변경하지 않는다.
- 프론트엔드는 확인·재질문 상태를 기존 상담 UI로 표시하는 데 필요한 최소 연결만
  허용한다.
- 제공 파일은 검증 입력으로만 사용하며 저장소에 추가하지 않는다.
