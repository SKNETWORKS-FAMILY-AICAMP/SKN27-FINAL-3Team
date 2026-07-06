# PM 대 자동차 사고 과실비율 비정형 기준 전처리 컬럼 설계안

대상 파일: `!!210624_PM대자동차사고과실비율비정형기준_송부(2021).pdf`  
목표: PM 대 자동차 사고 기준서를 단순 텍스트가 아니라 **PM 사고 전용 과실비율 룰북**으로 구조화한다.

---

## 1. 결론

이 파일은 일반 자동차 과실기준보다 더 세밀하게 봐야 한다.

이유는 다음이다.

```text
자동차 vs 자동차 기준이 아니라
PM vs 자동차 기준이다.

따라서 A/B 비율만 뽑으면 부족하고,
PM이 A인지 B인지,
자동차가 A인지 B인지,
PM이 어디로 통행했는지,
자전거도로가 있었는지,
보도/횡단보도/자전거횡단도인지,
PM을 타고 있었는지 끌고 있었는지,
도로교통법상 개인형이동장치 정의에 들어가는지
같은 PM 전용 컬럼이 필요하다.
```

이 파일의 저장 단위는 `도표1`부터 `도표38`까지의 **도표 단위 rule JSON**이 적절하다.

예시 파일명:

```text
도표01_자동차신호위반사고.json
도표02_PM신호위반사고.json
도표14_직진대좌회전사고.json
도표28_PM중앙선침범사고.json
도표32_자동차진로변경사고.json
도표36_PM보도통행사고.json
도표38_개문중사고.json
```

---

## 2. PM 기준서 구조 분석

### 2.1 목차 구조

이 PDF는 목차상 `도표1`부터 `도표38`까지 구성되어 있다.

큰 흐름은 다음과 같다.

```text
도표1~5   : 신호위반 사고
도표6~9   : 신호기 없는 교차로, 우측/좌측 도로, 대로/소로 사고
도표10~11 : 일방통행 위반 사고
도표12~17 : 직진, 좌회전, 우회전 사고
도표18~20 : 정체도로 급진입, 보도/자전거횡단도 관련 사고
도표21~24 : 선행/후행, 우회전, 추월, 좌회전 사고
도표25~27 : 자전거횡단도, 횡단보도 사고
도표28~30 : 중앙선 침범, 차도가 아닌 장소에서 진입 사고
도표31~34 : 진로변경, 추돌 사고
도표35~38 : 자전거도로, 보도 통행, 주정차 추돌, 개문 사고
```

---

### 2.2 본문 앞 설명 구조

상세 도표 전에 다음 설명 section이 있다.

```text
1. 개요
2. 적용범위
3. 용어 정의
4. 수정요소의 해설
```

이 부분도 버리면 안 된다.  
특히 `적용범위`, `PM 정의`, `PM을 끌고 가는 경우는 보행자에 해당한다`, `자전거도로`, `자전거횡단도`, `보도`, `교차로`, `신호기`, `자동차`, `개인형 이동장치` 정의가 rule 해석에 필요하다.

따라서 설명 section은 rule은 아니지만 `sections.jsonl`로 따로 저장한다.

---

### 2.3 도표 본문 공통 구조

각 도표는 대체로 아래 구조를 가진다.

```text
도표 번호 / 제목
기본과실 A xx : B yy
사고상황
  PM A : ...
  자동차 B : ...
수정요소 A B
  A ...
  B ...
[도표해설]
  사고상황
  기본과실 해설
  수정요소 해설
[관련법규]
[참고판례 또는 심의결정사례]
```

예를 들어 `도표28 PM 중앙선 침범 사고`는 `PM A : 중앙선 침범`, `자동차 B : 직진`, 기본과실 `A 100 B 0` 구조를 가진다.  
`도표32 자동차 진로변경 사고`는 `PM A : 직진`, `자동차 B : 좌 또는 우로 진로변경`, 기본과실 `A 10 : B 90` 구조를 가진다.

---

## 3. 저장 파일 방향

### 3.1 페이지별 JSON은 저장하지 않는다

페이지별 JSON은 이 데이터의 핵심 단위가 아니다.  
페이지는 누락 검증만 한다.

```json
{
  "source_file": "!!210624_PM대자동차사고과실비율비정형기준_송부(2021).pdf",
  "expected_page_count": 80,
  "read_page_count": 80,
  "missing_pages": [],
  "status": "success"
}
```

---

### 3.2 도표 제목 기반 JSON 저장

실제 저장 단위는 도표별 JSON이다.

```text
processed/traffic_ratio_stand/2021_pm_vs_auto_nontypical_rulebook/
├─ 01_overview/
├─ 02_scope/
├─ 03_terms/
├─ 04_adjustment_factor_explanation/
├─ 05_detailed_fault_ratio_standards/
│  ├─ 01_signal_violation/
│  │  ├─ 도표01_자동차신호위반사고.json
│  │  ├─ 도표02_PM신호위반사고.json
│  │  └─ ...
│  ├─ 02_unsignalized_intersection/
│  ├─ 03_one_way_violation/
│  ├─ 04_straight_left_right_turn/
│  ├─ 05_crossing_and_sidewalk/
│  ├─ 06_centerline_and_road_entry/
│  ├─ 07_lane_change_and_rear_end/
│  └─ 08_bicycle_road_sidewalk_door_opening/
└─ 99_tables_for_db/
```

DB 적재용은 별도 JSONL로 만든다.

```text
99_tables_for_db/
├─ rulebooks.jsonl
├─ sections.jsonl
├─ rules.jsonl
├─ parties.jsonl
├─ base_faults.jsonl
├─ pm_contexts.jsonl
├─ road_contexts.jsonl
├─ adjustment_factors.jsonl
├─ rule_blocks.jsonl
├─ law_refs.jsonl
├─ reference_cases.jsonl
├─ diagrams.jsonl
├─ chunks.jsonl
└─ parse_quality_report.jsonl
```

---

## 4. rule JSON 최상위 구조

도표별 JSON은 다음 구조를 추천한다.

```json
{
  "metadata": {},
  "hierarchy": {},
  "rule_identity": {},
  "applicability": {},
  "accident_classification": {},
  "parties": [],
  "pm_context": {},
  "vehicle_context": {},
  "road_context": {},
  "signal_context": {},
  "base_fault": {},
  "adjustment_factors": [],
  "blocks": [],
  "law_refs": [],
  "reference_cases": [],
  "diagram": {},
  "texts": {},
  "cleaning_quality": {},
  "parse_quality": {}
}
```

---

## 5. metadata 컬럼

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `rule_id` | string | 내부 고유 ID | `pm_auto_2021_도표28` |
| `source_type` | string | 데이터 유형 | `fault_standard` |
| `source_subtype` | string | 세부 출처 | `pm_auto_2021` |
| `source_reliability` | string | 신뢰도 | `official_standard` |
| `source_file` | string | 원본 PDF명 | `!!210624_PM대자동차사고과실비율비정형기준_송부(2021).pdf` |
| `published_year` | int | 발간 연도 | `2021` |
| `preprocessing_version` | string | 전처리 버전 | `pm_auto_2021_v1.0` |
| `file_hash` | string | 원본 파일 hash | `sha256...` |
| `page_start` | int | 도표 시작 페이지 | `58` |
| `page_end` | int | 도표 종료 페이지 | `59` |
| `page_count_checked` | bool | 페이지 수 검증 여부 | `true` |
| `missing_pages` | list[int] | 누락 페이지 | `[]` |

---

## 6. hierarchy 컬럼

PM 기준서는 도표 중심이므로 hierarchy는 다음 정도로 저장한다.

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `document_title` | string | 문서 제목 | `PM 대 자동차 사고 과실비율 비정형 기준` |
| `section_no` | string | 목차 section 번호 | `5` 또는 null |
| `section_title` | string | 상세 기준 section | `세부유형별 과실비율 적용기준` |
| `category_no` | string | 묶음 번호 | `07` |
| `category_title` | string | 사고유형 묶음 | `진로변경 및 추돌 사고` |
| `chart_no` | int | 도표 번호 | `28` |
| `chart_ref` | string | 도표 코드 | `도표28` |
| `section_path` | list[string] | 전체 경로 | `["PM 대 자동차 사고 과실비율 비정형 기준", "세부유형별 과실비율 적용기준", "중앙선 침범 및 차도 진입 사고", "도표28 PM 중앙선 침범 사고"]` |

예시:

```json
{
  "document_title": "PM 대 자동차 사고 과실비율 비정형 기준",
  "section_title": "세부유형별 과실비율 적용기준",
  "category_title": "중앙선 침범 및 차도 진입 사고",
  "chart_no": 28,
  "chart_ref": "도표28",
  "section_path": [
    "PM 대 자동차 사고 과실비율 비정형 기준",
    "세부유형별 과실비율 적용기준",
    "중앙선 침범 및 차도 진입 사고",
    "도표28 PM 중앙선 침범 사고"
  ]
}
```

---

## 7. rule_identity 컬럼

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `chart_no` | int | 도표 번호 | `32` |
| `chart_code` | string | 도표 코드 | `도표32` |
| `rule_title` | string | 도표 제목 | `자동차 진로변경 사고` |
| `rule_title_clean` | string | 파일명용 제목 | `자동차진로변경사고` |
| `rule_type` | string | 기준 유형 | `pm_vs_vehicle` |
| `chart_group` | string | 사고 묶음 | `lane_change` |
| `has_related_charts` | bool | 인접 도표 관계 여부 | `true` |
| `related_chart_refs` | list[string] | 관련 도표 | `["도표31", "도표33", "도표34"]` |

---

## 8. applicability 컬럼

PM 기준서는 적용범위가 중요하다.  
특히 PM을 끌고 가는 경우는 보행자에 해당하므로 이 기준을 적용하지 않는다.

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `applies_to` | string | 적용 대상 | `car_vs_pm_accident` |
| `pm_must_be_riding` | bool | PM 탑승 상태 필요 여부 | `true` |
| `pm_dismounted_excluded` | bool | 끌고 가는 경우 제외 | `true` |
| `pm_legal_definition_required` | bool | 도로교통법상 PM 정의 필요 | `true` |
| `pm_speed_limit_condition` | string | PM 속도 조건 | `25km/h 이상 작동 제한` |
| `pm_weight_condition` | string | PM 중량 조건 | `30kg 미만` |
| `included_pm_examples` | list[string] | 포함 예시 | `["전동킥보드", "전동외륜보드", "전동이륜평행차", "전동스케이트보드"]` |
| `excluded_cases` | list[string] | 제외 케이스 | `["PM을 끌고 가는 경우"]` |

---

## 9. accident_classification 컬럼

사고유형 분류용 컬럼이다.

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `accident_group` | string | 대분류 | `교차로`, `횡단보도`, `자전거횡단도`, `진로변경`, `추돌`, `개문` |
| `accident_subgroup` | string | 중분류 | `신호위반`, `신호기 없음`, `중앙선 침범`, `차도 진입` |
| `collision_pattern` | string | 충돌 패턴 | `straight_vs_left_turn`, `lane_change`, `rear_end`, `door_opening` |
| `movement_relation` | string | 이동 관계 | `perpendicular`, `opposite_direction`, `same_direction`, `crossing` |
| `violation_actor` | string | 위반 주체 | `pm`, `car`, `both`, `none` |
| `primary_violation` | string | 핵심 위반 | `signal_violation`, `centerline_violation`, `sidewalk_driving` |
| `priority_basis` | string | 통행우선 판단 기준 | `signal`, `right_side_priority`, `main_road`, `straight_priority`, `safe_distance` |
| `is_signalized` | bool | 신호기 있음 여부 | `true` |
| `is_unsignalized` | bool | 신호기 없음 여부 | `false` |
| `is_intersection_case` | bool | 교차로 사고 여부 | `true` |
| `is_crossing_case` | bool | 횡단 관련 사고 여부 | `false` |
| `is_lane_change_case` | bool | 진로변경 사고 여부 | `false` |
| `is_rear_end_case` | bool | 추돌 사고 여부 | `false` |

---

## 10. parties 컬럼

PM 기준서는 `A/B`만으로 부족하다.  
반드시 `PM인지 자동차인지`를 함께 저장해야 한다.

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `party_key` | string | A/B | `A` |
| `party_label` | string | 원문 라벨 | `PM A` |
| `party_type` | string | 유형 | `pm`, `car` |
| `movement` | string | 이동 행위 | `직진`, `좌회전`, `우회전`, `진로변경`, `추돌`, `개문` |
| `signal_state` | string | 신호 상태 | `녹색`, `황색`, `적색`, `신호없음` |
| `road_position` | string | 위치 | `차도`, `보도`, `자전거도로`, `횡단보도`, `자전거횡단도` |
| `lane_position` | string | 차로/통행 위치 | `도로 우측 가장자리`, `좌측통행`, `차로 중앙통행` |
| `direction_relation` | string | 진행 방향 관계 | `같은 방향`, `대향`, `좌측 도로`, `우측 도로` |
| `entry_timing` | string | 진입 시점 | `선진입`, `후진입`, `급진입` |
| `violation_type` | string | 위반 유형 | `신호위반`, `중앙선 침범`, `보도 통행`, `일방통행 위반` |
| `raw_text` | string | 원문 | `PM A : 중앙선 침범` |

예시:

```json
[
  {
    "party_key": "A",
    "party_label": "PM A",
    "party_type": "pm",
    "movement": "직진",
    "road_position": "차도",
    "raw_text": "PM A : 직진"
  },
  {
    "party_key": "B",
    "party_label": "자동차 B",
    "party_type": "car",
    "movement": "좌 또는 우로 진로변경",
    "raw_text": "자동차 B : 좌 또는 우로 진로변경"
  }
]
```

---

## 11. pm_context 컬럼

PM 전용 컬럼이다.  
이 파일에서 가장 중요하게 추가해야 할 부분이다.

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `pm_party_key` | string | PM이 A/B 중 어디인지 | `A` |
| `pm_action` | string | PM 행동 | `직진`, `중앙선 침범`, `보도 통행`, `횡단보도 횡단` |
| `pm_road_position` | string | PM 위치 | `차도`, `보도`, `자전거도로`, `자전거횡단도`, `횡단보도` |
| `pm_lane_position` | string | PM 통행 위치 | `우측 가장자리`, `좌측통행`, `차로 중앙통행` |
| `pm_signal_state` | string | PM 관련 신호 | `녹색`, `적색`, `황색`, `보행자 적색`, null |
| `pm_riding_state` | string | PM 탑승 여부 | `riding`, `dismounted` |
| `pm_near_bicycle_road` | bool | 인근 자전거도로 여부 | `true` |
| `pm_bicycle_road_distance_rule` | string | 인근 거리 기준 | `대략 10m 이내` |
| `pm_left_side_travel` | bool | 좌측통행 여부 | `true` |
| `pm_sidewalk_travel` | bool | 보도 통행 여부 | `true` |
| `pm_crosswalk_travel` | bool | 횡단보도 통행 여부 | `true` |
| `pm_bicycle_crossing_travel` | bool | 자전거횡단도 통행 여부 | `true` |
| `pm_centerline_violation` | bool | 중앙선 침범 여부 | `true` |
| `pm_one_way_violation` | bool | 일방통행 위반 여부 | `true` |
| `pm_lane_change` | bool | PM 진로변경 여부 | `true` |
| `pm_rear_end` | bool | PM 추돌 여부 | `true` |
| `pm_sudden_entry` | bool | PM 급진입 여부 | `true` |
| `pm_noticeability_issue` | bool | 자동차가 PM을 발견하기 어려운 사정 | `true` |
| `pm_vulnerability_basis` | string | PM 피해위험 근거 | `충돌 시 전도 및 피해 확대 위험` |

---

## 12. vehicle_context 컬럼

자동차 측 전용 컬럼이다.

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `car_party_key` | string | 자동차가 A/B 중 어디인지 | `B` |
| `car_action` | string | 자동차 행동 | `직진`, `좌회전`, `우회전`, `진로변경`, `개문` |
| `car_signal_state` | string | 자동차 신호 | `녹색`, `황색`, `적색`, null |
| `car_road_position` | string | 자동차 위치 | `차도`, `대로`, `소로`, `차도가 아닌 장소` |
| `car_lane_change` | bool | 자동차 진로변경 여부 | `true` |
| `car_door_opening` | bool | 개문 여부 | `true` |
| `car_rear_end` | bool | 자동차 추돌 여부 | `true` |
| `car_entering_bicycle_road` | bool | 자전거도로 진입 여부 | `true` |
| `car_entering_from_non_road` | bool | 차도가 아닌 장소에서 진입 | `true` |
| `car_notice_duty_basis` | string | 자동차 주의의무 근거 | `PM과 충돌 시 피해 확대 위험` |

---

## 13. road_context 컬럼

도로와 교통환경을 저장한다.

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `road_area` | string | 도로 영역 | `교차로`, `보도`, `자전거도로`, `횡단보도`, `차도`, `차도가 아닌 장소` |
| `intersection_type` | string | 교차로 유형 | `사거리`, `T자`, null |
| `traffic_control` | string | 교통정리 여부 | `signalized`, `unsignalized`, `flash_signal` |
| `road_width_relation` | string | 도로폭 관계 | `same_width`, `main_vs_side`, `left_vs_right` |
| `main_road_party` | string | 대로 진행 주체 | `A`, `B`, null |
| `side_road_party` | string | 소로 진행 주체 | `A`, `B`, null |
| `right_side_party` | string | 우측도로 진행 주체 | `A`, `B`, null |
| `left_side_party` | string | 좌측도로 진행 주체 | `A`, `B`, null |
| `bicycle_road_exists` | bool | 자전거도로 존재 | `true` |
| `bicycle_road_nearby` | bool | 인근 자전거도로 | `true` |
| `bicycle_crossing_exists` | bool | 자전거횡단도 존재 | `true` |
| `crosswalk_exists` | bool | 횡단보도 존재 | `true` |
| `sidewalk_exists` | bool | 보도 존재 | `true` |
| `one_way_road` | bool | 일방통행 여부 | `true` |
| `centerline_exists` | bool | 중앙선 존재 | `true` |
| `parked_or_stopped_context` | bool | 주정차 관련 여부 | `true` |
| `visibility_issue` | bool | 시야장애 여부 | `true` |
| `night_or_bad_weather` | bool | 야간/악천후 | `true` |

---

## 14. signal_context 컬럼

PM 기준서는 신호 관련 도표가 많으므로 별도 컬럼을 둔다.

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `has_signal` | bool | 신호기 있음 | `true` |
| `signal_control_type` | string | 신호 유형 | `normal`, `yellow_flash`, `red_flash`, `none` |
| `pm_signal_source` | string | PM이 따를 신호 | `vehicle_signal`, `pedestrian_signal`, `bicycle_signal` |
| `car_signal_source` | string | 자동차가 따를 신호 | `vehicle_signal` |
| `pm_signal_state` | string | PM 신호 | `red` |
| `car_signal_state` | string | 자동차 신호 | `green` |
| `both_signal_violation` | bool | 양측 신호위반 | `true` |
| `signal_violation_party` | string | 신호위반 주체 | `pm`, `car`, `both` |

---

## 15. base_fault 컬럼

대부분 A:B 비율로 나온다.

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `base_fault_type` | string | 비율 유형 | `pair_ratio` |
| `party_a_ratio` | int | A 과실 | `100` |
| `party_b_ratio` | int | B 과실 | `0` |
| `pm_ratio` | int | PM 과실 | `100` |
| `car_ratio` | int | 자동차 과실 | `0` |
| `normalized_ratio` | string | A:B 정규화 | `100:0` |
| `pm_car_normalized_ratio` | string | PM:자동차 정규화 | `100:0` |
| `raw_text` | string | 원문 | `기본과실 A 100 B 0` |
| `is_pm_heavier_fault` | bool | PM 과실이 더 큰지 | `true` |
| `is_car_heavier_fault` | bool | 자동차 과실이 더 큰지 | `false` |
| `is_one_sided_fault` | bool | 일방과실 여부 | `true` |

PM 기준서는 A/B가 항상 PM/자동차 순서라고 단정하면 안 된다.  
따라서 `party_a_ratio`, `party_b_ratio`와 별도로 `pm_ratio`, `car_ratio`를 저장해야 한다.

---

## 16. adjustment_factors 컬럼

PM 기준서의 수정요소는 PM 전용 요소와 자동차 전용 요소가 섞인다.

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `adjustment_id` | string | 수정요소 ID | `adj_pm_auto_2021_도표32_001` |
| `target_party_key` | string | A/B | `A` |
| `target_party_type` | string | PM/자동차 | `pm` |
| `factor_name` | string | 수정요소명 | `인근에 자전거 도로가 있는 경우` |
| `factor_category` | string | 수정요소 분류 | `bicycle_road_context` |
| `delta` | int/null | 가감 수치 | `5` |
| `delta_direction` | string | 증가/감소/비적용 | `increase` |
| `raw_delta` | string | 원문 수치 | `+5` |
| `raw_text` | string | 원문 | `A 인근에 자전거 도로가 있는 경우 +5` |
| `condition_text` | string | 조건 설명 | `인근에 자전거도로가 있는 경우 PM의 과실 가산` |
| `explanation_text` | string | 해설 | `자전거도로가 있는 경우에는 이곳에서 PM을 운행하여야 하므로...` |
| `is_pm_specific` | bool | PM 전용 수정요소 여부 | `true` |

### 16.1 수정요소 카테고리 추천

| category | 예시 |
|---|---|
| `visibility` | 야간, 기타 시야장애 |
| `bicycle_road_context` | 인근에 자전거도로가 있는 경우 |
| `pm_left_side_travel` | PM 좌측통행 |
| `pm_sidewalk_travel` | PM 보도 통행 |
| `pm_crosswalk_behavior` | PM 횡단보도 급진입 |
| `signal_behavior` | 신호불이행, 신호지연 |
| `lane_change_behavior` | 급 진로변경, 진로변경 금지 |
| `turning_behavior` | 급 좌회전, 급 우회전, 기 좌회전 |
| `speed_behavior` | 서행불이행, 감속불이행, 과속 |
| `severe_fault` | 현저한 과실, 중과실 |
| `priority` | 명확한 선진입, 대로/소로 |
| `door_opening` | 개문 관련 |
| `rear_end` | 추돌 관련 |

---

## 17. blocks 컬럼

도표 내부 텍스트는 block으로 나눈다.

| block_type | 설명 |
|---|---|
| `chart_header` | 도표 번호와 제목 |
| `base_fault` | 기본과실 |
| `accident_situation_short` | 표 상단 사고상황 |
| `adjustment_factor_table` | 수정요소 표 |
| `diagram_explanation` | `[도표해설]` 전체 |
| `accident_situation_explanation` | 도표해설 안 사고상황 |
| `base_fault_explanation` | 기본과실 해설 |
| `adjustment_explanation` | 수정요소 해설 |
| `related_law` | 관련법규 |
| `reference_case` | 참고판례/판례 |
| `review_case` | 심의결정사례 |
| `definition_or_scope` | 개요/적용범위/용어정의 section |
| `adjustment_factor_general_explanation` | 수정요소의 해설 section |

---

## 18. law_refs 컬럼

| 컬럼명 | 타입 | 설명 |
|---|---|---|
| `law_ref_id` | string | 법령 ID |
| `rule_id` | string/null | 연결 rule |
| `section_id` | string/null | 연결 section |
| `law_name` | string | 법령명 |
| `article` | string | 조문 |
| `paragraph` | string | 항 |
| `item` | string | 호 |
| `raw_text` | string | 원문 |
| `context` | string | 주변 문맥 |

PM 기준서에서 자주 연결될 수 있는 법령 예시는 다음이다.

```text
도로교통법 제2조
도로교통법 제5조
도로교통법 제13조
도로교통법 제13조의2
도로교통법 제14조
도로교통법 제18조
도로교통법 제25조
도로교통법 제31조
도로교통법 제37조
도로교통법 제38조
```

---

## 19. reference_cases / review_cases 컬럼

PM 기준서는 판례뿐 아니라 설명 section 안의 판례 인용도 있다.  
또 경우에 따라 심의결정사례 성격의 문장도 분리할 수 있다.

| 컬럼명 | 타입 | 설명 |
|---|---|---|
| `case_ref_id` | string | 사례 ID |
| `rule_id` | string/null | 연결 rule |
| `section_id` | string/null | 연결 section |
| `case_type` | string | `court_case`, `review_case` |
| `court_name` | string | 법원명 |
| `decision_date` | string | 선고일 |
| `case_number` | string | 사건번호 |
| `raw_text` | string | 원문 |
| `summary_text` | string | 사례 요약 |
| `fault_ratio_in_case` | string | 사례 속 과실비율 |
| `context` | string | 주변 문맥 |

---

## 20. diagram 컬럼

도표가 핵심이므로 이미지 메타데이터를 남겨두는 것이 좋다.

| 컬럼명 | 타입 | 설명 |
|---|---|---|
| `has_diagram` | bool | 도표 이미지 존재 여부 |
| `diagram_page` | int | 도표 페이지 |
| `diagram_caption` | string | 도표 제목 |
| `diagram_text_summary` | string | 그림 주변 텍스트 요약 |
| `diagram_image_path` | string/null | 이미지 crop 저장 경로 |
| `diagram_bbox` | list/null | crop 좌표 |

초기에는 이미지 crop을 하지 않아도 된다.  
다만 나중에 도표 이미지 기반 분석을 할 수 있도록 컬럼은 남겨두는 것이 좋다.

---

## 21. texts 컬럼

원문 추적과 전처리 검증을 위해 텍스트는 3단계로 저장한다.

| 컬럼명 | 설명 |
|---|---|
| `raw_text` | PDF에서 읽은 원문 |
| `clean_text` | 페이지 번호, 헤더, 불필요 공백 정리 |
| `structured_text` | rule 파싱을 위해 비율/제목/블록을 정리한 텍스트 |

예시:

```json
{
  "raw_text": "기본\n과실 A 60 B 40",
  "clean_text": "기본과실 A 60 B 40",
  "structured_text": "기본과실 A 60 : B 40"
}
```

---

## 22. 클리닝 작업 설계

PM 기준서는 PDF 추출 과정에서 줄바꿈과 표 구조가 자주 깨진다.  
따라서 단순 특수문자 제거가 아니라 **PM 기준 해석에 필요한 문자는 보존하고 PDF 노이즈만 제거**해야 한다.

### 22.1 제거할 텍스트

```text
페이지 번호
목차 점선
반복 header/footer
2칸 이상 반복 공백
의미 없는 빈 줄
```

### 22.2 보존해야 하는 기호

```text
+
-
:
~
( )
[ ]
A
B
PM
·
對
```

`對`는 원문 보존용 raw_text에는 유지하고, structured_text에서는 `대`로 정규화한다.

### 22.3 정규화할 표현

| 원문 | 정규화 |
|---|---|
| `對` | `대` |
| `기본\n과실` | `기본과실` |
| `사고\n상황` | `사고상황` |
| `수정\n요소` | `수정요소` |
| `A 100 B 0` | `A 100 : B 0` |
| `야간 기타 시야장애` | `야간·기타 시야장애` |
| `자전거 도로` | `자전거도로` |
| `개인형 이동장치` | `개인형이동장치` |
| `전동 킥보드` | `전동킥보드` |

### 22.4 자동 수정 금지

사고 구조가 바뀔 수 있는 단어는 자동 수정하지 않는다.

```text
직진
좌회전
우회전
유턴
일방통행
중앙선
보도
차도
자전거도로
자전거횡단도
횡단보도
개문
추돌
```

애매하면 원문을 유지하고 `needs_manual_review_reason`에 기록한다.

---

## 23. chunks 컬럼

검색/RAG용 chunk다.  
chunk는 rule 전체가 아니라 block 기준으로 만든다.

| 컬럼명 | 설명 |
|---|---|
| `chunk_id` | chunk ID |
| `rule_id` | 연결 rule |
| `block_id` | 연결 block |
| `chunk_type` | 사고상황, 기본과실 해설, 수정요소 해설 등 |
| `chunk_text` | 검색용 텍스트 |
| `chart_no` | 도표 번호 |
| `rule_title` | 도표 제목 |
| `section_path` | 목차 경로 |
| `pm_party_key` | PM A/B |
| `car_party_key` | 자동차 A/B |
| `pm_ratio` | PM 과실 |
| `car_ratio` | 자동차 과실 |
| `accident_tags` | 사고 태그 |
| `source_reliability` | `official_standard` |

---

## 24. quality 컬럼

| 컬럼명 | 설명 |
|---|---|
| `parse_status` | `valid`, `review_required`, `failed` |
| `page_count_checked` | 전체 페이지 수 검증 여부 |
| `missing_pages` | 누락 페이지 |
| `chart_no_detected` | 도표 번호 추출 여부 |
| `title_detected` | 제목 추출 여부 |
| `base_fault_detected` | 기본과실 추출 여부 |
| `party_detected` | PM/자동차 당사자 추출 여부 |
| `pm_party_detected` | PM A/B 추출 여부 |
| `car_party_detected` | 자동차 A/B 추출 여부 |
| `adjustment_factor_detected` | 수정요소 추출 여부 |
| `law_ref_detected` | 법령 추출 여부 |
| `block_split_success` | block 분리 성공 여부 |
| `needs_manual_review_reason` | 검수 필요 사유 |

---

## 25. 최종 rule JSON 예시: 도표28 PM 중앙선 침범 사고

```json
{
  "metadata": {
    "rule_id": "pm_auto_2021_도표28",
    "source_type": "fault_standard",
    "source_subtype": "pm_auto_2021",
    "source_reliability": "official_standard",
    "source_file": "!!210624_PM대자동차사고과실비율비정형기준_송부(2021).pdf",
    "published_year": 2021,
    "page_start": 58,
    "page_end": 59
  },
  "hierarchy": {
    "document_title": "PM 대 자동차 사고 과실비율 비정형 기준",
    "section_title": "세부유형별 과실비율 적용기준",
    "category_title": "중앙선 침범 및 차도 진입 사고",
    "chart_no": 28,
    "chart_ref": "도표28"
  },
  "rule_identity": {
    "chart_code": "도표28",
    "rule_title": "PM 중앙선 침범 사고",
    "rule_type": "pm_vs_vehicle",
    "chart_group": "centerline_violation"
  },
  "applicability": {
    "applies_to": "car_vs_pm_accident",
    "pm_must_be_riding": true,
    "pm_dismounted_excluded": true,
    "pm_legal_definition_required": true
  },
  "accident_classification": {
    "accident_group": "중앙선 침범",
    "collision_pattern": "opposite_direction_collision",
    "movement_relation": "opposite_direction",
    "violation_actor": "pm",
    "primary_violation": "centerline_violation"
  },
  "parties": [
    {
      "party_key": "A",
      "party_label": "PM A",
      "party_type": "pm",
      "movement": "중앙선 침범",
      "violation_type": "중앙선 침범",
      "raw_text": "PM A : 중앙선 침범"
    },
    {
      "party_key": "B",
      "party_label": "자동차 B",
      "party_type": "car",
      "movement": "직진",
      "raw_text": "자동차 B : 직진"
    }
  ],
  "pm_context": {
    "pm_party_key": "A",
    "pm_action": "중앙선 침범",
    "pm_centerline_violation": true
  },
  "vehicle_context": {
    "car_party_key": "B",
    "car_action": "직진"
  },
  "base_fault": {
    "base_fault_type": "pair_ratio",
    "party_a_ratio": 100,
    "party_b_ratio": 0,
    "pm_ratio": 100,
    "car_ratio": 0,
    "normalized_ratio": "100:0",
    "pm_car_normalized_ratio": "100:0",
    "raw_text": "기본과실 A 100 B 0",
    "is_pm_heavier_fault": true,
    "is_one_sided_fault": true
  },
  "adjustment_factors": [
    {
      "target_party_key": "A",
      "target_party_type": "pm",
      "factor_name": "추월금지 장소 추월",
      "factor_category": "centerline_or_passing_violation",
      "delta": 10,
      "delta_direction": "increase",
      "raw_text": "A 추월금지 장소 추월 +10"
    },
    {
      "target_party_key": "B",
      "target_party_type": "car",
      "factor_name": "현저한 과실",
      "factor_category": "severe_fault",
      "delta": 10,
      "delta_direction": "increase",
      "raw_text": "B 현저한 과실 +10"
    }
  ],
  "texts": {
    "raw_text": "...",
    "clean_text": "...",
    "structured_text": "..."
  },
  "quality": {
    "parse_status": "valid",
    "chart_no_detected": true,
    "base_fault_detected": true,
    "pm_party_detected": true,
    "car_party_detected": true
  }
}
```

---

## 26. 최종 DB 적재용 JSONL

Nested JSON은 사람이 검토하기 위한 파일이고, DB에는 아래처럼 나눠 넣는 것이 좋다.

```text
rulebooks.jsonl
sections.jsonl
rules.jsonl
parties.jsonl
base_faults.jsonl
pm_contexts.jsonl
vehicle_contexts.jsonl
road_contexts.jsonl
signal_contexts.jsonl
adjustment_factors.jsonl
rule_blocks.jsonl
law_refs.jsonl
reference_cases.jsonl
diagrams.jsonl
chunks.jsonl
parse_quality_report.jsonl
```

---

## 27. 최종 결론

PM 대 자동차 기준서에서 공통적으로 추가로 뽑아야 할 컬럼은 다음이다.

```text
PM이 A/B 중 어디인지
자동차가 A/B 중 어디인지
PM 탑승 여부
PM이 도로교통법상 개인형이동장치 정의에 해당하는지
PM을 끌고 가는 경우 제외 여부
PM 통행 위치
PM 좌측통행 여부
PM 보도 통행 여부
PM 자전거도로/자전거횡단도/횡단보도 관련 여부
인근 자전거도로 존재 여부
자전거도로 거리 기준
자동차 행동
교통정리 여부
신호 상태
대로/소로/좌측도로/우측도로
중앙선/일방통행/진로변경/추돌/개문 여부
PM 과실비율과 자동차 과실비율
PM 전용 수정요소
자동차 전용 수정요소
도표해설 block
관련법규
판례/심의사례
도표 이미지 메타데이터
클리닝 품질
파싱 품질
```

따라서 이 파일은 단순히 `도표번호`, `제목`, `기본과실`, `수정요소`만 저장하면 부족하다.

한 줄로 정리하면 다음과 같다.

```text
PM 기준서는 “A:B 과실비율표”가 아니라 “PM의 통행 위치, 법적 정의, 교통 환경, 자동차와의 역할 관계를 함께 저장해야 하는 PM 전용 룰북”이다.
```
