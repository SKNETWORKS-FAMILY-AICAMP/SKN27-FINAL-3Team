# 심의사례 검색 A-B 정량 점수표

생성일시: 2026-07-04T12:08:08

reranker_model: `models/bge-reranker-v2-m3`

reranker_input_field: `chunk_text`

## 1. 평가 개요

- query_count: 5
- retriever_count: 4
- top_k: 5
- candidate_count: 100
- 후보 수 계산: 5 queries x 4 retrievers x top5 = 100 candidates

## 2. Retriever별 평균 점수

| Retriever | Query Count | Candidate Count | Avg Top1 | Avg@5 | Avg Max@5 | Avg Min@5 | Avg Std@5 | Chart Top1 Hit | Chart Hit@5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| elasticsearch_bm25_nori | 5 | 25 | 0.7277 | 0.7115 | 0.7278 | 0.6688 | 0.0238 | 100.0% | 100.0% |
| elasticsearch_hybrid_bm25_vector_rrf | 5 | 25 | 0.7149 | 0.7221 | 0.7299 | 0.7084 | 0.0078 | 100.0% | 100.0% |
| elasticsearch_vector_cosine | 5 | 25 | 0.6676 | 0.6650 | 0.7149 | 0.6027 | 0.0413 | 100.0% | 100.0% |
| pgvector_cosine | 5 | 25 | 0.6676 | 0.6562 | 0.7107 | 0.6019 | 0.0401 | 100.0% | 100.0% |

## 3. Query별 Retriever 점수

| Query ID | Query | Retriever | Top1 | Avg@5 | Max@5 | Top Chunk Type | Chart Top1 | Chart@5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| review_q001 | 신호등 없는 중앙선 설치 도로에서 중앙선을 침범한 역주행 사고 | elasticsearch_bm25_nori | 0.7310 | 0.7282 | 0.7310 | case_overview | True | True |
| review_q001 | 신호등 없는 중앙선 설치 도로에서 중앙선을 침범한 역주행 사고 | elasticsearch_hybrid_bm25_vector_rrf | 0.7310 | 0.7243 | 0.7310 | evidence_issue | True | True |
| review_q001 | 신호등 없는 중앙선 설치 도로에서 중앙선을 침범한 역주행 사고 | elasticsearch_vector_cosine | 0.7310 | 0.7228 | 0.7310 | evidence_issue | True | True |
| review_q001 | 신호등 없는 중앙선 설치 도로에서 중앙선을 침범한 역주행 사고 | pgvector_cosine | 0.7310 | 0.7228 | 0.7310 | evidence_issue | True | True |
| review_q002 | 신호등 있는 사거리 교차로에서 녹색 직진 차량과 적색 직진 차량 충돌 | elasticsearch_bm25_nori | 0.7304 | 0.7303 | 0.7308 | case_overview | None | None |
| review_q002 | 신호등 있는 사거리 교차로에서 녹색 직진 차량과 적색 직진 차량 충돌 | elasticsearch_hybrid_bm25_vector_rrf | 0.7304 | 0.7303 | 0.7308 | case_overview | None | None |
| review_q002 | 신호등 있는 사거리 교차로에서 녹색 직진 차량과 적색 직진 차량 충돌 | elasticsearch_vector_cosine | 0.7102 | 0.6662 | 0.7304 | evidence_issue | None | None |
| review_q002 | 신호등 있는 사거리 교차로에서 녹색 직진 차량과 적색 직진 차량 충돌 | pgvector_cosine | 0.7102 | 0.6662 | 0.7304 | evidence_issue | None | None |
| review_q003 | 차로 변경 중 후행 직진 차량과 충돌한 사고의 과실비율 | elasticsearch_bm25_nori | 0.7302 | 0.6858 | 0.7303 | case_overview | None | None |
| review_q003 | 차로 변경 중 후행 직진 차량과 충돌한 사고의 과실비율 | elasticsearch_hybrid_bm25_vector_rrf | 0.7303 | 0.7303 | 0.7309 | case_overview | None | None |
| review_q003 | 차로 변경 중 후행 직진 차량과 충돌한 사고의 과실비율 | elasticsearch_vector_cosine | 0.5139 | 0.6311 | 0.7303 | evidence_issue | None | None |
| review_q003 | 차로 변경 중 후행 직진 차량과 충돌한 사고의 과실비율 | pgvector_cosine | 0.5139 | 0.5870 | 0.7091 | evidence_issue | None | None |
| review_q004 | 비보호 좌회전 차량과 녹색 신호 직진 차량 사이 교차로 사고 | elasticsearch_bm25_nori | 0.7306 | 0.7297 | 0.7306 | evidence_issue | None | None |
| review_q004 | 비보호 좌회전 차량과 녹색 신호 직진 차량 사이 교차로 사고 | elasticsearch_hybrid_bm25_vector_rrf | 0.7305 | 0.7293 | 0.7305 | case_overview | None | None |
| review_q004 | 비보호 좌회전 차량과 녹색 신호 직진 차량 사이 교차로 사고 | elasticsearch_vector_cosine | 0.7305 | 0.7277 | 0.7305 | case_overview | None | None |
| review_q004 | 비보호 좌회전 차량과 녹색 신호 직진 차량 사이 교차로 사고 | pgvector_cosine | 0.7305 | 0.7277 | 0.7305 | case_overview | None | None |
| review_q005 | 주차장 또는 이면도로에서 출차 차량과 직진 차량이 충돌한 사고 | elasticsearch_bm25_nori | 0.7165 | 0.6837 | 0.7165 | decision | None | None |
| review_q005 | 주차장 또는 이면도로에서 출차 차량과 직진 차량이 충돌한 사고 | elasticsearch_hybrid_bm25_vector_rrf | 0.6525 | 0.6962 | 0.7262 | evidence_issue | None | None |
| review_q005 | 주차장 또는 이면도로에서 출차 차량과 직진 차량이 충돌한 사고 | elasticsearch_vector_cosine | 0.6525 | 0.5773 | 0.6525 | evidence_issue | None | None |
| review_q005 | 주차장 또는 이면도로에서 출차 차량과 직진 차량이 충돌한 사고 | pgvector_cosine | 0.6525 | 0.5773 | 0.6525 | evidence_issue | None | None |

## 4. Query별 Winner

| Query ID | Query | Winner | Winner Avg@5 | Winner Top1 |
| --- | --- | --- | --- | --- |
| review_q001 | 신호등 없는 중앙선 설치 도로에서 중앙선을 침범한 역주행 사고 | elasticsearch_bm25_nori | 0.7282 | 0.7310 |
| review_q002 | 신호등 있는 사거리 교차로에서 녹색 직진 차량과 적색 직진 차량 충돌 | elasticsearch_hybrid_bm25_vector_rrf | 0.7303 | 0.7304 |
| review_q003 | 차로 변경 중 후행 직진 차량과 충돌한 사고의 과실비율 | elasticsearch_hybrid_bm25_vector_rrf | 0.7303 | 0.7303 |
| review_q004 | 비보호 좌회전 차량과 녹색 신호 직진 차량 사이 교차로 사고 | elasticsearch_bm25_nori | 0.7297 | 0.7306 |
| review_q005 | 주차장 또는 이면도로에서 출차 차량과 직진 차량이 충돌한 사고 | elasticsearch_hybrid_bm25_vector_rrf | 0.6962 | 0.6525 |

## 5. 전체 Chunk Type 분포

| Chunk Type | Count |
| --- | --- |
| arguments | 3 |
| case_overview | 47 |
| decision | 5 |
| evidence_issue | 45 |