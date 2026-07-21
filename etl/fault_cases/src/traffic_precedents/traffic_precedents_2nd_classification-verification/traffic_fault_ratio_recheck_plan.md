# 2차 분류 검증 및 재정리 계획

## 0. 실행 결과 (2026-07-15)

이 계획은 구현과 전체 재검증까지 완료했다. 2차 과실비율 증거 검증을 통과한
1,006건은 recall-first 기본 코퍼스로 유지하고, 사건명 자체가 명백한 비교통 사건인
경우만 제외했다.

| 분기 | 건수 | 후속 처리 |
|---|---:|---|
| `fault_ratio_confirmed` / `rag_eligibility=ready` | 987 | 청킹·임베딩 입력 |
| `rag_review_flags` 보유 | 779 | ready 987건에 포함된 검토 메타데이터 |
| `fault_ratio_rag_excluded` | 19 | 사건명으로 확정된 비교통 오탐 |
| 합계 | 1,006 | 2차 과실비율 증거 검증 통과 집합 |

`rag_review_flags` 779건은 별도 탈락 집합이 아니라 ready 987건의 부분집합이다.
전체 입력 3,632건 기준으로는 987건 ready, 과실비율 증거 부족 2,626건과 명백한
비교통 사건 19건이 excluded다.
최종 RAG 입력은 아래 파일 하나뿐이다.

```text
etl/fault_cases/artifacts/traffic_precedents_output/
  traffic_prec_fault_ratio_rag_verified/
    01_fault_ratio_rag_ready_cases.jsonl
```

검증 코드와 상세 리포트:

```text
rag_eligibility.py
traffic_fault_ratio_recheck.py
traffic_prec_fault_ratio_rag_verified/00_fault_ratio_rag_verification_report.json
```

---

## 1. 문서 목적

이 문서는 2차 과실비율 분류가 끝난 뒤 수행할 **과실비율 관련성 검증 및 재정리 단계**의 계획서입니다.

2차 분류 결과는 다음 세 라벨로 나뉩니다.

```text
fault_ratio_confirmed
fault_ratio_possible_review
traffic_but_no_fault_ratio
```

이 검증 단계의 질문은 하나입니다.

```text
이 교통사고 판례가 진짜 과실비율/과실상계/책임비율 판단용 판례인가?
```

최종 목적은 RAG 데이터베이스에 넣을 수 있는 **과실비율 판단용 판례만** 깨끗하게 남기는 것입니다.

---

## 2. 현재 2차 분류 결과

현재 재검증 입력 기준 결과는 다음과 같습니다.

```text
총 처리 대상: 3,632건
fault_ratio_confirmed 입력: 1,191건
fault_ratio_possible_review 입력: 998건
traffic_but_no_fault_ratio 입력: 1,443건
과실비율 증거 검증 통과: 1,006건
```

현재 의미는 다음과 같습니다.

| 라벨 | 현재 의미 | 검증 필요성 |
|---|---|---|
| `fault_ratio_confirmed` | 과실비율 판단용으로 바로 쓸 수 있다고 본 판례 | 오탐이 있으면 비과실로 내려야 함 |
| `fault_ratio_possible_review` | 과실/책임/손해배상 단서는 있으나 확정이 필요한 판례 | 진짜 과실비율이면 confirmed로 올리고 아니면 비과실로 보냄 |
| `traffic_but_no_fault_ratio` | 교통사고 관련은 맞지만 과실비율용은 아니라고 본 판례 | 기본 유지 |

---

## 3. 왜 2차 검증이 필요한가

2차 분류는 과실비율 관련성을 규칙 기반으로 판단합니다.  
하지만 규칙 기반 분류에는 두 가지 문제가 남을 수 있습니다.

첫째, `fault_ratio_confirmed` 안에도 실제 과실비율 판단용이 아닌 판례가 섞일 수 있습니다.

예시는 다음과 같습니다.

```text
손해배상 사건이지만 쟁점이 일실수입, 후유장해, 치료비, 소멸시효뿐인 판례
보험금/구상금 사건이지만 실제 과실 분담 판단이 없는 판례
업무상과실치상/교통사고처리특례법위반 형사사건에서 형사책임만 판단한 판례
과실이라는 단어가 죄명이나 일반 책임 표현으로만 등장한 판례
연 5%, 연 12%, 연 20% 같은 지연손해금 비율을 과실비율로 잘못 잡은 판례
```

둘째, `fault_ratio_possible_review` 안에는 실제 과실비율 판단용 판례가 숨어 있을 수 있습니다.

예시는 다음과 같습니다.

```text
본문에 원고와 피고의 책임비율을 70:30, 50:50 등으로 나누는 판례
과실상계 또는 책임제한 비율을 명시한 손해배상(자) 판례
공동불법행위자 사이 내부 책임분담비율을 판단한 구상금 판례
피해자 과실, 운전자 과실, 보험자 구상 범위를 구체적으로 판단한 판례
```

따라서 2차 검증 단계에서는 `fault_ratio_possible_review`를 최종 RAG 라벨로 남기지
않고 아래처럼 정리합니다. 애매한 사건은 코퍼스에서 삭제하지 않고 검토 플래그를
붙입니다.

```text
fault_ratio_confirmed
fault_ratio_rag_excluded
traffic_but_no_fault_ratio
rag_review_flags (ready 내부 메타데이터)
```

---

## 4. 계획 코드 파일

새로 만들 검증 코드는 다음 이름을 권장합니다.

```text
traffic_fault_ratio_recheck.py
```

예상 실행:

```bash
python traffic_fault_ratio_recheck.py --fresh
```

입력/출력을 직접 지정하는 실행 예시는 다음과 같습니다.

```bash
python traffic_fault_ratio_recheck.py \
  --fault-ratio-dir etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_fault_ratio \
  --out-dir etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_fault_ratio_rag_verified \
  --fresh
```

---

## 5. 입력 파일

기본 입력 폴더:

```text
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_fault_ratio/
```

입력 파일:

```text
01_fault_ratio_confirmed_cases.jsonl
02_fault_ratio_possible_review.jsonl
03_traffic_but_no_fault_ratio_cases.jsonl
```

| 파일 | 의미 |
|---|---|
| `01_fault_ratio_confirmed_cases.jsonl` | 2차 분류에서 과실비율 판단용으로 확정한 판례 |
| `02_fault_ratio_possible_review.jsonl` | 과실/책임/손해배상 단서는 있으나 확정이 필요한 판례 |
| `03_traffic_but_no_fault_ratio_cases.jsonl` | 교통사고 관련은 맞지만 과실비율용은 아니라고 본 판례 |

---

## 6. 출력 파일

기본 출력 폴더:

```text
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_fault_ratio_rag_verified/
```

출력 파일:

```text
00_fault_ratio_rag_verification_report.json
01_fault_ratio_rag_ready_cases.jsonl
02_fault_ratio_rag_excluded_cases.jsonl
03_fault_ratio_review_flagged_cases.jsonl
04_fault_ratio_rag_verified_all.jsonl
05_demoted_from_confirmed.jsonl
06_promoted_from_possible.jsonl
07_possible_excluded.jsonl
08_rag_gate_rejected.jsonl
```

| 파일 | 의미 | 사용처 |
|---|---|---|
| `00_fault_ratio_rag_verification_report.json` | 검증 통계와 기준 요약 | 통계 확인 |
| `01_fault_ratio_rag_ready_cases.jsonl` | 과실 증거 검증을 통과하고 명백한 비교통 제목이 없는 판례 | RAG DB 적재 입력 |
| `02_fault_ratio_rag_excluded_cases.jsonl` | 비과실 또는 RAG 부적합 판례 | 제외 보관 |
| `03_fault_ratio_review_flagged_cases.jsonl` | 약한 근거나 부수 쟁점이 있는 ready 판례의 부분집합 | QA·오류 분석 |
| `04_fault_ratio_rag_verified_all.jsonl` | 전체 row 감사 파일 | 추적/디버깅 |
| `08_rag_gate_rejected.jsonl` | 과실 증거는 통과했지만 RAG 게이트에서 제외된 판례 | 오탐 분석 |

최종 RAG 데이터베이스 적재 후보는 다음 파일 하나입니다.

```text
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_fault_ratio_rag_verified/01_fault_ratio_rag_ready_cases.jsonl
```

`03_fault_ratio_review_flagged_cases.jsonl`은 `01_fault_ratio_rag_ready_cases.jsonl`에
이미 포함된 부분집합이므로 별도로 합치지 않습니다.

---

## 7. 최종 라벨 구조

검증 후에는 `fault_ratio_possible_review`를 RAG 입력 라벨로 남기지 않습니다.

최종 라벨은 다음 세 개입니다. 검토 필요 여부는 라벨이 아니라
`rag_review_flags` 배열로 저장합니다.

```text
fault_ratio_confirmed
fault_ratio_rag_excluded
traffic_but_no_fault_ratio
```

라벨 이동 규칙은 다음과 같습니다.

| 원본 라벨 | 조건 | 최종 라벨 |
|---|---|---|
| 증거 검증 통과 | 사건명에 명백한 비교통 사건 유형이 없음 | `fault_ratio_confirmed` |
| 증거 검증 통과 | 부수 쟁점, 약한 교통 표현, 과실 문장 연결성 부족 | `fault_ratio_confirmed` + `rag_review_flags` |
| 증거 검증 통과 | 사건명 자체가 명백한 비교통 사건 | `fault_ratio_rag_excluded` |
| 증거 검증 실패 | 과실비율 판단용 근거 부족 | `traffic_but_no_fault_ratio` |
| `traffic_but_no_fault_ratio` | 별도 재검토 없음 | `traffic_but_no_fault_ratio` |

---

## 8. 검증에 사용할 기존 근거 필드

2차 분류 결과 row에는 다음 필드가 붙어 있습니다.

검증 단계에서 사건유형을 다시 확인할 때는 새 전처리 산출물의 한글 필드를 우선 사용하고, 기존 영문 필드를 fallback으로 사용합니다.

```text
사건명 / case_name
사건번호 / case_number
사건종류명 / case_category
```

| 필드 | 의미 |
|---|---|
| `fault_ratio_label` | 2차 분류 라벨 |
| `fault_ratio_score` | 과실비율 관련성 점수 |
| `fault_ratio_reclass_reasons` | 2차 분류 이유 |
| `fault_ratio_evidence_terms` | 실제 잡힌 근거 표현 |
| `fault_ratio_signal_groups` | 과실비율 관련 근거 묶음 |
| `fault_ratio_signal_group_count` | 근거 묶음 개수 |
| `has_core_fault_ratio_context` | 과실비율 핵심 문맥 여부 |
| `has_damage_or_insurance_context` | 손해배상/보험/구상금 문맥 여부 |
| `no_fault_context_without_core` | 비과실 문맥은 있는데 핵심 과실비율 문맥이 없는지 여부 |
| `fault_ratio_explicit_terms` | 과실비율 직접 표현 |
| `fault_ratio_party_fault_terms` | 당사자별 과실 판단 표현 |
| `fault_ratio_damage_terms` | 손해배상/보험/구상금 표현 |
| `fault_ratio_no_fault_terms` | 비과실비율 쪽 신호 |
| `preprocessed_fault_ratio` | 전처리 단계에서 추출한 과실비율 값 |

2차 검증은 이 필드들을 다시 조합해 판단합니다.

---

## 9. 검증 후 추가할 필드

새 검증 코드에서는 다음 필드를 추가하는 것이 좋습니다.

| 필드 | 의미 |
|---|---|
| `fault_ratio_label_before_verification` | 검증 전 라벨 |
| `fault_ratio_verification_source_label` | 어느 원본 파일에서 온 row인지 |
| `fault_ratio_verification_final_label` | 검증 후 최종 라벨 |
| `fault_ratio_verification_decision_reasons` | 최종 라벨로 보낸 이유 |

이 필드는 RAG 데이터 품질 검토와 추후 디버깅에 필요합니다.

---

## 10. 강한 과실비율 근거

다음 근거가 있으면 강한 과실비율 신호로 봅니다.

```text
explicit_fault_ratio_expression
numerical_fault_apportionment
party_fault_judgment
damage_or_insurance_context
```

각 의미는 다음과 같습니다.

| 근거 묶음 | 의미 | 예시 |
|---|---|---|
| `explicit_fault_ratio_expression` | 과실비율/과실상계/책임비율 직접 표현 | 과실비율, 과실상계, 책임비율, 쌍방과실 |
| `numerical_fault_apportionment` | 과실/책임 주변 숫자 비율 | 70%, 30%, 7:3, 50:50, 2할 |
| `party_fault_judgment` | 당사자별 과실 판단 | 원고의 과실, 피고의 과실, 피해자의 과실, 운전자의 과실 |
| `damage_or_insurance_context` | 과실 판단이 손해배상/보험/구상금과 연결됨 | 손해배상, 구상금, 보험금, 대인배상 |

---

## 11. confirmed 유지/승격 기준

기존 `fault_ratio_confirmed`를 유지하거나 `fault_ratio_possible_review`를 승격하려면 다음 기준을 만족해야 합니다.

```text
1. has_core_fault_ratio_context = true
2. has_damage_or_insurance_context = true
3. fault_ratio_signal_group_count >= 2
4. no_fault_context_without_core = false
5. 지연손해금/이자율/소송촉진법상 연 비율을 과실비율로 오인한 것이 아님
6. 형사책임, 면허, 산재, 의료수가, 사기 등 비과실 문맥만 중심인 판례가 아님
```

더 강한 confirmed 근거는 다음 조합입니다.

```text
과실비율/과실상계/책임비율 직접 표현 + 손해배상/보험/구상금 문맥
숫자 비율 + 과실/책임/분담 문맥
당사자별 과실 판단 + 손해배상/보험 문맥
공동불법행위 + 내부 책임분담비율 판단
```

---

## 12. fault_ratio_confirmed에서 강등할 기준

기존 `fault_ratio_confirmed`라도 다음 유형이면 `traffic_but_no_fault_ratio`로 내립니다.

```text
1. 과실비율 직접 표현 없이 손해배상액 산정만 다룸
2. 일실수입, 위자료, 치료비, 개호비, 장례비 산정만 다룸
3. 지연손해금 비율을 과실비율로 잘못 잡은 경우
4. 업무상과실치상/치사 같은 형사 죄명에만 과실이 등장
5. 교통사고처리특례법위반, 도주치상, 위험운전치상 등 형사책임 중심
6. 음주운전, 무면허운전, 면허취소, 벌점 등 행정/형사처분 중심
7. 산재 요양급여/유족급여/요양불승인 중심
8. 자동차보험진료수가, 의료법위반, 사기 등 과실비율과 직접 관련 없는 쟁점
```

이런 판례는 교통사고 관련 판례일 수는 있지만, 사용자가 묻는 과실비율 판단 RAG에는 노이즈가 됩니다.

---

## 13. fault_ratio_possible_review 승격 기준

기존 `fault_ratio_possible_review` 중 다음 조건을 만족하면 `fault_ratio_confirmed`로 올립니다.

```text
1. 과실비율/과실상계/책임비율 직접 표현이 있음
2. 또는 과실/책임 단어 주변에 숫자 비율이 있음
3. 또는 당사자별 과실 판단과 손해배상/보험 문맥이 함께 있음
4. 손해배상/보험/구상금 문맥이 있음
5. 비과실 문맥이 있더라도 핵심 과실비율 문맥이 더 강함
```

승격 예시는 다음과 같습니다.

```text
원고 차량 운전자와 피고 차량 운전자의 내부적 책임분담비율을 50%로 판단
피해자의 과실을 30%로 보아 과실상계
보험자가 공동불법행위자 중 일방을 상대로 구상금 청구, 부담비율 판단
망인의 무단횡단 과실을 참작하여 손해배상책임 제한
```

---

## 14. possible에서 비과실로 보낼 기준

`fault_ratio_possible_review` 중 다음 유형은 `traffic_but_no_fault_ratio`로 보냅니다.

```text
1. 손해배상/보험 단어는 있지만 실제 과실 분담 판단이 없음
2. 과실이라는 단어가 일반 주의의무 또는 형사 과실로만 등장
3. 숫자 비율이 지연손해금, 이자율, 법정이율 문맥임
4. 사고 경위만 있고 책임비율/과실상계 판단이 없음
5. 치료비, 후유장해, 일실수입, 위자료 산정만 중심
6. 보험약관, 진료수가, 심사청구, 보험금 지급절차만 중심
```

---

## 15. 기존 traffic_but_no_fault_ratio 유지 기준

기존 `traffic_but_no_fault_ratio`는 기본적으로 그대로 유지합니다.

이유는 이 단계의 목적이 다음 두 가지에 집중하기 때문입니다.

```text
1. fault_ratio_confirmed의 precision 보강
2. fault_ratio_possible_review 안의 강한 과실비율 판례만 recall 보강
```

`traffic_but_no_fault_ratio` 전체를 다시 뒤져 숨은 과실비율 판례를 찾는 작업은 별도 recall 보강 작업으로 분리하는 것이 안전합니다.

---

## 16. 과실비율과 헷갈리기 쉬운 숫자 비율

2차 검증에서 가장 조심해야 할 것은 숫자 비율입니다.  
숫자 비율이 있다고 모두 과실비율이 아닙니다.

| 표현 | 과실비율 가능성 | 이유 |
|---|---|---|
| `과실비율 70%` | 높음 | 과실비율 직접 표현 |
| `피해자의 과실을 30%로 봄` | 높음 | 당사자 과실 + 숫자 |
| `책임을 80%로 제한` | 높음 | 손해배상책임 제한 문맥 |
| `연 5%`, `연 12%`, `연 20%` | 낮음 | 지연손해금/이자율 가능성 큼 |
| `장해율 20%` | 낮음 | 신체 장해율일 수 있음 |
| `노동능력상실률 30%` | 낮음 | 손해액 산정 요소이지 과실비율 자체는 아님 |
| `전문의 자격 취득 비율 80%` | 낮음 | 사고 과실과 무관한 통계 |

따라서 숫자 비율은 반드시 과실/책임/분담/상계 문맥과 가까이 있을 때만 강한 근거로 봅니다.

---

## 17. 1차 검증과 2차 검증 비교

| 구분 | 1차 검증/재정리 | 2차 검증/재정리 |
|---|---|---|
| 핵심 질문 | 진짜 교통사고 관련 판례인가? | 진짜 과실비율 판단용 판례인가? |
| 입력 폴더 | `etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_reclass/` | `etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_fault_ratio/` |
| 중간 라벨 | `possible_traffic_review` | `fault_ratio_possible_review` |
| 최종 confirmed | `confirmed_traffic` | `fault_ratio_confirmed` |
| 최종 제외 | `non_traffic` | `traffic_but_no_fault_ratio` |
| confirmed 의미 | 교통사고 관련 판례 | 과실비율 RAG 적재 후보 |
| 검증 후 최종 입력 | 과실비율 2차 분류 입력 | RAG DB 적재 입력 |

---

## 18. 실행 통계

검증 리포트에는 다음 통계를 넣습니다.

```json
{
  "fault_confirmed_input_rows": 1191,
  "possible_input_rows": 998,
  "no_fault_input_rows": 1443,
  "base_fault_ratio_confirmed_rows": 1006,
  "base_confirmed_rag_ready_rows": 987,
  "base_confirmed_review_flagged_rows": 779,
  "base_confirmed_rag_excluded_rows": 19,
  "final_all_rows": 3632
}
```

---

## 19. 전체 흐름

```text
2차 분류 결과
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_fault_ratio/
  01_fault_ratio_confirmed_cases.jsonl
  02_fault_ratio_possible_review.jsonl
  03_traffic_but_no_fault_ratio_cases.jsonl
↓
2차 과실 증거 검증 + recall-first RAG 적합성 판정
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_fault_ratio_rag_verified/
  01_fault_ratio_rag_ready_cases.jsonl       # 987, 청킹·임베딩 입력
  03_fault_ratio_review_flagged_cases.jsonl  # 779, ready 내부 QA 부분집합
  08_rag_gate_rejected.jsonl                 # 19, 명백한 비교통 제목
↓
rag_eligibility=ready만 RAG DB 적재
```

---

## 20. 하드코딩 여부

2차 검증도 특정 판례 ID나 특정 줄 번호를 찍어서 이동시키는 방식으로 만들지 않습니다.

없는 것:

```text
case_id가 몇 번이면 confirmed
case_id가 몇 번이면 no_fault
특정 사건명을 무조건 이동
```

있는 것:

```text
과실비율 직접 표현
당사자별 과실 판단
숫자 비율과 과실/책임 문맥의 근접성
손해배상/보험/구상금 문맥
비과실비율 문맥
지연손해금/이자율 오탐 방지
점수와 근거 묶음 기준
```

즉 특정 row 맞춤 하드코딩이 아니라 **규칙 기반 과실비율 검증/재정리 기준**으로 설계합니다.
