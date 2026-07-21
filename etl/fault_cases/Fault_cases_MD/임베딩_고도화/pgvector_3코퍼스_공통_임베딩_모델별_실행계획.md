# pgvector 3코퍼스 공통 임베딩 모델별 실행 계획

> 개정 기준일: 2026-07-17  
> 대상: 판례, 인정기준, 심의사례의 공통 Query 50개 기반 pgvector 임베딩 모델 A/B/n  
> 실행 단위: 임베딩 모델별 별도 작업 채팅  
> 공통 본 실험(Track A): 최신 6개 모델, 모델별 기본/native 차원, dense vector only  
> 참고 실험(Track B): `run_20260716_embedding_ab_v1`의 5개 모델·1024차원 고정 결과. 최종 모델 순위에는 합산하지 않음

---

## 1. 문서 목적

이 문서는 코퍼스별 평가 설계를 다시 설명하는 문서가 아니라, **세 코퍼스의 임베딩을 모델별 별도 채팅에서 안전하게 생성하기 위한 공통 실행 오케스트레이션 문서**다.

세 코퍼스는 공통 사용자 사고 Query 50개와 `query_id`를 공유하지만, 검색 문서와 Ground Truth는 서로 다르다. 따라서 다음 원칙을 동시에 만족해야 한다.

```text
공유:
- 공통 query_text 50개와 query_id
- 공통 최신 6개 모델
- 모델마다 공식 기본/native dimension 사용
- cosine distance
- 모델별 공식 query/document adapter
- 실행 환경과 비용 기록 형식

분리:
- 코퍼스별 document corpus
- 코퍼스별 query vector artifact
- 코퍼스별 qrels
- 코퍼스별 pgvector table 또는 corpus_key
- 코퍼스별 retrieval 결과와 평가 점수
```

이 문서의 핵심 목표는 다음 세 가지다.

1. 모델 하나를 한 번 로드한 상태에서 세 코퍼스를 작은 데이터부터 순차 batch 처리한다.
2. 모델별 별도 채팅이 같은 RunPod를 잘못 동시에 조작하거나 새 Pod를 중복 생성하지 못하게 한다.
3. 차원이 같거나 다르더라도 다른 모델 또는 다른 adapter의 벡터가 섞이지 못하게 한다.

---

## 2. 반드시 함께 읽을 세 코퍼스 계획

모델별 작업 채팅은 이 문서를 먼저 읽고, 이어서 아래 세 문서를 모두 읽는다.

- [판례 임베딩 모델 A/B 계획](판례/pgvector_판례_임베딩_모델_AB_실험계획.md)
- [인정기준 임베딩 모델 A/B 계획](인정기준/pgvector_인정기준_임베딩_모델_AB_실험계획.md)
- [심의사례 임베딩 모델 A/B 계획](심의사례/pgvector_심의사례_임베딩_모델_AB_실험계획.md)

문서별 책임 범위는 다음과 같다.

| 문서 | 소유하는 내용 |
|---|---|
| 이 공통 실행 계획 | 모델별 작업 채팅, 실행 순서, batch, 병렬 허용 범위, RunPod 소유권, 공통 산출물 규칙 |
| 판례 계획 | 판례 987건/8,334청크, 판례 adapter, 판례 qrels와 Case/Chunk 평가 |
| 인정기준 계획 | 1차 Rule 277개, 후속 evidence 3,516개, Rule qrels와 Rule 평가 |
| 심의사례 계획 | 226사례/904청크, 심의사례 adapter, review_case qrels와 Case/Chunk 평가 |

실행·Pod·모델 수·E5 overflow 처리에 관해 문서 사이에 충돌이 있으면 **이 공통 실행 계획을 우선**한다. 코퍼스 내용, 정답지, relevance, 코퍼스별 평가 지표는 각 코퍼스 계획을 우선한다. 해소되지 않은 충돌을 모델 채팅이 임의로 선택하지 않으며 `00_preflight_orchestrator`가 계획을 갱신하고 새 manifest SHA를 만든 뒤 재개한다.

---

## 3. 공통 입력과 코퍼스별 정답지

### 3.1 공통 Query 원본

```text
etl/fault_cases/evaluation/common/embedding_ab/v1/common_fault_queries_v1.jsonl
```

공통 Query는 `fault_common_q01`부터 `fault_common_q50`까지 정확히 50개다. 모델별 작업 채팅은 Query 문장, ID, 순서, 난이도, 사고군을 수정하지 않는다.

운영 Input Schema에서 임베딩의 논리 입력은 `agent_input.query_text`다. 다만 동결 평가 JSONL에서는 이 값을 최상위 `query_text`로 펼쳐 저장했으므로 runner가 실제로 읽을 필드는 다음과 같다.

```text
common_fault_queries_v1.jsonl 레코드의 query_text
```

`raw_user_text`는 검수용으로 보존하지만 기본 query 임베딩에는 사용하지 않는다. `annotation_status`, `difficulty`, `issue_tags`, `retrieval_targets`도 임베딩 문자열에 합치지 않는다.

### 3.2 코퍼스별 Ground Truth

```text
etl/fault_cases/evaluation/precedent/embedding_ab/v1/ground_truth/precedent_qrels_v1.jsonl
etl/fault_cases/evaluation/fault_standard/embedding_ab/v1/ground_truth/fault_standard_qrels_v1.2.jsonl
etl/fault_cases/evaluation/review_case/embedding_ab/v1/ground_truth/review_case_qrels_v1.jsonl
```

qrels는 임베딩 생성 입력이 아니다. 모델별 작업 채팅은 qrels를 읽어 모델 설정을 조정하거나 Query 문장을 바꾸지 않는다. RunPod 전송 bundle에도 qrels를 포함하지 않는다.

코퍼스별 qrels schema는 동일할 필요가 없으며 승인 이력을 위한 필드는 보존할 수 있다. 임베딩 runner는 qrels를 입력으로 읽지 않고, 평가 validator만 코퍼스별 manifest에 선언된 최종 상태를 검사한다. 특히 심의사례 qrels 89행의 `adjudication_status=approved`와 `label_source`는 승인·검수 이력이므로 제거하지 않는다. 상태 필드가 있는 qrels는 `draft` 또는 `reviewed` 행이 0건이어야 하고, 상태 필드가 없는 qrels는 manifest의 최종 승인 상태와 SHA로 동결 여부를 판정한다.

| qrels | 현재 계획상 상태 | 정식 실행 전 조건 |
|---|---|---|
| 판례 | 50 Query/58행, 내용 재검수 반영 | 승인 manifest SHA 재확인 |
| 인정기준 | 50 Query/111행, Rule 판정 110행 + q31 무정답 negative-control 1행 | 승인된 v1.2 manifest SHA 재확인 |
| 심의사례 | 50 Query/89행, 89행 모두 `approved` | qrels SHA `093f70b7...c6c1f`와 manifest 일치 확인 |

즉, runner와 smoke 코드는 준비할 수 있지만 **공통 Query manifest가 `approved`로 동결되고 세 정답지의 위 게이트가 모두 끝나기 전에는 유료 본 실험과 최종 점수 산출을 시작하지 않는다.**

2026-07-16 재검수 시점의 실행 게이트는 다음과 같다.

| 항목 | 재검수 결과 | 판정 |
|---|---|---|
| 공통 Query | 50행, 고유 `query_id` 50개, SHA `a50921b0...a02102` | approved 동결 완료 |
| 인정기준 v1.2 | 111행, 고유 Query 50개, JSON 오류 0, SHA `0eb20fd6...ff9343` | q13 최종 판정 반영 및 v1.2 manifest 동결 완료 |
| 심의사례 v1 | 89행, 고유 Query 50개, JSON 오류 0, SHA `093f70b7...c6c1f` | approved manifest 일치 확인 |
| 판례 v1 | 58행, 고유 Query 50개, JSON 오류 0, SHA `c44a6d8f...a7f85` | 승인 manifest SHA 일치 확인 |

위 표는 계획 검수 결과이지 본 실험 승인 선언이 아니다. 평가 원본이 다시 수정되면 고정 숫자와 SHA를 새 값으로 갱신하고 재검수한다.

### 3.3 코퍼스별 동결 입력

| corpus_key | 원천 | 본 실험 동결 산출물 | 기대 행 수 |
|---|---|---|---:|
| `fault_standard` | PostgreSQL `search.rule_search_documents`, `search_load_id=2`, `document_type='rule_summary'` | `00_input/corpora/fault_standard/documents.jsonl` | 277 |
| `review_case` | `etl/fault_cases/artifacts/review_case_output/preprocessed/review_case_chunks.jsonl` | `00_input/corpora/review_case/documents.jsonl` | 904 |
| `precedent` | `etl/fault_cases/artifacts/traffic_precedents_output/precedent_chunking_v2/fault_ratio_precedent_chunks_v2.jsonl` | `00_input/corpora/precedent/documents.jsonl` | 8,334 |

판례 ready 사건 원본 `traffic_prec_fault_ratio_rag_verified/01_fault_ratio_rag_ready_cases.jsonl`과 심의사례 `review_case_documents.jsonl`은 추적·검수용이다. 본 실험의 document embedding 행은 위 동결 청크/Rule 산출물만 사용한다. 각 snapshot은 행 수, ID 유일성, 빈 입력 0건, 입력 문자열 hash와 파일 SHA-256을 통과해야 한다.

---

## 4. 공통 본 실험 모델

### 4.1 Track A — 모델 기본 차원 공정 비교

세 코퍼스 종합 비교에는 다음 최신 6개 모델을 포함한다. `text-embedding-ada-002`는 구형 모델이므로 제외한다.

| 실행 순서 | model_key | 모델 | 기본/native 차원 | 실행 위치 | Track A |
|---:|---|---|---:|---|---:|
| 1 | `openai_small_native_1536` | `text-embedding-3-small` | 1,536 | 로컬 OpenAI API | 예 |
| 2 | `openai_large_native_3072` | `text-embedding-3-large` | 3,072 | 로컬 OpenAI API | 예 |
| 3 | `qwen3_06b_native_1024` | `Qwen/Qwen3-Embedding-0.6B` | 1,024 | 공통 RunPod(기존 임베딩 Pod 우선) | 예 |
| 4 | `qwen3_4b_native_2560` | `Qwen/Qwen3-Embedding-4B` | 2,560 | 공통 RunPod(기존 임베딩 Pod 우선) | 예 |
| 5 | `bge_m3_dense_native_1024` | `BAAI/bge-m3` | 1,024 | 공통 RunPod(기존 임베딩 Pod 우선) | 예 |
| 6 | `e5_large_native_1024` | `intfloat/multilingual-e5-large` | 1,024 | 공통 RunPod(기존 임베딩 Pod 우선) | 예 |

Track A에서는 OpenAI 요청에 `dimensions=1024`를 전달하지 않는다. 응답 차원은 small 1,536, large 3,072인지 검사한다. Qwen의 MRL 축소 옵션도 사용하지 않고 위 native 차원을 그대로 사용한다.

### 4.2 Qwen3-Embedding-8B 제외 근거

본 실험은 설계 단계의 자원·비용·효율 검토를 거쳐 Qwen 계열의 품질 상한 후보를 `Qwen3-Embedding-4B`로 확정한다. Qwen 공식 모델 카드의 다국어 MTEB 평균은 4B가 69.45, 8B가 70.58로 차이가 1.13점인 반면, 파라미터 수는 4B에서 8B로 2배이고 native 벡터 차원은 2,560에서 4,096으로 60% 증가한다. 이 증가는 문서·질의 임베딩 시간, GPU 메모리 압력, 벡터 저장량과 검색 연산량에 모두 영향을 주며, 세 코퍼스 전체를 독립 3회 실행하는 본 계획에서는 비용이 반복 증폭된다.

따라서 이번 공식 비교는 4B를 Qwen 계열의 중대형 대표로 사용하고 8B는 포함하지 않는다. 이는 8B의 품질을 부정하거나 실행 실패로 탈락시키는 결정이 아니라, 제한된 실험 예산에서 서로 다른 계열 6개 모델을 동일 조건으로 완주하고 재현성을 확보하기 위한 사전 후보 축소다. 8B 검증이 필요해지면 본 실험의 6개 모델 순위에 부분 결과를 섞지 않고 별도 후속 확장 실험으로 수행한다. 근거 자료는 [Qwen3-Embedding-4B 공식 모델 카드](https://huggingface.co/Qwen/Qwen3-Embedding-4B)와 [Qwen3-Embedding-8B 공식 모델 카드](https://huggingface.co/Qwen/Qwen3-Embedding-8B)다.

### 4.3 기존 결과 분리와 Track A 전체 독립 3회

- 기존 `run_20260716_embedding_ab_v1`은 **Track B: 1024차원 제약 환경 비교**로만 보존한다. Track A의 반복 회차, 종합 순위 또는 우승 판정에는 넣지 않는다.
- Track A는 `repeat_01`, `repeat_02`, `repeat_03`의 **전체 독립 3회**로 실행한다.
- 매 반복에서 6개 모델이 세 코퍼스의 document와 query embedding을 원문으로부터 모두 새로 생성한다. 이전 실행이나 이전 반복의 vector/parquet/retrieval/metric 재사용은 금지한다.
- Hugging Face 모델 가중치와 Python package 다운로드 cache는 재사용할 수 있지만, 생성된 embedding artifact는 재사용할 수 없다.
- 세 반복은 corpus/query/qrels/model revision/adapter/runtime lock을 동일하게 유지하며 `repeat_id`, `run_id`, 산출물 폴더와 manifest를 분리한다.

```text
반복당: 6 models x 3 corpora = 18 model-corpus 실행
전체:   18 x 3 repeats = 54 model-corpus 실행
반복당 query vectors: 900
전체 query vectors:   2,700
반복당 document vectors: 9,515 x 6 = 57,090
전체 document vectors:   57,090 x 3 = 171,270
```

세 반복 모두 277개 인정기준, 904개 심의사례, 8,334개 판례 전체를 처리한다. 축약 코퍼스로 수행한 실행은 세 정식 repeat 중 하나로 인정하지 않는다.

## 5. 데이터 batch 구성

### 5.1 1차 모델 선정용 문서 batch

공통 본 실험의 모델 하나가 처리할 문서는 다음 순서다.

| batch_id | corpus_key | 1차 문서 수 | 처리 목적 |
|---:|---|---:|---|
| `batch_01` | `fault_standard` | 277 | 가장 작은 Rule 코퍼스로 adapter와 저장 경로 조기 검증 |
| `batch_02` | `review_case` | 904 | 중간 크기 구조화 청크 검증 |
| `batch_03` | `precedent` | 8,334 | 가장 큰 판례 코퍼스 전체 처리 |
| 합계 | - | 9,515 | 모델당 1차 document vectors |

인정기준의 evidence/law/reference/usage 3,516개는 1차 공통 모델 선정에 넣지 않는다. 1차 winner 또는 상위 모델을 고정한 뒤 인정기준 계획의 Evidence Retrieval 단계에서 별도 생성한다.

작은 코퍼스부터 실행하는 이유는 파일 경로, adapter, vector shape, ID 누락 문제가 있을 때 판례 8,334개를 처리하기 전에 실패시키기 위해서다.

### 5.2 Query batch

공통 Query 문장은 같지만 산출물은 모델과 코퍼스별로 분리한다.

```text
모델당 query vectors:
  fault_standard 50
  review_case    50
  precedent      50
  합계          150

공통 6개 모델 전체:
  150 x 7 = 1,050 query vectors
```

OpenAI, BGE-M3, E5는 동일 모델·동일 adapter라면 이론적으로 Query 벡터가 같을 수 있다. 그러나 Track A에서는 코퍼스별·repeat별 artifact를 각각 새로 생성하고 hash가 같은지 보조 검증만 한다. 코퍼스 또는 repeat 사이에서 vector 파일을 복사해 재사용하지 않는다.

Qwen은 코퍼스별 retrieval instruction이 다르므로 반드시 코퍼스별 Query 벡터를 생성한다.

### 5.3 GPU에서 허용하는 batch 병렬성

`batch`는 GPU에 여러 문서를 한 번에 넣는 추론 batch를 뜻한다. 로컬 모델 4개를 동시에 실행하는 뜻이 아니다.

```text
허용:
- 현재 로드된 모델 하나의 document batch GPU 추론
- CPU tokenizer worker와 GPU inference prefetch
- 같은 모델 세 코퍼스의 연속 batch 처리

금지:
- Qwen, BGE, E5를 같은 GPU에서 동시 실행
- 모델별 별도 채팅이 같은 Pod에서 동시에 명령 실행
- 모델 하나의 최종 실행 중 batch size를 임의 변경
```

---

## 6. 모델별 별도 작업 채팅 구조

각 모델은 별도 채팅 하나가 담당한다. 모든 채팅은 같은 workspace 파일을 읽고 `run_group_id`를 공유한다.

| 작업 채팅 | 담당 모델/역할 | 실행 위치 | RunPod 관리 권한 |
|---|---|---|---|
| `00_preflight_orchestrator` | 입력 동결, 코드, manifest, smoke 승인 | 로컬 | 기존 임베딩 Pod 확인·신규 생성 분기와 종료 승인 확인 담당 |
| `01_openai_small` | OpenAI small 세 코퍼스 | 로컬 | 없음 |
| `02_openai_large` | OpenAI large 세 코퍼스 | 로컬 | 없음 |
| `03_qwen3_06b` | Qwen 0.6B 세 코퍼스 | 공통 RunPod | 지정 Pod에서 해당 모델 실행만 허용 |
| `04_bge_m3` | BGE-M3 dense 세 코퍼스 | 공통 RunPod | 지정 Pod에서 해당 모델 실행만 허용 |
| `05_e5_large` | E5-large 세 코퍼스 | 공통 RunPod | 지정 Pod에서 해당 모델 실행만 허용 |
| `06_integrate_evaluate` | pgvector 적재, 검색, 코퍼스별 평가 | 로컬 | 없음 |

### 6.1 작업 채팅 시작 시 필수 확인

각 모델 채팅은 다음을 먼저 수행한다.

```text
1. 이 공통 실행 계획 읽기
2. 판례·인정기준·심의사례 계획 읽기
3. run_group_id 확인
4. common query, 세 corpus, adapter hash 확인
5. 자기 model_key와 output 경로 확인
6. 다른 모델 task가 active인지 확인
7. 입력 SHA가 manifest와 다르면 실행하지 않고 중단
```

### 6.2 작업 채팅이 하면 안 되는 일

```text
- 공통 Query 또는 qrels 수정
- 다른 model_key의 파일 덮어쓰기
- 운영 embedding 테이블 덮어쓰기
- RunPod 신규 Pod 추가 생성
- 기존 SKN27-3T-OJH 접근
- 공통 Pod의 Stop, Restart, Terminate, Delete
- 자기 모델 완료를 이유로 공통 volume 삭제
```

RunPod 모델 채팅은 모델 실행과 자기 산출물 검증까지만 담당한다. 공통 Pod의 생성과 최종 종료는 `00_preflight_orchestrator` 소유다.

---

## 7. 공통 run 상태와 잠금

### 7.1 확정 공통 산출물 루트

세 코퍼스는 아래 한 experiment group 아래에서 **동일한 반복 폴더 구조와 동일한 파일명**을 사용한다. `<repeat_id>`는 `repeat_01`, `repeat_02`, `repeat_03` 중 하나, `<corpus_key>`는 `fault_standard`, `review_case`, `precedent` 중 하나, `<model_key>`는 공통 6개 모델 key 중 하나다.

식별자는 `experiment_group_id`를 세 반복이 공유하고, `run_group_id`는 `<experiment_group_id>_<repeat_id>`로 반복마다 고유하게 만든다. 모든 score row는 두 값과 `repeat_id`를 함께 가진다.

`artifacts/embedding_ab_shared/`는 실행 산출물 전용이다. `.py`, `.pyc`, `.sh`, `.ps1`, `.bat`, `.cmd`, `.exe` 및 실행 코드를 포함한 ZIP은 이 루트에 저장하지 않는다. 공통 runner와 RunPod 실행 코드는 `etl/fault_cases/src/embedding_ab_shared/`가 소유한다.

- Track A 새 공식 결과: `artifacts/embedding_ab_shared/track_a_6models_native_3repeats/`
- Track B 기존 참고 결과: `artifacts/embedding_ab_shared/track_b_5models_fixed1024/`
- Track B의 실행 코드 보존본: `src/embedding_ab_shared/track_b_5models_fixed1024/`

```text
etl/fault_cases/artifacts/embedding_ab_shared/track_a_6models_native_3repeats/
  run_<experiment_group_id>/
    00_experiment_manifest/
      experiment_manifest.json
      repeat_registry.json
    repeat_01/                         # repeat_02, repeat_03도 동일
      00_input/
        common/
          queries.jsonl
          query_manifest.json
        corpora/
          fault_standard/
            documents.jsonl
            corpus_manifest.json
          review_case/
            documents.jsonl
            corpus_manifest.json
          precedent/
            documents.jsonl
            corpus_manifest.json
      00_manifest/
        run_group_manifest.json
        run_state.json
        runpod_resource_manifest.json
        runpod_execution_lock.json
        model_manifests/
        eval_snapshots/
          fault_standard/
            queries.jsonl
            qrels.jsonl
            ground_truth_manifest.json
          review_case/
            queries.jsonl
            qrels.jsonl
            ground_truth_manifest.json
          precedent/
            queries.jsonl
            qrels.jsonl
            ground_truth_manifest.json
      01_token_audit/
        <model_key>/
          fault_standard/token_length_audit.json
          review_case/token_length_audit.json
          precedent/token_length_audit.json
      02_vectors/
        <model_key>/
          fault_standard/
            document_embeddings.parquet
            query_embeddings.parquet
            artifact_manifest.json
            failures.jsonl
          review_case/                  # 위 4개 파일과 동일
          precedent/                    # 위 4개 파일과 동일
      03_retrieval/
        fault_standard/<model_key>/
          raw_top50.jsonl
          primary_top10.jsonl
          retrieval_manifest.json
        review_case/<model_key>/         # 위 3개 파일과 동일
        precedent/<model_key>/           # 위 3개 파일과 동일
      04_metrics/
        fault_standard/
          scores.csv
          query_details.jsonl
          bootstrap.json
          cost_latency.json
          error_analysis.csv
          cosine_similarity_summary.csv
          cosine_similarity_query_details.jsonl
        review_case/                     # 위 6개 파일과 동일
        precedent/                       # 위 6개 파일과 동일
        common/
          model_score_matrix.csv
          common_answerable_scores.csv
          model_ranking.json
    05_aggregate/
      repeat_score_matrix.csv
      model_score_summary.csv
      rank_stability.csv
      query_top10_stability.csv
      cosine_similarity_repeat_summary.csv
    05_report/
      corpora/
        fault_standard/corpus_result.md
        review_case/corpus_result.md
        precedent/corpus_result.md
      pgvector_3코퍼스_임베딩_모델_AB_스코어_비교표.md
      pgvector_3코퍼스_임베딩_모델_AB_분석_리포트.md
```

`evaluation/`의 원본 파일명은 version을 보존한다. 각 repeat snapshot에 복사할 때만 `queries.jsonl`, `qrels.jsonl`, `ground_truth_manifest.json`으로 통일하고, 각 `run_group_manifest.json`에 원본 절대 저장소 경로, 원본 파일명, version, SHA-256을 반드시 기록한다. 세 반복의 입력 SHA는 정확히 같아야 한다.

`primary_top10.jsonl`의 1차 검색 단위만 코퍼스별로 다르다.

| corpus_key | primary 단위 | collapse key |
|---|---|---|
| `fault_standard` | Rule | `rule_id` |
| `review_case` | 심의사례 | `review_case_id` |
| `precedent` | 판례 사건 | `case_id` |

파일명과 디렉터리는 위 계약을 고정한다. 추가 진단 파일이 필요하면 각 코퍼스 폴더 안에만 추가하고, 공통 필수 파일의 이름을 바꾸지 않는다.

재실행 코드는 다음처럼 공통 runner와 세 코퍼스 adapter를 한 패키지에 둔다.

```text
etl/fault_cases/src/embedding_ab_shared/
  __init__.py
  common/
    __init__.py
    paths.py                             # Track A/B 코드와 출력 루트의 단일 경로 계약
  track_b_5models_fixed1024/             # 과거 5모델·1024차원 Track B, 기능 변경 금지
    __init__.py
    README.md
    RUNPOD_BUNDLES.md
    run_ab.py
    runpod_local_models.sh
    runpod_bundles/
  track_a_6models_native_3repeats/       # 새 공식 Native-6 전체 3회 구현 전용
    __init__.py
    README.md
    config.py
    model_registry.py
    run_state.py
    runpod_lock.py
    build_transfer_bundle.py
    run_native7.py
    run_openai_models.py
    run_local_models.py
    runpod_native7_3repeats.sh
    validate_vectors.py
    integrate_results.py
    build_final_reports.py
    requirements.lock
    corpora/
      fault_standard/
        build_corpus_snapshot.py
        adapter.py
        load_pgvector.py
        evaluate_retrieval.py
        build_corpus_report.py
      review_case/                       # 위 5개 파일과 동일
      precedent/                         # 위 5개 파일과 동일
    tests/
```

기존 도메인 패키지는 원천 전처리와 운영 검색을 계속 소유한다. A/B 공통 orchestration·경로·최종 통합은 `track_a_6models_native_3repeats`가 소유하여 같은 기능의 runner를 세 곳에 복제하지 않는다. Track B 코드는 과거 결과 재현 외에는 호출하지 않고 Track A가 import하지 않는다. 두 Track의 공통 사용은 부작용 없는 `common/paths.py` 경로 계약으로 제한한다.

### 7.1.1 한국어 문서·코드 주석 작성 계약

- 새로 만드는 계획서, README, 실행 안내서, 오류 안내, 표, 분석 리포트와 운영 문서는 한국어로 작성한다.
- 모델명, 라이브러리명, API 필드명, 파일 경로, CLI 옵션처럼 변경할 수 없는 고유 식별자만 원문 영문을 유지하고 바로 옆에서 한국어 의미를 설명한다.
- 모든 Python/Bash 파일은 파일 첫 부분에 한국어로 목적, 입력, 출력, 실행 순서와 Track A/B 소속을 설명한다.
- 모든 함수에는 한국어 docstring을 작성하고 매개변수, 반환값, 발생 가능한 예외와 부작용을 빠짐없이 설명한다.
- 변수 할당, 조건문, 반복문, 파일 입출력, API 호출, 차원 검사, 재시도, 비용 계산, 오류 처리 등 각 실행 줄의 의미를 따라갈 수 있도록 한국어 주석을 작성한다.
- 주석은 코드가 무엇을 하는지만 반복하지 않고 해당 검사가 필요한 이유, 실패 시 영향, 생성되는 산출물을 함께 설명한다.
- API key 값·앞부분·길이 등 비밀정보는 코드, 주석, 로그, README와 보고서 어디에도 기록하지 않는다.
- 한국어 설명 누락, 영어 설명문 잔존, 함수 docstring 누락 또는 핵심 실행 줄 주석 누락은 코드 검토 실패로 처리한다.

### 7.2 run 상태 필드

```json
{
  "experiment_group_id": "embedding_native7_3repeat_YYYYMMDD_HHMMSS",
  "run_group_id": "embedding_native7_3repeat_YYYYMMDD_HHMMSS_repeat_01",
  "repeat_id": "repeat_01|repeat_02|repeat_03",
  "status": "preflight|openai|runpod|retrieval|complete|failed",
  "query_version": "fault_common_queries_v1",
  "query_sha256": "...",
  "current_model_key": null,
  "active_task_owner": null,
  "allowed_next_model_key": "openai_small_native_1536",
  "completed_model_keys": [],
  "failed_model_keys": [],
  "updated_at": "ISO-8601"
}
```

### 7.3 RunPod 실행 lock

RunPod 모델 채팅은 실행 전에 `runpod_execution_lock.json`을 확인한다. 다른 `active_task_owner`가 있으면 접속하거나 명령을 실행하지 않는다.

```json
{
  "pod_id": "experiment_pod_id",
  "repeat_id": "repeat_01",
  "model_key": "qwen3_06b_native_1024",
  "task_owner": "03_qwen3_06b",
  "status": "active",
  "acquired_at": "ISO-8601"
}
```

모델 완료 후 count, dimension, finite, norm, SHA 검증이 통과해야 lock을 `released`로 바꾸고 다음 모델로 넘긴다.

---

## 8. 전체 실행 순서

아래 Phase 1~5를 `repeat_01`, `repeat_02`, `repeat_03`에 대해 각각 끝까지 수행한다. 한 repeat의 18개 model-corpus 평가가 완료되기 전 다음 repeat 산출물과 섞지 않는다. 동일 Pod를 계속 사용할 수 있지만 repeat마다 embedding artifact는 전부 새로 생성한다.

### Phase 0. 비용 없는 로컬 준비

```text
1. 공통 A/B runner와 requirements.lock 구현
2. 세 corpus export와 corpus manifest 생성
3. common query 50개와 세 qrels SHA 최종 동결
4. 세 qrels의 manifest 승인 상태와 SHA 확인, 상태 필드가 있으면 `draft|reviewed` 0건 확인
5. 6개 tokenizer 전체 문서/query 길이 audit
6. E5 512-token 초과 건수와 코퍼스별 winner 자격 확정
7. output path와 model_key 덮어쓰기 방지 테스트
8. pgvector extension, 별도 schema 생성 권한 확인
9. OpenAI key 존재 여부만 확인하고 값은 출력하지 않음
```

Phase 0이 통과하기 전에는 RunPod `+ Deploy`를 누르지 않는다.

### Phase 1. OpenAI smoke와 전체 실행

```text
1. text-embedding-3-small: corpus별 20 documents + 10 queries smoke
2. `dimensions` 축소 인자를 전달하지 않고 native 1,536차원, count, norm, usage 확인
3. small 세 코퍼스 전체 실행
4. text-embedding-3-large에 같은 절차를 적용하고 native 3,072차원 확인
5. 두 모델의 세 코퍼스 output SHA 검증
```

기본 실행은 각 repeat에서 small 완료 후 large 순서다. 두 OpenAI 모델의 smoke가 모두 통과하고 rate limit과 output 경로가 분리된 경우에만 전체 document 호출을 병렬 lane으로 실행할 수 있다. 세 정식 repeat 모두 재현성과 비용 추적을 위해 순차 실행을 기본으로 한다.

### Phase 2. 공통 RunPod 선택·생성

```text
1. Chrome의 RunPod 로그인 여부와 Pods 목록을 읽기 전용으로 확인
2. 로그아웃 또는 MFA 요구 시 사용자가 직접 인증할 때까지 중단
3. 보호 Pod `SKN27-3T-OJH`의 name+ID를 denylist에 기록하고 절대 조작하지 않음
4. `SKN27-embedding-ab-*` 등 임베딩 A/B용 기존 Pod가 있으면 **신규 Pod를 만들지 않음**
5. 기존 임베딩 Pod가 있으면 사용자에게 해당 Pod의 Start와 JupyterLab 열기를 요청하고, 준비 전까지 RunPod 실행을 대기
6. 임베딩 A/B용 기존 Pod가 없고 보호 Pod만 있으면, GPU·시간당 가격·storage·최대 예산을 기록한 뒤 신규 공통 Pod와 volume을 생성
7. 기존 Pod 재사용이면 `resource_origin=reused`, 신규 생성이면 `resource_origin=new`과 함께 Pod name/ID·volume ID를 manifest에 기록
8. 기존 Pod의 GPU가 불가하거나 migration·GPU 변경이 필요하면 자동 변경하지 않고 사용자 확인을 요청
```

### Phase 3. RunPod 공통 모델 실행

```text
Qwen3-Embedding-0.6B
  -> batch_01 fault_standard
  -> batch_02 review_case
  -> batch_03 precedent
  -> corpus별 queries
  -> 검증 후 unload

Qwen3-Embedding-4B
  -> 같은 batch 순서
  -> corpus별 queries
  -> 검증 후 unload

BGE-M3 dense
  -> 같은 batch 순서
  -> corpus별 queries
  -> 검증 후 unload

multilingual-E5-large
  -> 같은 batch 순서
  -> corpus별 queries
  -> 검증 후 unload
```

RunPod 모델 네 개는 한 GPU에서 동시에 실행하지 않는다. Qwen3-4B native 2,560차원을 안정적으로 처리할 수 있는 GPU를 기본 후보로 하고, 각 모델 smoke 후 batch를 확정한다. 세 정식 repeat 모두 로그와 비용 추적을 단순화하기 위해 OpenAI 완료 후 RunPod를 기본 순서로 둔다.

### Phase 4. 회수와 종료

```text
1. 모든 모델/corpus 결과 파일 count와 SHA 생성
2. 로컬로 다운로드
3. RunPod SHA와 로컬 SHA 대조
4. RunPod 모델 4개 x corpus 3개의 필수 파일 존재 확인
5. experiment Pod name+ID를 manifest와 이중 대조
6. `resource_origin=new` 또는 `reused`와 관계없이 Pod Stop, Terminate, Delete는 사용자 확인 없이는 수행하지 않음
7. SKN27-3T-OJH 상태가 바뀌지 않았음을 목록에서 확인
```

### Phase 5. pgvector와 평가

```text
1. 모델·코퍼스별 별도 A/B table 또는 corpus_key로 적재
2. raw chunk/document top-K 저장
3. 코퍼스별 사건/Rule collapse 적용
4. 판례 qrels로 판례만 평가
5. 인정기준 qrels로 인정기준만 평가
6. 심의사례 qrels로 심의사례만 평가
7. 모델별 세 코퍼스 macro와 공통-answerable 교집합 점수 별도 계산
```

### Phase 6. 3회 집계와 공통 점수표·분석 리포트 생성

세 반복의 모든 모델·코퍼스 평가가 끝난 뒤 `06_integrate_evaluate`가 다음 순서로 공통 최종 문서 두 개를 생성한다.

```text
1. repeat별 세 04_metrics/<corpus_key>/scores.csv의 schema, model_key 6개, 반복당 18개·전체 54개 model-corpus 행을 검증
2. 세 반복의 corpus/query/qrels/model revision/adapter hash가 동일하고 repeat_id/run_id/output path는 서로 다른지 검증
3. 누락·실패·winner 부적격 모델과 사유를 repeat별 model_ranking.json에 기록
4. repeat_score_matrix.csv, model_score_summary.csv, rank_stability.csv, query_top10_stability.csv, cosine_similarity_repeat_summary.csv 생성
5. 임시 .partial 파일로 스코어 비교표 MD 작성
6. 스코어 비교표와 세 반복의 query_details/bootstrap/error_analysis/cost_latency를 근거로 분석 리포트 MD 작성
7. 두 MD의 필수 표·필수 섹션·experiment/repeat 식별자 검증
8. 검증 통과 후 두 파일을 최종 이름으로 atomic rename
9. 두 파일 SHA-256을 experiment_manifest.json에 기록하고 experiment status를 complete로 변경
```

세 반복 중 하나라도 필수 metric이 없거나, 54개 model-corpus 행 중 하나가 이유 없이 누락됐거나, 입력 SHA·model revision·adapter가 달라졌으면 두 최종 MD를 생성하지 않고 실패한다. 탈락 모델은 행을 삭제하지 않고 `eligible=no`와 탈락 사유를 표에 남긴다. 기존 Track B 점수는 별도 참고 표에만 두며 Track A의 54개 행과 평균내지 않는다.

---

## 9. 모델별 adapter와 시작 batch

### 9.1 OpenAI small/large

```text
document = corpus별 동결 embedding text
query = corpus별 query_text
dimensions parameter = 생략(축소 금지)
expected output = small 1536 / large 3072
encoding_format = float
request batch = 고정 문서 수가 아니라 token 합계 기준
```

API 응답의 `usage.total_tokens`, request ID, retry count, latency를 기록한다. OpenAI runner는 프로젝트 루트 `C:\dev\project\SKN27-FINAL-3Team\.env`에서 `OPENAI_API_KEY`를 로드한다. 키가 없으면 유료 호출 전에 즉시 실패하고 설정 방법만 안내한다. 키 값·접두부·길이는 로그, manifest, Markdown 보고서에 기록하지 않으며 RunPod에도 전송하지 않는다. Qwen/BGE/E5 로컬 실행에는 OpenAI 키가 필요하지 않다.

### 9.2 Qwen3-Embedding-0.6B/4B

```text
document batch 시작 = 64
query batch 시작 = 32
OOM fallback = 32 -> 16 -> 8
dtype = bf16 가능 시 bf16, 아니면 fp16
output = float32, 모델별 native 차원(1024/2560/4096), L2 normalized
```

Qwen query instruction은 영어 한 문장으로 코퍼스별 고정한다.

```text
fault_standard:
Instruct: Given a Korean traffic-accident description, retrieve the applicable Korean fault-ratio standard rule

review_case:
Instruct: Given a Korean traffic-accident description, retrieve the most relevant fault-ratio dispute review cases

precedent:
Instruct: Given a Korean traffic-accident description, retrieve the most relevant Korean traffic-accident fault-liability precedents

공통 형식:
{instruction}\nQuery: {query_text}
```

### 9.3 BGE-M3

```text
document batch 시작 = 64
query batch 시작 = 32
OOM fallback = 32 -> 16 -> 8
dense vector만 저장
sparse/ColBERT output 금지
output = float32, native 1024, L2 normalized
```

### 9.4 multilingual-E5-large

```text
document = passage: {corpus_text}
query = query: {query_text}
document batch 시작 = 64
query batch 시작 = 32
OOM fallback = 32 -> 16 -> 8
max_length = 512
silent truncation = 금지
overflow = 0이면 정식 후보, overflow > 0이면 명시적 truncation과 건수 기록 후 legacy 참고 후보
output = float32, native 1024, L2 normalized
```

E5 overflow 때문에 세 코퍼스의 이미 동결된 구조화 단위를 공통 runner가 자동 재청킹하지 않는다. 한 코퍼스라도 overflow가 있으면 E5는 3코퍼스 종합 winner 자격에서 제외하고, 해당 코퍼스 계획에 따라 참고 점수만 보고한다. 입력을 바꾸는 재청킹 실험은 새 corpus version을 만든 별도 후속 실험으로 분리한다.

20문서 smoke는 정확성 확인용이다. 전체 비용과 시간을 예상하려면 각 RunPod 모델에서 500문서 timed benchmark를 추가한다. 예상 실행이 승인된 시간 또는 비용 상한을 넘으면 전체 batch를 시작하지 않는다.

---

## 10. 벡터 혼합 방지 계약

차원이 같아도 서로 다른 모델의 vector space는 호환되지 않으며, 차원이 다른 모델을 한 pgvector 컬럼에 적재할 수도 없다. 검색 코드가 다음 조건을 강제해야 한다.

pgvector는 `vector(n)`의 차원이 컬럼 타입에 고정되므로 Track A는 모델별 물리 테이블/partition을 사용한다. 예: `document_vectors__openai_small_native_1536 vector(1536)`, `document_vectors__qwen3_4b_native_2560 vector(2560)`. 단일 `vector(1024)` 컬럼에 padding·truncation해서 넣는 것은 금지한다.

```text
query.corpus_key      = document.corpus_key
query.model_key       = document.model_key
query.adapter_hash    = document.query_adapter_hash에 대응하는 승인 adapter
query.embedding_dim   = document.embedding_dim = model_manifest.native_dimension
query.query_version   = 승인된 common query version
document.corpus_sha   = 승인된 corpus manifest SHA
```

권장 기본키:

```text
query_vectors:
  PRIMARY KEY (run_group_id, corpus_key, model_key, query_id)

document_vectors:
  PRIMARY KEY (run_group_id, corpus_key, model_key, document_id)
```

다음 조합은 모두 실행 오류로 중단한다.

```text
Qwen query + BGE document
OpenAI small query + OpenAI large document
판례 Qwen instruction query + 인정기준 Qwen document search
서로 다른 corpus_version 또는 adapter_hash
```

모델 채팅은 최종 파일명을 바로 쓰지 않는다. 임시 파일을 완성하고 count/SHA 검증을 통과한 뒤 atomic rename한다.

---

## 11. RunPod 공통 자원 규칙

### 11.1 보호 자원

```text
protected_pod_name = SKN27-3T-OJH
protected_pod_id   = c7ool8ji5f17fj
```

실행 당일 Pods 목록에서 이름과 ID가 모두 일치하는지 보기만 하고 manifest denylist에 기록한다. 보호 Pod에 대해 Connect, 상세 열기, Start, Stop, Restart, Clone, Edit, Redeploy, volume 연결, Terminate, Delete를 모두 금지한다. 이름 또는 ID가 예상과 다르면 대상 판별을 시도하지 말고 사용자 확인 전까지 RunPod 작업 전체를 중단한다.

### 11.2 공통 본 실험 Pod 선택 우선순위

이 절의 선택 규칙은 이 문서와 세 코퍼스 계획에 남아 있는 `신규 Pod`, `신규 volume` 표현보다 우선한다.

```text
1. 보호 대상 SKN27-3T-OJH는 존재 여부만 확인하고 절대 사용하지 않는다.
2. 임베딩 A/B 전용 기존 Pod가 있으면 신규 Pod를 만들지 않는다.
3. 기존 임베딩 Pod 발견 시 사용자에게 Start와 JupyterLab 열기를 요청한 뒤 그 Pod를 사용한다.
4. 기존 임베딩 Pod가 없고 OJH 보호 Pod만 있으면 신규 Pod를 생성한다.
5. 기존 Pod의 GPU 불가, migration, GPU 유형 변경은 사용자 확인 전 자동 실행하지 않는다.
6. 재사용 Pod의 이전 vector·검색·점수 산출물은 절대 재사용하지 않고, 새 Track A run 경로에 결과를 새로 만든다.
7. Pod 종료·삭제는 재사용 여부와 무관하게 결과 회수·SHA 검증 뒤 사용자 확인을 받아 수행한다.
```

### 11.3 선택된 공통 본 실험 Pod 구성

```text
Pod name: 기존 `SKN27-embedding-ab-*` 또는 새 `SKN27-3T-EMBED-AB-ALL-<initials>-<YYYYMMDD>`
Cloud: Community Cloud, 데이터 보안 gate 실패 시 Secure Cloud
Billing: On-demand
GPU: A40 48GB x 1 또는 동급 48GB VRAM GPU
Template: RunPod 공식 PyTorch 고정 tag/digest
Python: 3.11
Container disk: 기존 Pod 설정 또는 신규 30GB
Pod volume: 기존 Pod의 `/workspace` 또는 신규 40GB
Network volume: 없음
결과 경로: 기존 Pod를 재사용해도 `/workspace/embedding_ab_native7_<experiment_group_id>/`를 새로 생성
```

공통 Native-6 본 실험은 Qwen3-4B를 로컬 최대 모델로 사용한다. GPU는 4B smoke에서 확정한 batch를 안정적으로 처리할 수 있는 자원을 선택하며, 실제 재고·가격은 Deploy 직전에 확인한다. GPU가 달라져도 모델 품질 점수는 동일 계약으로 평가하고 처리량·비용은 실행 환경과 함께 별도 보고한다.

### 11.4 로그인과 결제 게이트

```text
RunPod 로그아웃: 사용자가 직접 로그인할 때까지 중단
MFA 요구: 사용자가 직접 처리, 계정 설정 변경 금지
잔액 부족: 자동 충전 금지
가격이 계획보다 상승: 신규 Deploy 또는 GPU 변경 전 재승인
공통 본 실험 1회 비용 상한: 기본 $3
자동 유료 재실행: 금지
```

### 11.5 자원 소유권

`00_preflight_orchestrator`만 기존 임베딩 Pod 확인, 필요 시 신규 공통 Pod Deploy, 종료 전 사용자 확인을 담당한다. 모델별 RunPod 채팅은 manifest의 정확한 experiment Pod name+ID를 읽어 자기 모델만 실행한다.

모델 채팅에서 Pod가 없거나 ID가 다르면 새 Pod를 만들지 않고 중단한다.

---

## 12. 모델별 완료 조건

각 모델은 다음 조건을 모두 만족해야 `completed`로 표시한다.

```text
document vectors:
  fault_standard = 277
  review_case = 904
  precedent = 8,334

query vectors:
  fault_standard = 50
  review_case = 50
  precedent = 50

dimension = model manifest의 native_dimension과 정확히 일치
NaN/Inf = 0
zero norm = 0
duplicate ID = 0
missing ID = 0
corpus/query/adapter SHA mismatch = 0
model revision과 requirements lock 기록 완료
```

한 코퍼스라도 실패하면 해당 모델은 세 코퍼스 공통 비교에서 미완료다. 성공한 코퍼스 결과는 진단용으로 보존하지만 일부 결과만으로 종합 순위를 계산하지 않는다.

---

## 13. 별도 모델 채팅용 공통 시작 지시문

새 모델 작업 채팅에는 다음 내용을 함께 전달한다.

```text
이 작업은 3코퍼스 공통 임베딩 A/B의 <model_key> 전용 작업이다.

먼저 아래 네 계획을 읽는다.
1. pgvector_3코퍼스_공통_임베딩_모델별_실행계획.md
2. 판례/pgvector_판례_임베딩_모델_AB_실험계획.md
3. 인정기준/pgvector_인정기준_임베딩_모델_AB_실험계획.md
4. 심의사례/pgvector_심의사례_임베딩_모델_AB_실험계획.md

공통 Query나 qrels는 수정하지 않는다.
자기 model_key 외의 vector 파일을 수정하지 않는다.
corpus 순서는 fault_standard 277 -> review_case 904 -> precedent 8,334다.
query vectors는 corpus_key + model_key별로 50개씩 별도 저장한다.

RunPod 모델이면 기존 SKN27-3T-OJH는 절대 접근하지 않는다.
신규 Pod를 독자적으로 만들거나 종료하지 않고 runpod_resource_manifest의
공통 experiment Pod만 name+ID 대조 후 사용한다.
다른 RunPod model task가 active이면 실행하지 않는다.
```

모델별 채팅에는 `<model_key>`, `run_group_id`, 입력/output 경로와 허용 adapter를 추가로 지정한다.

---

## 14. 최종 공통 MD 두 파일 계약

모든 A/B 테스트가 끝나면 아래 두 파일을 반드시 생성한다. 코퍼스별 `corpus_result.md`는 근거 자료이고, 팀이 최종 확인하는 공통 문서는 정확히 아래 두 파일이다.

```text
etl/fault_cases/artifacts/embedding_ab_shared/track_a_6models_native_3repeats/run_<experiment_group_id>/05_report/
  pgvector_3코퍼스_임베딩_모델_AB_스코어_비교표.md
  pgvector_3코퍼스_임베딩_모델_AB_분석_리포트.md
```

### 14.1 `pgvector_3코퍼스_임베딩_모델_AB_스코어_비교표.md`

이 파일은 **해석보다 숫자와 판정 근거를 우선**하며 다음 표를 포함한다.

1. run/query/qrels/corpus/model revision과 SHA 요약
2. 코퍼스별 모델 점수표
3. 세 코퍼스 통합 비교표
4. 공통-answerable Query 교집합 비교표
5. latency·비용·VRAM·처리량 표
6. 실행 적격성 및 제외 사유 표
7. 모델별 순위와 동률 여부
8. 모델·코퍼스·회차별 코사인 유사도 요약표
9. 대표 성공·실패 Query의 Top-10 코사인 유사도 상세표

세 코퍼스의 `04_metrics/<corpus_key>/scores.csv`는 최소한 다음 공통 열을 가진다.

```text
experiment_group_id,repeat_id,run_id,corpus_key,model_key,eligible,exclusion_reason,
primary_metric_name,primary_ndcg_at_10,hit_at_1,hit_at_5,mrr_at_10,
answerable_query_count,total_query_count,p95_latency_ms,total_cost,
query_sha256,qrels_sha256,corpus_sha256
```

`primary_metric_name`과 `primary_ndcg_at_10`의 매핑은 다음처럼 고정한다.

| corpus_key | primary_metric_name | `primary_ndcg_at_10` 값 |
|---|---|---|
| `fault_standard` | `rulebook_macro_rule_ndcg_at_10` | 기준서별 Rule nDCG@10의 macro |
| `review_case` | `case_ndcg_at_10` | 사례 collapse 후 Case nDCG@10 |
| `precedent` | `case_ndcg_at_10` | 사건 collapse 후 Case nDCG@10 |

통합 비교표는 3회 개별값과 집계값을 모두 보여야 한다. 최소 열은 다음과 같다.

| model_key | repeat_01 Macro | repeat_02 Macro | repeat_03 Macro | 3회 평균 | 표준편차 | 최솟값 | 최댓값 | 순위 일치 | p95 latency | 총비용 | eligible | rank |
|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---|---:|
| `<model_key>` | `<score>` | `<score>` | `<score>` | `<mean>` | `<std>` | `<min>` | `<max>` | `<3/3>` | `<ms>` | `<cost>` | `yes/no` | `<rank>` |

각 repeat의 `3코퍼스 Macro`는 세 코퍼스의 0~1 범위 1차 nDCG@10을 동일 가중 평균한다. 모델 최종 대표값은 세 repeat Macro의 산술평균이며 sample standard deviation, min, max와 repeat별 rank를 함께 보고한다. 서로 다른 의미의 Hit@K, MRR, similarity 원점수를 하나의 평균으로 섞지 않는다. 값이 없으면 빈칸이나 0으로 꾸미지 않고 `N/A`와 사유를 기록한다.

코사인 유사도는 최종 우승 점수에 섞지 않지만 사용자가 실제 검색 점수를 확인할 수 있도록 별도 표로 반드시 출력한다. pgvector의 `<=>` 연산 결과는 `cosine_distance`이므로 보고서에는 `cosine_similarity = 1 - cosine_distance`로 변환한 값도 함께 기록한다. 유사도는 이론적으로 -1~1 범위이며 1에 가까울수록 방향이 유사하지만, 모델마다 점수 분포와 보정 상태가 다르므로 서로 다른 모델의 절대값만으로 승자를 정하지 않는다.

코사인 유사도 요약표의 최소 열은 다음과 같다.

| model_key | corpus_key | Top-1 유사도 평균 | Top-1 유사도 중앙값 | Top-1 유사도 p95 | 최초 정답 유사도 평균 | Top-1 정답 유사도 평균 | Top-1 오답 유사도 평균 | 정답-오답 유사도 차이 | 정답 없음 Query Top-1 평균 | 3회 표준편차 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `<model_key>` | `<corpus_key>` | `<mean>` | `<median>` | `<p95>` | `<mean>` | `<mean>` | `<mean>` | `<gap>` | `<mean 또는 N/A>` | `<std>` |

질문별 상세 원본 `cosine_similarity_query_details.jsonl`은 최소한 `experiment_group_id`, `repeat_id`, `corpus_key`, `model_key`, `query_id`, `rank`, `document_id`, `relevance`, `is_relevant`, `cosine_distance`, `cosine_similarity`를 가진다. 최종 MD의 대표 성공·실패 Query 표에는 Query별 Top-1 문서와 유사도, 최초 정답 순위와 유사도, 오답 여부를 함께 표시한다.

### 14.2 `pgvector_3코퍼스_임베딩_모델_AB_분석_리포트.md`

이 파일은 위 스코어 비교표와 `04_metrics`의 원본 산출물을 분석하여 다음 내용을 포함한다.

1. 한 줄 결론과 권장 모델·대체 모델
2. 실험 범위, 제외 범위, 재현성 식별자
3. 코퍼스별 승자와 세 코퍼스 종합 승자가 다른지 분석
4. baseline 대비 paired delta와 95% CI, 사실상 동률 판정
5. 사고군·난이도·문서 길이·품질 flag별 성능 분석
6. 공통 실패 Query와 코퍼스별 실패 원인
7. E5 truncation, adapter, collapse 단위가 결과에 미친 영향
8. 품질 대비 비용·지연·운영 복잡도 분석
9. 세 전체 반복의 평균·표준편차·최솟값·최댓값과 모델 순위 안정성
10. Query별 Top-10 결과 일치율과 회차별 성공/실패 전환 분석
11. 최종 채택/보류/탈락 사유
12. 후속 실험 우선순위
13. cosine distance와 cosine similarity의 정의, 계산식과 각 컬럼 설명
14. 모델 내부 유사도 분포, 정답·오답 유사도 차이, 과신 false positive와 정답 없음 Query 분석

분석 문장은 반드시 표나 raw query detail의 근거를 연결한다. 차이가 CI 범위 안이면 “우수” 또는 “압승”으로 단정하지 않고 사실상 동률로 기록한다. 모델이 일부 코퍼스에서 실패했다면 종합 점수를 억지로 보간하지 않는다.

### 14.3 생성기 완료 조건

두 MD 생성기는 다음을 검증해야 성공 exit code를 반환한다.

```text
필수 모델 6개가 세 repeat에 모두 존재하고 3코퍼스 기준 총 54개 행 존재
repeat_01/02/03 각각 세 코퍼스 scores.csv가 모두 존재
모든 score row의 experiment_group_id와 입력 SHA/model revision/adapter 일치
repeat_id와 run_id가 세 회차에서 고유하고 산출물 경로가 분리됨
모든 수치가 finite이고 metric 범위가 유효
Macro 재계산값과 표 출력값 일치
제외 모델의 eligible/reason 누락 0
스코어 비교표의 필수 표 9개 존재
분석 리포트의 필수 섹션 14개 존재
세 repeat·세 코퍼스·6모델의 cosine_similarity_summary.csv와 cosine_similarity_query_details.jsonl 존재
모든 cosine_similarity가 1 - cosine_distance 재계산값과 허용 오차 안에서 일치
두 MD 내부에 experiment_group_id, repeat_id 3개와 생성 시각 존재
두 MD SHA가 experiment_manifest에 기록됨
```

실험 전에는 결과처럼 보이는 빈 최종 MD를 만들지 않는다. 필요하면 `.template.md`를 별도 사용하되 최종 이름은 모든 검증을 통과한 뒤에만 생성한다.

---

## 15. 최종 체크리스트

### 공통 준비

- [ ] 이 문서와 세 코퍼스 계획의 경로가 유효함
- [x] 공통 Query 50행의 `annotation_status`와 query manifest가 모두 approved
- [ ] 공통 Query 50개와 세 qrels SHA 동결
- [x] 인정기준 q13 최종 판정 반영과 pending 상태 해소
- [ ] 세 qrels의 최종 승인 상태와 SHA 확인, 상태 필드가 있으면 `draft|reviewed` 0건
- [ ] 277 + 904 + 8,334 document manifest 동결
- [ ] 공통 A/B runner와 requirements.lock 구현
- [ ] 6개 tokenizer audit 완료
- [ ] E5 512-token overflow와 코퍼스별/종합 winner 자격 기록
- [ ] model/corpus/output 덮어쓰기 방지 테스트 통과
- [ ] 6모델 × 3코퍼스 전체를 repeat_01/02/03에서 각각 실행하는 계약 확인

### OpenAI

- [ ] `OPENAI_API_KEY` 존재 확인, 값 미출력
- [ ] small 전체 3코퍼스 × 3회 완료
- [ ] large 전체 3코퍼스 × 3회 완료
- [ ] model/corpus별 usage와 비용 기록

### RunPod

- [ ] 사용자가 로그인한 올바른 계정 확인
- [ ] `SKN27-3T-OJH` name+ID denylist 기록
- [ ] 기존 임베딩 A/B Pod 존재 여부 확인 및 `resource_origin` 기록
- [ ] 기존 Pod가 있으면 사용자에게 Start·JupyterLab 열기 요청, 없으면 유료 Deploy와 비용 상한 기록 후 신규 생성
- [ ] Qwen 0.6B 세 corpus × 3회 완료
- [ ] Qwen 4B 세 corpus × 3회 완료
- [ ] BGE-M3 dense 세 corpus × 3회 완료
- [ ] E5-large 세 corpus × 3회 완료
- [ ] RunPod output과 로컬 SHA 일치
- [ ] 결과 회수·SHA 검증 후 Pod 종료 여부를 사용자에게 확인
- [ ] OJH 상태 불변 확인

### 평가

- [ ] model/corpus별 vectors count와 dimension 검증
- [ ] 서로 다른 model_key vector 조합 0건
- [ ] 판례·인정기준·심의사례를 각 전용 qrels로 독립 평가
- [ ] 공통 6개 모델의 3코퍼스 macro 별도 보고
- [ ] 반복당 18행·전체 54행과 3회 평균/표준편차/min/max/rank 안정성 검증
- [ ] 모델·코퍼스·회차별 코사인 유사도 원본·요약·3회 집계 생성 및 최종 두 MD 표기
- [ ] 기존 1024차원 Track B 결과를 Native-6 Track A 종합 순위와 혼합하지 않음
- [ ] 세 코퍼스가 동일 폴더명과 공통 필수 파일명을 사용
- [ ] `04_metrics/common` 통합 원본 3개 생성
- [ ] 공통 스코어 비교표 MD 생성·검증·SHA 기록
- [ ] 공통 분석 리포트 MD 생성·검증·SHA 기록
- [ ] 두 공통 MD 생성 후에만 run status를 `complete`로 변경

---

## 16. 한 줄 결론

```text
공통 최신 6개 모델을 각 모델의 공식 기본/native 차원으로 세 코퍼스 전체에 독립 3회 실행하되,
OpenAI 2개는 로컬에서 실행하고 Qwen 3개/BGE/E5는 신규 공통 48GB RunPod 한 대를 순차 공유하며,
모든 vector는 corpus_key + model_key + adapter_hash로 분리해 평가한다.
평가 완료 후에는 통일된 metric 원본으로 공통 스코어 비교표 MD와 분석 리포트 MD를 생성한다.
```
