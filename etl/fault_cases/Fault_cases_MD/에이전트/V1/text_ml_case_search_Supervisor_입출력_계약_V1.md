# text_ml_case_search Supervisor 입출력 계약 V1

## 목적

이 문서는 `text_ml_case_search` Agent가 Supervisor와 연동될 때 지켜야 하는 입력/출력 JSON 계약을 정리한다.

14단계의 목적은 새 검색 기능을 추가하는 것이 아니라, 이미 구현한 Agent가 어떤 JSON을 받고 어떤 JSON을 반환하는지 고정하는 것이다. Supervisor는 이 계약을 기준으로 다른 Agent 결과와 병합하고 최종 사용자 응답을 만든다.

## 계약 버전

```text
contract_version = text_ml_case_search_v1
node_code = text_ml_case_search
```

계약 버전을 둔 이유:

```text
1. Supervisor가 여러 Agent 결과를 받을 때 어떤 schema 기준인지 확인할 수 있다.
2. 나중에 판례/인정기준 통합 또는 출력 필드 변경이 생겨도 V1 결과와 V2 결과를 구분할 수 있다.
3. 테스트와 운영 결과가 서로 다른 계약으로 해석되는 문제를 줄일 수 있다.
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
| `raw_user_text` | string/null | 사용자가 실제 입력한 원문 |
| `vision_evidence` | array/null | Vision Agent 또는 영상 분석 결과 |
| `ocr_evidence` | object/null | OCR Agent의 교통사고사실확인원 등 문서 분석 결과 |
| `insurer_claim` | object/null | 보험사 과실 주장과 이유 |
| `required_outputs` | array/null | Supervisor가 요구한 출력 범위 |

### 입력 처리 기준

```text
query_text 없음:
  status = failed
  missing_fields = ["query_text"]

vision_evidence 없음:
  실패가 아님
  []로 정규화

ocr_evidence 없음:
  실패가 아님
  null로 유지

insurer_claim 없음:
  실패가 아님
  insurer_claim_review = null

source_ref 입력:
  deprecated alias로 허용
  내부에서는 source_reference로 정규화
  최종 output에는 source_ref를 반환하지 않음
```

## 출력 계약

최상위 출력 구조:

```json
{
  "contract_version": "text_ml_case_search_v1",
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
| `success` | 입력 검증 성공 + RAG evidence 존재 | 유사 근거와 참고 과실비율을 최종 응답 재료로 사용 |
| `partial` | 입력 검증 성공 + RAG evidence 없음 또는 제한적 결과 | 정규화/쟁점/추천자료는 사용하되 유사 근거는 부족하다고 표시 |
| `failed` | 필수 입력 부족 또는 실행 불가 | 사용자에게 추가 입력 요청 |

## structured_result 계약

| 필드 | 타입 | Supervisor 사용 여부 | 설명 |
|---|---|---|---|
| `normalized_description` | string | 사용 | 사고 설명 정규화 결과 |
| `accident_type_candidates` | array | 사용 | 사고 유형 후보 |
| `issue_tags` | array | 사용 | 주요 쟁점 태그 |
| `evidence_tags` | array | 보조 사용 | 추천 증거자료 type 코드 목록 |
| `recommended_evidence` | array | 사용 | 사용자에게 요청할 추가 자료 |
| `insurer_claim_review` | object/null | 조건부 사용 | 보험사 주장 검토 재료 |
| `similar_cases` | array | 사용 | 유사 심의사례 요약 |
| `ratio_range_label` | string | 사용 | 참고 과실비율 라벨 |
| `display_evidence` | array | 사용 | 사용자 표시용으로 정리한 근거 텍스트 |
| `search_text` | object | 디버그/개발용 | 실제 검색 입력 variant 확인 |
| `rag_debug` | object | 디버그/개발용 | retriever, hit count, 검증 report 확인 |
| `reliability_score` | number/null | 현재 미사용 | V1에서는 null |
| `limitations` | array | 사용 | Agent 내부 한계 |

## evidence 계약

`evidence`는 RAG 원천 근거에 가까운 구조다. Supervisor가 사용자에게 바로 보여줄 때는 `display_evidence`를 우선 사용하고, 상세 근거나 추적이 필요할 때 `evidence`를 참조한다.

```json
{
  "source_type": "review_case",
  "title": "case title",
  "source_reference": "review_case_db:case_id#chunk_id",
  "metadata": {
    "case_id": "review_case_000001",
    "review_no": "2019-000001",
    "chunk_id": "review_case_000001_decision",
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

## display_evidence 계약

`display_evidence`는 사용자에게 보여주기 쉽게 정리한 evidence다.

| 필드 | 설명 |
|---|---|
| `source_type` | 근거 출처. V1은 `review_case` 우선 |
| `title` | 사례 제목 |
| `source_reference` | 추적 가능한 근거 참조값 |
| `reference_chart_key` | 인정기준/도표 참조 키 |
| `ratio_label` | 표시용 과실비율 |
| `summary` | 표시용 요약 문장 |
| `matched_snippets` | Elasticsearch highlight에서 추출한 매칭 문구 |
| `display_warnings` | 표시 전 확인해야 할 경고 |

`display_evidence`를 둔 이유:

```text
evidence 원문은 chunk_text, metadata, highlight가 섞여 있어 사용자에게 바로 보여주기 어렵다.
Supervisor는 최종 답변을 만들 때 display_evidence를 우선 사용하고, 필요할 때 evidence 원문을 보조로 참조한다.
```

## insurer_claim_review 계약

`insurer_claim`이 입력되면 `insurer_claim_review`를 반환한다.

```json
{
  "claimed_ratio": "사용자 70 : 상대 30",
  "claim_summary": "...",
  "comparison_summary": "...",
  "key_dispute_points": [],
  "reference_ratio_label": "A 70 : B 30",
  "reference_evidence_count": 5,
  "reference_evidence": [],
  "needed_evidence": [],
  "limitations": []
}
```

보험사 주장은 확정 사실이 아니며, Agent는 이를 반박하거나 확정하지 않는다. Supervisor는 이 내용을 “비교 검토 재료”로만 사용해야 한다.

## recommended_evidence와 evidence_tags 관계

| 필드 | 역할 |
|---|---|
| `evidence_tags` | 내부 분류/필터/후속 로직용 코드 목록 |
| `recommended_evidence` | 사용자 또는 Supervisor에게 보여줄 추가 자료 요청 목록 |

두 필드의 값은 일부 겹칠 수 있다. 겹치는 것이 문제는 아니며, 역할이 다르기 때문에 분리한다.

## Supervisor 사용 우선순위

최종 답변 생성 시 우선순위:

```text
1. status / missing_fields
2. normalized_description
3. issue_tags
4. display_evidence
5. similar_cases
6. ratio_range_label
7. insurer_claim_review
8. recommended_evidence
9. limitations / next_actions
```

디버그용:

```text
search_text
rag_debug
evidence.metadata.score
```

위 디버그용 필드는 운영 로그나 개발 검증에는 유용하지만, 사용자에게 그대로 노출하지 않는다.

## 14단계 결론

V1에서는 `review_case` BM25+Nori 기반 RAG를 우선 사용한다. 판례/인정기준 통합 검색은 V1 계약을 흔들지 않고, 후속 버전에서 `source_type`과 `metadata` 확장으로 붙이는 방향이 안전하다.

따라서 14단계 기준 최종 고정 사항은 다음과 같다.

```text
1. contract_version = text_ml_case_search_v1
2. query_text만 필수 입력으로 둔다.
3. vision/ocr/insurer_claim은 optional 입력으로 둔다.
4. Supervisor 표시용 근거는 display_evidence를 우선 사용한다.
5. 원천 근거 추적은 evidence와 source_reference로 한다.
6. search_text와 rag_debug는 디버그용으로 유지한다.
7. 최종 과실비율 확정은 하지 않고 ratio_range_label은 참고 라벨로만 둔다.
```
