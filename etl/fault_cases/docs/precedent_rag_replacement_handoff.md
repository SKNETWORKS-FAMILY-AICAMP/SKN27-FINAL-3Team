# 판례 RAG 교체 인수 문서

## 활성 파이프라인

```text
collect
→ validate-collection
→ preprocess
→ semantic-blocks
→ classify
→ validate-classification
→ build-rag-records
→ embed
→ load
```

전체 실행은 stage별 CLI 인자 배열을 담은 JSON 파일과 함께 실행한다.

```powershell
python -m etl.fault_cases.src.traffic_precedents.run_pipeline `
  --stage all `
  --pipeline-config C:\deployment\precedent_pipeline.json
```

최초 배포에서는 문서 임베딩을 다시 실행하지 않는다. 저장소에 포함된 다음 두 파일을
loader에 직접 전달한다.

```text
etl/fault_cases/bootstrap/precedent/qwen3_4b_bge_v1/
├─ 01_document_embeddings_qwen3_4b.npy
└─ 02_document_embedding_metadata.jsonl
```

DB 연결 없는 사전 검증:

```powershell
python -m etl.fault_cases.src.traffic_precedents.run_pipeline `
  --stage load `
  --embeddings etl/fault_cases/bootstrap/precedent/qwen3_4b_bge_v1/01_document_embeddings_qwen3_4b.npy `
  --metadata etl/fault_cases/bootstrap/precedent/qwen3_4b_bge_v1/02_document_embedding_metadata.jsonl
```

실제 적재 시 위 명령에 `--apply`와 `--dsn`을 추가한다. loader는 다음 조건을 모두
통과한 뒤에만 transaction을 시작한다.

- NPY SHA-256 일치
- metadata SHA-256 일치
- 원본 4,185행과 metadata 행 정렬 일치
- `enabled_in_general_accident_search=true` 선택 결과 3,339블록/825판례
- 선택 등급이 `GENERAL_READY_DIRECT` 또는 `SEED_READY`
- 임베딩 차원 2,560, float32, 유한값

## 검색 연결

과실비율 에이전트의 호출부는 수정하지 않았다.

```python
from etl.fault_cases.src.traffic_precedents.precedent_search.pgvector.retriever import (
    search_query,
)
```

활성 `search_query("fault_ratio", query, top_k)` 내부 흐름:

```text
Qwen3-Embedding-4B 질문 임베딩
→ 3,339 의미 블록 cosine 검색
→ 판례별 최고 블록
→ 고유 판례 Top 200
→ ACCIDENT_FACT + FAULT_DECISION 문맥
→ BGE rerank
→ 기존 에이전트 row 계약으로 Top K 반환
```

## 이번 작업에서 실행하지 않은 외부 작업

- 국가법령정보센터 실제 재수집
- Qwen 문서 재임베딩
- PostgreSQL schema 생성 및 데이터 적재
- Qwen/BGE GPU 실검색
- AWS 배포
- supervisor, 인정기준 RAG, 심의사례 RAG 변경
