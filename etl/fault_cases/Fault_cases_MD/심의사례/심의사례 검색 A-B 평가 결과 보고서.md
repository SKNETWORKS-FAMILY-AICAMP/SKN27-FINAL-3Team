# 심의사례 검색 A-B 평가 결과 보고서

생성일시: 2026-07-04T12:08:08

## 1. 실험 개요

- 후보 수: 100
- query 수: 5
- retriever 수: 4
- top_k: 5
- reranker_model: `models/bge-reranker-v2-m3`
- reranker_input_field: `chunk_text`

## 2. 왜 후보가 100개인가

현재 실험은 최종 평가가 아니라 smoke evaluation이다.
5개 심의사례 샘플 query를 4개 retriever가 각각 top5로 검색했기 때문에 후보 수는 100개다.

```text
5 queries x 4 retrievers x top5 = 100 candidates
```

여기서 4개 retriever는 실험 분석 관점의 구분이다. 서비스 후보 관점에서는 pgvector, BM25/Nori, hybrid의 3개 축으로 볼 수 있고, Elasticsearch vector는 hybrid 구성요소를 검증하기 위한 중간 비교군이다.

## 3. 전체 결과 요약

- Avg@5 기준 1위: `elasticsearch_hybrid_bm25_vector_rrf` (0.7221)
- Top1 기준 1위: `elasticsearch_bm25_nori` (0.7277)
- retriever_score는 검색기 내부 점수이므로 직접 비교하지 않았다.
- 공통 비교 점수는 local_reranker_score를 사용했다.

## 4. Query별 Winner 수

| Retriever | Winner Count |
| --- | --- |
| elasticsearch_bm25_nori | 2 |
| elasticsearch_hybrid_bm25_vector_rrf | 3 |

## 5. Chunk Type 관점 분석

| Retriever | case_overview | arguments | evidence_issue | decision |
| --- | --- | --- | --- | --- |
| elasticsearch_bm25_nori | 12 | 2 | 7 | 4 |
| elasticsearch_hybrid_bm25_vector_rrf | 18 | 1 | 5 | 1 |
| elasticsearch_vector_cosine | 9 | 0 | 16 | 0 |
| pgvector_cosine | 8 | 0 | 17 | 0 |

## 6. 해석 기준

- BM25/Nori는 신호위반, 중앙선 침범, 참고기준 번호처럼 명시 키워드가 강한 질의에서 유리할 수 있다.
- pgvector와 Elasticsearch vector는 사용자 표현이 문서 표현과 달라도 의미가 가까운 후보를 찾는 데 유리할 수 있다.
- hybrid는 BM25와 vector가 동시에 상위권으로 찾은 후보를 RRF로 올리는 방식이다.
- case_overview는 검색에는 강하지만, 답변 근거로는 decision chunk 보강이 필요할 수 있다.

## 7. 다음 검토 사항

1. query별 winner 후보의 chunk_preview를 사람이 확인한다.
2. case_overview가 top1일 때 같은 review_no의 decision chunk 보강 규칙이 필요한지 확인한다.
3. query set을 30개 이상으로 확장한다.
4. RRF k=10/30/60 비교는 후속 실험으로 분리한다.