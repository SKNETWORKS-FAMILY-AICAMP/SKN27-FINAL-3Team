# 인정기준 FULL-50 pgvector · PostgreSQL · Neo4j A/B/C 실험계획 V6

> 문서 상태 갱신(2026-07-20): `G0 완료 · G1 Gold Outcome 보강 중`

## 0-A. 실행 요약: 이 순서를 건너뛰지 않는다

목표는 **동일한 50개 사고 입력에 대해 A/B/C가 인정기준 Rule과 최종 과실비율을 얼마나 정확하게 찾는지 수치로 비교**하는 것이다. 다섯 Gate를 모두 통과한 뒤에만 최종 비교 표와 보고서를 낸다.

| 순서 | 단계 | 단계 목표 | 완료 판정 | 현재 상태 |
|---|---|---|---|---|
| G0 | 인벤토리 | 50개 입력·Facts·Gold의 실제 보유 상태 확인 | case_id 집합과 미완성 항목을 출력 | 완료: Gold 25건만 완결 |
| G1 | 입력/정답 완결 | 재질문 답변을 포함한 Facts 50개와 독립 Gold Outcome 50개를 완성 | Rule, PDF Party 매핑, base/variant/adjustment/final ratio, PDF 근거가 각 Gold에 있음 | 진행 중 |
| G2 | 공통 계약 구현 | 한 Canonical을 PostgreSQL·Neo4j로 투영하고 같은 계산기로 검증 | 투영 parity·계산 단위테스트 통과 | 대기 |
| G3 | A/B/C 실행 | 같은 50 입력·같은 vector Top-50에서 세 방법 실행 | 50행 결과와 MRR/nDCG/Rule·비율 정확도/지연시간 생성 | 대기 |
| G4 | 보고 | 결과·실패 원인·재현 명령을 MD로 보고 | 비교표와 감사 trace가 서로 일치 | 대기 |

**현재 차단 사유(G0 실측):** 질문 50개와 Facts 50개는 존재하지만, `Rule + Party 매핑 + 최종 비율`까지 완결된 Gold Outcome은 25개뿐이다. 24개는 최종 비율 또는 계산 근거가 비어 있고, 1개(`fault_common_q31`)는 positive Rule 자체가 없다. 따라서 지금 A/B/C를 돌려도 50개 정확도라고 부를 수 없으므로 G3를 실행하지 않는다.

**G1 누출 방지 계약:** Supervisor 재질문 답변은 `기존 질문 + 공통 Fact Dictionary + 사전에 고정한 scenario truth`만 보고 만든다. qrels, Gold Rule, PDF 정답 페이지, 비율을 재질문 답변 생성에 사용하면 Gate 실패다. Facts를 고정한 뒤 별도의 Label 과정이 PDF 근거만으로 Gold를 제작한다. 없는 숫자를 추정해서 채우지 않는다.

> 최초 계획 상태: `draft_for_final_review` → 현재 실행 상태는 본문 `0-A`의 Gate 표를 따른다.  
> 기준일: 2026-07-20  
> 실행 루트: `etl/fault_cases/NEW_ABC_TEST_V6/`  
> 이전 실행: V1~V5는 읽기 전용 참고이며 V6 성능 결과에 합산하지 않는다.

## 0. 한눈에 보는 결론

이 실험의 목적은 **동일한 50개 사고에 대해 의미검색만 사용했을 때와, 의미검색 뒤 PostgreSQL 또는 Neo4j 구조 매칭을 적용했을 때 정답 인정기준 Rule의 순위·선택·최종 과실비율 정확도가 얼마나 달라지는지 수치로 비교하는 것**이다.

이번에는 아래 네 파일이 모두 50건으로 완성되기 전에는 A/B/C를 실행하지 않는다.

```text
기준 질문 50건
+ Supervisor 재질문 답변 50건
= 보강 완료 사고 Facts 50건

보강 완료 사고 Facts 50건
+ PDF 표·해설 독립 검수
= Rule·A/B 매핑·기본비율·수정요소·최종비율 Gold Outcome 50건
```

최종 비교는 다음과 같다.

| 비교 | 동일 입력 | 결과 순위 | 핵심 지표 |
|---|---|---|---|
| A: pgvector | 보강 완료 Facts 50건 | Qwen cosine 원순위 | Hit/Recall, MRR, nDCG, Rule Top-1, 공통 계산기 비율 |
| B: pgvector → PostgreSQL | A와 같은 Top-50 | SQL hard-condition 후처리 순위 | MRR, nDCG, Rule 선택, 비율 exact, latency |
| C: pgvector → Neo4j | A와 같은 Top-50 | Cypher 관계 hard-match 후처리 순위 | MRR, nDCG, Rule 선택, 비율 exact, latency |
| B vs C | 같은 Canonical | 같은 의미이면 동일 순위가 정상 | semantic parity, latency, 운영성, 관계 확장성 |

LLM은 Rule·당사자·비율을 판단하지 않는다. Runtime은 구조화 Facts를 읽고, 승인된 PDF 조건을 비교하고, 승인된 숫자를 기계적으로 계산한 JSON만 반환한다.

---

## 1. 현재 상태와 V5 실패 원인

### 1.1 실제 파일 상태

| 데이터 | Case 수 | 최종비율 보유 | V6 용도 |
|---|---:|---:|---|
| `common_fault_queries_v1.jsonl` | 50 | 해당 없음 | 기준 질문 후보 |
| `completed_accident_facts_v4.jsonl` | 50 | 0 | Supervisor 보강 Facts 후보 |
| `calculation_answer_key_v3_template.jsonl` | 50 | 0 | 사용 금지: 빈 템플릿 |
| `calculation_answer_key_v3_simulated_source_verified.jsonl` | 50 | 20 | Gold 후보 근거만 참고 |
| `fault_standard_qrels_v1.2.jsonl` | 50 | 29 | Gold 후보·hard-negative 참고 |

현재는 **50건 모두의 최종비율이 검증된 정답지가 없다.** 따라서 기존 V5의 `4/23`, `3/23` 같은 축소 분모는 FULL-50 본실험 결과가 아니다.

### 1.2 V5에서 확인된 오류

1. hard-negative `relevance=0`가 허용 Rule에 섞였다.
2. A의 원검색 순위와 B/C의 유일 Rule 선택을 같은 정확도처럼 비교했다.
3. B/C의 MRR·nDCG를 처음부터 계산하지 않았다.
4. 50건 전체 대신 평가 가능한 일부 Case로 분모를 축소했다.
5. `3/4` 계산 coverage를 비율 정확도처럼 표현했다.
6. Party 직접 조건만 사용하고 Variant·Adjustment·LaneStep이 미완료인 상태에서 숫자를 계산했다.
7. B/C가 같은 Canonical을 사용하므로 결과가 같은 것이 정상인데, 이를 비정상처럼 해석했다.

V6는 위 오류를 자동 Gate로 차단한다.

---

## 2. 변경 불가 실험 원칙

### 2.1 FULL-50 원칙

- 본실험 Case 수는 정확히 50개다.
- 모든 Case는 기준 질문, Supervisor 답변, 완료 Facts, Gold Outcome을 정확히 1개씩 가져야 한다.
- Gold Outcome 50건은 모두 `expected_status=calculated`여야 한다.
- 모든 Gold Outcome은 Rule ID, 사용자/상대의 PDF Party key, 기본비율, 적용 Variant, 적용 Adjustment, 최종비율, PDF Evidence를 가져야 한다.
- 하나라도 완성되지 않으면 G1 Gate 실패이며 A/B/C 본실험을 실행하지 않는다.

### 2.2 기존 질문 중 계산 불가능 Case 처리

현재 질문이 PDF 인정기준과 정확히 매핑되지 않거나, 재질문 후에도 최종비율을 확정할 수 없으면 숫자를 만들지 않는다.

FULL-50을 유지하려면 다음 중 하나를 선택한다.

1. 질문의 사고 사실이 부족한 경우: 정답을 보지 않은 공통 Fact Dictionary로 Supervisor 질문·답변을 추가한다.
2. corpus에 정확한 Rule이 없는 경우: 해당 Case를 별도 `negative_safety_set`으로 이동하고, PDF Rule에서 역으로 만든 것이 아닌 독립 질문 작성 절차로 계산 가능한 신규 Case를 보충한다.
3. PDF 근거가 충돌하는 경우: 자동 선택하지 않고 사용자에게 충돌 근거를 보고한다.

Case 교체는 평가 분포를 바꾸므로 사용자 승인 없이는 수행하지 않는다. 교체 시 V6 Query ID와 이전 Case ID를 manifest에 모두 기록한다.

### 2.3 누출 금지

G1 입력 제작 프로세스는 다음을 읽을 수 없다.

- qrels
- Gold Rule ID
- Party A/B 정답
- 기본·최종비율
- PDF 정답 페이지
- 임베딩 순위

Supervisor 답변은 `질문 원문 + 공통 Fact Dictionary + 고정 Scenario Truth`만 사용한다. Facts가 고정된 후 별도 Label 프로세스가 PDF로 Gold Outcome을 만든다.

### 2.4 검색 가중치 금지

- 벡터 점수와 구조 조건 점수를 합산하지 않는다.
- Rule별 임의 가중치를 사용하지 않는다.
- 정답지에 맞춘 threshold·boost를 만들지 않는다.
- B/C 후처리는 승인 조건의 3값 결과와 원래 pgvector rank만 사용한다.

---

## 3. V6 데이터 계약

### 3.1 기준 질문

`queries_v6.jsonl` 한 행:

```json
{
  "case_id": "fault_v6_q001",
  "raw_user_text": "...",
  "query_text": "...",
  "accident_group": "signalized_intersection",
  "participants": ["vehicle", "vehicle"],
  "source_case_id": "fault_common_q01"
}
```

### 3.2 Supervisor 요청·답변

`supervisor_responses_v6.jsonl` 한 행:

```json
{
  "case_id": "fault_v6_q001",
  "responses": [
    {
      "fact_key": "user.signal_state",
      "answer_value": "green",
      "answer_state": "confirmed",
      "provenance": "fixed_scenario_truth"
    }
  ],
  "contains_rule_or_ratio": false
}
```

### 3.3 완료 Facts

`completed_facts_v6.jsonl`은 기준 질문과 Supervisor 답변을 병합한 Runtime 입력이다.

필수 범주:

- `environment`: 사고군, 신호기, 교차로/도로/회전교차로 구조, 진입 순서
- `user`: actor type, movement, signal, road/lane position, violation, entry/exit timing
- `opponent`: 동일 필드
- `sequence`: LaneStep·충돌 전후 순서가 필요한 경우
- `adjustment_facts`: 대형차, 현저한 과실, 중과실, 급정지 등 PDF 수정요소 사실

Rule ID·비율·PDF 페이지가 포함되면 Gate 실패다.

#### 3.3.1 UNKNOWN 정규화와 재질문 계약

- 원본에 `state=confirmed`라도 값이 `null`, 빈 문자열, `unknown`, `not_confirmed`이면 V6 Runtime에서는 반드시 `answer_state=unknown`으로 정규화한다.
- `unknown`은 "없음"이나 "해당 없음"이 아니다. 후자의 두 값은 Supervisor가 명시적으로 답한 경우에만 각각 `none_confirmed`, `not_applicable`로 기록한다.
- 재질문은 특정 Rule을 목표로 하지 않는다. 50개 모든 Case에 공통 Fact Dictionary(신호, 이동, 진입/진출 순서, 차로, 우선관계, 보행자/PM 여부, 수정요소)를 같은 형식으로 적용한다.
- G1-LABEL에서 필요한 사실이 UNKNOWN이면 Labeler는 비율을 추정하지 않고 `needs_fact`로 기록한다. 그 뒤에도 다시 묻는 질문은 공통 Dictionary에서만 고른다.
- `completed_facts_v6.jsonl`의 SHA-256을 G2/G3 manifest에 고정한다. 이후 한 글자라도 바뀌면 A/B/C 모두 재실행한다.

### 3.4 FULL-50 Gold Outcome

`gold_outcomes_v6.jsonl` 한 행:

```json
{
  "case_id": "fault_v6_q001",
  "expected_status": "calculated",
  "acceptable_rule_ids": ["official_2023_차1-1"],
  "selected_rule_id": "official_2023_차1-1",
  "party_mapping": {"user": "A", "opponent": "B"},
  "base_ratio": {"user": 0, "opponent": 100},
  "variant_id": null,
  "adjustments": [],
  "calculation_steps": [
    {"step": "base", "user": 0, "opponent": 100}
  ],
  "final_ratio": {"user": 0, "opponent": 100},
  "explanation_ko": "PDF 표의 당사자 조건과 기본과실을 적용한 감사 해설",
  "pdf_evidence": {
    "source_file": "230630_자동차사고_과실비율_인정기준_최종.pdf",
    "page_start": 148,
    "page_end": 151,
    "rule_table_text_sha256": "..."
  },
  "review_status": "pdf_verified"
}
```

### 3.5 검색 qrels

`retrieval_qrels_v6.jsonl`은 순위 지표 전용이다.

- `relevance=2`: 정확한 Gold Rule
- `relevance=1`: PDF상 동등 Outcome을 만드는 허용 Rule
- `relevance=0`: hard-negative
- `relevance=0`은 절대 `acceptable_rule_ids`에 포함하지 않는다.

---

## 4. 네 PDF의 Canonical 구조화 계약

### 4.1 공통 Core

```text
Rulebook
  └─ Rule
      ├─ PartyRole A/B 또는 보행자/차량 역할
      ├─ BaseFault
      ├─ Evidence
      ├─ Adjustment
      └─ CalculationContract
```

### 4.2 형식별 확장

| PDF | 필수 확장 | Rule 선택에 필요한 이유 |
|---|---|---|
| 2020 비정형 | RoadContext, PriorityContext | 도로 우선관계·진행 조건 구분 |
| 2021 PM vs 자동차 | PMContext, VehicleContext, SignalContext, Scenario, SharedRuleGroup | PM/자동차 역할·신호·공통표 조건 구분 |
| 2023 공식 인정기준 | Section, Variant, UsageNote | 같은 Rule 내부 보기·Variant·적용 제외 구분 |
| 2025 2차로형 회전교차로 | RoundaboutContext, LanePath, LaneStep | 진입차로·회전차로·진출 순서 구분 |

### 4.3 조건 3값

각 조건은 `MATCH`, `UNKNOWN`, `MISMATCH` 중 하나다.

- `MATCH`: Facts와 PDF 조건이 명시적으로 일치
- `UNKNOWN`: 필요한 Fact가 없음
- `MISMATCH`: 명시적으로 불일치

조건 없는 Rule은 `MATCH`가 아니라 `UNMODELED`이다.

### 4.4 Party 매핑

PDF Party key를 사용자/상대로 바로 가정하지 않는다.

```text
mapping 1: user=A, opponent=B
mapping 2: user=B, opponent=A
```

각 mapping에서 PartyRole 조건을 모두 평가하고, 정확히 하나만 완전 일치할 때 mapping을 확정한다. 둘 다 일치하거나 둘 다 불완전하면 계산하지 않는다.

### 4.5 Calculation Contract

Calculator 입력은 Resolver가 만든 다음 계약 하나뿐이다.

```json
{
  "rule_id": "...",
  "party_mapping": {"user": "A", "opponent": "B"},
  "base_shares": {"A": 30, "B": 70},
  "variant_shares": null,
  "adjustments": [
    {"adjustment_id": "...", "target_party_key": "A", "delta": 10}
  ]
}
```

Calculator는 적용 가능성을 판단하지 않는다. 승인된 숫자를 순서대로 더하고 빼며 합계 100·범위 0~100을 검증한다.

---

## 5. A/B/C Runtime 계약

### 5.1 공통 검색 입력

세 실험은 동일한 `completed_facts_v6.jsonl` 직렬화 문자열과 동일한 Qwen 4B 2,560차원 query vector를 사용한다.

문서 corpus, 임베딩 SHA, Top-50 후보 SHA가 모두 같아야 한다.

Rule 선택 이후의 Resolver·Calculator는 DB별 구현을 사용하지 않는다. G2가 만든 단일 `calculation_contracts.jsonl`을 읽는 공통 Python 구현을 A/B/C가 호출한다. 따라서 계산 정확도 차이는 Rule 선택 결과에서만 발생하고, 계산 코드 차이로 생기지 않는다.

### 5.2 A — pgvector only

1. exact cosine으로 277 Rule 전체를 검색한다.
2. 원래 pgvector 순위를 그대로 반환한다.
3. Top-1 Rule은 Rule 정확도 평가에 사용한다.
4. Top-10/50은 Recall·MRR·nDCG에 사용한다.
5. A의 Rule **선택**에는 PostgreSQL/Neo4j 조건을 사용하지 않는다.
6. Top-1이 선택된 뒤에는 세 실험 공통 `Calculation Contract Resolver`가 해당 Rule의 PDF Party 조건과 완료 Facts를 대조해 mapping·Variant·Adjustment를 확정한다.
7. A도 B/C와 동일한 `calculator.py`를 호출한다. 따라서 잘못된 Top-1 Rule로 계산된 비율은 end-to-end 오답으로 기록되고, mapping을 확정하지 못하면 `not_calculable`로 기록된다.

### 5.3 B — pgvector Top-50 → PostgreSQL

1. A와 byte-identical Top-50을 받는다.
2. PostgreSQL에서 Rule→Party→Variant→Adjustment→LaneStep 조건을 조인한다.
3. 각 후보를 3값 평가한다.
4. 후처리 순위는 다음 버킷 순서로 고정한다.

```text
MATCH
→ UNKNOWN
→ UNMODELED
→ MISMATCH
```

동일 버킷 안에서는 원래 pgvector rank를 유지한다. 점수 가중치는 없다.

5. 유일한 완전 MATCH Rule과 Party mapping이 있을 때만 Resolver·Calculator를 실행한다.

### 5.4 C — pgvector Top-50 → Neo4j

1. B와 byte-identical Top-50을 받는다.
2. B와 동일한 Canonical을 Neo4j 관계로 Projection한다.
3. Cypher로 Rule→PartyRole→Context→Variant/Adjustment/LaneStep 경로를 조회한다.
4. B와 동일한 3값 평가·버킷 순위·Calculator를 사용한다.

B/C의 Canonical 의미가 같다면 후보 상태, 후처리 순위, RuleSelection, Calculation 결과가 모두 같아야 한다.

---

## 6. 공정한 평가 지표

### 6.0 KPI 우선순위

최종 의사결정에 사용하는 Primary KPI는 세 개로 제한한다.

1. `nDCG@50`: Top-50 전체 순위가 Gold relevance를 얼마나 잘 반영하는가
2. `Exact Rule Accuracy / 50`: 최종 선택 Rule이 Gold 허용 Rule과 일치하는가
3. `End-to-End Exact / 50`: Rule·mapping·수정요소·최종비율이 모두 맞는가

진단 지표는 Recall@10/50, MRR@10/50, Calculation Coverage, 조건 상태 분포다. Guardrail은 false match, 입력 누출, hard-negative 혼입, B/C parity 실패, 계산 합계 오류다.

### 6.1 공통 분모

V6 FULL-50 본실험에서는 Gold Outcome이 모두 계산 가능해야 하므로 주요 분모는 50이다.

분모를 줄인 조건부 지표는 반드시 별도 표기한다. `3/4` 같은 값을 전체 비율 정확도라고 부르지 않는다.

### 6.2 A/B/C 공통 순위 지표

세 방법 모두 순위 목록을 만들므로 같은 50개와 같은 graded qrels로 계산한다.

| 지표 | 정의 |
|---|---|
| Hit@1 | 첫 Rule이 relevance>0인 Case 비율 |
| Recall@10/50 | Top-k에 Gold Rule이 하나 이상 있는 Case 비율 |
| MRR@10/50 | 첫 relevance>0 Rule의 reciprocal rank 평균 |
| nDCG@10/50 | relevance 2/1/0 graded ranking quality |

A는 원 pgvector 순위, B/C는 구조 후처리 순위를 사용한다.

### 6.3 Rule 선택 지표

| 지표 | 분모 |
|---|---:|
| Exact Rule Accuracy | 50 |
| Party Mapping Accuracy | 50 |
| Rule Selection Coverage | 50 |
| False Match Rate | 50 |
| Ambiguous/Unknown Rate | 50 |

### 6.4 비율 계산 지표

| 지표 | 계산식 |
|---|---|
| Base Ratio Exact | 기본비율이 Gold와 정확히 같은 Case / 50 |
| Adjustment Set Exact | 적용 adjustment ID·delta가 Gold와 같은 Case / 50 |
| Final Ratio Exact | 숫자를 출력하고 최종비율이 Gold와 같은 Case / 50 |
| End-to-End Exact | Rule+mapping+adjustment+final ratio가 모두 같은 Case / 50 |
| Calculation Coverage | 숫자를 안전하게 출력한 Case / 50 |
| Conditional Ratio Exact | 숫자를 출력한 Case 중 정확한 비율 / 숫자 출력 Case |

`Calculation Coverage`와 `Conditional Ratio Exact`는 서로 다른 지표다.

### 6.5 B/C 운영 지표

- p50/p95/p99 query latency
- 50건 총 실행시간
- Case당 DB query 수
- PostgreSQL join 수·SQL 길이
- Neo4j traversal hop 수·Cypher 길이
- Canonical Projection row/node/relationship 수
- Projection parity
- 관계 확장 시 변경 파일·테이블·쿼리 수

Latency는 cold start 1회를 버리고 동일 머신에서 방법별 3회 기능 실행으로 측정한다. Query embedding 생성 시간은 세 방법 공통 전처리이므로 구조 매칭 latency에서 제외하고 별도 총 pipeline latency에 포함한다. B/C 실행 순서는 반복마다 교차해 cache 순서 편향을 줄인다.

---

## 7. Gate별 실행 계획

### G0 — 원천·기존 파일 감사

목표: 현재 50건 중 무엇이 실제로 계산 가능한지 확인하고, 빈 정답지·부분 정답지를 분리한다.

산출물:

- `00_g0_inventory/current_dataset_audit.json`
- `00_g0_inventory/case_coverage_50.csv`
- `00_g0_inventory/g0_report.md`

통과 조건:

- 기준 질문 50, Supervisor Facts 50, case_id 1:1
- 기존 최종비율 보유/미보유 Case를 50건 전부 명시
- hard-negative가 Gold Outcome에 섞이지 않음

### G1-INPUT — FULL-50 입력 확정

목표: 정답을 보지 않고 50개 Supervisor 답변과 완료 Facts를 고정한다.

산출물:

- `01_g1_input/queries_v6.jsonl`
- `01_g1_input/supervisor_requests_v6.jsonl`
- `01_g1_input/supervisor_responses_v6.jsonl`
- `01_g1_input/completed_facts_v6.jsonl`
- `01_g1_input/leakage_scan.json`

통과 조건:

- 네 파일 모두 50건·case_id 1:1
- Rule ID·ratio pattern·PDF 정답 페이지 누출 0
- Gold Rule·Variant·Adjustment 적용에 필요한 required Fact의 `unknown` 0
- 3회 생성 SHA 동일

### G1-LABEL — FULL-50 Gold Outcome 제작

목표: 고정된 Facts를 PDF 표·해설과 대조해 50건 모두 계산 가능한 Gold를 만든다.

산출물:

- `02_g1_label/gold_outcomes_v6.jsonl`
- `02_g1_label/retrieval_qrels_v6.jsonl`
- `02_g1_label/pdf_evidence_audit_v6.jsonl`
- `02_g1_label/gold_quality_report.json`

통과 조건:

- Gold 50건
- `expected_status=calculated` 50건
- Rule·Party mapping·Base·Variant·Adjustment·Final ratio·Evidence 누락 0
- final ratio 합계 100
- Calculator 재계산 결과와 Gold 계산 단계 50/50 일치
- PDF Evidence 검증 50/50

이 Gate에서 기존 Case가 계산 불가능하면 자동으로 숫자를 만들지 않는다. Case 교체가 필요하면 근거와 대체 후보를 사용자에게 보고한다.

### G2 — Canonical 완성

목표: 50건 Top-50 union에 등장하는 모든 Rule을 완전 구조화한다.

산출물:

- `03_g2_canonical/candidates_top50.jsonl`
- `03_g2_canonical/canonical_rules.jsonl`
- `03_g2_canonical/canonical_conditions.jsonl`
- `03_g2_canonical/calculation_contracts.jsonl`
- `03_g2_canonical/projection_parity.json`

통과 조건:

- 각 Case Top-50 정확히 50개·중복 0
- A/B/C 후보 SHA 동일
- 후보 union의 `UNMODELED` Rule 0
- Gold Rule의 Party·Variant·Adjustment·LaneStep 조건 coverage 100%
- PostgreSQL/Neo4j 조건 의미 parity 100%

### G3-A — pgvector 기준선

산출물:

- `04_g3_a/a_ranked_rules.jsonl`
- `04_g3_a/a_metrics.json`

필수 지표:

- Hit@1
- Recall@10/50
- MRR@10/50
- nDCG@10/50

### G3-B — PostgreSQL 구조 후처리

산출물:

- `05_g3_b/b_candidate_states.jsonl`
- `05_g3_b/b_ranked_rules.jsonl`
- `05_g3_b/b_rule_selection.jsonl`
- `05_g3_b/b_calculations.jsonl`
- `05_g3_b/b_metrics.json`

필수 지표:

- A와 같은 순위 지표 전체
- Rule·Party mapping·Base·Adjustment·Final ratio 정확도
- latency p50/p95/p99

### G3-C — Neo4j 관계 후처리

산출물은 B와 동일한 Schema를 사용한다.

추가 검증:

- B/C candidate state parity
- B/C ranked list parity
- B/C RuleSelection parity
- B/C Calculation parity
- 관계 경로 trace 존재

### G4 — 최종 비교와 실패 분석

최종 표는 반드시 다음 형식을 포함한다.

| 지표 | A pgvector | B pgvector+PostgreSQL | C pgvector+Neo4j |
|---|---:|---:|---:|
| Hit@1 | | | |
| Recall@10 | | | |
| Recall@50 | | | |
| MRR@10 | | | |
| MRR@50 | | | |
| nDCG@10 | | | |
| nDCG@50 | | | |
| Exact Rule Accuracy / 50 | | | |
| Party Mapping Accuracy / 50 | | | |
| Final Ratio Exact / 50 | | | |
| End-to-End Exact / 50 | | | |
| p50/p95/p99 latency | | | |

실패 Case는 아래 원인으로 상호 배타적으로 분류한다.

- `candidate_miss`
- `ranking_failure`
- `canonical_condition_missing`
- `party_mapping_failure`
- `variant_failure`
- `adjustment_failure`
- `lane_sequence_failure`
- `calculator_failure`
- `gold_evidence_conflict`

---

## 8. 폴더 구조

```text
etl/fault_cases/NEW_ABC_TEST_V6/
├─ FULL_50_ABC_실험계획.md
├─ README.md
├─ configs/
│  ├─ experiment_v6.yaml
│  ├─ fact_dictionary_v6.yaml
│  └─ metric_contract_v6.yaml
├─ infra/
│  ├─ .env.example
│  └─ docker-compose.yml
├─ src/new_abc_test_v6/
│  ├─ common/
│  ├─ g0_inventory.py
│  ├─ g1_build_inputs.py
│  ├─ g1_build_gold.py
│  ├─ g1_validate_leakage.py
│  ├─ g2_build_canonical.py
│  ├─ g2_project_postgresql.py
│  ├─ g2_project_neo4j.py
│  ├─ g2_validate_parity.py
│  ├─ rank_a_pgvector.py
│  ├─ rank_b_postgresql.py
│  ├─ rank_c_neo4j.py
│  ├─ calculation_resolver.py
│  ├─ calculator.py
│  ├─ evaluate_rankings.py
│  ├─ evaluate_outcomes.py
│  └─ generate_report.py
├─ evaluation/v6/
│  ├─ 00_g0_inventory/
│  ├─ 01_g1_input/
│  ├─ 02_g1_label/
│  ├─ 03_g2_canonical/
│  ├─ 04_g3_a/
│  ├─ 05_g3_b/
│  ├─ 06_g3_c/
│  └─ 07_g4_report/
└─ artifacts/run_v6_full50/
```

V6는 기존 V5 container·schema를 수정하지 않는다. 새 Lab을 사용할 경우 권장 포트는 PostgreSQL `55434`, Neo4j Bolt `17689`, HTTP `17476`이다.

---

## 9. 단계별 명령 계약

실제 모듈 생성 후 다음 인터페이스를 고정한다.

```powershell
$env:PYTHONPATH = (Resolve-Path etl\fault_cases\NEW_ABC_TEST_V6\src)

python -m new_abc_test_v6.g0_inventory
python -m new_abc_test_v6.g1_build_inputs
python -m new_abc_test_v6.g1_validate_leakage
python -m new_abc_test_v6.g1_build_gold
python -m new_abc_test_v6.g2_build_canonical
python -m new_abc_test_v6.g2_project_postgresql
python -m new_abc_test_v6.g2_project_neo4j
python -m new_abc_test_v6.g2_validate_parity
python -m new_abc_test_v6.rank_a_pgvector
python -m new_abc_test_v6.rank_b_postgresql
python -m new_abc_test_v6.rank_c_neo4j
python -m new_abc_test_v6.evaluate_rankings
python -m new_abc_test_v6.evaluate_outcomes
python -m new_abc_test_v6.generate_report
```

각 명령은 선행 Gate manifest가 `passed=true`가 아니면 종료 코드 1로 중단한다.

---

## 10. 자동 검증 체크리스트

### 데이터 완전성

- [ ] query 50
- [ ] supervisor response 50
- [ ] completed facts 50
- [ ] gold outcome 50
- [ ] case_id 집합 4개 파일 완전 동일
- [ ] Gold final ratio 50건 모두 존재
- [ ] final ratio 합계 100

### 누출

- [ ] Runtime input의 Rule ID 0
- [ ] Runtime input의 `A30:B70` 형태 ratio 0
- [ ] Runtime input의 Gold PDF page 0
- [ ] Gold 파일을 변경해도 입력 SHA 불변

### 검색

- [ ] document vector 277 × 2560
- [ ] query vector 50 × 2560
- [ ] Top-50 2,500행
- [ ] 각 Case 후보 중복 0
- [ ] A/B/C candidate SHA 동일
- [ ] hard-negative를 positive relevance로 계산하지 않음

### 구조·계산

- [ ] Top-50 union UNMODELED 0
- [ ] Party mapping coverage 50/50
- [ ] Variant coverage 50/50
- [ ] Adjustment coverage 50/50
- [ ] LaneStep 필요 Case coverage 100%
- [ ] Gold 계산 단계와 Calculator 50/50 일치

### 평가

- [ ] A/B/C MRR@10/50 존재
- [ ] A/B/C nDCG@10/50 존재
- [ ] Rule Accuracy 분모 50
- [ ] Final Ratio Exact 분모 50
- [ ] Coverage와 conditional accuracy 분리
- [ ] B/C semantic parity 100%
- [ ] A/B/C 3회 결과 SHA 동일
- [ ] latency p50/p95/p99 존재

---

## 11. 사용자 보고·승인 지점

각 Gate 후 다음 내용을 보고하고 진행 여부를 묻는다.

| Gate | 보고 내용 | 사용자 판단이 필요한 경우 |
|---|---|---|
| G0 | 현재 50건 중 Gold 완성/미완성 목록 | 없음 |
| G1-INPUT | 50개 재질문 답변·Facts 완전성·누출 검사 | Scenario Truth 충돌 |
| G1-LABEL | Rule·비율 Gold 50건과 PDF Evidence | Case 교체, PDF 근거 충돌 |
| G2 | Canonical coverage·B/C parity | PDF 조건 해석 충돌 |
| G3-A | MRR/nDCG 기준선 | 없음 |
| G3-B | PostgreSQL 순위·Rule·비율·latency | 없음 |
| G3-C | Neo4j 순위·Rule·비율·latency·parity | 없음 |
| G4 | 최종 비교표·실패 원인·도입 판단 근거 | 최종 구조 선택 |

사용자가 직접 실행해야 하는 기본 과정은 없다. Docker Desktop 실행, 새 Lab container 생성, 로컬 파일 생성·적재는 이 프로젝트 범위 안에서 수행한다. 기존 DB 삭제·초기화, Case 교체, 충돌하는 Gold 정답 채택만 별도 승인을 받는다.

---

## 12. 완료 정의

다음이 모두 충족되어야 V6 실험을 완료라고 부른다.

1. 50개 기준 질문과 50개 Supervisor 응답을 모두 사용했다.
2. 50개 완료 Facts와 50개 PDF 검증 Gold Outcome이 1:1이다.
3. 모든 Gold Outcome에 Rule·Party mapping·Base·Adjustment·Final ratio·Evidence가 있다.
4. A/B/C가 동일 query vector와 동일 Top-50 후보를 사용했다.
5. A/B/C 모두 MRR·nDCG를 포함한 순위 지표가 있다.
6. B/C 모두 Rule·Party mapping·최종비율 정확도를 50개 전체 분모로 계산했다.
7. B/C parity와 latency·운영성·관계 확장성 비교가 있다.
8. 실패 Case 50건 전체가 원인 분류표에 들어간다.
9. 3회 재현성·누출·hard-negative·분모 검증이 모두 통과한다.
10. 최종 리포트가 수치표와 Case별 상세 결과를 모두 제공한다.

이 중 하나라도 빠지면 `incomplete`이며, 일부 Case 분모로 축소한 결과를 FULL-50 성능이라고 부르지 않는다.

---

## 13. 2026-07-20 실행 기록: 탐색 실행과 본실험의 구분

V6 입력 50개와 고정 Qwen Top-50을 사용해 격리 Lab PostgreSQL/Neo4j에서 A/B/C를 3회 실행했다. 결과 파일은 `evaluation/v6/05_g4_report/`에 있다.

| 항목 | 결과 |
|---|---|
| A MRR@50 / nDCG@50 | 0.2830 / 0.3915 |
| B MRR@50 / nDCG@50 | 0.3841 / 0.4531 |
| C MRR@50 / nDCG@50 | 0.3841 / 0.4531 |
| B/C Top-1 Exact Rule | 7/39 (17.9%) |
| A Top-1 Exact Rule | 5/39 (12.8%) |
| B/C 숫자 출력·정확 비율 | 7/33 · 3/33 |
| B/C parity·3회 재현성 | True · 통과 |

이 수치는 **G3 탐색 실행**이다. 50개 질문을 실제로 모두 실행했고 B/C는 각각 11건의 숫자를 계산했으나, Gold 50/50 PDF 검증과 Rule별 필요 Facts가 아직 충족되지 않았다. B/C의 `requires_fact` 12건과 `ambiguous_rule` 11건, 그리고 3/33 정확 비율 결과만으로 도입 판단을 해서는 안 된다. 본 문서 12장의 완료 정의는 아직 충족하지 못했고, 다음 작업은 PDF 조건·Supervisor Facts·Variant/Adjustment를 보강한 뒤 같은 Runner를 재실행하는 것이다.
