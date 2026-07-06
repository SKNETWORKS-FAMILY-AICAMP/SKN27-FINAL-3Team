# 230630 자동차사고 과실비율 인정기준 전처리 컬럼 설계안

대상 파일: `230630_자동차사고 과실비율 인정기준_최종.pdf`  
목표: PDF 원문을 단순 페이지 텍스트로 저장하지 않고, **공식 과실비율 룰북**으로 구조화한다.

---

## 1. 결론

이 파일은 일반 문서가 아니라 **사고유형별 과실비율 Rule Book**이다.  
따라서 저장 단위는 페이지가 아니라 다음 순서가 되어야 한다.

```text
룰북 PDF
↓
목차 section
↓
세부유형별 과실비율 적용기준
↓
개별 rule
↓
rule 내부 block
↓
검색용 chunk
```

특히 230630 파일은 다음 세 가지 룰 체계가 섞여 있다.

```text
보 = 자동차와 보행자의 사고
차 = 자동차와 자동차(이륜차 포함)의 사고
거 = 자동차와 자전거(농기계 포함)의 사고
```

따라서 `보1`, `차1-1`, `거7-2` 같은 기준 코드를 중심으로 JSON을 저장해야 한다.

---

## 2. 저장 방향

### 2.1 페이지별 JSON은 저장하지 않는다

페이지별 JSON은 너무 많고, 이 데이터의 핵심 단위도 아니다.  
대신 전체 페이지를 읽었는지는 별도 검증 파일로만 저장한다.

```json
{
  "source_file": "230630_자동차사고 과실비율 인정기준_최종.pdf",
  "expected_page_count": 600,
  "read_page_count": 600,
  "missing_pages": [],
  "status": "success"
}
```

저장 위치 예시:

```text
processed/traffic_ratio_stand/2023_official_auto_accident_rulebook/00_manifest/page_coverage.json
```

---

### 2.2 실제 저장 단위는 rule JSON

예시:

```text
processed/traffic_ratio_stand/2023_official_auto_accident_rulebook/
└─ 04_accident_type_fault_ratio_standards/
   ├─ 01_vehicle_vs_pedestrian/
   │  └─ 04_detailed_rules/
   │     └─ 01_crosswalk_inside_signal/
   │        ├─ 보1_자동차녹색신호교차로통과후_보행자적색신호횡단개시적색신호충격사고.json
   │        ├─ 보2_자동차황색신호교차로통과후_보행자적색신호횡단개시적색신호충격사고.json
   │        └─ ...
   ├─ 02_vehicle_vs_vehicle_motorcycle/
   │  └─ 04_detailed_rules/
   │     └─ 01_intersection/
   │        └─ 차1-1_녹색직진대적색직진.json
   └─ 03_vehicle_vs_bicycle_agricultural/
      └─ 04_detailed_rules/
         └─ 01_intersection/
            └─ 거7-1_오른쪽우회전자전거대왼쪽직진자동차.json
```

파일명 원칙:

```text
{rule_code}_{section_title}_{rule_title}.json
```

단, 실제 파일명은 너무 길어질 수 있으므로 80~120자 정도로 자른다.

---

## 3. 230630 파일에서 공통적으로 뽑을 수 있는 컬럼

아래 컬럼들은 `보`, `차`, `거` 기준에서 공통적으로 뽑을 수 있다.  
다만 값의 형태는 사고유형마다 다를 수 있으므로, 일부 필드는 `null`을 허용해야 한다.

---

## 4. rule JSON 최상위 구조

각 rule JSON은 다음 구조를 추천한다.

```json
{
  "metadata": {},
  "hierarchy": {},
  "rule_identity": {},
  "parties": [],
  "base_fault": {},
  "variants": [],
  "adjustment_factors": [],
  "blocks": [],
  "law_refs": [],
  "reference_cases": [],
  "usage_notes": [],
  "texts": {},
  "chunks": [],
  "quality": {}
}
```

이 구조를 쓰면 사람이 열어보기도 쉽고, 나중에 DB 테이블로 쪼개기도 쉽다.

---

## 5. metadata 컬럼

파일과 전처리 자체에 대한 정보다.

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `rule_id` | string | 내부 고유 ID | `official_2023_보1` |
| `source_type` | string | 데이터 유형 | `fault_standard` |
| `source_subtype` | string | 세부 출처 | `official_2023` |
| `source_reliability` | string | 신뢰도 | `official_standard` |
| `source_file` | string | 원본 PDF명 | `230630_자동차사고 과실비율 인정기준_최종.pdf` |
| `published_year` | int | 발간 연도 | `2023` |
| `published_month` | int | 발간 월 | `6` |
| `preprocessing_version` | string | 전처리 버전 | `official_2023_v1.0` |
| `file_hash` | string | 원본 파일 hash | `sha256...` |
| `page_start` | int | rule 시작 페이지 | `38` |
| `page_end` | int | rule 종료 페이지 | `41` |
| `page_count_checked` | bool | 페이지 수 검증 여부 | `true` |
| `missing_pages` | list[int] | 누락 페이지 | `[]` |

---

## 6. hierarchy 컬럼

목차 경로를 저장한다.  
이 파일에서는 이 컬럼이 매우 중요하다.

### 6.1 공통 컬럼

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `part_no` | string | 편 번호 | `제3편` |
| `part_title` | string | 편 제목 | `과실비율 적용기준(사고유형별)` |
| `chapter_no` | string | 장 번호 | `제1장` |
| `chapter_title` | string | 장 제목 | `자동차와 보행자의 사고` |
| `section_no` | string | 절 번호 | `4` |
| `section_title` | string | 절 제목 | `세부유형별 과실비율 적용기준` |
| `category_no` | string | 대분류 번호 | `(1)` |
| `category_title` | string | 대분류 제목 | `횡단보도 내(신호등 있음)` |
| `sub_category_no` | string | 소분류 번호 | `1)` |
| `sub_category_title` | string | 소분류 제목 | `자동차 녹색신호 교차로 통과 후` |
| `rule_group_ref` | string | 목차상 묶음 코드 | `[보1]`, `[보2~보4]`, `[차1]` |
| `section_path` | list[string] | 전체 목차 경로 | `["제3편", "제1장", "4. 세부유형별...", "(1) 횡단보도 내", "1) 자동차 녹색신호..."]` |

### 6.2 hierarchy 예시

```json
{
  "part_no": "제3편",
  "part_title": "과실비율 적용기준(사고유형별)",
  "chapter_no": "제1장",
  "chapter_title": "자동차와 보행자의 사고",
  "section_no": "4",
  "section_title": "세부유형별 과실비율 적용기준",
  "category_no": "(1)",
  "category_title": "횡단보도 내(신호등 있음)",
  "sub_category_no": "1)",
  "sub_category_title": "자동차 녹색신호 교차로 통과 후",
  "rule_group_ref": "[보1]",
  "section_path": [
    "제3편 과실비율 적용기준(사고유형별)",
    "제1장 자동차와 보행자의 사고",
    "4. 세부유형별 과실비율 적용기준",
    "(1) 횡단보도 내(신호등 있음)",
    "1) 자동차 녹색신호 교차로 통과 후 [보1]"
  ]
}
```

---

## 7. rule_identity 컬럼

해당 rule 자체의 식별 정보다.

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `rule_code` | string | 기준 코드 | `보1`, `차1-1`, `거7-2` |
| `rule_prefix` | string | 코드 접두어 | `보`, `차`, `거` |
| `rule_number` | string | 번호 부분 | `1`, `1-1`, `7-2` |
| `rule_title` | string | rule 제목 | `보행자 적색신호 횡단 개시, 적색신호 충격 사고` |
| `rule_title_clean` | string | 파일명용 제목 | `보행자적색신호횡단개시적색신호충격사고` |
| `accident_group` | string | 사고 대분류 | `횡단보도`, `교차로`, `회전교차로`, `추돌` |
| `accident_subgroup` | string | 사고 중분류 | `횡단보도 내(신호등 있음)` |
| `rule_type` | string | 기준 유형 | `vehicle_vs_pedestrian`, `vehicle_vs_vehicle`, `vehicle_vs_bicycle` |
| `has_multiple_variants` | bool | 가/나 등 변형 여부 | `false` |
| `variant_count` | int | 변형 개수 | `0` |
| `old_standard_refs` | list[string] | 舊 기준 번호 | `["201", "301", "302"]` |

---

## 8. parties 컬럼

당사자 정보다.  
`보` 기준은 보행자/자동차 구조이고, `차` 기준은 A/B 차량 구조이며, `거` 기준은 자전거/자동차 구조가 많다.

### 8.1 parties 배열 구조

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `party_key` | string | 내부 키 | `A`, `B`, `보`, `차` |
| `party_label` | string | 원문 라벨 | `보행자`, `자동차`, `A차량`, `B차량` |
| `party_type` | string | 당사자 유형 | `pedestrian`, `vehicle`, `bicycle`, `motorcycle`, `agricultural_machine` |
| `movement` | string | 진행 행위 | `직진`, `좌회전`, `우회전`, `횡단`, `유턴` |
| `signal_state` | string | 신호 상태 | `녹색`, `황색`, `적색`, `신호없음` |
| `road_position` | string | 도로 위치 | `횡단보도`, `교차로`, `대로`, `소로` |
| `entry_timing` | string | 진입 시점 | `선진입`, `후진입`, `교차로 통과 후` |
| `violation_type` | string | 위반 유형 | `신호위반`, `중앙선 침범`, `진로변경금지 위반` |
| `raw_text` | string | 원문 상태 | `(보) 적색에 횡단 개시, 적색에 충격` |

### 8.2 보1 예시

```json
[
  {
    "party_key": "보",
    "party_label": "보행자",
    "party_type": "pedestrian",
    "movement": "횡단",
    "signal_state": "적색",
    "road_position": "횡단보도",
    "entry_timing": "횡단 개시",
    "violation_type": "보행자신호 위반",
    "raw_text": "(보) 적색에 횡단 개시, 적색에 충격"
  },
  {
    "party_key": "차",
    "party_label": "자동차",
    "party_type": "vehicle",
    "movement": "교차로 진입",
    "signal_state": "녹색",
    "road_position": "교차로",
    "entry_timing": "교차로 통과 후",
    "violation_type": null,
    "raw_text": "(차) 녹색에 교차로 진입"
  }
]
```

---

## 9. base_fault 컬럼

기본 과실비율이다.  
이 파일에서 특히 중요한 점은 **기준 형태가 하나가 아니라는 것**이다.

### 9.1 기본 과실비율 유형

| 유형 | 설명 | 예시 |
|---|---|---|
| `single_party_fault` | 한쪽 당사자 과실만 제시 | `보행자 기본 과실비율 70` |
| `pair_ratio` | A:B 비율 제시 | `A 0 : B 100` |
| `variant_ratio` | 가/나 등 변형별 비율 제시 | `차33-1 (가) A20 B80, (나) A100 B0` |
| `multi_rule_combined` | 한 페이지/한 그룹에 여러 rule | `거7-1`, `거7-2` |

### 9.2 base_fault 공통 컬럼

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `base_fault_type` | string | 비율 유형 | `single_party_fault`, `pair_ratio`, `variant_ratio` |
| `base_fault_label` | string | 원문 라벨 | `보행자 기본 과실비율`, `기본 과실비율` |
| `base_fault_party` | string | 단일 과실 대상 | `pedestrian` |
| `base_fault_ratio` | int | 단일 과실 수치 | `70` |
| `party_a_ratio` | int | A 과실 | `0` |
| `party_b_ratio` | int | B 과실 | `100` |
| `normalized_ratio` | string | 정규화 비율 | `0:100`, `70:null` |
| `raw_text` | string | 원문 | `기본 과실비율 A0 B100` |
| `ratio_sum` | int | 합계 | `100` |
| `is_one_sided_fault` | bool | 일방과실 여부 | `true` |

### 9.3 보1 예시

```json
{
  "base_fault_type": "single_party_fault",
  "base_fault_label": "보행자 기본 과실비율",
  "base_fault_party": "pedestrian",
  "base_fault_ratio": 70,
  "party_a_ratio": null,
  "party_b_ratio": null,
  "normalized_ratio": "pedestrian:70",
  "raw_text": "보행자 기본 과실비율 70",
  "ratio_sum": null,
  "is_one_sided_fault": false
}
```

### 9.4 차1-1 예시

```json
{
  "base_fault_type": "pair_ratio",
  "base_fault_label": "기본 과실비율",
  "base_fault_party": null,
  "base_fault_ratio": null,
  "party_a_ratio": 0,
  "party_b_ratio": 100,
  "normalized_ratio": "0:100",
  "raw_text": "기본 과실비율 A0 B100",
  "ratio_sum": 100,
  "is_one_sided_fault": true
}
```

---

## 10. variants 컬럼

일부 rule은 하나의 rule_code 안에 변형 조건이 있다.  
대표적으로 `차33-1`처럼 `(가) 상시유턴구역`, `(나) 신호유턴`이 있고, 각 변형별 기본과실이 다르다.

### 10.1 variants 배열 구조

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `variant_id` | string | 변형 ID | `official_2023_차33-1_가` |
| `variant_key` | string | 변형 키 | `가`, `나` |
| `variant_title` | string | 변형 제목 | `상시유턴구역` |
| `party_a_ratio` | int | A 과실 | `20` |
| `party_b_ratio` | int | B 과실 | `80` |
| `raw_text` | string | 변형 원문 | `(가) 상시유턴구역 A20 B80` |
| `scenario_text` | string | 변형 사고 상황 | `(가) 교차로에서 녹색신호에 따라 직진...` |

### 10.2 variants 예시

```json
[
  {
    "variant_id": "official_2023_차33-1_가",
    "variant_key": "가",
    "variant_title": "상시유턴구역",
    "party_a_ratio": 20,
    "party_b_ratio": 80,
    "raw_text": "(가) 상시유턴구역 A20 B80"
  },
  {
    "variant_id": "official_2023_차33-1_나",
    "variant_key": "나",
    "variant_title": "신호유턴",
    "party_a_ratio": 100,
    "party_b_ratio": 0,
    "raw_text": "(나) 신호유턴 A100 B0"
  }
]
```

---

## 11. adjustment_factors 컬럼

수정요소는 과실비율 계산에 직접 연결된다.  
`+10`, `-10`, `비적용`을 모두 보존해야 한다.

### 11.1 adjustment_factors 배열 구조

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `adjustment_id` | string | 수정요소 ID | `adj_official_2023_보1_001` |
| `order_no` | string | 원문 번호 | `①`, `②`, `③` |
| `target_party_key` | string | 적용 대상 | `A`, `B`, `보`, `차` |
| `target_party_type` | string | 대상 유형 | `pedestrian`, `vehicle` |
| `factor_name` | string | 수정요소명 | `야간·기타 시야장애` |
| `delta` | int/null | 가감 수치 | `5`, `-10`, `null` |
| `delta_direction` | string | 증가/감소/비적용 | `increase`, `decrease`, `not_applicable` |
| `raw_delta` | string | 원문 수치 | `+5`, `-10`, `비적용` |
| `raw_text` | string | 원문 전체 | `야간·기타 시야장애 +5` |
| `condition_text` | string | 조건 설명 | 해설에서 추출 |
| `explanation_text` | string | 수정요소 해설 | 해설 문장 |
| `is_applicable` | bool | 적용 가능 여부 | `true`, `false` |

### 11.2 수정요소에서 추가로 뽑을 수 있는 공통 카테고리

수정요소명에서 다음 의미 태그를 추가로 뽑을 수 있다.

| category | 예시 |
|---|---|
| `visibility` | 야간·기타 시야장애 |
| `road_type` | 간선도로 |
| `area_context` | 주택·상점가·학교 |
| `protected_area` | 어린이·노인·장애인보호구역 |
| `vulnerable_person` | 어린이·노인·장애인 |
| `severe_fault` | 현저한 과실, 중대한 과실 |
| `entry_timing` | 명확한 선진입 |
| `signal_behavior` | 신호불이행·지연 |
| `lane_behavior` | 진로변경, 차로변경 |
| `road_marking_violation` | 노면표시 위반 |
| `non_applicable` | 비적용 |

---

## 12. blocks 컬럼

rule 내부 텍스트를 의미 단위로 나눈다.

### 12.1 block_type

| block_type | 설명 |
|---|---|
| `diagram_header` | 도표 상단 제목/요약 |
| `party_condition` | `(A)`, `(B)`, `(보)`, `(차)` 조건 |
| `base_fault_table` | 기본 과실비율 표 |
| `adjustment_factor_table` | 과실비율 조정 예시 표 |
| `accident_situation` | 사고 상황 |
| `base_fault_explanation` | 기본 과실비율 해설 |
| `adjustment_explanation` | 수정요소 해설 |
| `related_law` | 관련 법규 |
| `reference_case` | 참고 판례 |
| `usage_note` | 활용시 참고 사항 |
| `old_standard_reference` | 舊 기준 |
| `diagram_image_note` | 도표/그림 설명 또는 이미지 참조 |

### 12.2 blocks 예시

```json
[
  {
    "block_id": "block_official_2023_보1_001",
    "block_type": "accident_situation",
    "block_title": "사고 상황",
    "block_order": 1,
    "raw_text": "...",
    "clean_text": "...",
    "structured_text": "..."
  },
  {
    "block_id": "block_official_2023_보1_002",
    "block_type": "base_fault_explanation",
    "block_title": "기본 과실비율 해설",
    "block_order": 2,
    "raw_text": "...",
    "clean_text": "...",
    "structured_text": "..."
  }
]
```

---

## 13. law_refs 컬럼

관련 법규는 rule과 section 모두에서 나올 수 있다.  
Rule 내부 관련법규는 rule에 연결하고, 총설/수정요소 해설의 법규는 section에 연결한다.

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

예시:

```json
{
  "law_name": "도로교통법",
  "article": "제5조",
  "paragraph": null,
  "raw_text": "도로교통법 제5조",
  "context": "도로교통법 제5조에 따라 보행자나 차마는 신호기의 신호에 따라야..."
}
```

---

## 14. reference_cases 컬럼

참고 판례는 여러 rule에서 등장한다.  
판례 자체도 나중에 판례 DB와 연결할 수 있으므로, 구조화해서 저장한다.

| 컬럼명 | 타입 | 설명 |
|---|---|---|
| `reference_case_id` | string | 참고판례 ID |
| `rule_id` | string/null | 연결 rule |
| `section_id` | string/null | 연결 section |
| `court_name` | string | 법원명 |
| `decision_date` | string | 선고일 |
| `case_number` | string | 사건번호 |
| `fault_ratio_in_case` | string | 판례 속 과실비율 |
| `raw_text` | string | 원문 |
| `summary_text` | string | 판례 요약 |
| `context` | string | 주변 문맥 |

---

## 15. usage_notes 컬럼

일부 rule에는 `활용시 참고 사항`이 따로 있다.  
이건 일반 해설과 분리해서 저장하는 게 좋다.

| 컬럼명 | 타입 | 설명 |
|---|---|---|
| `note_id` | string | 참고사항 ID |
| `rule_id` | string | 연결 rule |
| `note_type` | string | `usage_note`, `application_limit`, `exception` |
| `note_text` | string | 참고사항 원문 |
| `related_law_refs` | list | 관련 법규 |
| `related_conditions` | list | 적용 조건 |

예시:

```json
{
  "note_type": "usage_note",
  "note_text": "도로교통법 제22조 제3항에 정한 앞지르기 금지 장소인 교차로, 터널 안, 다리 위..."
}
```

---

## 16. diagram 컬럼

PDF에는 각 rule마다 그림/도표가 들어간다.  
텍스트 추출만으로는 도표 이미지의 정보를 완전히 얻기 어렵기 때문에, 최소한 다음 메타데이터는 남기는 것이 좋다.

| 컬럼명 | 타입 | 설명 |
|---|---|---|
| `has_diagram` | bool | 도표 이미지 존재 여부 |
| `diagram_page` | int | 도표가 있는 페이지 |
| `diagram_caption` | string | 도표 제목 |
| `diagram_text_summary` | string | 그림 주변 텍스트 요약 |
| `diagram_image_path` | string/null | 나중에 crop 저장 시 경로 |
| `diagram_bbox` | list/null | 이미지 crop 좌표 |

처음부터 이미지 crop까지 구현하지 않아도 된다.  
다만 나중에 확장을 위해 컬럼은 남겨두는 것이 좋다.

---

## 17. texts 컬럼

원문 추적과 전처리 검증을 위해 텍스트는 3단계로 저장한다.

| 컬럼명 | 설명 |
|---|---|
| `raw_text` | PDF에서 읽은 원문 |
| `clean_text` | 페이지 번호, 헤더, 불필요 공백 정리 |
| `structured_text` | rule 파싱을 위해 비율/제목/블록을 정리한 텍스트 |

예시:

```json
{
  "raw_text": "기본 과실비율\nA0\nB100",
  "clean_text": "기본 과실비율 A0 B100",
  "structured_text": "기본 과실비율 A 0 : B 100"
}
```

---

## 18. 클리닝 작업 설계

230630 자동차사고 과실비율 인정기준 PDF는 일반 텍스트 문서가 아니라 **표, 도표, 세로 라벨, 페이지 머리말, 목차 점선, 수정요소 표**가 섞인 공식 룰북이다. 따라서 특수문자를 무조건 삭제하면 안 된다. 과실비율 계산과 기준 해석에 필요한 문자는 보존하고, PDF 추출 과정에서 생긴 노이즈만 제거하는 방향으로 클리닝해야 한다.

---

### 18.1 텍스트 저장 단계

전처리 과정에서는 텍스트를 한 번만 저장하지 않고 3단계로 나누어 저장한다.

| 컬럼명 | 설명 | 사용 목적 |
|---|---|---|
| `raw_text` | PDF에서 추출한 원문 그대로 | 원본 추적, 파싱 오류 검증 |
| `clean_text` | 페이지 번호, 반복 헤더, 불필요 공백, 목차 점선 등을 제거한 텍스트 | 사람이 읽기 좋은 정제본 |
| `structured_text` | 비율, 제목, 수정요소, 법령을 파싱하기 쉽게 정리한 텍스트 | rule 추출, chunk 생성, DB 저장 |

예시는 다음과 같다.

```json
{
  "raw_text": "기본\n과실비율\nA0\nB100",
  "clean_text": "기본 과실비율 A0 B100",
  "structured_text": "기본 과실비율 A 0 : B 100"
}
```

---

### 18.2 제거할 텍스트

다음 항목은 검색이나 rule 추출에 도움이 되지 않으므로 `clean_text`, `structured_text`에서는 제거한다.

```text
페이지 번호
목차 점선
반복 header/footer
불필요한 줄바꿈
2칸 이상 반복 공백
PDF 추출 과정에서 생긴 의미 없는 단독 문자
```

예시:

```text
자동차사고 과실비율 인정기준 │ 제3편 과실비율 적용기준
- 38 -
....................................................................
```

단, 원본 확인을 위해 `raw_text`에는 그대로 보존한다.

---

### 18.3 보존해야 하는 특수문자

다음 문자는 과실비율 기준 해석에 필요하므로 제거하지 않는다.

```text
+
-
:
~
( )
[ ]
① ② ③ ④ ⑤
A
B
보
차
거
舊
·
```

특히 아래 표현은 rule 파싱에 직접 필요하다.

```text
+5
-10
A 70 : B 30
[보1]
[차54-1]
舊 기준
야간·기타 시야장애
어린이·노인·장애인
```

따라서 특수문자를 일괄 삭제하면 안 된다.  
특수문자는 “삭제 대상”과 “보존 대상”을 나눠 관리한다.

---

### 18.4 정규화할 특수문자

PDF에서 전각 문자나 한자식 표현이 섞일 수 있으므로 다음처럼 정규화한다.

| 원문 | 정규화 |
|---|---|
| `：` | `:` |
| `％` | `%` |
| `＋` | `+` |
| `－` | `-` |
| `–`, `—` | `-` |
| `∼`, `～` | `~` |
| `對` | `대` |
| `ㆍ` | `·` |

단, `·`는 `야간·기타`, `어린이·노인·장애인`처럼 의미가 있으므로 삭제하지 않는다.

---

### 18.5 PDF 깨짐 복원

PDF 추출 과정에서 제목이나 표 라벨이 세로로 분리될 수 있다. 이런 경우에는 원래 의미로 복원한다.

```text
과
실
비
율
조
정
예
시
↓
과실비율 조정 예시
```

```text
기본
과실비율
↓
기본 과실비율
```

```text
사고
상황
↓
사고 상황
```

```text
수정
요소
↓
수정요소
```

이 복원 작업은 `structured_text` 생성 전에 수행한다.

---

### 18.6 과실비율 표현 정규화

230630 기준서에는 과실비율이 여러 형태로 등장한다. 모두 동일한 구조로 정규화해야 한다.

| 원문 표현 | 정규화 |
|---|---|
| `A0 B100` | `A 0 : B 100` |
| `A 70 : B 30` | `A 70 : B 30` |
| `A70:B30` | `A 70 : B 30` |
| `보행자 기본 과실비율 70` | `보행자 기본 과실비율 70` |
| `차의 현저한 과실 -10` | `차의 현저한 과실 -10` |
| `보행자 급진입 비적용` | `보행자 급진입 비적용` |

자동차 대 자동차 기준은 보통 A:B 비율이므로 다음처럼 저장한다.

```json
{
  "base_fault_type": "pair_ratio",
  "party_a_ratio": 0,
  "party_b_ratio": 100,
  "normalized_ratio": "0:100"
}
```

자동차 대 보행자 기준은 한쪽 기준 과실비율로 제시되는 경우가 있으므로 다음처럼 저장한다.

```json
{
  "base_fault_type": "single_party_fault",
  "base_fault_party": "pedestrian",
  "base_fault_ratio": 70,
  "normalized_ratio": "pedestrian:70"
}
```

---

### 18.7 긴 띄어쓰기와 줄바꿈 정리

다음 규칙을 적용한다.

```text
2칸 이상 공백 → 1칸
3줄 이상 빈 줄 → 1줄 또는 2줄
문장 중간에서 끊긴 줄바꿈 → 문맥에 따라 공백으로 병합
표/항목 구분 줄바꿈 → 유지
```

예시:

```text
도로교통법     제5조에     따라
↓
도로교통법 제5조에 따라
```

단, 수정요소 표처럼 각 줄이 하나의 의미를 가지는 경우에는 줄바꿈을 유지한다.

```text
야간·기타 시야장애 +5
간선도로 +5
주택·상점가·학교 -5
```

---

### 18.8 이상한 단어 보정 원칙

230630 기준서는 공식 문서이므로 자막처럼 오타 보정을 공격적으로 하면 안 된다.  
따라서 이상한 단어는 자동 수정보다 “후보 기록” 중심으로 처리한다.

자동 수정 가능:

| 원문 | 수정 |
|---|---|
| `기본 과실비율` 중간 줄바꿈 | `기본 과실비율` |
| `사고 상황` 중간 줄바꿈 | `사고 상황` |
| `수정 요소` | `수정요소` |
| `관련 법규` | `관련법규` |
| `참고 판례` | `참고판례` |

자동 수정 금지:

```text
비보호
보호
직진
직좌
좌회전
우회전
유턴
신호위반
무단횡단
현저한 과실
중대한 과실
```

이 단어들은 사고 구조와 과실 판단에 직접 연결되므로, 애매한 경우 원문을 유지하고 `quality_flags`에 기록한다.

예시:

```json
{
  "uncertain_terms": [
    {
      "raw": "직자",
      "candidates": ["직좌", "직진"],
      "action": "not_corrected",
      "reason": "meaning_changes_fault_standard"
    }
  ]
}
```

---

### 18.9 클리닝 품질 컬럼

각 rule JSON에는 클리닝 품질을 확인할 수 있는 컬럼을 둔다.

```json
{
  "cleaning_quality": {
    "page_noise_removed": true,
    "header_footer_removed": true,
    "vertical_label_repaired": true,
    "ratio_expression_normalized": true,
    "long_spaces_normalized": true,
    "special_symbols_preserved": ["+", "-", ":", "①", "②", "舊", "·"],
    "uncertain_terms": [],
    "needs_manual_review": false
  }
}
```

검수 필요 사유가 있으면 다음처럼 저장한다.

```json
{
  "needs_manual_review": true,
  "review_reasons": [
    "base_fault_ratio_not_detected",
    "party_condition_not_detected",
    "adjustment_factor_table_parse_failed"
  ]
}
```

---

### 18.10 클리닝 최종 원칙

클리닝의 목적은 원문을 예쁘게 만드는 것이 아니라, 과실비율 rule을 안정적으로 추출하는 것이다.

따라서 최종 원칙은 다음과 같다.

```text
원문은 raw_text에 반드시 보존한다.
의미 없는 PDF 노이즈만 제거한다.
과실비율 계산에 필요한 기호는 보존한다.
비율 표현은 정규화한다.
수정요소의 +, -, 비적용은 반드시 보존한다.
애매한 단어는 자동 수정하지 않고 검수 대상으로 남긴다.
clean_text와 structured_text를 분리해서 저장한다.
```


---

## 18. chunks 컬럼

검색/RAG용 chunk다.  
chunk는 rule_blocks를 기반으로 만든다.

| 컬럼명 | 설명 |
|---|---|
| `chunk_id` | chunk ID |
| `rule_id` | 연결 rule |
| `block_id` | 연결 block |
| `chunk_type` | `accident_situation`, `base_fault_explanation`, `adjustment_explanation` 등 |
| `chunk_text` | 검색용 텍스트 |
| `rule_code` | 기준 코드 |
| `rule_title` | 기준 제목 |
| `section_path` | 목차 경로 |
| `base_fault_type` | 기본과실 유형 |
| `base_fault_ratio` | 단일 과실비율 |
| `party_a_ratio` | A 과실 |
| `party_b_ratio` | B 과실 |
| `accident_tags` | 사고 태그 |
| `law_refs` | 법령 |
| `source_reliability` | `official_standard` |

---

## 19. quality 컬럼

파싱 품질 검증용이다.

| 컬럼명 | 설명 |
|---|---|
| `parse_status` | `valid`, `review_required`, `failed` |
| `page_count_checked` | 전체 페이지 수 검증 여부 |
| `missing_pages` | 누락 페이지 |
| `rule_code_detected` | rule_code 추출 여부 |
| `title_detected` | 제목 추출 여부 |
| `base_fault_detected` | 기본과실 추출 여부 |
| `party_detected` | 당사자 추출 여부 |
| `adjustment_factor_detected` | 수정요소 추출 여부 |
| `block_split_success` | block 분리 성공 여부 |
| `needs_manual_review_reason` | 검수 필요 사유 |

---

## 20. 최종 rule JSON 예시: 보1

```json
{
  "metadata": {
    "rule_id": "official_2023_보1",
    "source_type": "fault_standard",
    "source_subtype": "official_2023",
    "source_reliability": "official_standard",
    "source_file": "230630_자동차사고 과실비율 인정기준_최종.pdf",
    "published_year": 2023,
    "published_month": 6,
    "page_start": 38,
    "page_end": 41,
    "preprocessing_version": "official_2023_v1.0"
  },
  "hierarchy": {
    "part_no": "제3편",
    "part_title": "과실비율 적용기준(사고유형별)",
    "chapter_no": "제1장",
    "chapter_title": "자동차와 보행자의 사고",
    "section_no": "4",
    "section_title": "세부유형별 과실비율 적용기준",
    "category_no": "(1)",
    "category_title": "횡단보도 내(신호등 있음)",
    "sub_category_no": "1)",
    "sub_category_title": "자동차 녹색신호 교차로 통과 후",
    "rule_group_ref": "[보1]"
  },
  "rule_identity": {
    "rule_code": "보1",
    "rule_prefix": "보",
    "rule_title": "보행자 적색신호 횡단 개시, 적색신호 충격 사고",
    "accident_group": "횡단보도",
    "rule_type": "vehicle_vs_pedestrian",
    "old_standard_refs": []
  },
  "parties": [
    {
      "party_key": "보",
      "party_label": "보행자",
      "party_type": "pedestrian",
      "movement": "횡단",
      "signal_state": "적색",
      "road_position": "횡단보도",
      "raw_text": "(보) 적색에 횡단 개시, 적색에 충격"
    },
    {
      "party_key": "차",
      "party_label": "자동차",
      "party_type": "vehicle",
      "movement": "교차로 진입",
      "signal_state": "녹색",
      "road_position": "교차로",
      "raw_text": "(차) 녹색에 교차로 진입"
    }
  ],
  "base_fault": {
    "base_fault_type": "single_party_fault",
    "base_fault_label": "보행자 기본 과실비율",
    "base_fault_party": "pedestrian",
    "base_fault_ratio": 70,
    "raw_text": "보행자 기본 과실비율 70"
  },
  "adjustment_factors": [
    {
      "order_no": "①",
      "target_party_type": "pedestrian",
      "factor_name": "야간·기타 시야장애",
      "delta": 5,
      "delta_direction": "increase",
      "raw_delta": "+5"
    },
    {
      "order_no": "⑤",
      "target_party_type": "pedestrian",
      "factor_name": "보행자 급진입",
      "delta": null,
      "delta_direction": "not_applicable",
      "raw_delta": "비적용"
    }
  ],
  "blocks": [
    {
      "block_type": "accident_situation",
      "block_title": "사고 상황",
      "text": "신호기가 있는 횡단보도에서 녹색신호에 교차로를 통과한 차량이..."
    },
    {
      "block_type": "base_fault_explanation",
      "block_title": "기본 과실비율 해설",
      "text": "도로교통법 제5조에 따라 보행자나 차마는 신호기의 신호에 따라야..."
    }
  ],
  "texts": {
    "raw_text": "...",
    "clean_text": "...",
    "structured_text": "..."
  },
  "quality": {
    "parse_status": "valid",
    "base_fault_detected": true,
    "party_detected": true,
    "adjustment_factor_detected": true
  }
}
```

---

## 21. 최종 DB 적재용 JSONL

rule JSON은 사람이 검토하기 위한 nested 구조이고, DB에는 아래처럼 납작하게 나눠 넣는 것이 좋다.

```text
rulebooks.jsonl
sections.jsonl
rules.jsonl
parties.jsonl
base_faults.jsonl
variants.jsonl
adjustment_factors.jsonl
rule_blocks.jsonl
law_refs.jsonl
reference_cases.jsonl
usage_notes.jsonl
diagrams.jsonl
chunks.jsonl
parse_quality_report.jsonl
```

---

## 22. 결론

230630 최종 인정기준 파일은 단순히 `rule_code`, `title`, `base_ratio`, `adjustments`만 뽑으면 부족하다.  
공통적으로 추가로 뽑아야 할 컬럼은 다음이다.

```text
목차 경로
rule 그룹 ref
사고 대분류/중분류
당사자 유형
당사자 행동
신호 상태
도로 위치
위반 유형
기본과실 유형
단일 과실비율 vs A:B 비율
가/나 변형 기준
舊 기준 번호
수정요소 카테고리
비적용 수정요소
사고상황
기본과실 해설
수정요소 해설
관련법규
참고판례
활용시 참고사항
도표 이미지 메타데이터
파싱 품질
```

따라서 최종 저장 방향은 다음이다.

```text
제목 기반 rule JSON
+
DB 적재용 JSONL 테이블
+
목차 section 연결
+
rule 내부 block 분리
```

한 줄로 정리하면:

```text
230630 파일은 “페이지 텍스트”가 아니라 “목차-사고유형-rule-수정요소-근거”를 가진 공식 룰북으로 저장해야 한다.
```
