# 교통사고 판례 RAG 파이프라인 상세 계획
## PostgreSQL · Chunk · Embedding · Elasticsearch · A/B 테스트 전략

---

## 0. 문서 목적

이 문서는 교통사고/과실비율 **판례 데이터**를 서비스 검색/RAG에 사용하기 위해, 아래 순서별로 무엇을 결정해야 하는지 정리한 계획서입니다.

```text
1. 2차 과실비율 분류 완료
↓
2. PostgreSQL에 판례 원본 저장
↓
3. chunk 생성
↓
4. embedding 생성
↓
5. Elasticsearch 색인
↓
6. 검색 API 만들기
↓
7. 오프라인 A/B 테스트
↓
8. 더 좋은 설정 선택
↓
9. 서비스 적용
↓
10. 나중에 실제 사용자 생기면 온라인 A/B 테스트
```

핵심 질문은 다음입니다.

```text
1. 왜 Elasticsearch를 쓰는가?
2. PostgreSQL과 Elasticsearch는 각각 어떤 역할인가?
3. chunk 생성은 어떤 방식으로 할 것인가?
4. embedding 모델 후보는 무엇인가?
5. 후보 중 어떤 2개를 A/B 테스트할 것인가?
6. 단계별로 비교해야 할 선택지는 무엇인가?
7. 오프라인 A/B 테스트는 어떤 기준으로 평가할 것인가?
```

---

## 1. 전체 결론 요약

### 1.1 권장 전체 구조

```text
2차 과실비율 분류 완료 JSONL
↓
PostgreSQL에 판례 원본/메타데이터 저장
↓
판례 본문을 chunk로 분할
↓
PostgreSQL에 chunk 저장
↓
embedding 모델 후보로 chunk embedding 생성
↓
Elasticsearch에 chunk + metadata + embedding 색인
↓
검색 API에서 hybrid 검색
↓
오프라인 A/B 테스트로 embedding/chunk/search 설정 비교
↓
가장 좋은 설정을 운영 index로 승격
```

### 1.2 Elasticsearch를 쓰는 이유 한 줄 요약

```text
PostgreSQL은 원본/상태 관리용이고,
Elasticsearch는 사용자 사고 경위와 비슷한 판례 chunk를 빠르게 찾는 검색/RAG retrieval용이다.
```

### 1.3 embedding 모델 A/B 테스트 추천 2개

최초 A/B 테스트 추천 후보는 다음 2개입니다.

| 구분 | 추천 모델 | 선택 이유 |
|---|---|---|
| A안 | `text-embedding-3-small` | 비용/성능 균형, 구현 쉬움, baseline으로 적합 |
| B안 | `gemini-embedding-2` | 한국어 포함 다국어 검색/RAG 가능성이 높고, query/document 형식 지정이 가능 |

보조 후보:

```text
voyage-law-2
```

이 모델은 법률 retrieval/RAG 특화 후보로 볼 수 있습니다. 다만 한국어 판례에서 실제 성능은 직접 검증해야 하므로, 처음 A/B의 메인 2개보다는 2차 실험 후보로 둡니다.

---

## 2. 왜 Elasticsearch를 사용할 생각인가

### 2.1 Elasticsearch의 역할

Elasticsearch는 **판례 원본 저장소**가 아니라 **검색 엔진**입니다.

우리 서비스에서 Elasticsearch가 해야 하는 일은 다음입니다.

```text
사용자 사고 경위 입력
↓
관련 사고유형/과실 판단 chunk 검색
↓
상위 판례 chunk 반환
↓
LLM이 그 chunk를 근거로 설명 생성
```

예시 사용자 질문:

```text
신호 없는 교차로에서 직진 중이었는데 상대 차량이 우회전하다가 제 차 옆을 들이받았습니다.
```

이때 필요한 것은 판례 전체 1건이 아니라, 판례 안에서도 다음 문단입니다.

```text
사고 경위
주의의무 위반
과실상계
책임비율
손해배상책임 판단
```

그래서 Elasticsearch에는 **판례 chunk 단위**로 넣는 것이 좋습니다.

### 2.2 PostgreSQL만으로 충분하지 않은 이유

PostgreSQL도 검색을 할 수 있습니다. 하지만 이번 프로젝트에서는 다음 이유로 Elasticsearch가 더 적합합니다.

| 비교 항목 | PostgreSQL | Elasticsearch |
|---|---|---|
| 원본 판례 저장 | 매우 적합 | 가능하지만 주 역할 아님 |
| 분류 라벨/검수상태 관리 | 매우 적합 | 가능하지만 관리성이 낮음 |
| 긴 판례 본문 전문검색 | 가능하지만 튜닝 부담 | 전문 검색에 적합 |
| BM25 랭킹 | 직접 구현/튜닝 부담 | 기본 검색 랭킹으로 사용 가능 |
| 한국어 형태소 분석 | tsvector 튜닝 필요 | Nori analyzer 적용 가능 |
| chunk 검색 | 가능 | 매우 적합 |
| 하이라이트 | 직접 구현 부담 | 검색 결과에서 제공 가능 |
| vector search | pgvector 가능 | dense_vector/kNN 검색 가능 |
| keyword + vector hybrid | 구현 부담 | query + kNN 조합 가능 |

결론:

```text
PostgreSQL = 원본/메타데이터/검수/로그
Elasticsearch = 검색/RAG retrieval
```

### 2.3 Elasticsearch를 쓰는 구체적 근거

| 이유 | 설명 |
|---|---|
| 긴 본문 검색 | 판례 본문은 길고 쟁점이 여러 개라 chunk 검색이 필요 |
| BM25 검색 | 과실상계, 책임비율, 무단횡단 같은 정확 키워드 검색에 강함 |
| 한국어 분석기 | Nori analyzer로 한국어 형태소 분석 적용 가능 |
| 필터 검색 | 사건종류, 선고일자, 법원, fault_ratio_label 등 필터 가능 |
| vector search | embedding 기반 의미 검색 가능 |
| hybrid 검색 | BM25 + vector를 합쳐 사용 가능 |
| RAG 연결 | 검색 결과 chunk를 LLM context로 바로 전달 가능 |
| 운영 버전 관리 | index alias로 v1/v2 전환 가능 |

---

# 1단계. 2차 과실비율 분류 완료

## 1.1 목적

1차 분류는 교통사고 관련 판례인지 확인하는 단계였습니다. 2차 분류는 그중에서 **과실비율/과실상계/책임비율 판단에 실제로 쓸 수 있는 판례**를 고르는 단계입니다.

```text
confirmed_traffic
↓
fault_ratio_confirmed
fault_ratio_possible_review
traffic_but_no_fault_ratio
```

## 1.2 선택지 비교

| 선택지 | 설명 | 장점 | 단점 | 추천 |
|---|---|---|---|---|
| A안: confirmed_traffic만 2차 분류 | 1차 통과 판례만 과실비율 후보 분류 | 입력 노이즈 적음 | 일부 누락 가능 | 추천 |
| B안: confirmed + possible_review 모두 2차 분류 | recall을 높이기 위해 possible까지 포함 | 누락 줄일 가능성 | 노이즈 증가 | 나중 보강용 |
| C안: 전체 판례를 바로 과실비율 분류 | 전체에서 과실비율 판례 탐색 | 구조 단순 | 비교통 판례가 너무 많이 섞임 | 비추천 |

## 1.3 권장안

```text
A안 사용
= 1차 confirmed_traffic만 2차 과실비율 분류 입력으로 사용
```

이유:

```text
과실비율 RAG는 검색 품질이 중요하다.
초기에는 많이 담는 것보다 깨끗한 판례만 넣는 것이 더 안전하다.
```

## 1.4 예상 결과

```text
fault_ratio_confirmed
→ 과실비율 RAG 핵심 데이터

fault_ratio_possible_review
→ 나중에 recall 보강용 검토 데이터

traffic_but_no_fault_ratio
→ 교통사고 관련은 맞지만 과실비율 RAG에는 제외
```

---

# 2단계. PostgreSQL에 판례 원본 저장

## 2.1 목적

PostgreSQL은 검색 엔진이 아니라 **원본/상태 관리 DB**입니다.

저장할 내용:

```text
case_id
case_name
case_number
court_name
decision_date
case_category
holding
summary
main_text
traffic_label
fault_ratio_label
검수 상태
raw_json
created_at
updated_at
```

## 2.2 선택지 비교

| 선택지 | 구조 | 장점 | 단점 | 추천 |
|---|---|---|---|---|
| A안: 하나의 `precedent_cases` 테이블 | dataset_type으로 교통사고/과실비율 구분 | 중복 구조 적음 | 초반 이해가 어려울 수 있음 | 중장기 추천 |
| B안: `traffic_precedent_cases`, `fault_ratio_precedent_cases` 분리 | 목적별 테이블 분리 | 이해 쉬움, 검색 목적 명확 | 같은 case_id 중복 저장 가능 | 초기 추천 |
| C안: JSONB만 통째로 저장 | raw_json 중심 | 빠르게 저장 가능 | 쿼리/제약조건 약함 | 보조용 |
| D안: PostgreSQL 생략 | 바로 ES로 적재 | 빠른 데모 | 원본/상태 관리 어려움 | 실험용만 |

## 2.3 권장안

초기에는 다음 구조를 추천합니다.

```text
traffic_precedent_cases
fault_ratio_precedent_cases
precedent_chunks
indexing_jobs
search_eval_logs
```

이유:

```text
교통사고 일반 검색과 과실비율 RAG 검색은 목적이 다르다.
초기에는 테이블을 분리하는 편이 이해하기 쉽다.
```

---

# 3단계. chunk 생성

## 3.1 목적

chunk 생성은 판례 전체를 검색에 넣기 좋은 작은 문서 조각으로 나누는 과정입니다.

```text
판례 1건
↓
사고 경위 chunk
과실 판단 chunk
손해배상책임 chunk
과실상계 chunk
손해액 계산 chunk
```

## 3.2 왜 chunk가 필요한가

| 문제 | 설명 |
|---|---|
| 검색 결과가 너무 넓음 | 판례 전체가 맞아도 실제 관련 문단이 어디인지 모름 |
| RAG context가 길어짐 | LLM에 넘길 때 불필요한 문장까지 포함 |
| 여러 쟁점이 섞임 | 하나의 판례에 사고 경위, 손해액, 지연손해금 등이 모두 섞임 |
| 과실 판단이 묻힘 | 진짜 필요한 과실상계 문단이 긴 본문에 묻힘 |

## 3.3 chunk 방식 후보 비교

| 후보 | 방식 | 장점 | 단점 | 예상 |
|---|---|---|---|---|
| A안: 고정 길이 chunk | 1500자 + overlap 250자 | 구현 쉬움, 빠른 MVP | 문단 중간이 잘릴 수 있음 | 초기 baseline |
| B안: 문단 기준 chunk | 줄바꿈/문단 단위로 묶음 | 문맥 보존 좋음 | 판례별 문단 품질 차이 | A보다 자연스러울 가능성 |
| C안: 섹션 기준 chunk | 판시사항/요지/이유/판단 등 구간 분리 | 판례 구조 반영 | 섹션 파서 필요 | 장기적으로 가장 좋음 |
| D안: evidence 중심 chunk | 과실상계/책임비율 주변 문단 강화 | 과실비율 검색에 강함 | 사고 경위가 약해질 수 있음 | 보조 chunk로 좋음 |
| E안: 전체 판례 통째로 | 판례 1건 1문서 | 구현 간단 | RAG에 부적합 | 비추천 |

## 3.4 권장 chunk 전략

초기 권장안:

```text
A안 + D안 혼합
```

즉:

```text
1. main_text는 1500자 기준 + 250자 overlap으로 자른다.
2. holding은 holding chunk로 별도 저장한다.
3. summary는 summary chunk로 별도 저장한다.
4. 과실비율 근거 표현이 있는 주변 문단은 evidence chunk로 별도 저장한다.
```

## 3.5 chunk_type 설계

```text
holding
summary
main_text
evidence
law
```

검색 가중치는 다음처럼 줄 수 있습니다.

| chunk_type | 예상 가중치 |
|---|---:|
| evidence | 가장 높음 |
| summary | 높음 |
| holding | 높음 |
| main_text | 기본 |
| law | 낮음 |

## 3.6 chunk A/B 테스트 후보

| 실험 | A안 | B안 | 비교 목적 |
|---|---|---|---|
| chunk_size 테스트 | 1200자 + overlap 200자 | 1800자 + overlap 300자 | 짧은 chunk vs 긴 chunk |
| chunk_type 테스트 | main_text chunk만 | holding/summary/evidence 별도 chunk 추가 | 구조화 chunk 효과 |
| evidence 테스트 | 일반 chunk만 | 과실비율 근거 주변 evidence chunk 추가 | 과실 판단 검색 개선 여부 |

---

# 4단계. embedding 생성

## 4.1 목적

embedding은 `chunk_text`를 숫자 벡터로 바꾸는 과정입니다.

```text
chunk_text
↓
embedding model
↓
embedding vector
```

사용자 사고 경위도 같은 모델로 embedding합니다.

```text
사용자 사고 경위
↓
same embedding model
↓
query vector
```

그리고 Elasticsearch에서 query vector와 가까운 chunk vector를 찾습니다.

## 4.2 embedding은 판례 전체가 아니라 chunk에 한다

```text
판례 1건당 embedding 1개
X

chunk 1개당 embedding 1개
O
```

이유:

```text
사용자가 찾는 것은 판례 전체가 아니라,
사고 경위/과실상계/책임비율이 들어 있는 특정 문단이기 때문
```

## 4.3 embedding 모델 후보 비교표

| 후보 | 차원 | 장점 | 단점 | 우리 프로젝트 적합도 |
|---|---:|---|---|---|
| OpenAI `text-embedding-3-small` | 1536 | 비용/성능 균형, 구현 쉬움, baseline 적합 | 법률 특화는 아님 | 매우 높음 |
| OpenAI `text-embedding-3-large` | 3072 | 성능 기대 높음, 차원 축소 가능 | 비용/저장공간 증가 | 높음 |
| Google `gemini-embedding-2` | 공식 문서 확인 필요 | 다국어/멀티모달 embedding, RAG 사용 가능성 | prompt format 관리 필요 | 매우 높음 |
| Google `gemini-embedding-001` | 공식 문서 확인 필요 | query/document task_type 지원 | 최신성은 embedding-2보다 낮을 수 있음 | 중간~높음 |
| Cohere `embed-v4.0` | 256/512/1024/1536 | 긴 context, 다국어/문서 embedding 후보 | 비용/환경 확인 필요 | 높음 |
| Voyage `voyage-law-2` | 1024 | 법률 retrieval/RAG 특화 | 한국어 판례 성능은 직접 확인 필요 | 법률 특화 후보 |
| Voyage `voyage-4` 또는 `voyage-4-lite` | 1024 기본, 256/512/2048 지원 | retrieval 품질/차원 선택 가능 | 비용/환경 확인 필요 | 중간~높음 |
| 오픈소스 BGE-M3 계열 | 보통 1024 계열 | 자체 운영 가능, API 비용 없음 | GPU/서버/속도 관리 필요 | 비용 절감 후보 |

## 4.4 최초 A/B 테스트 추천 2개

### 추천 A안: OpenAI `text-embedding-3-small`

선택 이유:

```text
1. 비용/성능 균형이 좋다.
2. 구현이 쉽다.
3. 1536차원이라 Elasticsearch dense_vector mapping이 단순하다.
4. baseline으로 쓰기 좋다.
5. 실패 가능성이 낮다.
```

예상:

```text
사고 경위 자연어 검색에서 무난한 성능
과실상계/책임비율 같은 키워드는 BM25와 함께 쓰면 보완 가능
```

### 추천 B안: Google `gemini-embedding-2`

선택 이유:

```text
1. 한국어 사고 경위 자연어 검색에 강할 가능성이 있다.
2. RAG/검색용 embedding 구조를 명시할 수 있다.
3. query/document 입력 포맷을 구분해서 검색 품질을 조정할 수 있다.
4. 다국어 문서 검색에 적합한 후보이다.
```

예상:

```text
한국어 자연어 사고 설명에서는 OpenAI small보다 좋은 결과가 나올 수 있음
단, 과실상계/책임비율 같은 법률 표현은 BM25와 함께 써야 안정적
```

## 4.5 보조 실험 후보: Voyage `voyage-law-2`

법률 특화 관점에서는 매우 매력적인 후보입니다.

선택 이유:

```text
1. legal retrieval/RAG 특화 모델이다.
2. 판례/법률 문서 검색이라는 도메인과 잘 맞는다.
3. 1024차원이라 저장공간도 비교적 작다.
```

주의점:

```text
한국어 교통사고 판례에서 실제로 좋은지는 반드시 직접 테스트해야 한다.
법률 특화가 영어 법률 문서 중심이면 한국어에서는 기대보다 낮을 수 있다.
```

따라서 1차 A/B 이후 여유가 있으면 다음 실험으로 추가합니다.

```text
text-embedding-3-small
vs
voyage-law-2
```

또는

```text
gemini-embedding-2
vs
voyage-law-2
```

## 4.6 embedding 모델 A/B 테스트 설계

임베딩 모델을 비교할 때는 **모델만 바꿔야 합니다.**

고정할 것:

```text
같은 판례 데이터
같은 chunk 방식
같은 Elasticsearch mapping
같은 검색 API
같은 테스트 질문
같은 top-k
같은 필터 조건
```

바꿀 것:

```text
embedding model only
```

예시 index:

```text
fault_ratio_case_chunks_openai_small_v1
fault_ratio_case_chunks_gemini_embedding2_v1
```

---

# 5단계. Elasticsearch 색인

## 5.1 목적

Elasticsearch 색인은 PostgreSQL의 원본/청크 데이터를 검색하기 좋은 형태로 복사하는 과정입니다.

```text
PostgreSQL chunk
↓
검색용 document 변환
↓
Elasticsearch bulk insert
```

## 5.2 index 구조 후보

| 후보 | 구조 | 장점 | 단점 | 추천 |
|---|---|---|---|---|
| A안: chunk index만 | `fault_ratio_case_chunks_v1` | 빠른 구현 | 상세/메타 분리 약함 | MVP 가능 |
| B안: case index + chunk index | `fault_ratio_cases_v1`, `fault_ratio_case_chunks_v1` | 상세 조회/검색 분리 | 구현량 증가 | 추천 |
| C안: traffic/fault_ratio 통합 index | dataset_type 필터 | 관리 index 수 적음 | 검색 목적 섞임 | 비추천 |
| D안: traffic/fault_ratio 분리 index | 목적별 index 분리 | 노이즈 감소, 튜닝 쉬움 | index 수 증가 | 추천 |

## 5.3 권장 index

```text
traffic_cases_v1
traffic_case_chunks_v1
fault_ratio_cases_v1
fault_ratio_case_chunks_v1
```

과실비율 RAG는 우선 다음 index만 사용합니다.

```text
fault_ratio_case_chunks_v1
```

## 5.4 Elasticsearch document 예시

```json
{
  "chunk_id": "616249#002",
  "case_id": "616249",
  "case_name": "손해배상(자)",
  "case_number": "2022다287284",
  "court_name": "대법원",
  "decision_date": "2026-01-29",
  "case_category": "민사",
  "fault_ratio_label": "fault_ratio_confirmed",
  "chunk_type": "evidence",
  "chunk_text": "피고 차량은 ... 원고의 과실을 30%로 참작한다 ...",
  "search_text": "[사건명] 손해배상(자)\n[과실비율 근거] 과실상계, 원고의 과실\n[본문] ...",
  "embedding_model": "text-embedding-3-small",
  "embedding": [0.012, -0.044, 0.091]
}
```

## 5.5 analyzer 후보 비교

| 후보 | 설명 | 장점 | 단점 | 추천 |
|---|---|---|---|---|
| 기본 analyzer | Elasticsearch 기본 text 분석 | 바로 사용 가능 | 한국어 검색 품질 제한 | 첫 실행용 |
| Nori analyzer | 한국어 형태소 분석기 | 한국어 검색 품질 개선 가능 | 플러그인/설정 필요 | 추천 |
| Nori + 사용자 사전 | 교통사고/판례 용어 등록 | 과실상계, 전방주시의무 등 안정화 | 사전 관리 필요 | 장기 추천 |
| 동의어 사전 | 차로변경=진로변경 등 | recall 개선 | 오탐 증가 가능 | A/B 후 적용 |

## 5.6 mapping A/B 후보

| 실험 | A안 | B안 | 기대 |
|---|---|---|---|
| analyzer | 기본 analyzer | Nori analyzer | 한국어 질의 검색 개선 |
| field boost | chunk_text 중심 | case_name/summary/evidence boost | 과실비율 근거 chunk 상위 노출 |
| index 분리 | 통합 index | fault_ratio 전용 index | 노이즈 감소 |
| vector field | 없음 | dense_vector 추가 | 의미 검색 가능 |

---

# 6단계. 검색 API 만들기

## 6.1 목적

검색 API는 사용자 사고 경위를 받아서 Elasticsearch에서 관련 판례 chunk를 찾아 반환합니다.

입력 예시:

```json
{
  "accident_narrative": "신호 없는 교차로에서 직진 중 상대 차량이 우회전하다 충돌했습니다.",
  "top_k": 5
}
```

출력 예시:

```json
{
  "results": [
    {
      "case_id": "616249",
      "case_name": "손해배상(자)",
      "court_name": "대법원",
      "decision_date": "2026-01-29",
      "chunk_text": "...",
      "score": 12.34,
      "source_reference": "..."
    }
  ]
}
```

## 6.2 검색 방식 후보 비교

| 후보 | 설명 | 장점 | 단점 | 추천 단계 |
|---|---|---|---|---|
| A안: BM25 검색 | 키워드 기반 검색 | 빠르고 정확 키워드에 강함 | 표현이 다르면 약함 | 1차 baseline |
| B안: vector 검색 | embedding 의미 검색 | 자연어 사고 설명에 강함 | 엉뚱한 의미 유사 결과 가능 | 2차 |
| C안: hybrid 검색 | BM25 + vector | 키워드/의미 모두 반영 | 점수 조합 튜닝 필요 | 최종 추천 |
| D안: hybrid + reranker | 검색 후 재정렬 | top 결과 품질 개선 가능 | 비용/속도 증가 | 나중 |

## 6.3 권장 검색 API 단계

```text
1차 검색 API:
BM25 only

2차 검색 API:
BM25 + metadata filter

3차 검색 API:
BM25 + vector hybrid

4차 검색 API:
hybrid top 20 + reranker top 5
```

## 6.4 검색 필터 후보

| 필터 | 사용 이유 |
|---|---|
| `fault_ratio_label = fault_ratio_confirmed` | 과실비율용 판례만 검색 |
| `case_category = 민사` | 손해배상/과실상계 중심 검색 |
| `chunk_type in evidence, summary, main_text` | 법령/절차 chunk 노이즈 감소 |
| `decision_date range` | 최신 판례 우선 |
| `fault_ratio_evidence_terms` | 과실상계/책임비율 포함 판례 우선 |

---

# 7단계. 오프라인 A/B 테스트

## 7.1 목적

오프라인 A/B 테스트는 실제 사용자에게 공개하기 전에 내부 테스트 질문으로 검색 품질을 비교하는 단계입니다.

## 7.2 테스트 질문 세트

최소 30개, 가능하면 50개 정도를 만듭니다.

예시:

```text
1. 신호 없는 교차로에서 직진 차량과 우회전 차량 충돌
2. 좌회전 차량과 직진 오토바이 충돌
3. 횡단보도에서 보행자가 차량에 충격
4. 무단횡단 보행자와 직진 차량 충돌
5. 후미추돌 사고에서 앞차 급정거 과실
6. 차로 변경 중 후행 차량과 충돌
7. 중앙선 침범 차량과 마주 오던 차량 충돌
8. 주차장에서 후진 차량이 보행자 충격
9. 비보호 좌회전 차량과 직진 차량 충돌
10. 보험사가 구상금 청구한 책임분담비율 사건
```

## 7.3 평가 지표

| 지표 | 설명 | 중요도 |
|---|---|---:|
| Top-5 Hit | 상위 5개 안에 관련 판례가 있는가 | 매우 높음 |
| Precision@5 | 상위 5개 중 실제 관련 판례 비율 | 매우 높음 |
| 과실판단 포함률 | chunk 안에 과실상계/책임비율 판단이 있는가 | 매우 높음 |
| 사고유형 일치율 | 사용자 사고와 판례 사고유형이 맞는가 | 높음 |
| Noise Count | 형사/면허/산재/진료수가 등 노이즈 수 | 높음 |
| MRR | 첫 번째 관련 결과 순위 | 중간 |
| 응답 속도 | API latency | 중간 |
| 비용 | embedding/API 비용 | 중간 |

## 7.4 A/B 테스트 후보군 전체표

| 단계 | A안 | B안 | 비교 목적 | 예상 |
|---|---|---|---|---|
| chunk 크기 | 1200/200 | 1800/300 | 짧은 chunk vs 긴 chunk | 짧은 chunk는 정확, 긴 chunk는 문맥 좋음 |
| chunk 구조 | main_text만 | holding/summary/evidence 추가 | 구조화 효과 | B가 과실근거 검색에 유리 |
| embedding 모델 | OpenAI small | Gemini embedding-2 | embedding 품질 비교 | 자연어 검색에서 차이 발생 |
| analyzer | 기본 analyzer | Nori analyzer | 한국어 검색 개선 | Nori가 한국어 키워드에 유리 |
| 검색 방식 | BM25 | hybrid | 키워드 vs 의미검색 | hybrid가 최종 유리 가능 |
| 필터 | label만 | label + chunk_type | 노이즈 감소 | chunk_type 필터가 precision 증가 |
| reranker | 없음 | 있음 | top 결과 정렬 개선 | 품질은 증가, 속도/비용 증가 |

## 7.5 오프라인 A/B 테스트 순서

한 번에 모든 것을 비교하면 원인을 알 수 없습니다. 따라서 하나씩 비교해야 합니다.

### 실험 1. BM25 baseline

```text
목적:
검색이 기본적으로 되는지 확인

설정:
chunk = 1500/250
embedding = 없음
search = BM25
analyzer = 기본 analyzer
```

### 실험 2. Nori analyzer 비교

```text
A안:
기본 analyzer

B안:
Nori analyzer

고정:
chunk, 데이터, 검색 방식 동일
```

### 실험 3. chunk 구조 비교

```text
A안:
main_text 고정길이 chunk

B안:
main_text + holding + summary + evidence chunk
```

### 실험 4. embedding 모델 비교

```text
A안:
text-embedding-3-small

B안:
gemini-embedding-2

고정:
chunk 구조
Elasticsearch mapping
검색 API
테스트 질문
top_k
```

### 실험 5. 검색 방식 비교

```text
A안:
BM25

B안:
vector only

C안:
hybrid
```

예상:

```text
C안 hybrid가 최종적으로 가장 좋을 가능성이 높다.
```

### 실험 6. reranker 비교

```text
A안:
hybrid top 5 그대로 반환

B안:
hybrid top 20 검색 후 reranker로 top 5 재정렬
```

예상:

```text
B안은 품질은 좋아질 수 있지만 비용과 latency가 증가한다.
초기 MVP에서는 보류 가능하다.
```

---

# 8단계. 더 좋은 설정 선택

## 8.1 선택 기준

최종 선택은 단순히 Top-1만 보는 것이 아니라 종합 점수로 합니다.

| 항목 | 가중치 |
|---|---:|
| Precision@5 | 30 |
| Top-5 Hit | 25 |
| 과실판단 포함률 | 20 |
| Noise Count | 15 |
| 응답 속도 | 5 |
| 비용 | 5 |

## 8.2 선택 예시

| 설정 | Precision@5 | Top-5 Hit | 과실판단 포함률 | Noise | 선택 |
|---|---:|---:|---:|---:|---|
| BM25 only | 0.62 | 0.78 | 0.55 | 높음 | 보류 |
| Vector only | 0.58 | 0.82 | 0.50 | 중간 | 보류 |
| Hybrid | 0.74 | 0.88 | 0.68 | 낮음 | 선택 |
| Hybrid + reranker | 0.79 | 0.90 | 0.72 | 낮음 | 비용 보고 선택 |

예상 최종 선택:

```text
초기 운영:
Nori + structured chunk + text-embedding-3-small or gemini-embedding-2 + hybrid

나중 운영:
hybrid + reranker
```

---

# 9단계. 서비스 적용

## 9.1 운영 index 버전 관리

Elasticsearch index는 바로 덮어쓰지 않습니다.

```text
fault_ratio_case_chunks_v1
fault_ratio_case_chunks_v2
fault_ratio_case_chunks_v3
```

서비스는 alias를 봅니다.

```text
fault_ratio_case_chunks_current
```

새 index가 검증되면 alias만 바꿉니다.

```text
fault_ratio_case_chunks_current
↓
v1에서 v2로 전환
```

## 9.2 서비스 적용 전 체크리스트

```text
1. PostgreSQL 원본 row 수 확인
2. chunk 수 확인
3. Elasticsearch 문서 수 확인
4. embedding 누락 chunk 확인
5. 샘플 검색 10개 통과
6. 오탐 검색 5개 통과
7. API 응답 구조 확인
8. source_reference 연결 확인
9. 판례 상세 조회 연결 확인
10. rollback index 준비
```

---

# 10단계. 온라인 A/B 테스트

## 10.1 언제 하는가

온라인 A/B 테스트는 실제 사용자가 생긴 뒤에 합니다.

```text
오프라인 A/B 테스트
↓
최종 후보 선택
↓
서비스 적용
↓
실제 사용자 로그 축적
↓
온라인 A/B 테스트
```

## 10.2 온라인 A/B 테스트 후보

| 실험 | A안 | B안 | 측정 |
|---|---|---|---|
| 검색 방식 | BM25 | hybrid | 클릭률, 만족도 |
| 답변 방식 | 판례 3개 제시 | 판례 5개 제시 | 사용자가 다시 질문하는 비율 |
| 임베딩 모델 | OpenAI small | Gemini embedding-2 | 유사 판례 클릭률 |
| reranker | 없음 | 있음 | 상위 결과 클릭률 |
| 필터 강도 | confirmed only | confirmed + review | 누락/노이즈 비교 |

## 10.3 온라인 지표

| 지표 | 의미 |
|---|---|
| 검색 결과 클릭률 | 사용자가 결과 판례를 클릭했는가 |
| 답변 후 추가 질문률 | 답변이 부족해서 다시 물었는가 |
| 신고/불만 비율 | 엉뚱한 판례가 나왔는가 |
| 체류 시간 | 판례 근거를 실제로 읽었는가 |
| 사용자 만족도 | thumbs up/down 또는 별점 |
| 최종 상담 전환율 | 서비스 목표 행동으로 이어졌는가 |

---

# 11. 최종 권장 로드맵

## 11.1 1차 구현

```text
1. 2차 과실비율 분류 완료
2. PostgreSQL 테이블 생성
3. fault_ratio_confirmed 판례 저장
4. 1500/250 고정 chunk 생성
5. holding/summary/evidence chunk 추가
6. Elasticsearch BM25 index 생성
7. 샘플 검색 테스트
```

## 11.2 2차 구현

```text
1. Nori analyzer 적용
2. field boost 조정
3. search_text 구성 개선
4. 오탐 검색 테스트
```

## 11.3 3차 구현

```text
1. embedding 모델 2개 선택
   - text-embedding-3-small
   - gemini-embedding-2
2. 모델별 index 생성
3. 같은 테스트 질문 30~50개 실행
4. Top-5 Hit / Precision@5 / 과실판단 포함률 비교
5. 더 좋은 모델 선택
```

## 11.4 4차 구현

```text
1. BM25 + vector hybrid 검색 적용
2. score weight 조정
3. chunk_type boost 적용
4. 필요하면 reranker 추가
```

## 11.5 5차 구현

```text
1. 서비스 API 연결
2. 판례 상세 조회 연결
3. 사용자 로그 저장
4. 온라인 A/B 테스트 준비
```

---

# 12. 최종 결론

이번 프로젝트는 법령 검색이 아니라 **교통사고/과실비율 판례 검색 RAG**입니다.

따라서 핵심은 다음입니다.

```text
PostgreSQL:
판례 원본, 분류 결과, 검수 상태, chunk 상태, 검색 로그 관리

Elasticsearch:
사용자 사고 경위와 비슷한 판례 chunk 검색

Embedding:
chunk_text를 의미 벡터로 바꿔 자연어 사고 설명과 유사 판례를 연결

A/B 테스트:
embedding 모델, chunk 방식, analyzer, 검색 방식 중 무엇이 품질을 가장 높이는지 비교
```

최초 추천 실험은 다음입니다.

```text
검색 baseline:
BM25 + Nori + structured chunk

embedding A/B:
text-embedding-3-small
vs
gemini-embedding-2

최종 검색:
BM25 + vector hybrid
```

운영 관점 최종 구조는 다음입니다.

```text
PostgreSQL 원본
↓
chunk 생성/관리
↓
embedding 생성
↓
Elasticsearch 색인
↓
검색 API
↓
RAG 답변
↓
오프라인/온라인 A/B 테스트로 개선
```

---

# 13. 참고 자료

- OpenAI Embeddings API 문서  
  https://developers.openai.com/api/docs/guides/embeddings

- Google Gemini Embeddings 문서  
  https://ai.google.dev/gemini-api/docs/embeddings

- Cohere Embed 모델 문서  
  https://docs.cohere.com/docs/cohere-embed

- Voyage AI Embeddings 문서  
  https://docs.voyageai.com/docs/embeddings

- Elasticsearch kNN search 문서  
  https://www.elastic.co/docs/solutions/search/vector/knn

- Elasticsearch Nori analyzer 문서  
  https://www.elastic.co/docs/reference/elasticsearch/plugins/analysis-nori
