# 1차 분류 검증 및 재정리 계획

## 1. 문서 목적

이 문서는 `traffic_relevance_recheck.py`의 목적, 입력/출력, 라벨 이동 기준, 근거 필드, 검증 이유를 설명합니다.

이 단계는 1차 교통사고 관련성 분류가 끝난 뒤, 과실비율 2차 분류로 넘어가기 전에 수행하는 **교통사고 관련성 검증 및 재정리 단계**입니다.

질문은 하나입니다.

```text
이 판례가 진짜 교통사고 관련 판례인가?
```

이 단계는 과실비율 판단용 판례인지 여부를 판단하지 않습니다.  
과실비율 판단용 여부는 이후 2차 분류와 2차 검증 단계에서 다시 봅니다.

---

## 2. 코드 파일

검증 코드는 다음 파일입니다.

```text
traffic_relevance_recheck.py
```

기본 실행:

```bash
python traffic_relevance_recheck.py --fresh
```

입력/출력을 직접 지정할 수도 있습니다.

```bash
python traffic_relevance_recheck.py \
  --reclass-dir etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_reclass \
  --out-dir etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_reclass_verified \
  --fresh
```

---

## 3. 왜 1차 검증이 필요한가

1차 분류 결과는 다음 3개 라벨로 나뉩니다.

```text
confirmed_traffic
possible_traffic_review
non_traffic
```

하지만 1차 분류만으로 바로 과실비율 2차 분류에 들어가면 두 문제가 생길 수 있습니다.

첫째, `confirmed_traffic` 안에도 실제 교통사고 판례가 아닌 것이 일부 섞일 수 있습니다.

예시는 다음과 같습니다.

```text
도로교통법위반이지만 실제 사고 피해 판단이 없는 판례
음주운전, 무면허운전, 면허취소, 벌점 중심 판례
공동위험행위, 난폭운전처럼 교통상 위험만 다루고 사고는 발생하지 않은 판례
교통 단어가 법령 설명이나 일반 예시로만 등장하는 판례
```

둘째, `possible_traffic_review` 안에는 실제 교통사고 판례가 숨어 있을 수 있습니다.

예시는 다음과 같습니다.

```text
사건명은 손해배상(자)인데 본문에 실제 사고 경위가 명확한 판례
구상금/보험금 사건인데 차량 충돌, 피해자 상해/사망, 보험자 구상 문맥이 강한 판례
본문에 피고 차량, 피해자, 이 사건 사고, 충격, 부상, 사망이 함께 나오는 판례
```

따라서 이 단계는 2차 과실비율 분류 전에 입력을 다음처럼 정리합니다.

```text
교통사고 관련 판례 confirmed_traffic
교통사고 관련성이 부족한 판례 non_traffic
```

---

## 4. 입력 파일

기본 입력 폴더:

```text
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_reclass/
```

입력 파일:

```text
01_confirmed_traffic_cases.jsonl
02_possible_traffic_review.jsonl
03_non_traffic_cases.jsonl
```

각 파일의 의미는 다음과 같습니다.

| 파일 | 의미 |
|---|---|
| `01_confirmed_traffic_cases.jsonl` | 1차 분류에서 교통사고 관련성이 충분하다고 본 판례 |
| `02_possible_traffic_review.jsonl` | 교통/차량/보험 단서는 있으나 사고 맥락 확정이 필요한 판례 |
| `03_non_traffic_cases.jsonl` | 교통사고 관련성이 낮다고 본 판례 |

---

## 5. 출력 파일

기본 출력 폴더:

```text
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_reclass_verified/
```

출력 파일:

```text
00_traffic_reclass_verification_report.json
01_confirmed_traffic_cases.jsonl
02_non_traffic_cases.jsonl
03_traffic_reclassified_verified_all.jsonl
04_demoted_from_confirmed_to_non_traffic.jsonl
05_promoted_from_possible_to_confirmed.jsonl
06_possible_to_non_traffic.jsonl
```

| 파일 | 의미 | 사용처 |
|---|---|---|
| `00_traffic_reclass_verification_report.json` | 검증/재정리 통계와 기준 요약 | 통계 확인 |
| `01_confirmed_traffic_cases.jsonl` | 최종 교통사고 관련 판례 | 과실비율 2차 분류 입력 |
| `02_non_traffic_cases.jsonl` | 최종 비교통 또는 불충분 판례 | 2차 분류 제외 |
| `03_traffic_reclassified_verified_all.jsonl` | 전체 row에 최종 라벨을 붙인 감사 파일 | 추적/디버깅 |
| `04_demoted_from_confirmed_to_non_traffic.jsonl` | confirmed에서 non으로 내려간 row | 수동 검토 |
| `05_promoted_from_possible_to_confirmed.jsonl` | possible에서 confirmed로 올라간 row | 수동 검토 |
| `06_possible_to_non_traffic.jsonl` | possible에서 non으로 간 row | 보관 |

2차 과실비율 분류에 넣을 파일은 다음 하나입니다.

```text
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_reclass_verified/01_confirmed_traffic_cases.jsonl
```

`03_traffic_reclassified_verified_all.jsonl`은 전체 추적용이지 2차 분류 입력이 아닙니다.

---

## 6. 최종 라벨 구조

검증 후에는 중간 라벨인 `possible_traffic_review`를 남기지 않습니다.

최종 라벨은 다음 두 개입니다.

```text
confirmed_traffic
non_traffic
```

라벨 이동 규칙은 다음과 같습니다.

| 원본 라벨 | 조건 | 최종 라벨 |
|---|---|---|
| `confirmed_traffic` | 교통사고 판례 근거가 충분함 | `confirmed_traffic` |
| `confirmed_traffic` | 교통사고 판례 근거가 약함 | `non_traffic` |
| `possible_traffic_review` | 강한 교통사고 판례 근거가 있음 | `confirmed_traffic` |
| `possible_traffic_review` | confirmed로 올릴 만큼 강하지 않음 | `non_traffic` |
| `non_traffic` | 별도 재검토 없음 | `non_traffic` |

---

## 7. 검증에 사용하는 기존 근거 필드

이 단계는 1차 분류가 각 row에 붙인 근거 필드를 다시 사용합니다.

또한 원본 판례 텍스트를 다시 확인할 때는 새 전처리 산출물의 한글 필드를 우선 사용하고, 기존 영문 필드를 fallback으로 사용합니다.

```text
사건명 / case_name
판시사항 / holding
판결요지 / summary
주문
이유
판례내용 / main_text / full_text
```

| 필드 | 의미 |
|---|---|
| `traffic_relevance_score` | 1차 교통사고 관련성 점수 |
| `traffic_signal_groups` | 근거 묶음 |
| `traffic_signal_group_count` | 근거 묶음 개수 |
| `traffic_term_count` | 교통 관련 키워드 개수 |
| `traffic_reclass_reasons` | 1차 분류 이유 |
| `traffic_evidence_terms` | 실제 잡힌 근거 표현 |
| `has_core_accident_context` | 직접 사고 표현 또는 강한 사고 근접 문맥 여부 |
| `has_traffic_legal_plus_accident_context` | 법령/보험 문맥과 사고 문맥 결합 여부 |
| `non_traffic_domain_terms` | 비교통 도메인 단어 |
| `traffic_law_only_terms` | 사고 없는 교통법규 중심 단어 |

---

## 8. 검증 후 추가 필드

검증 후 row에는 다음 필드를 추가합니다.

| 필드 | 의미 |
|---|---|
| `traffic_label_before_verification` | 검증 전 라벨 |
| `traffic_verification_source_label` | 원본 입력 라벨 |
| `traffic_verification_final_label` | 검증 후 최종 라벨 |
| `traffic_verification_decision_reasons` | 최종 라벨로 보낸 이유 |

이 필드는 나중에 "왜 이 판례가 올라갔는지/내려갔는지"를 추적하기 위한 감사 필드입니다.

---

## 9. 강한 교통사고 근거

다음 중 하나가 있으면 강한 사고 신호로 봅니다.

```text
direct_traffic_accident_terms
road_actor_and_accident_action_nearby
core_actor_and_strong_accident_action_nearby
direct_accident_expression
road_actor_action_nearby
core_actor_action_nearby
has_core_accident_context = true
```

의미는 다음과 같습니다.

```text
교통사고, 자동차 사고, 차량 충돌, 추돌사고 같은 직접 사고 표현
차량/도로/보행자/운전자 같은 주체와 충돌/상해/사망/충격 같은 행위가 가까이 나오는 문맥
본문에 실제 사고 발생, 피해자, 가해 차량, 손해 발생이 함께 나타나는 문맥
```

단순히 다음 단어만 있다고 강한 사고 신호로 보지 않습니다.

```text
도로
자동차
운전
교통
차량
```

---

## 10. 보조 교통사고 문맥

강한 사고 신호와 함께 보조 문맥도 봅니다.

```text
traffic_legal_or_insurance_context
fault_or_liability_context
traffic_situation_context
```

예시는 다음과 같습니다.

```text
손해배상
구상금
보험금
자동차손해배상
교통사고처리특례법
주의의무
신호위반
전방주시의무
안전운전의무
과실상계
과실비율
책임비율
```

보조 문맥은 실제 사고가 법적 책임, 손해배상, 보험, 과실 판단과 연결되어 있는지를 확인하기 위한 근거입니다.

---

## 11. confirmed_traffic 유지 기준

기존 `confirmed_traffic` row는 다음 조건을 만족하면 최종 confirmed로 유지합니다.

```text
1. traffic_relevance_score >= 8
2. traffic_signal_group_count >= 2
3. traffic_term_count >= 3
4. 강한 교통사고 근거가 있음
5. 강한 사고 근거 + 보조 문맥이 함께 있거나, 강한 사고 근거 묶음이 충분함
6. 법규-only 문맥이 아님
```

법규-only 문맥은 다음처럼 실제 사고 피해보다 교통법규 위반, 면허, 행정처분, 처벌만 중심인 경우입니다.

```text
도로교통법위반
음주운전
무면허운전
운전면허취소
운전면허정지
벌점
범칙금
과태료
```

이런 단어가 있어도 실제 사고, 피해자, 상해/사망, 손해배상, 보험 문맥이 함께 있으면 유지할 수 있습니다.  
반대로 법규 문맥만 있고 사고 피해 문맥이 약하면 `non_traffic`으로 내립니다.

---

## 12. possible_traffic_review 승격 기준

기존 `possible_traffic_review` row는 다음 조건을 모두 만족하면 최종 `confirmed_traffic`으로 승격합니다.

```text
1. 강한 교통사고 근거가 있음
2. 보조 교통사고 문맥이 있음
3. traffic_relevance_score >= 8
4. traffic_signal_group_count >= 2
5. traffic_term_count >= 3
6. 법규-only 문맥이 아님
7. confirmed를 막는 사건종류가 아님
```

승격되는 대표 유형은 다음과 같습니다.

```text
손해배상(자) 사건에서 차량이 보행자를 충격하고 피해자가 사망/상해를 입은 경우
구상금 사건에서 두 차량 운전자, 보험금 지급, 공동불법행위 문맥이 함께 나오는 경우
보험금/자동차손해배상 사건에서 실제 사고 경위와 손해 발생이 명확한 경우
```

위 조건을 만족하지 못하는 `possible_traffic_review`는 `non_traffic`으로 보냅니다.  
이유는 2차 과실비율 분류 입력의 precision을 유지하기 위해서입니다.

---

## 13. non_traffic 유지 기준

기존 `non_traffic`은 이 단계에서 다시 confirmed로 올리지 않습니다.

이 단계의 목적은 다음 두 가지에 집중합니다.

```text
1. confirmed_traffic의 precision 보강
2. possible_traffic_review 안의 강한 교통사고 판례만 recall 보강
```

`non_traffic` 전체를 다시 훑어 숨은 교통사고 판례를 찾는 작업은 별도 recall 보강 작업으로 분리하는 것이 안전합니다.

---

## 14. 현재 실행 결과

현재 검증 결과는 다음과 같습니다.

```text
confirmed_traffic 입력: 3,207건
  - 최종 confirmed_traffic 유지: 3,197건
  - 최종 non_traffic으로 이동: 10건

possible_traffic_review 입력: 3,355건
  - 최종 confirmed_traffic으로 승격: 365건
  - 최종 non_traffic으로 이동: 2,990건

기존 non_traffic 유지: 8,958건

최종 confirmed_traffic: 3,562건
최종 non_traffic: 11,958건
전체: 15,520건
```

---

## 15. 다음 단계

검증 후 과실비율 2차 분류에 사용할 입력은 다음 파일입니다.

```text
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_reclass_verified/01_confirmed_traffic_cases.jsonl
```

그 다음 단계에서는 다음 질문을 봅니다.

```text
이 교통사고 판례가 과실비율/과실상계/책임비율 판단용 판례인가?
```

그 질문은 2차 분류 및 2차 검증/재정리 문서에서 다룹니다.

---

## 16. 1차 검증과 2차 검증의 차이

| 구분 | 1차 검증/재정리 | 2차 검증/재정리 |
|---|---|---|
| 질문 | 진짜 교통사고 관련 판례인가? | 진짜 과실비율 판단용 판례인가? |
| 입력 | `traffic_prec_reclass` | `traffic_prec_fault_ratio` |
| confirmed 의미 | 교통사고 관련 판례 | 과실비율 관련 판례 |
| 제외 라벨 | `non_traffic` | `traffic_but_no_fault_ratio` |
| 최종 사용 파일 | `traffic_prec_reclass_verified/01_confirmed_traffic_cases.jsonl` | `traffic_prec_fault_ratio_verified/01_fault_ratio_confirmed_cases.jsonl` |
| 다음 단계 | 과실비율 2차 분류 | RAG DB 적재 후보 |

---

## 17. 하드코딩 여부

이 검증은 특정 판례 ID나 특정 줄 번호를 찍어서 이동시키는 방식이 아닙니다.

없는 것:

```text
case_id가 몇 번이면 confirmed
case_id가 몇 번이면 non_traffic
특정 사건명을 무조건 이동
```

있는 것:

```text
1차 분류 점수
근거 묶음 개수
교통 키워드 개수
강한 사고 신호
보조 교통사고 문맥
법규-only 문맥
비교통 도메인 신호
```

즉 규칙 기반 검증/재정리입니다.
