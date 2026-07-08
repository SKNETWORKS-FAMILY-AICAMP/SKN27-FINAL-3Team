# 데이터 전처리 결과서

| 항목 | 내용 |
|---|---|
| 프로젝트 | SKN27 교통분쟁 AI |
| 문서 목적 | 법령, 교통 판례, 과실비율 판례, 과실비율 심의사례 전처리 및 적재 결과 정리 |
| 작성 기준 | `etl/`, `storage/schemas`, 전처리 산출 JSON, PostgreSQL load report, embedding report, Git 브랜치/이슈 흐름 |
| 기준일 | 2026-07-06 |
| 현재 브랜치 | `feature/connect-fault-ratio-agent` |

---

## 1. 전처리 범위 요약

| 데이터 영역 | 원천/대상 | 처리 목적 | 현재 상태 |
|---|---|---|---|
| 법령 데이터 | 도로교통법, 시행령, 시행규칙, 고시/행정 기준 | 법령 근거 검색, 이의신청서 근거, 법률 guardrail | 법령 chunk/embedding/Neo4j hint graph A/B 검증 |
| 교통 판례 | 교통사고 관련 판례 API 수집 결과 | 교통사고 맥락 판례 검색 | 수집, 정제, 교통사고 재분류, DB/chunk/embedding 적재 완료 |
| 과실비율 판례 | 교통 판례 중 과실비율 근거가 있는 판례 | 과실비율 RAG evidence | 최종 973건 확정, DB/chunk/embedding 적재 완료 |
| 과실비율 심의사례 | 과실비율심의사례 PDF 472p | 유사 심의사례 검색, 비율 근거 보강 | 226건 문서, 904 chunks, 904 embeddings 적재 완료 |
| 과실비율 인정기준 | 2020 비정형, 2021 PM, 2023 공식, 2025 회전교차로 등 | 기본과실/수정요소/Neo4j 적재 후보 | 전처리 보정 이력과 코드 존재, 최종 적재는 별도 확정 필요 |

---

## 2. Git/이슈 기반 진행 흐름

| 담당/이슈 | 관련 내용 | 전처리 영향 |
|---|---|---|
| `#71` 법률 데이터/RAG/Neo4j | GraphRAG, PostgreSQL/Neo4j, 법령 검색 | 법령 chunk, embedding, hint graph 검증 |
| `#20` 법률 데이터 파이프라인 | 법령 수집/전처리/적재 | 법령 RAG DB seed 및 pipeline |
| `#69` 과실비율/판례/사례 텍스트 LangGraph | 판례/사례 데이터 수집, 전처리, 임베딩 | 교통 판례, 과실비율 판례, 심의사례 검색 |
| `#74` 과실비율 RAG 프로세스 | 과실비율 RAG 흐름도 | 과실비율 판례/심의사례 evidence schema |
| `#72` 고지서 OCR/과태료·범칙금 | OCR state, notice fields | 고지서 데이터는 전처리 결과보다 agent 입력 schema 중심 |
| `#118` law ground search | 법령 GraphRAG merge | 법령 근거 검색 runtime 연결 |
| `#139` fault ratio knowledge base | 과실비율 지식베이스 merge | fault ratio precedent RAG 연결 |
| `#140` text ML case search adapter | 텍스트 ML 사례 검색 adapter | 심의사례/판례 evidence 통합 |

---

## 3. 법령 데이터 전처리 결과

### 3.1 처리 구조

```text
국가 법령/행정 기준 수집
-> 조문/별표/서식 단위 chunk 생성
-> normalized text/domain tags/source metadata 부여
-> embedding 생성
-> PostgreSQL pgvector 적재
-> Neo4j Hint Graph로 일상어를 법률 용어로 확장
```

### 3.2 저장 스키마

| 테이블 | 내용 |
|---|---|
| `law_chunks` | chunk id, source, 조문/별표/서식 구분, 원문, 정규화 텍스트, 시행일/만료일, domain tags |
| `law_embeddings` | `law_chunks.chunk_id` 기준 embedding vector |

### 3.3 검증 결과

| 항목 | 결과 |
|---|---:|
| 법령 chunk 규모 | 99,594개 |
| LawRelation 규모 | 44,761개 |
| 비교 chunk 수 | 68건 |
| E5 exact-text Top-1 accuracy | 0.824 |
| OpenAI exact-text Top-1 accuracy | 1.000 |
| E5 Recall@5 | 1.000 |
| OpenAI Recall@5 | 1.000 |
| 최종 검색 후보 | OpenAI embedding + Neo4j Graph-RAG |

법령 검색 A/B 테스트에서는 순수 vector only보다 Neo4j Hint Graph를 결합한 Graph-RAG가 도메인 용어 변환에 강했다. 특히 `전동킥보드 -> 개인형 이동장치`, `스텔스 차량 -> 등화/야간 운행`처럼 사용자 표현과 법률 용어가 다른 경우 효과가 컸다.

---

## 4. 교통 판례 전처리 결과

### 4.1 수집 결과

| 항목 | 수치 |
|---|---:|
| 검색 keyword 수 | 40 |
| list rows seen | 37,500 |
| unique case ids | 17,512 |
| details fetched | 17,512 |
| saved candidates | 17,512 |
| errors | 0 |

### 4.2 정제/중복 제거 결과

| 항목 | 수치 |
|---|---:|
| input rows | 17,512 |
| valid detail rows | 15,716 |
| invalid detail rows | 1,796 |
| duplicate groups | 195 |
| duplicate removed rows | 196 |
| deduped rows | 15,520 |
| quality checked rows | 15,520 |
| usable for reclassification | 15,515 |
| unusable for reclassification | 5 |

주요 품질 플래그:

| 플래그 | 건수 |
|---|---:|
| numeric dense text detected | 3,845 |
| table artifact detected | 1,538 |
| many question marks remaining | 889 |
| full text too short | 5 |
| missing case category | 1 |

### 4.3 교통사고 관련성 재분류

| 항목 | 수치 |
|---|---:|
| confirmed input rows | 3,207 |
| confirmed demoted to non-traffic | 10 |
| possible input rows | 3,355 |
| possible promoted to confirmed | 365 |
| possible to non-traffic | 2,990 |
| non-traffic input rows | 8,958 |
| final confirmed traffic rows | 3,562 |
| final non-traffic rows | 11,958 |
| final all rows | 15,520 |

정책:

- 교통 단어만으로 승격하지 않고 사고 신호와 보조 문맥을 함께 판단한다.
- 기존 confirmed라도 사고 판례 근거가 약하면 non-traffic으로 강등한다.
- 최종 `01_confirmed_traffic_cases.jsonl`이 과실비율 2차 분류 입력이다.

### 4.4 PostgreSQL/pgvector 적재 결과

| 항목 | 결과 |
|---|---:|
| DB | `traffic_precedent_db` |
| case table | `traffic_precedent_cases` |
| expected rows | 3,562 |
| DB rows | 3,562 |
| count match | true |
| chunk strategy | `structured_1500_250` |
| chunk count | 25,952 |
| embedding model | `text-embedding-3-small` |
| embedding dim | 1,536 |
| embedding count after | 25,952 |
| too long input count | 0 |
| prompt tokens | 22,230,807 |

chunk type:

| type | count |
|---|---:|
| case_overview | 3,562 |
| traffic_metadata | 4,076 |
| holding_summary | 2,465 |
| main_text | 13,568 |
| law_reference | 2,281 |

---

## 5. 과실비율 판례 전처리 결과

### 5.1 2차 과실비율 분류 검증

| 항목 | 수치 |
|---|---:|
| fault confirmed input rows | 1,151 |
| verified fault confirmed rows | 973 |
| demoted to no fault ratio | 178 |
| possible input rows | 980 |
| possible promoted to confirmed | 0 |
| possible to no fault | 980 |
| no fault input rows | 1,431 |
| final fault ratio confirmed rows | 973 |
| final no fault ratio rows | 2,589 |
| final all rows | 3,562 |

검증 정책:

- `has_core_fault_ratio_context`가 유효해야 한다.
- 손해배상/보험 문맥이 있어야 한다.
- 가중치 근거 그룹이 2개 이상이어야 한다.
- 이자율/장해율 등 과실비율이 아닌 숫자 비율 오탐을 차단한다.
- 형사/행정/산재보험 중심 판례를 confirmed에서 제외한다.

### 5.2 PostgreSQL/pgvector 적재 결과

| 항목 | 결과 |
|---|---:|
| DB | `fault_ratio_precedent_db` |
| case table | `fault_ratio_precedent_cases` |
| expected rows | 973 |
| DB rows | 973 |
| count match | true |
| chunk strategy | `structured_1500_250` |
| chunk count | 10,833 |
| embedding model | `text-embedding-3-small` |
| embedding dim | 1,536 |
| embedding count after | 10,833 |
| too long input count | 0 |
| prompt tokens | 9,602,076 |

chunk type:

| type | count |
|---|---:|
| case_overview | 973 |
| fault_ratio_metadata | 973 |
| holding_summary | 863 |
| fault_ratio_evidence | 2,895 |
| main_text | 4,341 |
| law_reference | 788 |

---

## 6. 과실비율 심의사례 전처리 결과

### 6.1 원천 및 파싱

| 항목 | 결과 |
|---|---:|
| 원천 PDF | `(최종)과실비율심의사례_(54MB).pdf` |
| PDF pages | 472 |
| extractor | `pymupdf` |
| read page count | 472 |
| fallback errors | 0 |
| case text count | 226 |

### 6.2 전처리 결과

| 항목 | 수치 |
|---|---:|
| document count | 226 |
| source chunk count | 285 |
| RAG chunk count | 904 |
| quality report count | 226 |
| TOC item count | 226 |
| TOC-case link count | 226 |
| valid document count | 226 |
| review required document count | 0 |
| fatal flag count | 0 |
| warning: header road context missing | 116 |

### 6.3 PostgreSQL/pgvector 적재 결과

| 테이블 | 적재 건수 |
|---|---:|
| `review_case_documents` | 226 |
| `review_case_source_chunks` | 285 |
| `review_case_chunks` | 904 |
| `review_case_quality_reports` | 226 |
| `review_case_toc_items` | 226 |
| `review_case_toc_case_links` | 226 |

검증 결과:

| 항목 | 결과 |
|---|---|
| count validation | complete |
| mismatches | none |
| embedding model | `text-embedding-3-small` |
| embedding dim | 1,536 |
| embedding count after | 904 |
| inserted/updated embeddings | 894 |
| existing embedding before | 10 |
| too long input count | 0 |
| prompt tokens | 335,563 |

---

## 7. 과실비율 인정기준 전처리 상태

전처리 코드와 보정 이력은 `etl/fault_cases/src/fault_standard/preprocessing`과 `etl/fault_cases/Fault_cases_MD/인정기준/전처리 수정 계획`에 정리되어 있다.

| 데이터 | 처리 방향 | 상태 |
|---|---|---|
| 2020 비정형 기준 | PDF 텍스트를 계산 가능한 rule/chunk로 재구성 | 보정 이력 존재 |
| 2021 PM 대 자동차 기준 | 공유 해설/법규 chunk와 일반 chunk 분리 | 보정 이력 존재 |
| 2023 공식 인정기준 | rule, base fault, variants, adjustment factors, law refs 분리 | 대규모 보정 이력 존재 |
| 2025 2차로형 회전교차로 | lane step, entry/exit direction, role 근거 보존 | 보정 계획/코드 존재 |

현재 기준정보 전처리의 핵심 원칙:

- PDF 텍스트를 그대로 쪼개지 않고 계산/검색 가능한 의미 단위로 재구성한다.
- `base_faults`, `variants`, `adjustment_factors`, `law_refs`, `reference_cases`, `chunks`를 분리한다.
- diagram/image crop은 이번 텍스트 전처리 범위에서 제외한다.
- Neo4j 적재 시 수정요소가 아닌 문장이 수정요소로 들어가지 않도록 관계 경계를 보존한다.

---

## 8. 검색/Agent 연결 결과

| Agent/검색 | 입력 데이터 | 연결 방식 |
|---|---|---|
| `law_ground_search` | `law_chunks`, `law_embeddings`, Neo4j hint graph | 법령 근거 검색 |
| `text_ml_case_search` | review case + fault ratio precedent evidence | 유사 사례, 과실비율 범위, 증거 표시 |
| Supervisor | 상담 메시지, 파일 metadata, agent outputs | worker progress와 report generation으로 연결 |
| Report workbench | `reports`, `agent_results`, `analysis_display_results` | partial/final report 품질 표시 |

---

## 9. 품질 및 한계

| 영역 | 품질 확인 | 남은 한계 |
|---|---|---|
| 법령 RAG | Graph-RAG 조합에서 테스트 쿼리 5개 정답 근접률 1.00 | 점수 일부는 문서상 이론적 추정 포함 |
| 교통 판례 | 수집 오류 0, 최종 3,562건 적재 검증 완료 | 표/숫자 artifact 플래그가 일부 존재 |
| 과실비율 판례 | precision 중심으로 973건만 확정 | possible class는 전부 no_fault로 내려 recall 손실 가능 |
| 심의사례 | 226건 전부 valid, fatal flag 없음 | header road context missing 116건 |
| 인정기준 | 보정 이력과 전처리 코드 존재 | 최종 DB/Neo4j 적재 수치 별도 확인 필요 |
| 검색 실험 | pgvector, BM25/Nori, Elasticsearch, reranker 실험 구조 존재 | 로컬 reranker 모델은 GitHub LFS 한계로 커밋 대상 아님 |

---

## 10. 최종 결론

2026-07-06 기준, 프로젝트의 데이터 전처리는 단순 수집 단계가 아니라 RAG 검색과 Agent 출력에 연결 가능한 수준까지 진행됐다.

핵심 성과는 다음과 같다.

1. 교통 판례 17,512건 수집 후 15,520건 정제, 최종 교통사고 판례 3,562건을 DB에 적재했다.
2. 교통사고 판례 중 과실비율 판례 973건을 precision 중심으로 확정하고 10,833 chunks/embeddings를 생성했다.
3. 과실비율 심의사례 PDF 472페이지에서 226건 문서와 904 RAG chunks를 생성하고 DB/embedding 적재를 검증했다.
4. 법령 RAG는 OpenAI embedding + Neo4j Graph-RAG 조합이 최종 후보로 정리됐다.
5. 전처리 결과는 `text_ml_case_search`, `law_ground_search`, Supervisor, Report workbench와 연결되는 구조를 갖췄다.

후속 작업은 과실비율 인정기준의 최종 DB/Neo4j 적재 수치 확정, 법령 RAG 운영 seed 자동화, 개인정보/원문 보관 정책 확정, 검색 품질 테스트 케이스 확대다.

