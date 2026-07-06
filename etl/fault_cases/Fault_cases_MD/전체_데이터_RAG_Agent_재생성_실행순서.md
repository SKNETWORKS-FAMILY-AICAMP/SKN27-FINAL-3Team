# 전체 데이터/RAG/Agent 재생성 실행순서

## 목적

이 문서는 `artifacts` 폴더의 JSON/JSONL 산출물을 정리하거나 삭제했을 때, 어떤 파일이 필수이고 어떤 명령을 어떤 순서로 다시 실행해야 하는지 정리한 운영용 체크리스트다.

전체 흐름은 다음 순서로 본다.

```text
0. 인프라 준비
1. 데이터 수집
2. 전처리
3. DB 적재
4. chunk / search_text 생성
5. embedding 저장
6. 검색 index 생성
7. RAG 검색 테스트
8. 선택 실험: A/B 평가 / reranker 평가
9. Agent 실행
10. 보고서 생성
```

현재 운영 기준 검색 방식은 **BM25+Nori**이다.

```text
심의사례 Agent V1/V2:
  review_case BM25+Nori

과실비율 판례 통합 V2:
  fault_ratio_precedent BM25+Nori

교통사고 일반판례 RAG V1:
  traffic_precedent BM25+Nori
```

따라서 `pgvector`, Elasticsearch `vector`, `hybrid`, local `reranker`는 운영 필수 단계가 아니라 검색 방식 비교를 다시 해야 할 때 실행하는 선택 실험 단계로 본다.

## 먼저 알아야 할 기준

삭제해도 대체로 다시 만들 수 있는 산출물:

```text
postgres_exports/
elasticsearch_exports/
retrieval_ab_exports/
agent_runs/
traffic_law_rag/
```

이유:

```text
검색 결과, 평가 결과, 실행 결과 JSON/JSONL은 코드와 DB/index가 있으면 다시 생성 가능하다.
```

반대로 없으면 복구 비용이 큰 파일:

```text
심의사례:
- review_case_output/crawled/(최종)과실비율심의사례_(54MB).pdf
- review_case_output/preprocessed/review_case_documents.jsonl
- review_case_output/preprocessed/review_case_chunks.jsonl

판례:
- traffic_precedents_output/traffic_prec_reclass_verified/01_confirmed_traffic_cases.jsonl
- traffic_precedents_output/traffic_prec_fault_ratio_verified/01_fault_ratio_confirmed_cases.jsonl

Agent 테스트:
- review_case_output/schema_search_test/text_ml_case_search_agent_input_full_optional_fields.jsonl
```

이유:

```text
이 파일들은 DB 적재 또는 Agent 테스트 입력 기준이 되는 핵심 source file이다.
```

---

## 0. 인프라 준비

PostgreSQL, Elasticsearch, Kibana가 실행 중인지 확인한다.

```powershell
docker compose ps
```

Elasticsearch 확인:

```powershell
curl http://localhost:9200
```

또는 브라우저:

```text
http://localhost:9200
```

필요한 서비스:

```text
postgres
elasticsearch
kibana
```

---

# 1. 심의사례 review_case 재생성 순서

심의사례는 PDF를 원천으로 한다.

## 1-1. PDF 수집

```powershell
python -B -m etl.fault_cases.src.review_case.crawling.one_click_collect
```

생성 위치:

```text
etl/fault_cases/artifacts/review_case_output/crawled/
```

중요 파일:

```text
(최종)과실비율심의사례_(54MB).pdf
crawling_manifest.jsonl
crawling_quality_report.jsonl
```

PDF가 이미 있으면 이 단계는 생략 가능하다.

## 1-2. 전처리

```powershell
python -B -m etl.fault_cases.src.review_case.preprocessing.preprocess_runner
```

생성 위치:

```text
etl/fault_cases/artifacts/review_case_output/preprocessed/
```

중요 파일:

```text
review_case_documents.jsonl
review_case_chunks.jsonl
review_case_source_chunks.jsonl
toc/review_case_toc_items.jsonl
toc/review_case_toc_case_links.jsonl
```

## 1-3. DB schema 생성

```powershell
python -B -m etl.fault_cases.src.review_case.db_loading.schema_manager
```

역할:

```text
review_case_db 생성
review_case_* 테이블 생성
```

## 1-4. PostgreSQL 적재

```powershell
python -B -m etl.fault_cases.src.review_case.db_loading.run_db_load
```

입력:

```text
preprocessed/review_case_documents.jsonl
preprocessed/review_case_chunks.jsonl
```

## 1-5. 적재 검증

```powershell
python -B -m etl.fault_cases.src.review_case.db_loading.validate_loaded_counts
```

## 1-6. search_text 재생성

```powershell
python -B -m etl.fault_cases.src.review_case.db_loading.rebuild_search_text
```

## 1-7. embedding 저장

먼저 API 호출 없는 dry-run:

```powershell
python -B -m etl.fault_cases.src.review_case.embedding.run_embedding --dry-run
```

소량 테스트:

```powershell
python -B -m etl.fault_cases.src.review_case.embedding.run_embedding --limit 10
```

전체 저장:

```powershell
python -B -m etl.fault_cases.src.review_case.embedding.run_embedding
```

검증:

```powershell
python -B -m etl.fault_cases.src.review_case.embedding.validate_embedding_counts
```

주의:

```text
embedding 저장은 OpenAI embedding API 비용이 발생할 수 있다.
```

## 1-8. pgvector index 생성 - 선택

```powershell
python -B -m etl.fault_cases.src.review_case.search.pgvector.create_index
```

이 단계는 심의사례 pgvector baseline 또는 vector/hybrid 비교 실험을 다시 할 때만 필요하다.

현재 Agent 운영 검색은 BM25+Nori이므로, 일반 복구 루트에서는 생략 가능하다.

## 1-9. Elasticsearch index 생성

BM25:

```powershell
python -B -m etl.fault_cases.src.review_case.search.elasticsearch.bm25_indexer
```

이 BM25 index는 현재 Agent RAG에서 사용하는 필수 index이다.

Vector - 선택:

```powershell
python -B -m etl.fault_cases.src.review_case.search.elasticsearch.vector_indexer
```

Vector index는 Elasticsearch vector/hybrid 비교 실험을 다시 할 때만 필요하다.

## 1-10. 심의사례 검색 테스트

운영 기준 필수 테스트는 BM25+Nori이다.

```powershell
python -B -m etl.fault_cases.src.review_case.search.elasticsearch.run_bm25_sample_queries
```

선택 실험:

```powershell
python -B -m etl.fault_cases.src.review_case.search.pgvector.run_sample_queries
python -B -m etl.fault_cases.src.review_case.search.elasticsearch.run_vector_sample_queries
python -B -m etl.fault_cases.src.review_case.search.elasticsearch.run_hybrid_sample_queries
```

이 단계에서 생성되는 JSON 결과는 검색 검증 산출물이므로 삭제되어도 다시 만들 수 있다.

현재 Agent가 실제 사용하는 것은 BM25+Nori 결과이므로, pgvector/vector/hybrid 결과 JSON은 운영 필수 파일이 아니다.

---

# 2. 판례 traffic_precedent / fault_ratio_precedent 재생성 순서

판례는 다음 흐름으로 재생성한다.

```text
API 수집
→ 전처리
→ 교통사고 판례 분류
→ 검증
→ 과실비율 판례 분류
→ 검증
→ DB 적재
→ chunk 생성
→ embedding 저장
→ 검색 index 생성
→ RAG/A-B 평가
```

## 2-1. API 수집

```powershell
python -B -m etl.fault_cases.src.traffic_precedents.traffic_precedents_crawling.traffic_prec_api_collector_all_raw_commented
```

생성 위치:

```text
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_api/
```

## 2-2. 판례 원문 전처리

```powershell
python -B -m etl.fault_cases.src.traffic_precedents.traffic_precedents_preprocessing.preprocess_traffic_precedents_final_all_raw_maintext_clean
```

생성 예상:

```text
traffic_prec_preprocessed/
```

## 2-3. 교통사고 판례 1차 분류

폴더명에 공백과 하이픈이 있어 파일 직접 실행 방식이 더 안전하다.

```powershell
python -B "etl/fault_cases/src/traffic_precedents/traffic_precedents_1st_classification-traffic accident/traffic_relevance_reclassifier_stage1.py"
```

생성:

```text
traffic_prec_reclass/
```

## 2-4. 교통사고 판례 검증

```powershell
python -B "etl/fault_cases/src/traffic_precedents/traffic_precedents_1st_classification-verification/traffic_relevance_recheck.py"
```

중요 최종 파일:

```text
traffic_prec_reclass_verified/01_confirmed_traffic_cases.jsonl
```

이 파일은 교통사고 일반판례 DB 적재 기준 파일이다.

## 2-5. 과실비율 판례 2차 분류

```powershell
python -B "etl/fault_cases/src/traffic_precedents/traffic_precedents_2nd_classification-fault_ratio/traffic_fault_ratio_stage2.py"
```

생성:

```text
traffic_prec_fault_ratio/
```

## 2-6. 과실비율 판례 검증

```powershell
python -B "etl/fault_cases/src/traffic_precedents/traffic_precedents_2nd_classification-verification/traffic_fault_ratio_recheck.py"
```

중요 최종 파일:

```text
traffic_prec_fault_ratio_verified/01_fault_ratio_confirmed_cases.jsonl
```

이 파일은 과실비율 판례 DB 적재 기준 파일이다.

## 2-7. 판례 DB schema 생성

```powershell
python -B -m etl.fault_cases.src.traffic_precedents.precedent_db_loading.schema_loader
```

## 2-8. 판례 DB 적재

교통사고 일반판례:

```powershell
python -B -m etl.fault_cases.src.traffic_precedents.precedent_db_loading.load_traffic_precedents
```

과실비율 판례:

```powershell
python -B -m etl.fault_cases.src.traffic_precedents.precedent_db_loading.load_fault_ratio_precedents
```

검증:

```powershell
python -B -m etl.fault_cases.src.traffic_precedents.precedent_db_loading.validate_loaded_counts
```

## 2-9. chunk 생성

```powershell
python -B -m etl.fault_cases.src.traffic_precedents.precedent_chunking.create_traffic_chunks
python -B -m etl.fault_cases.src.traffic_precedents.precedent_chunking.create_fault_ratio_chunks
```

## 2-10. embedding 저장

교통사고 판례:

```powershell
python -B -m etl.fault_cases.src.traffic_precedents.precedent_embedding.embed_traffic_chunks
```

과실비율 판례:

```powershell
python -B -m etl.fault_cases.src.traffic_precedents.precedent_embedding.embed_fault_ratio_chunks
```

검증:

```powershell
python -B -m etl.fault_cases.src.traffic_precedents.precedent_embedding.validate_embedding_counts
```

주의:

```text
embedding 저장은 OpenAI embedding API 비용이 발생할 수 있다.
```

## 2-11. pgvector index 생성 - 선택

```powershell
python -B -m etl.fault_cases.src.traffic_precedents.precedent_search.pgvector.create_indexes
```

이 단계는 판례 pgvector baseline 또는 vector/hybrid 비교 실험을 다시 할 때만 필요하다.

현재 Agent V2와 교통사고 일반판례 RAG V1 운영 기준은 BM25+Nori이므로 일반 복구 루트에서는 생략 가능하다.

## 2-12. Elasticsearch index 생성

BM25:

```powershell
python -B -m etl.fault_cases.src.traffic_precedents.precedent_search.elasticsearch.bm25_indexer
```

이 BM25 index는 현재 판례 RAG/Agent V2에서 사용하는 필수 index이다.

Vector - 선택:

```powershell
python -B -m etl.fault_cases.src.traffic_precedents.precedent_search.elasticsearch.vector_indexer
```

Vector index는 Elasticsearch vector/hybrid 비교 실험을 다시 할 때만 필요하다.

## 2-13. 판례 검색 샘플 재생성

운영 기준 필수 테스트는 BM25+Nori이다.

```powershell
python -B -m etl.fault_cases.src.traffic_precedents.precedent_search.elasticsearch.run_bm25_sample_queries
```

선택 실험:

```powershell
python -B -m etl.fault_cases.src.traffic_precedents.precedent_search.pgvector.run_sample_queries
python -B -m etl.fault_cases.src.traffic_precedents.precedent_search.elasticsearch.run_vector_sample_queries
python -B -m etl.fault_cases.src.traffic_precedents.precedent_search.elasticsearch.run_hybrid_sample_queries
```

현재 Agent V2에서 `fault_ratio_precedent`는 BM25+Nori로 붙어 있다.

따라서 pgvector/vector/hybrid 샘플 결과는 검색 방식 재비교가 필요할 때만 만든다.

## 2-14. 판례 A/B 후보 + reranker 평가 - 선택

```powershell
python -B -m etl.fault_cases.src.traffic_precedents.precedent_search.evaluation.export_retrieval_ab_candidates --top-k 5
python -B -m etl.fault_cases.src.traffic_precedents.precedent_search.evaluation.run_local_reranker --model models/bge-reranker-v2-m3 --input-field chunk_text --batch-size 4 --device cpu
python -B -m etl.fault_cases.src.traffic_precedents.precedent_search.evaluation.build_reranker_reports
python -B -m etl.fault_cases.src.traffic_precedents.precedent_search.evaluation.augment_answer_contexts
```

이 단계는 운영 필수가 아니다.

실행하는 경우:

```text
1. pgvector / BM25 / vector / hybrid 검색 방식을 다시 비교해야 할 때
2. 로컬 reranker 점수표를 다시 만들 때
3. 판례 검색 A/B 평가 보고서를 재생성할 때
```

실행하지 않아도 되는 경우:

```text
현재처럼 BM25+Nori를 운영 기준으로 그대로 사용할 때
```

## 2-15. 교통사고 일반판례 RAG 테스트

```powershell
python -B -m etl.fault_cases.src.traffic_precedents.precedent_search.traffic_law.run_bm25_sample_queries --top-k 5
python -B -m etl.fault_cases.src.traffic_precedents.precedent_search.traffic_law.build_rag_report
```

---

# 3. Agent text_ml_case_search 실행 순서

Agent는 PostgreSQL DB와 Elasticsearch index가 이미 준비되어 있어야 실제 RAG evidence를 붙일 수 있다.

## 3-0. 운영 진입점과 테스트 runner 구분

실제 운영에서 Supervisor 또는 백엔드가 호출해야 하는 진입점은 테스트 runner가 아니라 `agent.py`의 함수다.

운영 진입점:

```text
etl/fault_cases/src/agents/text_ml_case_search/agent.py
```

핵심 함수:

```python
run_text_ml_case_search(...)
```

운영 연결 흐름:

```text
Supervisor / Backend
→ run_text_ml_case_search(agent_input, es_client=client)
→ text_ml_case_search output schema 반환
```

예시:

```python
from etl.fault_cases.src.agents.text_ml_case_search.agent import run_text_ml_case_search
from etl.fault_cases.src.agents.text_ml_case_search.rag.es_client import get_elasticsearch_client

es_client = get_elasticsearch_client()

result = run_text_ml_case_search(
    agent_input=supervisor_input,
    es_client=es_client,
)
```

반면 아래 파일들은 운영 진입점이 아니라 테스트/검증/보고서 생성용 runner다.

```text
run_agent_sample.py
  - 단일 샘플 입력으로 Agent가 동작하는지 확인

run_full_optional_inputs.py
  - JSONL active input 10개를 읽어 Agent를 반복 실행

build_full_optional_report.py
  - Agent 실행 결과 JSON을 사람이 보기 좋은 보고서로 변환
```

즉 실제 서비스 연결은 `run_text_ml_case_search()`를 직접 호출하는 방식이고, PowerShell runner들은 개발/검증용이다.

## 3-1. 단위 테스트

```powershell
python -m pytest etl/fault_cases/src/agents/text_ml_case_search/tests
```

## 3-2. 단일 샘플 실행

```powershell
python -B -m etl.fault_cases.src.agents.text_ml_case_search.run_agent_sample
```

## 3-3. active input 10개 실행

입력 파일:

```text
etl/fault_cases/artifacts/review_case_output/schema_search_test/text_ml_case_search_agent_input_full_optional_fields.jsonl
```

실행:

```powershell
python -B -m etl.fault_cases.src.agents.text_ml_case_search.run_full_optional_inputs --limit 10
```

## 3-4. Agent 결과 보고서 생성

```powershell
python -B -m etl.fault_cases.src.agents.text_ml_case_search.build_full_optional_report
```

---

# 4. 삭제/복구 판단표

## 삭제되어도 다시 만들기 쉬운 것

```text
review_case_output/postgres_exports/
review_case_output/elasticsearch_exports/
review_case_output/retrieval_ab_exports/
review_case_output/agent_runs/

traffic_precedents_output/postgres_exports/
traffic_precedents_output/elasticsearch_exports/
traffic_precedents_output/retrieval_ab_exports/
traffic_precedents_output/traffic_law_rag/
```

이유:

```text
검색 결과, 평가 결과, Agent 실행 결과는 코드 실행으로 재생성 가능하다.
```

## 삭제되면 복구 비용이 큰 것

```text
review_case_output/crawled/(최종)과실비율심의사례_(54MB).pdf
review_case_output/preprocessed/review_case_documents.jsonl
review_case_output/preprocessed/review_case_chunks.jsonl

traffic_precedents_output/traffic_prec_reclass_verified/01_confirmed_traffic_cases.jsonl
traffic_precedents_output/traffic_prec_fault_ratio_verified/01_fault_ratio_confirmed_cases.jsonl

review_case_output/schema_search_test/text_ml_case_search_agent_input_full_optional_fields.jsonl
```

이유:

```text
DB 적재 또는 Agent 테스트 입력 기준이 되는 파일이다.
```

## 완전 재생성 시 시간이 오래 걸리는 단계

```text
1. 판례 API 수집
2. 대용량 판례 전처리/분류/검증
3. embedding 저장
4. Elasticsearch vector index 생성
5. local reranker 전체 평가
```

특히 embedding 저장은 API 비용이 발생할 수 있으므로 재실행 전에 반드시 필요한지 확인한다.

또한 현재 운영 기준은 BM25+Nori이므로 `Elasticsearch vector index 생성`과 `local reranker 전체 평가`는 검색 방식 재평가가 필요한 경우에만 실행한다.

---

# 5. 가장 짧은 복구 루트

이미 핵심 JSONL과 DB가 살아 있다면 전체를 처음부터 돌릴 필요는 없다.

## 심의사례 최소 복구

```text
preprocessed JSONL 있음
→ DB schema
→ DB load
→ search_text rebuild
→ BM25 index 생성
→ BM25 검색 확인
→ Agent 실행
```

선택:

```text
pgvector/vector/hybrid 비교가 필요하면 embedding, pgvector index, vector index를 추가 실행한다.
```

## 판례 최소 복구

```text
verified JSONL 2개 있음
→ DB schema
→ DB load
→ chunk 생성
→ BM25 index 생성
→ BM25 검색 확인
→ Agent 실행
```

선택:

```text
pgvector/vector/hybrid 비교가 필요하면 embedding, pgvector index, vector index, reranker 평가를 추가 실행한다.
```

## Agent만 다시 확인

```text
DB + Elasticsearch index 살아 있음
→ pytest
→ run_agent_sample
→ run_full_optional_inputs --limit 10
→ build_full_optional_report
```

---

# 6. 최종 결론

검색 결과 JSON/JSONL을 삭제했더라도 대부분은 다시 만들 수 있다.

진짜 중요한 기준 파일은 다음이다.

```text
심의사례:
- PDF
- review_case_documents.jsonl
- review_case_chunks.jsonl

판례:
- traffic_prec_reclass_verified/01_confirmed_traffic_cases.jsonl
- traffic_prec_fault_ratio_verified/01_fault_ratio_confirmed_cases.jsonl

Agent 테스트:
- text_ml_case_search_agent_input_full_optional_fields.jsonl
```

이 파일들이 살아 있으면 DB, RAG, Agent 결과는 순서대로 재생성할 수 있다.
