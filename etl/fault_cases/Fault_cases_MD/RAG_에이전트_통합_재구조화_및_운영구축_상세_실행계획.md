# RAG·에이전트 통합 재구조화 및 운영 구축 상세 실행계획

- 문서 버전: `v1.0`
- 기준일: `2026-07-20`
- 상태: 실행 전 기준계획
- 적용 범위: 인정기준, 판례, 심의사례 검색 RAG와 이를 호출하는 에이전트
- 최우선 원칙: 외부 백업과 복원 검증이 끝나기 전에는 기존 파일·DB·Docker 구성을 이동·삭제·초기화하지 않는다.

---

## 1. 문서 목적

이 문서는 현재 `etl/fault_cases` 아래에 분산된 전처리 코드, 임베딩 실험 코드, 질문지·정답지, Docker 실험환경, 최종 보고서와 운영 후보를 다음 목적에 맞게 안전하게 재구조화하기 위한 실행 기준이다.

1. 세 코퍼스의 데이터 생성 ETL과 실제 검색 RAG를 분리한다.
2. Qwen3-Embedding-4B를 사용하는 운영 재색인 파이프라인을 만든다.
3. 인정기준·판례·심의사례 RAG를 독립 서비스로 만든다.
4. 에이전트는 세 RAG의 공식 서비스 인터페이스만 호출하게 한다.
5. 최종 운영 코드와 과거 실험 코드를 명확히 분리한다.
6. 재실행 가치가 있는 과거 실험은 `legacy_runnable`로 모듈화한다.
7. 단순 기록과 중간 산출물은 `HISTORY_LOCAL`에 보존한다.
8. 현재 승인된 질문지·정답지·최종 보고서·성능 근거를 잃지 않는다.
9. 모든 이동은 파일 인벤토리, SHA-256, 참조 경로 검사와 롤백 절차를 갖춘 뒤 수행한다.

이 문서는 폴더를 보기 좋게 정리하는 작업만을 다루지 않는다. 최종적으로 운영 가능한 DB 재색인, 검색 RAG, 공통 응답 계약, 에이전트와 재현 가능한 과거 실험 보관까지 포함한다.

---

## 2. 현재 확정된 운영 결정

### 2.1 공통 임베딩 모델

세 코퍼스의 운영 문서·질문 임베딩 모델은 다음 값으로 고정한다.

| 항목 | 확정값 |
|---|---|
| 모델 | `Qwen/Qwen3-Embedding-4B` |
| 모델 리비전 | `5cf2132abc99cad020ac570b19d031efec650f2b` |
| 기본 차원 | `2560` |
| 정규화 | `L2` |
| 검색 거리 | 코사인 거리 또는 정규화 벡터의 내적 |
| 문서·질문 모델 일치 | 반드시 동일 모델·동일 리비전·동일 차원 사용 |

기존 AB 실험 Parquet은 운영 DB의 공식 적재 원본으로 사용하지 않는다. 현재 확정 코퍼스 문서·청크를 운영 재색인 파이프라인으로 다시 임베딩한다. 기존 Parquet은 결과 비교와 회귀 검증용 증거로만 보존한다.

### 2.2 코퍼스별 운영 검색 방식

| 코퍼스 | 운영 검색 방식 | 후처리 |
|---|---|---|
| 인정기준 | Qwen 4B `pgvector` 검색 | Neo4j V9 관계 대조 후 결정론적 계산기 실행 |
| 판례 | B-4 사고조건 기반 질의 보강 후 Qwen 4B `pgvector` 검색 | 판례 단위 중복 제거 및 원문 근거 반환 |
| 심의사례 | Qwen 4B `pgvector` 검색 | 사례 단위 중복 제거 및 원문 근거 반환 |

### 2.3 제외된 운영 방식

다음 방식은 실험 근거는 보존하지만 현재 운영 검색에는 적용하지 않는다.

- 1024차원 고정 5모델 비교
- Qwen3-Embedding-8B
- E5 길이 잘림이 발생한 결과
- BGE 기반 판례 리랭커
- GPT-4o mini 판례 리랭커
- 검수 신뢰도를 통과하지 못한 판례 메타데이터 태그 가점·필터
- Elasticsearch를 판례 B-4 검색의 필수 구성으로 추가하는 방식

---

## 3. 현재 기준선과 보존 대상

### 3.1 공통 검색 평가자료

| 자료 | 현재 경로 | 기준 상태 |
|---|---|---|
| 공통 질문 50개 | `evaluation/common/embedding_ab/v1/common_fault_queries_v1.jsonl` | 승인·고정 |
| 공통 질문 manifest | `evaluation/common/embedding_ab/v1/query_manifest.json` | 현재 질문 SHA-256과 일치 |
| 인정기준 정답지 | `evaluation/fault_standard/embedding_ab/v1/ground_truth/fault_standard_qrels_v1.2.jsonl` | 50 Query, 111 판정, 승인 |
| 심의사례 정답지 | `evaluation/review_case/embedding_ab/v1/ground_truth/review_case_qrels_v1.jsonl` | 50 Query, 89 판정, 승인 |
| 판례 정답지 | `evaluation/precedent/embedding_ab/v1/ground_truth/precedent_qrels_v1.jsonl` | 50 Query, 58 판정, 승인 |

qrels 행 수가 50보다 큰 것은 질문 하나에 관련 문서가 여러 개일 수 있기 때문이다. 행 수를 질문 수와 혼동하지 않는다.

### 3.2 인정기준 Complete30 평가자료

| 자료 | 현재 경로 | 기준 상태 |
|---|---|---|
| 사용자 질문 30개 | `NEW_ABC_TEST_V6/evaluation/v7_complete30/complete30_consumer_questions_v1.jsonl` | 실제 V9 실행 입력 |
| 정답·해설 30개 | `NEW_ABC_TEST_V6/evaluation/v7_complete30/complete30_answer_key_with_explanations_v1.jsonl` | 실제 V9 평가 정답 |
| 교정 manifest | `NEW_ABC_TEST_V6/evaluation/v7_complete30/complete30_manifest_v1.1.json` | 현재 파일 해시 기준 PASS |
| G0 실행 manifest | `NEW_ABC_TEST_V6/artifacts/v7_complete30_abc/00_frozen_input/g0_manifest.json` | 질문·정답 분리 및 해시 바인딩 PASS |
| Qwen 4B manifest | `NEW_ABC_TEST_V6/artifacts/v7_complete30_abc/01_common_candidates/runpod_all_embeddings_manifest.json` | 277문서·30질문·2560차원 PASS |

기존 `complete30_manifest.json`은 해시가 실제 V9 실행 입력과 달라 이력용으로만 보존한다. 이후 재현과 이관에는 `complete30_manifest_v1.1.json`을 사용한다.

### 3.3 최종 결정 근거 문서

다음 문서는 삭제하거나 단순 HISTORY로 분류하지 않는다.

- `Fault_cases_MD/임베딩_고도화/pgvector_3코퍼스_공통_임베딩_모델별_실행계획.md`
- `Fault_cases_MD/임베딩_고도화/인정기준/pgvector_인정기준_임베딩_모델_AB_실험계획.md`
- `Fault_cases_MD/임베딩_고도화/판례/pgvector_판례_임베딩_모델_AB_실험계획.md`
- `Fault_cases_MD/임베딩_고도화/심의사례/pgvector_심의사례_임베딩_모델_AB_실험계획.md`
- `NEW_ABC_TEST_V6/COMPLETE30_ABC_Neo4j_C2b_실험계획_V9.md`
- `NEW_ABC_TEST_V6/COMPLETE30_인정기준_RAG_최종_의사결정_보고서.md`
- `NEW_ABC_TEST_V6/artifacts/v7_complete30_abc/11_c2_pre_post/C1_C2_관계추가전후_비교표.md`
- `artifacts/embedding_ab_shared/track_a_6models_native_3repeats/run_native7_20260718_v1/05_report/`
- `artifacts/embedding_ab_shared/track_c_precedent_search_enhancement/run_precedent_retrieval_v3/07_final_operating_decision/전체_임베딩_검색_최종_의사결정_점수표.md`
- `artifacts/embedding_ab_shared/track_c_precedent_search_enhancement/run_precedent_retrieval_v3/07_final_operating_decision/판례_RAG_최종_운영_보고서.md`

### 3.4 현재 DB 상태

| 구분 | DB | 현재 벡터 상태 |
|---|---|---|
| 운영 | `fault_standard_db` | 검색문서 3,793행, 임베딩은 비어 있음 |
| 운영 | `review_case_db` | 임베딩 테이블은 있으나 0행 |
| 운영 | `law_db` | 1024차원 법령 임베딩 99,315행, Qwen 4B 아님 |
| 운영 | 판례 전용 DB | 현재 없음 |
| 실험 | `fault_standard_new_abc_test` | Qwen 4B 문서 277, 질문 50 |
| 실험 | `fault_complete30_lab` | Qwen 4B 문서 277, 질문 30 |

운영 재색인은 기존 운영 테이블을 덮어쓰지 않고 새 스키마에 적재한다.

---

## 4. 목표 폴더 구조

```text
SKN27-FINAL-3Team/
├─ docker-compose.yml                         # 최종 공식 Docker 구성 1개
│
└─ etl/fault_cases/
   ├─ src/                                    # 데이터 생성 ETL
   │  ├─ fault_standard/
   │  ├─ review_case/
   │  ├─ traffic_precedents/
   │  └─ shared_embedding/                    # Qwen 4B 공통 임베딩 모듈
   │
   ├─ rag_runtime/                            # 실제 검색 런타임
   │  ├─ contracts/
   │  ├─ fault_standard/
   │  ├─ precedent/
   │  ├─ review_case/
   │  └─ shared/
   │
   ├─ agent_runtime/                          # 세 RAG 호출·통합
   │
   ├─ database/
   │  ├─ migrations/
   │  ├─ loaders/
   │  └─ validation/
   │
   ├─ evaluation/                             # 공식 질문지·정답지
   ├─ docs/                                   # 현재 유효한 공식 문서
   ├─ legacy_runnable/                        # 재실행 가능한 과거 실험
   ├─ artifacts/                              # 산출물, Git 제외
   └─ HISTORY_LOCAL/                          # 단순 기록, Git 제외
```

### 4.1 `src`의 책임

현재 코퍼스별 `src` 폴더의 수집·전처리·청킹 책임은 유지한다. 같은 기능을 새 `rag_runtime`에 복제하지 않는다.

```text
원본 수집 → 전처리 → 청킹/검색문서 생성 → 문서 임베딩 → DB 적재
```

### 4.2 `rag_runtime`의 책임

`rag_runtime`은 이미 적재된 운영 DB를 검색한다.

```text
사용자 질문 → 질문 임베딩 → DB 검색 → 코퍼스별 후처리 → 근거 반환
```

문서 전처리·청킹·전체 문서 임베딩 생성은 담당하지 않는다.

### 4.3 `agent_runtime`의 책임

에이전트는 DB나 실험 폴더를 직접 읽지 않는다. 각 RAG의 `service.py`만 호출하고 결과를 공통 JSON으로 묶는다.

---

## 5. 단계 1 — 프로젝트 외부 안전 백업

### 5.1 목적

현재 작업트리에는 Git 미추적 코드·평가자료가 있고 `artifacts`는 Git 제외 대상이다. 따라서 Git만으로는 재구조화 이전 상태를 복구할 수 없다.

### 5.2 백업 위치

```text
C:/dev/project_backups/
└─ SKN27_before_rag_restructure_20260720/
   ├─ workspace/
   ├─ databases/postgres/
   ├─ databases/neo4j/
   ├─ secure_env/
   ├─ backup_inventory.json
   ├─ CHECKSUMS_SHA256.txt
   ├─ git_status_before.txt
   └─ 백업_복원_검증보고서.md
```

백업은 작업 대상 프로젝트 밖에 둔다. 프로젝트 폴더와 같은 위치에만 두면 폴더 이동 오류나 일괄 삭제의 영향을 함께 받을 수 있다.

### 5.3 필수 백업 대상

- `etl/fault_cases/src`
- `etl/fault_cases/evaluation`
- `etl/fault_cases/Fault_cases_MD`
- `etl/fault_cases/NEW_ABC_TEST`
- `etl/fault_cases/NEW_ABC_TEST_V6`
- `etl/fault_cases/artifacts`의 코퍼스 확정 입력과 최종 실험 결과
- 루트 `docker-compose.yml`
- 운영·실험 PostgreSQL dump
- 운영·실험 Neo4j dump 또는 일관된 볼륨 스냅샷
- `.env` 파일은 `secure_env`에 별도 저장하고 일반 백업 목록·로그에 값을 출력하지 않는다.

### 5.4 제외 가능 대상

- `__pycache__`
- `*.pyc`
- 다시 다운로드할 수 있는 Hugging Face 모델 캐시
- 압축 해제 임시 폴더
- 중복 다운로드 파일

제외하기 전에 해당 파일이 실제 실행 결과가 아닌 캐시인지 확인한다.

### 5.5 백업 통과 기준

| 검사 | 통과 기준 |
|---|---|
| 파일 수 | 원본과 백업 대상 파일 수 일치 |
| 파일 크기 | 중요 파일 크기 일치 |
| SHA-256 | 중요 파일 전부 일치 |
| PostgreSQL | 별도 임시 DB에 dump 복원 성공 |
| Neo4j | dump 검사 또는 별도 임시 인스턴스 복원 성공 |
| 평가자료 | JSON/JSONL 파싱 및 행 수 일치 |
| 비밀정보 | 일반 로그·MD·manifest에 키 값 노출 0건 |

### 5.6 즉시 중단 기준

- 백업 대상 디스크 여유 공간 부족
- dump 명령 실패
- 복원 검사 실패
- 중요 파일 해시 불일치
- `.env` 또는 API 키가 일반 백업 보고서에 노출됨

### 5.7 롤백

이 단계는 원본을 변경하지 않는다. 실패하면 생성 중인 백업만 격리하고 원인을 수정한 뒤 처음부터 다시 실행한다.

---

## 6. 단계 2 — 파일 전체 인벤토리와 이관 매핑

### 6.1 산출물

```text
Fault_cases_MD/재구조화_이관관리/
├─ 현재_파일_전체_인벤토리.json
├─ 파일별_이관_매핑표.md
├─ 중요_파일_SHA256.json
├─ import_참조_관계.md
├─ Docker_DB_현재상태.md
├─ 활성_문서_후보목록.md
├─ Supervisor_입출력_스키마_현황감사.md
└─ RAG별_필드_매핑표.md
```

이 폴더는 백업이 아니다. 무엇을 유지하고 어디로 옮기며 무엇으로 대체되는지 기록하는 통제 문서다.

### 6.2 파일 분류값

| 분류 | 의미 |
|---|---|
| `KEEP` | 현재 경로와 역할 유지 |
| `MIGRATE` | 새 운영 구조로 기능 이관 |
| `LEGACY_RUNNABLE` | 다시 실행 가능한 과거 실험으로 모듈화 |
| `HISTORY` | 단순 기록·중간 산출물로 로컬 보존 |
| `DELETE_CANDIDATE` | 캐시·중복·임시파일, 최종 승인 후 삭제 후보 |

### 6.3 매핑표 필수 컬럼

- 현재 절대경로
- 파일 또는 폴더 유형
- 현재 역할
- 최종 분류
- 최종 경로
- 최종 운영에서 사용 여부
- 재실행 필요 여부
- 참조하는 import 또는 설정
- 필요한 입력 데이터
- 필요한 환경변수 이름
- SHA-256
- 대체되는 파일
- 이동 전 검증
- 이동 후 검증
- 롤백 방법

### 6.4 Supervisor 입출력 계약 선행 감사

새 계약을 추측해서 만들지 않는다. GitHub Issue #33과 기존 `src/agents/text_ml_case_search` 구현을 현재 외부 계약의 기준으로 삼고, 다음 자료를 필드 단위로 대조한다.

- 첨부된 `text_ml_case_search Agent Schema Contract`
- `src/agents/text_ml_case_search/schemas.py`
- `input/validator.py`, `input/context_builder.py`
- `builders/output_builder.py`
- `tests/test_supervisor_contract.py`
- `tests/test_agent_v2_output_schema.py`
- 인정기준 Complete30 입력·V9·계산 결과
- 판례 B-4 질의 보강·검색 결과
- 심의사례 검색 결과와 qrels

감사 결과에는 다음을 기록한다.

- 문서 계약에는 있으나 코드에 없는 필드
- 코드에는 있으나 문서 계약에 없는 필드
- 필수·옵션·nullable 불일치
- 같은 의미를 가진 중복 필드
- Supervisor 외부 공개 필드와 내부 디버그 필드
- 물리 DB명 또는 실험 경로에 결합된 값
- 코퍼스별 전용 결과를 넣을 공식 위치

`vision_evidence`는 텍스트 전용 요청도 허용할 수 있도록 빈 배열을 정상값으로 허용한다. `source_ref`는 입력 호환 alias로만 받고 출력은 `source_reference`로 통일한다.

### 6.5 통과 기준

- `src`, `evaluation`, `Fault_cases_MD`, `NEW_ABC_TEST*`, `embedding_ab_shared` 파일 누락 0건
- Python import 참조 경로 미확인 0건
- 실행 스크립트가 참조하는 입력 파일 미확인 0건
- 최종 질문지·정답지·manifest가 `HISTORY`로 잘못 분류된 건수 0건
- `.env`가 문서·Git 이관 대상으로 분류된 건수 0건
- Supervisor 계약 문서와 현재 구현의 필드 차이 미확인 0건
- 세 RAG 결과를 외부 `evidence`로 변환할 필드 매핑 누락 0건
- 물리 DB명·테이블명·실험 절대경로가 외부 계약에 고정된 항목 0건

---

## 7. 단계 3 — 새 구조 뼈대와 공통 계약 추가

### 7.1 작업 원칙

기존 코드를 바로 이동하지 않는다. 새 폴더와 공통 인터페이스를 추가한 뒤 기존 기능을 호출하는 어댑터를 먼저 만든다.

### 7.2 새 런타임 구조

```text
rag_runtime/
├─ contracts/
│  ├─ accident_fact.py
│  ├─ supervisor_input.py
│  ├─ supervisor_output.py
│  ├─ rag_evidence.py
│  ├─ search_request.py
│  └─ search_result.py
├─ fault_standard/
│  ├─ retriever.py
│  ├─ neo4j_reranker.py
│  ├─ calculator.py
│  └─ service.py
├─ precedent/
│  ├─ query_expander.py
│  ├─ retriever.py
│  └─ service.py
├─ review_case/
│  ├─ retriever.py
│  └─ service.py
└─ shared/
   ├─ query_embedder.py
   ├─ postgres_client.py
   ├─ neo4j_client.py
   └─ settings.py
```

### 7.3 Supervisor 외부 입력 계약

외부 입력은 기존 `text_ml_case_search` 계약의 `agent_input` 구조를 v1 기준으로 채택한다.

- `contract_version`
- `session_id`
- `message_id`
- `job_id`
- `node_code`
- `raw_user_text`
- `query_text`
- `vision_evidence`
- `insurer_claim`
- `ocr_evidence`
- `required_outputs`

`session_id`, `message_id`, `job_id`, `node_code`, `query_text`는 기본 필수값으로 유지한다. `vision_evidence`는 빈 배열을 허용하고, `insurer_claim`과 `ocr_evidence`는 `null`을 허용한다. `required_outputs`는 허용된 출력 이름 enum만 받게 하며 알 수 없는 값은 명확한 검증 오류로 반환한다.

개별 RAG의 내부 `SearchRequest`는 외부 입력을 그대로 복제하지 않는다. 정규화된 사고 Fact, 검색 텍스트, `top_k`, `candidate_k`, 요청 ID, 런타임 버전만 전달한다.

### 7.4 Supervisor 외부 출력 계약

외부 출력은 기존 계약을 v1 기준으로 채택한다.

- `contract_version`
- `node_code`
- `status`: `success`, `partial`, `failed`
- `structured_result`
- `evidence`
- `next_actions`
- `limitations`
- `missing_fields`

`structured_result`의 기본 필드는 다음과 같다.

- `normalized_description`
- `accident_type_candidates`
- `issue_tags`
- `evidence_tags`
- `recommended_evidence`
- `insurer_claim_review`
- `similar_cases`
- `ratio_range_label`
- `reliability_score`
- `limitations`

현재 코드에 이미 존재하는 `display_evidence`, `search_text`, `source_summary`는 필드 감사 후 외부 공개 또는 내부 전용 여부를 확정한다. `rag_debug`는 Supervisor 공개 계약이 아니라 운영 로그·디버그 출력으로 분리하는 것을 기본 원칙으로 한다.

### 7.4.1 RAG Evidence 계약

세 RAG는 내부 결과를 다음 공통 `evidence` 구조로 변환한다.

- `source_type`
- `title`
- `source_reference`
- `metadata`
- `chunk_text` 또는 사용자 노출용 근거 요약
- `confidence`

`source_reference`는 물리 DB명이나 테이블명에 종속되지 않는 논리 참조값을 사용한다.

```text
standard:<rule_id>#<evidence_id>
precedent:<case_id>#<chunk_id>
review_case:<case_id>#<chunk_id>
law:<law_id>#<article_id>
```

기존 `review_case_db:...`, `fault_ratio_precedent_db:...` 형식은 입력 호환·이력 파싱용으로만 허용하고 신규 출력에서는 사용하지 않는다.

### 7.4.2 점수 의미 분리

`confidence`와 코사인 유사도를 같은 값으로 사용하지 않는다.

- `similarity_score`: 임베딩 코사인 유사도
- `retrieval_score`: 검색기가 최종 정렬에 사용한 점수
- `rerank_score`: 리랭커를 사용할 때만 기록
- `rank`: 최종 반환 순위
- `score_type`: 점수 산식 식별자
- `confidence`: 별도의 검증 가능한 신뢰도 산식이 있을 때만 사용하고, 없으면 `null`

### 7.4.3 코퍼스별 전용 결과

공통 `evidence`를 훼손하지 않고 `metadata` 또는 명시적 전용 결과 객체로 확장한다.

- 인정기준: `selected_rule`, `neo4j_validation`, `calculation_status`, `calculation_result`
- 판례: `retrieval_method`, `query_expansion_applied`, `matched_conditions`, `index_version`
- 심의사례: `review_no`, `decision_fault_ratio`, `party_roles`, `chunk_type`

판례 B-4 출력에는 Query ID, 정답 판례 ID, qrels 또는 기존 정답 순위를 넣지 않는다.

### 7.4.4 계약 버전 변경 규칙

- 호환되는 옵션 필드 추가: minor 버전 증가
- 기존 필드 제거·이름 변경·타입 변경: major 버전 증가
- 신규 출력은 항상 `contract_version`을 포함
- Supervisor와 Agent가 지원하는 버전이 다르면 조용히 변환하지 않고 명시적 오류 또는 호환 어댑터 사용
- 계약 변경 시 JSON 예시, OpenAPI, 타입 정의, 계약 테스트를 함께 변경

### 7.5 한국어 작성 규칙

- 새 MD 문서는 한국어로 작성한다.
- 코드의 모듈·클래스·함수 docstring은 한국어로 작성한다.
- 함수의 목적, 입력, 출력, 예외를 한국어로 설명한다.
- 복잡한 분기, DB 쿼리, 점수 계산에는 한국어 주석을 작성한다.
- 단순 대입문마다 의미 없는 주석을 반복하지 않고, 데이터 흐름과 판단 근거가 드러나도록 작성한다.

### 7.6 통과 기준

- 세 `service.py`가 같은 요청·응답 계약 사용
- `text_ml_case_search` 외부 계약 v1과 테스트가 일치
- 입력·출력 모든 예제가 JSON Schema 또는 타입 검증을 통과
- `success`, `partial`, `failed` 상태 전환 테스트 통과
- 한 RAG 실패 시 `partial`과 코퍼스별 오류가 보존됨
- 코사인 유사도와 `confidence`를 같은 필드로 반환하는 코드 0건
- 신규 `source_reference`에 물리 DB명·테이블명 포함 0건
- 기존 코드 수정 없이 어댑터 단위 테스트 통과
- 절대경로 0건
- import 순환 0건
- `.env`가 없을 때 호출 전 명확한 한국어 오류 반환
- 비밀 값이 로그에 출력되는 코드 0건

---

## 8. 단계 4 — 평가자료와 공식 MD 재구성

### 8.1 평가자료 구조

현재 공통 50문항 구조는 유지한다. `NEW_ABC_TEST_V6` 안의 Complete30 자료만 공식 평가 위치로 옮긴다.

```text
evaluation/
├─ common/embedding_ab/v1/
├─ fault_standard/
│  ├─ embedding_ab/v1/ground_truth/
│  └─ complete30_v9/v1/
├─ precedent/embedding_ab/v1/ground_truth/
└─ review_case/embedding_ab/v1/ground_truth/
```

Complete30 이동 전 모든 참조 코드를 검색하고 새 경로를 인자로 받을 수 있게 수정한다. 이동 직후 기존 위치에 의존하는 코드가 0건인지 검사한다.

### 8.2 공식 문서 구조

```text
docs/
├─ README_문서_지도.md
├─ 활성_문서_목록.json
├─ architecture/
├─ domains/
│  ├─ fault_standard/
│  ├─ precedent/
│  └─ review_case/
├─ evaluation/
├─ operations/
├─ decisions/
└─ history/
```

### 8.3 공식 운영 문서

- `전체_RAG_에이전트_아키텍처.md`
- `인정기준_RAG_운영명세.md`
- `판례_RAG_운영명세.md`
- `심의사례_RAG_운영명세.md`
- `Qwen4_운영_DB_재색인_절차.md`
- `DB_적재_검증절차.md`
- `Docker_실행_및_복구절차.md`
- `최종_성능_기준선.md`
- `text_ml_case_search_Supervisor_입출력_계약_v1.md`
- `Qwen4_선정_결정.md`
- `판례_B4_선정_결정.md`
- `인정기준_Neo4j_V9_선정_결정.md`

### 8.4 활성 문서 목록

에이전트와 개발 도구는 전체 MD를 무작위로 검색하지 않고 `활성_문서_목록.json`에 등록된 현재 문서만 공식 기준으로 사용한다.

등록 필드:

- 문서 경로
- 문서 역할
- 적용 코퍼스
- 버전
- 상태
- 대체한 이전 문서
- 근거 산출물
- 마지막 검증일

### 8.5 통과 기준

- 공통 50문항과 세 qrels 해시 유지
- Complete30 질문·정답 해시 유지
- manifest 참조 경로 유효
- 공식 MD 내부 링크 오류 0건
- 운영 문서에서 HISTORY 문서를 현재 기준으로 지칭하는 오류 0건
- 에이전트가 참조해야 할 문서가 활성 목록에서 누락된 건수 0건

---

## 9. 단계 5 — 통합 DB 스키마와 Docker 운영구조

### 9.0 선행 관문: 코퍼스 적재 현황 감사

새 DB나 벡터 테이블을 만들기 전에, 세 코퍼스가 현재 어디까지 진행되었는지 읽기 전용으로 확인한다. 전처리·청킹 파일이 존재한다는 사실만으로 운영 DB 적재가 완료됐다고 가정하지 않는다.

코퍼스별로 다음을 대조한다.

- 원본 문서 수와 원본 파일 SHA-256
- 전처리 문서 수와 전처리 manifest
- 청크 수와 청크 manifest
- 현재 PostgreSQL의 DB·스키마·테이블 존재 여부
- DB 원본 행·청크 행·벡터 행 수
- DB 행의 문서 ID·청크 ID가 확정 JSONL과 일치하는지
- 기존 적재 보고서·오류 로그·재실행 스크립트 존재 여부

현재 확인된 판례 상태는 다음과 같다.

```text
확정 판례 원본 987건: 존재
확정 판례 청크 8,334건: 존재
Qwen 4B AB 실험 벡터: Parquet으로 존재
운영 PostgreSQL 판례 DB·원본 테이블·청크 테이블·벡터 테이블: 없음
```

따라서 판례는 Qwen 4B 재색인 전에 먼저 원본 판례와 청크를 운영 DB에 적재하는 기본 적재 단계가 필요하다.

### 9.1 Docker 원칙

최종 공식 Compose는 프로젝트 루트 `docker-compose.yml` 하나로 관리한다. 여기서 "통합"은 컨테이너를 한 Compose에서 함께 실행·관찰한다는 뜻이며, 기존 데이터베이스·그래프·볼륨을 병합한다는 뜻이 아니다. 기존 실험 Compose는 운영 전환이 끝날 때까지 유지하고, 백업·복원 검증 후 `legacy_runnable` 또는 `HISTORY_LOCAL`로 분류한다.

특히 기존 법률 Neo4j 서비스 `skn27-neo4j`와 볼륨 `neo4j_data`·`neo4j_logs`는 보호 대상이다. 인정기준 V9를 위해 기존 Neo4j의 노드, 관계, 제약조건, 데이터베이스, 환경변수, 볼륨 또는 재시작 정책을 변경하지 않는다.

### 9.2 PostgreSQL 논리 분리

한 PostgreSQL 컨테이너를 사용하되 코퍼스별 DB와 스키마를 분리한다.

```text
skn27-postgres
├─ fault_standard_db.rag_qwen4
├─ review_case_db.rag_qwen4
├─ precedent_db.rag_qwen4
└─ law_db                         # 기존 유지
```

### 9.2.1 기본 코퍼스 적재와 벡터 적재의 분리

운영 DB 적재는 두 단계를 분리한다.

```text
기본 코퍼스 적재
  원본 문서·메타데이터·청크·원문 위치·해시를 DB에 적재
        ↓
Qwen 4B 벡터 적재
  동일 문서·청크 ID에 2560차원 벡터와 모델 정보를 연결
```

판례는 다음 순서가 필수다.

```text
987개 판례 원본·메타데이터 적재
  → 8,334개 청크·원문 위치·해시 적재
  → 문서·청크 관계 검증
  → Qwen 4B 임베딩 생성
  → 8,334개 벡터 적재
```

벡터만 먼저 넣거나 JSONL 파일에만 청크를 남긴 채 검색 DB를 만드는 방식을 금지한다.

### 9.3 Qwen 4B 공통 테이블 계약

각 코퍼스는 최소한 다음 정보를 보관한다.

- 문서 또는 청크 기본키
- 상위 문서 또는 사건 ID
- 임베딩 입력 텍스트
- `vector(2560)`
- 모델명
- 모델 리비전
- 정규화 방식
- 원문 SHA-256
- 임베딩 입력 SHA-256
- 인덱스 버전
- 적재 실행 ID
- 생성 시각

기존 OpenAI 1536차원 또는 1024차원 벡터와 같은 컬럼에 혼합하지 않는다.

### 9.4 Neo4j 원칙: 법률 그래프와 인정기준 V9 그래프의 물리 분리

Neo4j는 인정기준 V9 관계 대조에만 사용한다. 판례와 심의사례가 명확한 효과 검증 없이 Neo4j에 의존하지 않게 한다.

기존 법률 Neo4j와 인정기준 V9 Neo4j는 같은 데이터베이스, 같은 컨테이너 또는 같은 볼륨을 사용하지 않는다. Neo4j Community 환경은 사용자 데이터베이스를 분리 운영하는 용도로 적합하지 않으므로, 스키마 이름·레이블 접두사만으로 함께 보관하는 방식도 사용하지 않는다.

```text
docker-compose.yml
├─ skn27-neo4j                         # 기존 법률 그래프, 수정 금지
│  ├─ neo4j_data                       # 기존 볼륨 유지
│  └─ neo4j_logs                       # 기존 로그 볼륨 유지
│
└─ fault-standard-neo4j                # 인정기준 V9 전용 신규 서비스
   ├─ fault_standard_neo4j_data        # 신규 전용 볼륨
   └─ fault_standard_neo4j_logs        # 신규 전용 로그 볼륨
```

인정기준 RAG는 공용 `NEO4J_URI`를 사용하지 않고 다음 전용 환경변수만 사용한다.

- `FAULT_STANDARD_NEO4J_URI`
- `FAULT_STANDARD_NEO4J_USER`
- `FAULT_STANDARD_NEO4J_PASSWORD`
- `FAULT_STANDARD_NEO4J_DATABASE`

신규 서비스는 법률 Neo4j와 host port, Docker volume, 컨테이너 이름, 비밀번호 변수, 초기화 스크립트를 공유하지 않는다. 외부 host port가 필요하지 않다면 Docker 내부 네트워크로만 연결한다.

### 9.5 마이그레이션 순서

1. 기존 PostgreSQL·법률 Neo4j·인정기준 실험 Neo4j dump 생성
2. 세 코퍼스의 원본·전처리·청크·현재 DB 적재 현황을 읽기 전용으로 감사하고 기준선 보고서 생성
3. 법률 Neo4j의 컨테이너명·볼륨명·DB 목록·노드·관계 수를 읽기 전용 보호 기준선으로 기록
4. 새 PostgreSQL DB·스키마 생성 SQL과 `fault-standard-neo4j` 전용 Compose 정의 작성
5. 임시 테스트 DB와 신규 전용 Neo4j 서비스에만 정의 적용
6. 기존 법률 Neo4j의 컨테이너·볼륨·DB·노드·관계 수가 변하지 않았는지 재검증
7. 적재 없이 PostgreSQL 스키마와 신규 Neo4j 제약조건 검증
8. 코퍼스별 원본 문서·메타데이터·청크를 새 운영 DB에 기본 적재
9. 기본 적재 건수·ID·원문 위치·해시 검증
10. Qwen 4B 재색인과 벡터 적재
11. 벡터 건수·해시·차원 검증
12. RAG가 새 스키마와 전용 Neo4j만 읽도록 기능 플래그 적용
13. 기존 테이블과 기존 법률 Neo4j는 전환 검증 종료까지 유지

### 9.6 통과 기준

- 기존 테이블 변경·삭제 0건
- 기존 법률 Neo4j의 컨테이너 이름·볼륨 이름·DB 목록 변경 0건
- 기존 법률 Neo4j의 노드·관계 수 변경 0건
- 인정기준 V9 Neo4j가 `fault-standard-neo4j` 전용 컨테이너·전용 볼륨만 사용
- 법률 Neo4j와 인정기준 V9 Neo4j 사이의 공용 Docker volume·공용 환경변수·공용 초기화 스크립트 0건
- 판례 원본 987건과 청크 8,334건의 기본 적재가 벡터 적재 전에 완료
- 판례 원본·청크·벡터의 문서 ID·청크 ID 연결 누락 0건
- 벡터 차원 2560 외 값 0건
- NULL 벡터 0건
- 중복 기본키 0건
- 모델명·리비전 누락 0건
- 원문 해시 누락 0건
- 새 스키마 dump·복원 성공

---

## 10. 단계 6 — Qwen 4B 운영 재색인 파이프라인

이 단계는 단계 5의 기본 코퍼스 적재 검증이 통과한 뒤에만 시작한다. 여기서 "재색인"은 벡터 파일만 생성하는 작업이 아니라, 수집·전처리·청킹이 끝난 확정 입력을 다시 검증하고 Qwen 4B 벡터를 생성한 뒤 DB에 이미 적재된 문서·청크와 정확히 연결하여 운영 인덱스 버전으로 승격하는 전체 절차다.

기존 AB 실험 Parquet과 단계 5에서 구조 검증 목적으로 시험 적재한 벡터는 운영 공식 벡터로 승인하지 않는다. 새 운영 재색인 결과를 기존 시험 데이터에 추가하거나 섞지 않고, 새 실행 ID의 staging 영역에 적재한 뒤 최종 검증을 통과했을 때만 운영 버전을 전환한다.

### 10.1 시작 조건: 크롤링·전처리·청크 결과 재검토

RunPod 번들을 만들기 전에 세 코퍼스의 상류 데이터 파이프라인을 읽기 전용으로 감사한다. 기존 결과가 통과하면 다시 크롤링하거나 다시 청킹하지 않고 현재 결과를 확정 입력 스냅샷으로 동결한다. 실패하면 임베딩을 시작하지 않고 해당 코퍼스의 수집·전처리·청킹 단계로 돌아간다.

| 검사 범위 | 필수 검사 |
|---|---|
| 원본 | 원본 건수, 출처, 원문 위치, 원본 SHA-256, 파싱 가능 여부 |
| 전처리 | 빈 본문, 비정상 문자, 제목·사건번호·페이지 등 필수 메타데이터 보존 여부 |
| 검색 단위 | 문서·청크 ID 유일성, 상위 문서 ID 연결, 누락·중복, 길이 분포, 문장 경계 훼손 여부 |
| 평가 연결 | 승인 질문 ID와 qrels 문서 ID가 실제 운영 문서 ID로 연결되는지 여부 |
| DB 대조 | 단계 5에 기본 적재한 문서·청크 ID 집합 및 입력 텍스트 SHA-256과의 일치 여부 |

코퍼스별 검색 단위는 억지로 동일하게 만들지 않는다.

- 인정기준은 확정 Rule 검색문서 277개를 검색 단위로 사용하고 각 검색문서가 원문 근거와 연결되는지 검사한다.
- 심의사례는 확정 사례 문서와 904개 청크의 부모·자식 관계, 원문 위치와 중복 여부를 검사한다.
- 판례는 원본 판례 987건과 8,334개 청크의 부모·자식 관계, 사건번호·원문 위치와 중복 여부를 검사한다.

### 10.2 코퍼스별 독립 파이프라인과 공통 실행기

세 코퍼스는 하나의 데이터셋이나 하나의 DB 테이블로 합치지 않는다. 코퍼스별 입력 생성·검증·적재 파이프라인을 독립적으로 유지하고, 모델 로딩·배치 처리·벡터 검증·manifest 생성 기능만 공통 임베딩 모듈에서 재사용한다.

```text
인정기준 파이프라인
PDF 원본 → 구조화·전처리 → Rule 검색문서 생성 → 입력 검증
  → Qwen 4B 임베딩 → 인정기준 staging 적재 → 인정기준 운영 DB 승격

심의사례 파이프라인
원본 → 전처리 → 청킹 → 입력 검증
  → Qwen 4B 임베딩 → 심의사례 staging 적재 → 심의사례 운영 DB 승격

판례 파이프라인
크롤링 원본 → 전처리 → 청킹 → 입력 검증
  → Qwen 4B 임베딩 → 판례 staging 적재 → 판례 운영 DB 승격
```

한 코퍼스의 실패가 다른 코퍼스 결과를 오염시키지 않도록 결과 디렉터리, manifest, 검사 보고서와 DB 트랜잭션을 코퍼스별로 분리한다. 다만 사용자는 하나의 명령으로 세 파이프라인을 순차 실행하고 하나의 최종 압축 파일을 받을 수 있어야 한다.

### 10.3 공식 입력 스냅샷 동결

RunPod는 로컬 운영 PostgreSQL에 직접 접속하지 않는다. 단계 5에서 검증된 DB 데이터와 확정 파일을 대조한 뒤 임베딩에 필요한 최소 입력만 내보내고, 다음 정보를 포함한 입력 manifest를 생성한다.

- 실행 그룹 ID와 코퍼스 키
- 문서 ID, 청크 ID, 상위 문서 ID
- 임베딩 입력 텍스트와 입력 텍스트 SHA-256
- 원문 SHA-256과 원문 위치
- 코퍼스별 예상 건수
- 모델명, 고정 리비전, 차원, 정규화 방식
- 입력 파일별 SHA-256과 생성 시각
- 전처리·청킹 코드 버전 또는 Git commit

정답 판례 ID, qrels, 기존 검색 순위와 과실비율은 문서 임베딩 텍스트 생성에 사용하지 않는다. 질문지와 정답지는 누출 방지를 위해 분리하며, RunPod에는 평가용 질문 텍스트만 포함할 수 있다. 정답지는 로컬 검색 평가 단계에서만 사용한다.

### 10.4 운영 문서 벡터와 평가 질문 벡터의 구분

| 구분 | 생성 위치 | 사용 목적 | 운영 문서 테이블 적재 여부 |
|---|---|---|---|
| 인정기준 277개 검색문서 벡터 | RunPod | 인정기준 pgvector 인덱스 | 적재 |
| 심의사례 904개 청크 벡터 | RunPod | 심의사례 pgvector 인덱스 | 적재 |
| 판례 8,334개 청크 벡터 | RunPod | 판례 pgvector 인덱스 | 적재 |
| 공통 승인 질문 50개 벡터 | RunPod 결과의 평가 영역 | 세 코퍼스 검색 회귀 평가 | 문서 테이블에 적재하지 않음 |
| 인정기준 Complete30 질문 30개 벡터 | RunPod 결과의 평가 영역 | 인정기준 V9 회귀 평가 | 문서 테이블에 적재하지 않음 |

공통 질문 텍스트, 질의 전처리, 모델 지시문과 입력 SHA-256이 모두 동일할 때만 질문 벡터를 한 번 생성하여 코퍼스별 평가기가 공동 참조한다. 하나라도 다르면 코퍼스별 질문 벡터를 별도 생성하고 별도 manifest에 기록한다. qrels와 지표 계산은 항상 코퍼스별로 분리한다. B-4 조건형 질의 보강은 단계 8의 판례 RAG 규칙으로 적용하며, B-4 보강 질문 벡터를 운영 문서 벡터와 혼합하지 않는다.

### 10.5 RunPod 실행 환경 원칙

Qwen 4B 전체 재색인은 RunPod의 Jupyter 환경에서 GPU 배치 작업으로 실행한다. 로컬 CPU나 기존 운영 컨테이너에서 장시간 임베딩을 임의로 시작하지 않는다.

1. RunPod 계정에 이 작업용 기존 Pod가 있는지 먼저 확인한다.
2. 기존 임베딩 Pod가 있으면 새 Pod를 만들지 않고 사용자에게 해당 Pod의 시작·재개를 요청한다.
3. OJH 등 다른 목적의 Pod만 있거나 적합한 Pod가 없으면 임베딩 전용 Pod를 새로 만든다.
4. 권장 GPU는 A40 48GB 또는 RTX A6000 48GB급이며, 실제 GPU·VRAM·시간당 비용을 실행 manifest에 기록한다.
5. 기본 문서 batch는 32로 시작하고 CUDA OOM 시 16, 8 순으로 낮춰 재개한다. 이미 검증 완료된 결과는 다시 계산하지 않는다.
6. 실행이 끝나도 결과를 확인하기 전에 Pod를 Terminate하지 않는다. 최종 tar.gz 다운로드와 로컬 SHA-256 검증 후 비용 방지를 위해 Stop하며, Terminate는 사용자 확인 뒤 수행한다.

브라우저에서 Jupyter로 ZIP을 업로드하고 터미널에서 실행하는 방식에는 `RUNPOD_API_KEY`가 필요하지 않다. 로컬 Qwen 모델은 `OPENAI_API_KEY`도 사용하지 않는다. 루트 `.env`, API 키, DB 비밀번호와 그 일부·길이를 ZIP, 로그, manifest 또는 보고서에 포함하지 않는다.

### 10.6 RunPod 업로드 ZIP 계약

사용자에게는 세 코퍼스를 모두 실행할 수 있는 ZIP 파일 하나와 복사·붙여넣기 가능한 단일 실행 명령을 제공한다.

```text
qwen4_three_corpus_operational_bundle_<버전>.zip
├─ etl/fault_cases/src/shared_embedding/        # 공통 임베딩·검증 코드
├─ runpod_input/
│  ├─ fault_standard/                           # 인정기준 확정 입력
│  ├─ review_case/                              # 심의사례 확정 입력
│  ├─ precedent/                                # 판례 확정 입력
│  ├─ evaluation_queries/                       # 정답을 제외한 승인 질문 텍스트
│  ├─ input_manifest.json
│  └─ CHECKSUMS_SHA256.txt
├─ runpod_execute_qwen4_three_corpora.sh
└─ 실행안내.md
```

ZIP은 Windows에서 생성하더라도 내부 경로 구분자를 `/`로 고정하여 Linux에서 압축 해제했을 때 실행 파일 경로가 깨지지 않아야 한다. 배포 전에 별도 임시 디렉터리에서 ZIP 압축 해제, Python import, shell 문법, 입력 해시와 예상 파일 존재 여부를 스모크 테스트한다.

의존성은 버전을 고정하고 실행 전 호환성을 검사한다. 최소한 Python, PyTorch, Transformers, Sentence Transformers, Safetensors, PyArrow 버전과 CUDA 정보를 manifest에 남긴다. 모델은 `Qwen/Qwen3-Embedding-4B` 리비전 `5cf2132abc99cad020ac570b19d031efec650f2b`만 허용하며, 다른 리비전이 내려받아지면 실행을 중단한다.

### 10.7 RunPod 단일 실행과 재개 계약

단일 실행 스크립트는 다음 순서로 작동한다.

```text
환경·GPU·디스크·의존성 사전검사
  → ZIP 입력 SHA-256 검증
  → 모델 리비전 검증 및 1회 로딩
  → 인정기준 임베딩·자체검사
  → 심의사례 임베딩·자체검사
  → 판례 임베딩·자체검사
  → 평가 질문 임베딩·자체검사
  → 세 코퍼스 전체 완료조건 검사
  → 결과 CHECKSUMS_SHA256.txt 생성
  → 최종 tar.gz 생성
```

실행기는 다음 기능을 반드시 갖는다.

- `--resume`과 고정 실행 그룹 ID 지원
- 코퍼스·모델·리비전·배치 크기 인자화
- 파일 존재만으로 완료 처리하지 않고 manifest·건수·차원·해시까지 확인한 뒤 건너뛰기
- 부분 실패 시 완료 데이터와 로그 보존
- 배치별 진행률, 처리 건수와 실패 ID 기록
- CUDA OOM 발생 시 캐시 정리 후 batch를 32 → 16 → 8로 낮춰 해당 코퍼스부터 재시도
- batch 8에서도 실패하면 조용히 다음 코퍼스로 넘어가지 않고 명시적으로 중단
- 동일 실행 ID에서 모델 리비전·입력 해시·차원·정규화 설정 변경 금지
- 세 코퍼스 중 하나라도 불완전하면 최종 완료 tar.gz를 정상 완료로 표시하지 않음

### 10.8 RunPod 반환 tar.gz 계약

```text
qwen4_three_corpus_operational_<실행ID>.tar.gz
├─ fault_standard/
│  ├─ document_embeddings.parquet
│  ├─ artifact_manifest.json
│  └─ validation_report.json
├─ review_case/
│  ├─ chunk_embeddings.parquet
│  ├─ artifact_manifest.json
│  └─ validation_report.json
├─ precedent/
│  ├─ chunk_embeddings.parquet
│  ├─ artifact_manifest.json
│  └─ validation_report.json
├─ evaluation_queries/
├─ logs/
├─ run_manifest.json
└─ CHECKSUMS_SHA256.txt
```

모델 가중치 캐시는 결과 압축에 포함하지 않는다. 반환 파일에는 각 벡터의 문서·청크 ID, 임베딩 입력 SHA-256, 차원, dtype, 모델명, 모델 리비전과 정규화 여부가 있어야 한다.

### 10.9 로컬 수신 검증: tar.gz는 즉시 적재하지 않음

사용자가 tar.gz를 전달하면 압축을 곧바로 운영 DB에 적재하지 않고 다음 순서로 검증한다.

1. 압축 파일 자체의 SHA-256 기록
2. 경로 탈출 항목과 비정상 심볼릭 링크가 없는지 안전검사 후 격리 디렉터리에 압축 해제
3. `CHECKSUMS_SHA256.txt`와 모든 결과 파일 대조
4. 입력 manifest가 로컬에서 동결한 입력 manifest와 동일한지 대조
5. 모델명·리비전·차원·정규화·의존성 기록 대조
6. 코퍼스별 예상 ID 집합과 결과 ID 집합 대조
7. 빈 벡터, NaN, Inf, 중복 ID, 누락 ID, 비정상 norm 검사
8. 평가 질문 벡터가 문서 벡터 영역에 섞이지 않았는지 검사
9. 검증 결과를 한국어 MD와 기계 판독 가능한 JSON으로 기록

검증이 하나라도 실패하면 운영 DB를 변경하지 않는다. 수정된 번들은 새 버전명과 새 SHA-256으로 다시 생성하며 실패한 압축 파일을 정상 결과로 덮어쓰지 않는다.

### 10.10 세 운영 DB 일괄 적재와 승격

사용자 관점에서는 검증된 tar.gz 하나를 한 번의 적재 명령으로 처리한다. 내부적으로는 세 코퍼스를 서로 다른 DB와 staging 테이블에 적재하고 각각 독립 트랜잭션으로 검증한다.

```text
검증된 tar.gz
  → 인정기준 DB staging 적재·검증
  → 심의사례 DB staging 적재·검증
  → 판례 DB staging 적재·검증
  → 세 staging 전체 통과 확인
  → 활성 인덱스 버전 포인터 일괄 전환
  → 실제 Top-K 검색 스모크 테스트
  → 적재 manifest·검증 보고서·롤백 버전 기록
```

| 코퍼스 | 운영 적재 대상 | 예상 운영 벡터 |
|---|---|---:|
| 인정기준 | `fault_standard_db.rag_qwen4` | 검색문서 277개 |
| 심의사례 | `review_case_db.rag_qwen4` | 청크 904개 |
| 판례 | `precedent_db.rag_qwen4` | 청크 8,334개 |

기존 시험 벡터에 append하지 않는다. 새 실행 ID와 인덱스 버전으로 staging 적재하고, 세 staging 검증이 모두 끝나기 전에는 어느 RAG도 새 버전을 기본값으로 읽지 않는다. 특정 DB 적재가 실패하면 이미 검증된 staging은 보존할 수 있지만 활성 버전 포인터는 전환하지 않는다. 이전 활성 버전은 관찰기간과 롤백 검증이 끝날 때까지 삭제하지 않는다.

### 10.11 단계 7~9로 전달하는 계약

단계 6은 다음 산출물이 모두 준비되어야 끝난다.

- 세 코퍼스 활성 인덱스 버전과 적재 manifest
- 문서·청크 ID에서 원문으로 역추적할 수 있는 연결
- 같은 Qwen 4B 모델명·리비전·차원·정규화를 강제하는 질문 임베딩 계약
- 공통 50문항과 Complete30 평가 질문 벡터 및 입력 해시
- 코퍼스별 Top-K 검색 스모크 테스트 결과
- 이전 인덱스로 되돌리는 롤백 명령과 버전 정보

RunPod 배치 작업은 운영 문서 재색인 수단이지 실시간 질문 임베딩 서비스가 아니다. 단계 7~9의 실제 RAG는 동일 모델·동일 리비전으로 질문 벡터를 생성하는 공통 인코더 인터페이스를 사용해야 하며, 운영 배포 방식이 확정되기 전에는 저장된 평가 질문 벡터로 회귀 검증만 수행한다.

### 10.12 통과 기준

- 상류 원본·전처리·청크 감사 통과 및 확정 입력 manifest 생성
- 입력 manifest와 RunPod ZIP, 반환 tar.gz, 로컬 동결 입력의 SHA-256 일치
- 모델명 `Qwen/Qwen3-Embedding-4B`와 고정 리비전 일치
- 인정기준 검색문서 277개, 심의사례 청크 904개, 판례 청크 8,334개의 결과 ID 집합 일치
- DB의 원본·청크 ID 집합과 임베딩 결과 ID 집합 일치
- 모든 벡터 2560차원, NaN·Inf 0건, L2 norm 허용 오차 통과
- 문서·청크 ID 누락·중복 0건, 임베딩 입력 텍스트 공백 0건
- 모델·입력·출력·환경 manifest가 적재 manifest와 연결됨
- 세 staging 적재와 실제 Top-K 검색 스모크 테스트 성공
- 공통 50문항과 Complete30 질문 벡터가 문서 벡터와 분리됨
- 기존 운영 테이블과 기존 법률 Neo4j 변경 0건

### 10.13 중단 및 롤백 기준

- 현재 확정 코퍼스와 입력 manifest 또는 단계 5 DB의 ID·해시 집합이 설명 없이 다름
- tokenizer 길이 초과를 기록 없이 조용히 잘라내는 문서 존재
- 모델명·리비전·차원·정규화 설정이 계획과 다름
- RunPod ZIP 또는 tar.gz에 `.env`, API 키, DB 비밀번호 등 비밀정보 포함
- tar.gz 내부 체크섬 불일치 또는 경로 안전검사 실패
- 입력 문서와 적재 벡터를 연결할 수 없는 ID 존재
- 세 코퍼스 중 하나라도 결과 또는 staging 검증 실패

RunPod 실패 시 같은 실행 ID와 동일 입력으로 `--resume`하고, 입력·모델 설정을 바꿔야 하면 새 실행 ID를 발급한다. DB 적재 실패 시 staging만 격리하고 활성 인덱스 버전은 이전 상태로 유지한다. 운영 버전 전환 후 검색 스모크 테스트가 실패하면 즉시 이전 활성 버전 포인터로 복귀한다.

---

## 11. 단계 7 — 인정기준 RAG 구축

### 11.1 운영 흐름

```text
사고 Fact·질문
  → Qwen 4B 질문 임베딩
  → pgvector 후보 검색
  → Neo4j V9 관계 대조
  → Rule·당사자 방향 확정
  → 결정론적 계산기
  → 근거·경고·계산 결과 반환
```

### 11.2 이관 대상

- `NEW_ABC_TEST_V6/src/new_abc_test_v7`의 V9 관계 대조 기능
- `calculator.py`
- Complete30 V9 실행 계약
- V9에서 실제로 읽는 Neo4j 관계 정의

전체 실험 폴더를 복사하지 않고 운영 기능만 분리한다.

### 11.3 검증 세트

- Complete30 30문항
- 공통 50문항의 인정기준 qrels v1.2
- 기존 V9 최종 비교표

### 11.4 통과 기준

- Complete30 입력·정답 해시 일치
- 검색 후보와 V9 관계 대조 과정 추적 가능
- 계산 결과 합계 100
- 당사자 방향 반전 오류 0건
- 기존 V9에서 개선된 3건 회귀 0건
- 근거 부족 시 억지 계산 대신 `UNKNOWN` 또는 보완요청 반환
- 기존 최종 기준선보다 핵심 지표 하락 시 운영 전환 중단

### 11.5 롤백

기능 플래그를 통해 기존 Complete30 실험 런타임 또는 이전 운영 검색 경로로 즉시 복귀할 수 있게 한다. 기존 DB·Neo4j 실험 컨테이너는 전환 승인 전까지 제거하지 않는다.

---

## 12. 단계 8 — 판례 RAG 구축

### 12.1 운영 흐름

```text
사고 Fact·질문
  → B-4 사고조건 판정
  → 조건형 질의 보강
  → Qwen 4B 질문 임베딩
  → pgvector Top-K 후보
  → 판례 단위 중복 제거
  → 원문 근거와 검색 점수 반환
```

### 12.2 B-4 운영 이관 원칙

운영 코드에는 다음 값을 넣지 않는다.

- Query ID
- 정답 판례 ID
- qrels
- 기존 정답 순위
- 정답 과실비율

B-4는 질문 원문과 구조화된 사고 Fact에서 확인되는 조건만 사용한다.

### 12.3 이관 대상

- `configs/keyword_rules_b4_all_top10_failures.json`
- `keyword_expansion/run_b4_all_top10_failures.py`의 조건 판정·질의 보강 로직
- B-4 전체 50문항 결과
- B-4 최종 운영 보고서와 점수표

기존 runner에 하드코딩된 실험 경로, Query ID 검증, 산출물 경로는 운영 모듈에서 제거하고 인자로 전환한다.

### 12.4 검증 세트

- 공통 50문항
- 판례 qrels v1
- B-4 최종 50문항 결과
- B-4 규칙 비적용 질문에 대한 회귀 검사

### 12.5 통과 기준

- B-4 규칙 발동 여부와 근거 조건 기록
- 규칙 비대상 질문의 질의 원문 불필요 변경 0건
- 특정 Query ID 또는 정답 ID 직접 매핑 0건
- 사례 단위 Top-1·Top-10·Top-50, MRR@10, nDCG@10 산출
- 정답 가능 질문의 Top-10 성공·실패 건수와 비율 표시
- 기존 B-4 기준선 대비 Top-10 회귀 0건
- 과도한 한 판례 쏠림 여부 검사
- 높은 코사인 점수만으로 정답 판정하지 않음

### 12.6 롤백

B-4 적용 여부를 기능 플래그로 분리한다. 문제가 생기면 Qwen 4B 벡터 단독 검색으로 즉시 전환할 수 있게 한다.

---

## 13. 단계 9 — 심의사례 RAG 구축

### 13.1 운영 흐름

```text
사고 Fact·질문
  → Qwen 4B 질문 임베딩
  → pgvector 후보 검색
  → 심의사례 단위 중복 제거
  → 결정비율·당사자 역할·원문 근거 반환
```

### 13.2 검증 세트

- 공통 50문항
- 심의사례 qrels v1
- 6모델 AB 실험의 Qwen 4B 결과

### 13.3 통과 기준

- 사례 ID와 청크 ID가 모두 추적 가능
- 관련 문서가 없는 질문을 오답으로 강제하지 않음
- relevance 임계값 정책을 평가 보고서에 명시
- 사례 단위 Top-1·Top-10, MRR@10, nDCG@10 산출
- 코사인 유사도 분포와 성공·실패 사례 함께 보고
- 기존 Qwen 4B 기준선보다 핵심 지표 하락 시 운영 전환 중단
- 결정비율과 당사자 역할이 반대인 사례를 정답으로 승격하지 않음

### 13.4 롤백

새 `rag_qwen4` 스키마 선택을 기능 플래그로 제어하고, 기존 검색 경로는 전환 승인 전까지 제거하지 않는다.

---

## 14. 단계 10 — 세 RAG 공통 평가와 운영 승인

### 14.1 공통 비교표 필수 지표

| 지표 | 설명 |
|---|---|
| Hit@1 | 1위에 정답이 있는 질문 비율 |
| Hit@10 | 10위 안에 정답이 있는 질문 비율 |
| Top-10 성공/실패 건수 | 사용자가 직관적으로 확인할 실제 문항 수 |
| MRR@10 | 첫 정답이 얼마나 위에 있는지 평가 |
| nDCG@10 | 여러 관련 문서의 등급과 순위를 함께 평가 |
| Top-50 회수율 | 후속 재순위화 가능 후보가 포함되는지 평가 |
| Top-1 코사인 | 검색 확신이 아니라 유사도 진단값 |
| 정답 코사인 | 정답 문서가 검색 결과에서 받은 유사도 |
| 지연시간 | 질문 임베딩과 검색의 실제 응답시간 |
| 오류율 | 호출·DB·파싱 실패 비율 |

### 14.2 반복 정책

모델 선정 AB 실험은 전체 3회 결과를 보존한다. 운영 파이프라인의 단계별 개선 비교는 동일 동결 입력에 대해 한 번 실행하되, 실행 재현성 검사와 비결정적 요소가 있는 구간은 별도 반복 검증한다.

### 14.3 운영 승인 기준

- 입력 질문지·정답지·코퍼스 해시 일치
- 세 RAG 모두 필수 지표 산출
- 기준선 대비 설명되지 않은 회귀 0건
- 실패 Query별 원인 보고서 생성
- 코사인 점수와 정답 여부를 혼동하지 않음
- 재실행 명령과 결과 manifest 존재
- DB dump와 복구 절차 최신화

---

## 15. 단계 11 — 에이전트 구축

### 15.1 호출 구조

```text
Supervisor `text_ml_case_search` agent_input v1
          ↓
Agent Runtime
 ├─ 인정기준 RAG service
 ├─ 판례 RAG service
 └─ 심의사례 RAG service
          ↓
`text_ml_case_search` AgentOutput v1
```

### 15.2 에이전트 책임

- 요청 검증
- `contract_version` 호환성 검증
- 필요한 RAG 선택
- 세 RAG 병렬 또는 순차 호출
- 오류 격리
- 결과 출처 유지
- 동일 요청 ID로 결과 묶기
- 근거 부족·부분 실패 표시

### 15.3 에이전트가 하면 안 되는 일

- 실험 폴더 직접 탐색
- HISTORY 문서에서 현재 운영 규칙 선택
- DB 테이블 직접 쿼리
- 검색 근거 없이 과실비율 생성
- 한 코퍼스 결과를 다른 코퍼스의 정답처럼 사용
- API 키 또는 DB 비밀번호 로그 출력

### 15.4 통합 테스트

- 세 RAG 정상 응답
- 한 RAG 실패 시 나머지 결과 유지
- timeout 처리
- 빈 검색 결과 처리
- 중복 근거 병합 규칙
- 요청·응답 JSON 스키마 검사
- 기존 `test_supervisor_contract.py`와 신규 계약 테스트 동시 통과
- 출처와 검색방법 보존
- 인정기준 계산 결과와 판례·심의사례 근거 구분

### 15.5 통과 기준

- 에이전트가 세 `service.py` 외 내부 구현을 import하지 않음
- Supervisor 입출력이 `text_ml_case_search` 계약 v1과 일치
- 계약을 변경할 때 버전·OpenAPI·JSON 예시·테스트가 함께 변경됨
- 부분 실패가 전체 실패로 번지지 않음
- 모든 결과에 코퍼스·문서 ID·근거 위치 존재
- 동일 입력 재실행 시 구조적으로 동일한 결과 계약 유지
- 에이전트 응답과 개별 RAG 결과의 누락·변조 0건

---

## 16. 단계 12 — 재실행 가능한 과거 실험 모듈화

### 16.1 분리 원칙

과거 파일을 모두 `HISTORY_LOCAL`에 넣지 않는다. 다시 비교할 가치가 있는 실험은 `legacy_runnable`로 분리한다.

```text
legacy_runnable/
├─ embedding_fixed1024_5models/
├─ fault_standard_neo4j_v8/
├─ precedent_keyword_b1_b3/
└─ precedent_reranker/
```

### 16.2 실험 모듈 구조

```text
legacy_runnable/<experiment_name>/
├─ README_실행방법.md
├─ src/
├─ configs/
├─ evaluation/
├─ manifests/
├─ requirements.lock
├─ .env.example
├─ run.ps1
├─ run.sh
└─ 실행_검증결과.json
```

### 16.3 원본 보존 방식

옛 실험 원본을 결과에 맞게 다시 고치지 않는다.

```text
불변 원본 스냅샷
  + 현재 경로에서 실행하기 위한 호환 실행기
  + 고정된 의존성·설정·입력 manifest
```

형태로 보존한다.

### 16.4 `LEGACY_RUNNABLE` 통과 기준

- 절대경로 제거 또는 실행 인자로 대체
- 운영 DB를 기본 대상으로 사용하지 않음
- 별도 출력 폴더 사용
- 입력 manifest와 해시 존재
- `.env.example` 존재
- 의존성 버전 고정
- 최소 표본 스모크 테스트 통과
- 한국어 실행 README 존재
- 실행 명령 복사·붙여넣기로 재현 가능
- 실행 결과가 기존 기준선과 허용범위 내 일치

통과하지 못한 실험은 `LEGACY_RUNNABLE`로 이관 완료 처리하지 않는다.

---

## 17. 단계 13 — HISTORY와 삭제 후보 정리

### 17.1 `HISTORY_LOCAL` 대상

- 중간 비교표와 중간 분석보고서
- 실패한 메타데이터 v1·v2 산출물
- 최종 선택에 사용하지 않은 RunPod 실행 로그
- 중복 압축 파일
- 실행 중 생성된 임시 번들
- 최종 보고서가 대체한 중간 MD

### 17.2 HISTORY 이관 기록

Git에는 다음 두 파일을 남긴다.

```text
docs/history/
├─ HISTORY_이관_목록.md
└─ HISTORY_파일_해시.json
```

필수 기록:

- 원래 경로
- HISTORY 경로
- SHA-256
- 이관 이유
- 대체된 최종 코드·문서
- 재실행 가능 여부
- 백업 위치

### 17.3 삭제 후보

- `__pycache__`
- `*.pyc`
- 확인된 중복 다운로드
- 복원 가능한 모델 캐시
- 비어 있는 임시 폴더

삭제는 별도 승인 단계로 처리한다. HISTORY 이관과 동시에 삭제하지 않는다.

---

## 18. 단계 14 — 최종 전환과 롤백

### 18.1 전환 전 필수 조건

- 외부 백업과 복원 검증 PASS
- 파일 이관 매핑표 승인
- 세 코퍼스 Qwen 4B 적재 PASS
- 인정기준 RAG 기준선 PASS
- 판례 B-4 RAG 기준선 PASS
- 심의사례 RAG 기준선 PASS
- 에이전트 통합 테스트 PASS
- 공식 문서 링크 검사 PASS
- 새 DB dump·복원 PASS

### 18.2 전환 방식

1. 기능 플래그로 새 RAG를 비운영 모드에서 실행한다.
2. 동일 입력을 기존·신규 경로에 보내 비교한다.
3. 비교 결과를 승인한다.
4. 새 경로를 기본값으로 바꾼다.
5. 관찰 기간 동안 기존 경로를 유지한다.
6. 오류·회귀가 없을 때 기존 경로를 `legacy_runnable` 또는 HISTORY로 이동한다.

### 18.3 즉시 롤백 조건

- 검색 핵심 지표 회귀
- 정답 ID 또는 문서 ID 연결 오류
- 계산 당사자 반전
- DB 적재 누락·중복
- 에이전트가 근거 없는 결론 생성
- 새 런타임 장애율이 기준 초과
- 비밀정보 로그 노출

### 18.4 롤백 방법

- 기능 플래그를 기존 RAG로 복구
- 새 스키마를 읽기 전용으로 전환
- 기존 DB·Docker 유지
- 백업 dump로 별도 복원 검증
- 실패 실행 ID와 입력 manifest를 기록하고 원인 분석 후 재개

---

## 19. 단계별 실행 승인표

| 단계 | 선행조건 | 핵심 산출물 | 다음 단계 승인조건 |
|---|---|---|---|
| 1. 외부 백업 | 없음 | 파일 백업·DB dump | 복원 검증 PASS |
| 2. 인벤토리 | 백업 PASS | 파일별 매핑표 | 미분류 중요파일 0건 |
| 3. 새 구조 | 매핑표 완료 | 공통 계약·빈 런타임 | 기존 코드 회귀 0건 |
| 4. 평가·문서 | 새 구조 생성 | 공식 평가셋·문서 지도 | 해시·링크 PASS |
| 5. DB 구조·기본 적재 | 백업·스키마 계획 | 새 `rag_qwen4` 스키마와 원본·청크 적재 | 원본·청크 건수·ID·해시 PASS |
| 6. 재색인 | 기본 적재 PASS | Qwen 4B 운영 벡터 | 벡터 건수·차원·해시 PASS |
| 7~9. 개별 RAG | 운영 벡터 | 세 RAG 서비스 | 기준선 회귀 0건 |
| 10. 공통 평가 | 세 RAG 완료 | 최종 비교표·보고서 | 운영 승인기준 통과 |
| 11. 에이전트 | 공통 계약 확정 | Agent Runtime | 통합 테스트 PASS |
| 12~13. 과거 정리 | 신규 전환 완료 | legacy·HISTORY | 재실행·해시 검사 PASS |
| 14. 최종 전환 | 전 항목 PASS | 운영 기본경로 전환 | 관찰기간 오류 없음 |

---

## 20. 최종 산출물

### 20.1 코드

- 코퍼스별 Qwen 4B 운영 재색인 파이프라인
- 인정기준 RAG 서비스
- 판례 B-4 RAG 서비스
- 심의사례 RAG 서비스
- 공통 요청·응답 계약
- 에이전트 오케스트레이터
- DB 마이그레이션·검증 도구
- 재실행 가능한 legacy 모듈

### 20.2 DB

- 세 코퍼스 `rag_qwen4` 스키마
- 판례 전용 DB
- 적재·인덱스 버전 manifest
- 백업·복원 절차

### 20.3 평가

- 공통 50문항 세 코퍼스 평가 결과
- 인정기준 Complete30 전체 평가 결과
- Top-1·Top-10 성공/실패 건수
- Hit@1, Hit@10, MRR@10, nDCG@10, Top-50 회수율
- 코사인 유사도 진단표
- 지연시간·오류율
- 실패 Query 원인 보고서

### 20.4 문서

- 아키텍처 문서
- 코퍼스별 운영명세
- Qwen 4B 재색인 절차
- Docker·DB 운영 및 복구 절차
- 최종 성능 비교표
- 최종 운영 결정 보고서
- 활성 문서 목록
- HISTORY 이관 목록

---

## 21. 전체 완료 체크리스트

### 안전

- [ ] 프로젝트 외부 백업 완료
- [ ] 중요 파일 SHA-256 일치
- [ ] PostgreSQL 복원 테스트 성공
- [ ] Neo4j 복원 테스트 성공
- [ ] `.env` 비밀 값 노출 0건

### 인벤토리

- [ ] 전체 파일 분류 완료
- [ ] import 참조 관계 확인
- [ ] 최종 질문지·정답지·manifest 누락 0건
- [ ] HISTORY와 legacy 구분 완료

### DB·재색인

- [ ] 새 스키마가 기존 테이블과 분리됨
- [x] 인정기준 검색문서 277개 기본 적재 검증
- [x] 심의사례 원본·청크 904개 기본 적재 검증
- [x] 판례 원본 987건 기본 적재 검증
- [x] 판례 청크 8,334개 기본 적재 검증
- [x] 크롤링·전처리·청크 결과 감사와 확정 입력 스냅샷 동결
- [x] RunPod ZIP의 Linux 경로·import·shell·입력 SHA-256 스모크 테스트
- [x] RunPod 단일 명령으로 세 코퍼스 임베딩 및 최종 tar.gz 생성
- [x] 반환 tar.gz 체크섬·경로 안전성·manifest·건수 검증
- [x] Qwen 4B 벡터가 기본 적재된 문서·청크 ID와 1:1 연결됨
- [x] 모든 벡터 2560차원
- [x] 모델 리비전·해시 기록
- [x] 세 DB staging 적재 후 전체 통과 시 활성 인덱스 버전 전환
- [x] 평가 질문 벡터와 운영 문서 벡터 분리
- [x] 이전 활성 인덱스 롤백 검증

### RAG

- [ ] 인정기준 V9 기준선 통과
- [ ] 판례 B-4 기준선 통과
- [ ] 심의사례 기준선 통과
- [ ] 코사인·검색 지표·성공/실패 건수 보고
- [ ] 실패 Query 분석 완료

### 에이전트

- [ ] 공통 계약 사용
- [ ] 세 RAG 서비스만 호출
- [ ] 부분 실패 격리
- [ ] 근거·출처 보존
- [ ] 통합 평가 통과

### 정리

- [ ] 재실행 대상 legacy 스모크 테스트 통과
- [ ] HISTORY 파일 해시 기록
- [ ] 공식 MD 활성 목록 확정
- [ ] 기존 실험 Docker 정리 승인
- [ ] 삭제 후보 별도 승인
- [ ] 롤백 절차 최종 검증

---

## 22. 실행 시작 원칙

이 계획 승인 후 첫 실제 작업은 폴더 이동이나 DB 적재가 아니다.

```text
프로젝트 외부 백업 생성
  → 파일·DB 복원 검증
  → 파일 전체 인벤토리와 이관 매핑표 작성
```

순서로 시작한다. 이 세 작업이 완료되기 전에는 기존 코드, 질문지, 정답지, DB, Docker와 실험 산출물의 위치를 바꾸지 않는다.
