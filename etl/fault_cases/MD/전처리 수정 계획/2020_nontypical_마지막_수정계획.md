# 2020 비정형 기준 마지막 전처리 수정 계획

## 1. 현재 상태 판단

2020 비정형 기준은 전체 전처리 결과 중 가장 안정적인 편이다.

현재 감사 결과상 큰 구조는 대부분 정상이다.

```text
summary mismatch: 0건
adjustment target_party_key/type 누락: 0건
movement 누락: 큰 문제 없음
road_context: 대부분 정상
기본과실/수정요소 계산: 가능에 가까움
```

다만 Neo4j 최종 적재 전에 마무리해야 할 잔여 문제가 있다.

```text
1. 심의사례 과실비율 일부 누락
2. 일부 intersection_type 세분화 부족
3. diagram/image 산출물 제외 상태 유지
4. 하드코딩 제거 이후 summary title 자동 정렬 안정성 유지
```

이번 수정은 대수술이 아니라 마지막 보정이다.

목표는 추출량을 늘리는 것이 아니라, Neo4j에서 잘못 매칭되거나 잘못 계산될 여지를 줄이는 것이다.

---

## 2. 수정 원칙

이번 수정에서 지킬 원칙은 다음과 같다.

```text
1. 특정 No를 코드에 직접 박지 않는다.
2. 원문에 없는 값을 임의로 만들지 않는다.
3. PDF에서 추출 가능한 구조는 정규식/구조 파서로 읽는다.
4. 문서별 메타데이터는 config.py에 모으고, 처리 로직에는 직접 쓰지 않는다.
5. image/diagram 관련 JSON은 만들지 않는다.
6. [도표해설]은 이미지가 아니라 텍스트 해설로만 취급한다.
```

특히 `No.9`, `No.14`, `No.15` 같은 번호별 보정은 이미 제거했다.

요약표 제목은 상세 rule 제목과 자동 정렬하는 방식으로 바꿨기 때문에, 앞으로도 번호별 예외를 다시 만들지 않는다.

---

## 3. 문제 1: 심의사례 과실비율 일부 누락

### 3.1 문제

심의결정사례에서 청구/피청구 과실비율이 일부 누락된다.

예상되는 누락 유형은 다음과 같다.

```text
청구차량 60%, 피청구차량 40%
청구 차량 60%, 피청구 차량 40%
청구차량 과실 60%, 피청구차량 과실 40%
청구차량 과실 30%는 적정
```

이미 `과실` 단어가 없는 패턴도 일부 지원하지만, 실제 output 기준으로 아직 2건 정도가 남아 있다.

원인은 다음 중 하나일 가능성이 높다.

```text
1. 청구/피청구 라벨 사이에 공백 또는 조사 변형이 있음
2. 차량/자동차/이륜차 표현이 섞임
3. 쉼표, 괄호, 문장부호 때문에 기존 정규식이 끊김
4. 한쪽 비율만 명시된 사례를 완전 누락처럼 표시함
```

### 3.2 수정 대상

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/nontypical/extractors.py

수정 대상 함수:
- extract_claim_respondent_ratios()
- find_labeled_ratio()
```

### 3.3 수정 방식

청구/피청구 라벨 기반 파서를 더 넓게 만든다.

수정할 정규식 원칙은 다음과 같다.

```text
청구 계열:
- 청구차량
- 청구 차량
- 청구자동차
- 청구 자동차
- 청구이륜차
- 청구 이륜차
- 원고차량
- 원고 차량

피청구 계열:
- 피청구차량
- 피청구 차량
- 피청구자동차
- 피청구 자동차
- 피청구이륜차
- 피청구 이륜차
- 피고차량
- 피고 차량
- 상대차량
- 상대 차량
```

그리고 다음 형태를 모두 허용한다.

```text
라벨 + 숫자 + %
라벨 + 과실 + 숫자 + %
라벨 + 의 과실 + 숫자 + %
라벨 + 에게 + 숫자 + %
```

단, `피청구차량` 안의 `청구차량`이 청구 라벨로 오탐되지 않도록 negative lookbehind 또는 라벨 우선순위 처리를 유지한다.

### 3.4 한쪽만 명시된 사례 처리

한쪽만 명시된 경우 반대쪽 비율을 임의 생성하지 않는다.

예를 들어 원문이 아래와 같다면:

```text
청구차량 과실 30%는 적정
```

예상 output은 다음과 같다.

```json
{
  "claim_vehicle_fault_ratio": 30,
  "respondent_vehicle_fault_ratio": null,
  "needs_manual_review": true
}
```

`respondent_vehicle_fault_ratio = 70`을 자동 생성하지 않는다.

이유는 원문에 없는 값을 Neo4j 근거 그래프에 넣으면, 나중에 “근거에는 없는데 그래프에는 있는 값”이 생기기 때문이다.

### 3.5 양쪽이 모두 명시된 사례 output

원문이 아래와 같다면:

```text
청구차량 60%, 피청구차량 40%
```

예상 output은 다음과 같다.

```json
{
  "claim_vehicle_fault_ratio": 60,
  "respondent_vehicle_fault_ratio": 40,
  "needs_manual_review": false
}
```

---

## 4. 문제 2: intersection_type 세분화 부족

### 4.1 문제

`road_area`는 대부분 정상으로 들어가지만, `intersection_type`이 너무 단순하다.

현재는 교차로 관련 사고가 대체로 다음처럼 들어갈 수 있다.

```json
{
  "road_area": "교차로",
  "intersection_type": "교차로"
}
```

하지만 Neo4j 매칭에서는 교차로 세부 유형이 중요하다.

예를 들어 아래 사고들은 모두 교차로지만 의미가 다르다.

```text
신호없는 사거리 교차로
적색점멸/황색점멸 교차로
동일폭 교차로
대로/소로 교차로
우측 도로/좌측 도로 관계
```

### 4.2 수정 대상

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/nontypical/classifiers.py

수정 대상 함수:
- build_road_context()

추가 예정 함수:
- infer_intersection_type()
```

### 4.3 수정 방식

`build_road_context()`에서 `intersection_type`을 직접 `"교차로"`로 넣지 않고, `infer_intersection_type(title, text)`를 호출하도록 바꾼다.

추론 규칙은 제목과 기본 사고상황 텍스트를 우선한다.

예상 규칙은 다음과 같다.

```text
신호없는 사거리 / 신호기가 없는 사거리
-> unsignalized_four_way

적색점멸 / 황색점멸
-> flashing_signal_intersection

동일폭
-> same_width_intersection

대로 + 소로
-> main_side_road_intersection

우측 도로 / 좌측 도로 / 우측도로 / 좌측도로
-> side_road_priority_intersection

교차로만 있음
-> generic_intersection

교차로 정보 없음
-> null
```

### 4.4 예상 output

점멸신호 교차로 사고:

```json
{
  "road_area": "교차로",
  "intersection_type": "flashing_signal_intersection",
  "traffic_control": "flash_signal"
}
```

신호없는 사거리 사고:

```json
{
  "road_area": "교차로",
  "intersection_type": "unsignalized_four_way",
  "traffic_control": "unsignalized"
}
```

대로/소로 교차로 사고:

```json
{
  "road_area": "교차로",
  "intersection_type": "main_side_road_intersection",
  "road_width_relation": "main_vs_side_road"
}
```

---

## 5. 문제 3: diagram/image 산출물 제외

### 5.1 현재 정책

사용 범위는 텍스트 기반 전처리다.

따라서 아래 산출물은 만들지 않는다.

```text
diagrams.jsonl
diagram_image_path
diagram_bbox
page image
crop image
```

### 5.2 현재 코드 상태

이미 다음 방향으로 반영되어 있다.

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/nontypical/extractors.py

상태:
- diagram_explanation -> rule_explanation 으로 변경
- [도표해설]은 이미지가 아니라 텍스트 해설로 처리
```

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/nontypical/main.py

상태:
- stale diagrams.jsonl이 남아 있으면 삭제
```

### 5.3 추가 확인 계획

코드 수정 시 아래를 다시 확인한다.

```text
1. flatten_packages_to_tables()에 diagrams table이 없는지 확인
2. package["diagram"] 생성이 없는지 확인
3. diagrams.jsonl이 재생성되지 않는지 확인
4. rule_blocks.jsonl에는 rule_explanation만 남는지 확인
```

예상 output:

```text
99_tables_for_db/diagrams.jsonl 없음
rule_blocks.jsonl에는 rule_explanation block 존재
```

---

## 6. 문제 4: summary title 자동 정렬 안정성

### 6.1 현재 상태

기존에는 특정 No를 직접 보정했다.

예전 방식:

```text
No.9 -> canonical title
No.14 -> canonical title
No.15 -> canonical title
No.10 -> 특정 표현 치환
```

이 방식은 하드코딩이므로 제거했다.

현재 방식은 다음과 같다.

```text
1. summary table을 파싱한다.
2. 상세 rule 본문에서 No별 title을 다시 파싱한다.
3. summary_no 기준으로 두 title을 비교한다.
4. summary title이 비었거나 깨졌거나 상세 title과 의미상 다르면 detail title로 자동 정렬한다.
```

### 6.2 유지할 metadata

자동 정렬이 발생하면 아래 정보를 남긴다.

```json
{
  "summary_title": "최종 사용 제목",
  "summary_title_original": "요약표에서 읽힌 원래 제목",
  "summary_title_source": "detail_rule_title"
}
```

요약표 제목을 그대로 써도 되는 경우:

```json
{
  "summary_title_source": "summary_table"
}
```

### 6.3 수정 계획

현재 구조는 유지한다.

다만 마지막 코드 수정 때 다음을 확인한다.

```text
1. 번호별 canonical title이 다시 생기지 않았는지 확인
2. summary_title_original이 보존되는지 확인
3. summary_row_raw_text에 A:B 비율이 유지되는지 확인
4. summary mismatch 0건 상태가 유지되는지 확인
```

---

## 7. 수정 순서

이번 nontypical 마지막 보정은 아래 순서로 진행한다.

```text
1. extractors.py
   - review_case ratio parser 보강
   - 한쪽만 명시된 사례 needs_manual_review 처리

2. classifiers.py
   - infer_intersection_type() 추가
   - build_road_context()에서 intersection_type 세분화

3. diagram/image 확인
   - diagrams table 생성 없음 확인
   - stale diagrams.jsonl 삭제 유지

4. summary_parser.py 확인
   - 번호별 하드코딩 없음 확인
   - detail title 자동 정렬 metadata 유지

5. 문법 확인
   - compile()로 문법만 확인
   - 전처리 전체 실행은 마지막 통합 재생성 때 수행
```

---

## 8. 최종 기대 결과

수정 후 2020 비정형 기준의 기대 상태는 다음과 같다.

```text
summary mismatch: 0건 유지
adjustment target_party_key/type 누락: 0건 유지
review_case ratio missing: 최소화
road_area: 정상 유지
intersection_type: 세분화
diagrams.jsonl: 생성 안 됨
rule_explanation: 텍스트 근거 block으로 유지
Neo4j 기본과실/수정요소 계산용 사용 가능
```

Neo4j 적재 관점의 목표는 다음과 같다.

```text
사용자 사고 설명
-> accident_group / road_area / intersection_type / movement 기준으로 후보 rule 검색
-> base_faults에서 기본과실 조회
-> adjustment_factors에서 A/B target 기준 수정요소 계산
-> review_cases/law_refs/rule_explanation으로 근거 연결
```

---

## 9. 이번 계획에서 하지 않는 것

이번 nontypical 마지막 보정에서는 아래 작업을 하지 않는다.

```text
1. image crop 구현
2. diagram bbox 추출
3. page image 저장
4. 새로운 No별 예외 하드코딩 추가
5. 원문에 없는 과실비율 자동 생성
6. 전체 전처리 재실행
```

전체 전처리 재실행은 네 기준서 4종의 마지막 코드 수정이 모두 끝난 뒤 한 번에 수행하는 것이 좋다.

---

## 10. 실제 코드 단위 수정안

이 섹션은 현재 코드 기준으로 어떤 함수를 어떻게 바꿀지까지 적은 구현 계획이다.

### 10.1 `extractors.py` 심의사례 비율 파서 보강

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/nontypical/extractors.py

현재 함수:
- extract_review_cases()
- extract_claim_respondent_ratios()
- find_labeled_ratio()
```

현재 흐름은 다음과 같다.

```python
raw = normalize_spaces(match.group(0))
claim_ratio, respondent_ratio = extract_claim_respondent_ratios(raw)
```

그리고 `extract_claim_respondent_ratios()` 내부에서 청구/피청구 라벨별 정규식을 각각 돌린다.

마지막 수정에서는 이 구조는 유지하되, 라벨 추출 방식을 더 일반화한다.

#### 10.1.1 추가할 함수

아래 helper를 추가한다.

```python
def normalize_party_ratio_text(text: str) -> str:
    """심의사례 과실비율 파싱 전에 공백/조사/문장부호를 정리합니다."""
```

역할:

```text
1. 전각 쉼표, 중복 공백 정리
2. "청구 차량" -> "청구차량"처럼 라벨 사이 공백 정리
3. "피청구 차량" -> "피청구차량" 정리
4. "원고 차량", "피고 차량", "상대 차량"도 동일하게 정리
```

예상 코드 형태:

```python
def normalize_party_ratio_text(text: str) -> str:
    text = normalize_spaces(text)
    text = text.replace("，", ",")
    text = re.sub(r"(청구|피청구|원고|피고|상대)\s+(차량|자동차|이륜차|차)", r"\1\2", text)
    text = re.sub(r"\s+", " ", text)
    return text
```

#### 10.1.2 `extract_claim_respondent_ratios()` 수정

현재:

```python
claim_ratio = find_labeled_ratio(text, claim_patterns)
respondent_ratio = find_labeled_ratio(text, respondent_patterns)
```

수정 후:

```python
normalized = normalize_party_ratio_text(text)
claim_ratio = find_labeled_ratio(normalized, build_claim_ratio_patterns())
respondent_ratio = find_labeled_ratio(normalized, build_respondent_ratio_patterns())
```

추가할 pattern builder:

```python
def build_claim_ratio_patterns() -> List[str]:
    return [
        r"(?<!피)청구(?:차량|자동차|이륜차|차)?\s*(?:의\s*)?(?:과실)?\s*(\d{1,3})\s*%",
        r"원고(?:차량|자동차|이륜차|차)?\s*(?:의\s*)?(?:과실)?\s*(\d{1,3})\s*%",
    ]


def build_respondent_ratio_patterns() -> List[str]:
    return [
        r"피청구(?:차량|자동차|이륜차|차)?\s*(?:의\s*)?(?:과실)?\s*(\d{1,3})\s*%",
        r"피고(?:차량|자동차|이륜차|차)?\s*(?:의\s*)?(?:과실)?\s*(\d{1,3})\s*%",
        r"상대(?:차량|자동차|이륜차|차)?\s*(?:의\s*)?(?:과실)?\s*(\d{1,3})\s*%",
    ]
```

중요한 점:

```text
피청구차량 안의 청구차량 오탐 방지:
- claim 쪽에는 (?<!피)청구 사용
```

#### 10.1.3 `extract_review_cases()` output 보강

현재 review case row에는 `needs_manual_review`가 항상 `False`에 가깝다.

수정 후에는 한쪽만 명시된 경우만 검토 대상으로 표시한다.

예상 코드:

```python
needs_ratio_review = (claim_ratio is None) != (respondent_ratio is None)

review_cases.append(
    {
        ...
        "claim_vehicle_fault_ratio": claim_ratio,
        "respondent_vehicle_fault_ratio": respondent_ratio,
        "needs_manual_review": needs_ratio_review,
        "manual_review_reason": "partial_fault_ratio" if needs_ratio_review else None,
    }
)
```

예상 결과:

```json
{
  "claim_vehicle_fault_ratio": 30,
  "respondent_vehicle_fault_ratio": null,
  "needs_manual_review": true,
  "manual_review_reason": "partial_fault_ratio"
}
```

양쪽이 모두 있으면:

```json
{
  "claim_vehicle_fault_ratio": 60,
  "respondent_vehicle_fault_ratio": 40,
  "needs_manual_review": false,
  "manual_review_reason": null
}
```

---

### 10.2 `classifiers.py` intersection_type 세분화

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/nontypical/classifiers.py

현재 함수:
- build_road_context()
```

현재 `build_road_context()` 안에는 다음 코드가 있다.

```python
"intersection_type": "교차로" if "교차로" in combined else None,
```

이 값은 너무 단순하다.

수정 후에는 아래처럼 바꾼다.

```python
"intersection_type": infer_intersection_type(title, combined),
```

#### 10.2.1 추가할 함수

```python
def infer_intersection_type(title: str, text: str) -> Optional[str]:
    """교차로 세부 유형을 제목과 기본 사고상황에서 추론합니다."""
```

예상 코드:

```python
def infer_intersection_type(title: str, text: str) -> Optional[str]:
    source = f"{title}\n{text}"

    if "적색점멸" in source or "황색점멸" in source:
        return "flashing_signal_intersection"

    if "신호없는 사거리" in source or "신호기가 없는 사거리" in source:
        return "unsignalized_four_way"

    if "동일폭" in source or "동일 폭" in source:
        return "same_width_intersection"

    if "대로" in source and "소로" in source:
        return "main_side_road_intersection"

    if any(word in source for word in ["우측 도로", "좌측 도로", "우측도로", "좌측도로"]):
        return "side_road_priority_intersection"

    if "교차로" in source:
        return "generic_intersection"

    return None
```

#### 10.2.2 road_width_relation도 함께 보정

현재:

```python
"road_width_relation": "same_width" if "동일폭" in combined or "동일 폭" in combined else None,
```

수정 후 별도 함수로 분리한다.

```python
"road_width_relation": infer_road_width_relation(combined),
```

추가 함수:

```python
def infer_road_width_relation(text: str) -> Optional[str]:
    if "동일폭" in text or "동일 폭" in text:
        return "same_width"
    if "대로" in text and "소로" in text:
        return "main_vs_side_road"
    return None
```

예상 output:

```json
{
  "road_area": "교차로",
  "intersection_type": "main_side_road_intersection",
  "road_width_relation": "main_vs_side_road"
}
```

---

### 10.3 `summary_parser.py` 자동 정렬 유지 확인

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/nontypical/summary_parser.py

현재 함수:
- parse_summary_table()
- align_summary_titles_with_detail_rules()
- extract_detail_titles_by_no()
- should_use_detail_title()
```

현재 구조는 유지한다.

확인할 코드 흐름:

```python
return align_summary_titles_with_detail_rules(rows, pages)
```

이 구조는 summary table만 믿지 않고 상세 rule title과 자동 정렬한다.

수정하지 않고 유지할 값:

```python
row["summary_title_original"] = original_title
row["summary_title_source"] = "detail_rule_title"
```

검증 기준:

```text
1. canonical_titles 같은 dict가 다시 생기지 않을 것
2. if no == ... 같은 번호별 보정이 없을 것
3. summary_title_original이 보존될 것
4. summary_row_raw_text에 A:B 비율이 남을 것
```

---

### 10.4 `main.py` diagram stale file 삭제 유지

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/nontypical/main.py
```

현재 유지할 코드:

```python
stale_diagram_table = paths["table_dir"] / "diagrams.jsonl"
if stale_diagram_table.exists():
    stale_diagram_table.unlink()
```

추가 수정은 하지 않는다.

다만 마지막 확인 때 아래를 검색한다.

```powershell
rg "\"diagrams\"|package\\[\"diagram\"|build_diagram" etl/fault_cases/src/fault_standard/preprocessing/nontypical
```

검색 결과가 없어야 한다.

---

### 10.5 코드 수정 후 예상 table 변화

수정 후 table별 기대 변화는 다음과 같다.

```text
review_cases.jsonl:
- claim_vehicle_fault_ratio / respondent_vehicle_fault_ratio 누락 감소
- 한쪽만 명시된 사례는 needs_manual_review=true
- manual_review_reason=partial_fault_ratio 추가

road_contexts.jsonl:
- intersection_type이 "교차로" 단일값에서 세부 code로 변경
- road_width_relation이 main_vs_side_road까지 표현 가능

summary_table_rows.jsonl:
- summary_title_source 유지
- summary_title_original 유지
- summary mismatch 0건 유지

diagrams.jsonl:
- 생성되지 않음
```

---

## 11. 실제 코드 기준 작업 지시서 보강

이 섹션은 실제 `nontypical` 폴더 코드를 기준으로, 어떤 파일의 어떤 함수를 어떻게 수정하고 어떤 output을 기대하는지 정리한 최종 작업 지시서다.

중요 원칙:

```text
1. No.8, No.9 같은 번호별 예외 보정은 만들지 않는다.
2. 특정 제목 문자열을 dict로 박아 넣는 canonical title 방식은 쓰지 않는다.
3. PDF 본문 구조, marker, A/B 비율, 청구/피청구 표현, 제목 유사도처럼 재사용 가능한 규칙으로 처리한다.
4. diagram/image 관련 table은 생성하지 않는다.
```

### 11.1 `extractors.py` 심의결정사례 비율 parser 최종 보강

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/nontypical/extractors.py

현재 함수:
- extract_review_cases()
- extract_claim_respondent_ratios()
- find_labeled_ratio()
```

남은 문제:

```text
청구차량 60%, 피청구차량 40%
```

처럼 `과실`이라는 단어 없이 바로 비율이 나오는 문장이 일부 누락된다.

수정 계획:

```python
def normalize_party_ratio_text(text: str) -> str:
    ...
```

를 추가해 줄바꿈, 전각기호, 쉼표 주변 공백을 먼저 정리한다.

그 다음 `find_labeled_ratio()` 내부에서 아래 표현을 모두 같은 계열로 본다.

```text
청구차량
청구 차량
원고 차량
청구 이륜차

피청구차량
피청구 차량
피고 차량
피청구 이륜차
피청구이륜차
```

처리 방식:

```python
claim = find_labeled_ratio(normalized, CLAIM_LABEL_PATTERNS)
respondent = find_labeled_ratio(normalized, RESPONDENT_LABEL_PATTERNS)
```

여기서 `CLAIM_LABEL_PATTERNS`, `RESPONDENT_LABEL_PATTERNS`는 코드 내부 상수가 아니라 함수가 사용하는 정규식 label 묶음이다. 특정 case 번호를 기준으로 보정하지 않는다.

예상 output:

```json
{
  "claim_vehicle_fault_ratio": 60,
  "respondent_vehicle_fault_ratio": 40,
  "ratio_parse_status": "complete"
}
```

한쪽만 원문에 있는 경우:

```json
{
  "claim_vehicle_fault_ratio": 30,
  "respondent_vehicle_fault_ratio": null,
  "ratio_parse_status": "partial",
  "needs_manual_review": true,
  "manual_review_reason": "partial_review_case_fault_ratio"
}
```

### 11.2 `classifiers.py` road_context / accident_group 보정

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/nontypical/classifiers.py

현재 함수:
- classify_accident()
- build_road_context()
```

남은 문제:

```text
동일차로 사고가 교차로로 잡히거나,
버스정류장 사고가 주차장 계열로 잡히거나,
점멸신호 교차로 사고의 accident_group이 횡단보도 쪽으로 남는 문제
```

수정 계획:

`classify_accident()`와 `build_road_context()`가 같은 판단 기준을 공유하도록 아래 helper를 추가한다.

```python
def infer_base_road_area(title: str, text: str) -> str:
    ...

def infer_intersection_type(title: str, text: str) -> Optional[str]:
    ...

def infer_lane_relation(title: str, text: str) -> Optional[str]:
    ...
```

판단 순서:

```text
1. 제목을 최우선으로 본다.
2. 제목에 없으면 사고상황 block을 본다.
3. 수정요소, 해설, 심의사례 문장은 road_context의 근거로 쓰지 않는다.
4. 여러 후보가 있으면 사고유형을 직접 설명하는 표현을 우선한다.
```

예상 output:

```json
{
  "accident_group": "교차로/점멸신호",
  "road_context": {
    "road_area": "교차로",
    "intersection_type": "flashing_signal_intersection"
  }
}
```

동일차로 사고는 아래처럼 나온다.

```json
{
  "accident_group": "동일방향/동일차로",
  "road_context": {
    "road_area": "차도",
    "lane_relation": "same_lane"
  }
}
```

### 11.3 `summary_parser.py` summary title 정렬 방식 유지

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/nontypical/summary_parser.py

현재 함수:
- parse_summary_table()
- align_summary_titles_with_detail_rules()
- extract_detail_titles_by_no()
- should_use_detail_title()
```

수정 방향:

```text
현재 방식 유지.
번호별 title dict를 추가하지 않는다.
```

유지 이유:

```text
summary table은 PDF 줄바꿈 때문에 다음 row 제목이 섞일 수 있다.
상세 rule 본문은 rule 단위로 잘려 있으므로 title source로 더 안정적이다.
따라서 summary row는 원문 보존용으로 두고, 검색/적재용 title은 상세 rule title과 자동 정렬한다.
```

필수 보존 필드:

```json
{
  "summary_title": "상세 rule 기준으로 정렬된 제목",
  "summary_title_original": "summary table에서 읽은 원문 제목",
  "summary_title_source": "detail_rule_title",
  "summary_row_raw_text": "원본 row 텍스트"
}
```

### 11.4 `builder.py` table output 기준

현재 코드 위치:

```text
파일:
etl/fault_cases/src/fault_standard/preprocessing/nontypical/builder.py

현재 함수:
- build_rule_package()
- flatten_packages_to_tables()
```

수정 계획:

```text
1. review_cases에는 ratio_parse_status를 포함한다.
2. road_contexts에는 road_area, intersection_type, lane_relation을 분리한다.
3. parse_quality_report에는 review_case_ratio_partial, road_context_suspicious 같은 flag를 남긴다.
4. diagrams table은 만들지 않는다.
```

예상 table 변화:

```text
review_cases.jsonl:
- claim/respondent 비율 누락 감소
- partial인 경우 status와 reason 명시

road_contexts.jsonl:
- 횡단보도/교차로/동일차로/버스정류장/주차장 오분류 감소

parse_quality_report.jsonl:
- valid만 남발하지 않고 실제 검수 사유를 기록

diagrams.jsonl:
- 생성하지 않음
```
