# 교통사고 관련성 1차 분류 계획 및 코드 설명

## 1. 1차 분류의 목적

이 단계의 목적은 전처리와 중복 제거가 끝난 전체 판례 후보 중에서 **교통사고 관련 판례인지 아닌지**를 1차로 나누는 것입니다.

입력 데이터는 이미 다음 처리가 끝난 파일입니다.

```text
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_pre/03_cases_preprocessed.jsonl
```

이 파일은 invalid 분리, 18개 한글 표준 필드 생성, 본문 정리, 중복 제거, 과실비율 후보 추출이 끝난 판례 후보입니다.  
하지만 이 파일은 교통사고 판례만 모아 둔 정답 데이터가 아니라, 수집 키워드에 걸린 전체 후보입니다.

따라서 1차 분류는 다음 질문에 답합니다.

```text
이 판례가 실제 교통사고 관련 판례인가?
```

이 단계는 과실비율 판례를 찾는 단계가 아닙니다.  
과실비율/과실상계/책임비율 판단용 판례인지는 나중에 2차 분류에서 다시 판단합니다.

---

## 2. 코드 파일

1차 분류 코드는 다음 파일입니다.

```text
판례 데이터 1차 분류-교통사고 관련/traffic_relevance_reclassifier_stage1.py
```

기본 실행:

```bash
python "판례 데이터 1차 분류-교통사고 관련/traffic_relevance_reclassifier_stage1.py" --fresh
```

입력과 출력 경로를 직접 지정할 수도 있습니다.

```bash
python "판례 데이터 1차 분류-교통사고 관련/traffic_relevance_reclassifier_stage1.py" \
  --input etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_pre/03_cases_preprocessed.jsonl \
  --out-dir etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_reclass \
  --fresh
```

---

## 3. 입력과 출력

### 3.1 입력 파일

```text
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_pre/03_cases_preprocessed.jsonl
```

이 파일은 전처리 최종 산출물입니다.

### 3.2 출력 폴더

```text
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_reclass/
```

### 3.3 출력 파일

```text
etl/fault_cases/artifacts/traffic_precedents_output/
  traffic_prec_reclass/
    00_traffic_reclass_report.json
    01_confirmed_traffic_cases.jsonl
    02_possible_traffic_review.jsonl
    03_non_traffic_cases.jsonl
    04_traffic_reclassified_all.jsonl
```

| 파일 | 의미 | 다음 처리 |
|---|---|---|
| `00_traffic_reclass_report.json` | 1차 분류 통계와 기준 요약 | 통계 확인 |
| `01_confirmed_traffic_cases.jsonl` | 교통사고 관련성이 충분히 확인된 판례 | reclass 검증/정리 입력 |
| `02_possible_traffic_review.jsonl` | 교통/차량/보험 단서는 있으나 사고 맥락 확정이 필요한 판례 | reclass 검증/정리 입력 |
| `03_non_traffic_cases.jsonl` | 교통사고 관련성이 낮은 판례 | 보관 및 추적 |
| `04_traffic_reclassified_all.jsonl` | 전체 입력에 1차 라벨과 근거를 붙인 파일 | 감사/디버깅 |

---

## 4. 라벨 정의

1차 분류는 row를 다음 세 라벨 중 하나로 분류합니다.

```text
confirmed_traffic
possible_traffic_review
non_traffic
```

### 4.1 confirmed_traffic

`confirmed_traffic`은 교통사고 관련성이 충분히 확인된 판례입니다.

이 라벨은 다음 단계에서 바로 사용할 수 있어야 하므로 precision을 우선합니다.  
즉, 교통 관련 단어가 조금 보인다는 이유만으로 confirmed에 올리지 않습니다.

대표 예시는 다음과 같습니다.

```text
교통사고처리특례법위반(치상/치사) 사건에서 실제 차량 사고가 있는 경우
손해배상(자) 사건에서 차량 충돌, 피해자 상해/사망, 보험/손해배상 문맥이 있는 경우
구상금 사건에서 자동차 사고와 보험자 구상 문맥이 함께 있는 경우
차량, 보행자, 운전자 등 사고 주체와 충돌/추돌/들이받음 등 사고 행위가 가까이 나오는 경우
```

### 4.2 possible_traffic_review

`possible_traffic_review`는 교통사고 관련 가능성은 있지만 바로 confirmed로 확정하기 어려운 판례입니다.

이 라벨은 버리는 라벨이 아닙니다.  
나중에 reclass 검증/정리 단계에서 다시 확인하여, 강한 교통사고 판례는 confirmed로 올릴 수 있습니다.

대표 예시는 다음과 같습니다.

```text
도로교통법위반, 음주운전, 면허취소 단어는 있으나 실제 사고 문맥이 약한 경우
자동차보험, 구상금, 손해배상 단어는 있으나 교통사고 사실관계가 명확하지 않은 경우
차량/도로/사고 단어는 있으나 판례의 핵심 쟁점이 다른 도메인일 가능성이 있는 경우
본문 품질 문제로 사고 맥락을 확정하기 어려운 경우
```

### 4.3 non_traffic

`non_traffic`은 교통사고 관련성이 낮은 판례입니다.

대표 예시는 다음과 같습니다.

```text
세금, 선거, 특허, 상표, 노동, 의료, 가사 등 비교통 도메인 판례
교통 단어가 일반 예시로만 등장하는 판례
도로, 자동차 같은 단어가 있어도 실제 사고 주체/행위/피해 문맥이 없는 판례
```

---

## 5. 기본 정책

이 코드는 precision-first 기준으로 설계되어 있습니다.

핵심 정책은 다음과 같습니다.

```text
1. confirmed_traffic은 다음 단계에서 바로 사용할 데이터이므로 엄격하게 판단한다.
2. 도로교통법위반, 음주운전, 면허취소 같은 단어만으로는 confirmed_traffic으로 보내지 않는다.
3. confirmed_traffic은 최소 2개 이상의 근거 묶음이 있어야 한다.
4. confirmed_traffic은 교통 관련 키워드가 총 3개 이상 잡혀야 한다.
5. confirmed_traffic에는 직접 사고 표현 또는 강한 사고 근접 문맥이 반드시 있어야 한다.
6. 일반 예시 문구의 교통사고 언급은 confirmed 근거로 쓰지 않는다.
7. 세무/특허/가사 사건종류는 confirmed_traffic으로 바로 보내지 않는다.
8. 애매한 것은 non_traffic으로 바로 버리지 않고 possible_traffic_review로 보낸다.
9. 과실비율 분류는 이 단계에서 하지 않고 다음 단계에서 수행한다.
```

---

## 6. 기준값

코드의 주요 기준값은 다음과 같습니다.

| 기준값 | 값 | 의미 |
|---|---:|---|
| `CONFIRMED_SCORE_THRESHOLD` | 8 | confirmed가 되기 위한 최소 점수 |
| `REVIEW_SCORE_THRESHOLD` | 4 | possible review로 보낼 최소 참고 점수 |
| `MIN_CONFIRMED_SIGNAL_GROUPS` | 2 | confirmed가 되기 위한 최소 근거 묶음 수 |
| `MIN_CONFIRMED_TRAFFIC_TERM_COUNT` | 3 | confirmed가 되기 위한 최소 교통 관련 키워드 수 |
| `NEAR_WINDOW` | 80 | 주체 단어와 사고 행위 단어 사이 근접 허용 거리 |
| `MAX_RECLASS_BODY_CHARS` | 8000 | 분류에 사용할 본문 앞부분 최대 길이 |
| `RECLASS_BODY_TAIL_CHARS` | 2000 | 긴 본문에서 끝부분 보존 길이 |
| `REQUIRE_CORE_ACCIDENT_CONTEXT_FOR_CONFIRMED` | true | confirmed에는 사고 핵심 문맥이 필요 |

---

## 7. 분류에 사용하는 텍스트

각 row에서 다음 텍스트를 모아 분류합니다.

```text
사건명 / case_name
사건번호 / case_number
법원명 / court_name
사건종류명 / case_category
판시사항 / holding
판결요지 / summary
주문
이유
판례내용 / main_text / full_text
참조조문 / referenced_laws
참조판례 / referenced_cases
```

현재 코드는 새 전처리 산출물의 18개 한글 필드를 우선 읽고, 기존 영문 필드가 남아 있는 과거 산출물도 읽을 수 있도록 fallback을 둡니다.

본문이 너무 길면 전체를 다 검색하지 않고 앞부분과 끝부분을 중심으로 봅니다.  
교통사고 관련성 단서는 보통 사건명, 판시사항, 판결요지, 본문 앞부분에 많이 나오기 때문입니다.

---

## 8. 근거 묶음

1차 분류는 단순 키워드 하나로 확정하지 않습니다.  
다음 근거 묶음을 조합해서 판단합니다.

| 근거 묶음 | 의미 | 예시 |
|---|---|---|
| `direct_accident_expression` | 직접 교통사고 표현 | 교통사고, 차량 사고, 추돌사고 |
| `core_actor_action_nearby` | 강한 사고 주체와 강한 사고 행위가 가까이 있음 | 차량 + 충돌, 보행자 + 치어 |
| `traffic_legal_or_insurance_context` | 교통사고 법령/보험/사건명 문맥 | 교통사고처리특례법, 자동차보험, 손해배상(자), 구상금 |
| `traffic_situation_context` | 사고 상황 문맥 | 신호위반, 중앙선 침범, 무단횡단, 전방주시 |
| `fault_or_liability_context` | 과실/책임 문맥 | 과실상계, 과실비율, 손해배상책임, 주의의무 |

confirmed는 보통 이 근거 묶음이 2개 이상 필요합니다.

---

## 9. 강한 사고 근거

confirmed에 중요한 근거는 다음 두 종류입니다.

### 9.1 직접 사고 표현

```text
교통사고
자동차 사고
차량 사고
차량 충돌
자동차 충돌
접촉사고
추돌사고
후미추돌
보행자 사고
횡단보도 사고
자전거 사고
이륜차 사고
오토바이 사고
전동킥보드 사고
개인형 이동장치 사고
```

단, `교통사고처리특례법` 안에 포함된 `교통사고`는 직접 사고 표현이 아니라 법령 문맥으로 봅니다.

### 9.2 강한 사고 근접 문맥

강한 사고 주체와 강한 사고 행위가 가까이 있으면 실제 사고 문맥으로 봅니다.

사고 주체 예시:

```text
자동차
차량
승용차
화물차
버스
택시
오토바이
이륜차
자전거
전동킥보드
보행자
운전자
탑승자
동승자
```

사고 행위 예시:

```text
충돌
추돌
들이받
부딪
치어
치여
전복
전도
역과
```

예를 들면 다음 문장은 강한 사고 근거입니다.

```text
피고 차량이 횡단보도를 건너던 피해자를 들이받았다.
원고 차량과 피고 차량이 교차로에서 충돌하였다.
버스가 보행자를 충격하여 상해를 입게 하였다.
```

---

## 10. 보조 근거

### 10.1 교통 법령/보험 문맥

다음 표현은 중요한 힌트입니다.

```text
교통사고처리특례법
자동차손해배상 보장법
자동차손해배상보장법
자동차손해배상
손해배상(자)
자동차보험
책임보험
종합보험
대인배상
대물배상
운행자책임
보험자대위
구상금
```

다만 이 표현만으로 confirmed가 되지는 않습니다.  
실제 사고 문맥과 결합되어야 합니다.

### 10.2 사고 상황 문맥

```text
신호위반
중앙선 침범
무단횡단
전방주시의무
안전거리
좌회전
우회전
유턴
진로 변경
차로 변경
어린이보호구역
```

이 표현들은 사고 상황을 보조합니다.

### 10.3 과실/책임 문맥

```text
과실비율
과실상계
책임비율
주의의무
안전운전의무
전방주시의무
손해배상책임
손해액
```

이 단계에서는 과실비율 판례인지 확정하지 않습니다.  
이 표현들은 "교통사고와 법적 책임이 연결되어 있는지"를 보조하는 근거로만 사용합니다.

---

## 11. confirmed_traffic 기준

`confirmed_traffic`이 되려면 다음 조건을 모두 만족해야 합니다.

```text
1. traffic_relevance_score >= 8
2. traffic_signal_group_count >= 2
3. traffic_term_count >= 3
4. has_core_accident_context = true
5. generic_traffic_reference_patterns가 없음
6. 사건종류가 세무/특허/가사가 아님
```

즉 점수만 높아서는 confirmed가 될 수 없습니다.  
직접 사고 표현 또는 강한 사고 근접 문맥이 반드시 필요합니다.

confirmed로 보내지 않는 대표 사례:

```text
도로교통법위반 단어만 있는 사건
음주운전 또는 면허취소만 다루는 사건
자동차라는 단어가 세금/취득가액/보험료 계산 예시로만 등장하는 사건
천재지변, 화재, 교통사고처럼 일반 예시 문구로만 등장하는 사건
세무/특허/가사 사건종류
```

---

## 12. possible_traffic_review 기준

confirmed 기준은 부족하지만 교통 관련 단서가 있으면 `possible_traffic_review`로 보냅니다.

조건 예시는 다음과 같습니다.

```text
traffic_relevance_score >= 4
근거 묶음이 1개 이상 있음
교통 법령/보험 표현이 있음
도로교통법위반, 음주운전, 면허취소 등 교통 법규 단어가 있음
직접 사고 표현은 있으나 다른 confirmed 조건이 부족함
강한 사고 근접 문맥은 있으나 근거 묶음/키워드 수가 부족함
```

possible로 보내는 이유는 recall을 보강하기 위해서입니다.  
애매한 판례를 바로 `non_traffic`으로 버리면 이후에 실제 교통사고 판례를 놓칠 수 있습니다.

다만 possible은 최종 confirmed가 아닙니다.  
다음 단계인 `traffic_relevance_recheck.py`에서 다시 검증/정리합니다.

---

## 13. non_traffic 기준

교통사고 관련 근거가 부족하면 `non_traffic`으로 보냅니다.

또한 비교통 도메인 단어가 있고 교통사고 핵심 근거가 부족하면 `non_traffic`으로 강화합니다.

비교통 도메인 예시는 다음과 같습니다.

```text
공직선거법
선거운동
조세
법인세
부가가치세
소득세
근로기준법
임금
퇴직금
산업재해보상보험법
특허
상표
디자인보호법
저작권
의료법
마약류
건축허가
관세법
```

이 단어가 있다고 무조건 non이 되는 것은 아닙니다.  
교통사고 핵심 근거가 충분하면 confirmed 또는 possible로 남을 수 있습니다.

하지만 교통사고 핵심 근거 없이 비교통 도메인 단어만 강하면 non으로 보냅니다.

---

## 14. 일반 예시 문구 제외

다음처럼 실제 사건의 사고가 아니라 일반 예시로 등장하는 표현은 confirmed 근거에서 제외합니다.

```text
천재지변 ... 화재 ... 교통사고
화재 ... 교통사고 ... 도난
사고나 질병
질병 또는 사고
안전사고 예방
교통소통 원활
질서유지
```

이런 표현은 "교통사고"라는 단어가 있어도 실제 교통사고 판례라고 보기 어렵습니다.

---

## 15. 출력 row에 추가되는 필드

각 row에는 다음 필드가 추가됩니다.

```json
{
  "traffic_label": "confirmed_traffic",
  "traffic_relevance_score": 14,
  "traffic_reclass_reasons": [
    "direct_traffic_accident_terms",
    "traffic_legal_or_insurance_terms"
  ],
  "traffic_evidence_terms": [
    "교통사고",
    "손해배상(자)"
  ],
  "traffic_signal_groups": [
    "direct_accident_expression",
    "traffic_legal_or_insurance_context"
  ],
  "traffic_signal_group_count": 2,
  "traffic_term_count": 5,
  "has_core_accident_context": true,
  "generic_traffic_reference_patterns": [],
  "case_category_disallowed_for_confirmed": false
}
```

이 필드들은 나중에 왜 해당 판례가 confirmed, possible, non으로 분류되었는지 검토하기 위해 남깁니다.

---

## 16. 현재 실행 결과

아래 수치는 과거 `database/traffic_prec_reclass/00_traffic_reclass_report.json` 기준 예시입니다.  
현재 기본 입력이 `traffic_prec_pre/03_cases_preprocessed.jsonl`로 바뀌었으므로 재실행 후 새 report 기준으로 다시 확인해야 합니다.

```text
입력 row: 15,520건
confirmed_traffic: 3,207건
possible_traffic_review: 3,355건
non_traffic: 8,958건
skipped_unusable_rows: 0건
```

주요 reason 카운트는 다음과 같습니다.

```text
road_actor_and_accident_action_nearby: 6,801
direct_traffic_accident_terms: 4,136
traffic_legal_or_insurance_terms: 3,076
core_actor_and_strong_accident_action_nearby: 2,609
fault_context_with_traffic_evidence: 2,263
traffic_situation_terms: 1,130
traffic_law_terms_without_accident_context: 418
generic_traffic_reference_pattern_found: 185
case_category_disallowed_for_confirmed: 239
non_traffic_domain_without_enough_traffic_accident_signals: 6,872
```

이 결과에서 바로 과실비율 2차 분류로 가지 않습니다.  
다음 단계에서 `confirmed_traffic`과 `possible_traffic_review`를 다시 검증/정리합니다.

---

## 17. 다음 단계

1차 분류 후 다음 단계는 reclass 검증/정리입니다.

검증/정리 코드는 다음 파일입니다.

```text
traffic_relevance_recheck.py
```

이 단계에서는 다음을 수행합니다.

```text
confirmed_traffic 중 실제 교통사고 판례가 아니면 non_traffic으로 내림
possible_traffic_review 중 실제 교통사고 판례가 확실하면 confirmed_traffic으로 올림
possible_traffic_review 중 confirmed로 올릴 만큼 강하지 않으면 non_traffic으로 보냄
```

검증/정리 후 과실비율 2차 분류에 사용할 파일은 다음입니다.

```text
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_reclass_verified/01_confirmed_traffic_cases.jsonl
```

---

## 18. 전체 흐름

```text
전처리 최종 파일
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_pre/03_cases_preprocessed.jsonl
↓
교통사고 관련성 1차 분류
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_reclass/
  01_confirmed_traffic_cases.jsonl
  02_possible_traffic_review.jsonl
  03_non_traffic_cases.jsonl
↓
reclass 검증/정리
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_reclass_verified/
  01_confirmed_traffic_cases.jsonl
  02_non_traffic_cases.jsonl
↓
과실비율 2차 분류
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_fault_ratio/
```

---

## 19. 하드코딩 여부

이 코드는 특정 판례 ID나 특정 줄 번호를 찍어서 분류하지 않습니다.

없는 것:

```text
case_id가 몇 번이면 confirmed
특정 사건명은 무조건 제외
특정 줄 번호는 삭제
```

있는 것:

```text
교통사고 관련 키워드 사전
교통사고 법령/보험 문맥 사전
사고 주체 + 사고 행위 근접 문맥
비교통 도메인 사전
일반 예시 문구 제외 패턴
점수 기준
근거 묶음 기준
```

즉 특정 데이터 row에 맞춘 하드코딩이 아니라 **규칙 기반 1차 관련성 분류 기준**입니다.
