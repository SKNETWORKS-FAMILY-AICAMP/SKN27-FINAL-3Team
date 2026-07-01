# 2021 PM 기준 마지막 전처리 수정 계획

## 1. 현재 상태 판단

2021 PM 대 자동차 기준은 이전보다 구조가 많이 좋아졌다.

현재 감사 결과상 이미 반영이 잘 된 부분은 다음과 같다.

```text
rules: 38개 정상
parties: 76개 정상
A/B 방향: A=PM 38개, B=자동차 38개 정상
base_faults: 38개 정상
adjustment_factors: 282개 정상
adjustment target_party_key/type 누락: 0건
shared_rule_group_chunks text null: 0건
rule_scenarios 구조 생성됨
제어문자 잔존: 0건
```

하지만 Neo4j 최종 적재 기준으로는 아직 위험한 문제가 남아 있다.

가장 큰 문제는 `road_contexts.jsonl`에 수정요소 조건이나 공통 해설 조건이 섞이는 것이다.

예를 들어 `도표02 PM 신호위반 사고`인데 아래처럼 들어갈 수 있다.

```json
{
  "road_area": "교차로",
  "has_bicycle_road": true,
  "has_bicycle_crossing": true,
  "has_crosswalk": true,
  "has_sidewalk": true
}
```

이 값들은 기본 사고상황이 아니라 수정요소 또는 공통 해설에서 딸려온 조건일 가능성이 크다.

이 상태로 Neo4j에 넣으면 사용자가 “PM 신호위반 사고”를 입력했을 때, 그래프가 “자전거도로/횡단보도/보도 사고”로 잘못 후보를 좁힐 수 있다.

---

## 2. 수정 원칙

PM 기준 마지막 수정의 원칙은 다음과 같다.

```text
1. 기본 사고상황과 수정요소 조건을 완전히 분리한다.
2. road_context는 제목 + 사고상황 표 + 기본과실 주변 텍스트만 사용한다.
3. 수정요소 표, 도표해설, 관련법규, 참고판례, 심의사례는 road_context에 직접 섞지 않는다.
4. 인근 자전거도로, 좌측통행, 보도통행, 야간, 시야장애는 adjustment_condition_context로만 둔다.
5. 특정 도표번호 기반 하드코딩은 추가하지 않는다.
6. diagram/image 산출물은 만들지 않는다.
```

이번 PM 수정의 핵심은 “PM 기준서를 더 많이 파싱하는 것”이 아니라 “기본 사고상황만 정확히 분리하는 것”이다.

---

## 3. 문제 1: road_context 오염

### 3.1 문제

PM 기준은 수정요소 표와 해설에 아래 조건이 자주 등장한다.

```text
인근에 자전거도로가 있는 경우
자전거횡단도
보도통행
좌측통행
야간
기타 시야장애
횡단금지 표지 있음
주택·상점가·학교
제동등 고장
```

이 값들은 기본 도로상황이 아니라 과실 가감 조건이다.

그런데 현재 일부 rule에서는 이 값들이 `road_contexts.jsonl`에도 들어간다.

문제 예시는 다음과 같다.

```text
도표02 PM 신호위반 사고
현재 위험값:
- has_bicycle_road = true
- has_bicycle_crossing = true
- has_crosswalk = true
- has_sidewalk = true

기대:
- 기본 사고상황은 신호위반 교차로 사고
- 자전거도로/횡단보도/보도는 기본 road_context에 넣지 않음
```

### 3.2 수정 대상

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/pm_auto/extractors.py
etl/fault_cases/src/fault_standard/preprocessing/pm_auto/classifiers.py
etl/fault_cases/src/fault_standard/preprocessing/pm_auto/builder.py

주요 함수:
- extract_base_context_text()
- build_road_context()
- build_signal_context()
- classify_accident()
- build_adjustment_condition_context()
```

### 3.3 수정 방식

현재 `extract_base_context_text()`는 수정요소 이후 영역을 자르려 하지만, 실제 PDF 추출 구조에서는 공통 해설이나 법규 문장이 일부 섞일 수 있다.

따라서 기본 사고상황 추출을 더 엄격하게 만든다.

수정 방향은 다음과 같다.

```text
1. base_context_text는 아래 영역만 허용한다.
   - 도표 제목
   - 기본과실 줄
   - 사고상황 표
   - PM A / 자동차 B 당사자 action 줄

2. 아래 marker 이후 텍스트는 road_context에서 제외한다.
   - 수정요소 A B
   - [도표해설]
   - [관련법규]
   - [참고판례]
   - [심의결정사례]

3. 수정요소성 표현은 remove_adjustment_condition_terms()에서 제거한다.
   - 인근에 자전거도로
   - 대략 10m 이내
   - 좌측통행
   - 보도통행
   - 야간
   - 시야장애
   - 횡단금지
   - 주택·상점가·학교
   - 제동등 고장
```

### 3.4 예상 output

도표02 PM 신호위반 사고의 기대 output:

```json
{
  "rule_id": "pm_auto_2021_도표02",
  "road_area": "교차로",
  "has_signal": true,
  "has_bicycle_road": false,
  "has_bicycle_crossing": false,
  "has_crosswalk": false,
  "has_sidewalk": false,
  "has_centerline": false
}
```

수정요소 조건은 별도 table에 남긴다.

```json
{
  "rule_id": "pm_auto_2021_도표02",
  "near_bicycle_road": true,
  "pm_left_side_travel": true,
  "pm_sidewalk_travel": false,
  "night_or_visibility_issue": true,
  "condition_factor_count": 3
}
```

즉, `road_contexts`는 기본 사고상황, `adjustment_condition_contexts`는 가감 조건으로 분리된다.

---

## 4. 문제 2: 신호기 없음 / 신호 있음 오분류

### 4.1 문제

PM 기준에는 `신호기 없음`이라는 표현이 많다.

하지만 단순히 `"신호"`라는 문자열만 찾으면 아래처럼 잘못 들어갈 수 있다.

```json
{
  "has_signal": true,
  "is_signalized": true,
  "is_unsignalized": true
}
```

`신호기 없음`은 `신호`라는 글자를 포함하지만 의미는 비신호 교차로다.

### 4.2 수정 대상

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/pm_auto/classifiers.py

주요 함수:
- infer_has_signal()
- build_signal_context()
- classify_accident()
```

### 4.3 수정 방식

신호 판단은 부정 표현을 먼저 본다.

```text
1. "신호기 없음", "신호기 없는"이 있으면 has_signal=false
2. 그 다음 "신호위반", "녹색", "적색", "황색" 등이 있으면 has_signal=true
3. is_unsignalized와 is_signalized가 동시에 true가 되지 않도록 조정
```

### 4.4 예상 output

신호기 없는 교차로:

```json
{
  "has_signal": false,
  "is_signalized": false,
  "is_unsignalized": true,
  "signal_priority_basis": null
}
```

신호위반 사고:

```json
{
  "has_signal": true,
  "is_signalized": true,
  "is_unsignalized": false,
  "signal_priority_basis": "도로교통법 제5조"
}
```

---

## 5. 문제 3: PM rule_scenarios 중복 가능성

### 5.1 문제

PM 기준에서 rule_scenarios는 좋아졌지만, 감사 우선순위에 “PM rule_scenarios 중복 제거”가 남아 있다.

가능한 원인은 다음과 같다.

```text
1. 본문에 (가)/(나)/(다)가 여러 영역에 반복 등장
2. 기본과실 설명과 수정요소 해설에 같은 label이 반복됨
3. 동일 scenario label이 여러 번 파싱됨
```

### 5.2 수정 대상

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/pm_auto/extractors.py

주요 함수:
- extract_rule_scenarios()
- extract_scenario_ratio_segments()
```

### 5.3 수정 방식

시나리오 추출은 도표번호가 아니라 본문에서 label과 비율을 직접 읽는 방식으로 이미 변경했다.

여기에 중복 제거를 추가한다.

중복 기준은 다음과 같다.

```text
scenario_key + party_a_ratio + party_b_ratio
```

동일 key와 동일 ratio가 반복되면 첫 번째 raw_text만 사용한다.

동일 key인데 ratio가 다르면 데이터 충돌이므로 중복 제거하지 않고 `needs_manual_review=true`를 표시한다.

### 5.4 예상 output

정상:

```json
{
  "scenario_key": "가",
  "party_a_ratio": 20,
  "party_b_ratio": 80,
  "normalized_ratio": "20:80",
  "needs_manual_review": false
}
```

충돌:

```json
{
  "scenario_key": "가",
  "party_a_ratio": 20,
  "party_b_ratio": 80,
  "normalized_ratio": "20:80",
  "needs_manual_review": true,
  "review_reason": "scenario_ratio_conflict"
}
```

---

## 6. 문제 4: SharedRuleGroup 자동 판단 안정성

### 6.1 현재 상태

과거에는 아래처럼 특정 도표 묶음을 코드에 직접 박았다.

```text
도표01/02
도표03/04
도표06/07
도표08/09
도표33/34
```

이 방식은 하드코딩이라 제거했다.

현재 방향은 인접 도표를 자동 비교하는 방식이다.

```text
1. 인접 도표인지 확인
2. 같은 chart_group인지 확인
3. 한쪽 evidence가 부족하고 다른 쪽 evidence가 충분한지 확인
4. 제목 유사도와 accident_group 일치 여부를 확인
5. 조건을 만족하면 SharedRuleGroup 생성
```

### 6.2 남은 위험

자동 판단은 번호 하드코딩보다 낫지만, 너무 넓게 잡으면 불필요한 공유그룹이 생길 수 있다.

### 6.3 수정 대상

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/pm_auto/builder.py

주요 함수:
- apply_shared_rule_groups()
- should_share_rule_group()
- evidence_score()
- title_similarity()
```

### 6.4 수정 방식

공유 그룹 생성 조건을 더 엄격하게 한다.

```text
1. 두 rule은 반드시 인접 도표여야 한다.
2. chart_group이 같아야 한다.
3. 한쪽은 blocks/law_refs/chunks evidence가 부족해야 한다.
4. 다른 쪽은 충분한 evidence가 있어야 한다.
5. 두 제목의 핵심 토큰 유사도가 기준 이상이어야 한다.
6. 두 rule의 accident_group이 같아야 한다.
```

추가로 output에 판단 근거를 남긴다.

```json
{
  "sharing_strategy": "auto_detected_shared_rule_group",
  "sharing_reason": {
    "same_chart_group": true,
    "left_evidence_score": 1,
    "right_evidence_score": 12,
    "title_similarity": 0.5,
    "same_accident_group": true
  }
}
```

### 6.5 예상 output

```json
{
  "shared_group_id": "pm_auto_2021_shared_01_02",
  "member_chart_refs": ["도표01", "도표02"],
  "source_rule_id": "pm_auto_2021_도표02",
  "sharing_strategy": "auto_detected_shared_rule_group",
  "shared_chunk_count": 12
}
```

---

## 7. 문제 5: diagram/image 산출물 제외

### 7.1 현재 정책

PM 기준도 텍스트 전처리만 한다.

아래 산출물은 만들지 않는다.

```text
diagrams.jsonl
diagram_image_path
diagram_bbox
page image
crop image
```

### 7.2 현재 코드 상태

이미 다음 방향으로 반영되어 있다.

```text
builder.py:
- diagrams table 생성 제거
- package["diagram"] 제거

main.py:
- stale diagrams.jsonl 삭제

extractors.py:
- diagram_explanation -> rule_explanation 변경
```

### 7.3 마지막 확인 계획

코드 수정 후 아래를 확인한다.

```text
1. flatten_packages_to_tables()에 diagrams table이 없는지 확인
2. build_rule_package()에 diagram 생성이 없는지 확인
3. main.py가 stale diagrams.jsonl을 삭제하는지 확인
4. rule_blocks에는 rule_explanation 텍스트 block만 남는지 확인
```

예상 output:

```text
99_tables_for_db/diagrams.jsonl 없음
rule_blocks.jsonl에는 rule_explanation 존재
```

---

## 8. 수정 순서

PM 기준 마지막 수정은 아래 순서로 진행한다.

```text
1. extractors.py
   - extract_base_context_text() 강화
   - extract_rule_scenarios() 중복 제거

2. classifiers.py
   - road_context에서 수정요소성 조건 완전 제거
   - has_signal / is_signalized / is_unsignalized 상호 배타성 보정

3. builder.py
   - SharedRuleGroup 자동 판단 조건 강화
   - sharing_reason metadata 추가
   - parse_quality_report에 road_context contamination flag 강화

4. diagram/image 확인
   - diagrams table 미생성 유지
   - stale diagrams.jsonl 삭제 유지

5. 문법 확인
   - compile()로 문법만 확인
   - 전체 전처리 실행은 4개 기준서 마지막 수정 후 한 번에 수행
```

---

## 9. 최종 기대 결과

수정 후 PM 기준의 기대 상태는 다음과 같다.

```text
PM A/B 방향: 정상 유지
adjustment target_party_key/type 누락: 0건 유지
shared_rule_group_chunks text null: 0건 유지
rule_scenarios 중복 제거
road_context 오염 감소
신호기 없음/신호 있음 오분류 감소
diagrams.jsonl 생성 안 됨
```

Neo4j 적재 관점의 목표는 다음과 같다.

```text
사용자 사고 설명
-> PM/자동차 party 방향 확인
-> accident_group / road_area / signal_context로 후보 rule 검색
-> base_faults 또는 rule_scenarios로 기본과실 선택
-> adjustment_factors와 adjustment_condition_contexts로 수정요소 계산
-> shared_rule_group / rule_explanation / law_refs로 근거 연결
```

---

## 10. 이번 계획에서 하지 않는 것

이번 PM 마지막 보정에서는 아래 작업을 하지 않는다.

```text
1. image crop 구현
2. diagram bbox 추출
3. page image 저장
4. 특정 도표번호 기반 예외 하드코딩 추가
5. 원문에 없는 시나리오 비율 생성
6. 전체 전처리 재실행
```

전체 전처리 재실행은 `nontypical`, `pm_auto`, `roundabout`, `official_2023` 마지막 수정이 모두 끝난 뒤 한 번에 수행하는 것이 좋다.

---

## 11. 실제 코드 단위 수정안

이 섹션은 현재 `pm_auto` 코드 기준으로 어떤 함수를 어떻게 수정할지까지 적은 구현 계획이다.

### 11.1 `extractors.py` 기본 사고상황 텍스트 추출 강화

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/pm_auto/extractors.py

현재 함수:
- extract_base_context_text()
```

현재 흐름은 다음과 같다.

```python
for start, end in [("기본과실", "수정요소 A B"), ("사고상황", "수정요소 A B")]:
    value = extract_between(text, start, end)
    if value:
        base_parts.append(value)
```

문제는 `기본과실`부터 `수정요소 A B` 사이에 PDF 추출상 불필요 문장이 섞이거나, marker가 깨졌을 때 fallback 본문에 해설/법규가 일부 들어올 수 있다는 점이다.

#### 11.1.1 추가할 함수

아래 helper를 추가한다.

```python
def strip_non_base_sections(text: str) -> str:
    """기본 사고상황 추출 전에 수정요소/해설/법규 이후 영역을 제거합니다."""
```

예상 코드:

```python
def strip_non_base_sections(text: str) -> str:
    return re.split(
        r"수정요소\s*A\s*B|\[도표해설\]|\[관련법규\]|\[참고판례\]|\[심의결정사례\]",
        text,
        maxsplit=1,
    )[0]
```

#### 11.1.2 party action 줄만 별도 추출

기본 사고상황에서 중요한 것은 실제 당사자 action이다.

추가할 helper:

```python
def extract_party_action_lines(text: str) -> List[str]:
    """PM A / 자동차 B 같은 당사자 action 줄만 추출합니다."""
```

예상 코드:

```python
def extract_party_action_lines(text: str) -> List[str]:
    return re.findall(r"(?m)^(?:PM|자동차)\s*[AB]\s*:\s*.+$", text)
```

#### 11.1.3 `extract_base_context_text()` 수정 후 흐름

수정 후 흐름:

```python
def extract_base_context_text(text: str) -> str:
    base_scope = strip_non_base_sections(text)
    base_parts = []

    for start, end in [("기본과실", "사고상황"), ("사고상황", None)]:
        value = extract_between(base_scope, start, end)
        if value:
            base_parts.append(value)

    party_lines = extract_party_action_lines(base_scope)
    base_parts.extend(party_lines)

    return normalize_spaces("\n".join(base_parts))
```

기대 효과:

```text
road_context가 [도표해설], [관련법규], 수정요소 표의 자전거도로/보도/횡단보도 조건을 덜 먹음
```

---

### 11.2 `classifiers.py` road_context 오염 방지 강화

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/pm_auto/classifiers.py

현재 함수:
- build_road_context()
- remove_adjustment_condition_terms()
- infer_road_area()
- infer_base_feature()
```

현재 `build_road_context()`는 다음 흐름이다.

```python
base_text = remove_adjustment_condition_terms(f"{title}\n{text}")
title_text = remove_adjustment_condition_terms(title)

return {
    "road_area": infer_road_area(title_text, base_text),
    "has_bicycle_road": infer_base_feature(title_text, base_text, "자전거도로"),
    "has_bicycle_crossing": infer_base_feature(title_text, base_text, "자전거횡단도"),
    "has_crosswalk": infer_base_feature(title_text, base_text, "횡단보도"),
    "has_sidewalk": infer_base_feature(title_text, base_text, "보도"),
}
```

문제는 `remove_adjustment_condition_terms()`로도 공통 해설에서 들어온 일반 단어가 남으면 `has_bicycle_road=true`가 될 수 있다는 점이다.

#### 11.2.1 기본 road feature 판단 함수 변경

현재:

```python
def infer_base_feature(title: str, text: str, keyword: str) -> bool:
    return keyword in title or keyword in text
```

수정 후:

```python
def infer_base_feature(title: str, text: str, keyword: str) -> bool:
    source = f"{title}\n{text}"

    if appears_only_as_adjustment_condition(source, keyword):
        return False

    return keyword in source
```

추가 helper:

```python
def appears_only_as_adjustment_condition(text: str, keyword: str) -> bool:
    """키워드가 수정요소성 문맥에서만 등장하는지 판단합니다."""
```

예상 코드:

```python
def appears_only_as_adjustment_condition(text: str, keyword: str) -> bool:
    if keyword not in text:
        return False

    condition_patterns = [
        rf"인근에\s*{keyword}",
        rf"{keyword}가\s*있는\s*경우",
        rf"{keyword}\s*이용",
        rf"{keyword}\s*통행\s*시",
    ]

    stripped = text
    for pattern in condition_patterns:
        stripped = re.sub(pattern, " ", stripped)

    return keyword not in stripped
```

#### 11.2.2 feature별 더 엄격한 기준

자전거도로/횡단보도/보도는 단어만 있으면 true로 두지 않는다.

예상 기준:

```text
has_bicycle_road:
- title에 "자전거도로"가 있거나
- party action에 "자전거도로 통행", "자전거도로 진입"이 있으면 true
- "인근에 자전거도로"만 있으면 false

has_bicycle_crossing:
- title/action에 "자전거횡단도"가 있으면 true
- 법규/해설 문맥에만 있으면 false

has_crosswalk:
- title/action에 "횡단보도"가 있으면 true
- 공통 해설 문맥에만 있으면 false

has_sidewalk:
- title/action에 "보도 통행", "보도로 통행"이 있으면 true
- 수정요소의 "보도통행"만 있으면 false
```

#### 11.2.3 예상 output 변화

도표02 PM 신호위반 사고:

```json
{
  "road_area": "교차로",
  "has_signal": true,
  "has_bicycle_road": false,
  "has_bicycle_crossing": false,
  "has_crosswalk": false,
  "has_sidewalk": false
}
```

도표35 자동차의 자전거도로 진입 사고:

```json
{
  "road_area": "자전거도로",
  "has_bicycle_road": true,
  "has_bicycle_crossing": false,
  "has_crosswalk": false,
  "has_sidewalk": false
}
```

도표36 PM 보도 통행 사고:

```json
{
  "road_area": "보도",
  "has_sidewalk": true
}
```

---

### 11.3 `classifiers.py` signal_context 상호 배타성 보정

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/pm_auto/classifiers.py

현재 함수:
- build_signal_context()
- infer_has_signal()
```

현재 `build_signal_context()`는 `infer_has_signal()`을 사용하지만, 마지막 수정 때 더 명확히 상호 배타성을 보장한다.

수정 후 코드 흐름:

```python
has_signal = infer_has_signal(title_text, combined)
is_unsignalized = infer_is_unsignalized(title_text, combined)

return {
    "is_signalized": has_signal and not is_unsignalized,
    "is_unsignalized": is_unsignalized,
    ...
}
```

추가 함수:

```python
def infer_is_unsignalized(title: str, text: str) -> bool:
    return "신호기 없음" in title or "신호기 없는" in title or "신호기 없음" in text or "신호기 없는" in text
```

`infer_has_signal()`도 아래처럼 조정한다.

```python
def infer_has_signal(title: str, text: str) -> bool:
    if infer_is_unsignalized(title, text):
        return False
    return any(word in f"{title}\n{text}" for word in ["신호위반", "녹색", "적색", "황색", "신호"])
```

예상 output:

```json
{
  "is_signalized": false,
  "is_unsignalized": true,
  "signal_priority_basis": null
}
```

---

### 11.4 `extractors.py` rule_scenarios 중복 제거

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/pm_auto/extractors.py

현재 함수:
- extract_rule_scenarios()
- extract_scenario_ratio_segments()
- find_ratio_in_segment()
```

현재 `extract_rule_scenarios()`는 `extract_scenario_ratio_segments()` 결과를 그대로 row로 만든다.

수정 후에는 중복 제거 단계를 추가한다.

추가 함수:

```python
def dedupe_scenario_segments(
    segments: List[Tuple[str, str, int, int]]
) -> List[Tuple[str, str, int, int, bool, Optional[str]]]:
    """scenario_key/ratio 기준으로 중복 제거하고 충돌 여부를 표시합니다."""
```

예상 코드 흐름:

```python
segments = extract_scenario_ratio_segments(text)
segments = dedupe_scenario_segments(segments)

for idx, (label, raw_text, a_ratio, b_ratio, needs_review, review_reason) in enumerate(segments, start=1):
    rows.append(
        {
            ...
            "needs_manual_review": needs_review,
            "review_reason": review_reason,
        }
    )
```

중복 기준:

```text
key = (scenario_label, party_a_ratio, party_b_ratio)
```

충돌 기준:

```text
같은 scenario_label인데 ratio가 다르면 scenario_ratio_conflict
```

예상 output:

```json
{
  "scenario_key": "나",
  "party_a_ratio": 30,
  "party_b_ratio": 70,
  "normalized_ratio": "30:70",
  "needs_manual_review": false,
  "review_reason": null
}
```

충돌 시:

```json
{
  "scenario_key": "나",
  "party_a_ratio": 30,
  "party_b_ratio": 70,
  "needs_manual_review": true,
  "review_reason": "scenario_ratio_conflict"
}
```

---

### 11.5 `builder.py` SharedRuleGroup 판단 근거 output 추가

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/pm_auto/builder.py

현재 함수:
- apply_shared_rule_groups()
- should_share_rule_group()
- evidence_score()
- title_similarity()
```

현재 `should_share_rule_group()`는 bool만 반환한다.

수정 후에는 판단 근거를 반환하도록 바꾼다.

#### 11.5.1 함수 반환 구조 변경

현재:

```python
def should_share_rule_group(left, right) -> bool:
    ...
    return same_accident_group and title_score >= 0.35
```

수정 후:

```python
def evaluate_shared_rule_group(left, right) -> Dict[str, Any]:
    return {
        "should_share": bool,
        "same_chart_group": bool,
        "left_evidence_score": int,
        "right_evidence_score": int,
        "title_similarity": float,
        "same_accident_group": bool,
        "reason": str | None,
    }
```

`apply_shared_rule_groups()`에서는 이렇게 사용한다.

```python
evaluation = evaluate_shared_rule_group(left, right)
if not evaluation["should_share"]:
    continue

group["sharing_strategy"] = "auto_detected_shared_rule_group"
group["sharing_reason"] = evaluation
```

#### 11.5.2 예상 shared_rule_groups output

```json
{
  "shared_group_id": "pm_auto_2021_shared_01_02",
  "group_title": "신호위반 사고",
  "member_chart_refs": ["도표01", "도표02"],
  "source_rule_id": "pm_auto_2021_도표02",
  "shared_chunk_count": 12,
  "sharing_strategy": "auto_detected_shared_rule_group",
  "sharing_reason": {
    "same_chart_group": true,
    "left_evidence_score": 1,
    "right_evidence_score": 12,
    "title_similarity": 0.5,
    "same_accident_group": true,
    "reason": "adjacent_rule_uses_shared_evidence"
  }
}
```

이렇게 하면 나중에 공유 그룹이 왜 생성됐는지 검수할 수 있다.

---

### 11.6 `builder.py` parse_quality_report 오염 flag 강화

현재 parse quality에는 아래 정도가 있다.

```python
if road_context.get("has_bicycle_road") and adjustment_condition_context.get("near_bicycle_road"):
    reasons.append("road_context_bicycle_road_check")
```

마지막 수정에서는 flag를 더 명확히 한다.

추가할 검증:

```python
if road_context.get("has_bicycle_crossing") and not title_or_action_contains(section, "자전거횡단도"):
    reasons.append("road_context_bicycle_crossing_contaminated")

if road_context.get("has_crosswalk") and not title_or_action_contains(section, "횡단보도"):
    reasons.append("road_context_crosswalk_contaminated")

if road_context.get("has_sidewalk") and adjustment_condition_context.get("pm_sidewalk_travel"):
    reasons.append("road_context_sidewalk_contaminated")
```

추가 helper:

```python
def title_or_action_contains(section: Dict[str, Any], keyword: str) -> bool:
    title = section.get("rule_title", "")
    text = section.get("structured_text", "")
    action_lines = re.findall(r"(?m)^(?:PM|자동차)\s*[AB]\s*:\s*.+$", text)
    return keyword in title or any(keyword in line for line in action_lines)
```

예상 parse_quality_report:

```json
{
  "parse_status": "review_required",
  "quality_flags": [
    "road_context_crosswalk_contaminated"
  ],
  "needs_manual_review_reason": [
    "road_context_crosswalk_contaminated"
  ]
}
```

---

### 11.7 코드 수정 후 예상 table 변화

수정 후 table별 기대 변화는 다음과 같다.

```text
road_contexts.jsonl:
- PM 신호위반/직진/좌회전/우회전 사고에서 자전거도로/횡단보도/보도 오염 감소
- 실제 자전거도로/보도/횡단보도 사고는 true 유지

signal_contexts.jsonl:
- 신호기 없음이면 is_signalized=false, is_unsignalized=true
- 신호위반 사고면 is_signalized=true, is_unsignalized=false

rule_scenarios.jsonl:
- 동일 scenario_key/ratio 중복 제거
- 같은 key에 ratio 충돌이 있으면 needs_manual_review=true

shared_rule_groups.jsonl:
- sharing_strategy=auto_detected_shared_rule_group
- sharing_reason 객체 추가

parse_quality_report.jsonl:
- road_context contamination flag가 더 구체적으로 기록됨

diagrams.jsonl:
- 생성되지 않음
```

---

## 12. 실제 코드 기준 작업 지시서 보강

이 섹션은 실제 `pm_auto` 폴더 코드를 기준으로, 어떤 파일의 어떤 함수를 어떻게 수정하고 어떤 output을 기대하는지 정리한 최종 작업 지시서다.

중요 원칙:

```text
1. 도표02, 도표13 같은 번호별 예외 처리는 만들지 않는다.
2. 특정 도표 제목을 dict로 박아 넣는 방식은 쓰지 않는다.
3. 제목, 사고상황, party action, 수정요소 block, 공통해설 block을 분리해서 판단한다.
4. diagram/image 관련 table은 생성하지 않는다.
```

### 12.1 `extractors.py` 기본 사고상황 scope 재정의

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/pm_auto/extractors.py

현재 함수:
- extract_base_context_text()
- extract_rule_scenarios()
- extract_adjustment_factors()
```

남은 문제:

```text
기본 road_context에 수정요소나 공통 해설의 표현이 섞인다.
예: 인근 자전거도로, 보도통행, 자전거횡단도, 횡단보도 같은 표현이
실제 사고상황이 아니라 수정요소 조건인데 road_context에 true로 들어간다.
```

수정 계획:

`extract_base_context_text()`가 전체 본문을 느슨하게 자르지 않도록 아래 helper를 추가한다.

```python
def strip_non_base_sections(text: str) -> str:
    ...

def extract_party_action_lines(text: str) -> List[str]:
    ...

def extract_accident_situation_scope(text: str) -> str:
    ...
```

처리 순서:

```text
1. [도표해설], [관련법규], [참고판례], 수정요소 이후 영역을 제거한다.
2. 사고상황 marker가 있으면 그 block을 우선 사용한다.
3. PM A / 자동차 B 같은 party action 줄은 별도로 보존한다.
4. road_context와 signal_context에는 제목 + 사고상황 scope + party action만 넘긴다.
```

예상 내부 흐름:

```python
base_scope = extract_accident_situation_scope(text)
party_actions = extract_party_action_lines(text)
return normalize_spaces("\n".join([base_scope, *party_actions]))
```

예상 output 변화:

```text
도표02 신호위반 사고:
- has_bicycle_road=false
- has_bicycle_crossing=false
- has_crosswalk=false
- has_sidewalk=false

도표35 자동차의 자전거도로 진입 사고:
- has_bicycle_road=true

도표36 PM 보도 통행 사고:
- has_sidewalk=true
```

### 12.2 `classifiers.py` road_context 오염 차단 로직

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/pm_auto/classifiers.py

현재 함수:
- build_road_context()
- remove_adjustment_condition_terms()
- infer_base_feature()
- infer_road_area()
```

현재 문제 지점:

```python
"has_bicycle_road": infer_base_feature(title_text, base_text, "자전거도로")
```

현재 구조는 keyword가 남아 있으면 true가 될 수 있다. 수정요소 표현 제거를 하더라도 PDF 추출 문장 변형 때문에 일부 오염이 남을 수 있다.

수정 계획:

```python
def appears_only_as_adjustment_condition(text: str, keyword: str) -> bool:
    ...

def title_or_party_action_contains(title: str, base_text: str, keyword: str) -> bool:
    ...

def infer_base_feature(title: str, text: str, keyword: str) -> bool:
    if keyword in title:
        return True
    if appears_only_as_adjustment_condition(text, keyword):
        return False
    return title_or_party_action_contains(title, text, keyword)
```

`appears_only_as_adjustment_condition()`이 잡아야 할 일반 패턴:

```text
인근에 {keyword}
{keyword}가 있는 경우
{keyword} 있는 경우
{keyword} 이용 가능
{keyword} 통행 시
{keyword} 부근
대략 10m 이내
```

이 패턴은 특정 도표 번호가 아니라 문장 구조 기준이라 하드코딩이 아니다.

feature별 적용 기준:

```text
has_bicycle_road:
- 제목/party action에 자전거도로 통행, 자전거도로 진입, 자전거도로 주행이 있으면 true
- 인근에 자전거도로가 있는 경우는 false

has_bicycle_crossing:
- 제목/party action에 자전거횡단도 사고가 있으면 true
- 법규/해설에서만 언급되면 false

has_crosswalk:
- 제목/party action에 횡단보도 횡단/사고가 있으면 true
- 보행자보호 관련 해설에서만 언급되면 false

has_sidewalk:
- 제목/party action에 보도 통행 사고가 있으면 true
- 수정요소에서 보도통행만 나오면 false
```

예상 output:

```json
{
  "rule_id": "pm_auto_2021_도표02",
  "road_area": "교차로",
  "has_bicycle_road": false,
  "has_bicycle_crossing": false,
  "has_crosswalk": false,
  "has_sidewalk": false
}
```

### 12.3 `classifiers.py` signal_context 상호 배타 처리

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/pm_auto/classifiers.py

현재 함수:
- build_signal_context()
- infer_has_signal()
```

남은 문제:

```text
제목에 "신호기 없음"이 있는데도 공통 법규/해설의 "신호" 표현 때문에
is_signalized=true가 될 수 있다.
```

수정 계획:

```python
def infer_is_unsignalized(title: str, text: str) -> bool:
    ...

def build_signal_context(title: str, text: str) -> Dict[str, Any]:
    is_unsignalized = infer_is_unsignalized(title, text)
    has_signal = infer_has_signal(title, text) and not is_unsignalized
    ...
```

예상 output:

```json
{
  "is_signalized": false,
  "is_unsignalized": true,
  "signal_priority_basis": null
}
```

신호위반 사고는 반대로 나온다.

```json
{
  "is_signalized": true,
  "is_unsignalized": false,
  "signal_priority_basis": "도로교통법 제5조"
}
```

### 12.4 `extractors.py` RuleScenario 중복 제거와 충돌 flag

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/pm_auto/extractors.py

현재 함수:
- extract_rule_scenarios()
- extract_scenario_ratio_segments()
- find_ratio_in_segment()
```

수정 계획:

```python
def dedupe_scenario_segments(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ...
```

중복 기준:

```text
scenario_label + party_a_ratio + party_b_ratio
```

동일 label인데 ratio가 다르면 삭제하지 않고 검수 flag를 남긴다.

예상 output:

```json
{
  "scenario_label": "(나)",
  "party_a_ratio": 30,
  "party_b_ratio": 70,
  "needs_manual_review": false,
  "scenario_parse_status": "complete"
}
```

충돌 시:

```json
{
  "scenario_label": "(나)",
  "needs_manual_review": true,
  "manual_review_reason": "scenario_ratio_conflict"
}
```

### 12.5 `builder.py` shared_rule_group 판단 근거 기록

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/pm_auto/builder.py

현재 함수:
- apply_shared_rule_groups()
- should_share_rule_group()
- evidence_score()
- title_similarity()
```

현재 문제:

```text
공유 그룹이 생성되더라도 왜 생성됐는지 output만 보고 확인하기 어렵다.
```

수정 계획:

`should_share_rule_group()`를 bool 전용 함수로 두지 않고, 판단 근거 객체를 반환하는 함수로 바꾼다.

```python
def evaluate_shared_rule_group(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    ...
```

반환값:

```json
{
  "should_share": true,
  "same_chart_group": true,
  "left_evidence_score": 1,
  "right_evidence_score": 12,
  "title_similarity": 0.5,
  "same_accident_group": true,
  "reason": "adjacent_rule_uses_shared_evidence"
}
```

`apply_shared_rule_groups()`는 이 결과를 `shared_rule_groups.jsonl`에 함께 저장한다.

```json
{
  "sharing_strategy": "auto_detected_shared_rule_group",
  "sharing_reason": {
    "reason": "adjacent_rule_uses_shared_evidence"
  }
}
```

### 12.6 `builder.py` parse_quality_report 강화

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/pm_auto/builder.py

현재 함수:
- build_parse_quality_report()
```

수정 계획:

road_context와 adjustment_condition_context를 비교해서 오염 가능성을 flag로 남긴다.

```python
if road_context["has_bicycle_road"] and adjustment_condition_context["near_bicycle_road"]:
    flags.append("road_context_bicycle_road_contaminated")

if road_context["has_crosswalk"] and not title_or_action_contains(section, "횡단보도"):
    flags.append("road_context_crosswalk_contaminated")

if road_context["has_sidewalk"] and adjustment_condition_context["pm_sidewalk_travel"]:
    flags.append("road_context_sidewalk_contaminated")
```

예상 output:

```json
{
  "parse_status": "review_required",
  "quality_flags": [
    "road_context_bicycle_road_contaminated"
  ],
  "needs_manual_review_reason": [
    "road_context_bicycle_road_contaminated"
  ]
}
```

### 12.7 `flatten_packages_to_tables()` diagram output 금지

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/pm_auto/builder.py

현재 함수:
- flatten_packages_to_tables()
```

수정 원칙:

```text
tables["diagrams"]를 만들지 않는다.
package 내부에도 diagram/image/bbox 필드를 만들지 않는다.
이 프로젝트의 현재 전처리 목적은 텍스트 기반 Neo4j 적재이므로,
이미지 crop 관련 output은 마지막 수정 범위에서 제외한다.
```

확인 명령:

```powershell
rg "\"diagrams\"|diagram_image|diagram_bbox|build_diagram" etl/fault_cases/src/fault_standard/preprocessing/pm_auto
```

검색 결과가 없어야 한다.

### 12.8 최종 기대 output

```text
road_contexts.jsonl:
- 수정요소 조건으로 인한 자전거도로/횡단보도/보도 오염 감소
- 실제 자전거도로/보도 사고는 true 유지

signal_contexts.jsonl:
- 신호기 없음과 신호기 있음이 동시에 true가 되지 않음

rule_scenarios.jsonl:
- 중복 scenario row 제거
- ratio 충돌은 review flag로 분리

shared_rule_groups.jsonl:
- 공유 그룹 생성 근거가 sharing_reason에 남음

parse_quality_report.jsonl:
- road_context 오염 가능성이 구체적 flag로 남음

diagrams.jsonl:
- 생성하지 않음
```
