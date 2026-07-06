# 2020 비정형사고 과실비율 기준 전처리 컬럼 설계안

대상 파일: `210107_2020년 비정형사고 과실비율 기준.pdf`  
목표: 이 PDF를 단순 텍스트가 아니라 **비정형 사고유형별 과실비율 Rule Book**으로 구조화한다.

---

## 1. 결론

이 파일은 2023 공식 인정기준처럼 `보/차/거` 코드가 붙은 대형 룰북도 아니고, PM/회전교차로처럼 특정 주제만 다루는 별도 기준도 아니다.  
핵심은 **기존 정형 기준으로 바로 설명하기 어려운 비정형 사고유형을 No.1 ~ No.23 단위로 정리한 기준서**라는 점이다.

따라서 저장 단위는 다음이 맞다.

```text
페이지 단위 저장 X
전체 PDF raw_text 하나로 저장 X
No.1, No.2, ... 기준 rule 단위 저장 O
요약표와 상세 본문 매칭 O
도표해설/관련법규/참고판례/심의사례 분리 O
```

이 파일에서 가장 중요한 구조는 다음이다.

```text
요약표
- No
- 내용
- 기준과실

상세 본문
- 번호 + 사고 제목
- 기본과실
- 사고상황
- A/B 차량 역할
- 수정요소
- 도표해설
- 사고 상황 해설
- 기본과실 해설
- 수정요소 해설
- 관련법규
- 참고판례 또는 심의사례
```

---

## 2. 문서 구조 분석

### 2.1 요약표 구조

이 파일은 초반에 `No / 내용 / 기준과실` 표가 나온다.  
이 표는 단순 목차가 아니라 **상세 rule을 검증하는 기준표** 역할을 한다.

예시 구조:

```text
No | 내용 | 기준과실
1 | 횡단보도 보행자신호 우회전차량과 녹색 직진차량간 사고 | A 100 : B 0
7 | 비보호좌회전 차량과 우회전차량 간 사고 | A 60 : B 40
```

따라서 요약표는 별도 JSON으로 저장해야 한다.

```text
01_summary_table/
└─ summary_table.json
```

그리고 DB 적재용으로는 `summary_table_rows.jsonl`을 만든다.

---

### 2.2 상세 rule 구조

상세 본문은 다음 패턴으로 반복된다.

```text
6. 중앙선 없는 이면도로에서 우회전차량과 우측 좌회전차량간 사고
기본과실 A 50 : B 50
사고상황 자동차 A : 우회전
자동차 B : 우측 좌회전
수정요소 A B
A 대형차 +5
A 우회전방법 위반 +10
...
[도표해설]
사고 상황 :
...
기본과실 해설 :
...
수정요소 해설 :
...
[관련법규]
...
[참고판례]
...
```

즉, `번호. 사고 제목`을 기준으로 rule을 분리하고, 내부 block을 다시 나눠야 한다.

---

### 2.3 이 파일의 특이점

이 파일은 일반 정형 기준보다 다음 특징이 강하다.

```text
1. 사고유형이 교차로/이면도로/버스정류장/추월/정차후 출발 등으로 다양하다.
2. A/B 차량 모두 자동차인 경우가 대부분이다.
3. 요약표의 기준과실과 상세 본문의 기본과실을 반드시 대조해야 한다.
4. 상세 본문 중간에 심의접수번호나 기존 분쟁 사례가 섞일 수 있다.
5. 일부 법규/참고판례가 rule 본문 뒤에 이어진다.
6. 페이지 번호가 본문 중간에 붙어 텍스트가 깨질 수 있다.
7. `우→좌`, `좌→우`처럼 방향 화살표가 의미를 가진다.
```

---

## 3. 저장 파일 방향

### 3.1 페이지별 JSON은 저장하지 않는다

페이지별 JSON은 만들지 않는다.  
다만 PDF 전체를 읽었는지는 검증한다.

```json
{
  "source_file": "210107_2020년 비정형사고 과실비율 기준.pdf",
  "expected_page_count": 0,
  "read_page_count": 0,
  "missing_pages": [],
  "status": "success"
}
```

`expected_page_count`와 `read_page_count`는 실제 실행 시 PDF loader 결과로 채운다.

---

### 3.2 제목 기반 rule JSON 저장

추천 폴더 구조는 다음과 같다.

```text
processed/traffic_ratio_stand/2020_nontypical_accident_rulebook/
├─ 00_manifest/
├─ 01_summary_table/
│  └─ summary_table.json
├─ 02_detailed_fault_ratio_standards/
│  ├─ no_01_횡단보도보행자신호우회전차량과녹색직진차량간사고.json
│  ├─ no_02_적색점멸직진차량과황색점멸직진차량간사고.json
│  ├─ no_03_적색점멸좌회전차량과황색점멸직진차량간사고.json
│  ├─ ...
│  ├─ no_14_버스정류장에서정차후출발버스차량과추월차량간사고.json
│  └─ no_23_횡단보도적색보행자신호이륜차와신호위반차량간사고.json
└─ 99_tables_for_db/
```

DB 적재용은 다음 JSONL로 만든다.

```text
99_tables_for_db/
├─ rulebooks.jsonl
├─ summary_table_rows.jsonl
├─ rules.jsonl
├─ parties.jsonl
├─ base_faults.jsonl
├─ road_contexts.jsonl
├─ priority_contexts.jsonl
├─ adjustment_factors.jsonl
├─ rule_blocks.jsonl
├─ law_refs.jsonl
├─ reference_cases.jsonl
├─ review_cases.jsonl
├─ diagrams.jsonl
├─ chunks.jsonl
└─ parse_quality_report.jsonl
```

---

## 4. rule JSON 최상위 구조

No별 rule JSON은 다음 구조를 추천한다.

```json
{
  "metadata": {},
  "hierarchy": {},
  "summary_table_row": {},
  "rule_identity": {},
  "accident_classification": {},
  "parties": [],
  "road_context": {},
  "priority_context": {},
  "base_fault": {},
  "adjustment_factors": [],
  "blocks": [],
  "law_refs": [],
  "reference_cases": [],
  "review_cases": [],
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
| `rule_id` | string | 내부 고유 ID | `nontypical_2020_no_06` |
| `source_type` | string | 데이터 유형 | `fault_standard` |
| `source_subtype` | string | 세부 출처 | `nontypical_2020` |
| `source_reliability` | string | 신뢰도 | `official_standard` |
| `source_file` | string | 원본 PDF명 | `210107_2020년 비정형사고 과실비율 기준.pdf` |
| `published_year` | int | 기준 연도 | `2020` |
| `published_date` | string/null | 문서 표기 발간일 | `2021-01-07` |
| `preprocessing_version` | string | 전처리 버전 | `nontypical_2020_v1.0` |
| `file_hash` | string | 원본 파일 hash | `sha256...` |
| `page_start` | int | rule 시작 페이지 | `17` |
| `page_end` | int | rule 종료 페이지 | `18` |
| `page_count_checked` | bool | 페이지 수 검증 여부 | `true` |
| `missing_pages` | list[int] | 누락 페이지 | `[]` |

---

## 6. hierarchy 컬럼

이 파일은 목차가 깊은 구조라기보다 `요약표 → 상세 rule` 구조다.

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `document_title` | string | 문서 제목 | `2020년 비정형사고 과실비율 기준` |
| `section_title` | string | 본문 section | `비정형사고 과실비율 기준` |
| `summary_table_exists` | bool | 요약표 존재 여부 | `true` |
| `rule_no` | int | 번호 | `6` |
| `rule_ref` | string | 번호 코드 | `No.6` |
| `section_path` | list[string] | 경로 | `["2020년 비정형사고 과실비율 기준", "No.6 중앙선 없는 이면도로에서 우회전차량과 우측 좌회전차량간 사고"]` |

예시:

```json
{
  "document_title": "2020년 비정형사고 과실비율 기준",
  "section_title": "비정형사고 과실비율 기준",
  "summary_table_exists": true,
  "rule_no": 6,
  "rule_ref": "No.6",
  "section_path": [
    "2020년 비정형사고 과실비율 기준",
    "No.6 중앙선 없는 이면도로에서 우회전차량과 우측 좌회전차량간 사고"
  ]
}
```

---

## 7. summary_table_row 컬럼

이 파일은 요약표와 상세 본문 매칭이 핵심이므로, summary table row를 rule JSON 안에도 넣는다.

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `summary_no` | int | 요약표 번호 | `6` |
| `summary_title` | string | 요약표 내용 | `중앙선 없는 이면도로에서 우회전차량과 우측 좌회전차량간 사고` |
| `summary_base_ratio_raw` | string | 요약표 기준과실 | `A 50 : B 50` |
| `summary_party_a_ratio` | int | 요약표 A 과실 | `50` |
| `summary_party_b_ratio` | int | 요약표 B 과실 | `50` |
| `summary_row_raw_text` | string | 요약표 원문 row | 원문 |
| `matched_detail_rule` | bool | 상세 본문 매칭 여부 | `true` |
| `ratio_matches_detail` | bool | 요약표/상세 본문 비율 일치 여부 | `true` |

---

## 8. rule_identity 컬럼

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `rule_no` | int | 번호 | `14` |
| `rule_code` | string | rule 코드 | `No.14` |
| `rule_title` | string | 사고 제목 | `버스정류장에서 정차후 출발 버스차량과 추월차량간 사고` |
| `rule_title_clean` | string | 파일명용 제목 | `버스정류장에서정차후출발버스차량과추월차량간사고` |
| `rule_type` | string | 기준 유형 | `nontypical_vehicle_accident` |
| `is_nontypical_standard` | bool | 비정형 여부 | `true` |
| `related_official_standard_code` | string/null | 2023 정형 기준 연결 가능 코드 | null |
| `has_review_case_before_rule` | bool | 앞에 심의사례가 붙었는지 | `true` |
| `has_reference_case` | bool | 참고판례 존재 여부 | `true` |

---

## 9. accident_classification 컬럼

비정형 기준은 사고유형이 넓어서 사고분류 컬럼이 중요하다.

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `accident_group` | string | 대분류 | `교차로`, `이면도로`, `버스정류장`, `추월`, `차로변경`, `횡단보도`, `유턴`, `중앙선` |
| `accident_subgroup` | string | 중분류 | `우회전 대 좌회전`, `정차후 출발 대 추월`, `점멸신호 교차로` |
| `collision_pattern` | string | 충돌 패턴 | `right_turn_vs_left_turn`, `stopped_bus_departure_vs_overtaking` |
| `road_environment` | string | 도로 환경 | `이면도로`, `동일폭 교차로`, `버스정류장`, `직선도로` |
| `traffic_control` | string | 교통정리 | `unsignalized`, `flash_signal`, `signalized`, `none` |
| `movement_relation` | string | 진행 관계 | `same_direction`, `opposite_direction`, `perpendicular`, `right_side_entry` |
| `violation_actor` | string | 주요 위반 주체 | `A`, `B`, `both`, `none` |
| `primary_violation` | string | 핵심 위반 | `우회전방법 위반`, `좌회전방법 위반`, `서행불이행`, `진로변경 신호불이행` |
| `is_intersection_case` | bool | 교차로 여부 | `true` |
| `is_private_or_narrow_road_case` | bool | 이면도로 여부 | `true` |
| `is_bus_stop_case` | bool | 버스정류장 사고 여부 | `true` |
| `is_overtaking_case` | bool | 추월 사고 여부 | `true` |
| `is_lane_change_case` | bool | 진로변경 사고 여부 | `true` |
| `is_u_turn_case` | bool | 유턴 사고 여부 | `true` |
| `is_crosswalk_case` | bool | 횡단보도 사고 여부 | `true` |

---

## 10. parties 컬럼

A/B 차량 역할을 저장한다.

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `party_key` | string | A/B | `A` |
| `party_label` | string | 원문 라벨 | `자동차 A` |
| `party_type` | string | 당사자 유형 | `vehicle`, `bus`, `motorcycle` |
| `movement` | string | 이동 행위 | `우회전`, `좌회전`, `직진`, `추월`, `정차후 출발`, `유턴` |
| `road_position` | string | 위치 | `이면도로`, `우측 도로`, `좌측 도로`, `버스정류장`, `직선도로` |
| `direction_relation` | string | 방향 관계 | `우측`, `좌측`, `우→좌`, `좌→우` |
| `signal_state` | string/null | 신호 상태 | `적색점멸`, `황색점멸`, null |
| `entry_timing` | string/null | 진입 시점 | `선진입`, null |
| `violation_type` | string/null | 위반 유형 | `우회전방법 위반`, `좌회전방법 위반`, `진로변경 신호불이행` |
| `is_large_vehicle` | bool/null | 대형차 여부 | null |
| `is_bus` | bool | 버스 여부 | `true` |
| `is_overtaking_vehicle` | bool | 추월차량 여부 | `true` |
| `is_departing_after_stop` | bool | 정차후 출발 여부 | `true` |
| `raw_text` | string | 원문 | `자동차 A : 우회전` |

예시:

```json
[
  {
    "party_key": "A",
    "party_label": "자동차 A",
    "party_type": "vehicle",
    "movement": "우회전",
    "road_position": "이면도로",
    "raw_text": "자동차 A : 우회전"
  },
  {
    "party_key": "B",
    "party_label": "자동차 B",
    "party_type": "vehicle",
    "movement": "우측 좌회전",
    "road_position": "우측 도로",
    "raw_text": "자동차 B : 우측 좌회전"
  }
]
```

---

## 11. road_context 컬럼

이 파일은 동일폭 교차로, 이면도로, 우측도로/좌측도로, 대로/소로 같은 도로 맥락이 중요하다.

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `road_area` | string | 도로 영역 | `교차로`, `이면도로`, `버스정류장`, `직선도로` |
| `intersection_type` | string/null | 교차로 유형 | `사거리`, `삼거리`, null |
| `road_width_relation` | string/null | 도로폭 관계 | `same_width`, `main_vs_side` |
| `main_road_party` | string/null | 대로 진행 차량 | `A`, `B`, null |
| `side_road_party` | string/null | 소로 진행 차량 | `A`, `B`, null |
| `right_side_party` | string/null | 우측도로 차량 | `A`, `B` |
| `left_side_party` | string/null | 좌측도로 차량 | `A`, `B` |
| `has_centerline` | bool/null | 중앙선 존재 | false |
| `has_bus_stop` | bool | 버스정류장 존재 | true |
| `has_parked_vehicle_visibility_issue` | bool | 주정차 차량으로 인한 시야제한 | true |
| `visibility_issue` | bool | 시야장애 | true |
| `road_surface_or_width_issue` | bool | 도로폭/노면 관련 문제 | null |

---

## 12. priority_context 컬럼

비정형 기준은 “누가 우선권을 가지는지”가 해설의 핵심이다.

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `priority_basis` | string | 우선권 근거 | `우측도로 우선`, `직진 우선`, `대로 우선`, `우회전 통행우선권`, `정차후 출발 주의의무` |
| `priority_party` | string/null | 우선권 있는 차량 | `B` |
| `duty_heavier_party` | string/null | 주의의무가 더 큰 차량 | `A` |
| `priority_conflict_exists` | bool | 우선권 충돌 여부 | true |
| `priority_conflict_description` | string | 우선권 충돌 설명 | `A는 우회전 통행우선권, B는 우측도로 통행우선권` |
| `legal_priority_refs` | list[string] | 우선권 관련 법규 | `["도로교통법 제26조 제3항", "도로교통법 제26조 제4항"]` |
| `reason_for_base_fault` | string | 기본과실 산정 이유 | 해설 원문 요약 |

예시:

```json
{
  "priority_basis": "우측도로 우선 및 좌회전/우회전 통행우선권 충돌",
  "priority_party": null,
  "duty_heavier_party": null,
  "priority_conflict_exists": true,
  "priority_conflict_description": "A차량은 우회전 통행우선권이 있으나, B차량은 우측 도로 통행우선권이 인정되어 대등한 수준으로 판단",
  "legal_priority_refs": ["도로교통법 제26조 제3항", "도로교통법 제26조 제4항"]
}
```

---

## 13. base_fault 컬럼

대부분 A:B 기준과실이다.

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `base_fault_type` | string | 비율 유형 | `pair_ratio` |
| `party_a_ratio` | int | A 과실 | `50` |
| `party_b_ratio` | int | B 과실 | `50` |
| `normalized_ratio` | string | 정규화 비율 | `50:50` |
| `raw_text` | string | 원문 | `기본과실 A 50 : B 50` |
| `summary_ratio_raw` | string | 요약표 기준과실 | `A 50 : B 50` |
| `detail_ratio_raw` | string | 상세 본문 기본과실 | `A 50 : B 50` |
| `summary_detail_ratio_match` | bool | 요약표/상세 비율 일치 | `true` |
| `heavier_fault_party` | string/null | 과실이 큰 쪽 | `A`, `B`, null |
| `is_equal_fault` | bool | 50:50 여부 | `true` |
| `is_one_sided_fault` | bool | 100:0 여부 | `false` |

---

## 14. adjustment_factors 컬럼

비정형 기준은 A/B 양측 수정요소가 명확하게 나열된다.

예시:

```text
A 대형차 +5
A 우회전방법 위반 +10
A 현저한 과실 +10
A 중과실 +20
A 명확한 선진입 -10
B 대형차 +5
B 좌회전방법 위반 +10
B 현저한 과실 +10
B 중과실 +20
B 명확한 선진입 -10
```

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `adjustment_id` | string | 수정요소 ID | `adj_nontypical_2020_no_06_001` |
| `target_party_key` | string | A/B | `A` |
| `target_party_type` | string | vehicle/bus/motorcycle | `vehicle` |
| `factor_name` | string | 수정요소명 | `우회전방법 위반` |
| `factor_category` | string | 분류 | `turning_method_violation` |
| `delta` | int | 가감 수치 | `10` |
| `delta_direction` | string | 증가/감소 | `increase`, `decrease` |
| `raw_delta` | string | 원문 수치 | `+10` |
| `raw_text` | string | 원문 | `A 우회전방법 위반 +10` |
| `condition_text` | string | 적용 조건 | 해설에서 추출 |
| `explanation_text` | string | 수정요소 해설 | 해설 원문 |
| `is_common_factor` | bool | 공통 반복 요소 여부 | true |
| `is_priority_factor` | bool | 선진입/우선권 관련 | true |

### 14.1 수정요소 카테고리 추천

| category | 예시 |
|---|---|
| `vehicle_size` | 대형차 |
| `turning_method_violation` | 우회전방법 위반, 좌회전방법 위반 |
| `lane_change_signal` | 진로변경 신호불이행·지연 |
| `speed_or_slow_duty` | 서행불이행, 감속불이행 |
| `priority` | 명확한 선진입 |
| `severe_fault` | 현저한 과실, 중과실 |
| `overtaking` | 추월, 앞지르기 |
| `bus_stop_context` | 버스정류장, 정차후 출발 |
| `visibility` | 시야장애 |

---

## 15. blocks 컬럼

rule 내부 텍스트를 의미 단위로 저장한다.

| block_type | 설명 |
|---|---|
| `summary_table_row` | 요약표의 No/내용/기준과실 |
| `rule_header` | 번호와 사고 제목 |
| `base_fault` | 기본과실 |
| `party_condition` | 사고상황 A/B |
| `adjustment_factor_table` | 수정요소 표 |
| `diagram_explanation` | `[도표해설]` 전체 |
| `accident_situation` | 도표해설 안 사고 상황 |
| `base_fault_explanation` | 기본과실 해설 |
| `adjustment_explanation` | 수정요소 해설 |
| `related_law` | 관련법규 |
| `reference_case` | 참고판례 |
| `review_case` | 심의접수번호 등 심의 사례 |
| `application_note` | 적용상 주의사항 |

---

## 16. law_refs 컬럼

법령 참조를 구조화한다.

이 파일에서 반복적으로 등장할 수 있는 법령은 다음이다.

```text
도로교통법 제18조
도로교통법 제21조
도로교통법 제25조
도로교통법 제26조
도로교통법 제31조
도로교통법 제38조
도로교통법 제48조
```

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
| `law_role` | string | 역할 | `priority_basis`, `turning_method`, `overtaking`, `safe_driving` |

---

## 17. reference_cases 컬럼

참고판례가 있는 경우 구조화한다.

| 컬럼명 | 타입 | 설명 |
|---|---|---|
| `reference_case_id` | string | 판례 ID |
| `rule_id` | string/null | 연결 rule |
| `court_name` | string | 법원명 |
| `decision_date` | string | 선고일 |
| `case_number` | string | 사건번호 |
| `case_summary` | string | 판례 요약 |
| `fault_ratio_in_case` | string/null | 판례 속 과실비율 |
| `raw_text` | string | 원문 |
| `context` | string | 주변 문맥 |
| `case_relevance` | string | 관련성 | `priority`, `turning_method`, `overtaking`, `u_turn`, `centerline` |

---

## 18. review_cases 컬럼

이 파일은 상세 rule 사이에 `심의접수번호` 형태의 심의 사례 텍스트가 끼어들 수 있다.  
이건 단순 노이즈로 버리지 말고 별도 `review_cases`로 분리하는 것이 좋다.

| 컬럼명 | 타입 | 설명 |
|---|---|---|
| `review_case_id` | string | 심의사례 ID |
| `related_rule_id` | string/null | 연결 rule |
| `review_receipt_no` | string | 심의접수번호 | `2020-007424` |
| `claim_vehicle_fault_ratio` | int/null | 청구차량 과실 | `70` |
| `respondent_vehicle_fault_ratio` | int/null | 피청구차량 과실 | `30` |
| `accident_summary` | string | 사고 요약 |
| `decision_summary` | string | 적정성 판단 문장 |
| `raw_text` | string | 원문 |
| `should_attach_to_previous_rule` | bool | 앞 rule에 붙일지 |
| `should_attach_to_next_rule` | bool | 다음 rule에 붙일지 |
| `needs_manual_review` | bool | 수동 검토 필요 여부 |

---

## 19. diagram 컬럼

각 rule은 도표/그림을 포함할 수 있다.  
텍스트만으로 도표를 완벽히 읽기 어렵기 때문에 메타데이터는 남겨둔다.

| 컬럼명 | 타입 | 설명 |
|---|---|---|
| `has_diagram` | bool | 도표 이미지 존재 여부 |
| `diagram_page` | int | 도표 페이지 |
| `diagram_caption` | string | 도표 제목 |
| `diagram_image_path` | string/null | 이미지 crop 저장 경로 |
| `diagram_bbox` | list/null | crop 좌표 |
| `vehicle_a_visible` | bool | A 차량 표시 여부 |
| `vehicle_b_visible` | bool | B 차량 표시 여부 |
| `road_shape_visible` | bool | 도로 형태 표시 여부 |
| `signal_or_marking_visible` | bool | 신호/표지 표시 여부 |

초기 구현에서는 이미지 crop을 하지 않아도 된다.  
다만 나중에 도표 이미지 기반 검증을 위해 컬럼을 남겨둔다.

---

## 20. texts 컬럼

원문 추적과 전처리 검증을 위해 텍스트는 3단계로 저장한다.

| 컬럼명 | 설명 |
|---|---|
| `raw_text` | PDF에서 읽은 원문 |
| `clean_text` | 페이지 번호, 헤더, 불필요 공백 정리 |
| `structured_text` | rule 파싱을 위해 비율/제목/블록을 정리한 텍스트 |

예시:

```json
{
  "raw_text": "기본과실 A 50 : B 50\n사고상황 자동차 A : 우회전",
  "clean_text": "기본과실 A 50 : B 50\n사고상황 자동차 A : 우회전",
  "structured_text": "기본과실 A 50 : B 50\n사고상황\n자동차 A : 우회전"
}
```

---

## 21. 클리닝 작업 설계

이 파일은 표 기반 문서이고, PDF 추출 시 페이지 번호와 심의사례 문장이 상세 rule 앞뒤에 붙을 수 있다.  
따라서 단순 공백 제거가 아니라 **No 기준 rule 분리와 요약표/상세 본문 매칭을 안정화하는 클리닝**이 필요하다.

### 21.1 제거할 텍스트

```text
페이지 번호
목차 점선
반복 header/footer
2칸 이상 반복 공백
의미 없는 빈 줄
```

예시:

```text
- 17 -
- 38 -
```

이런 페이지 번호는 `clean_text`, `structured_text`에서는 제거한다.

---

### 21.2 보존해야 하는 기호와 표현

```text
+
-
:
~
( )
[ ]
A
B
→
·
No
[도표해설]
[관련법규]
[참고판례]
심의접수번호
우→좌
좌→우
```

특히 `우→좌`, `좌→우`는 차량 진행방향을 의미하므로 삭제하면 안 된다.

---

### 21.3 정규화할 표현

| 원문 | 정규화 |
|---|---|
| `기본과실 A 50 B 50` | `기본과실 A 50 : B 50` |
| `A70:B30` | `A 70 : B 30` |
| `사고상황 자동차 A : 우회전 자동차 B : 우측 좌회전` | `사고상황\n자동차 A : 우회전\n자동차 B : 우측 좌회전` |
| `도표 해설` | `도표해설` |
| `관련 법규` | `관련법규` |
| `참고 판례` | `참고판례` |
| `중과실 또는 중대한 과실` | 원문 보존 |
| `우->좌` | `우→좌` |
| `좌->우` | `좌→우` |

---

### 21.4 심의사례 분리

상세 rule 사이에 다음과 같은 문장이 붙을 수 있다.

```text
심의접수번호 2020-007424 ...
청구차량 과실 70%, 피청구차량 과실 30%
```

이런 문장은 다음 rule의 제목과 섞이지 않도록 분리한다.

처리 원칙:

```text
심의접수번호가 있는 문단은 review_case 후보로 분리한다.
바로 앞 rule의 참고 사례인지, 다음 rule의 참고 사례인지는 자동 확정하지 않는다.
should_attach_to_previous_rule / should_attach_to_next_rule 플래그를 둔다.
애매하면 needs_manual_review = true로 둔다.
```

---

### 21.5 자동 수정 금지

아래 단어는 사고 구조와 직접 연결되므로 자동 수정하지 않는다.

```text
직진
좌회전
우회전
유턴
추월
앞지르기
진로변경
정차후 출발
중앙선
이면도로
대로
소로
우측도로
좌측도로
신호위반
적색점멸
황색점멸
선진입
```

애매한 경우 원문을 유지하고 `needs_manual_review_reason`에 기록한다.

---

### 21.6 클리닝 품질 컬럼

```json
{
  "cleaning_quality": {
    "page_noise_removed": true,
    "header_footer_removed": true,
    "ratio_expression_normalized": true,
    "direction_arrow_preserved": true,
    "summary_detail_ratio_matched": true,
    "review_case_separated": true,
    "special_symbols_preserved": ["+", "-", ":", "→", "[도표해설]", "[관련법규]", "[참고판례]"],
    "uncertain_terms": [],
    "needs_manual_review": false
  }
}
```

---

## 22. chunks 컬럼

검색/RAG용 chunk는 block 기준으로 만든다.

| 컬럼명 | 설명 |
|---|---|
| `chunk_id` | chunk ID |
| `rule_id` | 연결 rule |
| `block_id` | 연결 block |
| `chunk_type` | 사고상황, 기본과실 해설, 수정요소 해설 등 |
| `chunk_text` | 검색용 텍스트 |
| `rule_no` | No 번호 |
| `rule_title` | 사고 제목 |
| `party_a_ratio` | A 과실 |
| `party_b_ratio` | B 과실 |
| `accident_group` | 사고 대분류 |
| `road_environment` | 이면도로, 버스정류장 등 |
| `priority_basis` | 우선권 근거 |
| `accident_tags` | 사고 태그 |
| `source_reliability` | `official_standard` |

---

## 23. parse_quality 컬럼

| 컬럼명 | 설명 |
|---|---|
| `parse_status` | `valid`, `review_required`, `failed` |
| `page_count_checked` | 전체 페이지 수 검증 여부 |
| `missing_pages` | 누락 페이지 |
| `summary_table_detected` | 요약표 추출 여부 |
| `summary_no_detected` | 요약표 No 추출 여부 |
| `detail_rule_detected` | 상세 rule 추출 여부 |
| `summary_detail_matched` | 요약표와 상세 본문 매칭 여부 |
| `base_fault_detected` | 기본과실 추출 여부 |
| `party_detected` | A/B 당사자 추출 여부 |
| `adjustment_factor_detected` | 수정요소 추출 여부 |
| `law_ref_detected` | 법령 추출 여부 |
| `reference_case_detected` | 참고판례 추출 여부 |
| `review_case_detected` | 심의사례 추출 여부 |
| `block_split_success` | block 분리 성공 여부 |
| `needs_manual_review_reason` | 검수 필요 사유 |

---

## 24. 최종 rule JSON 예시: No.6

```json
{
  "metadata": {
    "rule_id": "nontypical_2020_no_06",
    "source_type": "fault_standard",
    "source_subtype": "nontypical_2020",
    "source_reliability": "official_standard",
    "source_file": "210107_2020년 비정형사고 과실비율 기준.pdf",
    "published_year": 2020,
    "page_start": 17,
    "page_end": 18
  },
  "hierarchy": {
    "document_title": "2020년 비정형사고 과실비율 기준",
    "rule_no": 6,
    "rule_ref": "No.6",
    "section_path": [
      "2020년 비정형사고 과실비율 기준",
      "No.6 중앙선 없는 이면도로에서 우회전차량과 우측 좌회전차량간 사고"
    ]
  },
  "summary_table_row": {
    "summary_no": 6,
    "summary_title": "중앙선 없는 이면도로에서 우회전차량과 우측 좌회전차량간 사고",
    "summary_base_ratio_raw": "A 50 : B 50",
    "matched_detail_rule": true,
    "ratio_matches_detail": true
  },
  "rule_identity": {
    "rule_no": 6,
    "rule_code": "No.6",
    "rule_title": "중앙선 없는 이면도로에서 우회전차량과 우측 좌회전차량간 사고",
    "rule_type": "nontypical_vehicle_accident"
  },
  "accident_classification": {
    "accident_group": "교차로",
    "accident_subgroup": "이면도로 우회전 대 우측 좌회전",
    "collision_pattern": "right_turn_vs_right_side_left_turn",
    "traffic_control": "unsignalized",
    "is_intersection_case": true,
    "is_private_or_narrow_road_case": true
  },
  "parties": [
    {
      "party_key": "A",
      "party_label": "자동차 A",
      "party_type": "vehicle",
      "movement": "우회전",
      "raw_text": "자동차 A : 우회전"
    },
    {
      "party_key": "B",
      "party_label": "자동차 B",
      "party_type": "vehicle",
      "movement": "우측 좌회전",
      "raw_text": "자동차 B : 우측 좌회전"
    }
  ],
  "priority_context": {
    "priority_conflict_exists": true,
    "priority_conflict_description": "A차량은 우회전 통행우선권이 있으나, B차량은 우측 도로 통행우선권이 인정되어 대등한 수준으로 판단"
  },
  "base_fault": {
    "base_fault_type": "pair_ratio",
    "party_a_ratio": 50,
    "party_b_ratio": 50,
    "normalized_ratio": "50:50",
    "raw_text": "기본과실 A 50 : B 50",
    "is_equal_fault": true
  },
  "adjustment_factors": [
    {
      "target_party_key": "A",
      "factor_name": "우회전방법 위반",
      "factor_category": "turning_method_violation",
      "delta": 10,
      "delta_direction": "increase",
      "raw_text": "A 우회전방법 위반 +10"
    },
    {
      "target_party_key": "B",
      "factor_name": "좌회전방법 위반",
      "factor_category": "turning_method_violation",
      "delta": 10,
      "delta_direction": "increase",
      "raw_text": "B 좌회전방법 위반 +10"
    }
  ],
  "texts": {
    "raw_text": "...",
    "clean_text": "...",
    "structured_text": "..."
  },
  "cleaning_quality": {
    "ratio_expression_normalized": true,
    "summary_detail_ratio_matched": true,
    "direction_arrow_preserved": true
  },
  "parse_quality": {
    "parse_status": "valid",
    "summary_detail_matched": true,
    "base_fault_detected": true,
    "party_detected": true,
    "adjustment_factor_detected": true
  }
}
```

---

## 25. 최종 DB 적재용 JSONL

Nested JSON은 사람이 검토하기 위한 파일이고, DB에는 아래처럼 나눠 넣는 것이 좋다.

```text
rulebooks.jsonl
summary_table_rows.jsonl
rules.jsonl
parties.jsonl
base_faults.jsonl
road_contexts.jsonl
priority_contexts.jsonl
adjustment_factors.jsonl
rule_blocks.jsonl
law_refs.jsonl
reference_cases.jsonl
review_cases.jsonl
diagrams.jsonl
chunks.jsonl
parse_quality_report.jsonl
```

---

## 26. 최종 결론

2020 비정형사고 기준서에서 공통적으로 추가로 뽑아야 할 컬럼은 다음이다.

```text
No 번호
요약표 내용
요약표 기준과실
상세 본문 기본과실
요약표/상세 본문 매칭 여부
사고 대분류/중분류
교통정리 여부
이면도로/동일폭/버스정류장/직선도로 등 도로환경
A/B 차량 역할
A/B 이동 방향
우측도로/좌측도로
우→좌, 좌→우 진행방향
대로/소로
우선권 근거
주의의무가 큰 차량
기본과실 산정 이유
수정요소 카테고리
법규 참조
참고판례
심의접수번호 기반 심의사례
도표 이미지 메타데이터
클리닝 품질
파싱 품질
```

따라서 이 파일은 단순히 `No`, `제목`, `기본과실`, `수정요소`만 저장하면 부족하다.

한 줄로 정리하면 다음과 같다.

```text
2020 비정형사고 기준서는 “No별 기준과실표”가 아니라 “요약표와 상세 본문을 매칭하고, 우선권·도로환경·심의사례까지 함께 저장해야 하는 비정형 사고 룰북”이다.
```
