# 판례 임베딩 A/B 정답지 50개 작성·재검수 보고서

## 1. 결과

공통 사용자 사고 Query 50개 전부에 대해 판례 전용 Ground Truth를 작성했다.

| 항목 | 결과 |
|---|---:|
| 고유 Query | 50 |
| qrels 행 | 58 |
| relevance 1 이상 판례가 있는 Query | 34 |
| relevance 2 이상 직접 정답이 있는 Query | 21 |
| relevance 1 참고 판례만 있는 Query | 13 |
| `no_relevant_document` Query | 16 |
| 사건-청크 판정 | 42 |
| 서로 다른 관련 판례 | 31 |
| relevance 3 | 14 |
| relevance 2 | 13 |
| relevance 1 | 15 |

정답지 파일은 다음과 같다.

```text
etl/fault_cases/evaluation/precedent/embedding_ab/v1/ground_truth/precedent_qrels_v1.jsonl
```

이 파일은 심의사례 qrels와 같이 판정 1건당 한 행인 flat 구조를 사용한다. 관련 판례가 여러 개면 같은 `query_id`가 사건·대표 청크별로 반복되고, 관련 판례가 없으면 `judgment_status=no_relevant_document`인 행 하나를 기록한다.

## 2. 파일 역할

이 보고서는 정답지 작성 방법과 검증 결과를 기록한다. Query별 판정과 사실관계 해설은 `precedent_qrels_v1_해설.md`에서 확인한다. 정답지를 변경할 때마다 manifest의 qrels 통계와 SHA-256도 함께 갱신한다.

## 3. 작성 방법

특정 임베딩 모델 결과를 보지 않고 다음 순서로 후보를 만들었다.

```text
1. 최신 ready 판례 987건과 v2 청크 8,334개 고정
2. 문자 n-gram TF-IDF로 Query당 상위 30개 사건 후보 생성
3. issue_tags를 후보 생성 텍스트에 보조 가중
4. 유턴, 점멸신호, 도로진입 등 핵심 관계를 전체 청크에서 규칙 검색
5. 판례 원문과 대표 청크를 읽고 relevance 1~3을 등급 판정
6. relevance 1 이상 판례도 없으면 no_relevant_document로 명시
```

OpenAI, BGE-M3, Qwen3, E5의 검색 결과는 후보 생성이나 판정에 사용하지 않았다. 따라서 정답지가 특정 A/B 대상 모델에 유리해지는 누출을 피했다.

## 4. 파일럿 반영

파일럿 10개도 정식 50개 안에 포함했다. 외부 검수 의견 중 q11의 대표 청크 수정은 반영했다.

| Query | case_id | 파일럿 청크 | full 반영 청크 |
|---|---|---|---|
| q11 | 117988 | `aeb14e0b1fcf` | `a369532e26b4` |
| q11 | 200812 | `e346d74936fe` | `0e6f1fea9e03` |

추가 사실관계 재검수에서 q11의 95다11832 대표 청크도 `49fdd8caf0dc`로 교체했다. q46은 보행자 신호가 Query와 반대임을 확인하여 relevance 1로 조정했다.

## 5. 사실관계 재검수 반영

진행축, 신호, 도로 폭, 정차 여부처럼 통행 우선관계를 바꾸는 차이를 부차적인 조건으로 처리하지 않았다. 이에 따라 q02, q03, q04, q05, q06, q11의 95다11832, q15, q23, q25, q36, q39의 2003다6873, q41, q42, q44, q46을 relevance 1로 조정했다. q11의 93다1466은 relevance 2를 유지하되 선진입 표현을 바로잡았다.

q09는 기존 부정 판정에서 누락된 `91다42883`을 찾아 relevance 2로 추가했다. 양 도로가 같은 폭이고 양 차량이 직진하며 상대 차량이 사용자 기준 오른쪽에서 진입한 관계는 일치하지만, 판례에서는 사용자 측 차량의 명확한 선진입이 핵심 판단요소다.

세부 근거와 대표 청크 선택 이유는 `precedent_qrels_v1_해설.md`에 기록했다.

## 6. 부정 판정 검수

`no_relevant_document` 16개는 검색 실패가 아니라 현재 판례 코퍼스에서 relevance 1 이상으로 남길 판례를 확인하지 못했다는 뜻이다.

```text
q07 q08 q17 q18 q19 q20 q22 q24
q30 q31 q32 q33 q34 q35 q49 q50
```

특히 복수 좌회전 차로, 동시 진로변경, 회전교차로, 주차장, 고속도로 합류, 자전거 전용차로, PM 유형은 판례 코퍼스가 희소하다. 심의사례나 인정기준에는 정답이 있더라도 판례 qrels에는 옮겨 넣지 않는다.

## 7. 검증 결과

```text
JSONL 파싱 오류: 0
공통 Query 누락: 0
공통 Query 외 ID: 0
고유 Query ID: 50
중복 Query-case-chunk 판정: 0
존재하지 않는 case_id: 0
존재하지 않는 chunk_id: 0
```

Hit와 MRR은 relevance 2 이상 직접 정답이 있는 21개 Query를 대상으로 한다. nDCG는 relevance 1 이상 판례가 있는 34개 Query에서 계산한다.

```text
nDCG gain = 2^relevance - 1
discount = 1 / log2(rank + 1)
unjudged document = relevance 0
같은 case_id는 검색순위가 가장 높은 결과 하나만 유지
```

`no_relevant_document` 16개는 표준 검색 지표와 분리하되 무시하지 않는다. strict positive 21개와 negative 16개의 Top-1 cosine similarity 분포, AUROC, AUPRC를 별도 보고한다. relevance 1만 있는 13개는 이 이진 진단에서 제외한다.

## 8. 다음 단계

1. 실제 pgvector 적재 청크와 qrels의 모든 `chunk_id`가 일치하는지 확인한다.
2. 평가 코드가 Hit/MRR 21개, nDCG 34개, weak-only 13개, 부정 16개를 분리하는지 검증한다.
3. Query/qrels SHA를 실험 입력값으로 동결한다.
4. 같은 정답지와 같은 pgvector 조건으로 5개 임베딩 모델을 실행한다.
5. 5개 모델의 negative Top-10 합집합을 블라인드 재검수하고, 누락 판례가 있으면 qrels를 갱신한 뒤 전 모델을 재평가한다.
