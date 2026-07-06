# 교통사고/과실비율 판례 RAG 파이프라인 통합 최종 계획

## PostgreSQL · Elasticsearch · Chunk · Embedding · A/B Test · Smoke Test 통합본

---

## 0. 문서 목적

이 문서는 다음 자료들을 하나로 합친 **통합 최종 계획서**입니다.

```text
1. 기존 교통사고/과실비율 판례 RAG 계획 MD
2. 추가로 만든 PostgreSQL-first + Elasticsearch PoC 반영 MD
3. 4. Elasticsearch.ipynb 실습 흐름
4. docker-compose.yml Elasticsearch/Kibana 로컬 환경
5. README.md 실행/접속/검증 문서
```

핵심 목적은 다음입니다.

```text
1. 기존 계획과 새로 추가한 계획 사이의 충돌을 정리한다.
2. txt 기반 Elasticsearch 실습과 실제 판례 서비스 파이프라인을 구분한다.
3. PostgreSQL 먼저 원본 적재가 맞는지 최종 확정한다.
4. 교통사고 관련 판례와 과실비율 판례를 완전히 분리한다.
5. 코드 구현 순서와 A/B 테스트 계획을 하나의 흐름으로 통합한다.
```

---

## 0.1 사용자 피드백 반영 사항

이번 버전에서 반영한 피드백은 다음입니다.

```text
1. chunk 테이블은 완전 분리한다.
   - traffic_precedent_chunks
   - fault_ratio_precedent_chunks

2. PostgreSQL 원본 테이블도 완전 분리한다.
   - traffic_precedent_cases
   - fault_ratio_precedent_cases
   - 통합 precedent_cases 테이블은 사용하지 않는다.

3. txt 기반 Elasticsearch 테스트는 0단계로 두지 않는다.
   - 첨부 ipynb는 참고 자료로만 둔다.
   - 실제 실행은 바로 PostgreSQL-first 판례 파이프라인으로 간다.

4. 실제 데이터 기준 경로를 반영한다.
   - C:\dev\project\SKN27-FINAL-3Team\etl\fault_cases\artifacts\traffic_precedents_output

5. Elasticsearch 내부 data volume은 실제 판례 데이터 경로와 분리한다.
```

### 0.2 현재 프로젝트 구조 반영 사항

이 문서는 독립 신규 프로젝트 구조가 아니라 현재 프로젝트 구조를 기준으로 수정한다.

현재 프로젝트의 실제 기준은 다음이다.

```text
C:\dev\project\SKN27-FINAL-3Team
  docker-compose.yml
  storage/
    schemas/
      law_db_schema.sql
      precedent_db_schema.sql        # 추가 예정: 판례 DB 전용 schema
    rag/
      law_query_terms.yaml

  etl/fault_cases/
    src/traffic_precedents/
      traffic_precedents_crawling/
      traffic_precedents_preprocessing/
      traffic_precedents_1st_classification-traffic accident/
      traffic_precedents_1st_classification-verification/
      traffic_precedents_2nd_classification-fault_ratio/
      traffic_precedents_2nd_classification-verification/

    artifacts/traffic_precedents_output/
      traffic_prec_api/
      traffic_prec_preprocessed/          # 새 실행 기준
      traffic_prec_work/                  # 기존 실행 산출물, legacy
      traffic_prec_reclass/
      traffic_prec_reclass_verified/
      traffic_prec_fault_ratio/
      traffic_prec_fault_ratio_verified/
```

따라서 이후 코드 구현은 별도 `project/scripts/`, `project/sql/`, `project/config/`를 새로 가정하지 않는다.
판례 적재/청킹/검색 관련 코드는 `etl/fault_cases/src/traffic_precedents/` 아래에 모듈로 추가하고,
DB schema는 `storage/schemas/` 아래에 분리한다.

### 0.3 PostgreSQL DB 분리 결정

법령 DB와 판례 DB는 분리한다.

현재 `law_db_schema.sql`은 법령 전용이다.
판례 schema를 여기에 섞지 않는다.

판례는 다음 2개 DB로 분리한다.

```text
traffic_precedent_db
fault_ratio_precedent_db
```

향후 심의사례까지 적재할 경우 다음 DB를 추가한다.

```text
review_case_db
```

최종 목표는 DBeaver 같은 DB 클라이언트의 전체 보기에서 다음처럼 보이는 구조다.

```text
law_db
traffic_precedent_db
fault_ratio_precedent_db
review_case_db       # 후속 단계
```

schema 파일은 다음처럼 분리한다.

```text
storage/schemas/law_db_schema.sql          # 기존 법령 DB
storage/schemas/precedent_db_schema.sql    # 교통사고 판례 DB + 과실비율 판례 DB
```

`precedent_db_schema.sql`은 하나의 파일이지만 내부에서 `traffic_precedent_db`,
`fault_ratio_precedent_db`를 각각 생성하고 각 DB에 필요한 테이블을 만든다.

주의:

```text
PostgreSQL 컨테이너의 POSTGRES_DB=law_db는 기본 DB 생성용이다.
추가 DB는 init SQL 또는 별도 schema 생성 스크립트에서 CREATE DATABASE로 만든다.
```

### 0.4 현재 데이터 검증 기준 숫자

현재 판례 산출물 기준 확인된 숫자는 다음이다.

```text
raw 후보: 17,512건
전처리 품질검사 대상: 15,520건

1차 교통사고 분류:
  confirmed_traffic: 3,207건
  possible_traffic_review: 3,355건
  non_traffic: 8,958건

1차 교통사고 검증 후:
  final_confirmed_traffic: 3,562건
  final_non_traffic: 11,958건
  final_all: 15,520건

2차 과실비율 분류:
  fault_ratio_confirmed: 1,151건
  fault_ratio_possible_review: 980건
  traffic_but_no_fault_ratio: 1,431건

2차 과실비율 검증 후:
  final_fault_ratio_confirmed: 973건
  final_no_fault_ratio: 2,589건
  final_all: 3,562건
```

DB/RAG 적재 기준 파일은 다음으로 확정한다.

```text
교통사고 판례 DB 적재:
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_reclass_verified/01_confirmed_traffic_cases.jsonl

과실비율 판례 DB 적재:
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_fault_ratio_verified/01_fault_ratio_confirmed_cases.jsonl
```

전처리/분류의 세부 판단 기준은 `etl/fault_cases/src/traffic_precedents/` 하위 각 단계별 MD 문서를 참고한다.


---

## 1. 최종 결론

### 1.1 최종 파이프라인

최종 운영/서비스 기준 흐름은 다음입니다.

```text
1. 2차 과실비율 분류 완료
   - confirmed_traffic → fault_ratio_confirmed 분리

2. PostgreSQL schema 생성
   - traffic 계열 테이블
   - fault_ratio 계열 테이블

3. PostgreSQL에 원본 JSONL 적재
   - PostgreSQL = source of truth

4. PostgreSQL 원본 기준 chunk 생성
   - traffic_precedent_chunks
   - fault_ratio_precedent_chunks

5. PostgreSQL chunk embedding 생성 및 저장
   - text-embedding-3-small
   - gemini-embedding-2
   - optional: E5, qwen3, voyage-law-2
   - PostgreSQL pgvector embedding 테이블에 저장

6. pgvector vector 검색 baseline 생성
   - PostgreSQL에 저장된 embedding으로 similarity 검색

7. Elasticsearch BM25 index 생성
   - PostgreSQL chunk_text/search_text를 색인
   - embedding 없이 키워드/형태소 검색 실험

8. Elasticsearch vector/hybrid index 생성
   - PostgreSQL embedding을 dense_vector로 색인
   - embedding 모델별 index 분리

9. 오프라인 A/B 테스트
   - pgvector
   - Elasticsearch BM25
   - Elasticsearch vector
   - Elasticsearch hybrid
   - embedding 모델
   - analyzer
   - chunk 방식

10. 최종 설정 선택
   - current alias로 승격

11. 검색 API / RAG API 연결

12. 나중에 실제 사용자 로그가 쌓이면 온라인 A/B 테스트
```

---

### 1.2 가장 중요한 최종 결정

```text
PostgreSQL에 먼저 원본 JSONL을 적재한다.
PostgreSQL에서 chunk를 만들고 embedding을 저장한다.
pgvector는 1차 vector 검색 baseline이다.
Elasticsearch는 원본 저장소가 아니라 BM25/vector/hybrid 비교용 검색 index로 사용한다.
```

즉:

```text
원본 JSONL
↓
PostgreSQL 원본 저장
↓
PostgreSQL 기준 chunk 생성
↓
PostgreSQL embedding 저장
↓
검색 방식 분기
  1. PostgreSQL pgvector
  2. Elasticsearch BM25
  3. Elasticsearch vector/hybrid
↓
검색/RAG
```

---

### 1.3 txt 기반 Elasticsearch 실습의 최종 처리

첨부된 `4. Elasticsearch.ipynb`는 txt 파일을 바로 Elasticsearch에 넣어 검색을 확인하는 실습 흐름입니다.

하지만 이번 최종 계획에서는 이 txt 기반 테스트를 별도 0단계로 두지 않습니다.

최종 판단:

```text
txt 기반 Elasticsearch 테스트는 이번 실행 계획에서 제외한다.
바로 PostgreSQL-first 판례 파이프라인으로 진행한다.
```

이유:

```text
1. 이미 처리 대상은 txt가 아니라 JSONL 판례 데이터이다.
2. 실제 데이터 위치와 적재 구조가 정해져 있다.
3. txt 테스트를 추가하면 오히려 실행 흐름이 길어지고 혼동될 수 있다.
4. Elasticsearch 연결 확인은 별도 txt 색인 없이 health check와 실제 판례 index 생성으로 확인할 수 있다.
```

---

## 2. 기존 MD와 새 계획 사이의 충돌 분석

### 2.1 충돌 요약표

| 항목 | 기존 MD 내용 | 새 계획/첨부 실습 내용 | 충돌 여부 | 최종 정리 |
|---|---|---|---|---|
| PostgreSQL 사용 여부 | PostgreSQL에 원본 저장 | ipynb는 PostgreSQL 없이 txt → ES | 충돌 있음 | txt 방식 비채택, 본 파이프라인은 PostgreSQL-first |
| chunk 테이블 | 기존 MD 일부에서 `precedent_chunks` 공통 테이블 | 최종 요구는 `traffic_precedent_chunks`, `fault_ratio_precedent_chunks` 완전 분리 | 충돌 있음 | 완전 분리 확정, 공통 chunk 테이블 없음 |
| 원본 테이블 | 일부에서 하나의 `precedent_cases` 통합안이 언급됨 | 최종 요구는 traffic/fault_ratio 완전 분리 | 충돌 있음 | 통합 테이블 안 삭제, 원본 테이블도 완전 분리 확정 |
| Elasticsearch index | traffic/fault_ratio index 분리 | ipynb는 `rag_keywords` 단일 index | 충돌 있음 | `rag_keywords` 비채택, 운영은 traffic/fault_ratio 분리 index |
| chunk 크기 | 판례용 1500/250 | ipynb는 200/50 | 충돌 있음 | txt 설정 비채택, 판례는 1500/250 유지 |
| embedding 모델 | OpenAI/Gemini 중심 | ipynb는 Ollama qwen3-embedding | 충돌 가능 | qwen3는 최종 운영 A/B 기본 후보에서 제외, 필요 시 별도 참고 |
| LLM 적용 | RAG 답변은 후속 단계 | ipynb는 gemma3 LLM까지 연결 | 충돌 가능 | retrieval A/B 먼저, LLM 답변 평가는 후속 단계 |
| docker volume | 실제 데이터 위치는 `C:\dev\project\SKN27-FINAL-3Team\etl\fault_cases\artifacts\traffic_precedents_output` | docker-compose가 ES data를 `./database`에 저장 | 충돌 있음 | ES data는 실제 판례 데이터 경로와 분리 |
| Nori analyzer | 적용 후보/권장 | ipynb는 standard analyzer | 충돌 아님 | Nori는 판례 검색 A/B 대상 |
| PostgreSQL 생략 | 기존 MD에서 실험용 선택지로 존재 | 최종 요구는 운영/서비스 구조 | 충돌 있음 | PostgreSQL 생략 안 함, 비채택 |

---

### 2.2 최종 확정 기준

다음 기준으로 문서를 통합합니다.

```text
1. txt 기반 직접 Elasticsearch 적재는 이번 최종 실행 계획에서 제외한다.
2. 본 판례 파이프라인은 PostgreSQL-first로 간다.
3. 교통사고 데이터셋과 과실비율 데이터셋은 완전히 분리한다.
4. 공통 precedent_cases 테이블과 공통 precedent_chunks 테이블은 사용하지 않는다.
5. Docker의 Elasticsearch data 폴더는 실제 판례 데이터 폴더와 분리한다.
6. 실제 판례 데이터 기준 경로는 `C:\dev\project\SKN27-FINAL-3Team\etl\fault_cases\artifacts\traffic_precedents_output`를 기준으로 본다.
7. A/B 테스트는 retrieval 단계부터 먼저 한다.
8. LLM 답변 생성 평가는 retrieval 검증 후 별도 단계로 진행한다.
```

---

## 3. 데이터셋 완전 분리 원칙

### 3.1 왜 완전 분리하는가

교통사고 관련 판례와 과실비율 판례는 목적이 다릅니다.

| 구분 | 교통사고 관련 판례 | 과실비율 판례 |
|---|---|---|
| 목적 | 교통사고 도메인 전체 판례 검색 | 과실비율 RAG 검색 |
| 범위 | 형사, 행정, 면허, 보험, 손해배상, 구상금, 과실비율 | 과실상계, 책임비율, 손해배상, 구상금 중심 |
| 노이즈 허용 | 상대적으로 넓게 허용 | 매우 낮아야 함 |
| 검색 방식 | BM25/Nori 중심부터 시작 | BM25 + vector hybrid 중심으로 발전 |
| 사용자 질문 | 교통사고처리특례법, 면허취소, 음주운전 등 | 좌회전/직진, 무단횡단, 후미추돌 과실 등 |

과실비율 RAG에 형사/면허/행정 판례가 섞이면 결과가 흐려집니다.  
따라서 다음을 모두 분리합니다.

```text
파일/폴더
PostgreSQL 원본 테이블
PostgreSQL chunk 테이블
embedding job
Elasticsearch index
A/B 테스트 로그
```

---

### 3.2 실제 판례 데이터 기준 경로

현재 실제 산출물 기준 경로는 다음으로 둡니다.

```text
C:\dev\project\SKN27-FINAL-3Team\etl\fault_cases\artifacts\traffic_precedents_output
```

이 경로 아래에 교통사고 관련 산출물과 과실비율 산출물을 분리해 둡니다.

예상 구조:

```text
C:\dev\project\SKN27-FINAL-3Team\etl\fault_cases\artifacts\traffic_precedents_output\traffic_prec_reclass_verified
C:\dev\project\SKN27-FINAL-3Team\etl\fault_cases\artifacts\traffic_precedents_output\traffic_prec_fault_ratio_verified
C:\dev\project\SKN27-FINAL-3Team\etl\fault_cases\artifacts\traffic_precedents_output\postgres_exports
C:\dev\project\SKN27-FINAL-3Team\etl\fault_cases\artifacts\traffic_precedents_output\elasticsearch_exports
C:\dev\project\SKN27-FINAL-3Team\etl\fault_cases\artifacts\traffic_precedents_output\eval_results
```

---

### 3.3 최종 폴더 구조

아래 구조는 위 실제 경로 아래에 생성되는 상대 구조입니다.

```text
traffic_precedents_output/
  traffic_prec_api/
    list_results.jsonl
    all_prec_candidates_raw.jsonl
    run_summary.json

  traffic_prec_preprocessed/
    00_preprocess_report.json
    01_invalid_detail_cases.jsonl
    02_all_cases_cleaned.jsonl
    03_duplicate_candidate_groups.jsonl
    04_duplicate_removed_cases.jsonl
    05_all_cases_deduped.jsonl
    06_all_cases_quality_checked.jsonl

  traffic_prec_work/
    # 기존 실행 산출물 폴더다.
    # 새 실행 기준은 traffic_prec_preprocessed를 사용한다.

  traffic_prec_reclass/
    00_traffic_reclass_report.json
    01_confirmed_traffic_cases.jsonl
    02_possible_traffic_review.jsonl
    03_non_traffic_cases.jsonl
    04_traffic_reclassified_all.jsonl

  traffic_prec_reclass_verified/
    00_traffic_reclass_verification_report.json
    01_confirmed_traffic_cases.jsonl
    02_non_traffic_cases.jsonl
    03_traffic_reclassified_verified_all.jsonl
    04_demoted_from_confirmed_to_non_traffic.jsonl
    05_promoted_from_possible_to_confirmed.jsonl
    06_possible_to_non_traffic.jsonl

  traffic_prec_fault_ratio/
    00_fault_ratio_classification_report.json
    01_fault_ratio_confirmed_cases.jsonl
    02_fault_ratio_possible_review.jsonl
    03_traffic_but_no_fault_ratio_cases.jsonl
    04_fault_ratio_classified_all.jsonl

  traffic_prec_fault_ratio_verified/
    00_fault_ratio_verification_report.json
    01_fault_ratio_confirmed_cases.jsonl
    02_traffic_but_no_fault_ratio_cases.jsonl
    03_fault_ratio_verified_all.jsonl
    04_demoted_from_fault_confirmed_to_no_fault_ratio.jsonl
    05_promoted_from_possible_to_fault_confirmed.jsonl
    06_possible_to_no_fault_ratio.jsonl

  postgres_exports/
    traffic/
      traffic_cases_load_report.json
      traffic_chunks_load_report.json

    fault_ratio/
      fault_ratio_cases_load_report.json
      fault_ratio_chunks_load_report.json

  elasticsearch_exports/
    traffic/
      traffic_cases_bulk.ndjson
      traffic_chunks_bulk.ndjson
      traffic_index_report.json

    fault_ratio/
      fault_ratio_cases_bulk.ndjson
      fault_ratio_chunks_bulk.ndjson
      fault_ratio_index_report.json

  eval_results/
    traffic/
      bm25_eval_report.json
      nori_eval_report.json

    fault_ratio/
      bm25_eval_report.json
      nori_eval_report.json
      embedding_ab_test_report.json
      hybrid_eval_report.json
```

Elasticsearch 내부 data volume은 이 `database/` 폴더와 섞지 않습니다.

권장:

```text
infra/elasticsearch/es_data/
```

또는:

```text
es_data/
```

---

## 4. PostgreSQL-first 구조 확정

### 4.1 PostgreSQL에 먼저 원본 적재해도 괜찮은가

결론:

```text
괜찮다.
오히려 서비스/운영 관점에서는 반드시 그쪽이 더 안전하다.
```

이유:

| 이유 | 설명 |
|---|---|
| 원본 보존 | Elasticsearch index는 언제든 삭제/재생성할 수 있는 검색용 복사본 |
| 재실행 가능 | chunk, embedding, index 실패 시 PostgreSQL에서 다시 시작 가능 |
| 중복 방지 | case_id 기준 unique/upsert 가능 |
| 검수 상태 관리 | 1차/2차 분류, 검증 결과, quality flags 저장 가능 |
| A/B 테스트 추적 | 같은 원본에서 여러 chunk/index/embedding 버전 비교 가능 |
| 상세 조회 연결 | 검색 결과 case_id로 원문/메타데이터 조회 가능 |
| 로그 관리 | 검색 로그, 평가 결과, 색인 이력 저장 가능 |

---

### 4.2 최종 PostgreSQL DB와 테이블

```text
traffic_precedent_db
  public.traffic_precedent_cases
  public.traffic_precedent_chunks
  public.traffic_embedding_jobs
  public.traffic_elasticsearch_index_jobs
  public.traffic_search_eval_queries
  public.traffic_search_eval_results

fault_ratio_precedent_db
  public.fault_ratio_precedent_cases
  public.fault_ratio_precedent_chunks
  public.fault_ratio_embedding_jobs
  public.fault_ratio_elasticsearch_index_jobs
  public.fault_ratio_search_eval_queries
  public.fault_ratio_search_eval_results
```

`law_db`에는 판례 테이블을 만들지 않는다.

```text
law_db
  법령 전용
  storage/schemas/law_db_schema.sql

traffic_precedent_db
  교통사고 판례 전용
  storage/schemas/precedent_db_schema.sql

fault_ratio_precedent_db
  과실비율 판례 전용
  storage/schemas/precedent_db_schema.sql
```

테이블 이름은 다음을 사용한다.

```text
traffic_precedent_cases
traffic_precedent_chunks
traffic_embedding_jobs
traffic_elasticsearch_index_jobs
traffic_search_eval_queries
traffic_search_eval_results

fault_ratio_precedent_cases
fault_ratio_precedent_chunks
fault_ratio_embedding_jobs
fault_ratio_elasticsearch_index_jobs
fault_ratio_search_eval_queries
fault_ratio_search_eval_results
```

---

### 4.3 비채택 구조

다음 구조는 이번 최종안에서 사용하지 않습니다.

```text
precedent_cases 하나에 dataset_type으로 통합
precedent_chunks 하나에 dataset_type으로 통합
Elasticsearch 통합 index 하나에 dataset_type 필터
PostgreSQL 생략 후 Elasticsearch만 원본처럼 사용
txt 파일을 바로 Elasticsearch에 넣는 별도 smoke test
```

---

## 5. PostgreSQL schema 초안

schema 파일 위치는 다음으로 확정한다.

```text
storage/schemas/precedent_db_schema.sql
```

이 파일은 법령용 `law_db_schema.sql`과 분리한다.

초기 구현에서는 하나의 SQL 파일에서 다음 2개 DB를 만든다.

```sql
CREATE DATABASE traffic_precedent_db;
CREATE DATABASE fault_ratio_precedent_db;
```

그 다음 각 DB에 접속해 아래 테이블을 각각 생성한다.
Docker init SQL에서 `\connect` 사용이 부담스럽다면,
동일 SQL을 2개 DB에 순서대로 적용하는 별도 Python/psql 스크립트로 분리해도 된다.

### 5.1 traffic_precedent_cases

```sql
CREATE TABLE traffic_precedent_cases (
    case_id TEXT PRIMARY KEY,
    raw_case_id TEXT,
    case_name TEXT,
    case_number TEXT,
    court_name TEXT,
    decision_date DATE,
    case_category TEXT,
    judgment_type TEXT,
    holding TEXT,
    summary TEXT,
    main_text TEXT,
    full_text TEXT,
    referenced_laws TEXT,
    referenced_cases TEXT,
    source_reference TEXT,
    source_provider TEXT,
    source_type TEXT,
    matched_keywords JSONB,
    quality_flags JSONB,
    traffic_label TEXT,
    traffic_verification_final_label TEXT,
    traffic_relevance_score INTEGER,
    traffic_reclass_reasons JSONB,
    traffic_evidence_terms JSONB,
    traffic_signal_groups JSONB,
    traffic_term_count INTEGER,
    has_core_accident_context BOOLEAN,
    has_traffic_legal_plus_accident_context BOOLEAN,
    raw_json JSONB,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);
```

---

### 5.2 traffic_precedent_chunks

```sql
CREATE TABLE traffic_precedent_chunks (
    chunk_id TEXT PRIMARY KEY,
    case_id TEXT REFERENCES traffic_precedent_cases(case_id),
    chunk_index INTEGER,
    chunk_type TEXT,
    chunk_text TEXT,
    search_text TEXT,
    char_count INTEGER,
    token_count INTEGER,
    embedding_status TEXT DEFAULT 'not_required',
    embedding_model TEXT,
    elasticsearch_index_name TEXT,
    indexed_to_elasticsearch BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);
```

### 5.2.1 chunk_text와 search_text를 분리하는 이유

chunk 테이블에는 `chunk_text`와 `search_text`를 둘 다 둔다.
두 컬럼은 중복처럼 보일 수 있지만 목적이 다르다.

```text
chunk_text:
  - RAG context에 실제로 넣을 원문/요약 기반 청크
  - 사용자에게 근거로 보여줄 수 있는 텍스트
  - 판례 본문, 판시사항, 요약, 참조법령 등 원래 의미를 최대한 보존
  - embedding 생성의 기본 입력 후보

search_text:
  - 검색 성능을 높이기 위한 확장 텍스트
  - chunk_text에 사건명, 법원명, 사건번호, chunk_type, 분류 키워드, 과실비율 근거어 등을 붙인 텍스트
  - PostgreSQL text search 또는 Elasticsearch BM25/Nori 검색에 활용
  - 원문 근거를 오염시키지 않고 검색용 키워드를 보강하기 위한 컬럼
```

즉 두 컬럼의 역할은 다음처럼 나눈다.

```text
LLM 답변 근거:
  chunk_text 사용

embedding 생성:
  기본은 chunk_text 사용
  단, 실험에 따라 search_text embedding도 별도 version으로 비교 가능

BM25 / Nori / keyword 검색:
  search_text 사용 가능

Elasticsearch vector/hybrid 색인:
  chunk_text와 metadata를 기본 색인
  BM25 field에는 search_text를 함께 색인 가능
```

`chunk_text`만 둘 수도 있지만, 그러면 검색 튜닝을 위해 메타데이터나 동의어성 키워드를 붙일 때
RAG 근거 텍스트 자체가 오염된다.

예를 들어 판례 본문에는 `진로를 변경하였다`라고 되어 있고 사용자는 `차로변경 과실비율`로 검색할 수 있다.
이때 `search_text`에 `차로변경`, `진로변경`, `과실비율`, `손해배상`, `구상금` 같은 검색 보조어를 넣으면
BM25/Nori 검색 회수율을 높일 수 있다.
하지만 이런 보조어를 `chunk_text`에 직접 붙이면 LLM이 원문에 없는 표현까지 근거처럼 사용할 위험이 있다.

따라서 최종 기준은 다음과 같다.

```text
chunk_text = 보존용/RAG용/embedding 기본 입력
search_text = 검색 튜닝용/BM25용/메타데이터 확장 입력
```

이 분리는 특히 A/B 테스트에서 중요하다.

```text
A안: chunk_text만 BM25 색인
B안: search_text를 BM25 색인
C안: chunk_text embedding + search_text BM25 hybrid
D안: search_text embedding 별도 생성 후 비교
```

같은 chunk_id를 유지한 상태에서 어떤 텍스트 필드를 검색에 쓰는지만 바꿔 비교할 수 있으므로,
검색 품질 차이가 chunk 생성 때문인지 검색 필드 구성 때문인지 분리해서 판단할 수 있다.

---

### 5.3 fault_ratio_precedent_cases

```sql
CREATE TABLE fault_ratio_precedent_cases (
    case_id TEXT PRIMARY KEY,
    traffic_case_id TEXT,
    raw_case_id TEXT,
    case_name TEXT,
    case_number TEXT,
    court_name TEXT,
    decision_date DATE,
    case_category TEXT,
    judgment_type TEXT,
    holding TEXT,
    summary TEXT,
    main_text TEXT,
    full_text TEXT,
    referenced_laws TEXT,
    referenced_cases TEXT,
    source_reference TEXT,
    source_provider TEXT,
    source_type TEXT,
    matched_keywords JSONB,
    quality_flags JSONB,
    traffic_label TEXT,
    traffic_verification_final_label TEXT,
    fault_ratio_label TEXT,
    fault_ratio_verification_final_label TEXT,
    fault_ratio_score INTEGER,
    fault_ratio_reclass_reasons JSONB,
    fault_ratio_evidence_terms JSONB,
    fault_ratio_signal_groups JSONB,
    fault_ratio_explicit_terms JSONB,
    fault_ratio_party_fault_terms JSONB,
    fault_ratio_damage_terms JSONB,
    fault_ratio_duty_terms JSONB,
    fault_ratio_number_examples JSONB,
    has_core_fault_ratio_context BOOLEAN,
    has_damage_or_insurance_context BOOLEAN,
    no_fault_context_without_core BOOLEAN,
    raw_json JSONB,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);
```

### 5.5 JSONL 필드와 DB 컬럼 매핑 원칙

실제 JSONL에는 분류/검증 근거 필드가 많다.
모든 필드를 무조건 개별 컬럼으로 펼치지 않고 다음 기준을 적용한다.

```text
1. 검색 필터, 정렬, 조인, 검증에 자주 쓰는 값은 정규 컬럼으로 둔다.
2. 배열/근거/예시/분류 사유는 JSONB로 둔다.
3. 원본 row 전체는 raw_json JSONB에 보존한다.
4. chunk 생성에 쓰는 본문 필드는 TEXT 컬럼으로 둔다.
5. 나중에 재분류하거나 검수할 때 필요한 label/score/final_label은 정규 컬럼으로 둔다.
```

공통 정규 컬럼 후보:

| JSONL 필드 | DB 컬럼 | 비고 |
|---|---|---|
| `case_id` | `case_id` | PK |
| `raw_case_id` | `raw_case_id` | 원천 판례 ID |
| `case_name` | `case_name` | 사건명 |
| `case_number` | `case_number` | 사건번호 |
| `decision_date` | `decision_date` | DATE 변환 |
| `court_name` | `court_name` | 법원명 |
| `case_category` | `case_category` | 민사/형사/행정 등 필터 |
| `judgment_type` | `judgment_type` | 판결/결정 등 |
| `holding` | `holding` | 판시사항/요지 |
| `summary` | `summary` | 요약 |
| `main_text` | `main_text` | 본문 |
| `full_text` | `full_text` | 검색/감사용 전체 텍스트 |
| `referenced_laws` | `referenced_laws` | 참조 법령 |
| `referenced_cases` | `referenced_cases` | 참조 판례 |
| `matched_keywords` | `matched_keywords` JSONB | 수집 키워드 |
| `quality_flags` | `quality_flags` JSONB | 전처리 품질 플래그 |
| 전체 row | `raw_json` JSONB | 재처리/감사용 원본 |

교통사고 DB 전용 컬럼 후보:

| JSONL 필드 | DB 컬럼 |
|---|---|
| `traffic_label` | `traffic_label` |
| `traffic_verification_final_label` | `traffic_verification_final_label` |
| `traffic_relevance_score` | `traffic_relevance_score` |
| `traffic_reclass_reasons` | `traffic_reclass_reasons` JSONB |
| `traffic_evidence_terms` | `traffic_evidence_terms` JSONB |
| `traffic_signal_groups` | `traffic_signal_groups` JSONB |
| `traffic_term_count` | `traffic_term_count` |
| `has_core_accident_context` | `has_core_accident_context` |
| `has_traffic_legal_plus_accident_context` | `has_traffic_legal_plus_accident_context` |

과실비율 DB 전용 컬럼 후보:

| JSONL 필드 | DB 컬럼 |
|---|---|
| `traffic_label` | `traffic_label` |
| `traffic_verification_final_label` | `traffic_verification_final_label` |
| `fault_ratio_label` | `fault_ratio_label` |
| `fault_ratio_verification_final_label` | `fault_ratio_verification_final_label` |
| `fault_ratio_score` | `fault_ratio_score` |
| `fault_ratio_reclass_reasons` | `fault_ratio_reclass_reasons` JSONB |
| `fault_ratio_evidence_terms` | `fault_ratio_evidence_terms` JSONB |
| `fault_ratio_signal_groups` | `fault_ratio_signal_groups` JSONB |
| `fault_ratio_explicit_terms` | `fault_ratio_explicit_terms` JSONB |
| `fault_ratio_party_fault_terms` | `fault_ratio_party_fault_terms` JSONB |
| `fault_ratio_damage_terms` | `fault_ratio_damage_terms` JSONB |
| `fault_ratio_duty_terms` | `fault_ratio_duty_terms` JSONB |
| `fault_ratio_number_examples` | `fault_ratio_number_examples` JSONB |
| `has_core_fault_ratio_context` | `has_core_fault_ratio_context` |
| `has_damage_or_insurance_context` | `has_damage_or_insurance_context` |
| `no_fault_context_without_core` | `no_fault_context_without_core` |

---

### 5.4 fault_ratio_precedent_chunks

```sql
CREATE TABLE fault_ratio_precedent_chunks (
    chunk_id TEXT PRIMARY KEY,
    case_id TEXT REFERENCES fault_ratio_precedent_cases(case_id),
    chunk_index INTEGER,
    chunk_type TEXT,
    chunk_text TEXT,
    search_text TEXT,
    char_count INTEGER,
    token_count INTEGER,
    contains_fault_ratio_terms BOOLEAN DEFAULT false,
    contains_damage_terms BOOLEAN DEFAULT false,
    contains_duty_terms BOOLEAN DEFAULT false,
    embedding_status TEXT DEFAULT 'pending',
    embedding_model TEXT,
    embedding_dim INTEGER,
    embedding_version TEXT,
    elasticsearch_index_name TEXT,
    indexed_to_elasticsearch BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);
```

---

### 5.7 chunk embedding 저장 테이블

pgvector와 Elasticsearch vector/hybrid A/B 테스트를 공정하게 비교하려면
같은 chunk에서 생성한 같은 embedding을 기준으로 사용해야 한다.

따라서 embedding은 Elasticsearch에만 넣지 않고 PostgreSQL에도 저장한다.

```text
PostgreSQL 저장 목적:
1. 같은 embedding으로 pgvector와 Elasticsearch를 비교한다.
2. Elasticsearch index를 재생성해도 embedding API를 다시 호출하지 않는다.
3. embedding 모델, 차원, 버전, 생성 상태를 DB에서 추적한다.
4. 원본 판례, chunk, embedding의 계보를 PostgreSQL에서 보존한다.
5. A/B 테스트 결과가 검색엔진 차이인지 embedding 재생성 차이인지 분리한다.
```

교통사고 판례용:

```sql
CREATE TABLE traffic_precedent_chunk_embeddings (
    chunk_id TEXT REFERENCES traffic_precedent_chunks(chunk_id) ON DELETE CASCADE,
    embedding_model TEXT NOT NULL,
    embedding_dim INTEGER NOT NULL,
    embedding_version TEXT NOT NULL,
    embedding_vector VECTOR,
    embedding_provider TEXT,
    embedding_created_at TIMESTAMP DEFAULT now(),
    embedding_meta JSONB,
    PRIMARY KEY (chunk_id, embedding_model, embedding_version)
);
```

과실비율 판례용:

```sql
CREATE TABLE fault_ratio_precedent_chunk_embeddings (
    chunk_id TEXT REFERENCES fault_ratio_precedent_chunks(chunk_id) ON DELETE CASCADE,
    embedding_model TEXT NOT NULL,
    embedding_dim INTEGER NOT NULL,
    embedding_version TEXT NOT NULL,
    embedding_vector VECTOR,
    embedding_provider TEXT,
    embedding_created_at TIMESTAMP DEFAULT now(),
    embedding_meta JSONB,
    PRIMARY KEY (chunk_id, embedding_model, embedding_version)
);
```

주의:

```text
pgvector의 VECTOR 차원은 모델별로 달라질 수 있다.
OpenAI text-embedding-3-small은 1536차원 계열이고,
실습에서 사용한 qwen3-embedding:0.6b는 1024차원 예시였다.

여러 차원의 embedding을 같은 컬럼에 섞기 어렵다면
모델별 embedding 테이블을 분리하거나,
초기 A/B 후보를 하나의 차원으로 제한한 뒤 확장한다.
```

초기 구현 권장:

```text
1차:
  fault_ratio_precedent_chunk_embeddings_openai_small
  또는 embedding_model/version을 고정한 단일 테이블

2차:
  모델별 테이블 또는 차원별 테이블로 확장
```

---

## 6. Elasticsearch 로컬 환경 계획

### 6.1 현재 docker-compose 상태

현재 프로젝트의 `docker-compose.yml`에는 이미 PostgreSQL이 있다.

```text
postgres:
  image: pgvector/pgvector:pg16
  container_name: skn27-postgres
  POSTGRES_DB: law_db
  init schema: ./storage/schemas/law_db_schema.sql
```

따라서 PostgreSQL은 새로 추가하는 것이 아니라,
기존 pgvector PostgreSQL 컨테이너 안에 추가 DB를 만드는 방향으로 간다.

추가 대상:

```text
traffic_precedent_db
fault_ratio_precedent_db
review_case_db    # 후속 단계
```

현재 `docker-compose.yml`에는 Elasticsearch/Kibana 서비스가 없다.
따라서 Elasticsearch를 사용할 경우 별도 서비스 추가가 필요하다.

추가로 현재 `docker-compose.yml`에는 `redis` 서비스가 중복 선언되어 있으므로,
인프라 정리 시 중복 정의를 제거하는 것이 좋다.

---

### 6.2 반드시 수정할 부분

Elasticsearch를 추가할 경우 data volume을 실제 판례 산출물 폴더와 섞지 않는다.

실제 판례 데이터는 다음 경로를 기준으로 관리합니다.

```text
C:\dev\project\SKN27-FINAL-3Team\etl\fault_cases\artifacts\traffic_precedents_output
```

Elasticsearch 내부 데이터는 이 경로와 절대 섞지 않습니다.

최종 권장 수정:

```yaml
volumes:
  - ./es_data:/usr/share/elasticsearch/data
```

또는 docker-compose 위치를 기준으로 다음처럼 분리합니다.

```yaml
volumes:
  - ./infra/elasticsearch/es_data:/usr/share/elasticsearch/data
```

이유:

```text
traffic_precedents_output 폴더는 판례 JSONL, PostgreSQL export, Elasticsearch bulk export, eval 결과를 저장하는 산출물 폴더이다.
Elasticsearch 내부 데이터 파일은 검색엔진 내부 저장소이므로 별도 폴더에 둬야 한다.
```

---

### 6.3 추가 권장: 판례 DB 생성 방식

PostgreSQL service는 이미 있으므로 새 service를 만들지 않는다.
대신 `storage/schemas/precedent_db_schema.sql` 또는 별도 초기화 스크립트에서 다음 DB를 만든다.

```sql
CREATE DATABASE traffic_precedent_db;
CREATE DATABASE fault_ratio_precedent_db;
```

Docker init 단계에서 여러 DB를 자동 생성하려면 다음 방식 중 하나를 선택한다.

```text
1. /docker-entrypoint-initdb.d/에 shell script를 추가해 psql로 DB별 schema 적용
2. Python CLI에서 postgres 기본 DB에 접속해 CREATE DATABASE 후 schema 적용
3. 개발 단계에서는 DBeaver/psql로 DB를 만든 뒤 schema 파일을 수동 적용
```

최종 자동화 기준은 1번 또는 2번을 사용한다.

Elasticsearch/Kibana를 추가할 경우 예시는 다음이다.

```yaml
services:
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.12.1
    container_name: elasticsearch
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=true
      - xpack.security.http.ssl.enabled=false
      - xpack.security.transport.ssl.enabled=false
      - ELASTIC_PASSWORD=changeme123!
      - ES_JAVA_OPTS=-Xms1g -Xmx1g
    ports:
      - "9200:9200"
    volumes:
      - ./es_data:/usr/share/elasticsearch/data

  kibana:
    image: docker.elastic.co/kibana/kibana:8.12.1
    container_name: kibana
    ports:
      - "5601:5601"
```

검색 역할은 다음처럼 단계적으로 나눈다.

```text
1. PostgreSQL + pgvector
   - 원본, chunk, embedding 저장
   - vector 검색 baseline

2. Elasticsearch BM25
   - PostgreSQL chunk를 색인
   - 키워드/형태소 검색 baseline

3. Elasticsearch vector/hybrid
   - PostgreSQL embedding을 dense_vector로 색인
   - vector/hybrid 검색 A/B 테스트
```

즉 PostgreSQL과 Elasticsearch 중 하나를 고르는 구조가 아니라,
PostgreSQL을 기준 저장소로 두고 Elasticsearch를 비교 검색엔진으로 확장한다.

### 6.4 참고 docker-compose 반영 기준

참고한 pgvector compose:

```text
C:\dev\course\course_LLM\5. RAG\1. colab\3. Modular RAG\pgvector\docker-compose.yml
```

핵심 내용:

```text
image: pgvector/pgvector:pg16
POSTGRES_DB: vectordb
volume: ./database:/var/lib/postgresql/data
init.sql: CREATE EXTENSION IF NOT EXISTS vector
```

우리 프로젝트 반영:

```text
이미 docker-compose.yml에 pgvector/pgvector:pg16이 있다.
따라서 pgvector service를 새로 추가하지 않는다.
대신 traffic_precedent_db, fault_ratio_precedent_db에도 vector extension을 활성화한다.
volume은 기존 postgres_data named volume을 유지한다.
```

참고한 Elasticsearch compose:

```text
C:\dev\course\course_LLM\5. RAG\1. colab\3. Modular RAG\elasticsearch\docker-compose.yml
```

핵심 내용:

```text
Elasticsearch 8.12.1
Kibana 8.12.1
xpack.security.enabled=true
elastic/changeme123! 인증
setup container로 kibana_system 비밀번호 설정
dense_vector 실험 가능
```

우리 프로젝트 반영:

```text
Elasticsearch/Kibana는 현재 compose에 없으므로 실험 단계에서 추가한다.
단, volume은 강의 예시의 ./database를 그대로 쓰지 않는다.
프로젝트 산출물 폴더와 섞이지 않도록 infra/elasticsearch/es_data 또는 es_data로 분리한다.
비밀번호는 .env로 빼고 기본 예시 비밀번호를 운영값처럼 고정하지 않는다.
한국어 BM25/Nori 실험을 위해 infra/elasticsearch/Dockerfile에서 analysis-nori plugin을 설치한다.
```

이렇게 판단한 이유:

```text
1. pgvector는 이미 프로젝트 compose에 있으므로 중복 service를 만들면 포트/데이터 볼륨이 꼬인다.
2. Elasticsearch는 아직 없으므로 강의 compose의 service 구성을 참고하되 경로와 비밀번호는 프로젝트 방식으로 바꿔야 한다.
3. database라는 폴더명은 우리 프로젝트에서 산출물/DB 의미가 섞일 수 있으므로 Elasticsearch 내부 data volume으로 쓰지 않는다.
4. Elasticsearch는 검색 index이고, PostgreSQL은 원본/chunk/embedding 기준 저장소다.
5. Kibana 한국어 UI는 I18N_LOCALE=ko-KR로 설정하고, 검색 품질용 한국어 처리는 Nori analyzer로 따로 검증한다.
```

---

## 7. txt 기반 Elasticsearch smoke test 비채택

### 7.1 최종 판단

첨부 `4. Elasticsearch.ipynb`처럼 txt 파일을 바로 Elasticsearch에 넣는 테스트는 이번 최종 실행 계획에서 제외합니다.

이유:

```text
1. 실제 입력 데이터는 txt가 아니라 교통사고/과실비율 판례 JSONL이다.
2. PostgreSQL-first 구조를 확정했기 때문에 txt → ES 직접 적재 흐름이 불필요하다.
3. 0단계 smoke test를 별도로 두면 실행 순서가 길어지고 혼동될 수 있다.
4. Elasticsearch 연결 확인은 health check와 실제 판례 index 생성 단계에서 충분히 확인할 수 있다.
```

### 7.2 첨부 ipynb의 활용 방식

첨부 ipynb는 다음을 이해하는 참고 자료로만 둡니다.

```text
Elasticsearch Python client 연결
index 생성
bulk insert
BM25 검색
vector 검색
hybrid 검색
LangChain RAG 체인 구성
```

하지만 다음은 최종 계획에 반영하지 않습니다.

```text
txt 파일 직접 적재
rag_keywords 단일 index
200/50 chunk 설정
Ollama qwen3 embedding을 기본 운영 후보로 설정
gemma3 LLM 연결을 초기 필수 단계로 설정
```

### 7.3 최종 대체 확인 방법

txt smoke test 대신 다음 방식으로 바로 확인합니다.

```text
1. docker-compose up -d
2. Elasticsearch health check
3. PostgreSQL schema 생성
4. 실제 판례 JSONL을 PostgreSQL에 적재
5. 실제 판례 chunk 생성
6. 실제 판례 chunk를 Elasticsearch BM25 index에 색인
7. 샘플 검색 실행
```


## 8. Chunk 생성 최종 계획

### 8.1 판례 chunk 기본 설정

```text
traffic:
  chunk_size_chars = 1500
  chunk_overlap_chars = 250
  chunk_type = case_overview / traffic_metadata / holding_summary / main_text / law_reference

fault_ratio:
  chunk_size_chars = 1500
  chunk_overlap_chars = 250
  chunk_type = case_overview / fault_ratio_metadata / holding_summary / fault_ratio_evidence / main_text / law_reference
  evidence_chunk_enabled = true
```

여기서 `1500/250`은 최소/최대 범위가 아니라 **기본 chunk window 설정**입니다.

```text
1500 = chunk_size_chars
  - 하나의 chunk_text를 만들 때 목표로 삼는 본문 길이
  - 문자 수 기준이며 token 수 기준이 아님
  - 판례 본문을 1500자 단위의 검색 단락으로 나누겠다는 의미
  - 짧은 section은 1500자보다 작아도 하나의 chunk로 유지 가능
  - 긴 section은 1500자를 기준으로 여러 chunk로 분할

250 = chunk_overlap_chars
  - 앞 chunk와 다음 chunk가 겹치도록 남기는 중복 문맥 길이
  - chunk 경계에서 사고 경위, 과실 판단, 법리 판단이 끊기는 문제를 줄이기 위한 값
  - 예를 들어 1번 chunk가 0~1500자라면 다음 chunk는 대략 1250자 지점부터 다시 시작
```

즉 `1500/250`은 다음과 같은 뜻입니다.

```text
기본 chunk 길이: 약 1500자
chunk 간 문맥 중복: 약 250자
실제 chunk 길이: 문단 경계, 문장 경계, section 길이에 따라 1500자보다 짧거나 약간 달라질 수 있음
```

이 값은 DB 컬럼의 최대 길이나 저장 제한이 아닙니다.
검색과 RAG 품질을 위한 **초기 분할 기준값**입니다.

---

### 8.2 왜 200/50이 아니라 1500/250인가

첨부 ipynb의 200/50은 짧은 txt 실습에 맞는 값이지만, 이번 최종 실행 계획에서는 사용하지 않습니다.

판례에는 다음 문제가 있습니다.

```text
사고 경위가 길다.
판단 이유가 길다.
과실상계 판단이 앞뒤 문맥과 연결된다.
문단이 길고 법원 표현이 복잡하다.
```

특히 판례 검색에서는 사용자의 질문이 단순 키워드 하나가 아니라 다음처럼 들어올 가능성이 높습니다.

```text
교차로에서 신호위반 차량과 직진 차량의 과실비율
무단횡단 보행자 사고에서 운전자 책임이 제한된 사례
차로변경 사고에서 전방주시의무 위반과 과실상계가 같이 판단된 판례
보험사가 구상금 청구한 사건에서 책임비율이 어떻게 인정됐는지
```

이런 질문은 `사고 경위`, `당사자 주장`, `법원의 판단`, `과실상계 사유`, `최종 결론`이 함께 맞물립니다.
chunk가 너무 짧으면 검색은 되더라도 필요한 판단 근거가 chunk 안에 같이 들어오지 못할 수 있습니다.

200/50을 판례에 그대로 쓰면 생기는 문제는 다음과 같습니다.

```text
1. 판례 문장 2~4개만 들어가서 사고 구조가 끊긴다.
2. "원고에게도 과실이 있다" 같은 결론만 잡히고 이유가 빠질 수 있다.
3. 과실비율 숫자와 그 숫자의 판단 근거가 서로 다른 chunk로 갈라질 수 있다.
4. BM25에서는 키워드 매칭 chunk가 너무 잘게 쪼개져 top_k가 분산될 수 있다.
5. vector 검색에서는 의미 단위가 짧아져 판례의 사실관계 유사도를 충분히 담기 어렵다.
```

반대로 chunk를 너무 크게 잡으면 다음 문제가 생깁니다.

```text
1. 하나의 chunk 안에 여러 쟁점이 섞여 검색 정밀도가 떨어진다.
2. embedding 하나가 너무 넓은 의미를 담아 유사도 비교가 흐려진다.
3. RAG 응답에서 필요한 부분보다 불필요한 판례 본문이 많이 들어간다.
4. Elasticsearch BM25에서도 긴 본문이 score를 희석시킬 수 있다.
```

그래서 1500/250은 다음 균형점으로 둡니다.

```text
1500자:
  - 판례의 한 판단 단락 또는 관련 문단 묶음을 담기 위한 기본 크기
  - 사고 경위와 법원의 판단 이유가 함께 들어올 가능성을 높임
  - RAG context로 넣었을 때 지나치게 길지 않은 수준

250자 overlap:
  - chunk 경계에서 문맥이 끊기는 것을 줄이는 완충 구간
  - 과실비율 숫자와 판단 근거가 인접 chunk에 걸칠 때 회수율을 높임
  - 전체 저장량을 과도하게 늘리지 않는 중복 비율
```

250자 overlap은 1500자 기준 약 16.7%입니다.
문맥 보존 효과는 주되, 중복 chunk가 지나치게 많이 늘어나지 않도록 잡은 값입니다.

따라서 판례에는 다음 값으로 시작합니다.

```text
chunk_size_chars = 1500
chunk_overlap_chars = 250
```

현재 기준은 다음 원칙을 따릅니다.

```text
최소값/최대값:
  - 1500은 절대 최대 길이가 아님
  - 250은 절대 최소 중복 길이가 아님
  - 둘 다 A/B 테스트 전 초기 운영 기본값

분할 단위:
  - 문자 수 기준
  - 가능하면 문단/문장 경계를 우선
  - 문단이 너무 길면 1500자 window 기준으로 분할

적용 대상:
  - traffic_precedent_chunks
  - fault_ratio_precedent_chunks
  - 이후 embedding, pgvector, Elasticsearch 색인은 같은 chunk_id/chunk_text를 기준으로 진행
```

A/B 테스트 후보:

```text
A안: 1200/200
B안: 1800/300
기본값: 1500/250
```

향후 조정 기준은 다음과 같습니다.

```text
1200/200으로 낮출 조건:
  - 검색 결과에 불필요한 문맥이 너무 많이 섞이는 경우
  - top_k 안에서 정확한 쟁점 문단만 더 날카롭게 잡아야 하는 경우
  - BM25 검색에서 긴 chunk 때문에 점수가 흐려지는 경우

1800/300으로 높일 조건:
  - 과실 판단 근거가 계속 chunk 경계 밖으로 밀리는 경우
  - 사고 경위와 판단 이유가 함께 검색되지 않는 경우
  - RAG 답변에서 판례의 앞뒤 맥락 부족 문제가 반복되는 경우

현재 1500/250을 유지할 조건:
  - 검색된 chunk 안에 사고 경위와 판단 이유가 함께 들어오는 비율이 충분한 경우
  - RAG 답변에서 과실비율 판단 근거를 안정적으로 인용할 수 있는 경우
  - chunk 수와 embedding 비용이 감당 가능한 수준인 경우
```

---

### 8.3 evidence chunk

과실비율 판례에서는 다음 표현 주변을 별도 chunk로 만듭니다.

```text
과실비율
책임비율
과실상계
원고의 과실
피고의 과실
피해자의 과실
망인의 과실
손해배상책임
구상금
전방주시의무
안전운전의무
신호위반
중앙선 침범
무단횡단
차로변경
진로변경
```

예상 효과:

```text
검색 결과 상위에 과실 판단 문단이 더 잘 올라온다.
LLM context에 실제 과실상계 판단이 포함될 가능성이 높아진다.
```

---

### 8.4 chunk_type별 분리 기준

chunk는 모든 텍스트를 하나의 규칙으로만 자르지 않는다.
판례 원문, 요약, 메타데이터, 검색 보조어는 역할이 다르므로 chunk_type을 분리한다.

최종 chunk_type 기준은 다음과 같다.

```text
case_overview:
  - 사건명
  - 사건번호
  - 법원
  - 선고일
  - 사건분류
  - 판결유형
  - 교통사고/과실비율 최종 라벨

traffic_metadata:
  - traffic_signal_groups
  - traffic_evidence_terms
  - traffic_direct_terms
  - traffic_legal_terms
  - traffic_actor_terms
  - traffic_action_terms
  - traffic_situation_terms
  - traffic_fault_terms

fault_ratio_metadata:
  - fault_ratio_signal_groups
  - fault_ratio_evidence_terms
  - fault_ratio_explicit_terms
  - fault_ratio_party_fault_terms
  - fault_ratio_damage_terms
  - fault_ratio_duty_terms
  - fault_ratio_number_examples

holding_summary:
  - 판시사항
  - 요약

fault_ratio_evidence:
  - 과실비율 판단 근거어
  - 과실/책임/손해/주의의무 관련 근거 문맥
  - main_text에서 과실비율 관련 표현 주변 snippet

main_text:
  - 판례 본문

law_reference:
  - 참조법령
  - 참조판례
```

핵심 원칙:

```text
case_overview는 짧은 식별/필터용 개요로 유지한다.
evidence_terms, signal_groups 같은 긴 검색 보조 메타데이터를 case_overview에 계속 붙이지 않는다.
긴 메타데이터는 traffic_metadata 또는 fault_ratio_metadata로 분리한다.
metadata chunk도 1500자를 넘으면 1500/250 기준으로 split한다.
holding_summary도 1500자를 넘으면 1500/250 기준으로 split한다.
law_reference도 현재는 대부분 짧지만, 안전하게 1500/250 split 대상에 포함한다.
main_text와 fault_ratio_evidence는 기존처럼 1500/250 split을 유지한다.
```

이렇게 나누는 이유:

```text
1. case_overview가 메타데이터 덩어리로 비대해지는 것을 막는다.
2. 검색 보조 메타데이터는 검색용 chunk로 따로 살아 있게 한다.
3. embedding 대상 chunk_text와 실제 반환 chunk_text의 의미 범위를 일치시킨다.
4. 특정 chunk_type만 과도하게 길어져 embedding API 한도를 넘는 문제를 막는다.
5. 나중에 RAG context 구성 시 원문 chunk와 메타데이터 chunk를 구분해서 사용할 수 있다.
```

중요:

```text
embedding 입력만 임시로 잘라서 저장하는 방식은 최종 기준으로 사용하지 않는다.

잘못된 방식:
  chunk_text는 8000자인데 embedding API에는 앞 4000자만 보내는 방식

문제:
  embedding이 반영한 의미 범위와 실제 RAG에 반환되는 chunk_text 범위가 달라진다.
  뒤쪽 내용은 vector 검색에 반영되지 않았는데 LLM context에는 들어갈 수 있다.

정답:
  chunk 생성 단계에서 해당 chunk_type을 다시 분할한다.
```

따라서 chunk 품질 검증에는 다음 항목을 포함한다.

```text
chunk_type별 max(length(chunk_text)) 확인
chunk_type별 1500자 초과 개수 확인
chunk_type별 3000자 초과 개수 확인
embedding API 한도 초과 가능 chunk 확인
case_overview에 metadata가 과도하게 들어가지 않았는지 확인
```

---

## 9. Embedding 모델 통합 후보

### 9.1 운영 A/B 1차 후보

1차 embedding baseline은 `text-embedding-3-small`로 시작한다.
이 단계의 목적은 모델 성능 최종 결론을 내는 것이 아니라,
같은 embedding을 기준으로 검색 방식 차이를 먼저 보는 것이다.

| 구분 | 모델 | 역할 | 비고 |
|---|---|---|---|
| A안 | text-embedding-3-small | 1차 baseline | 1536차원, 현재 pgvector schema와 바로 호환 |
| B안 | text-embedding-3-large | 2차 고성능 비교 후보 | 1차 검색 방식 A/B 이후 dimensions=1536으로 별도 version 저장 |
| C안 | gemini-embedding-2 | 한국어 자연어 후보 | OpenAI 기준선 이후 추가 비교 |

---

### 9.2 추가 후보

| 후보 | 역할 | 사용 시점 |
|---|---|---|
| intfloat/multilingual-e5-large | 오픈소스 다국어 후보 | GPU/로컬 처리 여건 있을 때 |
| qwen3-embedding:0.6b | Ollama 로컬 참고 후보 | 최종 운영 A/B 기본 후보에서는 제외 |
| voyage-law-2 | 법률 특화 후보 | 2차 실험 |
| cohere embed-v4.0 | 긴 문서/다국어 후보 | 여유 있을 때 |

---

### 9.3 중요한 원칙

embedding A/B 테스트와 검색 방식 A/B 테스트를 섞지 않는다.

1차 실험은 다음처럼 진행한다.

```text
1차 baseline embedding:
  model = text-embedding-3-small
  dim = 1536
  input_field = chunk_text
  embedding_version = openai_text_embedding_3_small_chunk_text_v1

1차 검색 방식 A/B:
  A. PostgreSQL pgvector
  B. Elasticsearch BM25/Nori
  C. Elasticsearch hybrid = BM25/Nori + vector
```

1차 실험에서 고정하는 값:

```text
같은 chunk_id
같은 chunk_text
같은 embedding_model/version
같은 query set
같은 top_k
같은 필터 조건
```

1차 실험에서 바꾸는 값:

```text
검색엔진
검색 방식
analyzer
hybrid 조합 방식
```

이렇게 해야 검색 품질 차이가 다음 중 무엇 때문인지 분리할 수 있다.

```text
PostgreSQL pgvector가 좋은가?
Elasticsearch BM25/Nori가 좋은가?
Elasticsearch hybrid가 좋은가?
```

처음부터 embedding 모델까지 같이 바꾸면 다음 문제가 생긴다.

```text
검색 방식이 좋아서 결과가 좋아진 것인지
embedding 모델이 좋아서 결과가 좋아진 것인지
chunk 구성 때문인지 구분하기 어렵다.
```

따라서 2차 실험에서만 모델을 바꾼다.

```text
2차 model A/B:
  기존 = text-embedding-3-small, 1536
  비교 = text-embedding-3-large, dimensions=1536

small version:
  openai_text_embedding_3_small_chunk_text_v1

large version:
  openai_text_embedding_3_large_1536_chunk_text_v1
```

2차 모델 비교에서 고정하는 값:


```text
같은 판례 데이터
같은 chunk 방식
같은 chunk_id
같은 chunk_text
같은 query set
같은 평가 기준
같은 검색 방식
같은 top_k
같은 필터
```

2차 모델 비교에서 바꾸는 값:

```text
embedding_model
embedding_dim
embedding_version
```

정리하면 1차는 검색 방식 비교, 2차는 embedding 모델 비교다.

```text
1차:
  small 기준 pgvector vs BM25/Nori vs hybrid

2차:
  같은 retriever 기준 small vs large
```

---

### 9.4 참고 실습 파일에서 가져올 것과 버릴 것

이번 계획은 다음 실습 파일을 참고한다.

```text
C:\dev\course\course_LLM\5. RAG\1. colab\3. Modular RAG\1. PGVectorDB.ipynb
C:\dev\course\course_LLM\5. RAG\1. colab\3. Modular RAG\4. Elasticsearch VectorDB.ipynb
C:\dev\course\course_LLM\5. RAG\1. colab\3. Modular RAG\pgvector\docker-compose.yml
C:\dev\course\course_LLM\5. RAG\1. colab\3. Modular RAG\elasticsearch\docker-compose.yml
```

PGVectorDB.ipynb의 흐름:

```text
1. PostgreSQL 접속
2. CREATE EXTENSION IF NOT EXISTS vector
3. 문서 로드
4. RecursiveCharacterTextSplitter로 chunk 생성
5. embedding 모델 설정
6. pgvector store에 document embedding 저장
7. similarity retriever로 검색
```

우리 프로젝트에 가져올 점:

```text
1. PostgreSQL + pgvector를 embedding 저장소이자 vector 검색 baseline으로 사용한다.
2. chunk 생성 후 embedding을 DB에 저장한다.
3. retriever는 결국 chunk 단위로 동작하므로 원본 판례와 chunk 테이블을 분리한다.
4. CREATE EXTENSION IF NOT EXISTS vector는 판례 DB에도 적용한다.
```

우리 프로젝트에서 그대로 쓰지 않을 점:

```text
1. 실습의 txt DirectoryLoader는 사용하지 않는다.
   입력은 verified JSONL과 PostgreSQL 원본 테이블이다.

2. 실습의 300/30 chunk는 사용하지 않는다.
   판례는 문맥이 길기 때문에 1500/250을 기본값으로 둔다.

3. 실습의 documents 단일 테이블 구조는 사용하지 않는다.
   교통사고와 과실비율 DB/테이블을 분리한다.
```

Elasticsearch VectorDB.ipynb의 흐름:

```text
1. Elasticsearch client 연결
2. embedding 모델로 query/document vector 생성
3. dense_vector 필드가 있는 index mapping 생성
4. chunk_text + embedding + metadata를 bulk 색인
5. vector 또는 hybrid 검색 실행
```

우리 프로젝트에 가져올 점:

```text
1. Elasticsearch BM25는 chunk_text만 색인해 실험한다.
2. Elasticsearch vector/hybrid는 chunk_text와 embedding_vector를 함께 색인한다.
3. dense_vector mapping은 embedding_dim에 맞춰 생성한다.
4. bulk 색인은 PostgreSQL chunk/embedding 테이블을 source로 사용한다.
```

우리 프로젝트에서 그대로 쓰지 않을 점:

```text
1. rag_keywords 단일 index는 사용하지 않는다.
2. txt 기반 직접 색인은 사용하지 않는다.
3. qwen3-embedding:0.6b는 참고 후보일 뿐 기본 운영 후보로 고정하지 않는다.
4. Elasticsearch의 ./database volume은 프로젝트 산출물 폴더와 섞지 않는다.
```

### 9.5 최종 embedding 저장 전략

결론:

```text
embedding은 PostgreSQL에 먼저 저장한다.
Elasticsearch vector/hybrid 실험은 PostgreSQL에 저장된 embedding을 읽어서 색인한다.
```

이유:

```text
1. pgvector와 Elasticsearch vector가 같은 벡터를 써야 공정하다.
2. embedding API 비용과 시간을 줄일 수 있다.
3. Elasticsearch index는 삭제/재생성될 수 있으므로 source of truth가 되면 안 된다.
4. PostgreSQL에서 원본 판례 → chunk → embedding → 검색 index 이력을 추적할 수 있다.
5. 모델별/버전별 embedding을 보존하면 A/B 테스트 결과 재현이 가능하다.
```

embedding 입력 길이 기준:

```text
원칙:
  embedding 입력은 chunk_text 전체와 의미 범위가 일치해야 한다.

금지:
  chunk_text는 길게 보존하고 embedding API 입력만 임의로 잘라서 저장하는 방식

허용:
  실행 중단 방지를 위한 임시 안전장치로만 truncate를 둘 수 있으나,
  truncate가 발생한 chunk는 최종 적재 전 chunk 재분할 대상으로 본다.

최종 처리:
  긴 chunk가 발견되면 embedding 입력을 자르는 것이 아니라
  chunk 생성 단계에서 해당 chunk_type을 1500/250 기준으로 다시 split한다.
```

최종 기준 흐름:

```text
verified JSONL
→ PostgreSQL 원본 case 테이블
→ PostgreSQL chunk 테이블
→ Python embedding 생성
→ PostgreSQL pgvector embedding 테이블 저장
→ embedding count 검증
→ pgvector 검색용 vector index 생성
→ 검색 방식별 분기
   A. PostgreSQL pgvector 검색
   B. Elasticsearch BM25 색인
   C. Elasticsearch vector/hybrid 색인
```

중요한 구분:

```text
청크 생성 주체:
  Python 코드

embedding 생성 주체:
  Python 코드 + embedding provider

embedding 1차 저장 위치:
  PostgreSQL pgvector

pgvector index 생성 시점:
  embedding 전체 저장 및 count 검증 이후

Elasticsearch의 역할:
  검색 index
  BM25 실험에서는 embedding을 쓰지 않음
  vector/hybrid 실험에서는 PostgreSQL에 저장된 embedding을 복사 색인
```

중요:

```text
embedding 저장 코드가 곧 pgvector 검색 index 생성까지 수행하는 것은 아니다.

6번 embedding 저장 단계:
  - OpenAI embedding API 호출
  - traffic_precedent_chunk_embeddings 저장
  - fault_ratio_precedent_chunk_embeddings 저장
  - embedding count 검증

7번 pgvector 검색 baseline 단계:
  - embedding 저장 완료 여부 확인
  - pgvector HNSW 또는 IVFFlat index 생성
  - query embedding 생성
  - vector similarity 검색 SQL 구현
  - top_k 검색 결과 검증
```

따라서 Elasticsearch 실험은 두 단계로 나눈다.

```text
1. Elasticsearch BM25 실험
   - PostgreSQL chunks에서 chunk_text만 읽어 색인
   - embedding 필요 없음
   - 목적: 키워드/형태소 기반 검색 baseline 확인

2. Elasticsearch vector/hybrid 실험
   - PostgreSQL chunks + embeddings에서 chunk_text와 embedding_vector를 읽어 색인
   - 목적: dense vector 검색과 BM25+vector 결합 성능 확인
```

---

## 10. pgvector / Elasticsearch index 최종 계획

### 10.1 운영 index

```text
PostgreSQL pgvector:
  traffic_precedent_chunk_embeddings
  fault_ratio_precedent_chunk_embeddings

Elasticsearch BM25:
  traffic_case_chunks_bm25_v1
  fault_ratio_case_chunks_bm25_v1

Elasticsearch vector:
  traffic_case_chunks_vector_openai_small_v1
  fault_ratio_case_chunks_vector_openai_small_v1

Elasticsearch hybrid:
  traffic_case_chunks_hybrid_openai_small_v1
  fault_ratio_case_chunks_hybrid_openai_small_v1
```

---

### 10.2 운영 alias

```text
traffic_cases_current
traffic_case_chunks_current

fault_ratio_cases_current
fault_ratio_case_chunks_current
```

---

### 10.3 A/B 테스트 index

```text
fault_ratio_case_chunks_bm25_standard_v1
fault_ratio_case_chunks_bm25_nori_v1
fault_ratio_case_chunks_openai_small_v1
fault_ratio_case_chunks_gemini_embedding2_v1
fault_ratio_case_chunks_hybrid_openai_small_v1
fault_ratio_case_chunks_hybrid_gemini_embedding2_v1
```

---

### 10.4 smoke test index

```text
rag_keywords_smoke_test
```

주의:

```text
rag_keywords_smoke_test는 강의 실습용 개념 확인 index다.
이번 판례 운영/실험 index와 완전히 별개이다.
```

---

## 11. 검색 방식 계획

### 11.1 검색 방식 3갈래

```text
공통 준비:
  PostgreSQL 원본 case
  PostgreSQL chunk
  PostgreSQL embedding

검색 방식 A:
  PostgreSQL pgvector

검색 방식 B:
  Elasticsearch BM25

검색 방식 C:
  Elasticsearch vector/hybrid
```

### 11.2 방식 A: PostgreSQL pgvector 검색

목적:

```text
현재 프로젝트에 이미 있는 PostgreSQL + pgvector 기반을 활용해
가장 먼저 구현 가능한 vector 검색 baseline을 만든다.
```

사용 데이터:

```text
traffic_precedent_chunks
traffic_precedent_chunk_embeddings

fault_ratio_precedent_chunks
fault_ratio_precedent_chunk_embeddings
```

검색 방식:

```text
1. 사용자 질문 embedding 생성
2. PostgreSQL pgvector cosine distance 검색
3. top_k chunk 반환
4. case_id로 원본 판례 메타데이터 join
```

실행 세부 단계:

```text
1. embedding count 최종 검증
   - traffic_precedent_chunks 수와 traffic_precedent_chunk_embeddings 수 비교
   - fault_ratio_precedent_chunks 수와 fault_ratio_precedent_chunk_embeddings 수 비교
   - embedding_dim = 1536 확인
   - embedding_version = openai_text_embedding_3_small_chunk_text_v1 확인

2. pgvector 검색용 index 생성
   - embedding 저장 완료 후 생성
   - 기본 후보: HNSW + vector_cosine_ops
   - 대량 embedding insert 중에는 생성하지 않고, 적재 완료 후 생성

3. query embedding 생성 코드 작성
   - 사용자 자연어 질문을 text-embedding-3-small로 embedding
   - document embedding과 같은 model/dim/version 기준을 사용

4. pgvector similarity 검색 코드 작성
   - query vector와 embedding_vector 간 cosine distance 계산
   - chunk 테이블과 case 테이블을 join
   - chunk_id, case_id, case_name, court_name, decision_date, chunk_type, chunk_text, similarity 반환

5. 샘플 질의로 top_k 결과 확인
   - 차로변경 사고 과실비율 판례
   - 무단횡단 보행자 사고 책임 제한
   - 신호위반 교차로 사고
   - 보험사 구상금 과실상계
   - 중앙선 침범 사고 과실 판단
```

완료 기준:

```text
1. validate_embedding_counts 결과가 is_complete = true
2. pgvector index 생성 SQL이 성공
3. 샘플 자연어 질문을 embedding으로 변환 가능
4. top_k 검색 결과가 chunk_text와 metadata를 함께 반환
5. 검색 결과가 판례 RAG context로 사용할 수 있는 형태
6. 이후 Elasticsearch BM25/vector/hybrid와 같은 query set으로 비교 가능
```

중요:

```text
pgvector baseline은 최종 챗봇이나 Supervisor 자체가 아니다.
나중에 Agent/Supervisor가 호출할 판례 검색 도구의 기본형이다.

사용자 질문
→ Supervisor/Agent
→ 판례 검색이 필요하다고 판단
→ pgvector_retriever 또는 Elasticsearch retriever 호출
→ 관련 chunk 반환
→ LLM 답변 생성
```

장점:

```text
1. 현재 docker-compose의 pgvector PostgreSQL을 그대로 활용할 수 있다.
2. 원본, chunk, embedding, 검색 결과 추적이 한 DB 안에서 가능하다.
3. Elasticsearch 없이도 vector RAG baseline을 빠르게 만들 수 있다.
4. DB row count 검증과 embedding 생성 상태 관리가 쉽다.
```

한계:

```text
1. 키워드 exact match나 형태소 기반 검색은 Elasticsearch BM25/Nori보다 약할 수 있다.
2. 대규모 인덱스 최적화는 별도 HNSW index 설계가 필요하다.
3. hybrid score 조합을 직접 구현해야 할 수 있다.
```

### 11.3 방식 B: Elasticsearch BM25 검색

목적:

```text
법률/판례 검색에서 중요한 사건명, 법률용어, 과실 키워드, 사고유형 키워드의
문자 기반 검색 성능을 확인한다.
```

사용 데이터:

```text
PostgreSQL chunk 테이블의 chunk_text/search_text
```

색인 데이터:

```text
chunk_id
case_id
chunk_type
chunk_text
search_text
case_name
case_number
court_name
decision_date
case_category
traffic/fault_ratio label
metadata
```

embedding 사용 여부:

```text
사용하지 않는다.
```

장점:

```text
1. "구상금", "무단횡단", "중앙선 침범", "과실상계" 같은 명시 키워드에 강하다.
2. Nori analyzer를 붙이면 한국어 형태소 기반 검색 실험이 가능하다.
3. embedding 비용 없이 빠르게 검색 baseline을 만들 수 있다.
```

한계:

```text
1. 표현이 다른 의미 유사 질문에는 약할 수 있다.
2. 사고 상황을 자연어로 길게 물어보는 경우 vector 검색보다 놓칠 수 있다.
```

### 11.4 방식 C: Elasticsearch vector/hybrid 검색

목적:

```text
Elasticsearch의 검색엔진 기능과 dense vector 검색을 결합해
pgvector와 BM25보다 나은 retrieval 품질이 나오는지 검증한다.
```

사용 데이터:

```text
PostgreSQL chunk 테이블
PostgreSQL embedding 테이블
```

색인 데이터:

```text
chunk_text
search_text
embedding_vector
metadata
```

Elasticsearch mapping 핵심:

```json
{
  "mappings": {
    "properties": {
      "chunk_text": {
        "type": "text",
        "analyzer": "standard"
      },
      "embedding": {
        "type": "dense_vector",
        "dims": 1536,
        "index": true,
        "similarity": "cosine"
      },
      "metadata": {
        "type": "object",
        "enabled": true
      }
    }
  }
}
```

주의:

```text
dims는 embedding 모델 차원에 맞춘다.
실습 qwen3 예시는 1024차원이었고,
OpenAI text-embedding-3-small 계열은 1536차원 기준으로 검토한다.
```

검색 방식:

```text
vector:
  사용자 질문 embedding → Elasticsearch dense_vector kNN 검색

hybrid:
  BM25 점수 + vector 점수 결합
  또는 BM25 top_n과 vector top_n을 합쳐 rerank
```

장점:

```text
1. 키워드 검색과 의미 검색을 동시에 활용할 수 있다.
2. Elasticsearch의 index/alias/bulk/reindex 운영 기능을 사용할 수 있다.
3. Kibana로 index 상태와 검색 결과를 확인하기 좋다.
```

한계:

```text
1. Elasticsearch 서비스를 추가로 운영해야 한다.
2. dense_vector mapping과 embedding 차원 관리가 필요하다.
3. PostgreSQL embedding과 Elasticsearch 색인 사이의 동기화 관리가 필요하다.
```

---

### 11.5 최종 진행 순서 추천

초기 구현:

```text
PostgreSQL 원본 적재
→ PostgreSQL chunk 생성
→ PostgreSQL embedding 저장
→ embedding count 검증
→ pgvector HNSW/IVFFlat index 생성
→ pgvector 검색 baseline
```

두 번째 구현:

```text
같은 PostgreSQL chunk를 Elasticsearch BM25에 색인
→ BM25/Nori 검색 baseline
```

세 번째 구현:

```text
PostgreSQL에 저장된 embedding을 Elasticsearch dense_vector에 색인
→ Elasticsearch vector/hybrid 검색
```

이 순서로 가는 이유:

```text
1. 현재 인프라에 PostgreSQL(pgvector)이 이미 있다.
2. Elasticsearch 없이도 먼저 RAG 검색 baseline을 만들 수 있다.
3. 같은 chunk와 같은 embedding을 기준으로 검색엔진만 바꿔 비교할 수 있다.
4. Elasticsearch 도입 효과를 나중에 정량적으로 판단할 수 있다.
5. vector index는 embedding 전체 저장 후 생성해야 대량 insert 성능 저하를 줄일 수 있다.
```

---

### 11.6 Elasticsearch 실험 세부 실행 계획

8번 Elasticsearch BM25/vector 실험은 하나의 작업으로 끝내지 않는다.
Elasticsearch는 PostgreSQL처럼 원본 테이블을 바로 검색하는 구조가 아니라,
검색 전용 index를 설계하고 PostgreSQL chunk/embedding을 복사 색인한 뒤 검색해야 한다.

따라서 8번은 다음 하위 단계로 나누어 진행한다.

```text
8-1. Elasticsearch 실행 환경 확인
  - docker-compose에 Elasticsearch/Kibana 서비스가 추가되어 있는지 확인
  - Nori analyzer 설치 방식 확인
  - .env의 Elasticsearch host, port, user/password 확인
  - health check로 클러스터 접속 확인

8-2. Elasticsearch index mapping 설계
  - traffic index와 fault_ratio index 분리
  - BM25 standard analyzer field 정의
  - BM25 Nori analyzer field 정의
  - vector 검색용 dense_vector field 정의
  - case_id, chunk_id, chunk_type, case_name, court_name 등 metadata field 정의

8-3. PostgreSQL chunk -> Elasticsearch text 색인
  - traffic_precedent_chunks 읽기
  - fault_ratio_precedent_chunks 읽기
  - chunk_text, search_text, case metadata 색인
  - 이 단계에서는 embedding_vector를 쓰지 않고 BM25/Nori 실험만 준비

8-4. BM25/Nori sample search
  - standard analyzer 검색
  - nori analyzer 검색
  - 같은 query set, 같은 top_k 기준으로 결과 저장
  - pgvector sample 결과와 비교 가능한 JSON 포맷 사용

8-5. PostgreSQL embedding -> Elasticsearch dense_vector 색인
  - traffic_precedent_chunk_embeddings 읽기
  - fault_ratio_precedent_chunk_embeddings 읽기
  - embedding_model, embedding_version, embedding_dim 기준으로 필터링
  - PostgreSQL에 저장된 embedding_vector를 Elasticsearch dense_vector에 복사

8-6. Elasticsearch vector search
  - query embedding 생성
  - dense_vector kNN 검색
  - pgvector와 같은 cosine 기준으로 비교 가능하게 결과 저장

8-7. Elasticsearch hybrid search
  - BM25/Nori 점수와 vector 검색 결과를 결합
  - 1차 후보: BM25 top_n + vector top_n union 후 RRF 또는 가중치 결합
  - hybrid raw score는 내부 정렬용으로만 사용

8-8. A/B 비교용 결과 포맷 통일
  - query_id
  - query
  - retriever
  - rank
  - retriever_score
  - chunk_id
  - case_id
  - chunk_type
  - case_name
  - chunk_text
  - search_text
  - metadata
```

이 단계의 핵심 원칙은 다음과 같다.

```text
1. PostgreSQL은 원본/chunk/embedding 기준 저장소다.
2. Elasticsearch는 검색 실험용 index다.
3. Elasticsearch index는 삭제/재생성 가능해야 한다.
4. BM25 실험은 embedding 없이 먼저 진행한다.
5. vector/hybrid 실험은 PostgreSQL에 이미 저장된 embedding을 읽어 색인한다.
6. pgvector, BM25/Nori, vector, hybrid 결과는 같은 query set과 같은 top_k로 저장한다.
7. 검색기 raw score는 서로 직접 비교하지 않는다.
8. 최종 A/B 비교는 별도 공통 평가 점수 또는 로컬 기성 reranker 평가로 진행한다.
```

#### 11.6.1 Kibana 접속 계정 결정

목적:

```text
Elasticsearch BM25/Nori/vector 실험은 Python API만으로도 가능하다.
하지만 Kibana가 정상 동작하면 index, mapping, document count, sample query를
화면에서 확인할 수 있으므로 실험 검증 편의성이 좋아진다.
```

현재 문제:

```text
Elasticsearch 8.12.1은 정상 실행되고 localhost:9200에서 JSON 응답이 나온다.
반면 Kibana는 localhost:5601에서 ERR_EMPTY_RESPONSE가 발생한다.

로그 핵심:
  [config validation of [elasticsearch].username]:
  value of "elastic" is forbidden.

원인:
  Kibana가 Elasticsearch에 elastic superuser 계정으로 접속하도록 설정되어 있다.
  Elasticsearch 8.x에서는 Kibana 내부 시스템 index 관리를 위해
  elastic superuser를 Kibana server 계정으로 쓰는 구성을 막는다.
```

검토한 선택지:

| 방식 | 설명 | 장점 | 한계 | 판단 |
|---|---|---|---|---|
| A. `kibana_system` 계정 사용 | Elasticsearch 내장 Kibana 시스템 계정 비밀번호를 설정하고 Kibana가 이 계정으로 접속 | 보안을 유지하면서 Kibana UI 사용 가능, Elasticsearch 8.x 권장 흐름에 가까움 | 비밀번호 설정과 compose 수정 필요 | 채택 |
| B. service account token 사용 | Kibana용 service token을 생성해 접속 | 운영 환경에 더 적합 | 로컬 실험 단계에서는 설정이 더 번거로움 | 후순위 |
| C. security off | Elasticsearch/Kibana 보안을 끄고 로컬에서 바로 접속 | 가장 단순 | 보안 약화, 추후 운영/공유 환경과 차이 큼 | 비채택 |

A 방식을 선택하는 이유:

```text
1. 추가 비용이 없다.
2. OpenAI API나 외부 서비스 호출이 아니다.
3. Elasticsearch 보안을 끄지 않는다.
4. Kibana UI를 정상 사용할 수 있다.
5. 현재 에러 원인인 "elastic superuser로 Kibana 접속" 문제를 직접 해결한다.
```

코드/설정 수정 방향:

```text
1. .env에 Kibana 전용 비밀번호 추가
   KIBANA_SYSTEM_PASSWORD=change-me

2. Elasticsearch에 kibana_system 계정 비밀번호 설정
   POST /_security/user/kibana_system/_password

3. docker-compose.yml의 kibana service 수정

   기존:
     ELASTICSEARCH_USERNAME=elastic
     ELASTICSEARCH_PASSWORD=${ELASTIC_PASSWORD:-change-me}

   변경:
     ELASTICSEARCH_USERNAME=kibana_system
     ELASTICSEARCH_PASSWORD=${KIBANA_SYSTEM_PASSWORD:-change-me}

4. Kibana 컨테이너 재생성
   docker compose up -d kibana
```

예상 결과:

```text
Elasticsearch:
  localhost:9200 정상 유지

Kibana:
  localhost:5601 접속 가능
  elastic superuser 금지 에러 사라짐
  로그인 화면 또는 Kibana UI 표시

주의:
  Kibana는 Elasticsearch보다 부팅이 느릴 수 있으므로 재기동 직후 30~90초 정도 기다릴 수 있다.
  elastic 계정은 브라우저 로그인용 superuser로 계속 사용할 수 있지만,
  Kibana server가 Elasticsearch에 붙는 내부 계정으로는 사용하지 않는다.
```

#### 11.6.2 Kibana Dev Tools 실제 확인 결과 (2026-07-03)

**확인 일자:** 2026-07-03

위 kibana_system 계정 방식(A 방식) 적용 후 Kibana가 정상 동작하는 것을 확인했다.

**Kibana Dev Tools 접근 방법:**

```text
Kibana UI (localhost:5601) 접속
→ 왼쪽 상단 ☰ 메뉴
→ Management
→ Dev Tools

또는 상단 검색창에 "Dev Tools" 검색
```

**Elasticsearch 상태 확인 (실제 실행):**

```http
GET /
```

응답: 200 OK, Elasticsearch 8.12.1 클러스터 정상 확인

**Nori 분석기 작동 확인 (실제 실행):**

```http
POST /_analyze
{
  "analyzer": "nori",
  "text": "차로변경 사고 과실비율"
}
```

**실제 응답 결과 (200 OK, 89ms):**

```json
{
  "tokens": [
    { "token": "차",   "start_offset": 0,  "end_offset": 2,  "type": "word", "position": 0 },
    { "token": "변경",  "start_offset": 2,  "end_offset": 4,  "type": "word", "position": 2 },
    { "token": "사고",  "start_offset": 5,  "end_offset": 7,  "type": "word", "position": 3 },
    { "token": "과실",  "start_offset": 8,  "end_offset": 10, "type": "word", "position": 4 },
    { "token": "비율",  "start_offset": 10, "end_offset": 12, "type": "word", "position": 5 }
  ]
}
```

**확인 결과 요약:**

```text
Nori 분석기 상태: 정상 작동
토큰화 결과: 차 / 변경 / 사고 / 과실 / 비율 (5개 토큰)
응답 코드: 200 OK
응답 시간: 89ms

특이 사항:
  "차로변경"이 "차" + "변경"으로 분리된다.
  한국어 복합어를 형태소 단위로 분리하는 Nori 기본 동작이 확인됐다.
  "차로변경" 원형을 하나의 토큰으로 잡으려면 user_dictionary 또는 decompound_mode 설정을 검토해야 한다.
```

**활용 방향:**

```text
Kibana Dev Tools는 코드 없이 Elasticsearch API를 빠르게 테스트하는 용도로 쓴다.
실제 판례 index 생성, document 색인, BM25 샘플 검색 확인에 활용한다.
index mapping 확인, document count 확인도 Dev Tools에서 바로 할 수 있다.
```

**"차로변경" 분리 관련 후속 검토 항목:**

```text
Nori decompound_mode:
  none: 복합어를 분리하지 않음 ("차로변경" → "차로변경" 단일 토큰)
  discard: 복합어를 분리하고 원형 제거 (현재 기본 동작)
  mixed: 복합어와 분리 결과를 동시 색인

user_dictionary:
  "차로변경"을 사전에 등록하면 하나의 어절로 인식 가능

A/B 테스트 후보:
  A안: 기본 decompound_mode=discard (현재 확인 상태)
  B안: decompound_mode=mixed로 설정해 "차로변경" + "차" + "변경" 동시 색인
  C안: user_dictionary에 도메인 단어 등록 후 비교
```

코드 구조는 `precedent_search/` 안에서 pgvector baseline 이후 확장한다.

```text
etl/fault_cases/src/traffic_precedents/precedent_search/
  elasticsearch_config.py
  elasticsearch_indexer.py
  elasticsearch_bm25_retriever.py
  elasticsearch_vector_retriever.py
  elasticsearch_hybrid_retriever.py
  run_elasticsearch_sample_queries.py
  export_retrieval_results.py
```

실행 산출물은 PostgreSQL export와 분리해서 Elasticsearch 실험 결과로 저장한다.

```text
etl/fault_cases/artifacts/traffic_precedents_output/elasticsearch_exports/
  traffic/
    traffic_bm25_index_report.json
    traffic_bm25_sample_queries.json
    traffic_vector_index_report.json
    traffic_vector_sample_queries.json
    traffic_hybrid_sample_queries.json

  fault_ratio/
    fault_ratio_bm25_index_report.json
    fault_ratio_bm25_sample_queries.json
    fault_ratio_vector_index_report.json
    fault_ratio_vector_sample_queries.json
    fault_ratio_hybrid_sample_queries.json
```

---

## 12. A/B 테스트 계획

### 12.1 먼저 하는 테스트

테스트는 한 번에 모든 변수를 바꾸지 않는다.
먼저 `text-embedding-3-small`을 공통 embedding 기준으로 고정하고,
검색 방식 차이를 비교한다.
그 다음에 같은 검색 방식 안에서 embedding 모델만 바꿔 비교한다.

```text
1차 검색 방식 A/B:
  1. pgvector vector baseline
  2. Elasticsearch BM25 standard analyzer
  3. Elasticsearch BM25 Nori analyzer
  4. Elasticsearch vector
  5. Elasticsearch hybrid

2차 모델 A/B:
  6. text-embedding-3-small vs text-embedding-3-large(dimensions=1536)
  7. OpenAI 계열 vs gemini-embedding-2

3차 chunk 전략 A/B:
  8. main_text chunk only vs structured/evidence chunk
```

테스트 통제 조건:

```text
같은 verified JSONL
같은 PostgreSQL case row
같은 chunk_id
같은 chunk_text
같은 embedding_model/version
같은 test query
같은 top_k
같은 필터 조건
```

비교할 것:

```text
검색엔진 차이:
  pgvector vs Elasticsearch

검색 방식 차이:
  BM25 vs vector vs hybrid

분석기 차이:
  standard analyzer vs Nori analyzer

모델 차이:
  OpenAI small vs OpenAI large 1536
  OpenAI 계열 vs Gemini embedding

chunk 전략 차이:
  main_text 중심 chunk vs evidence/structured chunk
```

---

### 12.2 평가 지표

검색 점수는 두 종류로 구분한다.

```text
1. retriever 내부 점수
   - 각 검색기가 자기 결과를 정렬하기 위해 쓰는 점수
   - pgvector cosine similarity, BM25 score, hybrid score 등

2. A/B 테스트 평가 점수
   - 서로 다른 검색 방식을 공통 기준으로 비교하기 위한 점수
   - manual relevance score, LLM judge score, Hit@k, Precision@k, MRR 등
```

중요한 점:

```text
pgvector cosine similarity와 Elasticsearch BM25 score는 직접 비교하지 않는다.
점수 체계와 범위가 다르기 때문이다.

예:
  pgvector similarity = 0.82
  BM25 score = 13.7
  hybrid score = 0.61

위 숫자는 서로 같은 척도가 아니므로 "13.7이 가장 좋다"고 판단할 수 없다.
```

따라서 raw score는 각 검색기 내부 정렬용으로만 사용하고,
최종 A/B 비교는 공통 평가 기준으로 한다.

### 12.2.1 vector similarity 후보

pgvector와 Elasticsearch vector 검색에서 사용할 수 있는 대표 유사도/거리 기준은 다음과 같다.

| 기준 | 의미 | 값 해석 | pgvector 연산자 | 장점 | 한계 | 1차 적용 여부 |
|---|---|---|---|---|---|---|
| Cosine Similarity | 두 벡터가 같은 방향을 보는지 측정 | similarity는 클수록 유사, distance는 작을수록 유사 | `<=>` cosine distance | 텍스트 의미 검색에서 가장 무난, chunk 길이 차이에 비교적 안정적 | 벡터 크기 정보는 거의 사용하지 않음 | 1차 baseline |
| Dot Product | 방향과 벡터 크기를 함께 반영 | 클수록 유사 | `<#>` negative inner product | 모델이 dot product 기준에 잘 맞으면 강함 | 벡터 크기 영향으로 해석이 까다로울 수 있음 | 2차 후보 |
| Euclidean Distance | 벡터 공간에서 두 점의 직선 거리 | 작을수록 유사 | `<->` L2 distance | 직관적이고 단순함 | 텍스트 embedding 검색에서는 cosine보다 덜 쓰이는 편 | 보류 |

1차 기준은 Cosine Similarity로 둔다.

이유:

```text
1. text-embedding-3-small 기반 텍스트 의미 검색에 무난하다.
2. pgvector와 Elasticsearch dense_vector 양쪽에서 cosine 기준을 맞추기 쉽다.
3. 검색 방식 A/B에서 embedding similarity 기준을 통제하기 좋다.
4. chunk 길이와 표현 차이가 있어도 방향 중심 비교가 안정적이다.
```

pgvector에서는 cosine distance를 사용한다.

```sql
embedding_vector <=> query_vector
```

이 값은 distance이므로 작을수록 가깝다.
사용자에게 similarity로 보여주거나 리포트에 남길 때는 다음처럼 변환할 수 있다.

```sql
1 - (embedding_vector <=> query_vector) AS similarity
```

### 12.2.2 공통 평가 점수 후보

검색 방식별 raw score를 직접 비교하지 않기 때문에,
A/B 테스트에는 별도 공통 평가 기준이 필요하다.

| 평가 방식 | 설명 | 장점 | 한계 | 적용 시점 |
|---|---|---|---|---|
| manual_relevance_score | 사람이 query와 chunk를 보고 0~3점 부여 | 가장 설명 가능하고 팀 합의가 쉬움 | 사람이 봐야 해서 느림 | 1차 추천 |
| llm_judge_relevance_score | LLM에게 query와 chunk 관련성을 0~3점으로 평가하게 함 | 반자동화 가능, 평가 기준을 prompt에 넣을 수 있음 | 비용/일관성 관리 필요 | 2차 추천 |
| local_reranker_score | 로컬 기성 reranker가 query-chunk relevance를 공통 점수로 산출 | 검색엔진 raw score 차이를 통일하기 좋고 외부 API 비용이 없음 | 로컬 모델 설치/CPU-GPU 속도 부담, 점수 해석 검수 필요 | 검색 방식 A/B 1차 평가 후보 |
| Hit@k | top k 안에 관련 chunk가 하나라도 있는지 | 단순하고 빠름 | 관련 chunk가 몇 개인지는 반영 약함 | 보조 지표 |
| Precision@k | top k 중 관련 chunk 비율 | 결과 목록의 밀도 평가 가능 | 관련성 강도 차이는 반영 약함 | 보조 지표 |
| MRR@k | 첫 관련 chunk가 몇 등인지 | 관련 결과가 얼마나 빨리 나오는지 평가 | 두 번째 이후 관련 결과 품질은 약하게 반영 | 보조 지표 |
| nDCG@k | 관련성 등급과 순위를 함께 반영 | 0~3점 등급 평가와 잘 맞음 | 계산/라벨링이 조금 더 복잡 | 2차 지표 |

현재 1차 A/B 테스트에서는 다음처럼 시작한다.

```text
공통 평가 점수:
  local_reranker_score

보조 지표:
  manual_relevance_score 0~3 일부 샘플 검수
  Hit@5
  Precision@5
  MRR@5
```

manual_relevance_score 기준:

```text
0점 = 관련 없음
1점 = 키워드만 일부 관련
2점 = 사고 상황은 관련 있으나 과실/책임 판단 근거가 약함
3점 = 사고 상황과 과실/책임 판단 근거가 모두 적합
```

검색 방식 A/B 평가 순서는 다음처럼 둔다.

```text
1차:
  로컬 기성 reranker로 pgvector, BM25/Nori, hybrid의 top_k 결과를 공통 채점

2차:
  사람이 일부 query의 top_k 결과를 0~3점으로 샘플 검수

3차:
  필요하면 LLM judge 또는 검색 개선용 reranking 검토
```

reranker에 대한 판단:

```text
reranker는 검색 결과를 바꾸는 용도가 아니라 A/B 테스트 공통 평가자로 먼저 사용한다.

pgvector, BM25/Nori, hybrid가 가져온 top_k 결과는 그대로 보존한다.
그 뒤 같은 로컬 기성 reranker로 query + chunk_text 관련성을 채점한다.

초기에는 비용이 들지 않는 로컬 기성 reranker를 사용한다.
fine-tuning은 query-positive-negative 데이터가 충분히 쌓인 뒤 고도화 단계에서만 검토한다.

상세 설계 문서:
etl/fault_cases/Fault_cases_MD/판례/판례 검색 A-B 평가 및 로컬 리랭커 계획.md
```

### 12.2.3 운영 평가 지표

| 지표 | 설명 |
|---|---|
| Top-5 Hit | 상위 5개 안에 관련 판례가 있는가 |
| Precision@5 | 상위 5개 중 실제 관련 판례 비율 |
| 과실판단 포함률 | 검색된 chunk에 과실상계/책임비율 판단이 있는가 |
| 사고유형 일치율 | 사용자 사고와 판례 사고유형이 맞는가 |
| Noise Count | 형사/면허/산재/진료수가 등 노이즈 개수 |
| MRR | 첫 관련 결과가 몇 번째에 있는가 |
| latency | 검색 응답 속도 |
| cost | embedding/API 비용 |

---

### 12.3 테스트 질문 예시

```text
신호 없는 교차로에서 직진 차량과 우회전 차량 충돌
좌회전 차량과 직진 오토바이 충돌
무단횡단 보행자와 직진 차량 충돌
횡단보도에서 보행자가 차량에 충격
후미추돌 사고에서 앞차 급정거 과실
차로 변경 중 후행 차량과 충돌
중앙선 침범 차량과 마주 오던 차량 충돌
주차장에서 후진 차량이 보행자 충격
비보호 좌회전 차량과 직진 차량 충돌
보험사가 구상금 청구한 책임분담비율 사건
```

---

## 13. 코드 구현 최종 계획

### 13.1 최종 코드 구조

```text
C:\dev\project\SKN27-FINAL-3Team
  storage/
    schemas/
      law_db_schema.sql
      precedent_db_schema.sql

  etl/fault_cases/src/traffic_precedents/
    traffic_precedents_crawling/
      traffic_prec_api_collector_all_raw_commented.py

    traffic_precedents_preprocessing/
      preprocess_traffic_precedents_final_all_raw_maintext_clean.py

    traffic_precedents_1st_classification-traffic accident/
      traffic_relevance_reclassifier_stage1.py

    traffic_precedents_1st_classification-verification/
      traffic_relevance_recheck.py

    traffic_precedents_2nd_classification-fault_ratio/
      traffic_fault_ratio_stage2.py

    traffic_precedents_2nd_classification-verification/
      traffic_fault_ratio_recheck.py

    precedent_db_loading/             # 추가 예정
      __init__.py
      config.py
      db.py
      schema_loader.py
      load_traffic_precedents.py
      load_fault_ratio_precedents.py
      validate_loaded_counts.py

    precedent_chunking/               # 추가 예정
      __init__.py
      chunk_config.py
      text_builder.py
      chunker.py
      create_traffic_chunks.py
      create_fault_ratio_chunks.py

    precedent_embedding/              # 추가 예정
      __init__.py
      embedding_config.py
      openai_embedder.py
      store_embeddings_common.py
      embed_traffic_chunks.py
      embed_fault_ratio_chunks.py
      validate_embedding_counts.py

    precedent_search/                 # pgvector baseline 이후 Elasticsearch 실험 단계에서 확장
      __init__.py
      create_pgvector_indexes.py
      pgvector_retriever.py
      elasticsearch_indexer.py
      retrieval_eval.py
      compare_ab_results.py

  etl/fault_cases/artifacts/traffic_precedents_output/
    traffic_prec_api/
    traffic_prec_preprocessed/
    traffic_prec_reclass/
    traffic_prec_reclass_verified/
    traffic_prec_fault_ratio/
    traffic_prec_fault_ratio_verified/
    postgres_exports/
    elasticsearch_exports/
    eval_results/
```

---

### 13.2 코드별 역할

| 코드 | 역할 |
|---|---|
| `precedent_db_schema.sql` | `traffic_precedent_db`, `fault_ratio_precedent_db` schema 정의 |
| `precedent_db_loading/config.py` | DB명, 입력 JSONL, 출력 report 경로 관리 |
| `precedent_db_loading/db.py` | psycopg 접속, upsert, transaction 공통 함수 |
| `precedent_db_loading/schema_loader.py` | 판례 DB 생성 및 schema 적용 |
| `precedent_db_loading/load_traffic_precedents.py` | 교통사고 verified JSONL을 `traffic_precedent_db`에 적재 |
| `precedent_db_loading/load_fault_ratio_precedents.py` | 과실비율 verified JSONL을 `fault_ratio_precedent_db`에 적재 |
| `precedent_db_loading/validate_loaded_counts.py` | JSONL row 수와 DB row 수 검증 |
| `precedent_chunking/text_builder.py` | 판례별 검색용 텍스트 구성 |
| `precedent_chunking/chunker.py` | 1500/250 등 chunk 생성 공통 로직 |
| `precedent_chunking/create_traffic_chunks.py` | 교통사고 판례 chunk 생성 |
| `precedent_chunking/create_fault_ratio_chunks.py` | 과실비율 판례 chunk 생성 |
| `precedent_embedding/embedding_config.py` | embedding 모델, 차원, version, batch 설정 |
| `precedent_embedding/openai_embedder.py` | OpenAI embedding API 호출 |
| `precedent_embedding/store_embeddings_common.py` | chunk 조회, embedding 저장, chunk 상태 업데이트 공통 로직 |
| `precedent_embedding/embed_traffic_chunks.py` | 교통사고 판례 chunk embedding 저장 |
| `precedent_embedding/embed_fault_ratio_chunks.py` | 과실비율 판례 chunk embedding 저장 |
| `precedent_embedding/validate_embedding_counts.py` | chunk 수와 embedding 수 검증 |
| `precedent_search/create_pgvector_indexes.py` | embedding 저장 완료 후 pgvector HNSW/IVFFlat index 생성 |
| `precedent_search/pgvector_retriever.py` | pgvector baseline 검색 구현 |
| `precedent_search/elasticsearch_indexer.py` | Elasticsearch 검색을 선택할 경우 index 생성 |
| `precedent_search/retrieval_eval.py` | retrieval A/B 테스트 실행 |
| `precedent_search/compare_ab_results.py` | 결과 비교 및 최종 설정 추천 |

---

## 14. 최종 실행 순서

```text
0. docker-compose 실행
   - 현재 기준 필수: PostgreSQL(pgvector)
   - Elasticsearch/Kibana는 BM25/vector 실험 단계에서 추가

1. 판례 수집
   - traffic_prec_api_collector_all_raw_commented.py
   - 산출물: traffic_prec_api/all_prec_candidates_raw.jsonl

2. 판례 전처리
   - preprocess_traffic_precedents_final_all_raw_maintext_clean.py
   - 산출물: traffic_prec_preprocessed/06_all_cases_quality_checked.jsonl
   - 기존 산출물 traffic_prec_work는 legacy로만 본다.

3. 1차 교통사고 분류
   - traffic_relevance_reclassifier_stage1.py
   - 산출물: traffic_prec_reclass/

4. 1차 교통사고 검증
   - traffic_relevance_recheck.py
   - 적재 기준: traffic_prec_reclass_verified/01_confirmed_traffic_cases.jsonl

5. 2차 과실비율 분류
   - traffic_fault_ratio_stage2.py
   - 산출물: traffic_prec_fault_ratio/

6. 2차 과실비율 검증
   - traffic_fault_ratio_recheck.py
   - 적재 기준: traffic_prec_fault_ratio_verified/01_fault_ratio_confirmed_cases.jsonl

7. 판례 DB schema 생성
   - storage/schemas/precedent_db_schema.sql
   - 생성 DB: traffic_precedent_db, fault_ratio_precedent_db

8. 교통사고 판례 DB 적재
   - load_traffic_precedents.py
   - 입력: traffic_prec_reclass_verified/01_confirmed_traffic_cases.jsonl
   - 대상 DB: traffic_precedent_db

9. 과실비율 판례 DB 적재
   - load_fault_ratio_precedents.py
   - 입력: traffic_prec_fault_ratio_verified/01_fault_ratio_confirmed_cases.jsonl
   - 대상 DB: fault_ratio_precedent_db

10. row count 검증
    - traffic JSONL 3,562건 = traffic_precedent_db row 수
    - fault_ratio JSONL 973건 = fault_ratio_precedent_db row 수

11. PostgreSQL 기준 chunk 생성
    - traffic_precedent_chunks
    - fault_ratio_precedent_chunks

12. PostgreSQL 기준 embedding 생성 및 저장
    - traffic_precedent_chunk_embeddings
    - fault_ratio_precedent_chunk_embeddings
    - embedding_model, embedding_dim, embedding_version 기록

13. embedding count 검증
    - traffic_precedent_chunks 수 = traffic_precedent_chunk_embeddings 수
    - fault_ratio_precedent_chunks 수 = fault_ratio_precedent_chunk_embeddings 수
    - embedding_dim = 1536 확인
    - embedding_version = openai_text_embedding_3_small_chunk_text_v1 확인

14. pgvector 검색용 index 생성
    - embedding 저장 완료 후 생성
    - HNSW 또는 IVFFlat index 검토
    - 기본 후보: vector_cosine_ops
    - 대량 embedding insert 중에는 index 생성을 미룬다.

15. pgvector baseline 검색 구현
    - PostgreSQL에 저장된 embedding_vector로 similarity 검색
    - 첫 번째 RAG retrieval baseline

16. Elasticsearch BM25 색인
    - PostgreSQL chunk_text/search_text를 Elasticsearch에 색인
    - embedding 없이 BM25/Nori 검색 실험

17. Elasticsearch vector/hybrid 색인
    - PostgreSQL chunk + embedding을 읽어 dense_vector index 생성
    - vector 검색 및 BM25+vector hybrid 검색 실험

18. retrieval A/B 테스트
    - pgvector
    - Elasticsearch BM25
    - Elasticsearch vector
    - Elasticsearch hybrid
    - analyzer, chunk 방식, embedding 모델 비교

19. 검색 API / RAG API 연결

20. 온라인 A/B 테스트 준비
```

---

## 15. 최종 요약

이번 통합으로 정리된 최종 원칙은 다음입니다.

```text
1. 첨부 ipynb는 참고 자료로만 둔다.
   txt 기반 Elasticsearch smoke test는 이번 최종 실행 계획에서 제외한다.

2. PostgreSQL 먼저 원본 적재한다.
   PostgreSQL은 source of truth이다.
   law_db와 섞지 않고 traffic_precedent_db, fault_ratio_precedent_db로 분리한다.

3. 법령 schema와 판례 schema는 분리한다.
   법령은 storage/schemas/law_db_schema.sql을 사용한다.
   판례는 storage/schemas/precedent_db_schema.sql을 사용한다.

4. 교통사고와 과실비율 데이터셋은 완전히 분리한다.
   파일, DB, 테이블, chunk, embedding job, index, eval log 모두 분리한다.

5. 현재 docker-compose에는 PostgreSQL(pgvector)이 이미 있다.
   PostgreSQL service를 새로 만들지 않고 기존 컨테이너 안에 추가 DB를 만든다.
   Elasticsearch/Kibana는 현재 compose에 없으므로 BM25/vector 실험 단계에서 추가한다.

6. Elasticsearch를 추가할 경우 내부 data volume과 실제 판례 데이터 경로를 섞지 않는다.
   실제 판례 데이터 기준 경로는 C:\dev\project\SKN27-FINAL-3Team\etl\fault_cases\artifacts\traffic_precedents_output 이다.

7. 판례 DB 적재 기준 파일은 verified 최종 산출물이다.
   교통사고: traffic_prec_reclass_verified/01_confirmed_traffic_cases.jsonl
   과실비율: traffic_prec_fault_ratio_verified/01_fault_ratio_confirmed_cases.jsonl

8. 현재 검증 기준 row count는 다음이다.
   교통사고 판례 DB 적재 대상: 3,562건
   과실비율 판례 DB 적재 대상: 973건

9. 판례 chunk는 1500/250으로 시작한다.
   ipynb의 200/50 설정은 이번 최종 실행 계획에서 사용하지 않는다.

10. retrieval A/B 테스트를 먼저 한다.
   LLM 답변 품질 평가는 그 다음 단계이다.

11. 검색 실험은 세 갈래로 나눈다.
    PostgreSQL pgvector, Elasticsearch BM25, Elasticsearch vector/hybrid를 비교한다.

12. embedding은 PostgreSQL에 먼저 저장한다.
    Elasticsearch vector/hybrid는 PostgreSQL embedding을 읽어 dense_vector로 색인한다.

13. A/B 테스트의 핵심 통제 조건은 같은 chunk와 같은 embedding이다.
    그래야 검색엔진 차이와 embedding 차이를 분리해서 판단할 수 있다.
```

---

## 16. 참고 자료 반영 메모

```text
- 기존 MD의 PostgreSQL/Elasticsearch 역할 구분은 유지
- 기존 MD의 embedding 모델 후보 및 A/B 테스트 계획은 유지
- 기존 MD의 공통 precedent_cases / precedent_chunks 구조는 비채택으로 변경
- 추가 MD의 완전 분리 구조는 최종 채택
- 첨부 ipynb의 txt 직접 적재 흐름은 비채택, 검색 방식 이해용 참고로만 유지
- 현재 docker-compose에는 PostgreSQL(pgvector)이 이미 있으므로 판례 DB만 추가 생성
- Elasticsearch/Kibana는 현재 compose에 없으므로 BM25/vector 실험 단계에서 추가
- 첨부 README의 실행/확인 명령은 로컬 환경 검증 명령으로 참고
```

---

## 최근 실행 기록: Elasticsearch BM25/Nori 색인 완료

### 목적

이 단계의 목적은 PostgreSQL에 저장된 판례 chunk를 Elasticsearch에 색인해서, pgvector 검색과 비교할 수 있는 BM25/Nori 검색 baseline을 만드는 것이다.

pgvector baseline은 PostgreSQL의 `embedding_vector`를 기준으로 의미 유사도 검색을 수행한다. 반면 Elasticsearch BM25는 embedding 없이 `chunk_text`, `search_text`에 포함된 실제 단어 일치와 빈도, 문서 길이 보정을 사용한다. 따라서 두 검색 방식은 성격이 다르며, A/B 테스트에서는 같은 chunk 집합을 대상으로 서로 다른 검색 엔진이 어떤 후보를 가져오는지 비교해야 한다.

### Nori 확인 근거

Kibana Dev Tools에서 다음 요청을 실행했다.

```http
POST /_analyze
{
  "analyzer": "nori",
  "text": "차로변경 사고 과실비율"
}
```

응답은 `200 - OK`였고, 토큰은 다음처럼 분리되었다.

```text
차
변경
사고
과실
비율
```

이 결과는 `analysis-nori` plugin이 Elasticsearch 컨테이너 안에 설치되어 있고, `nori` analyzer가 실제 API에서 인식된다는 뜻이다. 다만 `차로변경`이 `차`와 `변경`으로 나뉘는 것처럼 완벽한 도메인 토큰화는 아니다. 그래서 1차 BM25 실험에서는 Nori를 사용하되, 추후 검색 품질을 보고 사용자 사전 또는 동의어 사전을 추가할 수 있다.

### 코드 구현 위치

Elasticsearch BM25/Nori 관련 코드는 기존 pgvector 검색 코드와 같은 검색 영역에 추가했다.

```text
etl/fault_cases/src/traffic_precedents/precedent_search/
  search_config.py
  elasticsearch_client.py
  elasticsearch_indexer.py
  elasticsearch_bm25_retriever.py
  run_elasticsearch_sample_queries.py
```

각 파일의 역할은 다음과 같다.

```text
search_config.py
  - Elasticsearch host, 계정, index 이름, 결과 리포트 경로 설정

elasticsearch_client.py
  - Elasticsearch client 생성

elasticsearch_indexer.py
  - Nori analyzer 기반 index mapping 생성
  - PostgreSQL chunk 테이블에서 데이터를 읽음
  - Elasticsearch bulk API로 chunk 색인

elasticsearch_bm25_retriever.py
  - Elasticsearch BM25/Nori 검색 실행
  - bm25_score, highlight, chunk metadata 반환

run_elasticsearch_sample_queries.py
  - traffic/fault_ratio 샘플 질의 실행
  - 결과 JSON 리포트 저장
```

### 생성한 Elasticsearch index

PostgreSQL DB 분리 구조와 맞춰 Elasticsearch index도 분리했다.

```text
traffic:
  precedent_traffic_chunks_bm25_nori_v1

fault_ratio:
  precedent_fault_ratio_chunks_bm25_nori_v1
```

분리 이유는 다음과 같다.

```text
1. traffic 판례와 fault_ratio 판례는 데이터 목적이 다르다.
2. 검색 실험 결과를 데이터셋별로 따로 비교해야 한다.
3. 추후 vector/hybrid index를 추가할 때도 alias와 version 관리가 쉬워진다.
4. DBeaver/PostgreSQL에서 DB를 분리한 것과 같은 원칙을 Elasticsearch에도 유지한다.
```

### 색인 필드 설계

Elasticsearch 문서에는 다음 필드를 넣는다.

```text
dataset
case_id
chunk_id
chunk_index
chunk_type
chunk_strategy
case_name
case_number
court_name
decision_date
chunk_text
search_text
chunk_text_standard
search_text_standard
metadata
source_fields
indexed_at
index_version
```

`chunk_text`와 `search_text`를 둘 다 넣는 이유는 다음과 같다.

```text
chunk_text:
  - RAG 근거로 사용자에게 보여줄 원문 chunk
  - 검색 결과 preview와 LLM context에 사용

search_text:
  - 검색 recall을 높이기 위한 검색 전용 텍스트
  - 현재는 chunk_text와 동일하지만, 나중에 키워드/메타데이터를 조정한 검색용 텍스트로 분리 가능
```

또한 `chunk_text_standard`, `search_text_standard`를 함께 둔 이유는 다음과 같다.

```text
1. Nori analyzer 결과가 항상 최적이라고 보장할 수 없다.
2. standard analyzer 필드를 같이 두면 검색 비교와 fallback이 가능하다.
3. BM25/Nori 실험 결과가 안 좋을 때 mapping 전체를 다시 갈아엎지 않고 field boost만 조정할 수 있다.
```

### 실행 명령과 결과

smoke test는 다음 명령으로 먼저 수행했다.

```powershell
python -B -m etl.fault_cases.src.traffic_precedents.precedent_search.elasticsearch_indexer --dataset all --limit 10
```

smoke test 결과는 다음과 같았다.

```text
traffic:
  selected_chunk_count: 10
  bulk_success_count: 10
  bulk_error_count: 0
  indexed_document_count_after: 10

fault_ratio:
  selected_chunk_count: 10
  bulk_success_count: 10
  bulk_error_count: 0
  indexed_document_count_after: 10
```

이후 partial index를 지우고 전체 색인을 다시 수행했다.

```powershell
python -B -m etl.fault_cases.src.traffic_precedents.precedent_search.elasticsearch_indexer --dataset all --recreate
```

전체 색인 결과는 다음과 같다.

```text
traffic:
  elasticsearch_index: precedent_traffic_chunks_bm25_nori_v1
  selected_chunk_count: 25,952
  bulk_success_count: 25,952
  bulk_error_count: 0
  indexed_document_count_after: 25,952

fault_ratio:
  elasticsearch_index: precedent_fault_ratio_chunks_bm25_nori_v1
  selected_chunk_count: 10,833
  bulk_success_count: 10,833
  bulk_error_count: 0
  indexed_document_count_after: 10,833
```

즉, PostgreSQL chunk count와 Elasticsearch indexed document count가 일치한다.

### 샘플 검색 실행

BM25/Nori 검색 결과를 확인하기 위해 다음 명령을 실행했다.

```powershell
python -B -m etl.fault_cases.src.traffic_precedents.precedent_search.run_elasticsearch_sample_queries --dataset all --top-k 5
```

결과 파일은 다음 경로에 저장된다.

```text
etl/fault_cases/artifacts/traffic_precedents_output/elasticsearch_exports/traffic/traffic_elasticsearch_bm25_index_report.json
etl/fault_cases/artifacts/traffic_precedents_output/elasticsearch_exports/traffic/traffic_elasticsearch_bm25_sample_queries.json

etl/fault_cases/artifacts/traffic_precedents_output/elasticsearch_exports/fault_ratio/fault_ratio_elasticsearch_bm25_index_report.json
etl/fault_cases/artifacts/traffic_precedents_output/elasticsearch_exports/fault_ratio/fault_ratio_elasticsearch_bm25_sample_queries.json
```

샘플 검색 결과에는 다음 값이 들어간다.

```text
query
rank
case_id
chunk_id
chunk_type
case_name
case_number
court_name
decision_date
bm25_score
chunk_preview
highlight
```

여기서 `bm25_score`는 Elasticsearch 내부 검색 점수다. pgvector의 `cosine_similarity`와 직접 숫자 비교하면 안 된다. 두 점수는 계산 방식과 스케일이 다르기 때문이다. 나중에 A/B 비교에서는 검색기별 raw score를 그대로 비교하지 않고, 같은 query set과 같은 top_k 결과를 대상으로 별도 평가 기준을 둔다.

### 예상되는 후속 작업

이번 단계로 완료된 것은 Elasticsearch BM25/Nori baseline의 index 생성과 샘플 검색이다.

다음 단계는 다음과 같다.

```text
1. BM25/Nori 샘플 검색 결과를 눈으로 검토한다.
2. pgvector sample result와 같은 query set으로 맞춘다.
3. Elasticsearch vector index를 추가한다.
4. Elasticsearch hybrid 검색을 추가한다.
5. pgvector / BM25 / vector / hybrid 결과를 같은 포맷으로 저장한다.
6. 로컬 기성 reranker를 평가용으로만 사용해 공통 relevance score를 만든다.
```

이렇게 해야 검색 방식 비교가 명확해진다.

```text
pgvector:
  embedding 기반 의미 검색 baseline

Elasticsearch BM25/Nori:
  한국어 형태소 분석 + lexical 검색 baseline

Elasticsearch vector:
  Elasticsearch dense_vector 기반 의미 검색

Elasticsearch hybrid:
  BM25/Nori + vector 결합 검색
```

이번 BM25 단계만으로 최종 검색 품질을 판단하지 않는다. 목적은 어디까지나 비교 가능한 검색 후보군을 하나 더 만드는 것이다.

---

## 최근 의사결정: BM25 이후 후속 순서와 hybrid 설계

### 현재 완료 상태

현재 판례 RAG 검색 실험은 다음 단계까지 완료된 상태다.

```text
1. PostgreSQL 적재
2. chunk 생성
3. embedding 저장
4. pgvector baseline 검색
5. Elasticsearch BM25/Nori index 생성
6. BM25/Nori sample 검색
7. pgvector/BM25 query set 일치 확인
```

이 상태에서 `pgvector`와 `Elasticsearch BM25/Nori`는 같은 query set으로 검색 결과를 반환할 수 있다. 따라서 다음 작업은 단순히 검색기를 하나 더 만드는 것보다, 이미 만들어진 두 검색 결과를 같은 실험 단위로 정리하는 것이 우선이다.

### 왜 hybrid보다 결과 포맷 통일을 먼저 하는가

현재 이미 비교 대상은 두 개다.

```text
A. PostgreSQL pgvector
B. Elasticsearch BM25/Nori
```

하지만 두 검색 결과의 점수 이름과 구조가 서로 다르다.

```text
pgvector:
  cosine_similarity
  cosine_distance

BM25:
  bm25_score
  highlight
```

이 상태에서 바로 Elasticsearch hybrid를 구현하면 비교 대상은 세 개가 된다.

```text
A. pgvector
B. Elasticsearch BM25/Nori
C. Elasticsearch hybrid
```

그런데 결과 포맷이 통일되어 있지 않으면 각 검색 결과를 따로 해석해야 한다.

```text
pgvector 결과 따로 해석
BM25 결과 따로 해석
hybrid 결과 또 따로 해석
```

이렇게 되면 A/B 테스트가 검색기 구현보다 결과 해석에서 더 복잡해진다. 따라서 먼저 검색 결과를 공통 후보 포맷으로 정리한다.

### 공통 비교 포맷의 목적

검색 결과 포맷 통일은 검색 기능이 아니라 실험판을 정리하는 작업이다.

목적은 다음과 같다.

```text
1. 이미 만든 pgvector/BM25 결과를 비교 가능한 형태로 고정한다.
2. 이후 Elasticsearch vector/hybrid가 추가되어도 같은 포맷으로 추가할 수 있다.
3. 로컬 기성 reranker 평가도 이 통합 포맷을 입력으로 바로 사용할 수 있다.
4. 검색기별 raw score가 달라도 retriever_score/score_type으로 정리할 수 있다.
```

즉, 검색기별 점수 자체를 직접 비교하지 않고 다음처럼 보존한다.

```text
retriever_score:
  각 검색기가 반환한 원래 점수

score_type:
  그 점수가 어떤 종류인지 설명하는 값
```

예를 들어 pgvector 결과는 다음처럼 저장한다.

```json
{
  "query_id": "traffic_q001",
  "dataset": "traffic",
  "query": "차로변경 중 발생한 교통사고 판례",
  "retriever": "pgvector",
  "rank": 1,
  "case_id": "...",
  "chunk_id": "...",
  "chunk_type": "...",
  "retriever_score": 0.82,
  "score_type": "cosine_similarity",
  "chunk_preview": "..."
}
```

Elasticsearch BM25/Nori 결과도 같은 필드 구조로 저장한다.

```json
{
  "query_id": "traffic_q001",
  "dataset": "traffic",
  "query": "차로변경 중 발생한 교통사고 판례",
  "retriever": "elasticsearch_bm25_nori",
  "rank": 1,
  "case_id": "...",
  "chunk_id": "...",
  "chunk_type": "...",
  "retriever_score": 36.59,
  "score_type": "bm25_score",
  "chunk_preview": "..."
}
```

이렇게 하면 `retriever_score`의 숫자 크기는 직접 비교하지 않더라도, 검색기별 후보 결과를 같은 파일에서 볼 수 있다. 이후 reranker나 사람이 같은 기준으로 후보 품질을 평가할 수 있다.

### 다음 산출물

다음에 만들 산출물은 다음과 같은 비교용 JSONL이다.

```text
retrieval_ab_candidates.jsonl
```

권장 저장 위치는 다음과 같다.

```text
etl/fault_cases/artifacts/traffic_precedents_output/retrieval_ab_exports/
  retrieval_ab_candidates.jsonl
  retrieval_ab_summary.json
```

처음에는 `pgvector`와 `elasticsearch_bm25_nori` 결과만 넣는다. 이후 Elasticsearch vector와 hybrid가 구현되면 같은 포맷으로 계속 추가한다.

### 권장 실행 순서

BM25/Nori 완료 이후 권장 순서는 다음과 같다.

```text
1. pgvector/BM25 결과 비교용 JSONL 생성
2. Elasticsearch vector 검색 구현
3. Elasticsearch hybrid 검색 구현
4. pgvector / BM25 / ES vector / ES hybrid 결과를 같은 포맷으로 저장
5. 로컬 기성 reranker로 공통 평가 점수 산출
```

하이브리드를 먼저 구현할 수도 있다. 그러나 hybrid까지 만든 뒤에도 결국 결과 포맷 통일은 필요하다. 따라서 지금 한 번 공통 포맷을 만들어두면 이후 실험이 덜 꼬인다.

### Elasticsearch hybrid의 의미

Elasticsearch hybrid는 다음 둘을 합친 검색 방식이다.

```text
Elasticsearch hybrid
= Elasticsearch BM25/Nori
+ Elasticsearch vector
```

여기서 vector는 새로 embedding을 생성하는 것이 아니다. 이미 PostgreSQL에 저장된 embedding을 Elasticsearch에 dense_vector로 색인해서 사용한다.

현재 구조는 다음과 같다.

```text
PostgreSQL
  precedent_chunks
  precedent_chunk_embeddings  ← 이미 OpenAI embedding 저장됨

Elasticsearch
  BM25/Nori index             ← 완료됨
```

다음 vector/hybrid를 하려면 다음 순서가 필요하다.

```text
1. PostgreSQL에서 chunk + embedding_vector 조회
2. Elasticsearch index에 dense_vector 필드 추가 또는 새 vector index 생성
3. embedding_vector를 Elasticsearch dense_vector로 색인
4. Elasticsearch에서 vector kNN 검색 실행
5. BM25 결과와 vector 결과를 합쳐 hybrid 검색
```

재사용할 PostgreSQL embedding 테이블은 다음과 같다.

```text
traffic_precedent_chunk_embeddings.embedding_vector
fault_ratio_precedent_chunk_embeddings.embedding_vector
```

PostgreSQL embedding을 재사용하는 이유는 다음과 같다.

```text
1. 같은 embedding으로 pgvector와 Elasticsearch vector를 비교해야 공정하다.
2. embedding API 비용을 다시 쓰지 않는다.
3. embedding_model, embedding_dim, embedding_version 관리가 PostgreSQL에 이미 되어 있다.
4. PostgreSQL을 source of truth로 두는 원칙을 유지한다.
```

구조적으로는 다음과 같은 흐름이다.

```text
PostgreSQL chunk + embedding
        ↓
Elasticsearch dense_vector index
        ↓
Elasticsearch vector search
        ↓
Elasticsearch hybrid search
        = BM25/Nori score + vector similarity
```

따라서 다음에 만들 Elasticsearch vector indexer는 새 embedding 생성기가 아니라 PostgreSQL embedding export/indexer에 가깝다.

## 최근 실행 기록: Elasticsearch vector/hybrid 검색 구현 완료

### 목적

BM25/Nori까지만 비교하면 키워드 기반 검색 성능만 확인할 수 있다.  
현재 판례 RAG 실험의 목적은 다음 검색 방식을 같은 조건에서 비교하는 것이다.

```text
1. PostgreSQL pgvector
2. Elasticsearch BM25/Nori
3. Elasticsearch vector
4. Elasticsearch hybrid = BM25/Nori + vector
```

따라서 BM25 이후에는 PostgreSQL에 이미 저장된 embedding을 Elasticsearch에 복사 색인하고,
같은 query set과 같은 top_k로 vector/hybrid 결과를 만들어야 한다.

### 진행한 작업

`precedent_search` 폴더가 너무 평평하게 구성되어 있어 검색 방식별 역할이 헷갈렸으므로 다음과 같이 정리했다.

```text
etl/fault_cases/src/traffic_precedents/precedent_search/
  search_config.py
  sample_queries.py

  pgvector/
    create_indexes.py
    retriever.py
    run_sample_queries.py

  elasticsearch/
    client.py
    bm25_indexer.py
    bm25_retriever.py
    vector_indexer.py
    vector_retriever.py
    hybrid_retriever.py
    run_bm25_sample_queries.py
    run_vector_sample_queries.py
    run_hybrid_sample_queries.py

  evaluation/
    export_retrieval_ab_candidates.py
```

이 구조의 이유는 다음과 같다.

```text
1. pgvector, Elasticsearch, evaluation 코드를 분리해서 실행 목적을 명확히 한다.
2. BM25/vector/hybrid가 같은 sample_queries.py를 사용하게 하여 query set 불일치를 막는다.
3. 검색 결과 생성과 A/B 평가용 포맷 변환을 분리한다.
4. 이후 로컬 reranker 평가 코드를 evaluation 아래에 추가하기 쉽다.
```

### Elasticsearch vector 색인 방식

Elasticsearch vector index는 OpenAI embedding을 새로 만들지 않는다.  
이미 PostgreSQL에 저장된 embedding을 읽어 Elasticsearch `dense_vector` 필드로 색인한다.

사용한 PostgreSQL source table:

```text
traffic_precedent_chunk_embeddings.embedding_vector
fault_ratio_precedent_chunk_embeddings.embedding_vector
```

생성한 Elasticsearch vector index:

```text
precedent_traffic_chunks_vector_hybrid_v1
precedent_fault_ratio_chunks_vector_hybrid_v1
```

색인 결과:

```text
traffic:
  selected_chunk_count: 25,952
  bulk_success_count: 25,952
  bulk_error_count: 0

fault_ratio:
  selected_chunk_count: 10,833
  bulk_success_count: 10,833
  bulk_error_count: 0
```

이렇게 한 이유는 다음과 같다.

```text
1. pgvector와 Elasticsearch vector가 같은 embedding을 써야 검색엔진 차이만 비교할 수 있다.
2. embedding API 비용을 다시 쓰지 않는다.
3. embedding_model / embedding_dim / embedding_version 기준은 PostgreSQL을 source of truth로 둔다.
4. Elasticsearch는 검색 실험용 index이고, 원본 저장소 역할은 PostgreSQL이 담당한다.
```

### Hybrid 검색 방식

현재 hybrid는 다음 두 결과를 합친다.

```text
Elasticsearch BM25/Nori 결과
+ Elasticsearch vector 결과
```

단, BM25 원점수와 vector 원점수는 직접 더하지 않는다.

```text
BM25 score: 키워드 매칭 기반 점수
vector score: embedding 유사도 기반 점수
```

두 점수는 스케일과 의미가 다르므로 직접 합산하면 공정하지 않다.  
따라서 현재 hybrid는 RRF(Reciprocal Rank Fusion) 방식으로 순위를 합친다.

RRF 계산식:

```text
rrf_score = 1 / (k + rank)
hybrid_score = rrf_bm25 + rrf_vector
```

현재 baseline 값:

```text
k = 60
```

`k=60`을 사용한 이유:

```text
1. RRF에서 널리 쓰이는 기본 baseline 값이다.
2. 한 검색기의 1등 결과가 과하게 지배하지 않도록 완충한다.
3. BM25와 vector 양쪽에서 모두 상위권에 잡힌 후보를 우대한다.
4. 검색기 raw score 스케일 차이를 피하고 rank 기반으로만 융합할 수 있다.
```

예시:

```text
BM25 rank = 1, vector rank = 없음
rrf_bm25 = 1 / (60 + 1) = 0.01639
rrf_vector = 0
hybrid_score = 0.01639

BM25 rank = 15, vector rank = 1
rrf_bm25 = 1 / (60 + 15) = 0.01333
rrf_vector = 1 / (60 + 1) = 0.01639
hybrid_score = 0.02972
```

즉 BM25에서 1등만 한 후보보다, BM25와 vector 양쪽에서 함께 잡힌 후보가 hybrid에서 더 위로 올라올 수 있다.

### Hybrid 결과 컬럼 해석

Hybrid sample JSON에서 주요 컬럼은 다음 의미를 가진다.

```text
rank:
  hybrid 최종 순위

hybrid_score:
  rrf_bm25 + rrf_vector

bm25_rank:
  BM25/Nori 검색에서의 순위

bm25_score:
  BM25/Nori 원점수
  다른 검색 방식 점수와 직접 비교하지 않는다.

vector_rank:
  Elasticsearch vector 검색에서의 순위

vector_score:
  Elasticsearch dense_vector 검색 원점수
  BM25 score와 직접 비교하지 않는다.

rrf_bm25:
  bm25_rank를 RRF 공식으로 변환한 점수

rrf_vector:
  vector_rank를 RRF 공식으로 변환한 점수
```

주의할 점:

```text
1. hybrid_score는 BM25 score와 vector_score를 직접 더한 값이 아니다.
2. hybrid_score는 내부 정렬용 점수다.
3. A/B 최종 평가는 나중에 로컬 기성 reranker 또는 별도 평가 기준으로 한다.
4. k=60은 baseline이며, 필요하면 k=10, k=30, k=60을 비교 실험할 수 있다.
```

### 생성된 산출물

Elasticsearch BM25/Nori:

```text
etl/fault_cases/artifacts/traffic_precedents_output/elasticsearch_exports/traffic/
  traffic_elasticsearch_bm25_index_report.json
  traffic_elasticsearch_bm25_sample_queries.json

etl/fault_cases/artifacts/traffic_precedents_output/elasticsearch_exports/fault_ratio/
  fault_ratio_elasticsearch_bm25_index_report.json
  fault_ratio_elasticsearch_bm25_sample_queries.json
```

Elasticsearch vector:

```text
etl/fault_cases/artifacts/traffic_precedents_output/elasticsearch_exports/traffic/
  traffic_elasticsearch_vector_index_report.json
  traffic_elasticsearch_vector_sample_queries.json

etl/fault_cases/artifacts/traffic_precedents_output/elasticsearch_exports/fault_ratio/
  fault_ratio_elasticsearch_vector_index_report.json
  fault_ratio_elasticsearch_vector_sample_queries.json
```

Elasticsearch hybrid:

```text
etl/fault_cases/artifacts/traffic_precedents_output/elasticsearch_exports/traffic/
  traffic_elasticsearch_hybrid_sample_queries.json

etl/fault_cases/artifacts/traffic_precedents_output/elasticsearch_exports/fault_ratio/
  fault_ratio_elasticsearch_hybrid_sample_queries.json
```

통합 A/B 후보:

```text
etl/fault_cases/artifacts/traffic_precedents_output/retrieval_ab_exports/
  retrieval_ab_candidates.jsonl
  retrieval_ab_summary.json
```

최종 통합 결과:

```text
query_count: 6
top_k: 5
retrievers: 4

candidate_count:
  6 queries × 5 results × 4 retrievers = 120

retrievers:
  pgvector
  elasticsearch_bm25_nori
  elasticsearch_vector_cosine
  elasticsearch_hybrid_bm25_vector_rrf
```

### 현재 완료 상태

현재까지 완료된 단계는 다음과 같다.

```text
1. PostgreSQL 적재
2. chunk 생성
3. embedding 저장
4. pgvector index 생성
5. pgvector baseline 검색
6. Elasticsearch BM25/Nori index 생성
7. BM25/Nori sample 검색
8. Elasticsearch vector index 생성
9. Elasticsearch vector sample 검색
10. Elasticsearch hybrid sample 검색
11. pgvector / BM25 / vector / hybrid 결과를 같은 A/B 후보 포맷으로 통합
```

### 다음 단계

다음 단계는 검색 결과를 사람이 일일이 보는 것이 아니라, 공통 평가 기준으로 비교하는 것이다.

권장 다음 단계:

```text
1. retrieval_ab_candidates.jsonl을 입력으로 사용
2. 로컬 기성 reranker를 평가용으로만 적용
3. 검색 결과 순서는 변경하지 않고 각 후보에 relevance score만 부여
4. retriever별 avg_score@5, max_score@5, top1_score를 계산
5. pgvector / BM25 / ES vector / ES hybrid 중 어느 방식이 더 좋은 후보를 가져오는지 비교
```

중요한 원칙:

```text
reranker는 검색 개선용이 아니라 평가용으로 먼저 사용한다.
그래야 pgvector, BM25, vector, hybrid 검색 방식 자체의 차이를 분리해서 볼 수 있다.
```
