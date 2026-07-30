# 교통사고사실확인원 OCR → 과실비율 RAG 선택적 연결 설계

## 목적

교통사고사실확인원 OCR 결과가 있으면 과실비율 에이전트의 검색·쟁점 추출 입력을 보강하고, OCR 결과가 없거나 일부 필드가 누락되거나 OCR이 실패해도 과실비율 에이전트는 기존 사용자 사고 설명으로 독립 실행한다.

두 에이전트는 각각 표준 결과 봉투를 Supervisor에 반환하며, OCR은 과실비율 분석의 필수 선행 조건이 아니다.

## 검토한 접근

### 1. 공통 Supervisor 결과 스키마 변경

모든 에이전트가 공유하는 `upstream_results` 구조에 OCR 전용 필드를 추가할 수 있다. 하지만 다른 RAG와 공통 계약에 영향을 주고 현재 진행 중인 RAG 업그레이드와 충돌할 가능성이 커서 채택하지 않는다.

### 2. 과실비율 에이전트 전용 입력 어댑터 추가 — 채택

`text_ml_case_search` 어댑터가 기존 `context.ocr_evidence`를 우선 사용하고, 값이 없을 때만 `upstream_results.traffic_accident_confirmation_ocr.structured_result.extracted_fields`를 과실비율 에이전트의 `ocr_evidence` 형식으로 변환한다.

기존 공통 결과 봉투와 다른 RAG는 변경하지 않으며, OCR이 없으면 현재 실행 경로가 그대로 유지된다.

### 3. OCR 결과를 사용자 질의 문자열에만 합치기

수정 범위는 작지만 구조화된 OCR 필드를 잃고, 기존 `ocr_evidence` 기반 쟁점 추출과 검색문 생성 기능을 활용하지 못하므로 채택하지 않는다.

## 데이터 흐름

OCR 성공 또는 부분 성공 시:

```text
traffic_accident_confirmation_ocr
  structured_result.extracted_fields
    accident_datetime
    accident_location
    accident_type.value
    accident_cause
    accident_description
        ↓ 전용 변환
text_ml_case_search
  ocr_evidence
    accident_datetime
    accident_location
    accident_type
    accident_cause
    accident_description
        ↓
정규화·쟁점 태깅·RAG 검색문 보강
```

OCR이 없거나 실패한 경우:

```text
사용자 query_text / 사고 설명
        ↓
text_ml_case_search 독립 실행
        ↓
Supervisor에 과실비율 분석 결과 반환
```

## 입력 우선순위

1. `context.ocr_evidence`에 직접 전달된 구조화 값
2. `upstream_results.traffic_accident_confirmation_ocr.structured_result.extracted_fields`
3. 둘 다 없으면 `ocr_evidence=None`

직접 전달된 값은 호출자가 명시적으로 확정한 입력으로 간주해 upstream OCR보다 우선한다. 두 소스를 섞어 필드별 병합하지 않아 출처와 우선순위를 명확하게 유지한다.

## 검색 질의 정책

- 사용자 사고 설명이 있으면 기존 질의를 유지하면서 OCR 값은 `ocr_evidence` 섹션으로 보강한다.
- 사용자 사고 설명이 없고 OCR `accident_description`이 있으면 이를 `query_text`의 대체값으로 사용한다.
- `accident_description`이 없으면 `accident_type`, `accident_cause`, `accident_location`, `accident_datetime`의 비어 있지 않은 값으로 대체 질의를 만든다.
- OCR에서 누락된 값은 추측하거나 빈 문자열로 채우지 않는다.

## 상태 및 오류 처리

- OCR `success`: 비어 있지 않은 추출값을 과실비율 입력으로 사용한다.
- OCR `partial`: 추출된 값만 사용하며 누락값 때문에 과실비율 실행을 중단하지 않는다.
- OCR `failed` 또는 결과 없음: OCR 입력 없이 과실비율 실행을 계속한다.
- OCR도 자신의 `success|partial|failed` 결과 봉투를 Supervisor에 독립적으로 반환한다.
- 과실비율 에이전트의 상태는 OCR 상태를 그대로 상속하지 않고 자체 검색 결과와 필수 입력 충족 여부로 결정한다.

## 라우팅

기존 OCR 단독 요청은 `traffic_accident_confirmation_ocr` 경로를 유지한다.

OCR 문서를 활용한 과실비율 분석 경로에서는 실행 계획이 다음 순서를 보장해야 한다.

```text
input_context_validation
→ traffic_accident_confirmation_ocr
→ text_ml_case_search
→ agent_result_validation
→ final_response_merge
```

`text_ml_case_search`는 이 복합 경로에서 OCR 노드를 `depends_on`으로 갖는다. 다만 OCR 결과가 `partial` 또는 `failed`여도 실행 자체가 완료되어 표준 결과 봉투가 생성되면 과실비율 노드는 계속 진행한다.

## 출력 계약

이번 연결에서는 과실비율 에이전트의 기존 출력 스키마를 변경하지 않는다. OCR 결과 원문은 OCR 에이전트 출력에 남고, 과실비율 에이전트는 가공된 `normalized_description`, `issue_tags`, `similar_cases`, `ratio_range_label`, `recommended_evidence` 등을 반환한다.

OCR 사용 내역을 과실비율 출력에 중복 보존하는 기능은 이번 범위에서 제외한다.

## 테스트

1. 직접 전달된 `context.ocr_evidence`가 upstream OCR보다 우선하는지 확인한다.
2. 직접 OCR 입력이 없을 때 upstream `extracted_fields`가 `ocr_evidence`로 변환되는지 확인한다.
3. 중첩된 `accident_type.value`가 문자열 `accident_type`으로 평탄화되는지 확인한다.
4. OCR `accident_description`이 검색문과 쟁점 추출에 반영되는지 확인한다.
5. 사용자 질의가 없을 때 OCR 사고내용으로 과실비율 분석이 실행되는지 확인한다.
6. OCR 결과 없음·실패·부분 누락 시 기존 사용자 질의 기반 분석이 계속되는지 확인한다.
7. 기존 과실비율 에이전트 테스트와 Supervisor 실행 계획 테스트를 회귀 실행한다.

## 변경 범위

- `ai/agents/text_ml_case_search/agent.py`: upstream OCR 변환 및 선택적 질의 대체
- 과실비율 어댑터 테스트: OCR 있음/없음/부분 결과/우선순위 검증
- Supervisor 라우팅 또는 복합 분석 계획: OCR 후 과실비율 노드가 실행되는 경로 추가
- Supervisor 계획 테스트: 노드 순서와 의존성 검증

다른 RAG 구현, 공통 `upstream_results` 계약, OCR 추출 스키마, 과실비율 출력 스키마는 변경하지 않는다.
