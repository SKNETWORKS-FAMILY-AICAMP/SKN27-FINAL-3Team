# NEW_ABC_TEST V5 실행 상태

## 결론

이 폴더의 **환경 구축·데이터 적재·A/B/C 실행·재현성·저장소 일관성 검증은 완료**되었다.
그러나 이를 근거로 `PostgreSQL` 또는 `Neo4j`를 선택하면 안 된다. 현재 결과는
**구조 원본을 적재했고 안전한 미확정을 확인한 사전 실행**이며, 최종 Rule/과실비율
정확도를 비교하는 본실험은 아직 성립하지 않는다.

## 실행 범위와 격리

- 신규 루트: `etl/fault_cases/NEW_ABC_TEST/`
- 신규 PostgreSQL: `localhost:55433`, DB `fault_standard_new_abc_test`
- 신규 Neo4j Bolt: `localhost:17688`
- 기존 프로젝트 PostgreSQL `5432` 및 기존 Neo4j에는 쓰지 않았다.
- Qwen 4B 2,560차원 벡터는 기존 고정 산출물 277건/질문 50건을 읽어 사용했다.
  모델을 다시 실행하거나 HNSW를 사용하지 않았으며, 검색은 `float32 exact cosine`이다.
- 사고 입력은 `evaluation/fault_standard/rule_matching_abc/v4/completed_accident_facts_v4.jsonl`의
  완료된 Supervisor 재질문 응답 50건을 사용한다. 이 파일은 Rule/기본·최종비율을 포함하지
  않는 `simulation_only` 입력이다.

## 실제 적재한 데이터

| 항목 | 수량 | 용도 |
|---|---:|---|
| 검색 Rule 벡터 | 277 | A/B/C 공통 의미검색 후보 생성 |
| 평가 질문 벡터 | 50 | 같은 입력 보장 |
| 각 질문 Top-50 | 2,500 | B/C가 동일하게 받는 후보 집합 |
| 후보·라벨 Rule Canonical | 244 | Rule/Evidence/하드 조건의 공통 기준 |
| PDF 구조 원본 프로필 | 3,266 | Party, BaseFault, Adjustment, Variant, PM/신호/차로/회전교차로 context 원본 행 |

네 PDF의 형식 차이는 단일 표로 강제 변환하지 않았다. 원본 추출 테이블의 행을 Rule별
프로필로 보존했고, PostgreSQL은 `new_abc.rule_profile` JSONB 행으로, Neo4j는
`(:NewAbcTestRule)-[:HAS_SOURCE_RECORD]->(:NewAbcTestSourceRecord)` 관계로 같은
내용을 적재했다.

## A/B/C 정의와 이번 실행값

> 아래의 초기 실행값은 이후 재실행으로 대체되었다. 최신 결과는
> `evaluation/v5/04_g4_report/g4_metrics.json`을 기준으로 한다: B/C는 945개 PDF 직접
> 조건으로 11건의 기본비율을 계산했지만, 평가상 false match 4건이 있어 본실험 통과가 아니다.

- **A**: 공통 Qwen exact cosine Top-1만 반환한다.
- **B**: 동일 Top-50에서 PostgreSQL의 승인된 하드 조건만 적용한다.
- **C**: 동일 Top-50에서 Neo4j의 동일 승인 하드 조건만 관계 질의로 적용한다.
- 검색 점수 가중치, 점수 합산, 리랭커, 후보별 비율 가중치는 사용하지 않았다.
- 계산기는 한 구현이어야 하지만, 승인된 Party 매핑·Variant·Adjustment 계약이 아직
  완성되지 않았으므로 숫자를 만들지 않고 `not_calculable`을 반환한다.

| 측정 | A | B | C |
|---|---:|---:|---:|
| Top-1/10/50 Rule 회수 | 5/39 · 22/39 · 36/39 | 동일 후보 사용 | 동일 후보 사용 |
| 선택 상태 | `retrieved_only` 50 | `ambiguous_rule` 11, `no_match` 39 | B와 동일 |
| 숫자 과실비율 출력 | 0 | 0 | 0 |
| 3회 반복 결과 | 동일 | 동일 | 동일 |

B/C가 같은 것은 오류가 아니다. 같은 Canonical·같은 하드 조건·같은 선택 규칙을
서로 다른 저장 방식으로 실행했으므로 **결정 결과가 같아야** 한다. 차이는 이번처럼
관계가 단순할 때는 지연시간과 표현력뿐이며, Neo4j의 가치 평가는 Party→행동→차로
경로→Variant처럼 다단 관계가 실제 하드 조건으로 승인된 뒤에만 가능하다.

## 검증 결과

`validate_run.py` 12/12 통과:

- 50 Facts와 50 labels의 case set 일치
- 모든 case가 정확히 Top-50, 총 2,500 후보, case 내 중복 없음
- PostgreSQL 문서 277/질문 50/조건 244 적재
- Neo4j `REQUIRES_FACT` 관계 244개가 PostgreSQL 조건 244개와 일치
- B/C의 의미적 결과 일치

## 왜 본실험 결과가 아직 아닌가

1. `3,266`개의 원본 프로필은 **보존**되어 있으나, 각 필드를 Supervisor Facts의 어떤
   표준 코드와 비교할지에 대한 승인된 정규화 계약이 없다.
2. 현재 Facts는 기존 질문과 완료된 Supervisor 재질문 응답을 합친 값이다. 정답 Rule/비율을
   보고 사실을 채우지 않았으므로 정답 누출은 없다.
3. G1의 `verified_outcomes`는 기존 qrels 기반 scaffold다. Facts가 고정된 후 PDF 근거로
   독립 검증한 최종 hidden label이라고 주장할 수 없다.
4. 따라서 Rule 단위 `PartyRole / BaseFault / Variant / Adjustment / LaneStep` 계산 계약을
   승인하기 전 숫자 비율을 내면, PDF 근거 없이 계산한 결과가 된다.

## 다음에 필요한 승인 작업

이 실험 폴더에서 계속할 때는 아래 순서만 허용한다.

1. `Fact Dictionary`에 PM, 보행자, 차량, 선후진입, 신호, 차로 단계, 수정요소의 표준
   코드와 `unknown` 정책을 확정한다.
2. 4개 PDF 형식별 프로필 필드를 그 Fact 코드로 매핑한다. 매핑마다 PDF 페이지/원본행을
   근거로 기록하고, 근거가 없으면 하드 조건으로 승격하지 않는다.
3. Facts/qrels 분리 상태에서 Supervisor 보충 입력을 만들고, 이후에만 독립 PDF label을
   확정한다.
4. 같은 후보·같은 Facts·같은 `calculator.py`로 G2→G4를 재실행한다.

그 전까지의 올바른 결론은 **Neo4j 도입 판단 보류**다.
