# 판례 검색 A-B 정량 점수표

생성일: 2026-07-03T23:08:14

reranker_model: `models/bge-reranker-v2-m3`

reranker_input_field: `chunk_text`

## 전체 평균

| Retriever | Query Count | Avg Top1 | Avg@5 | Avg Max@5 | Avg Min@5 | Avg Std@5 |
| --- | --- | --- | --- | --- | --- | --- |
| elasticsearch_bm25_nori | 20 | 0.7038 | 0.6981 | 0.7197 | 0.6587 | 0.0235 |
| elasticsearch_hybrid_bm25_vector_rrf | 20 | 0.7013 | 0.6912 | 0.7216 | 0.6414 | 0.0316 |
| elasticsearch_vector_cosine | 20 | 0.6597 | 0.6370 | 0.6919 | 0.5690 | 0.0459 |
| pgvector | 20 | 0.6134 | 0.5964 | 0.6303 | 0.5543 | 0.0283 |

## Dataset별 평균

| Dataset | Retriever | Query Count | Avg Top1 | Avg@5 | Avg Max@5 | Avg Min@5 |
| --- | --- | --- | --- | --- | --- | --- |
| fault_ratio | elasticsearch_bm25_nori | 10 | 0.6987 | 0.7067 | 0.7264 | 0.6676 |
| fault_ratio | elasticsearch_hybrid_bm25_vector_rrf | 10 | 0.7018 | 0.6915 | 0.7284 | 0.6290 |
| fault_ratio | elasticsearch_vector_cosine | 10 | 0.6195 | 0.6280 | 0.6794 | 0.5617 |
| fault_ratio | pgvector | 10 | 0.6018 | 0.5932 | 0.6121 | 0.5626 |
| traffic | elasticsearch_bm25_nori | 10 | 0.7089 | 0.6894 | 0.7130 | 0.6497 |
| traffic | elasticsearch_hybrid_bm25_vector_rrf | 10 | 0.7008 | 0.6909 | 0.7148 | 0.6538 |
| traffic | elasticsearch_vector_cosine | 10 | 0.7000 | 0.6460 | 0.7043 | 0.5764 |
| traffic | pgvector | 10 | 0.6250 | 0.5995 | 0.6486 | 0.5460 |

## Query별 점수

| Query ID | Dataset | Query | Retriever | Top1 | Avg@5 | Max@5 | Top Chunk Type |
| --- | --- | --- | --- | --- | --- | --- | --- |
| fault_ratio_q001 | fault_ratio | 차로변경 사고에서 과실비율 판단 판례 | elasticsearch_bm25_nori | 0.7073 | 0.7006 | 0.7214 | fault_ratio_evidence |
| fault_ratio_q001 | fault_ratio | 차로변경 사고에서 과실비율 판단 판례 | elasticsearch_hybrid_bm25_vector_rrf | 0.7281 | 0.7133 | 0.7281 | fault_ratio_evidence |
| fault_ratio_q001 | fault_ratio | 차로변경 사고에서 과실비율 판단 판례 | elasticsearch_vector_cosine | 0.7197 | 0.7114 | 0.7219 | fault_ratio_evidence |
| fault_ratio_q001 | fault_ratio | 차로변경 사고에서 과실비율 판단 판례 | pgvector | 0.7197 | 0.7114 | 0.7219 | fault_ratio_evidence |
| fault_ratio_q002 | fault_ratio | 교통사고 손해배상 과실상계 비율 | elasticsearch_bm25_nori | 0.7292 | 0.7287 | 0.7292 | fault_ratio_evidence |
| fault_ratio_q002 | fault_ratio | 교통사고 손해배상 과실상계 비율 | elasticsearch_hybrid_bm25_vector_rrf | 0.5733 | 0.6470 | 0.7292 | case_overview |
| fault_ratio_q002 | fault_ratio | 교통사고 손해배상 과실상계 비율 | elasticsearch_vector_cosine | 0.5733 | 0.5911 | 0.6147 | case_overview |
| fault_ratio_q002 | fault_ratio | 교통사고 손해배상 과실상계 비율 | pgvector | 0.5733 | 0.5911 | 0.6147 | case_overview |
| fault_ratio_q003 | fault_ratio | 신호위반 교통사고 과실비율 판단 | elasticsearch_bm25_nori | 0.7262 | 0.7259 | 0.7290 | fault_ratio_evidence |
| fault_ratio_q003 | fault_ratio | 신호위반 교통사고 과실비율 판단 | elasticsearch_hybrid_bm25_vector_rrf | 0.7288 | 0.6939 | 0.7288 | fault_ratio_evidence |
| fault_ratio_q003 | fault_ratio | 신호위반 교통사고 과실비율 판단 | elasticsearch_vector_cosine | 0.7288 | 0.6566 | 0.7288 | case_overview |
| fault_ratio_q003 | fault_ratio | 신호위반 교통사고 과실비율 판단 | pgvector | 0.6444 | 0.6351 | 0.6497 | case_overview |
| fault_ratio_q004 | fault_ratio | 횡단보도 보행자 사고 과실상계 비율 | elasticsearch_bm25_nori | 0.7252 | 0.7045 | 0.7252 | fault_ratio_evidence |
| fault_ratio_q004 | fault_ratio | 횡단보도 보행자 사고 과실상계 비율 | elasticsearch_hybrid_bm25_vector_rrf | 0.7004 | 0.7160 | 0.7302 | fault_ratio_evidence |
| fault_ratio_q004 | fault_ratio | 횡단보도 보행자 사고 과실상계 비율 | elasticsearch_vector_cosine | 0.5081 | 0.6748 | 0.7302 | fault_ratio_evidence |
| fault_ratio_q004 | fault_ratio | 횡단보도 보행자 사고 과실상계 비율 | pgvector | 0.5062 | 0.5057 | 0.5064 | case_overview |
| fault_ratio_q005 | fault_ratio | 후방추돌 사고 과실비율 판례 | elasticsearch_bm25_nori | 0.5144 | 0.6717 | 0.7252 | fault_ratio_evidence |
| fault_ratio_q005 | fault_ratio | 후방추돌 사고 과실비율 판례 | elasticsearch_hybrid_bm25_vector_rrf | 0.6898 | 0.6573 | 0.7252 | holding_summary |
| fault_ratio_q005 | fault_ratio | 후방추돌 사고 과실비율 판례 | elasticsearch_vector_cosine | 0.6898 | 0.6049 | 0.6898 | case_overview |
| fault_ratio_q005 | fault_ratio | 후방추돌 사고 과실비율 판례 | pgvector | 0.5807 | 0.5833 | 0.6070 | case_overview |
| fault_ratio_q006 | fault_ratio | 중앙선 침범 사고 과실비율 판단 | elasticsearch_bm25_nori | 0.7297 | 0.7298 | 0.7303 | fault_ratio_evidence |
| fault_ratio_q006 | fault_ratio | 중앙선 침범 사고 과실비율 판단 | elasticsearch_hybrid_bm25_vector_rrf | 0.7238 | 0.7271 | 0.7299 | main_text |
| fault_ratio_q006 | fault_ratio | 중앙선 침범 사고 과실비율 판단 | elasticsearch_vector_cosine | 0.7283 | 0.6250 | 0.7283 | main_text |
| fault_ratio_q006 | fault_ratio | 중앙선 침범 사고 과실비율 판단 | pgvector | 0.5345 | 0.5326 | 0.5354 | case_overview |
| fault_ratio_q007 | fault_ratio | 교차로 좌회전 직진 사고 과실비율 | elasticsearch_bm25_nori | 0.7126 | 0.6721 | 0.7150 | main_text |
| fault_ratio_q007 | fault_ratio | 교차로 좌회전 직진 사고 과실비율 | elasticsearch_hybrid_bm25_vector_rrf | 0.7238 | 0.6789 | 0.7238 | fault_ratio_evidence |
| fault_ratio_q007 | fault_ratio | 교차로 좌회전 직진 사고 과실비율 | elasticsearch_vector_cosine | 0.5211 | 0.5403 | 0.5787 | case_overview |
| fault_ratio_q007 | fault_ratio | 교차로 좌회전 직진 사고 과실비율 | pgvector | 0.5211 | 0.5303 | 0.5374 | case_overview |
| fault_ratio_q008 | fault_ratio | 보행자 무단횡단 교통사고 과실상계 | elasticsearch_bm25_nori | 0.6936 | 0.7145 | 0.7287 | main_text |
| fault_ratio_q008 | fault_ratio | 보행자 무단횡단 교통사고 과실상계 | elasticsearch_hybrid_bm25_vector_rrf | 0.6936 | 0.7163 | 0.7287 | holding_summary |
| fault_ratio_q008 | fault_ratio | 보행자 무단횡단 교통사고 과실상계 | elasticsearch_vector_cosine | 0.7072 | 0.6818 | 0.7136 | fault_ratio_evidence |
| fault_ratio_q008 | fault_ratio | 보행자 무단횡단 교통사고 과실상계 | pgvector | 0.7072 | 0.6818 | 0.7136 | fault_ratio_evidence |
| fault_ratio_q009 | fault_ratio | 오토바이 사고 손해배상 과실비율 | elasticsearch_bm25_nori | 0.7294 | 0.7276 | 0.7297 | fault_ratio_evidence |
| fault_ratio_q009 | fault_ratio | 오토바이 사고 손해배상 과실비율 | elasticsearch_hybrid_bm25_vector_rrf | 0.7298 | 0.7291 | 0.7300 | fault_ratio_evidence |
| fault_ratio_q009 | fault_ratio | 오토바이 사고 손해배상 과실비율 | elasticsearch_vector_cosine | 0.5172 | 0.6805 | 0.7298 | fault_ratio_evidence |
| fault_ratio_q009 | fault_ratio | 오토바이 사고 손해배상 과실비율 | pgvector | 0.7294 | 0.6573 | 0.7294 | fault_ratio_evidence |
| fault_ratio_q010 | fault_ratio | 자전거 사고 손해배상 과실상계 비율 | elasticsearch_bm25_nori | 0.7198 | 0.6918 | 0.7302 | fault_ratio_evidence |
| fault_ratio_q010 | fault_ratio | 자전거 사고 손해배상 과실상계 비율 | elasticsearch_hybrid_bm25_vector_rrf | 0.7268 | 0.6359 | 0.7302 | fault_ratio_evidence |
| fault_ratio_q010 | fault_ratio | 자전거 사고 손해배상 과실상계 비율 | elasticsearch_vector_cosine | 0.5011 | 0.5140 | 0.5582 | case_overview |
| fault_ratio_q010 | fault_ratio | 자전거 사고 손해배상 과실상계 비율 | pgvector | 0.5011 | 0.5034 | 0.5051 | case_overview |
| traffic_q001 | traffic | 차로변경 중 발생한 교통사고 판례 | elasticsearch_bm25_nori | 0.7112 | 0.6909 | 0.7112 | main_text |
| traffic_q001 | traffic | 차로변경 중 발생한 교통사고 판례 | elasticsearch_hybrid_bm25_vector_rrf | 0.7249 | 0.6785 | 0.7249 | traffic_metadata |
| traffic_q001 | traffic | 차로변경 중 발생한 교통사고 판례 | elasticsearch_vector_cosine | 0.7249 | 0.6073 | 0.7249 | traffic_metadata |
| traffic_q001 | traffic | 차로변경 중 발생한 교통사고 판례 | pgvector | 0.5379 | 0.5527 | 0.5752 | case_overview |
| traffic_q002 | traffic | 신호위반 차량과 직진 차량의 충돌 사고 | elasticsearch_bm25_nori | 0.7098 | 0.7148 | 0.7294 | traffic_metadata |
| traffic_q002 | traffic | 신호위반 차량과 직진 차량의 충돌 사고 | elasticsearch_hybrid_bm25_vector_rrf | 0.7301 | 0.7263 | 0.7301 | traffic_metadata |
| traffic_q002 | traffic | 신호위반 차량과 직진 차량의 충돌 사고 | elasticsearch_vector_cosine | 0.7189 | 0.6800 | 0.7260 | traffic_metadata |
| traffic_q002 | traffic | 신호위반 차량과 직진 차량의 충돌 사고 | pgvector | 0.7189 | 0.6161 | 0.7260 | traffic_metadata |
| traffic_q003 | traffic | 보행자 횡단보도 사고 운전자의 책임 | elasticsearch_bm25_nori | 0.7299 | 0.7232 | 0.7299 | main_text |
| traffic_q003 | traffic | 보행자 횡단보도 사고 운전자의 책임 | elasticsearch_hybrid_bm25_vector_rrf | 0.7299 | 0.7239 | 0.7299 | holding_summary |
| traffic_q003 | traffic | 보행자 횡단보도 사고 운전자의 책임 | elasticsearch_vector_cosine | 0.7233 | 0.7157 | 0.7288 | holding_summary |
| traffic_q003 | traffic | 보행자 횡단보도 사고 운전자의 책임 | pgvector | 0.7233 | 0.7157 | 0.7288 | holding_summary |
| traffic_q004 | traffic | 중앙선 침범으로 발생한 교통사고 판례 | elasticsearch_bm25_nori | 0.7282 | 0.7287 | 0.7307 | main_text |
| traffic_q004 | traffic | 중앙선 침범으로 발생한 교통사고 판례 | elasticsearch_hybrid_bm25_vector_rrf | 0.7260 | 0.7293 | 0.7306 | holding_summary |
| traffic_q004 | traffic | 중앙선 침범으로 발생한 교통사고 판례 | elasticsearch_vector_cosine | 0.7260 | 0.7292 | 0.7306 | holding_summary |
| traffic_q004 | traffic | 중앙선 침범으로 발생한 교통사고 판례 | pgvector | 0.5149 | 0.5137 | 0.5168 | case_overview |
| traffic_q005 | traffic | 후방추돌 사고 운전자의 주의의무 | elasticsearch_bm25_nori | 0.7209 | 0.6346 | 0.7247 | traffic_metadata |
| traffic_q005 | traffic | 후방추돌 사고 운전자의 주의의무 | elasticsearch_hybrid_bm25_vector_rrf | 0.6192 | 0.6325 | 0.7303 | traffic_metadata |
| traffic_q005 | traffic | 후방추돌 사고 운전자의 주의의무 | elasticsearch_vector_cosine | 0.6803 | 0.6212 | 0.6803 | holding_summary |
| traffic_q005 | traffic | 후방추돌 사고 운전자의 주의의무 | pgvector | 0.6803 | 0.6498 | 0.6803 | holding_summary |
| traffic_q006 | traffic | 교차로 좌회전 차량과 직진 차량 충돌 사고 | elasticsearch_bm25_nori | 0.7290 | 0.7171 | 0.7290 | traffic_metadata |
| traffic_q006 | traffic | 교차로 좌회전 차량과 직진 차량 충돌 사고 | elasticsearch_hybrid_bm25_vector_rrf | 0.7155 | 0.7244 | 0.7275 | traffic_metadata |
| traffic_q006 | traffic | 교차로 좌회전 차량과 직진 차량 충돌 사고 | elasticsearch_vector_cosine | 0.7155 | 0.6289 | 0.7155 | traffic_metadata |
| traffic_q006 | traffic | 교차로 좌회전 차량과 직진 차량 충돌 사고 | pgvector | 0.5827 | 0.6180 | 0.7245 | traffic_metadata |
| traffic_q007 | traffic | 음주운전 교통사고 형사 책임 판례 | elasticsearch_bm25_nori | 0.7044 | 0.6801 | 0.7180 | traffic_metadata |
| traffic_q007 | traffic | 음주운전 교통사고 형사 책임 판례 | elasticsearch_hybrid_bm25_vector_rrf | 0.7180 | 0.6908 | 0.7180 | case_overview |
| traffic_q007 | traffic | 음주운전 교통사고 형사 책임 판례 | elasticsearch_vector_cosine | 0.7180 | 0.6009 | 0.7180 | traffic_metadata |
| traffic_q007 | traffic | 음주운전 교통사고 형사 책임 판례 | pgvector | 0.7180 | 0.6175 | 0.7180 | traffic_metadata |
| traffic_q008 | traffic | 오토바이와 자동차 충돌 교통사고 판례 | elasticsearch_bm25_nori | 0.7290 | 0.7191 | 0.7290 | traffic_metadata |
| traffic_q008 | traffic | 오토바이와 자동차 충돌 교통사고 판례 | elasticsearch_hybrid_bm25_vector_rrf | 0.7252 | 0.7171 | 0.7267 | traffic_metadata |
| traffic_q008 | traffic | 오토바이와 자동차 충돌 교통사고 판례 | elasticsearch_vector_cosine | 0.7252 | 0.6787 | 0.7252 | traffic_metadata |
| traffic_q008 | traffic | 오토바이와 자동차 충돌 교통사고 판례 | pgvector | 0.5067 | 0.5097 | 0.5224 | case_overview |
| traffic_q009 | traffic | 자전거와 자동차 충돌 사고 운전자 책임 | elasticsearch_bm25_nori | 0.7118 | 0.6989 | 0.7118 | traffic_metadata |
| traffic_q009 | traffic | 자전거와 자동차 충돌 사고 운전자 책임 | elasticsearch_hybrid_bm25_vector_rrf | 0.7086 | 0.7090 | 0.7148 | traffic_metadata |
| traffic_q009 | traffic | 자전거와 자동차 충돌 사고 운전자 책임 | elasticsearch_vector_cosine | 0.7086 | 0.6514 | 0.7148 | holding_summary |
| traffic_q009 | traffic | 자전거와 자동차 충돌 사고 운전자 책임 | pgvector | 0.7086 | 0.6514 | 0.7148 | holding_summary |
| traffic_q010 | traffic | 주정차 차량 관련 교통사고 판례 | elasticsearch_bm25_nori | 0.6152 | 0.5865 | 0.6168 | main_text |
| traffic_q010 | traffic | 주정차 차량 관련 교통사고 판례 | elasticsearch_hybrid_bm25_vector_rrf | 0.6105 | 0.5771 | 0.6152 | traffic_metadata |
| traffic_q010 | traffic | 주정차 차량 관련 교통사고 판례 | elasticsearch_vector_cosine | 0.5589 | 0.5470 | 0.5794 | case_overview |
| traffic_q010 | traffic | 주정차 차량 관련 교통사고 판례 | pgvector | 0.5589 | 0.5507 | 0.5794 | case_overview |

## Query별 Winner

| Query ID | Dataset | Query | Winner | Winner Avg@5 | Winner Top1 |
| --- | --- | --- | --- | --- | --- |
| fault_ratio_q001 | fault_ratio | 차로변경 사고에서 과실비율 판단 판례 | elasticsearch_hybrid_bm25_vector_rrf | 0.7133 | 0.7281 |
| fault_ratio_q002 | fault_ratio | 교통사고 손해배상 과실상계 비율 | elasticsearch_bm25_nori | 0.7287 | 0.7292 |
| fault_ratio_q003 | fault_ratio | 신호위반 교통사고 과실비율 판단 | elasticsearch_bm25_nori | 0.7259 | 0.7262 |
| fault_ratio_q004 | fault_ratio | 횡단보도 보행자 사고 과실상계 비율 | elasticsearch_hybrid_bm25_vector_rrf | 0.7160 | 0.7004 |
| fault_ratio_q005 | fault_ratio | 후방추돌 사고 과실비율 판례 | elasticsearch_bm25_nori | 0.6717 | 0.5144 |
| fault_ratio_q006 | fault_ratio | 중앙선 침범 사고 과실비율 판단 | elasticsearch_bm25_nori | 0.7298 | 0.7297 |
| fault_ratio_q007 | fault_ratio | 교차로 좌회전 직진 사고 과실비율 | elasticsearch_hybrid_bm25_vector_rrf | 0.6789 | 0.7238 |
| fault_ratio_q008 | fault_ratio | 보행자 무단횡단 교통사고 과실상계 | elasticsearch_hybrid_bm25_vector_rrf | 0.7163 | 0.6936 |
| fault_ratio_q009 | fault_ratio | 오토바이 사고 손해배상 과실비율 | elasticsearch_hybrid_bm25_vector_rrf | 0.7291 | 0.7298 |
| fault_ratio_q010 | fault_ratio | 자전거 사고 손해배상 과실상계 비율 | elasticsearch_bm25_nori | 0.6918 | 0.7198 |
| traffic_q001 | traffic | 차로변경 중 발생한 교통사고 판례 | elasticsearch_bm25_nori | 0.6909 | 0.7112 |
| traffic_q002 | traffic | 신호위반 차량과 직진 차량의 충돌 사고 | elasticsearch_hybrid_bm25_vector_rrf | 0.7263 | 0.7301 |
| traffic_q003 | traffic | 보행자 횡단보도 사고 운전자의 책임 | elasticsearch_hybrid_bm25_vector_rrf | 0.7239 | 0.7299 |
| traffic_q004 | traffic | 중앙선 침범으로 발생한 교통사고 판례 | elasticsearch_hybrid_bm25_vector_rrf | 0.7293 | 0.7260 |
| traffic_q005 | traffic | 후방추돌 사고 운전자의 주의의무 | pgvector | 0.6498 | 0.6803 |
| traffic_q006 | traffic | 교차로 좌회전 차량과 직진 차량 충돌 사고 | elasticsearch_hybrid_bm25_vector_rrf | 0.7244 | 0.7155 |
| traffic_q007 | traffic | 음주운전 교통사고 형사 책임 판례 | elasticsearch_hybrid_bm25_vector_rrf | 0.6908 | 0.7180 |
| traffic_q008 | traffic | 오토바이와 자동차 충돌 교통사고 판례 | elasticsearch_bm25_nori | 0.7191 | 0.7290 |
| traffic_q009 | traffic | 자전거와 자동차 충돌 사고 운전자 책임 | elasticsearch_hybrid_bm25_vector_rrf | 0.7090 | 0.7086 |
| traffic_q010 | traffic | 주정차 차량 관련 교통사고 판례 | elasticsearch_bm25_nori | 0.5865 | 0.6152 |