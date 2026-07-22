# Fault Cases RAG·에이전트 문서 지도

이 문서는 이후 구현자가 현재 운영 근거와 과거 실험 근거를 혼동하지 않도록 하는 출발점이다. 원본 문서는 아래 경로에 그대로 보존한다. 이 문서는 복사본의 진실 원천이 아니라 **활성 문서 목록**이다.

## 1. 최상위 운영 설계

| 문서 | 원본 경로 | 용도 |
|---|---|---|
| 통합 재구조화 실행계획 | `Fault_cases_MD/RAG_에이전트_통합_재구조화_및_운영구축_상세_실행계획.md` | 단계별 이관·운영 구축의 기준 |
| 사전 백업 검증 | `Fault_cases_MD/재구조화_이관관리/01_사전백업_검증기록_20260720.md` | 재구조화 전 복구 근거 |
| 이관 매핑표 | `Fault_cases_MD/재구조화_이관관리/02_이관_매핑표.md` | 원본 보존·어댑터 이관 원칙 |
| Docker·DB 분리 감사 | `Fault_cases_MD/재구조화_이관관리/02_도커_DB_분리_감사.md` | 법률/인정기준 그래프 분리 기준 |
| 슈퍼바이저 계약 감사 | `Fault_cases_MD/재구조화_이관관리/02_슈퍼바이저_계약_감사.md` | 입·출력 호환 기준 |

## 2. 인정기준 RAG

| 문서 | 원본 경로 | 용도 |
|---|---|---|
| Complete30 최종 의사결정 보고서 | `NEW_ABC_TEST_V6/COMPLETE30_인정기준_RAG_최종_의사결정_보고서.md` | 인정기준 RAG 운영 근거 |
| Complete30 V9 실험계획 | `NEW_ABC_TEST_V6/COMPLETE30_ABC_Neo4j_C2b_실험계획_V9.md` | V9 관계·계산 설계 근거 |
| C1/C2 관계 비교표 | `NEW_ABC_TEST_V6/artifacts/v7_complete30_abc/11_c2_pre_post/C1_C2_관계추가전후_비교표.md` | 관계 추가 전후 근거 |
| 공식 Complete30 자산 | `evaluation/fault_standard/complete30_v9/v1/` | 30문항 질문지·정답지·v1.1 매니페스트 |

## 3. 3코퍼스 임베딩 선정

| 문서 | 원본 경로 | 용도 |
|---|---|---|
| 공통 6모델 실행계획 | `Fault_cases_MD/임베딩_고도화/pgvector_3코퍼스_공통_임베딩_모델별_실행계획.md` | 모델·반복·평가 원칙 |
| 인정기준 AB 계획 | `Fault_cases_MD/임베딩_고도화/인정기준/pgvector_인정기준_임베딩_모델_AB_실험계획.md` | 인정기준 검색 평가 |
| 판례 AB 계획 | `Fault_cases_MD/임베딩_고도화/판례/pgvector_판례_임베딩_모델_AB_실험계획.md` | 판례 검색 평가 |
| 심의사례 AB 계획 | `Fault_cases_MD/임베딩_고도화/심의사례/pgvector_심의사례_임베딩_모델_AB_실험계획.md` | 심의사례 검색 평가 |
| 6모델 결과 | `artifacts/embedding_ab_shared/track_a_6models_native_3repeats/run_native7_20260718_v1/05_report/` | 모델 선정의 재현 근거 |

## 4. 판례 RAG 운영 결정

| 문서·자산 | 원본 경로 | 용도 |
|---|---|---|
| 판례 검색 고도화 계획 | `Fault_cases_MD/임베딩_고도화/판례/pgvector_판례_검색_고도화_단계별_실행계획.md` | B-1 → B-4 → 리랭커 검토 순서 |
| B-4 키워드 규칙 | `src/embedding_ab_shared/track_c_precedent_search_enhancement/configs/keyword_rules_b4_all_top10_failures.json` | 질의 조건 보강 규칙 |
| 최종 의사결정 점수표 | `artifacts/embedding_ab_shared/track_c_precedent_search_enhancement/run_precedent_retrieval_v3/07_final_operating_decision/전체_임베딩_검색_최종_의사결정_점수표.md` | B-4 운영 선택 근거 |
| 판례 RAG 최종 운영 보고서 | `artifacts/embedding_ab_shared/track_c_precedent_search_enhancement/run_precedent_retrieval_v3/07_final_operating_decision/판례_RAG_최종_운영_보고서.md` | `pgvector + B-4 키워드` 운영 근거 |

## 5. HISTORY로 관리할 대상

- 과거 모델 비교의 중간 run 폴더, RunPod 압축본, 표본 실험 결과
- B-1/B-2/B-3 등 B-4 이전의 판례 검색 중간 결과
- V6·초기 V7 등 Complete30 이전 실험 산출물
- `NEW_ABC_TEST_V6/lab_complete30_infra/`의 실험 전용 Compose

HISTORY는 삭제 대상이 아니다. 이후 재현이 필요하면 원본 입력 snapshot·manifest·실행 코드를 함께 사용한다. 신규 런타임이 직접 import하거나 읽어서는 안 된다.

