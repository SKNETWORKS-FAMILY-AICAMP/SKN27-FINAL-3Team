# text_ml_case_search Supervisor 입출력 계약 V2

## 목적

이 문서는 `text_ml_case_search` Agent V2가 Supervisor에게 반환하는 JSON 계약을 고정한다.

V2의 목적은 기존 V1의 `review_case` 심의사례 중심 RAG 결과에 `fault_ratio_precedent` 과실비율 판례 근거를 추가해서, Supervisor가 최종 답변을 만들 때 **심의사례 근거와 판례 근거를 함께 사용할 수 있게 하는 것**이다.

```text
사용자/슈퍼바이저 입력
→ text_ml_case_search Agent
→ review_case + fault_ratio_precedent RAG 검색
→ evidence / similar_cases / ratio_range_label / display_evidence 정리
→ Supervisor가 바로 받을 수 있는 output schema 반환
```

## 계약 버전

```text
contract_version = text_ml_case_search_v2
node_code = text_ml_case_search
```

V2 계약을 별도로 둔 이유:

```text
1. V1은 review_case 중심의 단일 source RAG였다.
2. V2는 review_case + fault_ratio_precedent 다중 source RAG다.
3. Supervisor는 source_type별로 최종 답변에 반영할 근거 성격을 다르게 해석해야 한다.
4. V1/V2를 같은 계약으로 보면, 심의사례와 판례가 섞인 근거를 구분하기 어렵다.
```

## V2 active source 범위

| 구분 | source_type | V2 상태 | 설명 |
|---|---|---|---|
| 심의사례 | `review_case` | active | 과실비율 심의사례 근거 |
| 과실비율 판례 | `fault_ratio_precedent` | active | 과실상계, 책임제한, 법원 판단 근거 |
| 교통사고 일반 판례 | `traffic_precedent` | standby | 추후 확장 대상 |
| 인정기준 | `standard` | excluded | 현재 입력/검색/출력 계획 미확정으로 제외 |

V2에서 `standard`를 제외한 이유:

```text
인정기준은 아직 Agent 입력 schema와 검색 입력 방식이 확정되지 않았다.
따라서 V2에서는 이미 적재/색인/실행 검증이 끝난 review_case와 fault_ratio_precedent만 active로 둔다.
```

## 입력 계약

### 필수 입력

| 필드 | 타입 | 설명 |
|---|---|---|
| `query_text` | string | 검색과 사고 정규화의 핵심 입력. 없으면 `failed` 반환 |

### 권장 입력

| 필드 | 타입 | 설명 |
|---|---|---|
| `session_id` | string/null | 대화 단위 추적값 |
| `message_id` | string/null | 사용자 메시지 추적값 |
| `job_id` | string/null | 실행 작업 추적값 |
| `node_code` | string/null | 호출 대상 Agent 코드 |
| `raw_user_text` | string/null | 사용자 원문 |
| `vision_evidence` | array/null | 영상/이미지 분석 결과 |
| `ocr_evidence` | object/null | 교통사고사실확인원 등 OCR 결과 |
| `insurer_claim` | object/null | 보험사 과실비율 주장 및 이유 |
| `required_outputs` | array/null | Supervisor가 요구하는 출력 범위 |

### 입력 처리 기준

```text
query_text 없음:
  status = failed
  missing_fields = ["query_text"]

vision_evidence 없음:
  실패 아님
  [] 또는 null로 처리

ocr_evidence 없음:
  실패 아님
  null로 처리

insurer_claim 없음:
  실패 아님
  insurer_claim_review = null
```

## 최상위 출력 구조

```json
{
  "contract_version": "text_ml_case_search_v2",
  "node_code": "text_ml_case_search",
  "status": "success",
  "structured_result": {},
  "evidence": [],
  "next_actions": [],
  "limitations": [],
  "missing_fields": []
}
```

## status 의미

| status | 의미 | Supervisor 처리 |
|---|---|---|
| `success` | 입력 검증 성공 + RAG evidence 존재 | 근거 기반 답변 생성에 사용 |
| `partial` | 입력 검증 성공 + RAG evidence 없음/부족 | 정규화/쟁점/추천자료는 사용하되 근거 부족 안내 |
| `failed` | 필수 입력 부족 또는 실행 불가 | 사용자에게 추가 입력 요청 |

## structured_result 계약

| 필드 | 타입 | Supervisor 사용 여부 | 설명 |
|---|---|---|---|
| `normalized_description` | string | 사용 | 사고 설명 정규화 결과 |
| `accident_type_candidates` | array | 사용 | 사고 유형 후보 |
| `issue_tags` | array | 사용 | 주요 쟁점 태그 |
| `evidence_tags` | array | 보조 사용 | 추천 증거자료 type 코드 목록 |
| `recommended_evidence` | array | 사용 | 사용자에게 요청할 추가 자료 |
| `insurer_claim_review` | object/null | 조건부 사용 | 보험사 주장 비교 자료 |
| `similar_cases` | array | 사용 | 유사 심의사례/판례 요약 |
| `ratio_range_label` | string | 사용 | 참고 과실비율 라벨 |
| `display_evidence` | array | 우선 사용 | 사용자 표시용 근거 요약 |
| `search_text` | object | 개발/디버그 | 실제 검색 입력 variant |
| `rag_debug` | object | 개발/디버그 | retriever, hit count, validation report |
| `source_summary` | object | 사용 | source별 근거 개수와 병합 전략 |
| `reliability_score` | number/null | 현재 미사용 | V2에서는 null |
| `limitations` | array | 사용 | Agent 내부 한계 |

## source_summary 계약

`source_summary`는 V2에서 새로 중요해진 필드다.

```json
{
  "active_sources": ["review_case", "fault_ratio_precedent"],
  "standby_sources": ["traffic_precedent"],
  "excluded_sources": ["standard"],
  "source_counts": {
    "review_case": 5,
    "fault_ratio_precedent": 5
  },
  "input_counts": {
    "review_case": 5,
    "fault_ratio_precedent": 5
  },
  "final_top_k": 10,
  "merge_strategy": "source_quota"
}
```

Supervisor 사용 기준:

```text
source_counts.review_case > 0:
  심의사례 근거가 존재한다고 판단

source_counts.fault_ratio_precedent > 0:
  판례 근거가 존재한다고 판단

excluded_sources에 standard 포함:
  인정기준은 이번 Agent 결과에 포함되지 않았음을 명시 가능

standby_sources에 traffic_precedent 포함:
  교통사고 일반 판례는 추후 확장 예정 source로만 취급
```

## evidence 계약

`evidence`는 RAG 원천 근거에 가까운 구조다. Supervisor는 사용자 표시에는 `display_evidence`를 우선 사용하고, 출처 추적이나 상세 근거 확인이 필요할 때 `evidence`를 참조한다.

### review_case evidence 예시

```json
{
  "source_type": "review_case",
  "title": "심의사례 제목",
  "source_reference": "review_case_db:review_case_2019_000001#review_case_2019_000001_decision",
  "metadata": {
    "case_id": "review_case_2019_000001",
    "review_no": "2019-000001",
    "chunk_id": "review_case_2019_000001_decision",
    "chunk_type": "decision",
    "reference_chart_key": "249",
    "decision_fault_ratio": "A 70 : B 30",
    "score": 123.4,
    "score_type": "bm25_score",
    "rank": 1
  },
  "chunk_text": "...",
  "search_text": "...",
  "confidence": null
}
```

### fault_ratio_precedent evidence 예시

```json
{
  "source_type": "fault_ratio_precedent",
  "title": "손해배상 판례명",
  "source_reference": "fault_ratio_precedent_db:81877#81877:structured_1500_250:0007",
  "metadata": {
    "case_id": "81877",
    "case_number": "2002다8767",
    "case_name": "손해배상",
    "court_name": "대법원",
    "decision_date": "2002-09-06",
    "chunk_id": "81877:structured_1500_250:0007",
    "chunk_type": "main_text",
    "score": 1532.48,
    "score_type": "bm25_score",
    "rank": 5,
    "precedent_context": {
      "source_role": "fault_ratio_precedent",
      "source_label": "fault_ratio_precedent",
      "chunk_type": "main_text"
    }
  },
  "chunk_text": "...",
  "search_text": "...",
  "confidence": null
}
```

## display_evidence 계약

`display_evidence`는 사용자에게 보여주기 쉬운 근거 요약이다.

| 필드 | 설명 |
|---|---|
| `source_type` | `review_case` 또는 `fault_ratio_precedent` |
| `title` | 심의사례/판례 제목 |
| `source_reference` | 추적 가능한 근거 참조값 |
| `reference_chart_key` | 심의사례 인정기준 참조 키. 판례에서는 없을 수 있음 |
| `case_number` | 판례 사건번호. 심의사례에서는 없을 수 있음 |
| `court_name` | 판례 법원명. 심의사례에서는 없을 수 있음 |
| `decision_date` | 판례 선고일. 심의사례에서는 없을 수 있음 |
| `ratio_label` | 표시 가능한 과실비율/판례 근거 라벨 |
| `summary` | 사용자 표시용 근거 요약 |
| `matched_snippets` | Elasticsearch highlight 기반 매칭 문구 |
| `display_warnings` | 표시 전 확인할 경고 |

Supervisor 표시 기준:

```text
1. display_evidence를 우선 사용한다.
2. source_type=review_case는 "유사 심의사례" 근거로 설명한다.
3. source_type=fault_ratio_precedent는 "관련 판례" 또는 "법원 판단 근거"로 설명한다.
4. source_reference는 사용자에게 직접 노출하기보다 내부 추적값으로 보관한다.
5. case_number/court_name/decision_date가 있으면 판례 근거 표시 문구에 포함할 수 있다.
```

## similar_cases 계약

`similar_cases`는 Supervisor가 최종 답변에서 “유사 사례/판례 요약” 영역을 만들 때 사용할 수 있다.

V2에서는 `source_type`이 섞일 수 있다.

```text
review_case:
  심의사례 기반 유사 사례

fault_ratio_precedent:
  판례 기반 유사 법원 판단
```

주의:

```text
similar_cases는 evidence보다 요약된 구조다.
정확한 출처와 원문 확인이 필요하면 evidence 또는 display_evidence를 함께 참조한다.
```

## ratio_range_label 계약

`ratio_range_label`은 최종 확정 과실비율이 아니다.

```text
역할:
  검색된 근거에서 추출 가능한 참고 과실비율 라벨

Supervisor 사용:
  "참고로 유사 근거에서는 ..." 수준으로 사용

금지:
  단독으로 최종 과실비율 확정처럼 표현하지 않기
```

## insurer_claim_review 계약

`insurer_claim`이 입력되면 `insurer_claim_review`가 생성될 수 있다.

Supervisor 사용 기준:

```text
1. 보험사 주장은 확정 사실이 아니라 비교 대상 주장으로 취급한다.
2. reference_ratio_label과 reference_evidence를 근거로 보험사 주장과 차이가 있는 지점을 설명한다.
3. 추가 확인자료가 필요하면 needed_evidence를 사용자에게 안내한다.
```

## V2 병합 전략

```text
merge_strategy = source_quota
review_case quota = 5
fault_ratio_precedent quota = 5
final_top_k = 10
```

5+5로 둔 이유:

```text
1. 심의사례와 판례가 모두 최종 output에 보이도록 하기 위해서다.
2. BM25 score는 source별 index와 문서 구조가 달라 직접 비교 기준으로 쓰기 어렵다.
3. 한쪽 source가 점수를 독점해 다른 source가 사라지는 문제를 막는다.
4. top 10은 Supervisor가 요약하기에는 감당 가능한 크기다.
```

## V2 active 10 실행 근거

2026-07-05 active 10개 실행 결과:

```text
active_input_count = 10
status_counts = {"success": 10}
total_evidence_count = 100
total_review_case_evidence_count = 50
total_fault_ratio_precedent_evidence_count = 50
total_similar_case_count = 50
total_display_evidence_count = 100
zero_evidence_count = 0
```

해석:

```text
10개 입력 모두에서 review_case 5개 + fault_ratio_precedent 5개가 반환됐다.
따라서 구조 기준으로 V2 multi-source RAG는 Supervisor 계약에 반영 가능한 상태다.
```

## Supervisor 사용 우선순위

최종 답변 생성 시 추천 우선순위:

```text
1. status / missing_fields 확인
2. normalized_description으로 사고 정리
3. issue_tags로 쟁점 정리
4. source_summary로 근거 source 구성 확인
5. display_evidence를 사용자 표시 근거로 사용
6. similar_cases로 유사 사례/판례 요약
7. ratio_range_label은 참고 비율로만 사용
8. insurer_claim_review로 보험사 주장 비교
9. recommended_evidence로 추가 자료 안내
10. limitations / next_actions로 한계와 다음 행동 안내
```

## Supervisor 출력 문구 가이드

V2에서는 같은 evidence 목록 안에 심의사례와 판례가 섞일 수 있으므로, Supervisor는 source를 구분해서 표현한다.

예:

```text
유사 심의사례에서는 ...
관련 판례에서는 ...
```

피해야 할 표현:

```text
이 판례와 심의사례가 곧바로 귀하의 최종 과실비율을 확정합니다.
```

권장 표현:

```text
아래 근거들은 유사한 사고 유형에서 참고할 수 있는 심의사례 및 판례입니다.
실제 과실비율은 신호, 진입 시점, 충돌 위치, 영상자료 등에 따라 달라질 수 있습니다.
```

## V2 한계

```text
1. standard 인정기준은 아직 포함하지 않는다.
2. traffic_precedent는 standby 상태다.
3. BM25 score는 source 간 직접 비교 점수로 쓰지 않는다.
4. ratio_range_label은 참고 라벨이며 확정 판단이 아니다.
5. 일부 원천 데이터 인코딩이나 색인 품질은 별도 점검이 필요할 수 있다.
```

## 14단계 결론

V2 계약은 다음을 Supervisor에게 보장한다.

```text
1. text_ml_case_search_v2는 review_case와 fault_ratio_precedent를 함께 반환할 수 있다.
2. source_summary로 source별 근거 개수를 확인할 수 있다.
3. display_evidence로 사용자 표시용 근거를 받을 수 있다.
4. evidence로 원천 근거와 metadata를 추적할 수 있다.
5. standard는 아직 제외되며, traffic_precedent는 추후 확장 대상이다.
```

