# 2023 공식 인정기준 전처리 마지막 수정계획

## 1. 목적

이 문서는 `etl/fault_cases/src/fault_standard/preprocessing/official_2023` 폴더의 실제 코드를 기준으로, 2023 자동차사고 과실비율 인정기준 전처리를 마지막으로 보정하기 위한 코드 수정 계획이다.

목표는 Neo4j 적재 시 기본과실, 수정요소, 시나리오, 사고유형, 법규/판례 근거를 텍스트 기반으로 안정적으로 사용할 수 있게 만드는 것이다.

중요 원칙:

```text
1. 보22, 차12-1 같은 rule code별 예외 하드코딩은 만들지 않는다.
2. 특정 rule 제목이나 특정 비율을 코드 dict/list에 직접 박지 않는다.
3. 원문 block, 제목, party line, 수정요소 표, 해설 문단에서 명시된 단서로만 추출한다.
4. 확정할 수 없는 값은 억지 fallback하지 않고 status/source/review flag를 남긴다.
5. diagram/image/crop/bbox 관련 output은 만들지 않는다.
```

## 2. 현재 코드 구조

대상 폴더:

```text
etl/fault_cases/src/fault_standard/preprocessing/official_2023
```

주요 파일 역할:

```text
config.py
- 입력 PDF 탐색 키워드, rule 개수, page span 제한, 출력 경로 관리

main.py
- PDF load
- explanatory section 생성
- rule section 분리
- rule package 생성
- table JSONL 저장
- stale diagrams.jsonl 삭제

rule_splitter.py
- 보/차/거 rule section 분리
- child rule 확장
- page boundary 제한
- spillover 제거

extractors.py
- parties, base_fault, variants, adjustment_factors, law_refs, reference_cases, usage_notes, blocks 추출
- 이번 수정의 핵심 대상

classifiers_clean.py
- hierarchy 생성
- accident_group / accident_subgroup / collision_pattern 분류

builder.py
- rule package 생성
- parse_quality_report 생성
- nested package를 DB 적재용 table로 분리

chunker.py
- block 기반 검색 chunk 생성
```

## 3. 남은 핵심 문제

최종 점검 기준으로 남은 핵심 문제는 다음이다.

```text
1. adjustment_factors target_party_key/type 누락이 아직 남아 있음
2. variant 시나리오 일부는 하드코딩성 보정이 남아 있고, 원문 기반 추출로 바꿔야 함
3. accident_group이 본문 전체 keyword에 오염될 수 있음
4. 일부 rule boundary / evidence context 오염을 더 정교하게 flag 처리해야 함
5. movement vocabulary는 더 넓히되 특정 rule code 예외 없이 처리해야 함
6. reference_case / law_ref / usage_note는 sanitize 결과와 parse status가 output에 남아야 함
7. diagram 관련 output은 생성하지 않아야 함
```

---

## 4. 실제 코드 라인 기준 상세 변경 설계

### 4.1 `builder.py` - 현재 package 생성 흐름과 보강 위치

현재 코드:

```python
parties = extract_parties(text, rule_id, rule_prefix)
base_fault = extract_base_fault(text, rule_prefix, rule_code)
variants = extract_variants(text, rule_id)
adjustment_factors = extract_adjustment_factors(text, rule_id, parties)
blocks = split_rule_blocks(text, rule_id)
law_refs = extract_law_refs(text, rule_id)
reference_cases = extract_reference_cases(text, rule_id)
usage_notes = extract_usage_notes(text, rule_id)
accident_classification = classify_accident(rule_prefix, section["rule_title"], text)
```

문제:

```text
1. extract_adjustment_factors()가 party 정보만 받고 rule_prefix/rule_title/base_fault를 못 본다.
2. classify_accident()가 structured_text 전체를 받아 evidence/해설 keyword에 오염될 수 있다.
3. parse_quality가 target 누락 여부는 잡지만, 왜 누락됐는지는 output으로 충분히 남기지 않는다.
```

수정 계획:

`build_rule_package()`에서 먼저 block을 만들고, 핵심 scope를 분리한다.

변경 후 흐름:

```python
blocks = split_rule_blocks(text, rule_id)
base_scope = build_base_classification_scope(section, blocks)

parties = extract_parties(text, rule_id, rule_prefix)
base_fault = extract_base_fault(text, rule_prefix, rule_code)
variants = extract_variants(text, rule_id, rule_code=rule_code, rule_prefix=rule_prefix)
adjustment_factors = extract_adjustment_factors(
    text=text,
    rule_id=rule_id,
    parties=parties,
    rule_prefix=rule_prefix,
    rule_title=section["rule_title"],
    base_fault=base_fault,
)
accident_classification = classify_accident(rule_prefix, section["rule_title"], base_scope)
```

추가 helper:

```python
def build_base_classification_scope(section: Dict[str, Any], blocks: List[Dict[str, Any]]) -> str:
    ...
```

scope 구성:

```text
1. rule_title
2. party_condition block
3. accident_situation block
4. base_fault block
```

제외할 영역:

```text
related_law
reference_case
usage_note
adjustment_explanation
```

예상 output:

```json
{
  "rule_id": "official_2023_차1-1",
  "accident_group": "교차로",
  "classification_scope_source": "title_party_accident_base_blocks"
}
```

### 4.2 `extractors.py` - `extract_adjustment_factors()` target 보강

현재 코드:

```python
def extract_adjustment_factors(text: str, rule_id: str, parties: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    candidate_lines = merge_adjustment_lines(text)
    ...
    parsed = parse_adjustment_line(line)
    target_party_key = infer_adjustment_target_party(parsed["target_party_key"], parsed["factor_name"], parties)
    ...
    "target_party_key": target_party_key,
    "target_party_type": infer_target_party_type(target_party_key, parties),
```

현재 `infer_adjustment_target_party()` 정책:

```text
명확한 단서가 없으면 None으로 둔다.
```

이 정책은 안전하지만, 현재 output에서는 `None`이 많이 남으면 Neo4j 계산이 어렵다.

수정 계획:

`target_party_key`만 반환하지 말고 판단 객체를 반환한다.

추가 함수:

```python
def infer_adjustment_target_info(
    explicit_key: Optional[str],
    factor_name: str,
    parties: List[Dict[str, Any]],
    rule_prefix: str,
    rule_title: str,
    base_fault: Dict[str, Any],
) -> Dict[str, Any]:
    ...
```

반환 구조:

```json
{
  "target_party_key": "보",
  "target_party_type": "pedestrian",
  "target_inference_source": "single_party_base_fault_party",
  "target_inference_confidence": 0.8,
  "target_parse_status": "inferred"
}
```

판단 순서:

```text
1. parsed line 앞에 A/B/차/보가 있으면 explicit_line_prefix, confidence=1.0
2. factor_name에 A/B/보행자/자동차/차량/자전거/이륜차가 명시되면 factor_name_label, confidence=0.9
3. base_fault_type이 single_party_fault이고 base_fault_party가 pedestrian이면 보 또는 pedestrian party로 연결, confidence=0.8
4. parties가 1개이고 factor_name이 그 party label과 직접 연결되면 single_party_context, confidence=0.75
5. 그래도 불명확하면 target_party_key=null, target_parse_status="unresolved"
```

금지:

```python
if rule_code == "보22":
    target_party_key = "보"
```

이런 rule code별 보정은 만들지 않는다.

`extract_adjustment_factors()` 변경 후 row:

```python
target_info = infer_adjustment_target_info(...)

factors.append({
    ...
    "target_party_key": target_info["target_party_key"],
    "target_party_type": target_info["target_party_type"],
    "target_inference_source": target_info["target_inference_source"],
    "target_inference_confidence": target_info["target_inference_confidence"],
    "target_parse_status": target_info["target_parse_status"],
})
```

예상 `adjustment_factors.jsonl` output:

```json
{
  "rule_id": "official_2023_보1",
  "factor_name": "야간·기타 시야장애",
  "delta": 5,
  "target_party_key": "보",
  "target_party_type": "pedestrian",
  "target_parse_status": "inferred",
  "target_inference_source": "single_party_base_fault_party",
  "target_inference_confidence": 0.8
}
```

불명확한 경우:

```json
{
  "target_party_key": null,
  "target_party_type": null,
  "target_parse_status": "unresolved",
  "target_inference_source": null,
  "needs_manual_review": true,
  "manual_review_reason": "adjustment_target_unresolved"
}
```

### 4.3 `extractors.py` - `parse_adjustment_line()` 보강

현재 코드:

```python
target_match = re.match(r"^(A|B|차|보)\s+", cleaned)
```

문제:

```text
표 추출 결과에 "A현저한 과실 +10", "차의 현저한 과실 -10", "보행자 야간 +5"처럼
대상자와 factor_name이 붙어 나오면 target을 놓칠 수 있다.
```

수정 계획:

대상자 prefix pattern을 확장한다.

추가 함수:

```python
def split_adjustment_target_prefix(cleaned: str) -> tuple[Optional[str], str, Optional[str]]:
    ...
```

처리 후보:

```text
A 현저한 과실
A현저한 과실
B 중대한 과실
차의 현저한 과실
차량의 현저한 과실
자동차 현저한 과실
보행자 야간
보행자의 과실
자전거 현저한 과실
이륜차 현저한 과실
```

반환:

```python
target_party_key, factor_name_without_target, target_prefix_source
```

예상 output:

```json
{
  "raw_text": "차의 현저한 과실 -10",
  "target_party_key": "차",
  "factor_name": "현저한 과실",
  "target_inference_source": "line_target_prefix"
}
```

### 4.4 `extractors.py` - `extract_variants()` 하드코딩성 제거

현재 코드:

```python
def extract_width_based_pedestrian_variants(text: str, rule_id: str) -> List[Dict[str, Any]]:
    ...
    title_ratio_pairs = [
        ("가", "소로 횡단", 10),
        ("나", "동일폭 횡단", 20),
        ("다", "대로 횡단", 30),
    ]
```

문제:

```text
10/20/30 비율이 코드에 직접 들어가 있다.
이는 특정 rule 원문을 코드에 박는 방식이라 하드코딩으로 볼 수 있다.
```

수정 계획:

`extract_width_based_pedestrian_variants()`를 제거하거나 내부를 원문 기반 parser로 바꾼다.

추가 함수:

```python
def extract_labeled_single_ratio_variants(text: str, rule_id: str) -> List[Dict[str, Any]]:
    ...
```

원문에서 직접 찾을 pattern:

```text
(가) ... 10%
(나) ... 20%
(다) ... 30%
소로 ... 보행자 기본 과실비율 10%
동일폭 ... 보행자 기본 과실비율 20%
대로 ... 보행자 기본 과실비율 30%
```

중요:

```text
비율 숫자는 코드에서 만들지 않고 원문 match에서만 가져온다.
```

변경 후 `extract_variants()` 흐름:

```python
variants = []
variants.extend(extract_paragraph_variant_ratios(text, rule_id))
variants.extend(extract_inline_variant_ratios(text, rule_id, existing_keys))
variants.extend(extract_labeled_single_ratio_variants(text, rule_id))
return dedupe_variant_rows(variants)
```

예상 `variants.jsonl` output:

```json
{
  "variant_id": "official_2023_보22_가",
  "rule_id": "official_2023_보22",
  "variant_key": "가",
  "variant_title": "소로 횡단",
  "single_party_ratio": 10,
  "ratio_source": "explicit_text",
  "scenario_parse_status": "complete",
  "raw_text": "(가) 소로 ... 보행자 기본 과실비율 10%"
}
```

비율이 없는 `(가)` 표식만 있으면 만들지 않는다.

```json
{
  "scenario_parse_status": "ignored_no_ratio"
}
```

단, 이 ignored row는 `variants.jsonl`에는 넣지 않고 `parse_quality_report` flag로만 남긴다.

### 4.5 `classifiers_clean.py` - `classify_accident()` 오염 방지

현재 코드:

```python
combined = f"{rule_title}\n{text}"
...
"accident_group": infer_accident_group(rule_prefix, title, combined),
"is_signalized": "신호" in combined,
"is_intersection_case": "교차로" in combined or any(word in title for word in ["직진", "좌회전", "우회전"]),
```

문제:

```text
법규/판례/활용시 참고사항에 나온 "횡단보도", "교차로", "신호" 단어가
accident_group을 오염시킬 수 있다.
```

수정 계획:

`classify_accident()`는 전체 `structured_text`가 아니라 `base_scope`만 받는다.

추가 helper:

```python
def build_classification_text(rule_title: str, base_scope: str) -> str:
    ...
```

분류 기준:

```text
1. rule_prefix == "보"인 경우만 횡단보도 그룹 가능
2. rule_prefix != "보"이면 횡단보도 단어가 evidence에 있어도 accident_group="횡단보도" 금지
3. 자동차 대 자동차는 제목/사고상황의 직진/좌회전/우회전/신호/교차로 단서로 교차로 판단
4. 주차/정차/개문/진로변경/추돌은 title 우선
```

예상 `rules.jsonl` output:

```json
{
  "rule_id": "official_2023_차1-1",
  "rule_prefix": "차",
  "accident_group": "교차로",
  "accident_subgroup": "신호위반",
  "classification_scope_source": "title_party_accident_base_blocks"
}
```

`parse_quality_report`에 추가할 flag:

```json
{
  "quality_flags": [
    "classification_scope_sanitized"
  ]
}
```

### 4.6 `rule_splitter.py` - boundary 보정 근거 output

현재 코드:

```python
block_text = limit_block_page_span(block_text, page_start, MAX_REASONABLE_RULE_PAGE_SPAN)
raw_text = truncate_spillover_text(remove_page_markers(strip_layout_noise_lines(block_text)), header["rule_prefix"])
```

문제:

```text
boundary 보정은 수행되지만,
어떤 이유로 잘렸는지 section output에 충분히 남지 않는다.
```

수정 계획:

문자열만 반환하던 함수를 info 객체 반환 방식으로 추가한다.

추가 함수:

```python
def limit_block_page_span_info(block_text: str, page_start: int, max_span: int) -> Dict[str, Any]:
    ...

def truncate_spillover_text_info(raw_text: str, rule_prefix: str) -> Dict[str, Any]:
    ...
```

`finalize_rule_section()` 변경:

```python
span_info = limit_block_page_span_info(block_text, page_start, MAX_REASONABLE_RULE_PAGE_SPAN)
spillover_info = truncate_spillover_text_info(cleaned_block, header["rule_prefix"])

return {
    ...
    "boundary_quality": {
        "page_span_limited": span_info["limited"],
        "original_page_end": span_info["original_page_end"],
        "limited_page_end": span_info["limited_page_end"],
        "spillover_truncated": spillover_info["truncated"],
        "spillover_marker": spillover_info["marker"],
    }
}
```

예상 `sections.jsonl` output:

```json
{
  "rule_code": "보36",
  "page_start": 121,
  "page_end": 126,
  "boundary_quality": {
    "page_span_limited": true,
    "original_page_end": 148,
    "limited_page_end": 126,
    "spillover_truncated": true
  }
}
```

`builder.py`의 parse quality는 이 값을 읽어서 flag를 만든다.

```python
if section.get("boundary_quality", {}).get("page_span_limited"):
    reasons.append("rule_boundary_page_span_limited")
```

### 4.7 `extractors.py` - law/reference/usage sanitize status output

현재 코드:

```python
law_block = sanitize_evidence_block(extract_between(text, "관련 법규", "참고 판례") or "")
block = sanitize_evidence_block(extract_between(text, "참고 판례", None) or "")
block = sanitize_evidence_block(extract_between(text, "활용시 참고 사항", "관련 법규") or "")
```

문제:

```text
sanitize_evidence_block()이 skip/break를 수행해도 output에 skip_count, break_marker가 남지 않는다.
```

수정 계획:

기존 `sanitize_evidence_block()`은 wrapper로 유지하고, info 함수 추가.

```python
def sanitize_evidence_block_info(text: str) -> Dict[str, Any]:
    ...
```

반환:

```json
{
  "text": "정리된 block",
  "skip_count": 3,
  "break_applied": false,
  "break_marker": null,
  "sanitization_actions": ["skip_layout_header", "skip_toc"]
}
```

`extract_law_refs()` row 추가:

```json
{
  "context_sanitized": true,
  "context_skip_count": 3,
  "context_break_applied": false
}
```

`extract_reference_cases()` row 추가:

```json
{
  "context_sanitized": true,
  "context_skip_count": 2,
  "context_break_applied": false
}
```

`usage_notes.jsonl`도 동일하게 `context_sanitized` 필드를 가진다.

### 4.8 `extractors.py` - movement vocabulary 보강

현재 코드 위치:

```text
파일:
extractors.py

현재 함수:
- infer_movement()
```

현재 문제:

```text
우측 끼어들기
정차 후 후진
정차 후 출발
선행 주차진행
교차로 내 회전
역통행
문열림/개문
```

같은 행동이 movement null로 남을 수 있다.

수정 계획:

특정 rule code가 아니라 action keyword 기반 vocabulary를 확장한다.

추가 구조:

```python
MOVEMENT_PATTERNS = [
    ("끼어들기", "cut_in"),
    ("정차 후 후진", "reverse_after_stop"),
    ("정차 후 출발", "start_after_stop"),
    ("주차진행", "parking_maneuver"),
    ("교차로 내 회전", "turning_inside_intersection"),
    ("역통행", "wrong_way"),
    ("개문", "door_opening"),
    ("문열림", "door_opening"),
]
```

`infer_movement()` 변경:

```python
for keyword, movement in MOVEMENT_PATTERNS:
    if keyword in text:
        return movement
```

예상 `parties.jsonl` output:

```json
{
  "action_summary": "정차 후 후진",
  "movement": "reverse_after_stop",
  "movement_source": "keyword_pattern"
}
```

### 4.9 `builder.py` - parse_quality_report 세분화

현재 코드:

```python
if any(not row.get("target_party_key") for row in adjustments):
    reasons.append("adjustment_target_party_missing")
...
if any(not row.get("movement") for row in parties):
    reasons.append("movement_missing")
```

문제:

```text
누락 여부는 알 수 있지만 어떤 row가 어떤 이유로 누락됐는지 알기 어렵다.
```

수정 계획:

row count와 unresolved id 목록을 output에 추가한다.

추가 helper:

```python
def summarize_adjustment_quality(adjustments: List[Dict[str, Any]]) -> Dict[str, Any]:
    ...

def summarize_party_quality(parties: List[Dict[str, Any]]) -> Dict[str, Any]:
    ...
```

`build_parse_quality()` output 추가:

```json
{
  "adjustment_target_missing_count": 12,
  "adjustment_target_missing_ids": [
    "adj_official_2023_차1-1_003"
  ],
  "adjustment_target_unresolved_count": 12,
  "movement_missing_count": 0,
  "movement_missing_party_ids": []
}
```

flag도 구체화:

```text
adjustment_target_unresolved
adjustment_target_low_confidence
movement_missing
variant_ratio_missing
variant_false_positive
classification_scope_sanitized
evidence_context_sanitized
rule_boundary_page_span_limited
```

### 4.10 `builder.py` - `flatten_packages_to_tables()` output 유지/확장

현재 tables:

```python
tables = {
    "rulebooks": [],
    "sections": sections,
    "rules": [],
    "parties": [],
    "base_faults": [],
    "variants": [],
    "adjustment_factors": [],
    "rule_blocks": [],
    "law_refs": [],
    "reference_cases": [],
    "usage_notes": [],
    "chunks": [],
    "parse_quality_report": [],
}
```

유지할 table:

```text
rules.jsonl
parties.jsonl
base_faults.jsonl
variants.jsonl
adjustment_factors.jsonl
rule_blocks.jsonl
law_refs.jsonl
reference_cases.jsonl
usage_notes.jsonl
chunks.jsonl
parse_quality_report.jsonl
sections.jsonl
rulebooks.jsonl
```

만들지 않을 table:

```text
diagrams.jsonl
diagram_images
image_bboxes
```

확인 기준:

```powershell
rg "\"diagrams\"|diagram_image|diagram_bbox|build_diagram|crop" etl/fault_cases/src/fault_standard/preprocessing/official_2023
```

있다면 텍스트 전처리 범위에서는 제거 대상이다.

### 4.11 `main.py` - stale diagram 삭제 유지

현재 코드:

```python
stale_diagram_table = paths["table_dir"] / "diagrams.jsonl"
if stale_diagram_table.exists():
    stale_diagram_table.unlink()
```

수정 계획:

이 코드는 유지한다.

추가로 package/table 생성 경로에서 `diagrams` key를 만들지 않는지 확인한다.

예상:

```text
99_tables_for_db/diagrams.jsonl 없음
```

---

## 5. 최종 기대 output

### 5.1 `adjustment_factors.jsonl`

```json
{
  "adjustment_id": "adj_official_2023_보1_001",
  "rule_id": "official_2023_보1",
  "target_party_key": "보",
  "target_party_type": "pedestrian",
  "factor_name": "야간·기타 시야장애",
  "delta": 5,
  "target_parse_status": "inferred",
  "target_inference_source": "single_party_base_fault_party",
  "target_inference_confidence": 0.8
}
```

### 5.2 `variants.jsonl`

```json
{
  "variant_id": "official_2023_보22_가",
  "rule_id": "official_2023_보22",
  "variant_key": "가",
  "variant_title": "소로 횡단",
  "single_party_ratio": 10,
  "ratio_source": "explicit_text",
  "scenario_parse_status": "complete"
}
```

### 5.3 `rules.jsonl`

```json
{
  "rule_id": "official_2023_차1-1",
  "rule_prefix": "차",
  "rule_title": "녹색직진 대 적색직진",
  "accident_group": "교차로",
  "accident_subgroup": "신호위반",
  "classification_scope_source": "title_party_accident_base_blocks"
}
```

### 5.4 `parse_quality_report.jsonl`

```json
{
  "rule_id": "official_2023_차1-1",
  "parse_status": "review_required",
  "adjustment_target_missing_count": 2,
  "adjustment_target_missing_ids": ["adj_official_2023_차1-1_003"],
  "movement_missing_count": 0,
  "quality_flags": [
    "adjustment_target_unresolved",
    "classification_scope_sanitized"
  ]
}
```

### 5.5 `law_refs.jsonl` / `reference_cases.jsonl`

```json
{
  "rule_id": "official_2023_차1-1",
  "context_sanitized": true,
  "context_skip_count": 2,
  "context_break_applied": false
}
```

---

## 6. 최종 검증 기준

```text
1. rules 201개 유지
2. base_faults 201개 유지
3. pair ratio sum 오류 0건 유지
4. adjustment_factors target_party_key/type 누락 감소
5. target이 여전히 불명확한 row는 unresolved status와 review reason 보유
6. variant는 원문 비율이 있는 경우만 생성
7. 보22 등 특정 rule code별 비율 하드코딩 제거
8. rule_prefix != 보 인 rule이 evidence keyword 때문에 횡단보도 그룹으로 분류되지 않음
9. law/reference/usage context sanitize status가 output에 남음
10. movement_missing 감소
11. diagrams.jsonl 생성 안 됨
```
