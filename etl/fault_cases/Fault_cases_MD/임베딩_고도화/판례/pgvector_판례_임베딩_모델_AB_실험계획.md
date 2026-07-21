# pgvector 판례 임베딩 모델 A/B 실험 계획

> 개정 기준일: 2026-07-17  
> 대상: `traffic_precedents` 과실비율 판례 987건 / 8,334청크  
> 실험 단계: Track A 모델 기본/native 차원 비교. 우승 후보 선정 후 차원 축소 Pareto 실험을 별도로 수행한다.

> [!IMPORTANT]
> 세 코퍼스의 실제 임베딩 생성 순서, 모델별 별도 작업 채팅, batch, 병렬 허용 범위와 RunPod 소유권은 [3코퍼스 공통 임베딩 모델별 실행 계획](../pgvector_3코퍼스_공통_임베딩_모델별_실행계획.md)을 따른다. 이 문서는 판례 corpus, 판례 adapter, 판례 qrels와 평가 규칙을 소유한다. 판례만을 위한 별도 RunPod를 만들지 않으며, 공통 신규 Pod에서 현재 모델의 `fault_standard -> review_case -> precedent` batch 중 판례 batch만 이 문서 기준으로 검증한다.

> [!IMPORTANT]
> Track A는 6개 모델 각각에 대해 판례 8,334개 document와 Query 50개를 `repeat_01`, `repeat_02`, `repeat_03`에서 모두 새로 생성한다. 이전 vector 재사용은 허용하지 않으며, 판례 기준 6 × 3 = 18개 model-repeat 결과를 만든다.

---

## 1. 문서 목적

이 문서는 **동일한 판례 코퍼스와 Ground Truth, 모델별 공식 기본/native 차원, 동일한 exact cosine 검색 조건**에서 최신 6개 임베딩 모델의 검색 품질과 운영 비용을 비교하기 위한 실행 계획이다.

이번 실험이 답할 질문은 하나다.

```text
과실비율 판례 검색에서 각 모델의 기본/native 벡터를 사용할 때,
어떤 임베딩 모델이 가장 좋은 retrieval 품질을 내며
품질이 비슷한 경우 어떤 모델이 더 저렴하고 운영하기 쉬운가?
```

모델이 출력한 cosine similarity 절대값은 서로 비교하지 않는다. 모델마다 점수 분포가 다르므로 **동일한 Ground Truth에 대한 검색 순위**로 비교한다.

---

## 2. 먼저 확정할 결론

### 2.1 판례 데이터만 사용한다

이번 계획은 판례 데이터 전용이다.

```text
포함: traffic_precedents 과실비율 판례
제외: 심의사례, 법령, 약관, 일반 교통 문서
```

심의사례 임베딩 실험은 별도 계획과 별도 평가셋으로 수행한다. 판례와 심의사례는 문서 구조와 사용자 검색 의도가 다르므로 같은 qrels로 평가하지 않는다.

### 2.2 현재 987건과 8,334청크를 기준선으로 동결한다

전처리, 1차 분류·검증, 2차 분류·검증, RAG 최종 적합성 검수를 거쳐 `rag_eligibility=ready`가 된 987건을 사용한다. 이 987건에서 생성한 최신 `precedent_chunking_v2` 8,334청크가 현재 기준선이다.

실험 실행 전 파일 SHA-256을 기록한다. 실행 중 RunPod나 모델별 코드에서 청크 본문을 수정하거나 재청킹하지 않는다.

### 2.3 모델만 독립 변수로 둔다

```text
독립 변수: embedding model과 그 모델의 공식 입력 adapter

통제 변수:
- 판례 987건
- chunk_id 8,334개
- embedding_text
- 평가 query와 qrels
- vector dimension = 모델 manifest의 기본/native 차원
- cosine distance
- pgvector exact scan
- 검색 후 사건 단위 중복 제거 규칙
- 평가 지표와 선정 규칙
```

### 2.4 사례 단위 평가를 1차, 청크 단위 평가를 2차로 둔다

한 판례에 `holding`, `summary`, `reasoning` 등 여러 청크가 존재한다. 관련 판례의 다른 청크가 검색된 경우를 완전 오답으로 처리하면 모델 품질을 잘못 평가할 수 있다.

따라서 다음 순서로 평가한다.

```text
1차: 정답 case_id가 상위 결과에 들어왔는가
2차: 정답 chunk_id와 기대 chunk_type이 상위에 배치됐는가
```

### 2.5 정식 50개 중 10개를 먼저 파일럿 라벨링한다

공통 평가셋은 총 50개다. 사고군별 1개씩 선정한 10개로 relevance 기준과 qrels 형식을 먼저 합의하고, 같은 기준으로 나머지 40개를 라벨링한다. 파일럿 10개도 승인 후에는 정식 50개 점수에 포함한다.

모델 adapter의 shape, prefix, NaN/Inf를 확인하는 기술 smoke에는 이 10개 query 문장을 재사용할 수 있다. 다만 파일럿 정답 성능을 보고 특정 모델의 instruction이나 전처리를 조정하지 않는다.

2026-07-15 현재 파일럿 10개를 포함한 50개 1차 작성본은 별도 `ground_truth` 폴더에 만들었다.

```text
etl/fault_cases/evaluation/precedent/embedding_ab/v1/ground_truth/
  precedent_qrels_v1.jsonl
  ground_truth_manifest.json
  ground_truth_labeling_report.md
```

`ground_truth`는 정답지 산출물 폴더명이다. 현재 qrels에는 50개 Query의 사실관계 재검수 결과를 반영했으며, 모델 A/B 실행 직전에 query·qrels·corpus·chunk SHA가 manifest와 일치하는지 확인한다.

### 2.6 이 실험에는 Hybrid 요소를 넣지 않는다

BM25, sparse vector, BGE-M3의 sparse/ColBERT 출력, metadata boost, reranker, Neo4j를 사용하지 않는다. BGE-M3는 **dense native 1024차원 출력만** 사용한다.

---

## 3. 현재 데이터 상태

### 3.1 전처리부터 RAG 적합성 검수까지의 현행 상황

현재 판례 파이프라인은 다음 단계까지 진행됐다.

```text
원본 수집
  -> 정상/실패 레코드 분리
  -> 표준 필드 정리와 텍스트 정규화
  -> 주문/이유 구조화
  -> 중복 제거
  -> 교통사고 관련 1차 분류/검증
  -> 과실비율 관련 2차 분류/검증
  -> 2차 검증에 RAG 코퍼스 최종 적합성 검수 보완
  -> rag_eligibility=ready 987건 확정
  -> precedent_chunking_v2 8,334청크 생성
```

`과실비율_판단문`은 검수용 annotation으로 활용할 수 있지만, 규칙으로 생성한 `과실비율_근거`를 임베딩 본문에 추가하지 않는다. 사람이 만든 해석성 근거가 검색어와 과도하게 맞아 검색 순위를 왜곡할 수 있기 때문이다.

### 3.2 판례 수 확정 과정

| 단계 | 결과 |
|---|---:|
| 2차 과실비율 증거 검증 통과 | 1,006건 |
| 사건명으로 확정 가능한 비교통 오탐 제외 | 19건 |
| 최종 `rag_eligibility=ready` | 987건 |
| 최신 청킹에 반영된 case_id | 987건 |
| 최종 청크 | 8,334개 |

19건은 근로자지위·해고, 의료과오, 학교안전 공제, 주주지위, 정비 용역대금, 가족운전자 특약처럼 사건명만으로 과실비율 교통판례가 아님을 확정할 수 있는 사례다.

교통 표현이 약하거나 보험·연금·절차 쟁점이 함께 있다는 이유만으로는 판례를 제거하지 않았다. 검색 recall을 보존하기 위해 포함하되 `rag_review_flags`로 관리한다.

### 3.3 실험 입력 파일

최종 판례:

```text
etl/fault_cases/artifacts/traffic_precedents_output/
  traffic_prec_fault_ratio_rag_verified/
    01_fault_ratio_rag_ready_cases.jsonl
```

최신 청크와 청킹 리포트:

```text
etl/fault_cases/artifacts/traffic_precedents_output/
  precedent_chunking_v2/
    fault_ratio_precedent_chunks_v2.jsonl
    fault_ratio_precedent_chunking_v2_report.json
```

삭제된 이전 `traffic_prec_fault_ratio_verified` 산출물과 `precedent_embedding/before_embedding` 코드는 현재 실험 입력이나 실행 코드로 사용하지 않는다. Native-6 A/B/n 코드는 공통 runner 경로에 작성한다.

### 3.4 최신 청크 검증 결과

2026-07-15 기준 로컬 파일을 다시 확인한 결과다.

| 검증 항목 | 결과 |
|---|---:|
| ready 판례 수 | 987 |
| 청크의 고유 case_id | 987 |
| ready에는 있으나 청크에는 없는 case_id | 0 |
| 청크에만 있는 예상 밖 case_id | 0 |
| 전체 chunk_id | 8,334 |
| 중복 chunk_id | 0 |
| 빈 `chunk_text` | 0 |
| 최대 `chunk_text` 길이 | 1,200자 |
| 최대 `embedding_text` 길이 | 1,296자 |
| 청크 JSONL 파일 크기 | 약 37.37MiB |
| 전체 `embedding_text` 문자 수 | 6,966,372자 |

청크 유형:

| `chunk_type` | 개수 |
|---|---:|
| `holding` | 801 |
| `summary` | 796 |
| `reasoning` | 6,491 |
| `main_text_fallback` | 246 |

길이 분포:

| 텍스트 | median | P95 | max |
|---|---:|---:|---:|
| `chunk_text` | 920자 | 1,166자 | 1,200자 |
| `embedding_text` | 952자 | 1,198자 | 1,296자 |

### 3.5 품질 플래그는 제외 조건이 아니라 분석 축이다

| 품질 플래그 | 건수 | 실험에서의 처리 |
|---|---:|---|
| `missing_holding_and_summary` | 186 | reasoning 검색 성능을 별도 확인 |
| `missing_reason_uses_main_text_fallback` | 42 | fallback 청크 검색 실패율 확인 |
| `missing_structured_fault_ratio` | 642 | 구조화 필드가 없어도 본문 증거가 있는 ready 사례이므로 포함 |
| `needs_traffic_case_review` | 210 | 전체 점수와 별도로 slice metric 산출 |
| `very_long_reason` | 5 | 분할 청크의 순위와 중복 노출 확인 |

이 플래그가 있다는 이유로 987건을 다시 300여 건으로 줄이지 않는다. 전체 987건을 검색 코퍼스로 유지하고 모델별 실패가 특정 플래그에 집중되는지 분석한다.

### 3.6 아직 완료되지 않은 것

```text
완료:
- 최종 판례 987건 확정
- 최신 공통 청크 8,334개 생성
- 청크 무결성 검증
- Native-6 후보와 모델별 기본/native 차원 확정

미완료:
- 6개 tokenizer 길이 audit
- 공통 50개 평가셋 확정 및 파일럿 10개 qrels 합의
- qrels 이중 검수
- 6개 모델 × 전체 3회 임베딩 생성
- pgvector A/B 적재와 exact 검색
- 모델별 점수·비용 비교
```

즉, 데이터 준비와 계획은 진행됐지만 **임베딩 모델 A/B 자체는 아직 실행하지 않았다.**

---

## 4. 실험 범위

### 4.1 포함

- 최신 ready 판례 987건 전체
- 최신 공통 청크 8,334개 전체
- 6개 임베딩 모델
- 모델별 공식 기본/native 차원
- PostgreSQL + pgvector
- cosine distance 기반 dense retrieval
- exact scan 기반 품질 비교
- 사건 단위와 청크 단위 Ground Truth 평가
- 문서 생성 비용, query 비용, latency, 저장 크기 비교
- RunPod에서 로컬 모델 4개 직접 추론

### 4.2 제외

- 심의사례 데이터
- BM25와 keyword score
- Hybrid RAG
- BGE-M3 sparse/ColBERT 출력
- Neo4j와 Graph-RAG
- metadata/사고유형 boost
- cross-encoder 또는 LLM reranker
- HNSW/IVFFlat 근사 인덱스에 의한 1차 품질 비교
- Track A 이후 같은 모델의 차원 축소·MRL 비교
- 규칙으로 생성한 과실비율 근거의 임베딩 본문 삽입
- 답변 생성 LLM 품질 평가

HNSW와 차원 비교는 모델 후보를 1~2개로 줄인 뒤 별도 실험으로 수행한다.

---

## 5. 비교 모델과 선정 근거

### 5.1 최종 후보 6개

| model_key | 모델 | 제공 방식 | 기본/native 차원 |
|---|---|---|---:|
| `openai_small_native_1536` | `text-embedding-3-small` | OpenAI API | 1,536 |
| `openai_large_native_3072` | `text-embedding-3-large` | OpenAI API | 3,072 |
| `qwen3_06b_native_1024` | `Qwen/Qwen3-Embedding-0.6B` | RunPod self-host | 1,024 |
| `qwen3_4b_native_2560` | `Qwen/Qwen3-Embedding-4B` | RunPod self-host | 2,560 |
| `bge_m3_dense_native_1024` | `BAAI/bge-m3` | RunPod self-host | 1,024 |
| `e5_large_native_1024` | `intfloat/multilingual-e5-large` | RunPod self-host | 1,024 |

### 5.2 모델별 공식 특성과 주의점

| 모델 | 공식 특성 | 이번 실험의 주의점 |
|---|---|---|
| OpenAI 3-small | 작은 다국어 embedding 모델, $0.02/1M input tokens | 축소 인자를 보내지 않고 기본 1,536차원 검증 |
| OpenAI 3-large | OpenAI의 고성능 embedding 모델, $0.13/1M input tokens | 축소 인자를 보내지 않고 기본 3,072차원 검증 |
| BGE-M3 | 1024차원, 100개 이상 언어, 최대 8192 tokens, MIT | sparse와 ColBERT 출력 금지, dense vector만 저장 |
| Qwen3-Embedding-0.6B | 0.6B, 최대 1024차원, 32K context, Apache-2.0 | query instruction을 고정하고 document에는 붙이지 않음 |
| Qwen3-Embedding-4B | 4B, native 2560차원 | 0.6B와 동일 instruction·pooling 계약 사용 |
| multilingual-e5-large | 약 0.6B, 1024차원, 다국어, MIT | 최대 512 tokens와 `query:`/`passage:` prefix를 반드시 준수 |

공식 참고 자료:

- [OpenAI text-embedding-3-small](https://developers.openai.com/api/docs/models/text-embedding-3-small)
- [OpenAI text-embedding-3-large](https://developers.openai.com/api/docs/models/text-embedding-3-large)
- [OpenAI embedding dimensions 안내](https://openai.com/index/new-embedding-models-and-api-updates/)
- [BAAI/bge-m3 model card](https://huggingface.co/BAAI/bge-m3)
- [Qwen/Qwen3-Embedding-0.6B model card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)
- [Qwen/Qwen3-Embedding-4B model card](https://huggingface.co/Qwen/Qwen3-Embedding-4B)
- [intfloat/multilingual-e5-large model card](https://huggingface.co/intfloat/multilingual-e5-large)

### 5.3 Qwen3-Embedding-8B 제외 근거

Qwen 공식 모델 카드의 다국어 MTEB 평균은 4B가 69.45, 8B가 70.58로 차이가 1.13점이다. 반면 파라미터 수는 4B에서 8B로 2배이고 native 벡터 차원은 2,560에서 4,096으로 60% 증가한다. 판례는 8,334개로 세 코퍼스 중 가장 크며 이를 3회 독립 실행하므로, 8B 추가 시 GPU 메모리·처리 시간·벡터 저장량·검색 연산량 증가가 가장 크게 누적된다.

따라서 본 계획은 설계 단계에서 Qwen3-4B를 Qwen 계열 품질 상한 대표로 확정하고 8B는 공식 6개 모델 비교에서 제외한다. 이는 실행 결과를 보고 탈락시킨 것이 아니며, 8B가 필요하면 6개 모델의 정식 순위에 부분 결과를 섞지 않고 별도 후속 확장 실험으로 수행한다. 근거는 [Qwen3-Embedding-4B 공식 모델 카드](https://huggingface.co/Qwen/Qwen3-Embedding-4B)와 [Qwen3-Embedding-8B 공식 모델 카드](https://huggingface.co/Qwen/Qwen3-Embedding-8B)다.

### 5.4 키와 비용의 경계

```text
OpenAI 2개:
- OPENAI_API_KEY 필요
- OpenAI embedding input token 비용 발생

Hugging Face 공개 모델 4개:
- OpenAI key 불필요
- 별도 모델 API 사용료 없음
- RunPod GPU와 storage 사용료 발생
- 공개 가중치 다운로드에는 일반적으로 Hugging Face key가 필수 아님
```

다운로드 제한 때문에 `HF_TOKEN`을 사용할 경우 read-only 토큰을 RunPod Secret 또는 환경변수로만 전달한다. 토큰을 코드, JSONL, manifest, shell history에 저장하지 않는다.

---

## 6. 공정 비교 규칙

### 6.1 모든 모델이 공유할 값

```text
corpus cases             = 987
document chunks          = 8,334
document input field     = embedding_text
final queries            = 50
dimension                = model manifest의 기본/native 차원
distance                 = cosine
raw retrieval depth      = 50 chunks
case-collapsed depth     = 10 cases
primary evaluation       = case-level
secondary evaluation     = chunk-level
pgvector quality search  = exact scan
```

### 6.2 허용되는 모델별 차이

모델 공식 사용법에 포함된 query/document prefix와 instruction은 허용한다. 이것을 제거하면 해당 모델을 잘못 사용하는 비교가 된다.

허용되는 차이는 adapter에 한정한다.

```text
- OpenAI dimensions 파라미터
- Qwen query instruction
- E5 query/passage prefix
- BGE-M3 공식 dense encode 방식
- 모델별 tokenizer와 공식 max_length
```

모델마다 다른 keyword를 추가하거나, 사고유형·과실비율 정답을 prompt에 넣거나, 특정 모델만 다른 청크를 사용하지 않는다.

### 6.3 vector 정규화와 저장 dtype

- OpenAI 출력은 공식적으로 L2 normalized vector다.
- 로컬 5개 모델은 adapter에서 `normalize_embeddings=True` 또는 동등한 L2 normalize를 적용한다.
- GPU 추론은 `fp16`을 사용하되 저장 전 `float32` 배열로 변환한다.
- 저장 전 각 vector의 norm, NaN/Inf, dimension을 검사한다.
- pgvector 검색은 `<=>` cosine distance를 사용한다.

정규화 검증의 허용 오차는 실행 코드에 고정하고 manifest에 기록한다. cosine 검색 순위가 핵심이므로 모델 간 cosine similarity 값의 크기는 성능 점수로 사용하지 않는다.

### 6.4 재현성 규칙

- 모델 이름만 기록하지 않고 Hugging Face commit SHA 또는 OpenAI model ID를 기록한다.
- Python, CUDA, PyTorch, transformers, sentence-transformers, FlagEmbedding 버전을 기록한다.
- query instruction, prefix, batch size, max_length, dtype를 모델 manifest에 기록한다.
- 같은 `run_id` 안에서는 중간에 모델 설정을 바꾸지 않는다.
- OOM으로 batch를 변경하면 기존 부분 결과를 폐기하고 해당 모델 전체를 같은 batch 설정으로 다시 생성한다.

---

## 7. 문서 임베딩 입력

### 7.1 사용할 필드

현재 청크 JSONL의 다음 필드를 그대로 사용한다.

```text
embedding_text
```

`embedding_text`는 대체로 다음 구조다.

```text
판례명: {사건명}
문서구역: {판시사항|판결요지|이유|판례본문 대체}
사건종류: {사건종류명}
{해당 chunk_text}
```

이 구조는 청크 본문만 넣는 것보다 사건명과 문서구역이라는 최소 문맥을 보존한다. 반면 모델이 정답을 쉽게 맞히도록 규칙 생성한 과실비율 근거나 keyword를 추가하지 않는다.

### 7.2 코퍼스 동결 manifest

실행 전에 다음 값을 생성한다.

```json
{
  "corpus_version": "fault_ratio_precedent_chunks_v2",
  "case_count": 987,
  "chunk_count": 8334,
  "source_sha256": "...",
  "ready_cases_sha256": "...",
  "chunk_ids_sha256": "...",
  "embedding_text_sha256": "...",
  "created_at": "2026-07-15T00:00:00+09:00"
}
```

RunPod 결과를 회수할 때도 이 SHA와 `chunk_id` 순서를 대조한다. input SHA가 다르면 같은 A/B run으로 합치지 않는다.

---

## 8. tokenizer 길이 audit와 중단 조건

### 8.1 왜 embedding 전에 audit하는가

현재 최대 `embedding_text`는 1,296자다. 문자 수와 token 수는 같지 않으며 한국어 tokenizer마다 분할 결과가 다르다. 특히 multilingual-E5-large의 최대 길이는 512 tokens이므로 **silent truncation 여부를 실제 tokenizer로 확인해야 한다.**

### 8.2 audit 대상

8,334개 document와 정식 query 50개에 대해 다음을 저장한다.

```text
model_key
record_type
record_id
token_count_before_special_tokens
token_count_after_special_tokens
model_max_length
would_truncate
```

요약 리포트에는 모델별 min, median, P90, P95, P99, max, 초과 건수를 기록한다.

### 8.3 E5 512 tokens 게이트

```text
초과 0건:
  현재 8,334청크로 그대로 A/B 진행

초과 1건 이상:
  현재 corpus v2는 그대로 동결
  OpenAI small/large, Qwen, BGE의 정식 A/B는 계속 진행
  E5는 명시적 truncation 건수를 기록한 legacy 참고 후보로만 평가하고 winner 자격 제외
  E5까지 동일 정보량으로 다시 비교하려면 모든 모델 공통 재분할 corpus v3를 만든 별도 후속 run 수행
```

E5만 자르고 다른 모델에는 긴 원문을 준 결과를 공정한 6개 모델 종합 순위에 넣는 것은 금지한다. 참고 점수에는 `exploratory_truncated=true`, overflow count와 영향 문서 ID를 기록한다.

부득이하게 E5 truncation baseline을 별도로 실행할 수는 있지만 결과에 `exploratory_truncated=true`를 표시하고 최종 우승 모델 선정에서는 제외한다.

### 8.4 OpenAI token audit

OpenAI 입력은 `tiktoken`으로 사전 계산하고 API 응답의 `usage.total_tokens`와 대조한다. API 요청 하나의 input token 합계가 제한을 넘지 않도록 문자 개수가 아닌 token 합계로 request batch를 구성한다.

---

## 9. 검색 query 입력 스키마

### 9.1 서비스 입력과 검색 입력을 구분한다

서비스 Input Schema에서 임베딩 검색에 사용하는 기본 필드는 다음이다.

```text
agent_input.query_text
```

예시:

```json
{
  "raw_user_text": "신호 없는 교차로에서 저는 직진 중이었고 상대 차량은 오른쪽에서 진입했습니다. 보험사는 제 과실을 70이라고 하는데 이해가 안 됩니다.",
  "query_text": "신호 없는 교차로에서 사용자 차량은 직진, 상대 차량은 우측에서 진입한 사고"
}
```

`raw_user_text`는 서비스 원문과 query 정규화 품질을 검토하기 위해 보관한다. 기본 pgvector 검색에는 `query_text`만 넣는다.

`vision_evidence`, `insurer_claim`, `ocr_evidence`를 이번 기본 query에 자동 결합하지 않는다. 어떤 필드를 결합할지는 query construction 실험의 대상이며 임베딩 모델 A/B와 섞지 않는다.

### 9.2 query 파일과 qrels를 분리한다

query 원본:

```json
{
  "query_id": "fault_common_q01",
  "split": "test",
  "raw_user_text": "신호 없는 교차로에서 저는 직진 중이었고 상대 차량은 오른쪽에서 진입했습니다.",
  "query_text": "신호 없는 교차로에서 사용자 차량은 직진, 상대 차량은 우측에서 진입한 사고",
  "intent_group": "fact_pattern",
  "accident_type": "신호 없는 교차로 충돌",
  "difficulty": "medium",
  "annotation_status": "frozen"
}
```

판례 qrels는 심의사례 qrels와 같이 사건·청크 판정 1건당 한 행인 flat 구조로 기록한다. 한 Query에 정답 판례가 여러 개면 같은 `query_id`가 반복된다.

```json
{
  "query_id": "fault_common_q01",
  "accident_group": "signalized_intersection",
  "judgment_status": "has_relevant_document",
  "case_id": "110371",
  "case_number": "93다57520",
  "chunk_id": "110371:fault_ratio_precedent_v2:reasoning:de81bc1781c1",
  "relevance": 3,
  "matched_facts": ["신호기 있는 교차로", "진행신호 직진", "적색신호 직진"],
  "different_facts": [],
  "reason": "사고 사실관계와 핵심 과실 쟁점이 직접 일치",
  "ground_truth_version": "precedent_qrels_v1"
}
```

정답이 없는 Query도 행을 생략하지 않는다.

```json
{
  "query_id": "fault_common_q33",
  "judgment_status": "no_relevant_document",
  "negative_control": true,
  "reason": "판례 코퍼스에서 relevance 2 이상 판례를 확인하지 못함",
  "ground_truth_version": "precedent_qrels_v1"
}
```

평가 실행 시 flat qrels를 `case_id` 기준 사건 평가와 `chunk_id` 기준 청크 평가에 각각 집계한다. Query 원본과 정답을 별도 파일로 유지하면 임베딩·검색 코드가 정답을 참조하는 실수를 막을 수 있다.

---

## 10. 평가셋 50개 설계

### 10.1 라벨링 단계

| 단계 | 개수 | 용도 | 승인 후 최종 점수 포함 |
|---|---:|---|---:|
| `pilot` | 10 | 사고군별 relevance 기준과 qrels 형식 합의 | 예 |
| 전체 판정본 | 50 | 파일럿 10개와 나머지 40개를 합친 판정본 | 예 |
| `final test` | 50 | 동결된 정식 모델 비교 | 예 |

파일럿과 전체 판정본은 모델 결과가 아니라 판례 원문과 중립 후보군으로 작성한다. 2026-07-16 현재 50개 Query 전부를 판정했으며, relevance 2 이상 직접 정답 21개, relevance 1 참고 판례만 존재 13개, 관련 판례 없음 16개다. 총 42판정과 서로 다른 판례 31개를 확보했다. 실험 직전에 50개 전체의 query/qrels SHA를 동결하고 6개 모델을 전체 3회 실행한다.

### 10.2 공통 query를 고정하고 판례 정답지를 독립 작성한다

다음 순서를 사용한다.

```text
1. 세 코퍼스 공통 사용자 사고 query 50개를 먼저 고정
2. 판례 987건과 청크 8,334개에서 문자 n-gram TF-IDF와 issue_tags로 Query당 상위 30개 사건 후보 수집
3. 유턴·점멸신호·도로진입 등 핵심 관계를 전체 청크에서 추가 규칙 검색
4. 판례 원문에서 사고 사실관계와 법원의 과실 판단 확인
5. 관련 case_id와 대표 chunk_id 및 relevance 0~3을 annotation
6. 판례에 relevance 1 이상 판례도 없으면 no_relevant_document를 명시
7. 두 검수자가 qrels와 query의 대응 관계 및 경계판정을 확인
8. 합의본 query/qrels SHA를 만들고 동결
```

검색 결과를 먼저 보고 정답을 만드는 방식은 평가셋이 특정 모델에 오염될 수 있으므로 금지한다. 다만 모델 결과에서 기존 qrels 누락을 발견하면 전체 모델명을 가린 상태에서 원문을 재검수하고 qrels 버전을 올린 뒤 **6개 모델의 세 반복 모두 재평가**한다.

후보 생성에는 OpenAI, BGE-M3, Qwen3, E5 임베딩 결과를 사용하지 않는다. 현재 판정본의 manifest에 `embedding_model_outputs_used=false`를 기록했다.

### 10.3 정식 50개 사고군 층화

| 사고군 | 기존 100개 | 정식 50개 |
|---|---:|---:|
| 신호 교차로 | 15 | 8 |
| 무신호 교차로 | 15 | 7 |
| 회전·차로규칙 | 10 | 5 |
| 차로변경·추돌 | 15 | 8 |
| 주차·도로진입 | 8 | 4 |
| 회전교차로 | 7 | 3 |
| 고속도로 | 8 | 4 |
| 이륜차 | 12 | 6 |
| 보행자 | 5 | 3 |
| 자전거·PM | 5 | 2 |
| 합계 | 100 | 50 |

정확히 절반이 0.5건이 되는 사고군은 총합이 50이 되도록 올림과 내림을 분산했다. 자전거·PM 2개는 자전거 1개와 개인형 이동장치 1개로 구성한다.

`no_relevant_document`를 제외하고 가능하면 30개 이상의 서로 다른 판례를 사용한다. 동일 판례는 원칙적으로 2개 Query 이하를 목표로 하되, 사용자 관점 전환이나 당사자 유형 비교처럼 사실관계상 필요한 경우 최대 3개까지 허용하고 Query별 점수를 독립 집계한다. 하나의 사건 문체에 모델이 과적합된 것처럼 보이는 현상을 줄이기 위해 판례별 사용 횟수도 결과에 함께 보고한다.

### 10.4 query 의도와 난이도 층화

사고 유형 외에도 다음 의도를 섞는다.

| 의도 | 예시 | 목표 |
|---|---|---:|
| 사실관계 중심 | 진행 방향, 충돌 관계, 도로 구조 | 20 |
| 과실 쟁점 중심 | 전방주시, 안전거리, 일시정지, 선진입 | 15 |
| 유사 판례 요청 | 특정 상황과 유사한 법원 판단 검색 | 10 |
| 불완전·구어체 정규화 | 원문은 장황하지만 query_text는 핵심 사실만 유지 | 5 |

공통 질문지의 `difficulty`는 코퍼스에 정답이 있는지가 아니라 **질문 문장과 사고 사실관계 자체의 복잡도**를 뜻한다. 코퍼스별 exact 정답 존재 여부와 실제 검색 난이도는 각 코퍼스 qrels에서 별도 관리한다.

| 난이도 | 개수 | 비율 | 기준 |
|---|---:|---:|---|
| easy | 25 | 50% | 한 가지 주된 충돌 관계와 우선·위반 쟁점으로 설명 가능 |
| medium | 21 | 42% | 둘 이상의 진행조건이나 추가 수정요소를 함께 비교해야 함 |
| hard | 4 | 8% | 복합 우선관계, 다차로 회전, 안전조치 또는 희소 당사자 조건이 결합됨 |
| 합계 | 50 | 100% | - |

hard는 `q11`, `q34`, `q38`, `q50`만 유지한다. 표본이 4개이므로 hard slice에서 query 1개는 25%p에 해당한다. 따라서 hard slice는 최종 모델 순위를 단독 결정하는 지표가 아니라 실패 유형을 설명하는 진단 지표로 사용한다.

`no_relevant_document`는 hard와 동일한 개념이 아니다. pgvector top-K가 항상 결과를 반환하는 현재 실험에서 정답 없는 query를 Hit@K, MRR, nDCG 분모에 그대로 포함하면 모든 모델에 동일한 0점을 부여한다. 따라서 표준 retrieval 지표에서는 분리하되, strict positive와 negative의 Top-1 cosine similarity 분포 및 AUROC·AUPRC를 별도 보고한다. 임계값 기반 false-positive rate와 abstention F1은 최종 test와 분리된 dev set에서 모델별 임계값을 정한 경우에만 계산한다.

파일럿 10개의 `query_id`, `raw_user_text`, `query_text`는 유지했다. 아직 qrels가 없는 `q05`, `q07`, `q15`, `q18`는 이중 위반, 보행자신호, 시야제한처럼 검색 난도를 불필요하게 높이던 조건을 줄여 medium 문장으로 단순화했다. 나머지는 질문 문장을 유지하고 공통 난이도 정의에 따라 재분류했다. 사건번호, 법원명, 판례명 전체, 원문의 고유한 긴 문구를 query에 넣어 정답을 쉽게 만드는 것은 계속 금지한다.

### 10.5 relevance 등급

| 등급 | 의미 |
|---:|---|
| 3 | 사고 사실관계와 핵심 과실 쟁점이 직접 일치하는 정답 |
| 2 | 주요 사실이나 법적 쟁점이 상당 부분 일치하는 관련 판례 |
| 1 | 주제는 관련되지만 핵심 사실관계가 다른 참고 판례 |
| 0 | 비관련 |

Hit와 MRR의 정답 기준은 relevance 2 이상으로 둔다. 따라서 relevance 2 이상 정답이 있는 21개 Query만 Hit/MRR 분모에 포함한다. nDCG는 relevance 1 이상 판례가 있는 34개 Query에서 계산한다. `no_relevant_document` 16개는 표준 검색 지표에서 제외하고 별도 negative 진단에 사용한다. 기준은 평가 전에 확정하고 리포트에서 바꾸지 않는다.

```text
nDCG gain = 2^relevance - 1
discount = 1 / log2(rank + 1)
unjudged document = relevance 0
동일 case_id의 여러 청크는 검색순위가 가장 높은 결과 하나만 유지
```

### 10.6 keyword 기반 채점은 보조 검수만 한다

`expected_keywords`는 query 작성과 qrels 검수 보조로 저장할 수 있다. 그러나 다음과 같은 휴리스틱 점수는 최종 모델 점수로 사용하지 않는다.

```text
키워드 2개 포함 = 1.0
키워드 1개 포함 = 0.5
```

법률 문서는 같은 사실을 다른 표현으로 기술할 수 있고, keyword가 있어도 법적 맥락이 다를 수 있기 때문이다.

---

## 11. 모델별 입력 adapter

### 11.1 adapter 고정표

| 모델 키 | document 입력 | query 입력 | 출력 처리 |
|---|---|---|---|
| `openai_small_native_1536` | 원본 `embedding_text` | 원본 `query_text` | 축소 인자 없이 1,536차원 검증 |
| `openai_large_native_3072` | 원본 `embedding_text` | 원본 `query_text` | 축소 인자 없이 3,072차원 검증 |
| `qwen3_06b_native_1024` | 원본 `embedding_text` | 고정 instruction + `query_text` | native 1,024, L2 normalize |
| `qwen3_4b_native_2560` | 원본 `embedding_text` | 동일 instruction + `query_text` | native 2,560, L2 normalize |
| `bge_m3_dense_native_1024` | 원본 `embedding_text` | 원본 `query_text` | dense native 1,024만 선택, L2 normalize |
| `e5_large_native_1024` | `passage: {embedding_text}` | `query: {query_text}` | native 1,024, max 512, L2 normalize |

### 11.2 Qwen query instruction

정식 실험 전에 다음 한 문장으로 고정한다.

```text
Instruct: Given a Korean traffic-accident description, retrieve the most relevant Korean traffic-accident fault-liability precedents
Query: {query_text}
```

instruction은 query에만 적용하고 document에는 적용하지 않는다. 기술 smoke 단계에서는 문법이나 공식 API 사용 오류만 수정할 수 있으며 파일럿 relevance나 정식 test 성능을 보고 내용을 조정하지 않는다.

### 11.3 E5 prefix

```text
query: {query_text}
passage: {embedding_text}
```

대소문자와 공백까지 adapter test로 고정한다. E5의 prefix는 선택적 prompt가 아니라 모델이 학습된 retrieval 입력 형식이므로 사용한다.

### 11.4 BGE-M3 사용 범위

```text
사용: dense_vecs 1024
미사용: lexical_weights, colbert_vecs
```

BGE-M3가 sparse와 multi-vector를 지원한다는 이유로 이번 모델이 추가 점수를 얻어서는 안 된다. Hybrid 가능성은 모델 선정 배경으로 설명할 수 있지만 이번 pgvector dense 점수에는 반영하지 않는다.

---

## 12. RunPod 실행 설계

### 12.1 왜 로컬 PC가 아니라 RunPod인가

로컬 5개 모델은 공개 가중치를 직접 내려받아 GPU에서 실행한다. CPU에서도 실행할 수 있지만 8,334개 문서와 query를 다섯 모델·세 repeat로 처리하면 실행 시간이 길고 batch 조건을 안정적으로 맞추기 어렵다.

RunPod를 사용하면 다음을 고정할 수 있다.

- CUDA GPU와 VRAM
- Python/PyTorch 환경
- 모델별 batch와 dtype
- 모델 다운로드 cache
- 실행 시간과 실제 GPU 비용
- 결과 파일과 manifest

RunPod에서는 **임베딩 생성만** 수행한다. PostgreSQL 비밀번호를 전달하거나 외부에서 로컬 DB에 접속시키지 않는다.

### 12.2 Pods를 쓰고 Serverless는 쓰지 않는 이유

이번 작업은 실시간 API가 아니라 로컬 모델 4개를 세 repeat에서 순차 실행하는 batch job이다.

```text
선택: RunPod Pods, on-demand 1대
미선택: Serverless endpoint
```

Pods가 적합한 이유:

- 모델 cache를 `/workspace`에 유지하면서 로컬 모델 4개를 연속 실행하고 repeat별 결과를 분리할 수 있다.
- endpoint image와 autoscaling 설정이 필요 없다.
- 설치, tokenizer audit, 기술 smoke, 전체 embedding을 한 환경에서 재현할 수 있다.
- Pod 생성부터 종료까지 실제 비용을 한 run으로 기록하기 쉽다.

첫 정식 실행에는 spot/interruptible을 쓰지 않는다. 중단 복구 코드를 검증한 뒤 재실행 비용을 줄이는 용도로만 검토한다.

### 12.3 기존 OJH Pod 보호와 공통 Pod 인계 원칙

> [!CAUTION]
> RunPod 계정에 이미 존재하는 **`SKN27-3T-OJH`는 OJH 작업 전용 보호 대상**이다. 임베딩 A/B 실험에서는 이 Pod를 절대 사용하거나 변경하지 않는다. 목록에서 이름을 확인하는 것 외에는 해당 행, 상세 화면, 더보기 메뉴를 열지 않는다.

`SKN27-3T-OJH`에 대해 금지하는 작업은 다음과 같다.

```text
- Connect, Web Terminal, SSH, Jupyter 접속
- 로그 열람, 파일 업로드, 명령 실행
- Start, Stop, Restart, Reset, Redeploy
- GPU, template, 환경변수, container disk 설정 변경
- 기존 Pod volume 또는 network volume 연결·분리·재사용
- Clone, Edit, Terminate, Delete
```

공통 Pod는 새로 만드는 것이 기본이 아니다. 공통 계획 11.2의 우선순위대로 `SKN27-embedding-ab-*` 등 임베딩 A/B용 기존 Pod가 있으면 사용자에게 Start와 JupyterLab 열기를 요청하여 그 Pod를 사용한다. 기존 임베딩 Pod가 없고 보호 대상 `SKN27-3T-OJH`만 있을 때에만 `00_preflight_orchestrator`가 신규 Pod를 생성한다. 기존 Pod의 GPU 불가·migration·GPU 변경은 사용자 확인 전 자동으로 처리하지 않는다. 이전 Track B vector·검색·점수는 재사용하지 않고, Track A 결과 경로를 새로 만든다.

`00_preflight_orchestrator`만 위 선택 분기와 필요 시 신규 Pod 생성을 수행한다. 판례 모델 작업은 manifest에 등록된 공통 Pod를 인계받아 자기 모델의 `batch_03_precedent`만 실행하며, Pod를 새로 만들거나 독자적으로 종료하지 않는다. 재사용·신규 여부와 무관하게 Pod Stop, Terminate, Delete는 결과 회수와 SHA 검증 후 사용자 확인 없이는 수행하지 않는다.

신규 리소스 식별 규칙:

```text
Pod name: SKN27-3T-EMBED-AB-ALL-<작업자이니셜>-<YYYYMMDD>
예시: SKN27-3T-EMBED-AB-ALL-HR-20260715
금지 이름: SKN27-3T-OJH 또는 OJH가 포함된 이름
Container disk: 신규 생성
Pod volume: 신규 40GB 생성
Network volume: 연결하지 않음
기존 Storage/Volume: 선택하지 않음
```

신규 Pod 생성 직후 아래 값을 로컬 `runpod_resource_manifest.json`에 기록한다.

```json
{
  "protected_pod_name": "SKN27-3T-OJH",
  "protected_pod_id": "c7ool8ji5f17fj",
  "experiment_pod_name": "SKN27-3T-EMBED-AB-ALL-<작업자이니셜>-<YYYYMMDD>",
  "experiment_pod_id": "신규 Pod ID",
  "experiment_volume_id": "신규 volume ID",
  "created_by": "작업자",
  "created_at": "ISO-8601 시각"
}
```

접속, 중지, 종료, 삭제 전에는 화면의 Pod 이름과 Pod ID가 manifest의 `experiment_pod_name`, `experiment_pod_id`와 모두 일치하는지 확인한다. 하나라도 다르거나 대상이 불명확하면 **아무 작업도 수행하지 않고 중단**한다. 특히 `SKN27-3T-OJH`에는 비용 절감 목적이라도 Stop이나 Terminate를 실행하지 않는다.

### 12.4 데이터 크기와 GPU 요구량

현재 코퍼스:

```text
8,334 chunks
6,966,372 embedding_text characters
37.37 MiB input JSONL
```

Track A float32 vector의 원시 저장량:

```text
6개 모델 native 차원 합계 = 10,240
반복당 약 325.5 MiB raw document vectors
전체 3회 약 976.6 MiB raw document vectors
```

GPU 선택은 저장 파일 크기보다 모델 파라미터, 입력 token 길이, batch size와 attention 메모리로 결정한다. Qwen3-4B를 로컬 최대 모델로 한 번에 하나씩 로드하고 smoke에서 안정적인 batch를 확정한다.

### 12.5 GPU 최종 권장안

2026-07-15 RunPod 공식 가격 페이지의 표시값 기준이다. 실제 가격과 재고는 배포 지역, Cloud 유형, 시점에 따라 달라질 수 있으므로 Pod 생성 직전에 다시 확인한다.

| 용도 | GPU | VRAM | 현재 표시 가격 | 판정 |
|---|---|---:|---:|---|
| **기본 선택** | `A40` | 48GB | 약 $0.44/hr | Qwen3-4B를 최대 모델로 하는 로컬 모델 4개 실행 후보 |
| 재고 대안 | 동급 48GB GPU | 48GB | 배포 시 확인 | A40 재고가 없을 때 가격·VRAM 재승인 후 사용 |
| 속도 우선 | `RTX 4090` | 24GB | 약 $0.69/hr | 설치보다 연산 시간을 줄이는 것이 중요할 때 |
| 과사양 | `A100/H100` | 80GB 이상 | $1.39/hr 이상 | A40 48GB smoke가 통과하면 불필요 |

최종 기본값:

```text
RunPod Community Cloud
On-demand Pod
A40 48GB x 1 또는 동급 48GB GPU
모델 1개씩 순차 실행
```

Qwen3 4B를 로컬 최대 모델로 하며 A40 48GB 또는 4B smoke를 통과한 동급 GPU를 기본 후보로 한다. 실제 재고와 가격은 Deploy 직전에 다시 확인하고 manifest에 고정한다.

RunPod 공식 참고 자료:

- [RunPod GPU 가격](https://www.runpod.io/pricing)
- [Pod 선택 가이드](https://docs.runpod.io/pods/choose-a-pod)
- [Pods 과금과 storage 가격](https://docs.runpod.io/pods/pricing)
- [Pod storage 종류](https://docs.runpod.io/pods/storage/types)

### 12.6 Community Cloud와 Secure Cloud 선택 기준

이번 입력이 공개 판례이며 개인정보·실제 사용자 사고 원문·비공개 qrels가 없다는 점을 검증한 경우 Community Cloud를 사용한다.

다음 중 하나라도 포함되면 Secure Cloud 또는 사내 GPU를 사용한다.

```text
- 비공개 사용자 사고 원문
- 식별 가능한 개인정보
- 내부 평가자 정보
- 운영 DB dump
- 운영 API key 또는 DB credential
```

RunPod에 전달하는 query는 합성·익명화 평가 query만 허용한다. `OPENAI_API_KEY`와 DB 비밀번호는 RunPod에 전달하지 않는다.

### 12.7 권장 신규 Pod 구성

```text
Cloud: Community Cloud, 보안 게이트 실패 시 Secure Cloud
Billing: On-demand
Pod name: SKN27-3T-EMBED-AB-ALL-<작업자이니셜>-<YYYYMMDD>
GPU count: 1
GPU: A40 48GB 또는 동급 48GB GPU
Template: RunPod 공식 PyTorch template
Container disk: 신규 30GB
Volume disk: 신규 40GB, /workspace
Network volume: 없음
Python: 3.11
Inference dtype: fp16
Vector output dtype: float32
```

공식 template의 이름, image tag 또는 digest, CUDA, PyTorch 버전은 실행 시점 manifest에 고정한다. 계획서에 임의의 최신 tag를 적어 자동 변경되게 하지 않는다.

스토리지 배치:

```text
/workspace/input/       동결 corpus와 query
/workspace/code/        A/B 실행 코드와 requirements lock
/workspace/hf-cache/    Hugging Face model cache
/workspace/checkpoints/ 재시작용 진행 상태
/workspace/output/      parquet와 model manifest
```

Container disk는 임시 OS와 package 설치에 사용한다. 모델 cache와 결과는 이번 실험을 위해 새로 만든 Pod의 `/workspace` volume에 둔다. `SKN27-3T-OJH` 또는 다른 기존 Pod의 volume은 검색하거나 선택하거나 연결하지 않는다. 이번 일회성 실험에는 여러 Pod 사이에서 이동 가능한 Network Volume이 필요 없다.

Volume은 Pod를 중지해도 비용이 계속 발생할 수 있다. 로컬 모델 4개·세 코퍼스·전체 3회 결과를 모두 로컬로 회수하고 SHA를 검증한 뒤 공통 오케스트레이터만 manifest에 기록한 **신규 공통 Pod와 신규 volume**을 Terminate/Delete한다. 판례 작업은 종료하지 않으며, 이 절차는 `SKN27-3T-OJH` 및 그 리소스에는 절대 적용하지 않는다.

### 12.8 권장 실행 환경

최소 package 계열:

```text
torch
transformers>=4.51.0,<5
sentence-transformers>=2.7.0
FlagEmbedding
accelerate
numpy
pandas
pyarrow
safetensors
```

Qwen model card의 최소 요구 버전을 만족하되 정식 실행에서는 lock 파일과 `pip freeze`를 함께 보존한다.

FlashAttention 2는 첫 실행에 강제하지 않는다. 현재 데이터 규모에서는 설치 실패 가능성을 늘릴 만큼 필수적인 최적화가 아니다. 공식 PyTorch template의 SDPA로 먼저 성공시키고 실제 병목이 확인될 때만 별도 run에서 적용한다.

### 12.9 모델별 시작 batch

token audit 통과 후 다음 값으로 기술 smoke를 수행한다.

| 모델 | dtype | 시작 document batch | query batch | max_length 원칙 | OOM 대응 |
|---|---|---:|---:|---|---|
| Qwen3 0.6B | fp16 | 64 | 32 | audit 최대 token 이상, 공식 한도 이하 | 32 -> 16 -> 8 |
| BGE-M3 | fp16 | 64 | 32 | audit 최대 token 이상, 공식 한도 이하 | 32 -> 16 -> 8 |
| multilingual-E5-large | fp16 | 64 | 32 | 512 고정, 초과 0건만 진행 | 32 -> 16 -> 8 |

batch 64는 목표가 아니라 시작값이다. 각 모델은 20개 문서로 peak VRAM을 먼저 측정하고 안정적인 가장 큰 batch를 고정한다. 최종 문서 embedding 전체에서 batch를 바꾸지 않는다.

### 12.10 RunPod 실행 순서

```text
1. 공통 Query, 판례 corpus, qrels SHA와 token audit를 로컬에서 완료
2. input, code, lock file, run manifest만 전송하고 DB credential, OpenAI key, qrels는 제외
3. 공통 오케스트레이터가 생성·검증한 `SKN27-3T-EMBED-AB-ALL-*` Pod manifest 확인
4. 자기 model lock을 획득하고 다른 모델이 실행 중이 아님을 확인
5. 같은 모델의 `batch_01_fault_standard`, `batch_02_review_case` 완료 상태와 hash 확인
6. 모델을 유지한 채 `batch_03_precedent` 20문서 smoke로 shape/norm/VRAM 검사
7. 판례 document 8,334개와 판례 adapter query 50개 encode
8. count/dimension/finite/norm/chunk_id/hash 검증 후 corpus_key/model_key 경로에 원자 저장
9. 해당 모델의 세 코퍼스 완료표를 갱신하고 model unload, CUDA cache 정리, lock 해제
10. 다음 로컬 모델 채팅으로 공통 Pod를 인계
11. 로컬 모델 4개 각 repeat 종료 후 output 전체 SHA-256을 로컬 결과와 대조
12. 로컬 pgvector A/B schema에 corpus_key/model_key를 분리해 적재
13. 판례 qrels로 exact cosine 평가
14. 로컬 모델 4개·세 코퍼스·전체 3회 산출물 회수 완료 후 공통 오케스트레이터만 신규 Pod와 volume 종료
```

한 모델의 결과가 완성되기 전에는 최종 파일명으로 이동하지 않는다. 임시 파일에 저장한 뒤 count와 SHA 검증을 통과하면 atomic rename한다.

### 12.11 RunPod 예상 시간과 예산

실행 시간과 비용은 로컬 모델 4개·세 코퍼스 전체 3회를 기준으로 timed benchmark 후 산정한다. 판례 8,334개가 대부분의 처리량을 차지하지만 비용과 생존 시간은 판례 전용 Pod가 아니라 공통 experiment 전체로 기록하고 사용자 승인 상한을 적용한다.

| Pod | 2시간 | 3시간 | 판단 |
|---|---:|---:|---|
| A40 | 약 $0.88 | 약 $1.32 | 기본 예산 |
| 동급 48GB GPU | 배포 시 확인 | 배포 시 확인 | A40 재고 대안 |
| RTX 4090 | 약 $1.38 | 약 $2.07 | 속도 우선 |

위 금액은 표시된 GPU 시간당 가격의 단순 환산이며 storage 비용은 별도다. RunPod Pods는 모델 download와 검증을 포함한 공통 Pod 전체 생존 시간을 비용으로 기록한다. 코퍼스별 비용이 필요하면 모델별 실측 GPU 초를 이용해 사후 배분하되, 판례 작업 채팅은 Pod를 종료하거나 비용을 독립 확정하지 않는다.

### 12.12 RunPod 결과 검증

각 모델별 필수 검증:

```text
document vectors = 8,334
query vectors = final test 50 (pilot 10 포함)
dimension = model_manifest.native_dimension
duplicate chunk_id = 0
missing chunk_id = 0
NaN/Inf = 0
zero norm = 0
source corpus SHA = local manifest와 동일
model revision = 계획된 revision과 동일
```

하나라도 실패하면 해당 모델을 pgvector에 적재하지 않는다.

---

## 13. OpenAI API 실행 설계

### 13.1 실행 위치와 key 관리

OpenAI 두 모델은 로컬 신뢰 환경에서 실행한다.

```text
사용: OPENAI_API_KEY 환경변수 또는 프로젝트 secret manager
금지: .py, .md, JSONL, manifest에 key 저장
RunPod로 key 전송 금지
```

### 13.2 호출 규칙

```text
model = text-embedding-3-small 또는 text-embedding-3-large
dimensions parameter = 생략, small 1536 / large 3072 검증
input = embedding_text 또는 query adapter 결과
encoding_format = float
```

문자 개수만으로 고정 batch를 만들지 않는다. 사전 계산한 token 합계를 기준으로 API request batch를 구성한다. rate limit과 일시 오류에는 지수 backoff를 적용한다. 성공 cache는 같은 repeat 안의 네트워크 재시도에만 사용하며 repeat 사이에는 embedding 응답을 재사용하지 않는다.

각 응답의 다음 값을 기록한다.

```text
request_id
model
dimensions
input_count
usage.total_tokens
latency_ms
retry_count
created_at
```

### 13.3 OpenAI 비용 계획

현재 공식 단가:

| 모델 | 1M input tokens |
|---|---:|
| `text-embedding-3-small` | $0.02 |
| `text-embedding-3-large` | $0.13 |

정확한 총비용은 token audit과 API `usage.total_tokens`로 계산한다.

```text
document_cost = document_total_tokens / 1,000,000 x model_price
query_cost = query_total_tokens / 1,000,000 x model_price
```

현재 696만 자의 한국어 입력은 문자 수만으로 token을 정확히 환산할 수 없다. 계획 예산을 5M~10M tokens 범위로 잡으면 다음 정도다.

| 모델 | 5M tokens | 10M tokens |
|---|---:|---:|
| small | 약 $0.10 | 약 $0.20 |
| large | 약 $0.65 | 약 $1.30 |

이 표는 예산 상한을 잡기 위한 범위이며 최종 보고서에는 추정치가 아니라 실제 usage와 청구 단가를 사용한다.

---

## 14. 코드와 산출물 구조

### 14.1 새 A/B 코드 경로

기존 `before_embedding`을 수정해 억지로 재사용하지 않고 공통 A/B 패키지의 판례 adapter에 새 코드를 둔다.

사람이 관리하는 평가 원본은 코드 폴더와 분리한다.

```text
etl/fault_cases/evaluation/precedent/embedding_ab/v1/
  pilot/
    qrels_precedents_pilot_v1.jsonl
    pilot_manifest.json
    pilot_labeling_report.md
  ground_truth/
    precedent_qrels_v1.jsonl
    ground_truth_manifest.json
    ground_truth_labeling_report.md
```

```text
etl/fault_cases/src/embedding_ab_shared/
  common/
    paths.py
  track_b_5models_fixed1024/             # 과거 5모델·1024차원 재현 전용, 수정 금지
    run_ab.py
    runpod_local_models.sh
    runpod_bundles/
  track_a_6models_native_3repeats/       # 판례 포함 Native-6 공식 실행 전용
    config.py
    model_registry.py
    run_native7.py
    run_openai_models.py
    run_local_models.py
    runpod_native7_3repeats.sh
    validate_vectors.py
    integrate_results.py
    build_final_reports.py
    requirements.lock
    corpora/precedent/
      build_corpus_snapshot.py
      adapter.py
      load_pgvector.py
      evaluate_retrieval.py
      build_corpus_report.py
    tests/
```

Track B 코드는 과거 고정 1024차원 결과 재현용으로 동결하고, Track A가 `run_ab.py`, `runpod_local_models.sh` 또는 과거 RunPod bundle을 import·복사·실행하지 않는다. 새 판례 결과는 Track A 코드에서만 생성하여 `artifacts/embedding_ab_shared/track_a_6models_native_3repeats/` 아래에 저장한다.

판례용으로 새로 만드는 `.md`, README, 표, 보고서와 오류 안내는 한국어로 작성한다. 모든 Python/Bash 파일은 한국어 파일 설명과 함수 docstring을 가지며, 매개변수·반환값·예외·부작용과 각 주요 실행 줄의 의미·필요 이유·실패 영향을 한국어 주석으로 설명한다. 고유 모델명·API 필드·경로·CLI만 원문 영문을 유지하며 공통 계획 7.1.1의 검토 실패 기준을 그대로 적용한다.

판례 전처리·청킹·운영 검색 코드는 기존 `traffic_precedents` 패키지가 계속 소유한다. 공통 A/B 실행 코드만 `embedding_ab_shared`에 두어 인정기준·심의사례와 같은 폴더 및 CLI 계약을 사용한다.

### 14.2 실행 산출물 경로

```text
etl/fault_cases/artifacts/embedding_ab_shared/track_a_6models_native_3repeats/run_<experiment_group_id>/repeat_<NN>/
  00_input/
    common/queries.jsonl
    common/query_manifest.json
    corpora/precedent/
      documents.jsonl
      corpus_manifest.json
  00_manifest/
    run_group_manifest.json
    run_state.json
    runpod_resource_manifest.json
    runpod_execution_lock.json
    model_manifests/<model_key>.json
    eval_snapshots/precedent/
      queries.jsonl
      qrels.jsonl
      ground_truth_manifest.json
  01_token_audit/<model_key>/precedent/token_length_audit.json
  02_vectors/<model_key>/precedent/
    document_embeddings.parquet
    query_embeddings.parquet
    artifact_manifest.json
    failures.jsonl
  03_retrieval/precedent/<model_key>/
    raw_top50.jsonl
    primary_top10.jsonl
    retrieval_manifest.json
  04_metrics/precedent/
    scores.csv
    query_details.jsonl
    bootstrap.json
    cost_latency.json
    error_analysis.csv
    cosine_similarity_summary.csv
    cosine_similarity_query_details.jsonl
```

판례 코사인 유사도는 `raw_top50.jsonl`에만 보관하지 않는다. 모델·회차별 Top-1 유사도 평균·중앙값·p95, 최초 정답 사건 유사도, Top-1 정답·오답 유사도 평균과 그 차이, `no_relevant_document` Query의 Top-1 유사도를 별도 집계한다. 이 값과 `cosine_similarity = 1 - cosine_distance` 계산식을 공통 스코어 비교표와 분석 리포트에 한국어 컬럼 설명과 함께 표시하되 모델 선정용 nDCG@10 평균에는 섞지 않는다.

평가셋과 qrels는 사람이 관리하는 versioned source이고, vector와 retrieval 결과는 재생성 가능한 artifact다. 두 종류를 같은 폴더에 섞지 않는다. 판례만의 별도 legacy run 루트를 만들지 않으며 공통 계획 7.1의 동일 폴더·파일명 계약을 따른다. 세 코퍼스 통합 최종 문서는 아래 두 파일이며 공통 계획 14장의 이름과 생성 게이트를 그대로 사용한다.

```text
run_<experiment_group_id>/05_report/pgvector_3코퍼스_임베딩_모델_AB_스코어_비교표.md
run_<experiment_group_id>/05_report/pgvector_3코퍼스_임베딩_모델_AB_분석_리포트.md
run_<experiment_group_id>/05_report/corpora/precedent/corpus_result.md
```

### 14.3 모델 manifest 필수 필드

```json
{
  "run_id": "precedent_embedding_ab_20260715_001",
  "experiment_group_id": "embedding_native7_3repeat_YYYYMMDD_HHMMSS",
  "run_group_id": "embedding_native7_3repeat_YYYYMMDD_HHMMSS_repeat_01",
  "repeat_id": "repeat_01",
  "model_key": "qwen3_06b_native_1024",
  "provider": "huggingface_runpod",
  "model_id": "Qwen/Qwen3-Embedding-0.6B",
  "model_revision": "commit_sha",
  "dimension": 1024,
  "dtype_inference": "float16",
  "dtype_output": "float32",
  "normalize": true,
  "query_instruction": "...",
  "document_prefix": null,
  "query_prefix": null,
  "max_length": 512,
  "batch_size": 64,
  "corpus_sha256": "...",
  "query_sha256": "...",
  "vector_file_sha256": "..."
}
```

모델에 해당하지 않는 항목은 `null`로 기록한다. 실제 Qwen max_length는 audit 후 확정한 값을 넣는다.

---

## 15. pgvector 적재 구조

### 15.1 별도 실험 schema

운영 테이블이나 과거 1536차원 embedding을 덮어쓰지 않는다.

```sql
CREATE SCHEMA IF NOT EXISTS precedent_embedding_ab;

CREATE TABLE precedent_embedding_ab.document_vectors__<model_key> (
    run_id              text        NOT NULL,
    repeat_id           text        NOT NULL,
    model_key           text        NOT NULL,
    chunk_id            text        NOT NULL,
    case_id             text        NOT NULL,
    chunk_type          text        NOT NULL,
    embedding_dim       integer     NOT NULL CHECK (embedding_dim = <native_dimension>),
    embedding_vector    vector(<native_dimension>) NOT NULL,
    source_text_hash    text        NOT NULL,
    model_revision      text        NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, repeat_id, model_key, chunk_id)
);

CREATE INDEX document_vectors_lookup_idx
ON precedent_embedding_ab.document_vectors__<model_key> (run_id, repeat_id, model_key);
```

1차 품질 평가 테이블에는 HNSW/IVFFlat vector index를 만들지 않는다. 8,334개 규모에서 exact scan으로 모델 자체 순위를 먼저 비교한다.

### 15.2 적재 검증

모델별 SQL 검증:

```text
row count = 8,334
distinct chunk_id = 8,334
distinct case_id = 987
embedding_dim = 1,024 only
source_text_hash mismatch = 0
NULL vector = 0
```

### 15.3 exact 검색

모델별 query vector로 raw top-50 chunks를 가져온다.

```sql
SELECT
    case_id,
    chunk_id,
    chunk_type,
    embedding_vector <=> :query_vector::vector AS cosine_distance
FROM precedent_embedding_ab.document_vectors
WHERE run_id = :run_id
  AND model_key = :model_key
ORDER BY embedding_vector <=> :query_vector::vector
LIMIT 50;
```

동일 distance가 발생하면 결과 재현성을 위해 `chunk_id`를 2차 정렬키로 둔다.

### 15.4 사건 단위 중복 제거

raw top-50에서 같은 `case_id`가 여러 번 나오면 첫 등장 순위를 해당 사건의 순위로 사용한다.

```text
raw chunk top-50
  -> distance 오름차순
  -> 같은 case_id는 가장 높은 청크 1개만 유지
  -> unique case top-10 생성
```

raw chunk 결과도 버리지 않는다. 청크 평가와 실패 분석에 사용한다.

---

## 16. 평가 지표

### 16.1 1차 모델 선정 지표: 사건 단위

| 지표 | 의미 |
|---|---|
| `Case Hit@1` | 1위 판례가 relevance 2 이상 정답인가 |
| `Case Hit@5` | 상위 5개 판례 안에 정답이 있는가 |
| `Case Hit@10` | 상위 10개 판례 안에 정답이 있는가 |
| `Case Recall@5/10` | 여러 정답 판례 중 상위 K에 검색된 비율 |
| `Case MRR@10` | 첫 정답 판례가 얼마나 위에 등장하는가 |
| `Case nDCG@10` | relevance 0~3의 더 중요한 판례가 위에 배치되는가 |

주요 순위 기준은 `Case nDCG@10`, `Case MRR@10`, `Case Hit@5` 순서다.

### 16.2 2차 지표: 청크 단위

- `Chunk Hit@1/5/10`
- `Chunk Recall@5/10`
- `Chunk MRR@10`
- `Chunk nDCG@10`
- 정답 사건 내 첫 청크의 `chunk_type`
- 같은 사건이 raw top-10을 과도하게 차지하는 비율

사건은 맞았지만 `holding`만 검색되고 사고 사실과 과실 판단이 있는 `reasoning`이 나오지 않는지 확인한다.

현재 qrels의 `chunk_id`는 사건별 대표 증거 청크다. 같은 사건 안의 모든 관련 청크를 완전 라벨링한 구조가 아니므로 Chunk 지표는 진단용으로만 보고하고 최종 모델 순위를 결정하지 않는다. 정식 Chunk nDCG가 필요하면 별도 `precedent_chunk_qrels_v1.jsonl`에 관련 청크를 모두 라벨링한다.

### 16.3 Negative Query 진단

```text
strict positive: relevance 2 이상 정답 Query 21개
weak-only: relevance 1만 있는 Query 13개
negative: relevance 1 이상 판례가 없는 Query 16개
```

- strict positive 대 negative의 Top-1 similarity AUROC·AUPRC
- 모델별 negative 최대 similarity 평균·중앙값·최댓값
- weak-only 13개는 이진 분류 지표에서 제외하고 별도 보고
- 6개 모델 × 3회에서 negative 16개 Top-10 합집합을 블라인드 pooling하여 누락 정답 재검수

### 16.4 품질 플래그 slice

전체 점수 외에 다음 그룹을 분리해 계산한다.

```text
rag_review_flags 없음
needs_traffic_case_review
missing_holding_and_summary
main_text_fallback 사용
structured_fault_ratio 있음/없음
chunk_type holding/summary/reasoning/fallback
query difficulty easy/medium/hard
```

전체 평균이 높아도 특정 어려운 그룹을 거의 검색하지 못하는 모델이면 실패 사례로 명시한다.

### 16.4 통계적 불확실성

50개 query에서 모델 점수 차이는 표본에 따라 흔들릴 수 있다.

- query 단위 paired bootstrap 1,000회
- `nDCG@10`, `MRR@10`, `Hit@5` 차이의 95% confidence interval
- 모델 간 승/패 query 수
- query별 reciprocal rank 차이

같은 50개 query를 모든 모델이 공유하므로 독립 표본 검정보다 paired 비교가 적절하다.

### 16.5 latency

다음 시간을 분리한다.

```text
document embedding total time
query embedding cold start
query embedding warm p50/p95
pgvector exact search p50/p95
query embedding + DB search end-to-end p50/p95
```

OpenAI API network latency와 RunPod warm model latency는 환경이 다르므로 한 숫자로 섞지 않는다. retrieval 품질은 동일 조건으로 비교하고 운영 latency는 제공 방식별 현실적인 값으로 별도 보고한다.

### 16.6 비용

다음 비용을 구분한다.

```text
초기 document embedding 비용
평가 query embedding 비용
운영 query 1,000건 예상 비용
RunPod 최초 환경 구성 포함 batch 비용
RunPod model cache가 있는 재실행 비용
vector와 index storage
```

RunPod의 일회성 batch 비용을 그대로 운영 query 비용이라고 부르지 않는다. self-host 모델을 실시간 서비스하려면 상시 Pod, autoscaling, cold start 정책이 추가로 필요하다.

---

## 17. 실행 단계

### Phase 0. 데이터 동결과 무결성 검증

1. ready 987건과 청크 8,334개의 수를 다시 확인한다.
2. case_id 집합이 정확히 일치하는지 검사한다.
3. 중복/빈 chunk_id, 빈 embedding_text를 검사한다.
4. corpus manifest와 SHA-256을 생성한다.
5. 이후 입력이 변경되면 새 corpus version과 새 run_id를 사용한다.

완료 조건:

```text
case mismatch = 0
duplicate chunk_id = 0
empty embedding_text = 0
manifest 생성 완료
```

### Phase 1. tokenizer preflight

1. 6개 tokenizer와 OpenAI token counter를 준비한다.
2. document 8,334개와 query 50개의 token 수를 계산한다.
3. 모델별 초과 건수와 분포를 저장한다.
4. E5 512 초과가 있으면 초과 목록을 저장하고 E5만 legacy 참고 후보로 전환한다. 다른 여섯 모델의 본 실험은 계속한다.

완료 조건:

```text
silent truncation = 0
token audit artifact 저장
모델별 max_length 확정
```

### Phase 2. 평가셋 작성과 동결

1. 공통 query 50개를 사고군·당사자·난이도로 층화해 동결한다.
2. 사고군별 1개인 파일럿 10개의 판례 qrels를 먼저 작성한다.
3. 파일럿 검수의 q11 대표 청크 수정사항을 반영한다.
4. 같은 기준으로 나머지 40개를 작성하고 `ground_truth/precedent_qrels_v1.jsonl`을 50개 Query, 58개 flat 판정 행으로 만든다.
5. 사실관계 재검수에서 15개 판례를 relevance 1로 판정하고 q09의 누락 판례 91다42883을 relevance 2로 추가한다.
6. 불일치를 합의하고 승인 버전과 SHA를 동결한다.

2026-07-16 현재 1~5는 완료했다. 현재 qrels SHA는 manifest에 갱신했으며, 실험 실행 직전에 입력 파일 변경 여부를 다시 확인한 뒤 동결한다.

완료 조건:

```text
pilot query = 10 (final test에 포함)
remaining query = 40
final test query = 50
test distinct relevant cases >= 30
unreviewed qrels = 0
```

### Phase 3. 모델 adapter 기술 smoke

1. 모델마다 문서 20개와 파일럿 query 10개를 임베딩해 기술 검증만 수행한다.
2. dimension, norm, NaN/Inf, token truncation을 확인한다.
3. query/document adapter가 공식 형식인지 확인한다.
4. RunPod GPU peak VRAM과 안정 batch를 확정한다.
5. 전체 50개 검색 점수를 계산하기 전에 설정을 동결한다.

완료 조건:

```text
7 models x model-specific native dimension
invalid vectors = 0
adapter configuration frozen
```

### Phase 4. 전체 임베딩 생성

1. `repeat_01`, `repeat_02`, `repeat_03`마다 OpenAI small/large의 판례 8,334 document와 query 50개를 새로 생성한다.
2. RunPod 로컬 모델 4개도 각 repeat마다 공통 Pod에서 인정기준, 심의사례, 판례 순으로 전체를 새로 생성한다.
3. 각 model-repeat의 `precedent` 경로에 document 8,334개와 query 50개를 저장하며 이전 repeat vector를 재사용하지 않는다.
4. repeat_id·model_key·corpus_key별 파일 SHA와 model manifest를 생성한다.
5. 모든 결과를 로컬로 회수하되 54개 공통 실행 완료 전에는 Pod를 종료하지 않는다.

완료 조건:

```text
model-repeat 21 x 8,334 = 175,014 document vectors
model-repeat 21 x 50 = 1,050 query vectors
missing/duplicate/invalid = 0
```

### Phase 5. pgvector exact retrieval

1. 별도 A/B schema의 모델별 native 차원 테이블에 6개 모델 × 3회를 적재한다.
2. 각 query마다 raw chunk top-50을 저장한다.
3. case_id 중복 제거 후 case top-10을 저장한다.
4. SQL 결과의 row 수와 정렬 재현성을 검증한다.

### Phase 6. 정식 평가와 실패 분석

1. 승인된 final test 50개 전체로 사건/청크 지표를 계산한다.
2. paired bootstrap을 수행한다.
3. 품질 플래그와 사고유형 slice를 계산한다.
4. 모델별 실패 query와 상위 오답 판례를 검토한다.
5. 세 repeat 개별 점수와 모델별 평균·표준편차·min/max·rank 안정성을 계산한다.
6. 비용과 latency를 합친 최종 보고서를 작성한다.

### Phase 7. 후속 실험 후보 확정

1. 품질·비용 기준으로 모델 1개를 최종 선택한다.
2. 필요하면 품질 상위 2개만 HNSW 운영성 비교에 남긴다.
3. 선택 모델로 차원 비교 실험을 별도 계획한다.

---

## 18. 모델 선정 규칙

### 18.1 실험 전 탈락 조건

다음 중 하나라도 발생하면 해당 run은 정식 비교에서 제외한다.

- document/query 누락 또는 중복
- model manifest의 native_dimension과 다른 vector
- NaN, Inf, zero vector
- silent truncation
- 동결 corpus/query SHA 불일치
- 공식 adapter 미적용
- test 결과를 본 뒤 adapter 변경
- 한 모델만 다른 청크 또는 qrels 사용

### 18.2 품질 우선 선정

```text
1순위: Case nDCG@10
2순위: Case MRR@10
3순위: Case Hit@5
4순위: hard query와 review-flag slice의 안정성
```

### 18.3 사실상 동률 처리

다음 두 조건을 모두 만족하면 `Case nDCG@10`은 실무상 동률로 본다.

```text
절대 점수 차이 <= 0.02
paired bootstrap 95% CI가 0을 포함
```

동률이면 다음 순서로 선택한다.

```text
1. 운영 query 비용
2. 초기 corpus embedding 비용
3. warm query latency
4. 배포와 장애 대응 복잡도
5. 라이선스와 데이터 정책 적합성
```

예를 들어 OpenAI large가 small보다 `nDCG@10`을 0.01만 개선하고 통계적으로 불확실하다면 small을 선택할 수 있다. 반대로 self-host 모델이 조금 저렴하더라도 검색 품질이 명확하게 낮으면 비용만으로 선택하지 않는다.

### 18.4 최종 보고 방식

보고서에는 다음 세 결론을 구분한다.

```text
품질 1위 모델
가격 대비 권장 모델
프로젝트 최종 채택 모델 1개와 채택 이유
```

최종 채택은 사전에 정한 동률 규칙으로 결정한다. 임의의 가중합 점수 하나로 품질과 비용을 숨기지 않는다.

---

## 19. 결과 보고서 구조

```text
1. 실험 목적과 제외 범위
2. corpus/query/qrels 버전과 SHA
3. 6개 모델, 세 repeat와 adapter 설정
4. tokenizer 길이 audit
5. RunPod/OpenAI 실행 환경
6. 사건 단위 전체 지표
7. 청크 단위 보조 지표
8. 사고 유형·난이도·quality flag slice
9. paired bootstrap과 동률 판정
10. 실패 query와 상위 오답 사례
11. document/query latency
12. 실제 OpenAI token 비용과 RunPod 청구액
13. 모델별 장단점
14. 최종 채택 모델과 후속 차원 실험
```

모델 평균 점수만 제시하지 않고 query별 raw top-10과 실패 사례를 함께 보존해야 재검수가 가능하다.

---

## 20. 위험 요소와 대응

| 위험 | 영향 | 대응 |
|---|---|---|
| E5 512 tokens 초과 | 모델별 입력 정보량 차이 | 전체 tokenizer audit, E5는 명시적 truncation 참고 점수만 생성하고 winner 제외. 재청킹은 새 corpus version의 후속 실험으로 분리 |
| qrels를 모델 결과로 작성 | 특정 모델 편향 | 중립 후보군과 판례 원문으로 작성, 이중 검수, test 동결 |
| 판례 하나의 여러 청크가 top-K 점유 | 사건 다양성 저하 | raw top-50 보존 후 case_id collapse top-10 |
| OpenAI 차원 축소 실수 | Track A 공정 비교 실패 | `dimensions` 축소 인자 금지, 1,536/3,072 적재 CHECK |
| BGE sparse/ColBERT 혼입 | Hybrid 효과가 모델 점수에 혼입 | dense vector만 허용 |
| RunPod OOM 후 설정 혼합 | 재현성 손상 | 모델 전체 재실행, batch 변경 이력 기록 |
| `SKN27-3T-OJH` 오조작 | 다른 팀원 작업 중단 또는 데이터 손실 | 해당 행·메뉴·접속을 전면 금지하고 공통 오케스트레이터만 신규 Pod/volume 생성, 모든 관리 작업 전 name+ID 이중 대조 |
| Community Cloud에 민감정보 전송 | 보안 문제 | 공개·익명 데이터 gate, 실패 시 Secure Cloud |
| Pod를 Stop만 하고 방치 | storage 비용 지속 | 로컬 5모델·세 코퍼스·3회 결과 SHA 확인 후 공통 오케스트레이터가 Pod와 volume Terminate |
| 예전 1536차원 코드/테이블 혼용 | 잘못된 결과 적재 | 새 `ab_test` 코드와 별도 pgvector schema 사용 |
| cosine 절대값 비교 | 모델별 score calibration 왜곡 | 순위 기반 metric만 모델 비교에 사용 |

---

## 21. 완료 체크리스트

### 데이터

- [x] ready 판례 987건 확인
- [x] 청크 8,334개 확인
- [x] ready/chunk case_id 불일치 0건
- [x] ground_truth qrels의 case_id/chunk_id 참조 오류 0건
- [x] 중복·빈 chunk_id 0건
- [x] corpus/query/chunk/qrels SHA-256 manifest 생성

### 평가셋

- [x] 공통 정식 query 50개 층화 선정
- [x] 판례 파일럿 query 10개 draft 작성
- [x] 파일럿 검수에서 확인된 q11 대표 청크 2건 수정
- [x] 나머지 40개를 포함한 50개 Query, 58개 flat qrels 행 작성
- [x] 직접 정답 21개 / 참고 판례만 존재 13개 / 부정 16개 판정
- [x] relevance 3은 14행 / relevance 2는 13행 / relevance 1은 15행으로 재검수
- [x] 서로 다른 관련 판례 31개 확보
- [x] 작성 원본에 case_id와 chunk_id를 함께 기록
- [ ] 평가 코드에서 `case_id`와 `chunk_id` 기준 집계 구현
- [x] 사실관계 재검수 피드백 반영
- [x] 현재 query/qrels SHA 기록
- [ ] 실험 직전 query/qrels SHA 최종 동결

### tokenizer와 adapter

- [ ] 6개 모델 token audit 완료
- [ ] E5 512 tokens 초과 건수와 E5 winner 자격 기록
- [ ] OpenAI small 1,536 / large 3,072차원 확인(`dimensions` 축소 인자 미사용)
- [ ] Qwen query instruction 고정
- [ ] E5 `query:`/`passage:` prefix 고정
- [ ] BGE dense output만 사용

### RunPod

- [ ] 보호 대상 Pod 이름 `SKN27-3T-OJH` 확인 및 접근 금지 공유
- [ ] 기존 임베딩 A/B Pod 확인 결과와 `resource_origin=reused|new`를 manifest로 확인
- [ ] 기존 Pod면 사용자 Start·JupyterLab 열기 후 사용, 없으면 신규 Pod name/ID/volume ID를 manifest에 기록
- [ ] 보호 Pod name/ID와 선택된 experiment Pod name/ID를 `runpod_resource_manifest.json`에 기록
- [ ] 모든 접속·중지·재시작·종료 전 선택된 experiment Pod name+ID 이중 대조
- [ ] Community/Secure Cloud 데이터 gate 확인
- [ ] A40 48GB 또는 동급 on-demand 재고와 현재 가격 확인
- [ ] 공식 PyTorch template tag/digest 기록
- [ ] Container 30GB / Volume 40GB 구성
- [ ] package lock과 model revision 고정
- [ ] 20-document smoke에서 peak VRAM과 batch 확정
- [ ] model-repeat별 8,334 + 50 vectors, 판례 전체 18개 결과 검증
- [ ] 결과 회수 후 SHA 확인
- [ ] 판례 산출물 검증 후 해당 모델 완료표와 lock을 갱신하고 다음 모델 작업으로 인계
- [ ] 로컬 5모델·세 코퍼스·전체 3회 완료 후 결과 SHA를 확인하고 Pod 종료 여부를 사용자에게 확인
- [ ] `SKN27-3T-OJH` 상태가 변경되지 않았음을 최종 확인

### pgvector와 평가

- [ ] 별도 A/B schema 적재
- [ ] model-repeat별 8,334 rows와 판례 전체 175,014 rows 확인
- [ ] exact chunk top-50 저장
- [ ] case collapse top-10 저장
- [ ] 사건/청크 표준 metric 계산
- [ ] quality flag slice 계산
- [ ] paired bootstrap 1,000회
- [ ] latency와 실제 비용 기록
- [ ] 모델 선정 규칙에 따라 최종 모델 확정

---

## 22. 팀 공유용 요약

```text
판례 데이터는 전처리, 1·2차 분류/검증, RAG 적합성 검수를 거쳐
최신 ready 987건과 8,334청크까지 준비됐다.

이번 실험은 그 청크를 바꾸지 않고 최신 6개 모델을 각 기본/native 차원으로 전체 3회 실행해
pgvector exact cosine 검색 품질과 비용을 비교한다.

OpenAI small/large는 로컬에서 API로 생성하고,
Qwen3-Embedding-0.6B/4B, BGE-M3, multilingual-E5-large는
기존 `SKN27-3T-OJH`를 건드리지 않고 새로 생성한
RunPod Community Cloud A40 48GB 또는 동급 on-demand Pod 한 대에서
한 모델씩 순차 실행한다.

A40 48GB는 Qwen3-4B를 최대 모델로 하는 로컬 모델 4개 실행의 기본 후보다.
E5의 512-token 한도를 모든 청크가 통과하는지 먼저 검사하고,
초과가 있으면 E5는 명시적 truncation 참고 점수만 생성해 winner에서 제외한다.
현재 동결 코퍼스는 재청킹하지 않으며 재청킹 비교는 새 corpus version의 후속 실험으로 분리한다.

정식 50개 중 사고군별 10개를 먼저 파일럿 라벨링하고,
파일럿과 사실관계 재검수사항을 반영한 50개 판정본을 `evaluation/.../ground_truth`에 저장했다.
현재 직접 정답 21개, 참고 판례만 존재 13개, 관련 판례 없음 16개이며 서로 다른 판례는 31개다.
`case_id`와 `chunk_id` 기준으로 집계해
Case nDCG@10, MRR@10, Hit@5를 중심으로 평가한다.

품질이 사실상 동률일 때만 비용, latency, 운영 복잡도로 최종 모델을 고른다.
Hybrid, BM25, reranker, 차원 비교는 이번 실험에 포함하지 않는다.
```
