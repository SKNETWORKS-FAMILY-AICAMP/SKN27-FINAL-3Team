# PM 발표 핵심: 왜 text_ml_case_search Agent를 사용하는가

## 1. 기존 단순 검색의 한계

단순 판례 검색은 사용자가 입력한 문자열과 비슷한 문서 chunk를 많이 가져오는 방식이다.

```text
사용자 입력
-> 문자열 기반 검색
-> 관련 있을 수도 있고 없을 수도 있는 판례/사례 후보 반환
```

이 방식은 검색 결과가 나오더라도 다음 문제가 남는다.

```text
1. 이 사고 상황에 정말 맞는 근거인지 사람이 다시 판단해야 한다.
2. 심의사례와 판례가 섞였을 때 어떤 근거가 어떤 출처인지 구분하기 어렵다.
3. 보험사 주장, OCR, 영상 분석 결과 같은 실제 사용자 맥락을 검색에 충분히 반영하기 어렵다.
4. Supervisor가 최종 답변에 바로 쓰기 좋은 JSON 구조로 정리되어 있지 않다.
```

## 2. 이 Agent를 사용한 이유

`text_ml_case_search` Agent는 단순히 판례를 많이 가져오기 위한 기능이 아니다.

목적은 다음과 같다.

```text
사용자의 사고 상황에 맞는 심의사례와 과실비율 판례를 찾아서
Supervisor가 바로 답변에 사용할 수 있는 근거 구조로 정리하는 것
```

즉 이 Agent는 검색 결과를 그대로 던지는 것이 아니라, 아래 작업을 함께 수행한다.

```text
1. 사용자 사고 설명을 정규화한다.
2. 사고 쟁점을 태그로 뽑는다.
3. 검색에 적합한 schema_search_text를 만든다.
4. 심의사례와 과실비율 판례를 각각 검색한다.
5. 출처별 근거를 5개씩 균형 있게 병합한다.
6. 사용자에게 보여줄 display_evidence로 정리한다.
7. Supervisor가 사용할 output schema로 반환한다.
```

## 3. 왜 BM25+Nori를 사용했는가

과실비율 판단에서는 정확한 법률/사고 키워드가 매우 중요하다.

예를 들면 다음 표현들이 검색 품질을 크게 좌우한다.

```text
차로변경
진로변경 주의의무
후방추돌
신호위반
횡단보도 보행자 보호의무
과실상계
손해배상 책임제한
```

그래서 V2에서는 BM25+Nori를 기본 검색 방식으로 사용했다.

```text
BM25
-> 검색어와 문서의 키워드 매칭 강도를 계산하는 검색 방식

Nori
-> 한국어 형태소 분석기
-> 차로변경, 보행자, 과실상계 같은 한국어 표현을 검색 가능한 단위로 나눔
```

이 방식을 선택한 이유는 다음과 같다.

```text
1. 사고 유형과 법률 쟁점은 키워드 일치가 중요하다.
2. 한국어 법률 문장은 형태소 분석이 없으면 검색 품질이 떨어질 수 있다.
3. 이전 A/B 실험에서 BM25+Nori가 운영 baseline으로 쓰기에 충분한 결과를 보였다.
4. vector/hybrid/reranker는 실험에는 유용하지만, V2 운영 경로는 단순하고 재현 가능한 BM25+Nori가 더 적합했다.
```

## 4. 왜 심의사례와 판례를 둘 다 검색하는가

V2의 active source는 2개다.

```text
review_case
-> 과실비율 심의사례
-> 보험 실무와 유사 사고 판단에 가까움

fault_ratio_precedent
-> 과실비율 관련 판례
-> 법원의 과실상계, 손해배상, 책임제한 판단 근거에 가까움
```

두 source를 같이 쓰는 이유는 다음과 같다.

```text
심의사례만 보면 보험 실무 근거는 강하지만 법적 판단 근거가 약할 수 있다.
판례만 보면 법적 근거는 강하지만 실제 보험 과실비율 유사사례와 거리가 있을 수 있다.
따라서 두 근거를 같이 보여줘야 사용자와 Supervisor가 균형 있게 판단할 수 있다.
```

## 5. 왜 5+5 source quota로 병합했는가

V2는 최종 evidence를 아래처럼 구성한다.

```text
review_case 5개
fault_ratio_precedent 5개
총 10개 evidence
```

이렇게 한 이유는 Elasticsearch index별 BM25 점수를 직접 비교하기 어렵기 때문이다.

```text
review_case score와 fault_ratio_precedent score는 같은 검색 방식이라도 index와 문서 구조가 다르다.
점수만으로 섞으면 한쪽 source가 전부 차지할 수 있다.
그러면 심의사례 또는 판례 중 하나가 최종 답변에서 사라질 수 있다.
```

그래서 source별 quota를 둔다.

```text
심의사례 근거도 반드시 보여준다.
판례 근거도 반드시 보여준다.
Supervisor는 두 근거를 구분해서 최종 답변에 사용할 수 있다.
```

## 6. 최종적으로 Agent가 해주는 일

한 줄로 정리하면 다음과 같다.

```text
text_ml_case_search Agent는 사용자의 사고 설명을 기반으로
심의사례와 과실비율 판례를 각각 검색하고,
그 결과를 Supervisor가 바로 사용할 수 있는 근거 JSON으로 정리하는 Agent다.
```

발표용 핵심 문장은 다음처럼 말하면 된다.

```text
기존 검색은 문자열이 맞는 문서를 가져오는 수준이었다면,
우리 Agent는 사용자의 사고 상황을 정리하고,
그 사고에 맞는 심의사례와 과실비율 판례를 출처별로 균형 있게 가져온 뒤,
Supervisor가 답변에 바로 쓸 수 있는 근거 구조로 변환합니다.
```

---
# text_ml_case_search V2 Supervisor 연동 보강 요약

## 0. Supervisor 연동 핵심 요약

이 문서는 PM 발표와 Supervisor 담당자 연동을 동시에 고려한 문서다.

핵심은 다음 한 줄이다.

```text
Supervisor는 agent_input을 만들고,
text_ml_case_search Agent의 run_text_ml_case_search(...)를 호출한 뒤,
반환된 result JSON에서 display_evidence / similar_cases / ratio_range_label / insurer_claim_review를 가져가면 된다.
```

V2 기준 실제 active 검색 source는 다음 2개다.

```text
1. review_case
   - 과실비율 심의사례

2. fault_ratio_precedent
   - 과실비율 관련 판례
```

현재 V2에서는 `traffic_precedent`와 `standard`는 아직 최종 active 검색 대상이 아니다.

```text
traffic_precedent = standby
standard = excluded
```

따라서 Supervisor 담당자가 지금 연결해야 하는 것은 다음 범위다.

```text
사용자 사고 설명
→ text_ml_case_search Agent
→ 심의사례 + 과실비율 판례 검색
→ Supervisor용 JSON output 수신
```

---

## 0-1. Supervisor 실제 호출 예시

Supervisor가 실제 서비스 코드에서 호출할 함수는 아래 파일에 있다.

```text
etl/fault_cases/src/agents/text_ml_case_search/agent.py
```

실제 호출 함수:

```python
run_text_ml_case_search(
    agent_input,
    es_client=client,
    search_variant="schema_search_text",
)
```

예시 코드:

```python
from etl.fault_cases.src.agents.text_ml_case_search.agent import run_text_ml_case_search
from etl.fault_cases.src.agents.text_ml_case_search.rag.es_client import get_elasticsearch_client


client = get_elasticsearch_client()

result = run_text_ml_case_search(
    agent_input=agent_input,
    es_client=client,
    search_variant="schema_search_text",
)
```

여기서 중요한 점은 `es_client`를 넘겨야 실제 RAG 검색이 돈다는 것이다.

```text
es_client 있음
→ 실제 Elasticsearch BM25+Nori 검색 수행
→ review_case + fault_ratio_precedent evidence 생성
→ contract_version = text_ml_case_search_v2

es_client 없음
→ 검색 없는 mock/skeleton 경로
→ Agent 구조 테스트용
```

---

## 0-2. 테스트 runner와 실제 Supervisor 호출 차이

아래 파일은 사람이 샘플 입력 10개로 검증할 때 쓰는 실행 파일이다.

```text
etl/fault_cases/src/agents/text_ml_case_search/run_full_optional_inputs.py
```

PowerShell 실행 명령:

```powershell
.\.venv\Scripts\python.exe -B -m etl.fault_cases.src.agents.text_ml_case_search.run_full_optional_inputs --limit 10
```

이 runner의 목적:

```text
1. active input JSONL에서 샘플 입력을 읽는다.
2. Elasticsearch client를 만든다.
3. 각 입력마다 run_text_ml_case_search(...)를 호출한다.
4. 결과를 JSONL과 summary JSON으로 저장한다.
5. PM 발표 및 개발 검증용 결과를 만든다.
```

즉 이 runner는 Supervisor 운영 코드가 아니다.

```text
run_full_optional_inputs.py
→ 개발자/PM 검증용 일괄 실행 runner

run_text_ml_case_search(...)
→ Supervisor가 실제로 호출해야 하는 Agent 함수
```

Supervisor 담당자는 runner를 가져다 붙이는 것이 아니라,
`run_text_ml_case_search(...)` 호출 방식을 서비스 흐름에 연결하면 된다.

---

## 0-3. Supervisor가 넘겨야 하는 입력

최소 입력은 `query_text`다.

```json
{
  "session_id": "ses_001",
  "message_id": "msg_001",
  "job_id": "job_001",
  "node_code": "text_ml_case_search",
  "raw_user_text": "사용자가 입력한 사고 설명 원문",
  "query_text": "검색과 사고 정리에 사용할 핵심 사고 설명",
  "vision_evidence": [],
  "ocr_evidence": null,
  "insurer_claim": null,
  "required_outputs": [
    "normalized_description",
    "issue_tags",
    "similar_cases",
    "evidence",
    "ratio_range_label",
    "insurer_claim_review"
  ]
}
```

필수 여부:

| 필드 | 필수 여부 | 설명 |
|---|---:|---|
| `query_text` | 필수 | Agent가 검색과 사고 정리를 수행할 핵심 문장 |
| `raw_user_text` | 선택 | 사용자 원문 |
| `vision_evidence` | 선택 | 영상/이미지 분석 결과 |
| `ocr_evidence` | 선택 | 교통사고사실확인원 OCR 결과 |
| `insurer_claim` | 선택 | 보험사 과실비율 주장 |

`insurer_claim`이 없으면 `insurer_claim_review`는 `null`로 반환된다.

---

## 0-4. Supervisor가 주로 읽으면 되는 출력 필드

최종 output은 `result` JSON이다.

Supervisor가 최종 답변 생성에 우선 사용하면 되는 필드는 아래다.

```text
result.status
result.contract_version
result.structured_result.normalized_description
result.structured_result.issue_tags
result.structured_result.source_summary
result.structured_result.display_evidence
result.structured_result.similar_cases
result.structured_result.ratio_range_label
result.structured_result.insurer_claim_review
result.structured_result.recommended_evidence
result.next_actions
result.limitations
```

개발/디버깅용으로만 보면 되는 필드는 아래다.

```text
result.structured_result.search_text
result.structured_result.rag_debug
result.evidence.metadata.score
result.evidence.metadata.highlight
```

Supervisor 답변에는 원칙적으로 `display_evidence`를 우선 사용한다.

```text
evidence
→ 내부 근거 원본에 가까움

display_evidence
→ 사용자에게 보여주기 좋게 정리된 근거
```

---

## 0-5. 정상 연결 여부 확인 기준

Supervisor 담당자가 연결 후 확인할 핵심 조건은 다음과 같다.

```text
1. result.contract_version = text_ml_case_search_v2
2. result.status = success 또는 partial
3. result.structured_result.source_summary.active_sources에 review_case, fault_ratio_precedent 포함
4. result.structured_result.display_evidence가 비어 있지 않음
5. result.structured_result.similar_cases가 비어 있지 않음
6. result.structured_result.ratio_range_label이 있으면 참고 비율로만 사용
7. result.limitations가 최종 답변에 반영 가능함
```

현재 검증된 active 10개 실행 결과는 다음과 같다.

```text
active_input_count = 10
status_counts = {"success": 10}
total_evidence_count = 100
total_review_case_evidence_count = 50
total_fault_ratio_precedent_evidence_count = 50
zero_evidence_count = 0
```

즉 샘플 10개 기준으로는 각 입력마다 다음 구조가 붙었다.

```text
review_case evidence 5개
fault_ratio_precedent evidence 5개
총 evidence 10개
```

---

## 0-6. Supervisor 답변 생성 시 주의 문구

Agent가 반환하는 `ratio_range_label`은 확정 과실비율이 아니다.

```text
ratio_range_label
→ 검색된 심의사례/판례 근거에서 참고 가능한 비율 범위
→ 최종 법적 판단 또는 확정 과실비율 아님
```

권장 표현:

```text
아래 근거들은 유사한 사고 유형에서 참고할 수 있는 심의사례 및 판례입니다.
실제 과실비율은 신호, 진입 시점, 충돌 위치, 블랙박스 영상, 보험사 산정 근거 등에 따라 달라질 수 있습니다.
```

피해야 할 표현:

```text
이 사건의 과실비율은 70:30으로 확정됩니다.
이 판례 때문에 반드시 사용자가 이깁니다.
보험사 주장은 틀렸습니다.
```

Supervisor는 Agent 결과를 다음처럼 사용하는 것이 안전하다.

```text
1. display_evidence로 근거 요약 제시
2. similar_cases로 유사 사례/판례 목록 제시
3. ratio_range_label은 참고 범위로만 표현
4. insurer_claim_review는 보험사 주장 검토용으로만 표현
5. limitations와 recommended_evidence를 함께 안내
```

---
# text_ml_case_search V2 ?ㅽ뻾 ?먮쫫 諛쒗몴???뺣━

## 1. 理쒖쥌 紐⑹쟻

`text_ml_case_search` Agent V2??紐⑹쟻? Supervisor媛 ?섍릿 ?ш퀬 ?ㅻ챸怨??좏깮 ?낅젰??諛쏆븘?? 怨쇱떎鍮꾩쑉 ?먮떒???꾩슂??洹쇨굅瑜?寃?됲븯怨?Supervisor媛 諛붾줈 ?ъ슜?????덈뒗 JSON output??諛섑솚?섎뒗 寃껋씠??

V2 湲곗? ?듭떖? ?ㅼ쓬怨?媛숇떎.

```text
Supervisor ?낅젰
??text_ml_case_search Agent
???ъ쓽?щ? review_case 寃????怨쇱떎鍮꾩쑉 ?먮? fault_ratio_precedent 寃??????洹쇨굅瑜?5+5濡?蹂묓빀
???ъ슜???쒖떆??evidence / ?좎궗?щ? / 李멸퀬 怨쇱떎鍮꾩쑉 / 蹂댄뿕??二쇱옣 寃???뺣━
??Supervisor媛 理쒖쥌 ?듬? ?앹꽦???ъ슜??output schema 諛섑솚
```

V2?먯꽌 active??source????媛쒕떎.

| source_type | ?섎? | V2 ?곹깭 |
|---|---|---|
| `review_case` | 怨쇱떎鍮꾩쑉 ?ъ쓽?щ? | active |
| `fault_ratio_precedent` | 怨쇱떎鍮꾩쑉 愿???먮? | active |
| `traffic_precedent` | 援먰넻?ш퀬 ?쇰컲 ?먮? | standby |
| `standard` | ?몄젙湲곗? | excluded |

---

## 2. ?쒖옉??
### Supervisor媛 肄붾뱶?먯꽌 吏곸젒 ?몄텧????
Supervisor媛 ?ㅼ젣 ?쒕퉬??肄붾뱶?먯꽌 ?몄텧?댁빞 ?섎뒗 ?⑥닔???ㅼ쓬?대떎.

```text
etl/fault_cases/src/agents/text_ml_case_search/agent.py
```

?듭떖 ?⑥닔:

```python
run_text_ml_case_search(
    agent_input,
    es_client=client,
    search_variant="schema_search_text",
)
```

??븷:

```text
Supervisor ?낅젰??諛쏆븘 text_ml_case_search ?꾩껜 ?먮쫫???ㅽ뻾?쒕떎.
es_client媛 ?ㅼ뼱?ㅻ㈃ ?ㅼ젣 Elasticsearch RAG 寃?됱쓣 ?섑뻾?쒕떎.
es_client媛 ?녾퀬 mock_evidence留??덉쑝硫??뚯뒪???ㅼ펷?덊넠 寃쎈줈濡??숈옉?쒕떎.
```

### ?щ엺???뚯뒪?몄슜?쇰줈 ?ㅽ뻾????
active 10媛??섑뵆 ?낅젰?쇰줈 ?ㅽ뻾???뚮뒗 ?꾨옒 runner瑜??ъ슜?쒕떎.

```text
etl/fault_cases/src/agents/text_ml_case_search/run_full_optional_inputs.py
```

PowerShell ?ㅽ뻾 紐낅졊:

```powershell
.\.venv\Scripts\python.exe -B -m etl.fault_cases.src.agents.text_ml_case_search.run_full_optional_inputs --limit 10
```

??紐낅졊????븷:

```text
1. active input JSONL?먯꽌 二쇱꽍???꾨땶 ?낅젰 10媛쒕? ?쎈뒗??
2. Elasticsearch client瑜?留뚮뱺??
3. 媛??낅젰留덈떎 run_text_ml_case_search(...)瑜??몄텧?쒕떎.
4. 寃곌낵瑜?JSONL怨?summary JSON?쇰줈 ??ν븳??
```

?낅젰 ?뚯씪:

```text
etl/fault_cases/artifacts/review_case_output/schema_search_test/text_ml_case_search_agent_input_full_optional_fields.jsonl
```

異쒕젰 ?뚯씪:

```text
etl/fault_cases/artifacts/review_case_output/agent_runs/text_ml_case_search_full_optional_agent_outputs.jsonl
etl/fault_cases/artifacts/review_case_output/agent_runs/text_ml_case_search_full_optional_agent_summary.json
```

---

## 3. ?낅젰 援ъ“

Supervisor媛 ?섍린???낅젰? `agent_input` 媛앹껜??

???援ъ“:

```json
{
  "session_id": "ses_...",
  "message_id": "msg_...",
  "job_id": "job_...",
  "node_code": "text_ml_case_search",
  "raw_user_text": "?ъ슜???먮Ц",
  "query_text": "寃?됯낵 ?ш퀬 ?뺣━???ъ슜???듭떖 臾몄옣",
  "vision_evidence": [],
  "ocr_evidence": {},
  "insurer_claim": {
    "claimed_ratio": "?ъ슜??70 : ?곷? 30",
    "reason_text": "蹂댄뿕?ъ쓽 二쇱옣 ?댁쑀",
    "source_type": "user_text",
    "source_text": "?ъ슜?먭? ?꾨떖??蹂댄뿕???ㅻ챸",
    "source_reference": null
  },
  "required_outputs": [
    "normalized_description",
    "issue_tags",
    "similar_cases",
    "evidence",
    "ratio_range_label"
  ]
}
```

?꾩닔 ?낅젰? `query_text`??

| ?꾨뱶 | ?꾩닔 ?щ? | ?ㅻ챸 |
|---|---:|---|
| `query_text` | ?꾩닔 | ?ш퀬 ?곹솴 寃?됯낵 ?뺢퇋?붿쓽 ?듭떖 臾몄옣 |
| `raw_user_text` | ?좏깮 | ?ъ슜???먮Ц |
| `vision_evidence` | ?좏깮 | ?곸긽/?대?吏 遺꾩꽍 寃곌낵 |
| `ocr_evidence` | ?좏깮 | 援먰넻?ш퀬?ъ떎?뺤씤??OCR 寃곌낵 |
| `insurer_claim` | ?좏깮 | 蹂댄뿕??怨쇱떎鍮꾩쑉 二쇱옣 |

`query_text`媛 ?놁쑝硫?Agent??`failed`瑜?諛섑솚?쒕떎.

---

## 4. 1李??낅젰 寃利?
?뚯씪:

```text
etl/fault_cases/src/agents/text_ml_case_search/input/validator.py
```

?몄텧 ?꾩튂:

```text
agent.py
```

??븷:

```text
?낅젰??query_text媛 ?덈뒗吏 ?뺤씤?쒕떎.
?꾩닔 ?낅젰???놁쑝硫?寃?됱쓣 ?쒖옉?섏? ?딄퀬 failed output??留뚮뱺??
```

?뺤긽????

```text
validation.ok = true
```

?ㅽ뙣????

```json
{
  "contract_version": "text_ml_case_search_v2",
  "node_code": "text_ml_case_search",
  "status": "failed",
  "missing_fields": ["query_text"]
}
```

???꾩슂?쒓?:

```text
Supervisor媛 遺덉셿?꾪븳 ?낅젰???섍꺼??Agent媛 ?곗?吏 ?딄퀬,
?ъ슜?먯뿉寃??대뼡 ?낅젰??遺議깊븳吏 ?섎룎?ㅼ＜湲??꾪빐?쒕떎.
```

---

## 5. ?낅젰 context ?뺣━

?뚯씪:

```text
etl/fault_cases/src/agents/text_ml_case_search/input/context_builder.py
```

?몄텧 ?꾩튂:

```text
agent.py
```

??븷:

```text
Supervisor ?낅젰??Agent ?대??먯꽌 ?곌린 ?ъ슫 context 援ъ“濡??뺣━?쒕떎.
?놁뼱???섎뒗 媛믪? None ?먮뒗 鍮?諛곗뿴濡??뺢퇋?뷀븳??
```

??

```text
vision_evidence媛 ?놁쑝硫??ㅽ뙣媛 ?꾨땲??鍮?媛믪쑝濡?泥섎━
ocr_evidence媛 ?놁쑝硫??ㅽ뙣媛 ?꾨땲??null濡?泥섎━
insurer_claim???놁쑝硫??ㅽ뙣媛 ?꾨땲??insurer_claim_review留?null 媛??```

---

## 6. ?ш퀬 ?ㅻ챸 ?뺢퇋??
?뚯씪:

```text
etl/fault_cases/src/agents/text_ml_case_search/input/normalizer.py
```

?몄텧 ?꾩튂:

```text
agent.py
```

??븷:

```text
?ъ슜???낅젰???ш퀬 ?좏삎 ?꾨낫? ?뺢퇋?붾맂 ?ш퀬 ?ㅻ챸?쇰줈 諛붽씔??
```

以묎컙 ?곗텧臾?

```json
{
  "normalized_description": "李⑤줈蹂寃?以??꾪뻾 李⑤웾 異⑸룎 ?ш퀬濡??뺣━?⑸땲??..",
  "accident_type_candidates": [
    {
      "type": "李⑤줈 蹂寃?以??꾪뻾 李⑤웾 異⑸룎 ?ш퀬",
      "reason": "李⑤줈/吏꾨줈蹂寃??쒗쁽???ы븿?섏뼱 ?덉뒿?덈떎."
    }
  ]
}
```

???꾩슂?쒓?:

```text
?ъ슜??臾몄옣? 湲멸굅???좊ℓ?????덈떎.
寃?됯낵 理쒖쥌 ?듬??먯꽌 ?쇨??섍쾶 ?곕젮硫??ш퀬 ?좏삎怨??듭떖 ?ㅻ챸??癒쇱? ?뺣━?댁빞 ?쒕떎.
```

---

## 7. ?곸젏 ?쒓렇 異붿텧

?뚯씪:

```text
etl/fault_cases/src/agents/text_ml_case_search/input/issue_tagger.py
```

?몄텧 ?꾩튂:

```text
agent.py
```

??븷:

```text
?ш퀬 ?ㅻ챸?먯꽌 二쇱슂 ?곸젏???쒓렇濡?戮묐뒗??
```

??

```text
李⑤줈 蹂寃?吏꾨줈蹂寃?二쇱쓽?섎Т
?꾪뻾 李⑤웾 ?꾨갑二쇱떆
?좏샇?꾨컲
蹂댄뻾??蹂댄샇?섎Т
蹂댄뿕??怨쇱떎鍮꾩쑉 二쇱옣
```

???쒓렇????怨녹뿉???곗씤??

```text
1. 寃???낅젰 ?앹꽦
2. recommended_evidence ?앹꽦
3. insurer_claim_review?먯꽌 蹂댄뿕??二쇱옣怨?鍮꾧탳???곸젏 ?뺣━
```

---

## 8. RAG 寃?됰Ц ?앹꽦

?뚯씪:

```text
etl/fault_cases/src/agents/text_ml_case_search/rag/search_text_builder.py
```

?몄텧 ?꾩튂:

```text
agent.py
```

??븷:

```text
寃?됱뿉 ?ъ슜???щ윭 ?뺥깭??text variant瑜?留뚮뱺??
???④퀎?먯꽌??Elasticsearch瑜??몄텧?섏? ?딅뒗??
```

?앹꽦?섎뒗 寃???낅젰 variant:

| variant | ?섎? |
|---|---|
| `natural_query_text` | ?ъ슜?먯쓽 query_text ?먮Ц |
| `normalized_description` | ?뺢퇋?붾맂 ?ш퀬 ?ㅻ챸 |
| `schema_search_text` | ?ш퀬?좏삎/?곸젏/?ш퀬?ㅻ챸??臾띠? 寃?됱슜 臾몄옣 |
| `full_optional_context` | Vision/OCR/蹂댄뿕??二쇱옣源뚯? ?ы븿??湲?寃??context |

湲곕낯 寃??variant:

```text
schema_search_text
```

??`schema_search_text`瑜?湲곕낯?쇰줈 ?곕뒗媛:

```text
?먯뿰????臾몄옣蹂대떎 ?ш퀬?좏삎, ?곸젏, ?ш퀬?ㅻ챸??媛숈씠 ?댁븘 BM25+Nori 寃?됱뿉 ?꾩슂???ㅼ썙?쒖? 臾몃㎘?????덉젙?곸쑝濡??쒓났?섍린 ?꾪빐?쒕떎.
```

---

## 9. Elasticsearch client ?앹꽦

?뚯씪:

```text
etl/fault_cases/src/agents/text_ml_case_search/rag/es_client.py
```

二쇰줈 ?몄텧?섎뒗 ?뚯씪:

```text
etl/fault_cases/src/agents/text_ml_case_search/run_full_optional_inputs.py
etl/fault_cases/src/agents/text_ml_case_search/run_agent_sample.py
```

??븷:

```text
.env ?ㅼ젙???쎌뼱 Elasticsearch???묎렐??client瑜?留뚮뱺??
ping?쇰줈 ?묒냽 媛???щ?瑜??뺤씤?쒕떎.
```

愿???ㅼ젙 ?뚯씪:

```text
.env
```

二쇱슂 ?섍꼍蹂??

```text
ELASTICSEARCH_HOST
ELASTICSEARCH_USER
ELASTIC_PASSWORD
```

?ㅽ뻾 ?꾩뿉 ?꾩슂??議곌굔:

```text
docker compose ps?먯꽌 elasticsearch媛 Up ?곹깭?ъ빞 ?쒕떎.
.env??ELASTIC_PASSWORD媛 ?ㅼ젣 Elasticsearch 鍮꾨?踰덊샇? 媛숈븘???쒕떎.
```

---

## 10. ?듯빀 RAG ?ㅽ뻾

?뚯씪:

```text
etl/fault_cases/src/agents/text_ml_case_search/rag/unified_retriever.py
```

?듭떖 ?⑥닔:

```python
run_unified_rag_pipeline(
    es=client,
    search_text=search_text,
    search_variant="schema_search_text",
)
```

?몄텧 ?꾩튂:

```text
agent.py
```

???뚯씪???섎뒗 ??

```text
1. ?ъ슜??search_text variant ?좏깮
2. review_case BM25+Nori 寃???ㅽ뻾
3. fault_ratio_precedent BM25+Nori 寃???ㅽ뻾
4. 媛?source??raw hit??evidence 援ъ“濡?蹂??5. evidence ?덉쭏 寃利?6. review_case 5媛?+ fault_ratio_precedent 5媛쒕줈 蹂묓빀
7. source_summary ?앹꽦
```

???먮쫫:

```text
search_text
??run_review_case_bm25_pipeline
??_run_fault_ratio_precedent_pipeline
??merge_evidence_by_source_quota
??source_summary
??evidence 諛섑솚
```

---

## 11. review_case 寃???먮쫫

### 11-1. review_case pipeline

?뚯씪:

```text
etl/fault_cases/src/agents/text_ml_case_search/rag/retrieval_pipeline.py
```

?듭떖 ?⑥닔:

```python
run_review_case_bm25_pipeline(...)
```

??븷:

```text
?ъ쓽?щ? review_case 寃???먮쫫???섎굹濡?臾띕뒗??
```

?대? ?먮쫫:

```text
select_search_text
??search_bm25_nori
??map_review_case_hits_to_evidence
??validate_evidence
??review_case evidence 諛섑솚
```

### 11-2. review_case BM25+Nori 寃?됯린

?뚯씪:

```text
etl/fault_cases/src/agents/text_ml_case_search/rag/bm25_nori_retriever.py
```

??븷:

```text
Elasticsearch??review_case BM25+Nori 寃???붿껌??蹂대궦??
```

寃??諛⑹떇:

```text
multi_match
operator = "or"
highlight ?ъ슜
```

寃??????꾨뱶:

```text
search_text^4
chunk_text^2
case_title^2
header_road_context^1.5
search_text_standard
chunk_text_standard
```

???꾨뱶 媛以묒튂???섎?:

```text
search_text??寃?됱슜?쇰줈 ?뺣━???꾨뱶??媛???믨쾶 蹂몃떎.
chunk_text???먮Ц 洹쇨굅??以묒슂?섏?留?search_text蹂대떎 ??쾶 ?붾떎.
case_title怨??꾨줈 留λ씫??蹂댁“ ?좏샇濡??ъ슜?쒕떎.
```

### 11-3. review_case evidence 蹂??
?뚯씪:

```text
etl/fault_cases/src/agents/text_ml_case_search/rag/evidence_mapper.py
```

??븷:

```text
Elasticsearch raw hit??Agent 怨듯넻 evidence 援ъ“濡?諛붽씔??
```

蹂????

```text
review_case_id ??metadata.case_id
review_no ??metadata.review_no
chunk_id ??source_reference / metadata.chunk_id
decision_fault_ratio ??metadata.decision_fault_ratio
reference_chart_key ??metadata.reference_chart_key
highlight ??metadata.highlight
chunk_text ??evidence.chunk_text
```

---

## 12. fault_ratio_precedent 寃???먮쫫

### 12-1. fault_ratio_precedent BM25+Nori 寃?됯린

?뚯씪:

```text
etl/fault_cases/src/agents/text_ml_case_search/rag/fault_ratio_precedent_retriever.py
```

??븷:

```text
Elasticsearch??怨쇱떎鍮꾩쑉 ?먮? BM25+Nori 寃???붿껌??蹂대궦??
```

寃??諛⑹떇:

```text
multi_match
operator = "or"
highlight ?ъ슜
```

寃??????꾨뱶:

```text
search_text^4
chunk_text^2
case_name^1.5
search_text_standard
chunk_text_standard
```

review_case? ?ㅻⅤ寃?`case_name`???곕뒗 ?댁쑀:

```text
?먮? index???ъ쓽?щ???case_title ???case_name 援ъ“瑜?媛吏꾨떎.
source蹂?schema媛 ?ㅻⅤ湲??뚮Ц??source??留욌뒗 ?꾨뱶瑜??ъ슜?쒕떎.
```

### 12-2. fault_ratio_precedent evidence 蹂??
?뚯씪:

```text
etl/fault_cases/src/agents/text_ml_case_search/rag/fault_ratio_precedent_evidence_mapper.py
```

??븷:

```text
?먮? Elasticsearch raw hit??Agent 怨듯넻 evidence 援ъ“濡?諛붽씔??
```

蹂????

```text
case_id ??metadata.case_id
case_number ??metadata.case_number
case_name ??title / metadata.case_name
court_name ??metadata.court_name
decision_date ??metadata.decision_date
chunk_id ??source_reference / metadata.chunk_id
chunk_type ??metadata.chunk_type
highlight ??metadata.highlight
chunk_text ??evidence.chunk_text
```

source_type:

```text
fault_ratio_precedent
```

Supervisor????媛믪쓣 蹂닿퀬 ?쒓????먮? 洹쇨굅?앸줈 ?쒖떆?????덈떎.

---

## 13. evidence ?덉쭏 寃利?
?뚯씪:

```text
etl/fault_cases/src/agents/text_ml_case_search/rag/evidence_validator.py
```

?몄텧 ?꾩튂:

```text
retrieval_pipeline.py
unified_retriever.py
```

??븷:

```text
寃??寃곌낵 以?Agent 洹쇨굅濡??곌린 ?대젮????ぉ??嫄몃윭?몃떎.
```

???寃利?湲곗?:

```text
source_reference媛 ?덈뒗媛
chunk_text媛 ?덈Т 吏㏃? ?딆?媛
```

???꾩슂?쒓?:

```text
寃??寃곌낵媛 ?덉뼱??異쒖쿂媛 ?녾굅??蹂몃Ц???덈Т 吏㏃쑝硫??ъ슜???듬? 洹쇨굅濡??곌린 ?대졄??
Supervisor?먭쾶 遺?ㅽ븳 evidence媛 ?섏뼱媛??寃껋쓣 以꾩씠湲??꾪븳 ?덉쟾?μ튂??
```

---

## 14. evidence 蹂묓빀

?뚯씪:

```text
etl/fault_cases/src/agents/text_ml_case_search/rag/evidence_merger.py
```

?듭떖 ?⑥닔:

```python
merge_evidence_by_source_quota(...)
```

??븷:

```text
review_case evidence? fault_ratio_precedent evidence瑜?理쒖쥌 evidence 紐⑸줉?쇰줈 ?⑹튇??
```

V2 蹂묓빀 ?꾨왂:

```text
merge_strategy = source_quota
review_case quota = 5
fault_ratio_precedent quota = 5
final_top_k = 10
```

??5+5?멸?:

```text
1. ?ъ쓽?щ?? ?먮?媛 紐⑤몢 理쒖쥌 output??蹂댁씠寃??섍린 ?꾪빐?쒕떎.
2. ?쒕줈 ?ㅻⅨ Elasticsearch index??BM25 ?먯닔??吏곸젒 鍮꾧탳 湲곗??쇰줈 ?곌린 ?대졄??
3. ?쒖そ source媛 ?먯닔瑜??낆젏?댁꽌 ?ㅻⅨ source媛 ?щ씪吏??臾몄젣瑜?留됰뒗??
4. top 10? Supervisor媛 理쒖쥌 ?듬????붿빟?섍린??媛먮떦 媛?ν븳 ?ш린??
```

理쒖쥌 蹂묓빀 寃곌낵:

```json
{
  "merge_strategy": "source_quota",
  "review_case_quota": 5,
  "fault_ratio_precedent_quota": 5,
  "final_top_k": 10,
  "source_counts": {
    "review_case": 5,
    "fault_ratio_precedent": 5
  },
  "evidence": []
}
```

---

## 15. source_summary ?앹꽦

?앹꽦 ?꾩튂:

```text
etl/fault_cases/src/agents/text_ml_case_search/rag/unified_retriever.py
```

理쒖쥌 output ?꾩튂:

```text
result.structured_result.source_summary
```

??

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

Supervisor媛 ?닿구 蹂대뒗 ?댁쑀:

```text
1. ?대뼡 source?먯꽌 洹쇨굅媛 ?붾뒗吏 ?????덈떎.
2. ?ъ쓽?щ?留??덈뒗吏, ?먮?源뚯? ?덈뒗吏 ?뺤씤?????덈떎.
3. standard媛 ?꾩쭅 ?쒖쇅?먮떎???먯쓣 ?듬? ?쒓퀎濡?諛섏쁺?????덈떎.
```

---

## 16. Agent ?대? ?꾩쿂由?builder

寃?됯낵 蹂묓빀???앸굹硫?`agent.py`??evidence瑜?諛뷀깢?쇰줈 ?ъ슜???덊띁諛붿씠????꾨뱶瑜?留뚮뱺??

### 16-1. similar_cases ?앹꽦

?뚯씪:

```text
etl/fault_cases/src/agents/text_ml_case_search/builders/similar_case_builder.py
```

??븷:

```text
evidence瑜??좎궗 ?щ?/?먮? ?붿빟 紐⑸줉?쇰줈 諛붽씔??
```

理쒖쥌 ?꾩튂:

```text
result.structured_result.similar_cases
```

### 16-2. ratio_range_label ?앹꽦

?뚯씪:

```text
etl/fault_cases/src/agents/text_ml_case_search/builders/ratio_range_builder.py
```

??븷:

```text
寃??洹쇨굅?먯꽌 李멸퀬 媛?ν븳 怨쇱떎鍮꾩쑉 ?쇰꺼??留뚮뱺??
```

二쇱쓽:

```text
ratio_range_label? 理쒖쥌 ?뺤젙 怨쇱떎鍮꾩쑉???꾨땲??
Supervisor???쒖갭怨?洹쇨굅?먯꽌??...???섏??쇰줈 ?ъ슜?댁빞 ?쒕떎.
```

### 16-3. display_evidence ?앹꽦

?뚯씪:

```text
etl/fault_cases/src/agents/text_ml_case_search/builders/evidence_display_builder.py
```

??븷:

```text
?먯쿇 evidence瑜??ъ슜?먯뿉寃?蹂댁뿬二쇨린 ?ъ슫 洹쇨굅 ?붿빟?쇰줈 諛붽씔??
```

理쒖쥌 ?꾩튂:

```text
result.structured_result.display_evidence
```

Supervisor???ъ슜???듬???`evidence` ?먮Ц蹂대떎 `display_evidence`瑜??곗꽑 ?ъ슜?쒕떎.

### 16-4. recommended_evidence ?앹꽦

?뚯씪:

```text
etl/fault_cases/src/agents/text_ml_case_search/builders/recommended_evidence_builder.py
```

??븷:

```text
?꾩옱 ?ш퀬 ?곸젏???곕씪 ?ъ슜?먭? 異붽?濡?以鍮꾪빐?????먮즺瑜??쒖븞?쒕떎.
```

??

```text
釉붾옓諛뺤뒪 ?곸긽
異⑸룎 ?꾩튂 ?ъ쭊
蹂댄뿕??怨쇱떎 ?곗젙 臾몄옄
援먰넻?ш퀬?ъ떎?뺤씤??```

### 16-5. insurer_claim_review ?앹꽦

?뚯씪:

```text
etl/fault_cases/src/agents/text_ml_case_search/builders/insurer_claim_review_builder.py
```

??븷:

```text
蹂댄뿕??怨쇱떎鍮꾩쑉 二쇱옣怨?RAG 洹쇨굅瑜?鍮꾧탳?????덈뒗 援ъ“瑜?留뚮뱺??
```

二쇱쓽:

```text
蹂댄뿕??二쇱옣? ?뺤젙 ?ъ떎???꾨땲??鍮꾧탳 ???二쇱옣?대떎.
Agent??蹂댄뿕??二쇱옣???뺤젙?섍굅??諛섎컯 ?먯젙?섏? ?딄퀬, 鍮꾧탳???꾩슂??洹쇨굅? 異붽? ?뺤씤?먮즺瑜??뺣━?쒕떎.
```

---

## 17. 理쒖쥌 output 議곕┰

?뚯씪:

```text
etl/fault_cases/src/agents/text_ml_case_search/builders/output_builder.py
```

?몄텧 ?꾩튂:

```text
agent.py
```

??븷:

```text
Agent媛 留뚮뱺 紐⑤뱺 以묎컙 寃곌낵瑜?Supervisor媛 諛쏆쓣 理쒖쥌 JSON?쇰줈 議곕┰?쒕떎.
```

V2 ?ㅼ젣 RAG ?ㅽ뻾 ??

```text
contract_version = text_ml_case_search_v2
node_code = text_ml_case_search
status = success ?먮뒗 partial ?먮뒗 failed
```

理쒖긽??援ъ“:

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

---

## 18. 理쒖쥌 output ?덉떆

?ㅼ젣 output? `run_full_optional_inputs.py` ?ㅽ뻾 ???꾨옒 ?뚯씪????λ맂??

```text
etl/fault_cases/artifacts/review_case_output/agent_runs/text_ml_case_search_full_optional_agent_outputs.jsonl
```

媛?以꾩쓽 援ъ“:

```json
{
  "run_index": 1,
  "session_id": "ses_...",
  "query_text": "...",
  "status": "success",
  "evidence_count": 10,
  "review_case_evidence_count": 5,
  "fault_ratio_precedent_evidence_count": 5,
  "result": {
    "contract_version": "text_ml_case_search_v2",
    "node_code": "text_ml_case_search",
    "status": "success",
    "structured_result": {
      "normalized_description": "...",
      "issue_tags": [],
      "recommended_evidence": [],
      "insurer_claim_review": {},
      "similar_cases": [],
      "ratio_range_label": "...",
      "display_evidence": [],
      "search_text": {},
      "rag_debug": {},
      "source_summary": {}
    },
    "evidence": [],
    "next_actions": [],
    "limitations": [],
    "missing_fields": []
  }
}
```

Supervisor媛 ?ㅼ젣濡?二쇰줈 媛?멸컝 遺遺?

```text
result.status
result.structured_result.normalized_description
result.structured_result.issue_tags
result.structured_result.source_summary
result.structured_result.display_evidence
result.structured_result.similar_cases
result.structured_result.ratio_range_label
result.structured_result.insurer_claim_review
result.structured_result.recommended_evidence
result.next_actions
result.limitations
```

媛쒕컻/寃利앹슜?쇰줈 蹂대뒗 遺遺?

```text
result.structured_result.search_text
result.structured_result.rag_debug
result.evidence.metadata.score
result.evidence.metadata.highlight
```

---

## 19. 蹂닿퀬???앹꽦

?ㅽ뻾 寃곌낵瑜?諛쒗몴/寃?섏슜 蹂닿퀬?쒕줈 留뚮뱾 ???ъ슜?섎뒗 ?뚯씪:

```text
etl/fault_cases/src/agents/text_ml_case_search/build_full_optional_report.py
```

PowerShell ?ㅽ뻾 紐낅졊:

```powershell
.\.venv\Scripts\python.exe -B -m etl.fault_cases.src.agents.text_ml_case_search.build_full_optional_report
```

?낅젰:

```text
etl/fault_cases/artifacts/review_case_output/agent_runs/text_ml_case_search_full_optional_agent_outputs.jsonl
etl/fault_cases/artifacts/review_case_output/agent_runs/text_ml_case_search_full_optional_agent_summary.json
```

異쒕젰:

```text
etl/fault_cases/artifacts/review_case_output/agent_runs/text_ml_case_search_full_optional_agent_report.json
etl/fault_cases/Fault_cases_MD/?먯씠?꾪듃/text_ml_case_search_active_10_?ㅽ뻾_寃곌낵_蹂닿퀬??md
```

蹂닿퀬?쒖뿉???뺤씤?섎뒗 寃?

```text
1. active input 10媛쒓? 紐⑤몢 success?몄?
2. evidence媛 0媛쒖씤 run???덈뒗吏
3. review_case evidence媛 ?ㅼ뼱?붾뒗吏
4. fault_ratio_precedent evidence媛 ?ㅼ뼱?붾뒗吏
5. display_evidence媛 ?앹꽦?먮뒗吏
6. source_summary媛 ?섎룄?濡??섏솕?붿?
```

---

## 20. ?꾩옱 寃利?寃곌낵

V2 active 10媛??ㅽ뻾 寃곌낵:

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

?댁꽍:

```text
10媛??낅젰 紐⑤몢 ?뺤긽 ?ㅽ뻾?먮떎.
媛??낅젰留덈떎 review_case 5媛?+ fault_ratio_precedent 5媛쒓? 遺숈뿀??
利?V2 multi-source RAG??援ъ“ 湲곗??쇰줈 ?뺤긽 ?묐룞?쒕떎.
```

---

## 21. PM 諛쒗몴????以??붿빟

```text
Supervisor媛 ?ш퀬 吏덉쓽瑜?text_ml_case_search Agent???섍린硫?
Agent???낅젰???뺢퇋?뷀븯怨?BM25+Nori 湲곕컲?쇰줈 ?ъ쓽?щ?? 怨쇱떎鍮꾩쑉 ?먮?瑜?媛곴컖 寃?됲븳 ??
5+5 source quota濡?洹쇨굅瑜?蹂묓빀?섏뿬 Supervisor媛 諛붾줈 ?듬? ?앹꽦???ъ슜?????덈뒗
display_evidence, similar_cases, ratio_range_label, insurer_claim_review, source_summary瑜?諛섑솚?쒕떎.
```

---

## 22. PM 諛쒗몴???④퀎 ?붿빟

```text
1. Supervisor媛 agent_input ?꾨떖
2. validator媛 query_text ?꾩닔 ?낅젰 ?뺤씤
3. context_builder媛 ?낅젰???대? context濡??뺣━
4. normalizer媛 ?ш퀬 ?ㅻ챸怨??ш퀬 ?좏삎 ?꾨낫 ?앹꽦
5. issue_tagger媛 二쇱슂 怨쇱떎 ?곸젏 異붿텧
6. search_text_builder媛 schema_search_text ?앹꽦
7. unified_retriever媛 review_case? fault_ratio_precedent瑜?媛곴컖 BM25+Nori 寃??8. mapper媛 Elasticsearch hit??怨듯넻 evidence schema濡?蹂??9. validator媛 洹쇨굅 ?덉쭏 ?뺤씤
10. evidence_merger媛 5+5濡?蹂묓빀
11. builders媛 display_evidence, similar_cases, ratio_range_label, insurer_claim_review ?앹꽦
12. output_builder媛 Supervisor??JSON 諛섑솚
```

---

## 23. Supervisor媛 理쒖쥌 ?듬????곕뒗 諛⑹떇

Supervisor??source_type蹂꾨줈 洹쇨굅 ?쒗쁽???섎닠???쒕떎.

```text
source_type = review_case:
  "?좎궗 ?ъ쓽?щ??먯꽌??..."

source_type = fault_ratio_precedent:
  "愿???먮??먯꽌??..."
```

沅뚯옣 ?쒗쁽:

```text
?꾨옒 洹쇨굅?ㅼ? ?좎궗???ш퀬 ?좏삎?먯꽌 李멸퀬?????덈뒗 ?ъ쓽?щ? 諛??먮??낅땲??
?ㅼ젣 怨쇱떎鍮꾩쑉? ?좏샇, 吏꾩엯 ?쒖젏, 異⑸룎 ?꾩튂, ?곸긽?먮즺 ?깆뿉 ?곕씪 ?щ씪吏????덉뒿?덈떎.
```

?쇳빐?????쒗쁽:

```text
???먮?? ?ъ쓽?щ?媛 怨㏓컮濡?理쒖쥌 怨쇱떎鍮꾩쑉???뺤젙?⑸땲??
```

---

## 24. ?꾩쭅 ?⑥? ?뺤옣 ?꾨낫

?꾩옱 V2??`review_case + fault_ratio_precedent`源뚯? ?꾨즺???곹깭??

異뷀썑 ?뺤옣 ?꾨낫:

```text
1. traffic_precedent 異붽?
2. standard ?몄젙湲곗? 異붽?
3. Supervisor ?ㅼ젣 LangGraph node ?곌껐
4. 理쒖쥌 ?듬? ?앹꽦 ?꾨＼?꾪듃/濡쒖쭅 ?곌껐
5. ?먯쿇 ?곗씠???몄퐫???먮뒗 ?됱씤 ?덉쭏 ?먭?
```

---

## 25. 愿???듭떖 ?뚯씪 紐⑸줉

| 寃쎈줈 | ??븷 |
|---|---|
| `etl/fault_cases/src/agents/text_ml_case_search/agent.py` | Agent 硫붿씤 吏꾩엯??|
| `etl/fault_cases/src/agents/text_ml_case_search/schemas.py` | Agent ?낆텧?????援ъ“ |
| `etl/fault_cases/src/agents/text_ml_case_search/config.py` | index紐? source 踰붿쐞, quota ?ㅼ젙 |
| `etl/fault_cases/src/agents/text_ml_case_search/input/validator.py` | ?꾩닔 ?낅젰 寃利?|
| `etl/fault_cases/src/agents/text_ml_case_search/input/context_builder.py` | ?낅젰 context ?뺣━ |
| `etl/fault_cases/src/agents/text_ml_case_search/input/normalizer.py` | ?ш퀬 ?ㅻ챸 ?뺢퇋??|
| `etl/fault_cases/src/agents/text_ml_case_search/input/issue_tagger.py` | ?곸젏 ?쒓렇 異붿텧 |
| `etl/fault_cases/src/agents/text_ml_case_search/rag/search_text_builder.py` | 寃?됰Ц variant ?앹꽦 |
| `etl/fault_cases/src/agents/text_ml_case_search/rag/es_client.py` | Elasticsearch client ?앹꽦 |
| `etl/fault_cases/src/agents/text_ml_case_search/rag/unified_retriever.py` | V2 ?듯빀 RAG pipeline |
| `etl/fault_cases/src/agents/text_ml_case_search/rag/retrieval_pipeline.py` | review_case 寃??pipeline |
| `etl/fault_cases/src/agents/text_ml_case_search/rag/bm25_nori_retriever.py` | review_case BM25+Nori 寃?됯린 |
| `etl/fault_cases/src/agents/text_ml_case_search/rag/fault_ratio_precedent_retriever.py` | ?먮? BM25+Nori 寃?됯린 |
| `etl/fault_cases/src/agents/text_ml_case_search/rag/evidence_mapper.py` | review_case evidence 蹂??|
| `etl/fault_cases/src/agents/text_ml_case_search/rag/fault_ratio_precedent_evidence_mapper.py` | ?먮? evidence 蹂??|
| `etl/fault_cases/src/agents/text_ml_case_search/rag/evidence_validator.py` | evidence ?덉쭏 寃利?|
| `etl/fault_cases/src/agents/text_ml_case_search/rag/evidence_merger.py` | 5+5 source quota 蹂묓빀 |
| `etl/fault_cases/src/agents/text_ml_case_search/builders/evidence_display_builder.py` | ?ъ슜???쒖떆??洹쇨굅 ?앹꽦 |
| `etl/fault_cases/src/agents/text_ml_case_search/builders/similar_case_builder.py` | ?좎궗?щ?/?먮? ?붿빟 ?앹꽦 |
| `etl/fault_cases/src/agents/text_ml_case_search/builders/ratio_range_builder.py` | 李멸퀬 怨쇱떎鍮꾩쑉 ?쇰꺼 ?앹꽦 |
| `etl/fault_cases/src/agents/text_ml_case_search/builders/insurer_claim_review_builder.py` | 蹂댄뿕??二쇱옣 寃???앹꽦 |
| `etl/fault_cases/src/agents/text_ml_case_search/builders/recommended_evidence_builder.py` | 異붽? 利앷굅?먮즺 異붿쿇 ?앹꽦 |
| `etl/fault_cases/src/agents/text_ml_case_search/builders/output_builder.py` | 理쒖쥌 Supervisor output 議곕┰ |
| `etl/fault_cases/src/agents/text_ml_case_search/run_full_optional_inputs.py` | active input ?ㅽ뻾 runner |
| `etl/fault_cases/src/agents/text_ml_case_search/build_full_optional_report.py` | ?ㅽ뻾 寃곌낵 蹂닿퀬???앹꽦 |
| `etl/fault_cases/Fault_cases_MD/?먯씠?꾪듃/text_ml_case_search_Supervisor_?낆텧??怨꾩빟_V2.md` | Supervisor 怨꾩빟 V2 臾몄꽌 |
| `etl/fault_cases/Fault_cases_MD/?먯씠?꾪듃/text_ml_case_search_active_10_?ㅽ뻾_寃곌낵_蹂닿퀬??md` | active 10 ?ㅽ뻾 寃곌낵 蹂닿퀬??|



