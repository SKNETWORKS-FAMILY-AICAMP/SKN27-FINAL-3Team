# PM 발표 참고용 Agent/RAG 설계 근거 정리

## 0. 이 문서의 용도

이 문서는 발표 대본이 아니라, PM님이 과실비율 Agent/RAG 구조를 설명할 때 참고할 수 있도록 설계 이유와 실제 구현 근거를 정리한 문서다.

각 섹션은 아래 기준으로 작성했다.

```text
왜 그렇게 했는가
실제로 어떻게 구현했는가
현재 한계는 무엇인가
질문을 받으면 어떻게 답변할 수 있는가
```

---

## 1. 발표에서 가장 먼저 말할 핵심

이번 과실비율 Agent와 RAG의 핵심은 단순 검색이 아니다.

```text
기존 검색:
문자열이 비슷한 판례나 사례를 가져오는 방식

이번 Agent/RAG:
사용자 사고 상황에 맞는 심의사례와 판례를 찾아
Supervisor가 바로 답변에 사용할 수 있는 근거 구조로 정리하는 방식
```

즉, 문서를 많이 가져오는 것이 목적이 아니라 “이 사용자 사고에 왜 맞는 근거인지”를 정리해서 넘기는 것이 목적이다.

발표에서는 아래처럼 말하면 된다.

```text
기존 검색은 관련 있어 보이는 문서를 가져오는 데서 끝나지만,
이번 Agent/RAG는 사용자의 사고 상황을 정리하고
그 상황에 맞는 심의사례와 판례 근거를 Supervisor가 바로 사용할 수 있는 JSON으로 변환합니다.
```

---

## 2. 왜 text_ml_case_search Agent를 사용했는가

사용자가 사고 설명을 입력하면, 단순 검색만으로는 다음 문제가 생긴다.

```text
1. 검색 결과가 실제 사고 상황과 맞는지 사람이 다시 판단해야 한다.
2. 심의사례와 판례가 섞이면 출처별 의미가 불명확해진다.
3. 보험사 주장, OCR, 영상 분석 결과 같은 사용자 맥락을 검색에 반영하기 어렵다.
4. 검색 결과가 Supervisor가 바로 사용할 수 있는 JSON 구조가 아니다.
```

그래서 `text_ml_case_search` Agent를 사용했다.

Agent의 역할은 다음과 같다.

```text
1. 사용자 사고 설명을 정규화한다.
2. 사고 쟁점을 태그로 뽑는다.
3. 검색에 적합한 schema_search_text를 만든다.
4. 심의사례와 과실비율 판례를 각각 검색한다.
5. 사용자에게 보여줄 display_evidence로 정리한다.
6. Supervisor가 사용할 output schema로 반환한다.
```

여기서 중요한 점은 Agent가 “검색 결과 원본”을 그대로 넘기지 않는다는 것이다.
### Agent가 필요한 이유에 대한 질문 대응

RAG 검색 결과는 Elasticsearch raw hit 또는 DB row에 가깝다. 그대로 Supervisor에게 넘기면 검색 점수, highlight, chunk_text, metadata를 다시 해석해야 한다.

`text_ml_case_search` Agent는 검색 결과를 아래 구조로 바꾼다.

```text
RAG raw hit
-> evidence
-> display_evidence
-> similar_cases
-> ratio_range_label
-> insurer_claim_review
-> source_summary
```

즉 Agent는 검색기 자체가 아니라, 검색 결과를 Supervisor가 바로 사용할 수 있는 근거 JSON으로 정리하는 변환 계층이다.

PM님이 질문을 받으면 이렇게 답변하면 된다.

```text
RAG 검색은 관련 문서를 찾는 단계이고,
Agent는 그 검색 결과를 사용자 답변에 쓸 수 있는 근거 구조로 정리하는 단계입니다.
그래서 Supervisor가 raw 검색 결과를 다시 해석하지 않아도 됩니다.
```

```text
검색 결과 원본
-> 출처, 사건명, 근거 문장, 참고 비율, 한계사항을 정리
-> Supervisor 답변 생성에 바로 사용할 수 있는 구조로 변환
```

---

## 3. 왜 BM25+Nori를 사용했는가

과실비율 판단에서는 정확한 사고 유형과 법률 키워드가 중요하다.

실제 검색과 평가에서 사용한 주요 사고/법률 키워드는 다음과 같다.

```text
차로변경
진로변경 주의의무
후방추돌
신호위반
횡단보도 보행자 보호의무
과실상계
손해배상 책임제한
```

그래서 기본 검색 방식으로 BM25+Nori를 사용했다.

```text
BM25
-> 검색어와 문서의 키워드 매칭 강도를 계산하는 검색 방식

Nori
-> Elasticsearch의 한국어 형태소 분석기
-> 차로변경, 보행자, 과실상계 같은 한국어 표현을 검색 가능한 단위로 나눔
```

선택 이유는 다음과 같다.

```text
1. 사고 유형과 법률 쟁점은 키워드 일치가 중요하다.
2. 한국어 법률 문장은 형태소 분석이 없으면 검색 품질이 떨어질 수 있다.
3. 이전 A/B 실험에서 BM25+Nori가 운영 baseline으로 쓰기에 충분한 결과를 보였다.
4. vector/hybrid/reranker는 실험에는 유용하지만, 운영 경로는 단순하고 재현 가능한 BM25+Nori가 적합했다.
```

---


### BM25+Nori 선택 근거 점수 요약

아래 점수는 로컬 reranker로 검색 후보를 다시 평가한 A/B 결과다.  
즉, 각 검색기가 가져온 후보가 query와 얼마나 잘 맞는지 같은 reranker 기준으로 비교한 값이다.

| 평가 대상 | Retriever | Query Count | Avg Top1 | Avg@5 | 해석 |
|---|---:|---:|---:|---:|---|
| 판례 검색 전체 | Elasticsearch BM25/Nori | 20 | 0.7038 | 0.6981 | 전체 Top1과 Avg@5가 가장 안정적이었다. |
| 판례 검색 전체 | Elasticsearch Hybrid | 20 | 0.7013 | 0.6912 | Top1은 근접했지만 Avg@5는 BM25/Nori보다 낮았다. |
| 판례 검색 전체 | Elasticsearch Vector | 20 | 0.6597 | 0.6370 | 키워드 중심 법률 쟁점 검색에서는 상대적으로 낮았다. |
| 판례 검색 전체 | pgvector | 20 | 0.6134 | 0.5964 | 운영 baseline으로 쓰기에는 점수가 가장 낮았다. |
| 심의사례 검색 | Elasticsearch BM25/Nori | 5 | 0.7277 | 0.7115 | Top1 기준으로 가장 높고 Chart Hit도 100%였다. |
| 심의사례 검색 | Elasticsearch Hybrid | 5 | 0.7149 | 0.7221 | Avg@5는 가장 높지만 Top1은 BM25/Nori보다 낮았다. |

간단히 해석하면 다음과 같다.

```text
판례 검색에서는 BM25+Nori가 전체 평균 기준으로 가장 안정적이었다.
심의사례 검색에서도 BM25+Nori는 Top1 기준이 가장 높고, 기대 기준표 hit도 유지했다.
Hybrid는 일부 지표에서 좋았지만 운영 복잡도가 더 크기 때문에,
V1/V2 운영 baseline은 BM25+Nori로 두는 것이 합리적이다.
### Hybrid를 운영 baseline으로 두지 않은 이유

Hybrid는 일부 Avg@5 지표에서 좋았지만, 운영에 넣으려면 다음 요소가 추가된다.

```text
query embedding 생성
vector index 관리
BM25 score와 vector score fusion
source별 score 해석
embedding model/version 관리
```

다만 현재는 latency나 비용을 정량 비교한 단계는 아니다. 그래서 “시간/비용 때문에 제외했다”고 단정하면 안 된다.

정확한 표현은 다음과 같다.

```text
현재는 latency/cost 정량 비교까지 한 것은 아니고,
검색 품질 평가와 구현 복잡도를 기준으로 BM25+Nori를 운영 baseline으로 선택했습니다.
```

### Reranker 점수를 사용한 이유

pgvector, BM25, hybrid는 원래 점수 체계가 다르다.

```text
BM25
-> 키워드 기반 relevance score

pgvector
-> embedding cosine similarity 또는 distance

hybrid
-> BM25와 vector 결과를 조합한 score
```

그래서 BM25 점수와 cosine similarity를 숫자로 직접 비교하면 안 된다.

이를 보완하기 위해 같은 reranker 모델로 query-document 관련성을 다시 평가했다.

```text
각 retriever가 후보를 가져옴
-> 같은 reranker가 query + chunk_text를 다시 평가
-> local_reranker_score 기준으로 비교
```

즉 reranker 점수는 검색기별 raw score를 직접 비교하기 위한 것이 아니라, 서로 다른 검색기의 후보 품질을 같은 기준으로 다시 평가하기 위한 것이다.

### 임베딩 모델 A/B 테스트 여부

임베딩 모델 자체의 A/B 테스트는 진행하지 않았다.

이번 실험에서 고정한 임베딩 모델은 다음이다.

```text
embedding model = text-embedding-3-small
dimension = 1536
```

우리가 비교한 것은 임베딩 모델 종류가 아니라 검색 방식이다.

```text
비교한 것:
pgvector
Elasticsearch BM25/Nori
Elasticsearch vector
Elasticsearch hybrid

비교하지 않은 것:
text-embedding-3-small vs text-embedding-3-large
OpenAI embedding vs bge-m3 embedding
1536 dimension vs 3072 dimension
다른 한국어 embedding model
```

따라서 이번 실험은 “검색 방식 A/B”이고, “임베딩 모델 A/B”는 아니다.

임베딩 모델을 하나로 고정한 이유는 변수를 줄이기 위해서다.

```text
검색 방식도 바꾸고 embedding model도 바꾸면
어떤 요인 때문에 결과가 좋아졌는지 해석하기 어렵다.

따라서 V1/V2에서는 text-embedding-3-small을 기준 embedding으로 고정하고,
검색 방식과 Agent output 구조를 먼저 검증했다.
```
```

## 4. 현재 Agent가 사용하는 근거 source

현재 V2 Agent에서 실제 active source는 2개다.

```text
review_case
-> 과실비율 심의사례
-> 보험 실무와 유사 사고 판단에 가까움

fault_ratio_precedent
-> 과실비율 관련 판례
-> 법원의 과실상계, 손해배상, 책임제한 판단 근거에 가까움
```

두 source를 함께 검색하는 이유는 다음과 같다.

```text
심의사례만 보면 보험 실무 근거는 강하지만 법적 판단 근거가 약할 수 있다.
판례만 보면 법적 근거는 강하지만 실제 보험 과실비율 유사사례와 거리가 있을 수 있다.
따라서 두 근거를 같이 보여줘야 사용자와 Supervisor가 균형 있게 판단할 수 있다.
```

발표에서는 아래처럼 설명하면 된다.

```text
심의사례는 보험 실무에서 유사한 사고가 어떻게 판단되는지 보여주고,
판례는 법원이 과실상계나 책임제한을 어떻게 판단했는지 보여줍니다.
두 근거를 함께 제공해야 사용자가 실무적 관점과 법적 관점을 같이 볼 수 있습니다.
```$([Environment]::NewLine)
### source quota를 5+5로 둔 이유

V2 Agent는 심의사례와 과실비율 판례를 함께 보여주는 것이 목적이다.

만약 전체 점수만으로 top_k를 합치면 한 source가 결과를 독점할 수 있다.

그래서 현재 V2에서는 source별 quota를 사용한다.

```text
review_case 최대 5개
fault_ratio_precedent 최대 5개
final_top_k = 10
```

이 방식의 목적은 다음이다.

```text
심의사례와 판례를 모두 보여준다.
source별 근거 수를 해석하기 쉽다.
Supervisor가 보험 실무 근거와 법원 판례 근거를 구분해서 사용할 수 있다.
```

PM님이 질문을 받으면 이렇게 답변하면 된다.

```text
심의사례와 판례 중 한쪽이 결과를 독점하지 않도록 source quota를 두었습니다.
현재는 review_case 5개, fault_ratio_precedent 5개를 합쳐 최종 10개 근거를 반환합니다.
```

---


## 5. 청크 단위는 어떻게 잡았는가

청크는 임의 길이로 자른 것이 아니라, source별 문서 구조에 맞춰 “검색과 답변 근거로 의미가 있는 단위”로 나누었다.

핵심 기준은 다음이다.

```text
문서 전체를 한 번에 검색하지 않는다.
사고 개요, 주장, 쟁점, 판단 이유, 본문 근거처럼 역할이 다른 정보는 chunk_type으로 분리한다.
검색용 문장(search_text)과 실제 근거 문장(chunk_text)은 따로 관리한다.
```

### 심의사례 review_case 청크 단위

심의사례는 사건 1건마다 아래 4개 chunk를 만들었다.

| chunk_type | 실제 포함 내용 | 이 단위로 나눈 이유 |
|---|---|---|
| `case_overview` | 심의번호, 사고분류, 사례명, 참고기준 키워드, 신호조건, 도로특징, A/B 행동, 결정비율, 사고내용 | 사용자의 사고 상황과 유사한 사례를 먼저 찾기 위한 요약 단위 |
| `arguments` | 청구인 주장, 피청구인 주장 | 양측 주장이 쟁점인 질문에서 비교 근거로 쓰기 위한 단위 |
| `evidence_issue` | 입증자료, 주요쟁점 | 블랙박스, 신호, 충돌위치 등 증거와 쟁점 중심 질문에 대응하기 위한 단위 |
| `decision` | 결정근거, 결정이유, 최종비율 | 최종 판단 이유와 비율 근거를 답변에 쓰기 위한 단위 |

실제 생성 규모는 다음과 같다.

```text
review_case_documents = 226건
사건당 chunk = 4개
총 review_case_chunks = 904개

case_overview = 226
arguments = 226
evidence_issue = 226
decision = 226
```

이렇게 나눈 근거는 질문 의도별로 필요한 근거가 다르기 때문이다.

```text
사고상황이 비슷한 사례를 찾는 질문
-> case_overview가 유리

상대방 주장이나 보험사 주장과 비교하는 질문
-> arguments가 유리

블랙박스, 신호, 충돌위치, 입증자료가 중요한 질문
-> evidence_issue가 유리

왜 그런 과실비율이 나왔는지 묻는 질문
-> decision이 유리
```

따라서 심의사례 chunk는 “한 사건을 여러 의미 단위로 쪼개서 검색하는 구조”다.

### 심의사례 chunk가 실제 데이터에서 쓰인 방식

심의사례는 처음 계획부터 `section chunk` 방식으로 잡았다.

일반적인 RAG처럼 본문을 1000자, 1500자 단위로 기계적으로 자른 것이 아니라, 심의사례 데이터가 이미 가지고 있는 의미 구조를 기준으로 나눴다.

```text
심의사례 1건
-> case_overview
-> arguments
-> evidence_issue
-> decision
```

이렇게 한 이유는 사용자 질문이 항상 같은 의도를 갖지 않기 때문이다.

| 사용자 질문 의도 | 필요한 chunk | 이유 |
|---|---|---|
| “내 사고와 비슷한 사례가 있나?” | `case_overview` | 사고내용, 신호조건, 도로특징, A/B 차량 행동이 중요 |
| “상대방 주장이 맞나?” | `arguments` | 청구인/피청구인 주장을 비교해야 함 |
| “블랙박스나 증거가 중요한가?” | `evidence_issue` | 입증자료와 주요 쟁점이 중요 |
| “왜 이 비율이 나왔나?” | `decision` | 결정근거, 결정이유, 최종비율이 중요 |

실제 구현은 아래 코드에서 확인된다.

```text
etl/fault_cases/src/review_case/preprocessing/chunker.py
```

`build_review_case_chunks(doc)` 함수가 심의사례 문서 1건을 받아서 아래 4개 chunk를 생성한다.

```text
chunk_id = {review_case_id}_{chunk_type}
chunk_type = case_overview / arguments / evidence_issue / decision
chunk_text = 각 section의 실제 근거 문장
decision_fault_ratio = 결정 과실비율
reference_chart_key = 연결 기준표 key
source_ref = 원천 심의사례 출처
```

즉, chunk는 검색 결과의 최소 단위이면서 동시에 Agent가 Supervisor에게 넘길 근거 단위다.

실제 적재 결과도 계획과 일치했다.

```text
review_case_documents = 226건
사건당 RAG chunk = 4개
review_case_chunks = 904개

case_overview = 226개
arguments = 226개
evidence_issue = 226개
decision = 226개
```

여기서 중요한 점은 `review_case_source_chunks`와 `review_case_chunks`를 구분했다는 것이다.

두 테이블은 이름이 비슷하지만 역할이 다르다.

| 구분 | 목적 | 실제 사용 |
|---|---|---|
| `review_case_source_chunks` | 원문/PDF 추적용 | 파싱 오류나 원문 확인이 필요할 때 사용. 일부 원문은 fixed size split 가능 |
| `review_case_chunks` | 실제 RAG 검색용 | 우리가 말하는 4개 section chunk. Elasticsearch, pgvector, Agent evidence에 사용 |

정리하면 다음과 같다.

```text
review_case_source_chunks
-> 원문/PDF 추적용
-> 일부 fixed size split 가능
-> RAG 답변 근거의 주 단위가 아님

review_case_chunks
-> 실제 RAG 검색용
-> 사건당 case_overview / arguments / evidence_issue / decision 4개 section chunk
-> Agent가 evidence로 사용하는 주 단위
```

그래서 발표에서는 이렇게 말하면 된다.

```text
심의사례는 원문 추적용 chunk와 RAG 검색용 chunk를 분리했습니다.
원문 추적용 chunk는 PDF 파싱 검증을 위해 남겨두고,
실제 Agent 검색에는 사건당 4개 section chunk를 사용했습니다.
이 구조 덕분에 사용자의 질문 의도에 따라 사고 개요, 당사자 주장, 증거/쟁점, 결정이유 중 필요한 근거를 더 정확히 회수할 수 있습니다.
```

또 하나 중요한 설계는 `chunk_text`와 `search_text`를 분리한 것이다.

```text
chunk_text
-> 실제 사용자에게 보여줄 근거 문장

search_text
-> 검색 성능을 높이기 위해 chunk_type label, 사고유형, 신호조건, 도로특징, 과실비율, 기준표 key 등을 보강한 검색용 문장
```

`search_text` 구성은 아래 설정 파일에서 관리한다.

```text
etl/fault_cases/src/review_case/db_loading/search_text_config.py
```

예를 들어 `case_overview`에는 사고내용, 기본 과실비율, 기준표 원문이 검색 필드로 들어가고, `decision`에는 결정근거, 결정이유, 최종비율이 검색 필드로 들어간다.

이렇게 한 이유는 분명하다.

```text
사용자에게 보여줄 문장은 원문 근거에 가까워야 한다.
하지만 검색은 사고유형, 기준표 key, 과실비율, 도로/신호 조건 같은 보강 정보가 있어야 더 잘 맞는다.
그래서 보여주는 문장과 검색용 문장을 분리했다.
```

고정 길이 window chunk를 쓰지 않은 이유도 있다.

심의사례 계획 문서 기준으로 현재 데이터는 section chunk 길이가 검색에 부담될 정도로 길지 않았다.

```text
case_overview 평균 약 278자
arguments 평균 약 281자
evidence_issue 평균 약 218자
decision 평균 약 638자
1500자를 넘는 chunk 없음
```

그래서 현재 심의사례 데이터에서는 `1500/250` 같은 고정 window split을 쓰지 않고 section chunk를 유지했다.

추가 분할을 실제로 하지 않은 이유는 다음과 같다.

```text
현재 심의사례 chunk 길이가 충분히 짧았음
1500자를 넘는 chunk가 없어서 추가 분할 필요가 없었음
```

만약 추후 긴 심의사례가 추가된다면, 단순 글자 수 기준으로 자르는 것보다 section 내부 의미 기준으로 나누는 편이 더 적합하다.

```text
추후 긴 심의사례가 들어올 경우:
글자 수 기준으로 중간을 자르는 방식은 지양
section 내부 의미 기준 분할을 우선 검토
```

다만 현재 구현에서는 내부 추가 분할을 하지 않았다.

```text
짧고 구조화된 심의사례
-> section chunk 유지

긴 본문 중심 판례
-> 본문/판결요지/과실비율 근거 등 판례 구조에 맞춘 별도 chunk
```

정리하면 심의사례 chunk 설계의 핵심은 이것이다.

```text
심의사례는 226건을 그대로 문서 단위로 검색하지 않고,
사건당 4개 의미 단위로 나눠 904개 RAG chunk를 만들었다.
이 chunk는 사용자 질문 의도별로 필요한 근거를 찾기 위한 검색 단위이며,
Agent가 Supervisor에게 evidence로 넘기는 근거 단위이기도 하다.
```

### 과실비율 판례 fault_ratio_precedent 청크 단위

판례는 심의사례처럼 정형화된 4칸 구조가 아니기 때문에, 판례 원천 필드와 분류 결과를 기준으로 chunk_type을 나누었다.

| chunk_type | 실제 포함 내용 | 이 단위로 나눈 이유 |
|---|---|---|
| `case_overview` | 사건명, 사건번호, 법원, 선고일, 사건분류, 판단유형, 교통사고/과실비율 라벨 | 판례가 어떤 사건인지 빠르게 식별하기 위한 메타 요약 단위 |
| `fault_ratio_metadata` | 과실비율 관련 신호어, 명시 표현, 당사자 과실 표현, 손해/주의의무 관련 term | 과실비율 쟁점이 있는 판례를 키워드 기반으로 찾기 위한 단위 |
| `holding_summary` | 판시사항, 판결요지 | 법원의 핵심 판단 요지를 검색하고 보여주기 위한 단위 |
| `fault_ratio_evidence` | 과실비율 관련 term과 본문 주변 snippet | 과실상계, 손해배상, 책임제한 등 실제 비율 판단 근거를 찾기 위한 단위 |
| `main_text` | 판례 본문 | 요약/메타데이터에 잡히지 않는 본문 근거를 찾기 위한 단위 |
| `law_reference` | 참조법령, 참조판례 | 법령 또는 다른 판례 연결 근거를 보존하기 위한 단위 |

판례 chunk에서 특히 중요한 점은 `fault_ratio_evidence`다.

```text
main_text 전체를 그대로 한 덩어리로 쓰지 않고,
과실상계/책임제한/손해배상 등 관련 term 주변 본문 snippet을 별도 chunk로 구성했다.
```

이렇게 한 이유는 판례 본문이 길기 때문이다.

```text
판례 본문 전체를 검색하면 관련 없는 문단이 함께 섞일 수 있다.
반대로 과실비율 관련 표현 주변을 따로 뽑으면 실제 판단 근거에 가까운 chunk를 회수할 가능성이 높아진다.
```

### search_text와 chunk_text를 분리한 이유

각 chunk에는 `chunk_text`와 `search_text`를 함께 둔다.

```text
chunk_text
-> 사용자에게 근거로 보여줄 실제 문장

search_text
-> 검색 품질을 높이기 위해 label, keyword, metadata를 보강한 검색용 문장
```

이렇게 분리한 이유는 다음과 같다.

```text
사용자에게 보여줄 문장은 자연스럽고 원문 근거에 가까워야 한다.
하지만 검색은 사고유형, 쟁점, 기준표 key, 과실비율 label 같은 보강 정보가 있을수록 잘 된다.
따라서 보여주는 문장과 검색용 문장을 분리했다.
```


이 청크 단위의 실제 근거 파일은 다음이다.

| 구분 | 경로 | 확인할 수 있는 내용 |
|---|---|---|
| 심의사례 chunk 생성 코드 | `etl/fault_cases/src/review_case/preprocessing/chunker.py` | `case_overview`, `arguments`, `evidence_issue`, `decision` 4개 chunk 생성 로직 |
| 심의사례 search_text 설정 | `etl/fault_cases/src/review_case/db_loading/search_text_config.py` | chunk_type별 검색 label과 검색 필드 설정 |
| 심의사례 청크 계획/검증 문서 | `etl/fault_cases/Fault_cases_MD/심의사례/심의사례_DB_청크_평가_상세_계획.md` | 226건 x 4개 = 904 chunk, chunk_type별 길이/검증 기준 |
| 판례 chunk 생성 코드 | `etl/fault_cases/src/traffic_precedents/precedent_chunking/text_builder.py` | `case_overview`, `traffic_metadata`, `fault_ratio_metadata`, `holding_summary`, `fault_ratio_evidence`, `main_text`, `law_reference` 생성 로직 |
| 판례 보강 context 코드 | `etl/fault_cases/src/traffic_precedents/precedent_search/evaluation/augment_answer_contexts.py` | metadata chunk가 top1일 때 `holding_summary`, `main_text`, `fault_ratio_evidence`를 보강 근거로 붙이는 규칙 |
발표에서는 아래처럼 말하면 된다.

```text
청크는 단순히 글자 수로 자른 것이 아니라, 심의사례는 사건당 사고개요/주장/쟁점/결정 4개 단위로 나눴고,
판례는 사건개요, 판결요지, 과실비율 근거, 본문, 참조법령처럼 판례 구조에 맞춰 나눴습니다.
이렇게 한 이유는 질문 의도에 따라 필요한 근거가 다르기 때문입니다.
사고가 비슷한지 볼 때는 개요 chunk가 필요하고, 왜 그런 비율이 나왔는지 볼 때는 decision이나 fault_ratio_evidence chunk가 필요합니다.
```

---

## 6. 교통사고사실확인원 OCR은 어떻게 연결할 예정인가

현재 Agent input schema에는 `ocr_evidence`를 받을 수 있는 구조가 이미 있다.

예상되는 OCR source는 다음과 같다.

```text
교통사고사실확인원 이미지
-> OCR
-> 사고 일시, 장소, 사고 유형, 사고 원인, 차량 정보, 사고 설명 추출
-> Agent input의 ocr_evidence로 전달
```

이 OCR 정보가 들어오면 Agent는 단순히 사용자가 적은 문장만 보는 것이 아니라, 공식 문서에서 추출한 사고 정보까지 함께 참고할 수 있다.

예상 효과는 다음과 같다.

```text
1. 사용자가 사고 설명을 짧게 입력해도 OCR 정보로 검색문을 보강할 수 있다.
2. 사고 장소, 사고 유형, 사고 원인 같은 구조화된 정보를 검색에 활용할 수 있다.
3. Supervisor가 답변할 때 “현재 확인된 공식 문서상 정보”와 “추가 확인이 필요한 정보”를 구분할 수 있다.
```

현재 상태는 다음과 같이 정리한다.

```text
현재:
ocr_evidence를 받을 수 있는 Agent 입력 구조는 준비됨

추후 진행:
교통사고사실확인원 이미지 OCR 파이프라인 구현
OCR 결과를 Agent input에 연결
OCR 기반 search_text 보강 로직 고도화
```

발표에서는 다음처럼 정리한다.

```text
현재는 사용자 입력과 RAG 근거를 중심으로 동작하지만,
추후 교통사고사실확인원 OCR을 연결하면 공식 문서의 사고 유형과 원인까지 검색에 반영할 수 있습니다.
```

---

## 7. 인정기준은 어떻게 연결할 예정인가

현재 V2에서는 인정기준 source가 active가 아니다.

```text
현재:
review_case = active
fault_ratio_precedent = active
standard = excluded
```

하지만 최종 과실비율 상담에서는 인정기준도 중요한 source다.

그럼에도 현재 V2에서 인정기준을 제외한 진짜 이유는 검색 기술 문제가 아니라 입력 정보 문제다.

인정기준은 단순히 “차로변경”, “후방추돌” 같은 키워드만으로 바로 적용하기 어렵다. 기본 과실비율과 수정 요소를 판단하려면 사고 장소, 도로 형태, 신호 여부, 차선 구조, 진입 방향, 일시정지 여부, 선진입 여부 같은 디테일한 도로상황이 필요하다.

현재 사용자 입력만으로는 이 정보를 안정적으로 받기 어렵다.

```text
인정기준 계산에 필요한 입력:
사고 장소/주소
도로 형태
신호 조건
차량 진행 방향
차선/교차로 구조
충돌 위치
일시정지/양보 여부
선진입 여부
수정 요소 적용 여부
```

특히 사고 장소나 도로상황을 안정적으로 받으려면 교통사고사실확인원 OCR 또는 별도 구조화 입력이 필요하다.

```text
현재 보류 이유:
인정기준 계산에는 디테일한 도로상황이 필요함
도로상황/주소를 안정적으로 받으려면 OCR 또는 구조화 입력이 필요함
현재 input schema만으로는 인정기준을 바로 적용하기에 정보가 부족함
따라서 인정기준은 V2 active source에서 제외하고 보류
```

인정기준 자체는 단순 문서 검색보다 관계 구조가 중요하다.

인정기준에서 실제로 표현해야 하는 관계는 다음과 같다.

```text
사고 유형
-> 기본 과실비율
-> 수정 요소
-> 가산/감산 사유
-> 관련 설명
```

그래서 인정기준을 나중에 연결한다면 Neo4j 기반 지식그래프가 적합할 수 있다.

```text
Neo4j를 검토하는 이유:
1. 사고 유형과 기준표 간 관계를 그래프로 표현할 수 있다.
2. 기본 과실비율과 수정 요소를 연결해서 탐색할 수 있다.
3. 단순 키워드 검색보다 “이 사고 유형에 연결된 기준”을 찾기 쉽다.
```

현재 상태와 추후 계획은 다음과 같다.

```text
현재:
인정기준은 V2 Agent active source에 포함하지 않음

추후 진행:
교통사고사실확인원 OCR 또는 구조화 입력 설계
주소/도로상황/신호조건/차량 진행방향 입력 방식 결정
인정기준 데이터 구조화
Neo4j 노드/관계 설계
사고 유형 기반 인정기준 탐색 RAG 구현
Agent output에 standard evidence 추가
```

발표에서는 다음처럼 정리한다.

```text
심의사례와 판례는 현재 BM25+Nori 기반으로 검색하고,
인정기준은 아직 active source에 넣지 않았습니다.
이유는 인정기준 적용에는 주소, 도로 형태, 신호 조건, 차량 진행 방향 같은 상세 입력이 필요한데,
현재는 이 입력을 안정적으로 받을 OCR/구조화 입력 설계가 더 필요하기 때문입니다.
추후 교통사고사실확인원 OCR과 입력 스키마가 정리되면 인정기준 데이터를 Neo4j 같은 관계 구조로 연결하는 방식을 검토할 예정입니다.
```

---

## 8. 전체 source 확장 방향

최종적으로는 아래 흐름을 목표로 한다.

```text
사용자 사고 설명
+ 교통사고사실확인원 OCR
+ 보험사 주장
+ 영상/이미지 분석 결과
-> text_ml_case_search Agent
-> 심의사례 RAG
-> 과실비율 판례 RAG
-> 인정기준 Neo4j RAG
-> Supervisor용 근거 JSON 반환
```

source별 역할은 다음과 같다.

| source | 현재 상태 | 역할 |
|---|---|---|
| `review_case` | active | 보험 실무상 유사 심의사례 근거 |
| `fault_ratio_precedent` | active | 법원 판례상 과실상계/책임제한 근거 |
| `ocr_evidence` | input 구조 준비 | 교통사고사실확인원 기반 사고 정보 보강 |
| `standard` | 추후 예정 | 인정기준, 기본 과실비율, 수정 요소 탐색 |
| `traffic_precedent` | 별도 RAG/Search 검증 | 일반 교통사고 법률 쟁점 판례 검색 |

---

## 9. text_ml_case_search Agent의 최종 역할

최종 역할은 다음 한 줄로 정리할 수 있다.

```text
text_ml_case_search Agent는 사용자의 사고 설명을 기반으로
심의사례와 과실비율 판례를 검색하고,
추후 OCR 및 인정기준까지 확장하여
Supervisor가 바로 사용할 수 있는 근거 JSON으로 정리하는 Agent다.
```

Supervisor가 주로 사용하는 output은 다음이다.

```text
display_evidence
similar_cases
ratio_range_label
insurer_claim_review
recommended_evidence
source_summary
limitations
next_actions
```

주의할 점은 `ratio_range_label`이 확정 과실비율이 아니라는 것이다.

```text
ratio_range_label
-> 검색된 심의사례/판례 근거에서 참고 가능한 비율 범위
-> 최종 법적 판단 또는 확정 과실비율 아님
```
### 보험사 주장은 어떻게 쓰는가

보험사 주장은 확정 사실로 보지 않는다.

사용자가 입력한 보험사 과실비율 주장은 비교 대상 주장으로만 취급한다.

```text
insurer_claim
-> 사용자 입력 기반 보험사 주장
-> 확정 사실 아님
-> RAG 근거와 비교할 쟁점으로만 사용
```

Agent는 보험사 주장을 바로 반박하거나 확정하지 않는다.

대신 다음 정보를 정리한다.

```text
보험사 주장 요약
보험사 주장의 주요 쟁점
RAG 근거와 비교할 포인트
추가로 확인해야 할 자료
한계사항
```

보험사 주장이 없는 경우에는 `insurer_claim_review`가 비어 있거나 제한적으로 생성된다.

---

## 10. 교통사고 일반판례 RAG를 별도로 둔 이유

교통사고 일반판례 RAG는 과실비율을 바로 산정하기 위한 Agent가 아니다.

목적은 다음과 같다.

```text
교통사고 상황에서 운전자 주의의무, 형사책임, 교통법규 위반, 사고 후 조치의무 같은
일반 법률 쟁점에 맞는 판례 후보를 검색하는 것
```

현재는 별도 Agent로 붙이지 않고 RAG/Search 단계까지만 구현했다.

이유는 다음과 같다.

```text
1. 교통사고 일반판례는 과실비율 Agent의 최종 active source가 아직 아니다.
2. 먼저 BM25+Nori 검색만으로 적절한 판례가 잡히는지 확인해야 한다.
3. 검색 품질이 검증된 뒤 Supervisor 또는 법률 Agent와 연결하는 것이 안전하다.
4. 과실비율 심의사례/판례와 역할이 다르므로 바로 섞으면 출력 의미가 흐려질 수 있다.
```

---

## 11. PM 발표 참고용 최종 요약 문장

```text
기존 검색은 문자열이 맞는 판례나 사례를 가져오는 수준이었다면,
이번 Agent/RAG는 사용자의 사고 상황을 정리하고,
그 사고에 맞는 심의사례와 판례를 출처별로 가져온 뒤,
Supervisor가 최종 답변에 바로 사용할 수 있는 근거 구조로 변환합니다.
```

```text
BM25+Nori를 사용한 이유는 교통사고와 과실비율 판단에서
차로변경, 신호위반, 과실상계 같은 한국어 법률 키워드 매칭이 중요하기 때문입니다.
```

```text
현재는 심의사례와 과실비율 판례를 중심으로 구현했고,
인정기준은 바로 붙이지 않았습니다.
인정기준 적용에는 주소, 도로 형태, 신호 조건, 진행 방향 같은 상세 입력이 필요하기 때문에
추후 교통사고사실확인원 OCR과 구조화 입력 설계가 정리된 뒤 연결을 검토할 예정입니다.
```


