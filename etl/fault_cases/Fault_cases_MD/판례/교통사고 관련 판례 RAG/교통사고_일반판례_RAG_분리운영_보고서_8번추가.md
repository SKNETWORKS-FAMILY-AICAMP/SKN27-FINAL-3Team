# 교통사고 일반 판례 RAG 분리 운영 검토 보고서

## 1. 검토 목적

본 문서는 `traffic_precedent`, 즉 **교통사고 일반 판례 RAG**를 과실비율 Agent 또는 `law_ground_search` 내부에 포함하지 않고, 독립 RAG source로 분리하는 이유와 운영 방향을 정리한다.

검토 대상은 다음 세 영역이다.

```text
1. text_ml_case_search
   - 과실비율 심의사례 및 과실비율 판례 검색 Agent

2. law_ground_search
   - 법령, 조문, 행정 기준 근거 검색 Agent

3. traffic_precedent_search
   - 교통사고 일반 판례 RAG source
```

---

## 2. 결론

`traffic_precedent`는 **과실비율 Agent 내부에 기본 통합하지 않고**, `law_ground_search` 하위 단계로도 넣지 않는다.

최종 구조는 다음과 같이 분리한다.

```text
Supervisor
├─ text_ml_case_search
│   ├─ review_case
│   └─ fault_ratio_precedent
│
├─ law_ground_search
│   └─ 법령 / 조문 / 행정 기준
│
└─ traffic_precedent_search
    └─ 교통사고 일반 판례 RAG
```

즉, `traffic_precedent`는 **Supervisor가 필요할 때 별도로 호출하는 독립 RAG source**로 둔다.

---

## 3. 분리 필요성

## 3.1 과실비율 Agent와의 차이

`text_ml_case_search`는 과실비율 판단에 필요한 근거를 구조화하는 Agent다. 핵심 source는 다음과 같다.

```text
review_case:
  과실비율 심의사례

fault_ratio_precedent:
  과실상계, 피해자 과실, 책임 제한, 손해배상 비율 관련 판례
```

반면 `traffic_precedent`는 일반 교통사고 판례로, 주로 다음 쟁점을 다룬다.

```text
전방주시의무
안전거리 확보의무
신호위반 책임
교차로 통행방법
손해배상 책임 성립
운전자 주의의무
민사/형사 책임 판단
```

따라서 `traffic_precedent`는 과실비율 산정이나 `ratio_range_label` 생성의 1차 근거로 사용하기에는 범위가 넓다.

---

## 3.2 law_ground_search와의 차이

`law_ground_search`는 법령과 조문 중심의 근거 검색 역할을 가진다. #26에서는 고지서·과태료 흐름에서 `law_code`, `violation_text`, `matched_laws`, `law_ground_result`를 중심으로 법률 근거를 연결하는 구조가 정리되어 있다. 또한 최종 자연어 답변은 Supervisor가 생성한다고 명시되어 있다. 

즉 `law_ground_search`의 중심은 다음이다.

```text
도로교통법 조문
시행령/시행규칙
행정 기준
과태료·범칙금 부과 근거
감경/이의신청 가능성 판단 보조
```

반면 `traffic_precedent`는 조문 자체가 아니라 **판례상 주의의무와 책임 판단**을 검색하는 source다.

따라서 `traffic_precedent`를 `law_ground_search` 하위에 넣으면 법령 검색과 판례 검색의 경계가 흐려진다.

---

## 4. 과실비율 Agent와 통합하지 않는 근거

과실비율 Agent의 주요 output은 다음이다.

```text
evidence
similar_cases
ratio_range_label
insurer_claim_review
```

이 중 `ratio_range_label`은 유사 심의사례 또는 과실비율 판례에서 확인되는 비율 표현을 참고 라벨로 정리하는 필드다.

그러나 일반 교통사고 판례는 다음과 같은 이유로 `ratio_range_label`의 1차 근거로 부적합할 수 있다.

```text
1. 과실비율 숫자가 직접 나오지 않을 수 있음
2. 형사책임 또는 일반 주의의무 판단 중심일 수 있음
3. 손해배상 책임 성립 여부와 과실비율 산정은 다른 문제임
4. 보험사 주장 비율과 직접 비교하기 어려운 판례가 섞일 수 있음
```

따라서 과실비율 Agent V2의 active source는 다음으로 제한한다.

```text
V2 active source:
  review_case
  fault_ratio_precedent
```

`traffic_precedent`는 active source에 포함하지 않는다.

---

## 5. 법률 데이터 파이프라인 기준과의 정합성

#20 법률 데이터 파이프라인에서는 도로교통법, 시행령, 시행규칙, 행정 기준 등 법률 데이터를 수집·전처리·DB/RAG에 적재하고, 최신 법률 질문은 MCP 호출 전략으로 분리한다고 정리되어 있다. 또한 반환해야 하는 결과 schema 후보로 `source_ref`, `retrieved_at`, `freshness_policy`, `applicability_limit`, `fallback_reason`이 제시되어 있다. 

특히 #20에는 다음 기준이 포함되어 있다.

```text
판례 데이터는 과실비율 파이프라인과 섞지 않는다.
과실비율 판례/인정기준/심의사례 파이프라인 구현은 제외 범위다.
```

이는 법률 데이터 파이프라인과 과실비율 파이프라인을 분리해야 한다는 의미로 해석된다. 따라서 `traffic_precedent` 역시 법령 데이터 파이프라인 내부로 흡수하기보다, 별도 판례 RAG source로 관리하는 것이 적절하다.

---

## 6. traffic_precedent를 RAG만 구축하는 이유

`traffic_precedent`는 현재 단계에서 특정 Agent의 active source로 확정하기보다, 검색 인프라를 먼저 준비하는 것이 적절하다.

구축 범위는 다음과 같다.

```text
1. 교통사고 일반 판례 Elasticsearch index 구축
2. BM25+Nori retriever 구현
3. evidence mapper 초안 작성
4. display_evidence 포맷 작성
5. 검색 품질 테스트
6. source_reference 규칙 정리
```

다만 기본 실행 flag는 비활성화한다.

```python
ENABLE_TRAFFIC_PRECEDENT_RETRIEVER = False
```

이렇게 하는 이유는 다음과 같다.

```text
1. 과실비율 Agent의 근거 품질을 흐리지 않기 위해
2. law_ground_search의 법령 검색 책임과 섞지 않기 위해
3. Supervisor가 질문 의도에 따라 선택 호출할 수 있도록 하기 위해
4. 검색 품질을 독립적으로 검증하기 위해
5. 향후 법률 책임/주의의무 답변에 활용 가능성을 남기기 위해
```

---

## 7. Supervisor input schema가 필요한 이유

`traffic_precedent_search`를 독립 RAG source로 두면, Supervisor가 이를 호출할 때 전달할 input 계약이 필요하다.

필요한 이유는 다음과 같다.

```text
1. 어떤 사고 쟁점으로 판례를 검색할지 명확히 해야 함
2. 과실비율 질문인지 법적 책임 질문인지 구분해야 함
3. law_ground_search 결과를 보조 입력으로 사용할지 결정해야 함
4. 검색 결과를 Supervisor가 병합 가능한 구조로 받아야 함
5. 향후 다른 Agent에서도 동일한 방식으로 호출할 수 있어야 함
```

입력 schema 초안은 다음과 같다.

```json
{
  "session_id": "ses_0001",
  "message_id": "msg_0001",
  "job_id": "job_0001",
  "node_code": "traffic_precedent_search",
  "query_text": "신호위반 교차로 사고에서 운전자 주의의무가 문제된 판례",
  "accident_context": {
    "normalized_description": "신호위반 교차로 충돌 사고",
    "issue_tags": [
      "신호위반",
      "전방주시의무",
      "교차로 통행방법"
    ]
  },
  "law_ground_result": {
    "law_code": "도로교통법 제5조",
    "article_content": "신호 또는 지시에 따라야 한다."
  },
  "required_outputs": [
    "evidence",
    "display_evidence",
    "applicability_limit",
    "source_reference"
  ]
}
```

`law_ground_result`는 선택 입력이다. 조문 근거가 있으면 판례 검색 보조 정보로 사용할 수 있지만, 필수값은 아니다.

---

## 8. traffic_precedent output 방향

`traffic_precedent_search`의 output은 과실비율 근거가 아니라 법적 책임/주의의무 근거임을 명확히 해야 한다.

```json
{
  "node_code": "traffic_precedent_search",
  "status": "success",
  "structured_result": {
    "display_evidence": [
      {
        "source_type": "traffic_precedent",
        "title": "손해배상(자)",
        "source_reference": "precedent_traffic_db:2022다000000#chunk_03",
        "court_name": "대법원",
        "judgment_date": "2022-01-01",
        "case_number": "2022다000000",
        "summary": "교통사고에서 운전자의 전방주시의무와 손해배상 책임이 문제된 판례입니다.",
        "use_for": [
          "duty_of_care_context",
          "liability_context"
        ],
        "not_primary_for": [
          "ratio_range_label"
        ],
        "applicability_limit": "일반 교통사고 판례이므로 현재 사고의 과실비율로 직접 단정할 수 없습니다."
      }
    ]
  },
  "evidence": []
}
```

핵심은 다음 필드다.

```text
use_for:
  duty_of_care_context
  liability_context

not_primary_for:
  ratio_range_label
```

### 8.1 출력 스키마 정의 시점

현재 `traffic_precedent` 코드의 `bm25_nori_retriever.py`는 다음과 같은 검색 결과 형태를 반환한다.

```text
검색 hit 리스트
source_reference
matched_snippets
chunk_preview
case_id / case_number / court_name / decision_date
```

즉 현재 단계에서는 `traffic_precedent`를 RAG 검색 인프라 수준으로 보는 것이 적절하다.

```text
현재 기준:
  traffic_precedent = RAG 검색 인프라

현재 출력:
  results: list[hit]

현재 불필요한 것:
  AgentOutput 스타일의 structured_result 강제 생성
```

따라서 지금은 출력 스키마를 단순하게 유지하는 것이 좋다.

별도의 wrapper output schema는 다음 조건이 충족될 때 정의한다.

```text
traffic_precedent_search를 Supervisor가 직접 호출한다.
Supervisor가 바로 병합/표시해야 한다.
use_for, not_primary_for, applicability_limit 같은 의미를 명시적으로 전달해야 한다.
```

그때의 구조는 다음과 같이 나눈다.

```text
검색 노드:
  results: list[hit] 형태 반환

wrapper / adapter 레이어:
  results를 display_evidence 구조로 변환
  use_for 부여
  not_primary_for 부여
  applicability_limit 부여
```

이렇게 하면 다음 장점이 있다.

```text
1. 검색 인프라는 단순하게 유지된다.
2. Supervisor 계약은 명확해진다.
3. 검색 책임과 표시/병합 책임이 분리된다.
4. 추후 output schema 변경이 검색기 내부에 영향을 주지 않는다.
```

정리하면 다음과 같다.

```text
현재:
  traffic_precedent는 검색 hit 반환 수준으로 유지한다.

추후:
  Supervisor가 직접 호출하고 병합/표시해야 하는 시점에
  wrapper output schema를 정의한다.

wrapper 역할:
  display_evidence 변환
  use_for 부여
  not_primary_for 부여
  applicability_limit 부여
```

---

## 9. 최종 운영 구조

```text
과실비율 질문:
  Supervisor
  → text_ml_case_search
  → review_case + fault_ratio_precedent

법령/조문 질문:
  Supervisor
  → law_ground_search

교통사고 법적 책임/주의의무 질문:
  Supervisor
  → traffic_precedent_search
  필요 시 law_ground_search 결과와 병합

복합 질문:
  Supervisor가 각 Agent/RAG 결과를 병합
```

---

## 10. 최종 정리

```text
traffic_precedent RAG는 law_ground_search 하위 단계가 아니다.
traffic_precedent RAG는 text_ml_case_search의 기본 source도 아니다.
traffic_precedent RAG는 Supervisor가 필요할 때 호출하는 독립 판례 RAG source다.
```

최종 판단은 다음과 같다.

```text
1. 과실비율 Agent V2는 review_case + fault_ratio_precedent로 구성한다.
2. traffic_precedent는 교통사고 일반 판례 RAG로 별도 구축한다.
3. traffic_precedent는 ratio_range_label의 1차 근거로 사용하지 않는다.
4. traffic_precedent는 법적 책임/주의의무 context 제공용으로 사용한다.
5. law_ground_search와는 병렬 관계이며, 하위 구조가 아니다.
6. Supervisor가 질문 의도에 따라 필요한 결과를 선택적으로 병합한다.
```
