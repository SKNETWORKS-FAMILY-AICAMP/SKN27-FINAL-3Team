# 2025 2차로형 회전교차로 사고 과실비율 비정형 기준 전처리 컬럼 설계안

대상 파일: `250624_2차로형 회전교차로사고 과실비율 비정형기준.pdf`  
목표: 이 PDF를 단순 텍스트가 아니라 **2차로형 회전교차로 전용 과실비율 Rule Book**으로 구조화한다.

---

## 1. 결론

이 파일은 일반 자동차 사고 기준서보다 구조가 훨씬 명확하다.  
핵심 저장 단위는 `페이지`가 아니라 **회전-1 ~ 회전-15 룰 단위 JSON**이다.

이 기준서는 다음 특징을 가진다.

```text
1. 적용 대상이 2차로형 회전교차로로 한정된다.
2. 차로변경억제형 2차로형 회전교차로 구조를 전제로 한다.
3. 사고유형은 회전-1부터 회전-15까지 총 15개다.
4. 큰 사고군은 2개다.
   - 회전-1~회전-8: 진입차량 간 사고
   - 회전-9~회전-15: 진입차량과 회전차량 간 사고
5. 각 룰은 레드(A), 블루(B) 차량의 경로와 기본 과실비율을 가진다.
6. 진입차로, 회전차로, 진출방향, 선진입/후진입, 차로변경 여부가 핵심 컬럼이다.
```

따라서 최종 저장 방향은 다음이다.

```text
PDF 전체 페이지 수 검증
↓
목차/머리말/통행방법 section 분리
↓
회전-1 ~ 회전-15 rule 분리
↓
각 rule을 제목 기반 JSON으로 저장
↓
DB 적재용 JSONL은 별도 생성
```

---

## 2. 문서 구조 분석

### 2.1 목차 구조

이 파일의 목차는 다음처럼 구성된다.

```text
머리말
회전교차로 올바른 통행방법
2차로형 회전교차로 사고 과실비율 비정형 기준
회전-1
회전-2
...
회전-15
```

세부 rule 제목은 다음과 같다.

| 코드 | 제목 |
|---|---|
| `회전-1` | 진입 2개 차로에서 진입한 차량 간 진입부 사고(1) |
| `회전-2` | 진입 2개 차로에서 진입한 차량 간 진입부 사고(2) |
| `회전-3` | 진입 2개 차로에서 양 차량 진입 후 회전 중 사고 |
| `회전-4` | 진입 2개 차로에서 진입한 차량 간 3시 진출부 사고(1) |
| `회전-5` | 진입 2개 차로에서 진입한 차량 간 3시 진출부 사고(2) |
| `회전-6` | 진입 2개 차로에서 진입한 차량 간 12시 진출부 사고(1) |
| `회전-7` | 진입 2개 차로에서 진입한 차량 간 12시 진출부 사고(2) |
| `회전-8` | 진입 2개 차로에서 진입한 차량 간 9시 진출부 사고 |
| `회전-9` | 선진입 회전 차량과 후진입 직진 차량 간 사고 |
| `회전-10` | 선진입하여 회전 후 진출 차량과 후진입 차량 간 사고 |
| `회전-11` | 선진입 회전차량과 후진입 직후 차로변경 차량 간 사고 |
| `회전-12` | 회전 중 차로변경 차량과 후진입 차량 간 사고 |
| `회전-13` | 선진입 회전 후 진출차량과 후진입 차로변경 차량 간 사고 |
| `회전-14` | 선진입 회전 후 진출차량과 후진입 차량 간 사고 |
| `회전-15` | 선진입 회전 후 차로변경하여 진출하는 차량과 후진입 차량 간 사고 |

---

### 2.2 머리말에서 뽑아야 할 메타 정보

머리말은 rule은 아니지만 중요한 문서 배경이다.  
다음 정보를 별도 `sections.jsonl`에 저장한다.

| 컬럼명 | 설명 |
|---|---|
| `background_reason` | 기준서 마련 배경 |
| `design_change_basis` | 회전교차로설계지침 개편과 노면표시 개선 |
| `roundabout_design_type` | 차로변경억제형 2차로형 회전교차로 |
| `existing_standard_limit` | 기존 차54-1~차54-5 적용 한계 |
| `related_existing_standard_codes` | `["차54-1", "차54-2", "차54-3", "차54-4", "차54-5"]` |
| `operation_status` | 비정형 기준으로 우선 운영 |
| `future_plan` | 정합성 검증 후 정형 인정기준 편입 예정 |
| `accident_group_1` | 진입차량 간 사고, 회전-1~회전-8 |
| `accident_group_2` | 진입차량과 회전차량 간 사고, 회전-9~회전-15 |

---

### 2.3 올바른 통행방법 section에서 뽑아야 할 정보

`회전교차로 올바른 통행방법`은 사고 rule은 아니지만 회전교차로 사고 해석의 기준이 된다.  
따라서 별도 section으로 저장한다.

뽑을 수 있는 컬럼은 다음과 같다.

| 컬럼명 | 설명 | 예시 |
|---|---|---|
| `must_yield_to_pedestrian` | 보행자에게 양보 필요 여부 | `true` |
| `entry_speed_rule` | 접근 시 서행 | `서행` |
| `circulating_vehicle_priority` | 회전차량 우선 | `true` |
| `right_side_keep_rule` | 나올 때 우측 깜빡이 | `true` |
| `left_side_signal_rule` | 돌아갈 때 좌측 깜빡이 | `true` |
| `allowed_lane_guidance` | 좌회전 안쪽차로, 우회전 바깥차로 등 | 배열 |
| `campaign_or_public_guidance` | 통행방법 캠페인 문구 | 원문 |

---

## 3. 저장 파일 방향

### 3.1 페이지별 JSON은 저장하지 않는다

페이지별 JSON은 만들지 않는다.  
페이지는 전체를 읽었는지 확인하는 검증용으로만 쓴다.

```json
{
  "source_file": "250624_2차로형 회전교차로사고 과실비율 비정형기준.pdf",
  "expected_page_count": 76,
  "read_page_count": 76,
  "missing_pages": [],
  "status": "success"
}
```

---

### 3.2 제목 기반 rule JSON 저장

실제 저장 단위는 `회전-1`부터 `회전-15`까지의 rule JSON이다.

추천 폴더 구조는 다음과 같다.

```text
processed/traffic_ratio_stand/2025_two_lane_roundabout_rulebook/
├─ 00_manifest/
├─ 01_preface/
├─ 02_correct_roundabout_driving_method/
├─ 03_two_lane_roundabout_fault_ratio_standard/
│  ├─ 01_entry_vehicle_vs_entry_vehicle/
│  │  ├─ 회전-1_진입2개차로에서진입한차량간진입부사고1.json
│  │  ├─ 회전-2_진입2개차로에서진입한차량간진입부사고2.json
│  │  ├─ 회전-3_진입2개차로에서양차량진입후회전중사고.json
│  │  ├─ 회전-4_진입2개차로에서진입한차량간3시진출부사고1.json
│  │  ├─ 회전-5_진입2개차로에서진입한차량간3시진출부사고2.json
│  │  ├─ 회전-6_진입2개차로에서진입한차량간12시진출부사고1.json
│  │  ├─ 회전-7_진입2개차로에서진입한차량간12시진출부사고2.json
│  │  └─ 회전-8_진입2개차로에서진입한차량간9시진출부사고.json
│  └─ 02_entry_vehicle_vs_circulating_vehicle/
│     ├─ 회전-9_선진입회전차량과후진입직진차량간사고.json
│     ├─ 회전-10_선진입하여회전후진출차량과후진입차량간사고.json
│     ├─ 회전-11_선진입회전차량과후진입직후차로변경차량간사고.json
│     ├─ 회전-12_회전중차로변경차량과후진입차량간사고.json
│     ├─ 회전-13_선진입회전후진출차량과후진입차로변경차량간사고.json
│     ├─ 회전-14_선진입회전후진출차량과후진입차량간사고.json
│     └─ 회전-15_선진입회전후차로변경하여진출하는차량과후진입차량간사고.json
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
├─ roundabout_contexts.jsonl
├─ lane_paths.jsonl
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

회전교차로 rule JSON은 다음 구조를 추천한다.

```json
{
  "metadata": {},
  "hierarchy": {},
  "rule_identity": {},
  "roundabout_scope": {},
  "accident_classification": {},
  "parties": [],
  "red_vehicle_context": {},
  "blue_vehicle_context": {},
  "lane_path_context": {},
  "roundabout_context": {},
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
| `rule_id` | string | 내부 고유 ID | `roundabout_2025_회전-1` |
| `source_type` | string | 데이터 유형 | `fault_standard` |
| `source_subtype` | string | 세부 출처 | `roundabout_2025` |
| `source_reliability` | string | 신뢰도 | `official_standard` |
| `source_file` | string | 원본 PDF명 | `250624_2차로형 회전교차로사고 과실비율 비정형기준.pdf` |
| `published_year` | int | 발간 연도 | `2025` |
| `published_month` | int | 발간 월 | `6` |
| `preprocessing_version` | string | 전처리 버전 | `roundabout_2025_v1.0` |
| `file_hash` | string | 원본 파일 hash | `sha256...` |
| `page_start` | int | rule 시작 페이지 | `10` |
| `page_end` | int | rule 종료 페이지 | `16` |
| `page_count_checked` | bool | 페이지 수 검증 여부 | `true` |
| `missing_pages` | list[int] | 누락 페이지 | `[]` |

---

## 6. hierarchy 컬럼

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `document_title` | string | 문서 제목 | `2차로형 회전교차로 사고 과실비율 비정형 기준` |
| `section_title` | string | 상세 기준 section | `2차로형 회전교차로 사고 과실비율 비정형 기준` |
| `major_group_no` | string | 큰 사고군 번호 | `01` |
| `major_group_title` | string | 큰 사고군 | `진입차량 간 사고` |
| `round_code` | string | 룰 코드 | `회전-1` |
| `round_no` | int | 룰 번호 | `1` |
| `section_path` | list[string] | 목차 경로 | 배열 |

예시:

```json
{
  "document_title": "2차로형 회전교차로 사고 과실비율 비정형 기준",
  "section_title": "2차로형 회전교차로 사고 과실비율 비정형 기준",
  "major_group_no": "01",
  "major_group_title": "진입차량 간 사고",
  "round_code": "회전-1",
  "round_no": 1,
  "section_path": [
    "2차로형 회전교차로 사고 과실비율 비정형 기준",
    "진입차량 간 사고",
    "회전-1 진입 2개 차로에서 진입한 차량 간 진입부 사고(1)"
  ]
}
```

---

## 7. rule_identity 컬럼

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `round_code` | string | 회전 코드 | `회전-1` |
| `round_no` | int | 번호 | `1` |
| `rule_title` | string | 사고 제목 | `진입 2개 차로에서 진입한 차량 간 진입부 사고(1)` |
| `rule_title_clean` | string | 파일명용 제목 | `진입2개차로에서진입한차량간진입부사고1` |
| `rule_type` | string | 기준 유형 | `two_lane_roundabout` |
| `major_group` | string | 큰 사고군 | `entry_vehicle_vs_entry_vehicle` |
| `related_existing_standard_codes` | list[string] | 기존 기준 참조 | `["차54-1", "차54-2", "차54-3", "차54-4", "차54-5"]` |
| `is_nontypical_standard` | bool | 비정형 기준 여부 | `true` |
| `will_be_integrated_to_regular_standard` | bool/null | 향후 정형 기준 편입 예정 | `true` |

---

## 8. roundabout_scope 컬럼

이 기준서의 적용 전제를 저장한다.

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `roundabout_type` | string | 회전교차로 유형 | `lane_change_suppressed_two_lane_roundabout` |
| `lane_count` | int | 회전교차로 차로 수 | `2` |
| `entry_lane_count` | int | 진입차로 수 | `2` |
| `has_road_marking` | bool | 진행방향 노면표시 존재 | `true` |
| `road_marking_type` | string | 노면표시 유형 | `direction_arrow_marking` |
| `road_marking_basis` | string | 노면표시 근거 | `진입로 진행방향 노면표시` |
| `design_guideline_basis` | string | 설계지침 근거 | `회전교차로설계지침 개편` |
| `driving_rule_summary` | string | 통행방법 요약 | `회전차량 우선, 진입 시 서행, 진출 시 우측 깜빡이` |
| `is_lane_change_suppressed` | bool | 차로변경 억제형 여부 | `true` |

---

## 9. accident_classification 컬럼

사고유형 분류용 컬럼이다.

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `accident_group` | string | 대분류 | `진입차량 간 사고` |
| `accident_subgroup` | string | 중분류 | `진입부 사고`, `회전 중 사고`, `진출부 사고` |
| `collision_zone` | string | 충돌 위치 | `entry_zone`, `circulation_zone`, `exit_zone` |
| `collision_stage` | string | 사고 발생 단계 | `entering`, `circulating`, `exiting`, `lane_changing` |
| `vehicle_relation` | string | 차량 관계 | `entry_vs_entry`, `entry_vs_circulating` |
| `movement_relation` | string | 이동 관계 | `same_entry`, `different_entry`, `first_entry_vs_late_entry` |
| `has_first_entry_issue` | bool | 선진입 쟁점 여부 | `true` |
| `has_late_entry_issue` | bool | 후진입 쟁점 여부 | `true` |
| `has_lane_change_issue` | bool | 차로변경 쟁점 여부 | `true` |
| `has_exit_issue` | bool | 진출 쟁점 여부 | `true` |
| `has_road_marking_violation_issue` | bool | 노면표시 위반 쟁점 | `true` |
| `has_yield_duty_issue` | bool | 양보의무 쟁점 | `true` |

---

## 10. parties 컬럼

이 기준서는 `레드(A)`와 `블루(B)` 기준으로 구성된다.

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `party_key` | string | A/B | `A` |
| `party_color` | string | 색상 라벨 | `red`, `blue` |
| `party_label` | string | 원문 라벨 | `레드(A)` |
| `party_type` | string | 유형 | `vehicle` |
| `role_in_rule` | string | 룰 내 역할 | `entry_vehicle`, `circulating_vehicle`, `exiting_vehicle`, `lane_changing_vehicle` |
| `action_summary` | string | 원문 행동 요약 | `진입1차로 진입, 회전1차로 진입` |
| `entry_direction` | string/null | 진입 방향 | `6시 방향`, `9시 방향`, `12시 방향` |
| `entry_lane` | string/null | 진입차로 | `진입1차로` |
| `circulation_lane` | string/null | 회전차로 | `회전1차로` |
| `exit_direction` | string/null | 진출 방향 | `3시 방향`, `12시 방향`, `9시 방향` |
| `exit_lane` | string/null | 진출차로 | `1차로`, `2차로` |
| `lane_change_from` | string/null | 차로변경 전 | `회전2차로` |
| `lane_change_to` | string/null | 차로변경 후 | `회전1차로` |
| `is_first_entry` | bool | 선진입 여부 | `true` |
| `is_late_entry` | bool | 후진입 여부 | `true` |
| `is_lane_changing` | bool | 차로변경 여부 | `true` |
| `is_exiting` | bool | 진출 중 여부 | `true` |
| `violated_road_marking` | bool/null | 노면표시 위반 여부 | `true` |
| `raw_text` | string | 원문 | `레드(A) : 진입1차로 진입, 회전1차로 진입` |

---

## 11. red_vehicle_context / blue_vehicle_context 컬럼

`parties` 배열로 저장하되, 검색과 조건 비교를 쉽게 하려면 색상별 context도 별도 저장하는 것이 좋다.

### 11.1 red_vehicle_context

| 컬럼명 | 설명 |
|---|---|
| `red_party_key` | `A` |
| `red_action` | 레드 차량 행동 |
| `red_entry_direction` | 레드 진입 방향 |
| `red_entry_lane` | 레드 진입차로 |
| `red_circulation_lane` | 레드 회전차로 |
| `red_exit_direction` | 레드 진출 방향 |
| `red_exit_lane` | 레드 진출차로 |
| `red_is_first_entry` | 선진입 여부 |
| `red_is_late_entry` | 후진입 여부 |
| `red_is_lane_changing` | 차로변경 여부 |
| `red_is_exiting` | 진출 여부 |
| `red_violated_road_marking` | 노면표시 위반 여부 |

### 11.2 blue_vehicle_context

| 컬럼명 | 설명 |
|---|---|
| `blue_party_key` | `B` |
| `blue_action` | 블루 차량 행동 |
| `blue_entry_direction` | 블루 진입 방향 |
| `blue_entry_lane` | 블루 진입차로 |
| `blue_circulation_lane` | 블루 회전차로 |
| `blue_exit_direction` | 블루 진출 방향 |
| `blue_exit_lane` | 블루 진출차로 |
| `blue_is_first_entry` | 선진입 여부 |
| `blue_is_late_entry` | 후진입 여부 |
| `blue_is_lane_changing` | 차로변경 여부 |
| `blue_is_exiting` | 진출 여부 |
| `blue_violated_road_marking` | 노면표시 위반 여부 |

---

## 12. lane_path_context 컬럼

이 파일에서 가장 중요한 추가 컬럼이다.  
사고 유형이 차로와 방향에 의해 결정되므로, 단순히 `레드 행동`, `블루 행동`만 저장하면 부족하다.

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `red_path` | list[string] | 레드 경로 | `["진입1차로", "회전1차로"]` |
| `blue_path` | list[string] | 블루 경로 | `["진입2차로", "회전1차로"]` |
| `red_path_text` | string | 레드 경로 원문 | `진입1차로 진입, 회전1차로 진입` |
| `blue_path_text` | string | 블루 경로 원문 | `진입2차로 진입, 회전1차로 진입` |
| `red_expected_path` | list[string] | 레드 정상 경로 | `["진입1차로", "회전1차로"]` |
| `blue_expected_path` | list[string] | 블루 정상 경로 | `["진입2차로", "회전2차로"]` |
| `red_path_matches_marking` | bool/null | 레드 경로가 노면표시와 맞는지 | `true` |
| `blue_path_matches_marking` | bool/null | 블루 경로가 노면표시와 맞는지 | `false` |
| `path_conflict_type` | string | 경로 충돌 유형 | `entry_lane_to_wrong_circulation_lane` |
| `conflict_lane` | string/null | 충돌 차로 | `회전1차로` |
| `conflict_direction` | string/null | 충돌 방향 | `3시 방향`, `12시 방향` |
| `route_rule_basis` | string | 통행 경로 기준 | `3시 우회전/12시 직진은 진입2차로, 12시 직진/9시 회전은 진입1차로` |

---

## 13. roundabout_context 컬럼

회전교차로 자체의 구조와 통행 원칙을 저장한다.

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `roundabout_design` | string | 설계 구조 | `차로변경억제형 2차로형 회전교차로` |
| `circulation_direction` | string | 회전 방향 | `반시계방향` |
| `central_island_exists` | bool | 중앙교통섬 여부 | `true` |
| `yield_line_exists` | bool | 양보선 존재 | `true` |
| `direction_arrow_marking_exists` | bool | 진행방향 노면표시 존재 | `true` |
| `lane_change_suppressed` | bool | 차로변경 억제 여부 | `true` |
| `circulating_vehicle_priority` | bool | 회전차량 우선 원칙 | `true` |
| `entry_vehicle_yield_duty` | bool | 진입차량 양보의무 | `true` |
| `entry_vehicle_slow_or_stop_duty` | bool | 진입차량 서행/일시정지 의무 | `true` |
| `turn_signal_duty` | bool | 방향지시기 의무 | `true` |
| `normal_right_turn_lane` | string | 곧바로 3시 방향 우회전 시 정상 차로 | `진입2차로` |
| `normal_straight_lane` | string | 12시 방향 직진 시 정상 차로 | `진입1차로 또는 진입2차로 상황별` |
| `normal_left_turn_lane` | string | 9시 방향 회전 시 정상 차로 | `진입1차로` |

---

## 14. base_fault 컬럼

이 기준서는 `레드:블루` 기본과실로 나온다.  
A:B보다 색상 기준을 같이 저장해야 한다.

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `base_fault_type` | string | 비율 유형 | `pair_ratio` |
| `red_ratio` | int | 레드 과실 | `20` |
| `blue_ratio` | int | 블루 과실 | `80` |
| `party_a_ratio` | int | A 과실 | `20` |
| `party_b_ratio` | int | B 과실 | `80` |
| `normalized_ratio` | string | A:B | `20:80` |
| `red_blue_normalized_ratio` | string | 레드:블루 | `20:80` |
| `raw_text` | string | 원문 | `기본 과실비율 레드20 블루80` |
| `heavier_fault_party` | string | 과실이 큰 쪽 | `blue` |
| `is_one_sided_fault` | bool | 일방과실 여부 | `false` |

---

## 15. adjustment_factors 컬럼

공통 수정요소는 거의 동일하게 반복된다.

대표 항목:

```text
레드(A) 서행불이행 +10
레드(A) 현저한 과실 +10
레드(A) 중과실 또는 중대한 과실 +20
레드(A) 선진입 -10
블루(B) 서행불이행 +10
블루(B) 현저한 과실 +10
블루(B) 중과실 또는 중대한 과실 +20
블루(B) 선진입 -10
```

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `adjustment_id` | string | 수정요소 ID | `adj_roundabout_2025_회전-1_001` |
| `target_party_key` | string | A/B | `A` |
| `target_party_color` | string | red/blue | `red` |
| `target_party_label` | string | 원문 대상 | `레드(A)` |
| `factor_name` | string | 수정요소명 | `서행불이행` |
| `factor_category` | string | 분류 | `speed_or_slow_duty` |
| `delta` | int | 가감 수치 | `10` |
| `delta_direction` | string | 증가/감소 | `increase`, `decrease` |
| `raw_delta` | string | 원문 수치 | `+10` |
| `raw_text` | string | 원문 | `레드(A) 서행불이행 +10` |
| `condition_text` | string | 적용 조건 | 해설에서 추출 |
| `explanation_text` | string | 수정요소 해설 | 해설 원문 |
| `is_common_factor` | bool | 반복 공통요소 여부 | `true` |
| `is_entry_timing_factor` | bool | 선진입 관련 여부 | `true` |

### 15.1 수정요소 카테고리

| category | 예시 |
|---|---|
| `speed_or_slow_duty` | 서행불이행 |
| `severe_fault` | 현저한 과실, 중과실, 중대한 과실 |
| `entry_timing` | 선진입 |
| `yield_duty` | 미양보 |
| `signal_or_indicator` | 방향지시기, 신호불이행 |
| `lane_change` | 차로변경 |
| `road_marking_violation` | 노면표시 위반 |

---

## 16. blocks 컬럼

rule 내부 텍스트는 block으로 나눠 저장한다.

| block_type | 설명 |
|---|---|
| `rule_header` | 회전 코드와 제목 |
| `party_condition` | 레드(A), 블루(B) 조건 |
| `base_fault` | 기본 과실비율 |
| `adjustment_factor_table` | 과실비율 조정 예시 |
| `accident_situation` | 사고 상황 |
| `base_fault_explanation` | 기본 과실비율 해설 |
| `adjustment_explanation` | 수정요소 해설 |
| `related_law` | 관련 법규 |
| `reference_case` | 참고 판례 |
| `driving_method_reference` | 올바른 통행방법 참조 |
| `diagram_description` | 그림/도표 설명 |
| `application_note` | 적용 범위나 구분 기준 설명 |

특히 `진입부 사고인지 회전중 사고인지 구별하는 기준`처럼 사고유형 분류에 필요한 문장은 `application_note`로 따로 저장하는 것이 좋다.

---

## 17. law_refs 컬럼

이 기준서에서 반복적으로 등장하는 법령은 다음이다.

```text
도로교통법 제2조
도로교통법 제5조
도로교통법 제14조
도로교통법 제19조
도로교통법 제25조의2
도로교통법 제38조
도로교통법 제48조
도로교통법시행규칙 [별표 6]
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
| `law_role` | string | 역할 | `definition`, `yield_duty`, `signal_duty`, `lane_change_duty`, `safe_driving_duty` |

---

## 18. reference_cases 컬럼

이 기준서는 참고 판례가 포함된다.  
판례는 rule 근거와 유사사례 검색에서 중요하므로 구조화한다.

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
| `case_relevance` | string | 관련성 | `entry_conflict`, `lane_change_in_roundabout`, `first_entry_priority` |

---

## 19. diagram 컬럼

도표 이미지가 매우 중요하다.  
텍스트만으로는 차로/방향을 놓칠 수 있으므로 이미지 메타데이터를 남긴다.

| 컬럼명 | 타입 | 설명 |
|---|---|---|
| `has_diagram` | bool | 도표 이미지 존재 여부 |
| `diagram_page` | int | 도표 페이지 |
| `diagram_caption` | string | 도표 제목 |
| `diagram_image_path` | string/null | 이미지 crop 저장 경로 |
| `diagram_bbox` | list/null | crop 좌표 |
| `red_vehicle_visible` | bool | 레드 차량 표시 여부 |
| `blue_vehicle_visible` | bool | 블루 차량 표시 여부 |
| `entry_lanes_visible` | bool | 진입차로 표시 여부 |
| `circulation_lanes_visible` | bool | 회전차로 표시 여부 |
| `exit_directions_visible` | bool | 진출 방향 표시 여부 |
| `road_marking_visible` | bool | 노면표시 표시 여부 |

초기에는 이미지 crop을 하지 않아도 된다.  
다만 나중에 이미지 기반 검증을 위해 컬럼은 남겨둔다.

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
  "raw_text": "기본 과실비율 레드20 블루80",
  "clean_text": "기본 과실비율 레드20 블루80",
  "structured_text": "기본 과실비율 레드 20 : 블루 80"
}
```

---

## 21. 클리닝 작업 설계

2차로형 회전교차로 기준서는 표와 이미지가 많고, PDF 텍스트 추출 시 세로 라벨이 깨져 나온다.  
따라서 특수문자를 무조건 제거하지 않고, 과실비율과 차로 정보를 보존하는 방향으로 클리닝해야 한다.

### 21.1 제거할 텍스트

```text
페이지 번호
목차 점선
반복 header/footer
의미 없는 빈 줄
2칸 이상 반복 공백
```

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
레드
블루
→
·
3시
6시
9시
12시
진입1차로
진입2차로
회전1차로
회전2차로
```

특히 `→`는 차로 흐름과 경로를 표현할 수 있으므로 무조건 삭제하면 안 된다.

---

### 21.3 정규화할 표현

| 원문 | 정규화 |
|---|---|
| `기본 과실비율 레드20 블루80` | `기본 과실비율 레드 20 : 블루 80` |
| `레드(A) : 진입1차로 진입, 회전1차로 진입` | 그대로 보존 |
| `블루(B) : 진입2차로에서 후진입하여 회전하며 1차로로 차로변경` | 그대로 보존 |
| `과\n실\n비\n율\n조\n정\n예\n시` | `과실비율 조정 예시` |
| `사고\n상황` | `사고 상황` |
| `진입 1차로` | `진입1차로` |
| `진입 2차로` | `진입2차로` |
| `회전 1차로` | `회전1차로` |
| `회전 2차로` | `회전2차로` |

---

### 21.4 자동 수정 금지

아래 단어는 사고 구조와 직접 연결되므로 자동 수정하지 않는다.

```text
선진입
후진입
진입
진출
회전
직진
우회전
좌회전
차로변경
대진입
노면표시
서행불이행
현저한 과실
중대한 과실
중과실
```

애매한 경우 원문을 유지하고 `needs_manual_review_reason`에 기록한다.

---

### 21.5 클리닝 품질 컬럼

```json
{
  "cleaning_quality": {
    "page_noise_removed": true,
    "header_footer_removed": true,
    "vertical_label_repaired": true,
    "ratio_expression_normalized": true,
    "lane_expression_normalized": true,
    "direction_expression_preserved": true,
    "special_symbols_preserved": ["+", "-", ":", "→", "·"],
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
| `chunk_type` | 사고상황, 기본과실 해설, 관련법규 등 |
| `chunk_text` | 검색용 텍스트 |
| `round_code` | 회전 코드 |
| `rule_title` | 사고 제목 |
| `major_group` | 진입차량 간 사고 / 진입차량과 회전차량 간 사고 |
| `red_ratio` | 레드 과실 |
| `blue_ratio` | 블루 과실 |
| `red_path` | 레드 경로 |
| `blue_path` | 블루 경로 |
| `collision_zone` | 충돌 위치 |
| `accident_tags` | 사고 태그 |
| `source_reliability` | `official_standard` |

---

## 23. parse_quality 컬럼

| 컬럼명 | 설명 |
|---|---|
| `parse_status` | `valid`, `review_required`, `failed` |
| `page_count_checked` | 전체 페이지 수 검증 여부 |
| `missing_pages` | 누락 페이지 |
| `round_code_detected` | 회전 코드 추출 여부 |
| `title_detected` | 제목 추출 여부 |
| `red_party_detected` | 레드(A) 추출 여부 |
| `blue_party_detected` | 블루(B) 추출 여부 |
| `base_fault_detected` | 기본과실 추출 여부 |
| `lane_path_detected` | 차로 경로 추출 여부 |
| `adjustment_factor_detected` | 수정요소 추출 여부 |
| `law_ref_detected` | 법령 추출 여부 |
| `reference_case_detected` | 참고판례 추출 여부 |
| `block_split_success` | block 분리 성공 여부 |
| `needs_manual_review_reason` | 검수 필요 사유 |

---

## 24. 최종 rule JSON 예시: 회전-1

```json
{
  "metadata": {
    "rule_id": "roundabout_2025_회전-1",
    "source_type": "fault_standard",
    "source_subtype": "roundabout_2025",
    "source_reliability": "official_standard",
    "source_file": "250624_2차로형 회전교차로사고 과실비율 비정형기준.pdf",
    "published_year": 2025,
    "published_month": 6,
    "page_start": 10,
    "page_end": 16
  },
  "hierarchy": {
    "document_title": "2차로형 회전교차로 사고 과실비율 비정형 기준",
    "major_group_title": "진입차량 간 사고",
    "round_code": "회전-1",
    "round_no": 1,
    "section_path": [
      "2차로형 회전교차로 사고 과실비율 비정형 기준",
      "진입차량 간 사고",
      "회전-1 진입 2개 차로에서 진입한 차량 간 진입부 사고(1)"
    ]
  },
  "rule_identity": {
    "round_code": "회전-1",
    "rule_title": "진입 2개 차로에서 진입한 차량 간 진입부 사고(1)",
    "rule_type": "two_lane_roundabout",
    "major_group": "entry_vehicle_vs_entry_vehicle"
  },
  "roundabout_scope": {
    "roundabout_type": "lane_change_suppressed_two_lane_roundabout",
    "entry_lane_count": 2,
    "has_road_marking": true,
    "is_lane_change_suppressed": true
  },
  "accident_classification": {
    "accident_group": "진입차량 간 사고",
    "accident_subgroup": "진입부 사고",
    "collision_zone": "entry_zone",
    "vehicle_relation": "entry_vs_entry",
    "has_road_marking_violation_issue": true
  },
  "parties": [
    {
      "party_key": "A",
      "party_color": "red",
      "party_label": "레드(A)",
      "party_type": "vehicle",
      "action_summary": "진입1차로 진입, 회전1차로 진입",
      "entry_lane": "진입1차로",
      "circulation_lane": "회전1차로",
      "is_first_entry": false
    },
    {
      "party_key": "B",
      "party_color": "blue",
      "party_label": "블루(B)",
      "party_type": "vehicle",
      "action_summary": "진입2차로 진입, 회전1차로 진입",
      "entry_lane": "진입2차로",
      "circulation_lane": "회전1차로",
      "violated_road_marking": true
    }
  ],
  "lane_path_context": {
    "red_path": ["진입1차로", "회전1차로"],
    "blue_path": ["진입2차로", "회전1차로"],
    "blue_expected_path": ["진입2차로", "회전2차로"],
    "path_conflict_type": "entry_lane_to_wrong_circulation_lane",
    "conflict_lane": "회전1차로"
  },
  "base_fault": {
    "base_fault_type": "pair_ratio",
    "red_ratio": 20,
    "blue_ratio": 80,
    "party_a_ratio": 20,
    "party_b_ratio": 80,
    "normalized_ratio": "20:80",
    "raw_text": "기본 과실비율 레드20 블루80",
    "heavier_fault_party": "blue"
  },
  "adjustment_factors": [
    {
      "target_party_color": "red",
      "factor_name": "서행불이행",
      "factor_category": "speed_or_slow_duty",
      "delta": 10,
      "delta_direction": "increase",
      "raw_text": "레드(A) 서행불이행 +10"
    },
    {
      "target_party_color": "blue",
      "factor_name": "선진입",
      "factor_category": "entry_timing",
      "delta": -10,
      "delta_direction": "decrease",
      "raw_text": "블루(B) 선진입 -10"
    }
  ],
  "texts": {
    "raw_text": "...",
    "clean_text": "...",
    "structured_text": "..."
  },
  "cleaning_quality": {
    "vertical_label_repaired": true,
    "ratio_expression_normalized": true,
    "lane_expression_normalized": true
  },
  "parse_quality": {
    "parse_status": "valid",
    "round_code_detected": true,
    "red_party_detected": true,
    "blue_party_detected": true,
    "base_fault_detected": true,
    "lane_path_detected": true
  }
}
```

---

## 25. 최종 DB 적재용 JSONL

Nested JSON은 사람이 검토하기 위한 파일이고, DB에는 아래처럼 나눠 넣는 것이 좋다.

```text
rulebooks.jsonl
sections.jsonl
rules.jsonl
parties.jsonl
base_faults.jsonl
roundabout_contexts.jsonl
lane_paths.jsonl
adjustment_factors.jsonl
rule_blocks.jsonl
law_refs.jsonl
reference_cases.jsonl
diagrams.jsonl
chunks.jsonl
parse_quality_report.jsonl
```

---

## 26. 최종 결론

2차로형 회전교차로 기준서에서 공통적으로 추가로 뽑아야 할 컬럼은 다음이다.

```text
회전 코드
회전 번호
큰 사고군
진입차량 간 사고 / 진입차량과 회전차량 간 사고
충돌 위치
충돌 단계
레드/블루 차량 역할
레드/블루 경로
진입방향
진입차로
회전차로
진출방향
진출차로
차로변경 전/후
정상 경로
노면표시 위반 여부
선진입/후진입 여부
회전차량 우선 원칙
진입차량 양보의무
서행/일시정지 의무
방향지시기 의무
레드/블루 기본과실
공통 수정요소
경로 충돌 유형
관련 법규
참고 판례
도표 이미지 메타데이터
클리닝 품질
파싱 품질
```

따라서 이 파일은 단순히 `회전-1`, `제목`, `기본과실`, `수정요소`만 저장하면 부족하다.

한 줄로 정리하면 다음과 같다.

```text
2차로형 회전교차로 기준서는 “레드/블루 차량의 차로 경로와 회전교차로 통행원칙을 함께 저장해야 하는 차로·방향 중심 룰북”이다.
```
