# 임베딩 고도화 및 Hybrid RAG 후속실험 정리

## 1. 문서 목적

이 문서는 현재 과실비율 Agent/RAG에서 임베딩이 어떤 역할을 하는지, 아직 진행하지 않은 임베딩 모델 A/B 테스트가 무엇인지, 그리고 추후 Hybrid RAG를 다시 검토할 때 어떤 기준으로 판단해야 하는지를 정리한 문서다.

현재 결론은 다음과 같다.

```text
현재 운영 baseline:
BM25+Nori

현재 임베딩 모델:
text-embedding-3-small
dimension = 1536

이미 진행한 실험:
검색 방식 A/B

아직 진행하지 않은 실험:
임베딩 모델 A/B
```

---

## 2. BM25+Nori와 임베딩의 차이

BM25+Nori는 임베딩을 사용하지 않는다.

```text
BM25+Nori
-> 키워드 기반 검색
-> 한국어 형태소 분석
-> embedding 없음
```

BM25는 검색어와 문서의 단어 매칭 강도를 계산한다. Nori는 한국어 문장을 검색 가능한 형태소 단위로 나누는 Elasticsearch 한국어 분석기다.

따라서 BM25+Nori는 아래처럼 정확한 사고/법률 키워드가 중요한 검색에 강하다.

```text
차로변경
신호위반
후방추돌
횡단보도
과실상계
손해배상
책임제한
```

반면 Vector search는 임베딩이 필요하다.

```text
Vector search
-> query를 embedding vector로 변환
-> 문서 chunk embedding과 유사도 비교
```

Hybrid는 두 방식을 합친 구조다.

```text
Hybrid = BM25+Nori + Vector search
```

정리하면 다음과 같다.

```text
BM25+Nori를 쓰려면 embedding이 필요 없음
Hybrid를 쓰려면 embedding이 필요함
Hybrid를 쓴다고 해서 embedding model을 반드시 바꿔야 하는 것은 아님
```

---

## 3. 현재 임베딩은 어디에 사용했는가

현재 사용한 임베딩 모델은 하나다.

```text
model = text-embedding-3-small
dimension = 1536
```

이 임베딩은 아래 실험에 사용했다.

```text
pgvector 검색
Elasticsearch vector 검색
Elasticsearch hybrid 검색
```

하지만 현재 운영 baseline인 BM25+Nori 자체에는 임베딩이 들어가지 않는다.

```text
현재 Agent 운영 baseline:
BM25+Nori 기반 검색

임베딩 사용 경로:
vector/hybrid 실험 경로
```

---

## 4. 우리가 이미 한 것은 검색 방식 A/B다

이미 진행한 비교는 임베딩 모델 비교가 아니라 검색 방식 비교다.

| 비교 대상 | 설명 |
|---|---|
| pgvector | 임베딩 기반 DB vector 검색 |
| Elasticsearch BM25/Nori | 한국어 형태소 분석 기반 키워드 검색 |
| Elasticsearch vector | Elasticsearch vector 검색 |
| Elasticsearch hybrid | BM25+Nori와 vector 검색 조합 |

즉 이번 실험의 질문은 다음이었다.

```text
같은 데이터와 같은 query에서
어떤 검색 방식이 더 안정적으로 관련 근거를 가져오는가?
```

실험 결과에서는 BM25+Nori가 운영 baseline으로 가장 안정적이었다.

```text
판례 검색:
BM25+Nori가 Avg Top1, Avg@5 모두 가장 안정적

심의사례 검색:
BM25+Nori가 Top1 기준 가장 높음
Hybrid는 Avg@5가 높았지만 Top1은 BM25+Nori보다 낮음
```

---

## 5. 아직 하지 않은 것은 임베딩 모델 A/B다

임베딩 모델 자체의 A/B 테스트는 아직 진행하지 않았다.

비교하지 않은 것은 다음과 같다.

```text
text-embedding-3-small vs text-embedding-3-large
OpenAI embedding vs bge-m3
1536 dimension vs 3072 dimension
다른 한국어/다국어 embedding model
```

따라서 현재 문서에서 정확한 표현은 다음이다.

```text
이번 실험은 검색 방식 A/B이다.
임베딩 모델 A/B는 아직 진행하지 않았다.
```

---

## 6. 임베딩 모델을 하나로 고정한 이유

임베딩 모델을 하나로 고정한 이유는 실험 변수를 줄이기 위해서다.

검색 방식과 임베딩 모델을 동시에 바꾸면 어떤 요인 때문에 결과가 좋아졌는지 해석하기 어렵다.

```text
검색 방식 변경
+ embedding model 변경
-> 결과가 좋아져도 원인 해석이 어려움
```

그래서 V1/V2에서는 `text-embedding-3-small`을 기준 embedding으로 고정하고, 먼저 검색 방식과 Agent output 구조를 검증했다.

---

## 7. Hybrid를 쓰려면 임베딩 모델을 바꿔야 하는가

반드시 바꿔야 하는 것은 아니다.

Hybrid를 사용하려면 embedding은 필요하지만, 현재처럼 `text-embedding-3-small`을 그대로 사용해도 Hybrid 검색은 가능하다.

다만 Hybrid 성능을 더 끌어올리고 싶다면 임베딩 모델을 바꿔서 비교할 수 있다.

```text
가능한 실험:
BM25+Nori
vs Hybrid(text-embedding-3-small)
vs Hybrid(text-embedding-3-large)
vs Hybrid(bge-m3 등 다른 embedding model)
```

즉 정확한 표현은 다음이다.

```text
Hybrid를 쓰려면 embedding이 필요하다.
하지만 Hybrid를 쓰기 위해 embedding model을 반드시 바꿔야 하는 것은 아니다.
embedding model 변경은 Hybrid 고도화 실험의 한 선택지다.
```

---

## 8. Hybrid가 BM25+Nori보다 유의미해지는 기준

예를 들어 BM25+Nori의 reranker 평균 점수가 0.70이고, 임베딩 모델을 바꾼 Hybrid가 0.77이 되었다고 가정한다.

```text
BM25+Nori = 0.70
Hybrid = 0.77

상대 개선율:
(0.77 - 0.70) / 0.70 = 10%
```

이 정도면 단순 오차로 보기 어렵고, Hybrid를 운영 후보로 다시 검토할 만한 차이다.

다만 reranker 점수 하나만으로 바로 운영 전환을 결정하면 안 된다.

함께 봐야 하는 기준은 다음이다.

```text
Avg Top1이 올랐는가
Avg@5가 올랐는가
Hit@5가 유지되거나 올랐는가
관련 없는 문서가 늘지 않았는가
특정 query에서만 좋아진 것이 아닌가
심의사례와 판례 모두에서 좋아졌는가
검색 시간이 감당 가능한가
운영 복잡도를 감수할 만큼 품질 차이가 큰가
```

판단 기준은 이렇게 잡을 수 있다.

| 개선 폭 | 해석 |
|---:|---|
| 0~3% | 오차 또는 query set 영향일 수 있어 운영 전환 근거로 약함 |
| 5% 내외 | 재검증할 가치 있음 |
| 10% 이상 | 다른 지표도 함께 좋아졌다면 운영 후보로 검토 가능 |

---

## 9. 후속 실험 설계

후속 실험의 핵심은 운영용 기존 index를 건드리지 않고, 실험용 index를 따로 만드는 것이다.

```text
운영용 기존 1536 dim index는 건드리지 않는다.
후속 실험용 1024 dim index를 따로 만든다.
비교표에는 현재 1536 dim 결과와 1024 dim 통일 실험 결과를 분리해서 기록한다.
```

이렇게 하는 이유는 모델 차이와 dimension 차이를 섞지 않기 위해서다.

```text
기존 1536 dim 결과
-> 현재 운영/기존 실험 baseline

1024 dim 통일 실험 결과
-> 후속 모델 비교용 실험 결과

두 결과를 분리 기록
-> dimension 차이인지, embedding model 차이인지 구분 가능
```

### 실험 index 분리 원칙

현재 `text-embedding-3-small`은 1536 dimension으로 사용했다.

이 index를 그대로 1024 dimension 실험에 쓰면 안 된다. vector index는 같은 field 안에서 dimension이 같아야 하기 때문이다.

```text
현재 운영/기존 실험 index:
text-embedding-3-small
1536 dim

후속 1024 통일 실험 index:
text-embedding-3-small dimensions=1024
text-embedding-3-large dimensions=1024
bge-m3 1024 dim
multilingual-e5-large 1024 dim
```

즉 1024 dimension 실험을 하려면 문서 chunk와 query를 모두 1024 dimension으로 다시 임베딩해야 한다.

```text
문서 chunk = 1536 dim
query = 1024 dim
-> 비교 불가능

문서 chunk = 1024 dim
query = 1024 dim
-> 비교 가능
```

### 비교 구조

비교는 두 묶음으로 나눠서 기록한다.

| 비교 묶음 | 목적 | 대상 |
|---|---|---|
| 기존 baseline | 현재 운영/기존 실험 결과 보존 | BM25+Nori, Hybrid(text-embedding-3-small 1536 dim) |
| 1024 통일 실험 | 모델별 embedding 성능 비교 | Hybrid(text-embedding-3-small 1024 dim), Hybrid(text-embedding-3-large 1024 dim), Hybrid(bge-m3 1024 dim), Hybrid(multilingual-e5-large 1024 dim) |

결과표도 아래처럼 분리한다.

| 구분 | Retriever | Embedding model | Dimension | Avg Top1 | Avg@5 | Hit@5 | 비고 |
|---|---|---|---:|---:|---:|---:|---|
| 기존 baseline | BM25+Nori | 없음 | 없음 | 기존값 | 기존값 | 기존값 | 운영 baseline |
| 기존 baseline | Hybrid | text-embedding-3-small | 1536 | 기존값 | 기존값 | 기존값 | 기존 hybrid 실험 |
| 1024 실험 | Hybrid | text-embedding-3-small | 1024 | 측정 | 측정 | 측정 | 같은 모델의 dimension 축소 영향 확인 |
| 1024 실험 | Hybrid | text-embedding-3-large | 1024 | 측정 | 측정 | 측정 | large 모델 성능 확인 |
| 1024 실험 | Hybrid | bge-m3 | 1024 | 측정 | 측정 | 측정 | 오픈소스 다국어 후보 |
| 1024 실험 | Hybrid | multilingual-e5-large | 1024 | 측정 | 측정 | 측정 | 오픈소스 다국어 후보 |

### 실험 조건

임베딩 모델 A/B를 한다면 아래 조건은 동일하게 맞춘다.

```text
같은 query set
같은 chunk set
같은 top_k
같은 reranker
같은 평가 지표
같은 보고서 포맷
```

단, dimension은 두 방식으로 분리해서 해석한다.

```text
1536 dim 결과
-> 현재 운영/기존 실험 baseline

1024 dim 결과
-> 후속 통일 비교 실험
```


### 점수 산출 방식

후속 임베딩 모델 비교의 점수 산출 방식은 기존에 `pgvector`, `BM25+Nori`, `Elasticsearch vector`, `Elasticsearch hybrid`를 비교했던 방식과 동일하게 유지한다.

핵심은 각 retriever의 raw score를 직접 비교하지 않는 것이다.

```text
각 retriever가 후보 chunk를 가져옴
-> 같은 query
-> 같은 top_k
-> 같은 chunk set
-> 같은 reranker로 query-document 관련성 재평가
-> local_reranker_score 기준으로 비교
```

이 방식을 유지하는 이유는 retriever마다 raw score 체계가 다르기 때문이다.

```text
BM25+Nori
-> BM25 relevance score

pgvector / vector search
-> cosine similarity 또는 distance

Hybrid
-> BM25 score와 vector score를 조합한 score
```

따라서 아래처럼 숫자를 직접 비교하면 안 된다.

```text
BM25 raw score 12.5
vs vector cosine similarity 0.82
vs hybrid score 0.64
-> 서로 의미가 달라 직접 비교 불가능
```

그래서 기존 실험과 동일하게 같은 reranker로 후보 품질을 다시 평가한다.

```text
기존 비교:
pgvector
BM25+Nori
Elasticsearch vector
Elasticsearch hybrid
-> 같은 reranker score로 비교

후속 비교:
Hybrid(text-embedding-3-small 1024)
Hybrid(text-embedding-3-large 1024)
Hybrid(bge-m3 1024)
Hybrid(multilingual-e5-large 1024)
-> 같은 reranker score로 비교
```

즉 후속 실험에서 바뀌는 것은 embedding model과 vector index이지, 평가 방식은 바꾸지 않는다.

PM님에게 설명할 때는 이렇게 말하면 된다.

```text
후속 임베딩 모델 비교도 기존 pgvector, BM25+Nori, Hybrid를 평가했던 방식과 동일하게 진행합니다.
각 검색기가 가져온 후보를 그대로 비교하지 않고,
같은 reranker로 query와 chunk의 관련성을 다시 점수화한 뒤 Avg Top1, Avg@5, Hit@5 기준으로 비교합니다.
그래야 BM25 점수와 vector similarity처럼 서로 다른 raw score 체계를 직접 비교하는 문제를 피할 수 있습니다.
```
### 평가 지표

평가 지표는 다음을 사용한다.

```text
Avg Top1 reranker score
Avg@5 reranker score
Hit@5
Noise count
source별 winner count
metadata chunk 과다 여부
응답 시간
재색인 비용
vector index 크기
```

특히 dimension을 낮추면 저장공간과 검색 속도는 좋아질 수 있지만, 정확도는 떨어질 수 있다.

따라서 최종 판단은 아래 기준으로 한다.

```text
정확도 차이가 크면:
더 정확한 dimension/model 선택

정확도 차이가 거의 없으면:
더 가볍고 운영 쉬운 dimension/model 선택
```

### 결과 보고서 구조

결과 보고서는 다음 구조가 적합하다.

```text
1. 기존 1536 dim baseline 결과
2. 1024 dim 통일 실험 결과
3. query별 winner
4. BM25+Nori가 이긴 query 유형
5. Hybrid가 이긴 query 유형
6. 1536 dim과 1024 dim 차이
7. embedding model별 장단점
8. 운영 전환 여부 판단
```
---

## 10. 현재 결론

현재는 임베딩 모델 A/B를 당장 진행하지 않아도 된다.

이유는 현재 `text_ml_case_search` Agent의 운영 baseline은 BM25+Nori이고, 현재 작업의 핵심은 검색 근거를 Supervisor가 사용할 수 있는 구조로 정리하는 것이기 때문이다.

현재 결론은 다음과 같다.

```text
현재:
BM25+Nori 운영 baseline 유지

임베딩 모델:
text-embedding-3-small 고정

임베딩 모델 A/B:
아직 미진행

후속 실험:
운영용 1536 dim index는 유지
1024 dim 통일 실험 index를 별도로 생성
1536 baseline과 1024 실험 결과를 분리 기록
```


### 후속 실험 폴더 구조 제안

`Fault_cases_MD`는 Markdown 문서만 모아두는 폴더로 유지한다.

따라서 이 폴더에는 실험 설명서, 비교표, 최종 요약처럼 사람이 읽는 `.md` 파일만 둔다. CSV, JSON, pickle, parquet, log 같은 실제 실험 산출물은 넣지 않는다.

추천 구조는 다음과 같다.

```text
etl/fault_cases/Fault_cases_MD/임베딩_고도화/
├─ 00_실험_개요.md
├─ 01_query_set_정리.md
├─ 02_index_설계.md
├─ 03_점수산출방식.md
├─ 04_모델별_결과요약.md
└─ 05_PM공유용_최종요약.md
```

실제 실험 코드와 원본 결과 파일은 Markdown 폴더가 아니라 별도 실험 폴더에 둔다.

```text
etl/fault_cases/experiments/embedding_hybrid/
├─ README.md
├─ configs/
├─ scripts/
├─ outputs/
│  ├─ baseline_1536/
│  ├─ experiment_1024/
│  └─ final_tables/
└─ logs/
```

역할을 나누면 다음과 같다.

| 위치 | 저장 대상 | 예시 |
|---|---|---|
| `Fault_cases_MD/임베딩_고도화/` | 사람이 읽는 Markdown 문서 | 실험 개요, index 설계, 결과 요약, PM 공유용 정리 |
| `experiments/embedding_hybrid/` | 실제 실험 코드와 산출물 | 실행 script, config, CSV/JSON 결과, raw output, log |

즉 문서와 산출물을 분리한다.

```text
문서:
Fault_cases_MD/임베딩_고도화/*.md

실험 코드/결과:
etl/fault_cases/experiments/embedding_hybrid/
```

이렇게 분리하면 `Fault_cases_MD`의 목적을 유지하면서도, 후속 실험 결과를 체계적으로 관리할 수 있다.

PM님에게 공유할 때는 `Fault_cases_MD/임베딩_고도화/05_PM공유용_최종요약.md`만 전달하면 되고, 개발자가 재현해야 할 때는 `experiments/embedding_hybrid/`를 보면 된다.

---|---|
| `00_실험_개요.md` | 실험 목적, 비교 대상, 결론 요약 |
| `01_query_set.md` | 기존 평가 query와 추가 query 목록 |
| `02_index_설계.md` | 1536 운영 index와 1024 실험 index 분리 구조 |
| `03_모델별_실험결과.md` | 모델별 상세 결과 |
| `04_최종_비교_요약.md` | PM/팀 공유용 최종 요약 |

현재 문서는 전체 방향을 정리하는 상위 문서로 두고, 실제 실험을 시작할 때 위 폴더를 새로 만들어 산출물을 쌓는 방식이 좋다.

```text
현재 문서:
임베딩_고도화_및_Hybrid_RAG_후속실험_정리.md
-> 방향성과 판단 기준 정리

추후 실험 폴더:
임베딩_고도화/
-> 실제 query set, index 설계, 모델별 결과, 최종 비교표 저장
```

이렇게 분리하면 운영 baseline 문서와 실험 결과 문서가 섞이지 않고, 나중에 PM님에게 공유할 때도 `04_최종_비교_요약.md`만 따로 전달할 수 있다.
PM님에게 설명할 때는 이렇게 정리하면 된다.

```text
현재는 임베딩 모델을 바꿔가며 비교한 것이 아니라,
text-embedding-3-small을 기준으로 고정하고 검색 방식 A/B를 먼저 진행했습니다.
BM25+Nori가 운영 baseline으로 충분히 안정적이었기 때문에,
임베딩 모델 A/B는 후속 고도화 실험으로 남겨두었습니다.
다만 후속 실험에서는 운영용 1536 dim index를 건드리지 않고,
1024 dim 통일 비교용 실험 index를 별도로 만들어 비교합니다.
이때 1536 baseline 결과와 1024 실험 결과를 분리 기록하고,
Top1, Hit@5, reranker score에서 충분한 개선이 확인되면
Hybrid를 운영 검색 방식으로 재검토할 수 있습니다.
```

---

## 11. 임베딩 모델 비교 후보

아래 표는 현재 사용 중인 `text-embedding-3-small`과, 추후 Hybrid RAG 고도화 실험에서 비교할 만한 임베딩 모델 후보를 정리한 것이다.

가격은 2026-07 기준으로 정리했으며, API 가격은 변동될 수 있다. 오픈소스 모델은 모델 사용료 자체는 없지만, 직접 운영할 경우 GPU 서버/추론 인프라 비용이 발생한다.

| 모델 | 유형 | 대략 가격/운영비 | 한국어 적합성 | 속도/운영 난이도 | 정확도 기대 | 차원/입력 길이 | 장점 | 한계 | 실험 우선순위 |
|---|---|---|---|---|---|---|---|---|---|
| `text-embedding-3-small` | OpenAI API | 약 `$0.02 / 1M tokens` 수준 | 보통~좋음 | 빠름, 운영 쉬움 | 기준선 | 1536 dim / max 8192 tokens | 현재 사용 중이라 비교 기준으로 적합. 비용 낮고 API 운영이 단순함 | 한국어 법률/보험 도메인 특화 모델은 아님 | 현재 baseline |
| `text-embedding-3-large` | OpenAI API | 약 `$0.13 / 1M tokens` 수준 | 좋음 | `small`보다 느리고 비쌈, 운영은 쉬움 | `small`보다 높을 가능성 | 3072 dim / max 8192 tokens | OpenAI 계열에서 가장 먼저 비교하기 좋은 상위 후보. dimension 축소 옵션도 있음 | 비용, 저장공간, 색인 크기 증가 | 1순위 |
| `BAAI/bge-m3` | 오픈소스 self-host | 모델 비용 없음. GPU/서버 비용 발생 | 좋음 | 직접 서빙 필요. GPU 권장 | 높을 가능성 | 1024 dim / max 8192 tokens | 다국어, long text, dense/sparse/multi-vector 지원. Hybrid 검색 실험과 궁합이 좋음 | 운영 복잡도 증가. 서버/배포/모니터링 필요 | 1~2순위 |
| `intfloat/multilingual-e5-large` | 오픈소스 self-host | 모델 비용 없음. GPU/서버 비용 발생 | 좋음 | 직접 서빙 필요. 입력 prefix 규칙 필요 | 높을 가능성 | 1024 dim / max 512 tokens | 다국어 검색 성능이 검증된 대표 모델. 한국어 포함 다국어 검색 비교 후보로 적합 | 긴 chunk는 512 token 제한에 걸릴 수 있음. `query:`/`passage:` prefix 관리 필요 | 2순위 |
| `text-embedding-ada-002` | OpenAI API legacy | 약 `$0.10 / 1M tokens` 수준 | 보통 | 운영 쉬움 | 최신 모델 대비 낮음 | 1536 dim / max 8192 tokens | 과거 baseline 비교용으로만 의미 있음 | 현재 신규 고도화 후보로는 매력이 낮음 | 낮음 |
| `Cohere Embed 4` | 상용 API/전용 배포 | 공개 API 과금 또는 전용 배포 비용 확인 필요 | 좋을 가능성 | API면 쉬움, 전용 배포면 복잡 | 높을 가능성 | 제품 설정에 따라 확인 필요 | 검색/검색증강용 상용 모델 후보. 엔터프라이즈 배포 옵션 있음 | 가격/계약/배포 방식 확인 필요 | 보류 |

### 모델별 해석

현재 가장 현실적인 비교 순서는 다음과 같다.

```text
1. text-embedding-3-small
   -> 현재 기준선

2. text-embedding-3-large
   -> 같은 OpenAI 계열이라 코드 변경과 운영 부담이 가장 작음

3. BAAI/bge-m3
   -> Hybrid 검색 고도화 후보로 가장 흥미로움
   -> dense + sparse + multi-vector 구조를 지원해서 BM25+Vector 조합과 비교 가치가 있음

4. multilingual-e5-large
   -> 다국어 검색 성능 검증용 후보
   -> 다만 max 512 token 제한과 prefix 규칙 때문에 전처리 관리가 필요함
```

### 가격 관점 정리

가격은 단순 API 단가만 보면 안 된다.

```text
OpenAI API 모델:
토큰당 비용 발생
서버 운영 부담 낮음
재색인 비용 계산 쉬움

오픈소스 모델:
모델 사용료 없음
GPU/서버/배포/모니터링 비용 발생
대량 색인 시 인프라 비용이 커질 수 있음
```

즉 `bge-m3`나 `multilingual-e5-large`가 무료라는 말은 정확하지 않다. 모델 라이선스 비용은 없지만, 직접 운영하면 GPU 서버 비용과 운영 복잡도가 생긴다.

### 정확도 관점 정리

정확도는 일반 벤치마크 점수만으로 결정하면 안 된다.

우리 프로젝트에서는 아래 기준으로 다시 봐야 한다.

```text
과실비율 심의사례 query에서 유사 사례를 잘 찾는가
판례 query에서 과실상계/책임제한 근거를 잘 찾는가
차로변경, 신호위반, 횡단보도 같은 키워드 쟁점을 놓치지 않는가
한국어 법률 문장과 보험 실무 표현을 잘 처리하는가
BM25+Nori보다 Top1/Hit@5/reranker score가 실제로 좋아지는가
```

따라서 임베딩 모델 비교는 아래처럼 진행하는 것이 적합하다.

```text
Baseline:
BM25+Nori

Embedding 후보:
text-embedding-3-small
text-embedding-3-large
BAAI/bge-m3
intfloat/multilingual-e5-large

비교 방식:
Hybrid 검색 결과를 같은 reranker로 재평가
```

### 현재 추천 결론

지금 당장 실험한다면 우선순위는 다음이다.

| 순위 | 후보 | 이유 |
|---:|---|---|
| 1 | `text-embedding-3-large` | 현재 구조에서 가장 쉽게 비교 가능. API만 바꾸면 되므로 실험 비용이 낮음 |
| 2 | `BAAI/bge-m3` | 한국어 포함 다국어, 긴 문서, hybrid 검색 특성이 좋아 후속 고도화 후보로 가치 있음 |
| 3 | `multilingual-e5-large` | 다국어 검색 성능 비교 후보. 다만 512 token 제한과 prefix 규칙 때문에 전처리 확인 필요 |

PM님에게 설명할 때는 이렇게 말하면 된다.

```text
현재 사용 중인 text-embedding-3-small은 비용과 운영 단순성이 장점이라 baseline으로 적합합니다.
후속 실험을 한다면 먼저 text-embedding-3-large로 같은 OpenAI 계열 내 성능 개선을 확인하고,
그 다음 bge-m3 같은 오픈소스 다국어 임베딩을 self-host 방식으로 비교하는 순서가 현실적입니다.
다만 오픈소스 모델은 모델 비용이 없을 뿐 GPU 운영 비용과 배포 복잡도가 생기므로,
정확도 개선 폭이 충분히 커야 운영 전환 근거가 됩니다.
```

### 참고 출처

```text
OpenAI Embeddings 문서:
text-embedding-3-small = 1536 dim
text-embedding-3-large = 3072 dim
둘 다 max input 8192 tokens

BAAI/bge-m3 Hugging Face:
MIT license
1024 dim
8192 sequence length
100개 이상 언어 지원

intfloat/multilingual-e5-large Hugging Face:
MIT license
1024 dim
100개 언어 기반
max 512 tokens
```






---

## 12. 실제 진행 순서

아래 순서는 후속 임베딩/Hybrid RAG 고도화를 실제로 진행할 때의 실행 순서다.

핵심 원칙은 다음이다.

```text
운영용 기존 1536 dim index는 건드리지 않는다.
후속 실험용 1024 dim index를 따로 만든다.
점수 산출 방식은 기존 pgvector/BM25+Nori/Hybrid 비교 방식과 동일하게 유지한다.
결과는 1536 baseline과 1024 통일 실험을 분리 기록한다.
```

### 전체 진행 순서 요약

| 단계 | 해야 할 일 | 왜 하는가 | 근거 | 예상 결과 |
|---:|---|---|---|---|
| 1 | 기존 baseline 결과 정리 | 현재 기준선을 명확히 해야 후속 실험의 개선 여부를 판단할 수 있음 | 기존 BM25+Nori, pgvector, vector, hybrid 비교 결과가 이미 있음 | 1536 baseline 표 확정 |
| 2 | query set 확정 | 모델별 결과가 query 차이 때문에 흔들리지 않게 하기 위함 | 기존 평가도 같은 query set 기준으로 retriever별 비교를 진행함 | 후속 실험 공통 query 목록 확보 |
| 3 | chunk set 고정 | 모델 성능 비교에서 데이터 차이를 제거하기 위함 | 같은 chunk를 검색해야 embedding model 차이만 비교 가능 | review_case/fault_ratio_precedent chunk 기준 고정 |
| 4 | 1024 dim 실험 index 설계 | 기존 1536 index를 건드리지 않고 1024 통일 비교를 하기 위함 | vector index는 같은 field 안에서 dimension이 같아야 함 | `embedding_1024` 계열 별도 index 설계 |
| 5 | 1024 dim 문서 embedding 생성 | query와 chunk의 dimension을 맞추기 위함 | 문서 chunk와 query embedding dimension이 다르면 vector similarity 비교 불가 | 모델별 1024 dim document embedding 생성 |
| 6 | 1024 dim query embedding 생성 | 각 모델의 검색 조건을 동일하게 맞추기 위함 | 문서 embedding과 query embedding은 같은 모델/차원이어야 함 | 모델별 query embedding 생성 |
| 7 | Hybrid 검색 실행 | BM25+Nori와 vector 검색 조합이 baseline보다 좋아지는지 확인하기 위함 | 기존 실험에서도 Hybrid가 Avg@5에서 일부 가능성을 보였음 | 모델별 Hybrid 후보 결과 생성 |
| 8 | 같은 reranker로 재평가 | BM25 raw score와 vector similarity를 직접 비교하지 않기 위함 | 기존 평가 방식도 local reranker score로 후보 품질을 다시 평가했음 | Avg Top1, Avg@5, Hit@5 산출 |
| 9 | 1536 baseline과 1024 실험 결과 분리 비교 | dimension 차이와 model 차이를 혼동하지 않기 위함 | 1536 결과와 1024 결과는 같은 index 조건이 아님 | 분리된 비교표 생성 |
| 10 | 비용/속도/운영 복잡도 정리 | 정확도가 좋아도 운영 비용이 과하면 baseline 전환이 어려움 | Hybrid는 embedding 생성, vector index, score fusion 관리가 필요함 | 운영 전환 가능성 판단 |
| 11 | 최종 결론 작성 | PM/팀원이 바로 판단할 수 있는 형태로 정리하기 위함 | 실험 결과는 점수만으로 끝나면 의사결정에 쓰기 어려움 | 운영 유지/추가 실험/전환 후보 중 결론 도출 |

---

### 1단계. 기존 baseline 결과 정리

먼저 기존 실험 결과를 표로 고정한다.

```text
BM25+Nori
pgvector
Elasticsearch vector
Elasticsearch hybrid
```

이 단계에서 해야 할 일은 새로운 실험이 아니라, 이미 나온 결과를 기준선으로 정리하는 것이다.

| 항목 | 내용 |
|---|---|
| 왜 하는가 | 후속 실험이 실제로 좋아졌는지 비교할 기준이 필요함 |
| 근거 | 기존 실험에서 BM25+Nori가 운영 baseline으로 가장 안정적이었음 |
| 예상 결과 | `baseline_1536` 비교표 확정 |

정리할 표는 아래 형태가 적합하다.

| 구분 | Retriever | Embedding model | Dimension | Avg Top1 | Avg@5 | Hit@5 | 비고 |
|---|---|---|---:|---:|---:|---:|---|
| 기존 baseline | BM25+Nori | 없음 | 없음 | 기존값 | 기존값 | 기존값 | 운영 baseline |
| 기존 실험 | pgvector | text-embedding-3-small | 1536 | 기존값 | 기존값 | 기존값 | vector DB 비교 |
| 기존 실험 | ES vector | text-embedding-3-small | 1536 | 기존값 | 기존값 | 기존값 | ES vector 비교 |
| 기존 실험 | ES hybrid | text-embedding-3-small | 1536 | 기존값 | 기존값 | 기존값 | 기존 hybrid 비교 |

---

### 2단계. query set 확정

후속 실험에서는 query set을 고정해야 한다.

```text
같은 query set
같은 query 의도
같은 source 대상
같은 top_k
```

| 항목 | 내용 |
|---|---|
| 왜 하는가 | query가 달라지면 모델 성능 차이인지 query 난이도 차이인지 구분하기 어려움 |
| 근거 | 기존 평가도 같은 query 기준으로 retriever 후보 품질을 비교했음 |
| 예상 결과 | 후속 실험용 query 목록 확정 |

query는 최소한 아래 유형을 포함하는 것이 좋다.

```text
차로변경
후방추돌
신호위반
횡단보도
과실상계
손해배상 책임제한
보험사 주장 비교
```

---

### 3단계. chunk set 고정

문서 chunk도 고정해야 한다.

```text
review_case_chunks
fault_ratio_precedent chunks
```

| 항목 | 내용 |
|---|---|
| 왜 하는가 | chunk가 달라지면 embedding model 차이와 데이터 차이가 섞임 |
| 근거 | RAG 검색 결과는 chunk 단위에 직접 영향을 받음 |
| 예상 결과 | 모든 모델이 같은 chunk set을 대상으로 검색 |

이 단계에서는 chunk를 새로 나누지 않는다.

```text
심의사례:
기존 4개 section chunk 유지

판례:
기존 판례 chunk 구조 유지
```

---

### 4단계. 1024 dim 실험 index 설계

기존 운영 index는 그대로 둔다.

```text
기존:
1536 dim index 유지

후속 실험:
1024 dim 실험 index 생성
```

| 항목 | 내용 |
|---|---|
| 왜 하는가 | 기존 운영/실험 결과를 보존하면서 1024 통일 비교를 하기 위함 |
| 근거 | 같은 vector field 안에서는 dimension이 같아야 함 |
| 예상 결과 | 1024 dim 전용 index 설계 완료 |

index는 모델별로 분리하는 편이 안전하다.

```text
hybrid_text_embedding_3_small_1024
hybrid_text_embedding_3_large_1024
hybrid_bge_m3_1024
hybrid_multilingual_e5_large_1024
```

---

### 5단계. 1024 dim document embedding 생성

1024 실험에서는 문서 chunk를 모두 1024 dimension으로 다시 임베딩한다.

```text
text-embedding-3-small dimensions=1024
text-embedding-3-large dimensions=1024
bge-m3 1024 dim
multilingual-e5-large 1024 dim
```

| 항목 | 내용 |
|---|---|
| 왜 하는가 | document vector와 query vector의 dimension을 맞추기 위함 |
| 근거 | 1536 dim chunk와 1024 dim query는 similarity 비교 불가 |
| 예상 결과 | 모델별 1024 dim document embedding 생성 |

주의할 점은 기존 1536 embedding을 잘라서 쓰지 않는 것이다.

```text
기존 1536 vector를 임의로 잘라 1024로 사용
-> 권장하지 않음

모델 API/모델 출력 기준으로 1024 embedding 재생성
-> 권장
```

---

### 6단계. 1024 dim query embedding 생성

query도 같은 모델과 같은 dimension으로 임베딩해야 한다.

| 항목 | 내용 |
|---|---|
| 왜 하는가 | query embedding과 document embedding은 같은 vector space에 있어야 함 |
| 근거 | 서로 다른 모델/차원의 vector는 의미 공간이 달라 직접 비교 불가 |
| 예상 결과 | 모델별 query embedding 생성 |

```text
문서: text-embedding-3-large 1024
query: text-embedding-3-large 1024
-> 비교 가능

문서: bge-m3 1024
query: text-embedding-3-small 1024
-> 비교하면 안 됨
```

---

### 7단계. Hybrid 검색 실행

각 모델별 vector 검색 결과를 BM25+Nori와 결합해 Hybrid 후보를 만든다.

| 항목 | 내용 |
|---|---|
| 왜 하는가 | 키워드 기반 강점과 의미 기반 검색 강점을 함께 쓰기 위함 |
| 근거 | 과실비율 query는 법률 키워드도 중요하지만 표현이 달라지는 유사 사고도 존재함 |
| 예상 결과 | 모델별 Hybrid 후보 top_k 생성 |

비교 대상은 아래와 같다.

```text
BM25+Nori baseline
Hybrid(text-embedding-3-small 1024)
Hybrid(text-embedding-3-large 1024)
Hybrid(bge-m3 1024)
Hybrid(multilingual-e5-large 1024)
```

---

### 8단계. 같은 reranker로 재평가

검색기가 가져온 후보를 같은 reranker로 다시 평가한다.

```text
각 retriever 후보
-> query + chunk_text
-> 같은 reranker
-> local_reranker_score
```

| 항목 | 내용 |
|---|---|
| 왜 하는가 | BM25 score와 vector similarity는 직접 비교할 수 없기 때문 |
| 근거 | 기존 pgvector/BM25+Nori/Hybrid 비교도 reranker score로 평가했음 |
| 예상 결과 | Avg Top1, Avg@5, Hit@5 산출 |

이 단계는 기존 평가 방식과 동일해야 한다.

```text
평가 방식은 유지
비교 대상만 추가
```

---

### 9단계. 1536 baseline과 1024 실험 결과 분리 비교

결과표는 반드시 분리해서 작성한다.

| 구분 | 의미 |
|---|---|
| 1536 baseline | 현재 운영/기존 실험 기준 |
| 1024 통일 실험 | 후속 모델 비교 실험 |

| 항목 | 내용 |
|---|---|
| 왜 하는가 | dimension 차이와 모델 차이를 혼동하지 않기 위함 |
| 근거 | 1536과 1024는 같은 vector index 조건이 아님 |
| 예상 결과 | 1536 유지가 좋은지, 1024 통일이 좋은지 판단 가능 |

해석 기준은 다음과 같다.

```text
1024가 성능도 좋고 가볍다
-> 1024 전환 후보

1536이 명확히 더 좋다
-> 1536 유지

점수 차이가 거의 없다
-> 비용/속도/운영 단순성 기준으로 판단
```

---

### 10단계. 비용/속도/운영 복잡도 정리

정확도만 보고 결정하면 안 된다.

| 항목 | 확인할 내용 |
|---|---|
| 비용 | API embedding 비용, self-host GPU 비용 |
| 속도 | query embedding 생성 시간, 검색 latency |
| 저장공간 | vector index 크기 |
| 운영 복잡도 | 모델 버전 관리, 재색인, score fusion 관리 |

| 항목 | 내용 |
|---|---|
| 왜 하는가 | 정확도가 조금 좋아도 운영 부담이 크면 baseline 전환이 어려움 |
| 근거 | Hybrid는 embedding 생성, vector index, fusion 관리가 추가됨 |
| 예상 결과 | 품질 개선 대비 운영 비용 판단 |

---

### 11단계. 최종 결론 작성

마지막에는 점수표만 남기지 말고 의사결정 문장까지 작성한다.

결론은 아래 셋 중 하나로 정리한다.

```text
1. BM25+Nori baseline 유지
2. Hybrid는 가능성 있으나 추가 실험 필요
3. 특정 embedding model 기반 Hybrid를 운영 후보로 검토
```

| 항목 | 내용 |
|---|---|
| 왜 하는가 | PM/팀원이 바로 판단할 수 있는 형태로 남기기 위함 |
| 근거 | 실험 결과는 점수만으로는 의사결정에 쓰기 어려움 |
| 예상 결과 | 운영 유지/후속 실험/전환 후보 중 하나로 결론 도출 |

PM님 공유용 최종 문장은 아래 형태가 적합하다.

```text
후속 임베딩 실험은 기존 1536 dim 운영 index를 유지한 상태에서,
1024 dim 통일 실험 index를 별도로 만들어 진행합니다.
평가는 기존 pgvector/BM25+Nori/Hybrid 비교와 동일하게 reranker score 기준으로 수행하고,
1536 baseline과 1024 실험 결과를 분리 기록합니다.
최종적으로 정확도 개선 폭, 비용, 속도, 운영 복잡도를 함께 보고
BM25+Nori 유지 또는 Hybrid 전환 후보 여부를 판단합니다.
```
