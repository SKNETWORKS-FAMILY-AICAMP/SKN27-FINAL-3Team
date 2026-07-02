# 2025 2차로형 회전교차로 전처리 마지막 수정계획

## 1. 목적

이 문서는 `etl/fault_cases/src/fault_standard/preprocessing/roundabout` 폴더의 실제 코드를 기준으로, 2025 2차로형 회전교차로 기준 전처리를 마지막으로 보정하기 위한 코드 수정 계획이다.

목표는 단순히 JSON을 많이 만드는 것이 아니라, Neo4j 적재 시 회전교차로 사고 매칭에 필요한 텍스트 기반 구조를 안정적으로 만드는 것이다.

중요 원칙:

```text
1. 회전-9, 회전-13 같은 번호별 예외 하드코딩은 만들지 않는다.
2. 특정 제목이나 특정 action 문장을 dict로 고정하지 않는다.
3. 원문에 명시된 party action, 사고상황, 진입/회전/진출/차로변경 표현을 기준으로 파싱한다.
4. 확정할 수 없는 값은 확정값처럼 넣지 않고 source/confidence/review flag를 남긴다.
5. diagram/image/crop/bbox 관련 output은 만들지 않는다.
```

## 2. 현재 코드 구조

대상 폴더:

```text
etl/fault_cases/src/fault_standard/preprocessing/roundabout
```

주요 파일 역할:

```text
config.py
- PDF 탐색 키워드, 회전 rule 개수, 회전 번호 범위, 출력 경로 관리
- ROUND_GROUP_RANGES로 회전-1~8 / 회전-9~15 대분류 관리

rule_splitter.py
- PDF page text에서 회전-1~회전-15 rule section 분리
- 제목, page_start/page_end, raw_text, clean_text, structured_text 생성

extractors.py
- party, 기본과실, 수정요소, 법규, 참고판례, lane path 추출
- 이번 수정의 핵심 대상

classifiers.py
- 사고 대분류/중분류, collision zone/stage, 회전교차로 공통 context 생성

builder.py
- rule package 생성
- parse_quality_report 생성
- nested package를 DB 적재용 JSONL table로 분리

chunker.py
- rule/chunk 검색용 텍스트 생성
```

## 3. 남은 핵심 문제

최종 점검 기준으로 남은 핵심 문제는 다음과 같다.

```text
1. lane_path가 명시 텍스트 기반으로 더 촘촘하게 구조화되어야 함
2. entry_direction / exit_direction이 같은 방향으로 잘못 잡히는 경우를 더 엄격히 막아야 함
3. 줄바꿈이나 제어문자 때문에 party action이 끊긴 경우를 복원하거나 review flag로 잡아야 함
4. conflict_direction / conflict_lane은 확정값이 아니라 추론값으로 관리해야 함
5. role_in_rule을 party action과 rule title 기준으로 더 일관되게 분류해야 함
6. reference_case의 fault_ratio_in_case가 시간값을 비율로 잡지 않도록 유지 및 강화해야 함
7. diagram 관련 table/output은 만들지 않아야 함
```

## 4. `rule_splitter.py` 수정 계획

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/roundabout/rule_splitter.py

현재 함수:
- split_roundabout_rules()
- looks_like_round_title()
- finalize_rule_section()
```

### 4.1 문제

party action이 PDF 줄바꿈 때문에 아래처럼 끊기면 후속 extractor가 차로변경/진출을 놓칠 수 있다.

```text
12시 방향 1차로로 선진입한 후 회전하다 2차로로 차로변경하여
3시 방향으로 진출
```

이 경우 현재 `finalize_rule_section()`은 `clean_pdf_text()`와 `structure_rule_text()`에 맡기지만, party action 단위의 줄 병합 의도가 명확하지 않다.

### 4.2 코드 수정 계획

`finalize_rule_section()` 안에서 section 전체를 구조화하기 전에 party action 줄 병합용 helper를 추가한다.

추가 함수:

```python
def merge_broken_party_action_lines(lines: List[str]) -> List[str]:
    ...
```

처리 규칙:

```text
1. 레드(A) :, 블루(B) : 로 시작한 줄은 party action 시작으로 본다.
2. 다음 줄이 기본 과실비율, 과실비율 조정 예시, 사고 상황, 관련 법규 같은 marker가 아니면 같은 party action의 연속으로 붙인다.
3. 다음 줄이 다른 party line이면 현재 party action을 마감한다.
4. 줄 끝이 "차로로", "방향으로", "차로변경하여", "진로변경하여"이면 다음 줄과 반드시 결합 후보로 본다.
```

예상 코드 흐름:

```python
merged_lines = merge_broken_party_action_lines(section["lines"])
raw_text = "\n".join(merged_lines).strip()
```

### 4.3 기대 output

`parties.jsonl`의 `action_summary`가 끊기지 않는다.

예상:

```json
{
  "party_key": "A",
  "action_summary": "12시 방향 1차로로 선진입한 후 회전하다 2차로로 차로변경하여 3시 방향으로 진출",
  "is_lane_changing": true,
  "is_exiting": true,
  "exit_direction": "3시 방향"
}
```

## 5. `extractors.py` party direction / lane parser 수정 계획

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/roundabout/extractors.py

현재 함수:
- extract_parties()
- normalize_party_action()
- extract_direction()
- extract_lane()
- extract_lane_change_from()
- extract_lane_change_to()
- has_dangling_action_suffix()
```

### 5.1 문제

진입 방향과 진출 방향은 같은 action 안에 여러 방향이 같이 나온다.

예:

```text
12시 방향 1차로로 선진입하여 회전하다 3시 방향 1차로로 진출
```

여기서 `entry_direction=12시 방향`, `exit_direction=3시 방향`이어야 한다.

### 5.2 코드 수정 계획

`extract_direction(action, keyword)`를 더 문맥 기반으로 분리한다.

추가 helper:

```python
def extract_direction_near_verbs(action: str, verbs: List[str]) -> Optional[str]:
    ...

def extract_entry_direction(action: str) -> Optional[str]:
    ...

def extract_exit_direction(action: str) -> Optional[str]:
    ...
```

수정 전:

```python
"entry_direction": extract_direction(action, "진입")
"exit_direction": extract_direction(action, "진출")
```

수정 후:

```python
"entry_direction": extract_entry_direction(action)
"exit_direction": extract_exit_direction(action)
```

판단 기준:

```text
entry_direction:
- 선진입, 후진입, 진입, 회전교차로에 진입 주변의 방향만 인정

exit_direction:
- 진출 주변의 방향만 인정
- "12시 방향으로 회전 중" 같은 표현은 exit_direction으로 쓰지 않음
```

### 5.3 기대 output

```json
{
  "entry_direction": "12시 방향",
  "exit_direction": "3시 방향",
  "direction_parse_source": {
    "entry_direction": "near_entry_verb",
    "exit_direction": "near_exit_verb"
  }
}
```

## 6. `extractors.py` LaneStep 구조화 수정 계획

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/roundabout/extractors.py

현재 함수:
- build_lane_path_context()
- extract_lane_sequence()
- extract_lane_steps()
- format_lane_step_text()
- infer_expected_path()
```

### 6.1 문제

회전-9~15는 선진입 회전차량과 후진입 차량의 경로가 핵심이다.

이 기준은 단순히 `red_path=["회전1차로"]` 정도로는 부족하고, 다음 단계가 필요하다.

```text
진입
회전
차로변경 전
차로변경 후
진출
```

### 6.2 코드 수정 계획

`extract_lane_steps()`를 action 문장의 순서대로 movement step을 만드는 방식으로 강화한다.

추가 helper:

```python
def extract_ordered_lane_mentions(action: str) -> List[Dict[str, Any]]:
    ...

def infer_step_movement(context: str) -> str:
    ...

def normalize_lane_token(raw: str, movement: str) -> Optional[str]:
    ...
```

처리 방식:

```text
1. action에서 방향/차로/동사를 순서대로 스캔한다.
2. "선진입", "후진입", "진입" 주변은 movement="진입"
3. "회전" 주변은 movement="회전"
4. "차로변경", "진로변경" 주변은 movement="차로변경"
5. "진출" 주변은 movement="진출"
6. 명시 차로가 없고 방향만 있으면 direction_only step으로 보존한다.
```

예상 output:

```json
{
  "red_lane_steps": [
    {"seq": 1, "movement": "진입", "lane": "진입1차로", "direction": "12시 방향", "source": "explicit_text"},
    {"seq": 2, "movement": "회전", "lane": "회전1차로", "direction": null, "source": "derived_from_entry_lane"},
    {"seq": 3, "movement": "진출", "lane": "진출1차로", "direction": "3시 방향", "source": "explicit_text"}
  ]
}
```

### 6.3 하드코딩 금지 기준

아래 방식은 금지한다.

```python
if round_no == 13:
    exit_direction = "3시 방향"
```

대신 action 안에서 `진출` 문맥을 찾아 추출한다.

## 7. `extractors.py` conflict 값 관리 수정 계획

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/roundabout/extractors.py

현재 함수:
- infer_conflict_lane()
- infer_conflict_direction()
- extract_conflict_context()
- build_lane_path_context()
```

### 7.1 문제

`conflict_lane`, `conflict_direction`은 원문에 명확히 쓰여 있지 않으면 확정값으로 쓰면 위험하다.

현재 코드도 source/confidence를 넣고 있지만, output에서 더 명확히 “추론 후보”임을 표현해야 한다.

### 7.2 코드 수정 계획

`infer_conflict_lane()`과 `infer_conflict_direction()`의 반환값을 단일 문자열이 아니라 판단 객체로 바꾼다.

추가 함수:

```python
def infer_conflict_lane_info(parties: List[Dict[str, Any]], text: str) -> Dict[str, Any]:
    ...

def infer_conflict_direction_info(parties: List[Dict[str, Any]], text: str) -> Dict[str, Any]:
    ...
```

반환 구조:

```json
{
  "value": "3시 방향",
  "source": "derived_from_exit_direction",
  "confidence": 0.65,
  "is_confirmed": false
}
```

확정 조건:

```text
1. 사고상황/충돌 문장에 "3시 방향 진출부 사고"처럼 직접 명시되면 is_confirmed=true
2. party exit_direction에서 가져온 값이면 is_confirmed=false
3. 차로변경 후 차로에서 가져온 conflict_lane이면 is_confirmed=false
```

### 7.3 기대 output

`lane_paths.jsonl`에 아래 필드를 추가한다.

```json
{
  "conflict_direction": "3시 방향",
  "conflict_direction_source": "derived_from_exit_direction",
  "conflict_direction_confidence": 0.65,
  "conflict_direction_confirmed": false,
  "conflict_lane": "회전1차로",
  "conflict_lane_source": "derived_from_lane_change_to",
  "conflict_lane_confidence": 0.65,
  "conflict_lane_confirmed": false
}
```

parse quality에는 아래 flag를 남긴다.

```json
{
  "quality_flags": [
    "conflict_direction_derived",
    "conflict_lane_derived"
  ]
}
```

## 8. `extractors.py` role_in_rule 수정 계획

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/roundabout/extractors.py

현재 함수:
- infer_role()
```

### 8.1 문제

회전교차로는 party 역할이 매칭에서 중요하다.

필요한 역할:

```text
entry_vehicle
circulating_vehicle
exiting_vehicle
lane_changing_vehicle
lane_changing_at_exit
first_entry_vehicle
late_entry_vehicle
```

### 8.2 코드 수정 계획

`infer_role()`에서 title과 action을 모두 보되, action에 명시된 동작을 우선한다.

판단 순서:

```text
1. title이 "진입한 차량 간 진입부 사고"이면 양쪽 entry_vehicle
2. action에 후진입이면 late_entry_vehicle
3. action에 선진입이면 first_entry_vehicle
4. action에 차로변경 + 진출이면 lane_changing_at_exit
5. action에 차로변경이면 lane_changing_vehicle
6. action에 진출이면 exiting_vehicle
7. action에 회전이면 circulating_vehicle
8. 그 외 entry_vehicle
```

현재 코드가 이 방향을 이미 일부 따르고 있으므로, 마지막 수정에서는 helper를 분리해 검증 가능하게 만든다.

추가 helper:

```python
def infer_role_reason(action: str, rule_title: str) -> Dict[str, Any]:
    ...
```

예상 output:

```json
{
  "role_in_rule": "first_entry_vehicle",
  "role_source": "action_contains_first_entry",
  "role_confidence": 0.9
}
```

## 9. `extractors.py` reference_case 비율 parser 유지 및 강화

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/roundabout/extractors.py

현재 함수:
- extract_reference_cases()
- extract_fault_ratio_text()
- is_time_like_ratio()
```

### 9.1 현재 좋은 점

현재 코드에는 이미 시간값 방지 로직이 있다.

```python
if is_time_like_ratio(left, right, context):
    continue
```

이 방향은 유지한다.

### 9.2 추가 수정 계획

시간값 방지 기준을 조금 더 명확히 한다.

```python
def is_time_like_ratio(left: int, right: int, context: str) -> bool:
    ...
```

강화 기준:

```text
1. 0~23 : 0~59 형태이고 주변에 과실/비율/책임/부담이 없으면 시간으로 본다.
2. 주변에 시각, 무렵, 경, 분, 사고일시 같은 단어가 있으면 시간으로 본다.
3. left + right == 100 이거나 주변에 과실/비율/책임이 있으면 과실비율 후보로 인정한다.
```

예상 output:

```json
{
  "fault_ratio_in_case": null,
  "ratio_parse_status": "not_found_or_time_excluded"
}
```

비율이 명확한 경우:

```json
{
  "fault_ratio_in_case": "40:60",
  "ratio_parse_status": "complete"
}
```

## 10. `builder.py` parse_quality_report 수정 계획

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/roundabout/builder.py

현재 함수:
- build_parse_quality()
- is_direction_parse_suspicious()
- flatten_packages_to_tables()
- build_lane_step_rows()
```

### 10.1 문제

품질 flag가 있어도 어떤 값이 확정값이고 어떤 값이 추론값인지 downstream에서 바로 알기 어렵다.

### 10.2 코드 수정 계획

`build_parse_quality()`에 아래 검증을 추가한다.

```python
if lane_path_context.get("conflict_direction") and not lane_path_context.get("conflict_direction_confirmed"):
    quality_flags.append("conflict_direction_derived")

if lane_path_context.get("conflict_lane") and not lane_path_context.get("conflict_lane_confirmed"):
    quality_flags.append("conflict_lane_derived")

if any(p.get("exit_direction") and p.get("entry_direction") == p.get("exit_direction") for p in parties):
    reasons.append("entry_exit_direction_same_check")
```

`is_direction_parse_suspicious()`는 다음 기준으로 유지/강화한다.

```text
1. action에 진출이 있는데 exit_direction이 없으면 suspicious
2. action에 방향이 2개 이상 있는데 entry_direction == exit_direction이면 suspicious
3. action 끝이 "방향으로", "차로변경하여"처럼 끊기면 dangling_action_suffix
```

### 10.3 기대 output

```json
{
  "parse_status": "review_required",
  "lane_path_detected": true,
  "direction_parse_suspicious": false,
  "quality_flags": [
    "conflict_direction_derived"
  ],
  "needs_manual_review_reason": []
}
```

## 11. `builder.py` table output 수정 계획

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/roundabout/builder.py

현재 함수:
- flatten_packages_to_tables()
- build_lane_step_rows()
```

### 11.1 유지할 table

```text
rules.jsonl
parties.jsonl
base_faults.jsonl
roundabout_contexts.jsonl
lane_paths.jsonl
lane_steps.jsonl
adjustment_factors.jsonl
rule_blocks.jsonl
law_refs.jsonl
reference_cases.jsonl
chunks.jsonl
parse_quality_report.jsonl
```

### 11.2 만들지 않을 table

```text
diagrams.jsonl
diagram_images
image_bboxes
```

확인 기준:

```powershell
rg "\"diagrams\"|diagram_image|diagram_bbox|build_diagram" etl/fault_cases/src/fault_standard/preprocessing/roundabout
```

검색 결과가 있으면 제거 대상이다.

### 11.3 기대 output

`lane_steps.jsonl`:

```json
{
  "lane_step_id": "lane_step_roundabout_2025_회전-13_A_01",
  "rule_id": "roundabout_2025_회전-13",
  "party_key": "A",
  "party_color": "red",
  "seq": 1,
  "movement": "진입",
  "lane": "진입1차로",
  "direction": "12시 방향",
  "source": "explicit_text"
}
```

`lane_paths.jsonl`:

```json
{
  "rule_id": "roundabout_2025_회전-13",
  "red_path": ["12시 방향 진입1차로", "회전1차로", "3시 방향 진출1차로"],
  "blue_path": ["6시 방향 진입2차로", "회전2차로", "회전1차로"],
  "path_conflict_type": "lane_change_conflict",
  "conflict_direction": "3시 방향",
  "conflict_direction_confirmed": false,
  "conflict_lane_confirmed": false
}
```

## 12. `classifiers.py` 수정 계획

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/roundabout/classifiers.py

현재 함수:
- classify_accident()
- infer_accident_subgroup()
- infer_collision_zone()
- infer_collision_stage()
- infer_movement_relation()
```

### 12.1 문제

classification은 title/text keyword 기반이지만, party에서 추출한 lane path 결과와 연결되지 않는다.

### 12.2 코드 수정 계획

`classify_accident()`의 역할은 유지하되, lane path 확정값을 분류 함수 안에 박지 않는다.

유지할 원칙:

```text
1. 대분류는 config.py의 ROUND_GROUP_RANGES 기준
2. 중분류는 title/text marker 기준
3. 차로 경로와 conflict 판단은 extractors.py의 lane_path_context 기준
4. classifiers.py에서 회전번호별 exit_direction, conflict_direction을 보정하지 않는다.
```

필요 시 추가 필드:

```json
{
  "classification_source": "round_group_range_and_title_text",
  "classification_confidence": 0.8
}
```

## 13. 최종 검증 기준

코드 수정 후 기대되는 검증 기준은 다음과 같다.

```text
1. rules 15개 유지
2. parties 30개 유지
3. base_faults 15개 유지
4. adjustment_factors target 누락 0건 유지
5. lane_paths red_path/blue_path 빈값 0건 목표
6. lane_steps는 party별 순서가 보존되어야 함
7. entry_direction과 exit_direction이 다른 문맥에서 추출되어야 함
8. conflict_direction/conflict_lane은 confirmed/source/confidence와 함께 제공
9. reference_cases에서 10:02, 15:00 같은 시간값이 fault_ratio로 들어가지 않아야 함
10. diagrams.jsonl은 생성하지 않아야 함
```

## 14. 최종 기대 결과

이번 수정 후 2025 회전교차로 전처리 결과는 다음 상태를 목표로 한다.

```text
기본과실 조회:
- 가능

수정요소 계산:
- 가능

회전교차로 사고유형 매칭:
- lane_steps 기반으로 진입/회전/차로변경/진출 경로 매칭 가능

conflict_direction/conflict_lane:
- 확정값이 아니라 추론값이면 derived flag와 confidence를 함께 사용

reference_case:
- 시간값 오인식 제거

diagram/image:
- 이번 텍스트 전처리 범위에서 제외
```

---

## 15. 실제 코드 라인 기준 상세 변경 설계

위 계획은 방향성이고, 이 섹션은 실제 현재 코드의 흐름을 기준으로 “어떤 코드를 어떻게 바꿔서 어떤 output을 만들 것인지”를 더 구체적으로 적은 작업 설계다.

### 15.1 `extractors.py` - `extract_parties()`의 현재 row 생성 방식 수정

현재 코드 흐름:

```python
parties.append(
    {
        "role_in_rule": infer_role(action, rule_title=rule_title),
        "action_summary": action,
        "entry_direction": extract_direction(action, "진입"),
        "entry_lane": extract_lane(action, "진입"),
        "circulation_lane": extract_lane(action, "회전"),
        "exit_direction": extract_direction(action, "진출"),
        "exit_lane": extract_lane(action, "진출"),
        "lane_change_from": extract_lane_change_from(action),
        "lane_change_to": extract_lane_change_to(action),
        ...
    }
)
```

문제:

```text
1. entry_direction / exit_direction 추출 source가 output에 남지 않는다.
2. role_in_rule이 어떤 근거로 결정됐는지 output에서 알 수 없다.
3. direction parser가 실패해도 어느 단계에서 실패했는지 확인하기 어렵다.
```

수정 계획:

`extract_parties()` 내부에서 값을 바로 넣지 않고, 먼저 분석 객체를 만든다.

추가할 함수:

```python
def parse_party_action(action: str, rule_title: str) -> Dict[str, Any]:
    role_info = infer_role_info(action, rule_title)
    entry_direction_info = extract_direction_info(action, kind="entry")
    exit_direction_info = extract_direction_info(action, kind="exit")
    lane_info = extract_lane_info(action)
    lane_change_info = extract_lane_change_info(action)

    return {
        "role_in_rule": role_info["value"],
        "role_source": role_info["source"],
        "role_confidence": role_info["confidence"],
        "entry_direction": entry_direction_info["value"],
        "entry_direction_source": entry_direction_info["source"],
        "entry_direction_confidence": entry_direction_info["confidence"],
        "exit_direction": exit_direction_info["value"],
        "exit_direction_source": exit_direction_info["source"],
        "exit_direction_confidence": exit_direction_info["confidence"],
        **lane_info,
        **lane_change_info,
    }
```

`extract_parties()` 변경 후 흐름:

```python
action_info = parse_party_action(action, rule_title)

parties.append(
    {
        "party_id": f"party_{rule_id}_{party_key}",
        "rule_id": rule_id,
        "party_key": party_key,
        "party_color": party_color,
        "party_label": f"{color_ko}({party_key})",
        "party_type": "vehicle",
        "action_summary": action,
        **action_info,
        "is_first_entry": "선진입" in action,
        "is_late_entry": "후진입" in action,
        "is_lane_changing": "차로변경" in action or "진로변경" in action,
        "is_exiting": "진출" in action,
        "raw_text": f"{color_ko}({party_key}) : {action}",
    }
)
```

예상 `parties.jsonl` output:

```json
{
  "rule_id": "roundabout_2025_회전-13",
  "party_key": "A",
  "party_color": "red",
  "role_in_rule": "first_entry_vehicle",
  "role_source": "action_contains_first_entry",
  "role_confidence": 0.9,
  "action_summary": "12시 방향 1차로로 선진입하여 회전하다 3시 방향 1차로로 진출",
  "entry_direction": "12시 방향",
  "entry_direction_source": "near_entry_verb",
  "entry_direction_confidence": 0.95,
  "exit_direction": "3시 방향",
  "exit_direction_source": "near_exit_verb",
  "exit_direction_confidence": 0.95,
  "entry_lane": "진입1차로",
  "circulation_lane": "회전1차로",
  "exit_lane": "진출1차로"
}
```

이렇게 하면 나중에 Neo4j 적재 시 `role_in_rule`, `entry_direction`, `exit_direction`을 그냥 값으로만 보지 않고 근거와 confidence까지 같이 볼 수 있다.

### 15.2 `extractors.py` - `extract_direction()`을 단일 함수에서 source 포함 함수로 변경

현재 코드:

```python
def extract_direction(action: str, keyword: str) -> Optional[str]:
    if keyword == "진입":
        patterns = [...]
        return first_group_match(patterns, action, "direction")

    if keyword == "진출":
        patterns = [...]
        return last_group_match(patterns, action, "direction")
```

문제:

```text
값만 반환하므로 어떤 pattern에서 잡혔는지 모른다.
진입/진출 방향이 같은 값으로 잡혔을 때 원인 추적이 어렵다.
```

수정 계획:

기존 `extract_direction()`은 호환용 wrapper로 남기고, 실제 parser는 info 객체를 반환한다.

추가할 함수:

```python
def extract_direction_info(action: str, kind: str) -> Dict[str, Any]:
    action = normalize_spaces(action)

    if kind == "entry":
        return match_direction_patterns(
            action,
            [
                ("near_entry_verb", r"(?P<direction>(?:3시|6시|9시|12시)\s*방향)\s*(?:[12]차로)?(?:에서|로)?\s*(?:선진입|후진입|진입)"),
                ("near_roundabout_entry", r"(?P<direction>(?:3시|6시|9시|12시)\s*방향).*?회전교차로에\s*(?:선진입|후진입|진입)"),
            ],
            pick="first",
        )

    if kind == "exit":
        return match_direction_patterns(
            action,
            [
                ("near_exit_verb", r"(?P<direction>(?:3시|6시|9시|12시)\s*방향)\s*(?:[12]차로)?(?:로)?\s*진출"),
                ("direction_to_exit", r"(?P<direction>(?:3시|6시|9시|12시)\s*방향)(?:으로)?\s*진출"),
            ],
            pick="last",
        )
```

반환값:

```json
{
  "value": "3시 방향",
  "source": "near_exit_verb",
  "confidence": 0.95
}
```

실패 시:

```json
{
  "value": null,
  "source": null,
  "confidence": 0.0
}
```

기존 wrapper:

```python
def extract_direction(action: str, keyword: str) -> Optional[str]:
    kind = "entry" if keyword == "진입" else "exit" if keyword == "진출" else "generic"
    return extract_direction_info(action, kind).get("value")
```

기대 효과:

```text
1. 진입 방향은 진입 동사 주변에서만 추출
2. 진출 방향은 진출 동사 주변에서만 추출
3. "12시 방향으로 회전 중" 같은 표현이 exit_direction으로 들어가지 않음
```

### 15.3 `extractors.py` - `extract_lane_steps()`를 현재 필드 재조립 방식에서 action 순서 스캔 방식으로 변경

현재 코드:

```python
add_step("진입", party.get("entry_lane"), party.get("entry_direction"))
add_step("회전", party.get("circulation_lane"), None)

if lane_change_from or lane_change_to:
    add_step("차로변경_전", lane_change_from, None)
    add_step("차로변경_후", lane_change_to, None)

add_step("진출", party.get("exit_lane"), party.get("exit_direction"))
```

문제:

```text
현재 방식은 이미 추출된 필드를 정해진 순서로 재조립한다.
원문에서 어떤 순서로 등장했는지, 어떤 문맥에서 나온 lane인지가 충분히 보존되지 않는다.
```

수정 계획:

action 원문을 직접 스캔해서 `LaneStep` 후보를 만든다.

추가할 함수:

```python
def extract_ordered_lane_steps_from_action(action: str) -> List[Dict[str, Any]]:
    ...
```

내부 처리:

```text
1. action에서 방향 표현과 차로 표현을 위치 index와 함께 추출
2. 각 표현 주변 30~50자 context를 확인
3. context에 선진입/후진입/진입이 있으면 movement="진입"
4. context에 회전이 있으면 movement="회전"
5. context에 차로변경/진로변경이 있으면 movement="차로변경"
6. context에 진출이 있으면 movement="진출"
7. index 순서대로 seq 부여
```

변경 후 `extract_lane_steps()`:

```python
def extract_lane_steps(party: Dict[str, Any]) -> List[Dict[str, Any]]:
    action = party.get("action_summary", "")
    ordered = extract_ordered_lane_steps_from_action(action)

    if ordered:
        return enrich_lane_steps_with_party_fields(ordered, party)

    return build_lane_steps_from_party_fields(party)
```

예상 `lane_steps.jsonl` output:

```json
{
  "lane_step_id": "lane_step_roundabout_2025_회전-15_A_03",
  "rule_id": "roundabout_2025_회전-15",
  "party_key": "A",
  "party_color": "red",
  "seq": 3,
  "movement": "진출",
  "lane": null,
  "direction": "3시 방향",
  "source": "ordered_action_scan",
  "source_text": "3시 방향으로 진출"
}
```

`build_lane_step_rows()`도 `source_text`를 보존하도록 수정한다.

현재:

```python
"source": step.get("source"),
```

수정:

```python
"source": step.get("source"),
"source_text": step.get("source_text"),
"confidence": step.get("confidence"),
```

### 15.4 `extractors.py` - `build_lane_path_context()`의 conflict 문자열 반환 구조 변경

현재 코드:

```python
conflict_lane = infer_conflict_lane(parties, text, round_no)
conflict_direction = infer_conflict_direction(parties, text, round_no)

return {
    ...
    "conflict_lane": conflict_lane,
    "conflict_lane_source": "derived_from_lane_change_or_conflict_context" if conflict_lane else None,
    "conflict_direction": conflict_direction,
    "conflict_direction_source": "derived_from_conflict_or_exit_context" if conflict_direction else None,
    "conflict_direction_confidence": 0.65 if conflict_direction else 0.0,
}
```

문제:

```text
source가 고정 문자열이라 실제로 conflict_context에서 나온 값인지,
exit_direction에서 추론한 값인지,
lane_change_to에서 추론한 값인지 구분이 부족하다.
```

수정 계획:

`infer_conflict_lane()` / `infer_conflict_direction()`은 유지하지 않고, info 함수로 교체한다.

추가할 함수:

```python
def infer_conflict_lane_info(parties: List[Dict[str, Any]], text: str) -> Dict[str, Any]:
    ...

def infer_conflict_direction_info(parties: List[Dict[str, Any]], text: str) -> Dict[str, Any]:
    ...
```

`build_lane_path_context()` 변경 후:

```python
conflict_lane_info = infer_conflict_lane_info(parties, text)
conflict_direction_info = infer_conflict_direction_info(parties, text)

return {
    ...
    "conflict_lane": conflict_lane_info["value"],
    "conflict_lane_source": conflict_lane_info["source"],
    "conflict_lane_confidence": conflict_lane_info["confidence"],
    "conflict_lane_confirmed": conflict_lane_info["confirmed"],
    "conflict_direction": conflict_direction_info["value"],
    "conflict_direction_source": conflict_direction_info["source"],
    "conflict_direction_confidence": conflict_direction_info["confidence"],
    "conflict_direction_confirmed": conflict_direction_info["confirmed"],
}
```

`infer_conflict_lane_info()` 판단 순서:

```text
1. extract_conflict_context(text)에 차로가 직접 있으면 source="explicit_conflict_context", confirmed=true, confidence=0.9
2. party lane_change_to에서 가져오면 source="derived_from_lane_change_to", confirmed=false, confidence=0.65
3. party exit_lane에서 가져오면 source="derived_from_exit_lane", confirmed=false, confidence=0.6
4. 없으면 value=null
```

`infer_conflict_direction_info()` 판단 순서:

```text
1. extract_conflict_context(text)에 "3시 방향 진출부 사고"처럼 직접 있으면 source="explicit_conflict_context", confirmed=true, confidence=0.9
2. party exit_direction에서 가져오면 source="derived_from_exit_direction", confirmed=false, confidence=0.65
3. 없으면 value=null
```

예상 `lane_paths.jsonl` output:

```json
{
  "rule_id": "roundabout_2025_회전-13",
  "conflict_direction": "3시 방향",
  "conflict_direction_source": "derived_from_exit_direction",
  "conflict_direction_confidence": 0.65,
  "conflict_direction_confirmed": false,
  "conflict_lane": "회전1차로",
  "conflict_lane_source": "derived_from_lane_change_to",
  "conflict_lane_confidence": 0.65,
  "conflict_lane_confirmed": false
}
```

### 15.5 `builder.py` - `build_parse_quality()`의 derived flag 조건 수정

현재 코드:

```python
if lane_path_context.get("conflict_direction"):
    quality_flags.append("conflict_direction_derived")

if lane_path_context.get("conflict_lane"):
    quality_flags.append("conflict_lane_derived")
```

문제:

```text
명시적으로 확정된 conflict 값도 무조건 derived flag가 붙는다.
```

수정 계획:

```python
if lane_path_context.get("conflict_direction") and not lane_path_context.get("conflict_direction_confirmed"):
    quality_flags.append("conflict_direction_derived")

if lane_path_context.get("conflict_lane") and not lane_path_context.get("conflict_lane_confirmed"):
    quality_flags.append("conflict_lane_derived")
```

추가 검증:

```python
if any(p.get("entry_direction") and p.get("exit_direction") and p.get("entry_direction") == p.get("exit_direction") for p in parties):
    reasons.append("entry_exit_direction_same_check")

if any(p.get("is_lane_changing") and not p.get("lane_change_to") for p in parties):
    reasons.append("lane_change_target_missing")
```

예상 `parse_quality_report.jsonl` output:

```json
{
  "rule_id": "roundabout_2025_회전-13",
  "parse_status": "valid",
  "conflict_direction_source": "derived_from_exit_direction",
  "conflict_direction_confidence": 0.65,
  "quality_flags": [
    "conflict_direction_derived"
  ],
  "needs_manual_review_reason": []
}
```

방향 파싱이 의심되는 경우:

```json
{
  "parse_status": "review_required",
  "quality_flags": [
    "entry_exit_direction_same_check"
  ],
  "needs_manual_review_reason": [
    "entry_exit_direction_same_check"
  ]
}
```

### 15.6 `builder.py` - `flatten_packages_to_tables()` output 확장

현재 코드:

```python
tables["lane_paths"].append({"rule_id": rule_id, **package["lane_path_context"]})
tables["lane_steps"].extend(build_lane_step_rows(rule_id, package["lane_path_context"]))
```

수정 계획:

`lane_path_context`에 추가된 아래 필드가 그대로 `lane_paths.jsonl`에 들어가게 한다.

```text
conflict_lane_confidence
conflict_lane_confirmed
conflict_direction_confirmed
red_path_parse_status
blue_path_parse_status
```

`build_lane_step_rows()`는 step 단위 근거를 보존한다.

현재 output:

```json
{
  "movement": "진출",
  "lane": "진출1차로",
  "direction": "3시 방향",
  "source": "explicit_text"
}
```

수정 후 output:

```json
{
  "movement": "진출",
  "lane": "진출1차로",
  "direction": "3시 방향",
  "source": "ordered_action_scan",
  "source_text": "3시 방향 1차로로 진출",
  "confidence": 0.95
}
```

### 15.7 `extractors.py` - `extract_fault_ratio_text()` output status 추가

현재 코드:

```python
"fault_ratio_in_case": extract_fault_ratio_text(get_context(block, match.start(), match.end(), 300)),
```

문제:

```text
비율이 없어서 null인지, 시간값이라 제외돼서 null인지 구분되지 않는다.
```

수정 계획:

`extract_fault_ratio_text()`를 wrapper로 두고, 상태 객체를 반환하는 함수를 추가한다.

추가 함수:

```python
def extract_fault_ratio_info(text: str) -> Dict[str, Any]:
    ...
```

반환값:

```json
{
  "value": null,
  "status": "time_like_ratio_excluded",
  "excluded_candidate": "10:02"
}
```

`extract_reference_cases()` 변경:

```python
ratio_info = extract_fault_ratio_info(context)

"fault_ratio_in_case": ratio_info["value"],
"fault_ratio_parse_status": ratio_info["status"],
"fault_ratio_excluded_candidate": ratio_info.get("excluded_candidate"),
```

예상 `reference_cases.jsonl` output:

```json
{
  "reference_case_id": "refcase_roundabout_2025_회전-07_001",
  "fault_ratio_in_case": null,
  "fault_ratio_parse_status": "time_like_ratio_excluded",
  "fault_ratio_excluded_candidate": "10:02"
}
```

### 15.8 `rule_splitter.py` - party action 줄 병합 위치 명확화

현재 코드:

```python
raw_text = "\n".join(section["lines"]).strip()
clean_text = clean_pdf_text(raw_text)
structured_text = structure_rule_text(clean_text)
```

수정 계획:

```python
merged_lines = merge_broken_party_action_lines(section["lines"])
raw_text = "\n".join(merged_lines).strip()
clean_text = clean_pdf_text(raw_text)
structured_text = structure_rule_text(clean_text)
```

추가 helper:

```python
def is_section_marker(line: str) -> bool:
    return any(marker in line for marker in [
        "기본 과실비율",
        "과실비율 조정 예시",
        "사고 상황",
        "관련 법규",
        "참고 판례",
    ])
```

병합 기준:

```text
1. party line 이후 section marker 전까지는 같은 action 후보
2. 다음 party line이 나오면 이전 party action 종료
3. line 끝이 연결형이면 다음 줄과 강제 병합
```

예상 결과:

```text
레드(A) : 12시 방향 1차로로 선진입한 후 회전하다 2차로로 차로변경하여 3시 방향으로 진출
```

### 15.9 diagram 관련 코드 점검 기준

이번 수정에서 절대 추가하지 않을 코드:

```python
tables["diagrams"] = []
package["diagram"] = ...
"diagram_image_path": ...
"diagram_bbox": ...
```

계획서 기준 확인 명령:

```powershell
rg "\"diagrams\"|diagram_image|diagram_bbox|build_diagram|crop" etl/fault_cases/src/fault_standard/preprocessing/roundabout
```

있다면 텍스트 전처리 범위에서는 제거 대상이다.
