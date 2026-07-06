# 판례 검색 A-B 평가 결과 보고서

생성일: 2026-07-03T23:08:14

## 실험 개요

- 후보 수: 400
- query 수: 20
- retriever 수: 4
- reranker_model: `models/bge-reranker-v2-m3`
- reranker_input_field: `chunk_text`

## 전체 결과 요약

- Avg@5 기준 1위: `elasticsearch_bm25_nori` (0.6981)
- Top1 기준 1위: `elasticsearch_bm25_nori` (0.7038)
- reranker는 검색 결과를 재정렬하지 않고 평가 점수만 부여했다.
- retriever_score는 검색기 내부 점수이므로 직접 비교하지 않았다.

## Query별 Winner 수

| Retriever | Winner Count |
| --- | --- |
| elasticsearch_bm25_nori | 8 |
| elasticsearch_hybrid_bm25_vector_rrf | 11 |
| pgvector | 1 |

## Chunk Type 분포

| Chunk Type | Count |
| --- | --- |
| case_overview | 93 |
| fault_ratio_evidence | 78 |
| fault_ratio_metadata | 9 |
| holding_summary | 70 |
| main_text | 51 |
| traffic_metadata | 99 |

## 해석 기준

- BM25/Nori는 명시 키워드가 강한 질의에서 유리할 수 있다.
- vector 계열은 표현이 달라도 의미가 가까운 후보를 찾는 데 유리할 수 있다.
- hybrid는 BM25와 vector 양쪽에서 함께 잡힌 후보를 RRF로 우대한다.
- metadata chunk가 많이 이기는 경우, 법리 설명 근거로 충분한지 별도 검수가 필요하다.

## 다음 검수 항목

1. query별 winner 후보의 chunk_preview를 사람이 확인한다.
2. metadata chunk가 실제 답변 근거로 충분한지 확인한다.
3. 필요하면 query set을 20개 이상으로 확장한다.
4. RRF k=10/30/60 비교를 후속 실험으로 진행한다.