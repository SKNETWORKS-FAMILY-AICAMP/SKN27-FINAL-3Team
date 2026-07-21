# 심의사례 DB 적재 · Chunk · Embedding · 검색 평가 상세 계획

## 0. 이 문서의 목적

이 문서는 기존 **교통사고/과실비율 판례 RAG 파이프라인 계획**을 참고하되,  
그 구조를 그대로 복사하지 않고 **자동차사고 과실비율분쟁 심의사례 전용 구조**로 바꾸기 위한 계획서다.

핵심 질문은 다음이다.

```text
1. review_case_db를 어떻게 구성할 것인가?
2. 테이블은 몇 개가 필요한가?
3. 왜 최소 7개라는 말이 나왔고, 실제 운영/평가 기준은 몇 개인가?
4. 심의사례 chunk는 왜 section chunk가 정답인가?
5. section chunk가 너무 길어지면 어떻게 할 것인가?
6. 각 단계별 코드는 왜 그렇게 나누는가?
7. 그렇게 만들면 어떤 결과가 예상되는가?
8. 적재 이후 검색 품질은 어떤 기준으로 평가할 것인가?
```

---

# 1. 최종 결론

## 1.1 review_case_db도 판례 DB처럼 분리한다

현재 판례 쪽은 다음처럼 분리되어 있다.

```text
law_db
traffic_precedent_db
fault_ratio_precedent_db
```

심의사례도 같은 원칙으로 간다.

```text
review_case_db
```

DBeaver에서 최종적으로는 다음처럼 보이는 구조가 목표다.

```text
law_db
traffic_precedent_db
fault_ratio_precedent_db
review_case_db
```

---

## 1.2 심의사례는 판례 파이프라인의 뼈대만 가져온다

가져올 것:

```text
PostgreSQL-first
원본 document와 chunk 분리
chunk_text와 search_text 분리
embedding 저장
pgvector 검색 baseline
Elasticsearch BM25/Nori 검색
hybrid 검색
오프라인 평가
```

그대로 가져오면 안 되는 것:

```text
판례용 테이블명
판례용 chunk_type
1500/250 고정 window chunk 중심 구조
court_name, case_number, decision_date 중심 메타데이터
holding, summary, main_text 중심 chunk 구조
```

심의사례는 법원 판례가 아니라 **심의위원회 판단 사례**다.  
따라서 중심 키와 chunk 기준이 다르다.

```text
판례 중심 키 = case_id
심의사례 중심 키 = review_no, review_case_id
```

---

# 2. 테이블 개수 기준

## 2.1 “최소 7개”의 의미

이전에 말한 “최소 7개”는 **DB 적재와 RAG 검색을 시작하기 위한 최소 테이블 수**라는 뜻이다.  
하지만 그것만으로는 embedding job, Elasticsearch index job, 검색 평가 run까지 관리하기에는 부족하다.

따라서 기준을 명확히 나눈다.

```text
A. 최소 적재 기준 = 7개
B. 운영/평가 전체 기준 = 13개
C. 후속 온라인 서비스 기준 = 15개 이상
```

---

## 2.2 최소 적재 기준 7개

아래 7개가 있으면 현재 preprocessed 결과를 PostgreSQL에 보존하고, RAG chunk 검색을 시작할 수 있다.

```text
1. review_case_preprocess_runs
2. review_case_documents
3. review_case_source_chunks
4. review_case_chunks
5. review_case_quality_reports
6. review_case_toc_items
7. review_case_toc_case_links
```

이 7개는 다음 역할을 가진다.

| 번호 | 테이블 | 역할 |
|---:|---|---|
| 1 | review_case_preprocess_runs | 어떤 전처리 결과를 적재했는지 run 단위 기록 |
| 2 | review_case_documents | 심의번호 1건 단위 구조화 결과 |
| 3 | review_case_source_chunks | PDF 원문 추적용 chunk |
| 4 | review_case_chunks | RAG 검색용 section chunk |
| 5 | review_case_quality_reports | fatal/warning 검증 결과 |
| 6 | review_case_toc_items | 목차에서 추출한 보조 index |
| 7 | review_case_toc_case_links | 목차와 실제 사례 연결 검증 |

이 7개가 최소인 이유:

```text
documents만 있으면 검색 단위가 너무 크다.
chunks만 있으면 원문/사례 단위 추적이 약하다.
source_chunks가 없으면 파싱 오류가 생겼을 때 PDF 원문으로 돌아가기 어렵다.
quality_reports가 없으면 적재 결과가 믿을 수 있는지 판단하기 어렵다.
toc는 정답 분류가 아니라 보조 검증이므로 별도 테이블로 분리해야 한다.
preprocess_runs가 없으면 나중에 preprocessed(9), preprocessed(10) 같은 실행 결과를 비교할 수 없다.
```

---

## 2.3 운영/평가 전체 기준 13개

현재 목표가 단순 적재가 아니라 **embedding, Elasticsearch, 검색 평가까지 포함**이라면 13개가 맞다.

```text
1. review_case_preprocess_runs
2. review_case_documents
3. review_case_source_chunks
4. review_case_chunks
5. review_case_quality_reports
6. review_case_toc_items
7. review_case_toc_case_links
8. review_case_chunk_embeddings
9. review_case_embedding_jobs
10. review_case_elasticsearch_index_jobs
11. review_case_search_eval_queries
12. review_case_search_eval_runs
13. review_case_search_eval_results
```

추가 6개가 필요한 이유:

| 번호 | 테이블 | 필요한 이유 |
|---:|---|---|
| 8 | review_case_chunk_embeddings | 같은 chunk에 대해 embedding vector 저장 |
| 9 | review_case_embedding_jobs | embedding 생성 성공/실패/모델/버전 관리 |
| 10 | review_case_elasticsearch_index_jobs | ES 색인 버전, 문서 수, 실패 내역 관리 |
| 11 | review_case_search_eval_queries | 테스트 질문과 기대 정답 관리 |
| 12 | review_case_search_eval_runs | 어떤 검색 설정으로 평가했는지 run 단위 기록 |
| 13 | review_case_search_eval_results | query별 top-k 검색 결과와 평가 점수 저장 |

결론:

```text
최소 7개 = 전처리 결과 적재와 추적을 위한 최소 구조
최종 13개 = embedding, index, 검색 평가까지 포함한 운영/실험 기준 구조
```

이 문서의 최종 기준은 **13개 테이블**이다.

---

## 2.4 후속 온라인 서비스 기준

실제 사용자 로그까지 쌓기 시작하면 아래 테이블을 추가한다.

```text
14. review_case_search_api_logs
15. review_case_user_feedback_logs
```

이 2개는 지금 당장 필수는 아니다.

```text
오프라인 평가 단계 = 13개까지
온라인 서비스 로그 단계 = 15개 이상
```

---

# 3. review_case_db 테이블 상세 설계

## 3.1 review_case_preprocess_runs

### 역할

전처리 산출물을 어떤 버전으로 DB에 적재했는지 기록한다.

### 필요한 이유

preprocessed(9), preprocessed(10)처럼 산출물이 계속 바뀔 수 있다.  
run 정보를 남기지 않으면 나중에 어느 결과가 DB에 들어갔는지 알기 어렵다.

### 주요 컬럼

```sql
CREATE TABLE review_case_preprocess_runs (
    run_id TEXT PRIMARY KEY,
    source_pdf_name TEXT,
    source_pdf_path TEXT,
    preprocessed_zip_name TEXT,
    preprocessed_artifact_path TEXT,
    document_count INTEGER,
    source_chunk_count INTEGER,
    rag_chunk_count INTEGER,
    quality_report_count INTEGER,
    toc_item_count INTEGER,
    toc_case_link_count INTEGER,
    valid_document_count INTEGER,
    fatal_flag_counts JSONB,
    warning_flag_counts JSONB,
    loader_report JSONB,
    page_coverage JSONB,
    preprocessing_summary JSONB,
    created_at TIMESTAMP DEFAULT now()
);
```

### 예상 결과

현재 preprocessed(9) 기준이라면 다음 값이 들어갈 것으로 예상한다.

```text
document_count = 226
source_chunk_count = 285
rag_chunk_count = 904
quality_report_count = 226
toc_item_count = 226
toc_case_link_count = 226
valid_document_count = 226
fatal_flag_counts = {}
warning_flag_counts = {}
header_road_context_null_count = 116  # 원문에 명시적 ` - ` 맥락 구간이 없는 정상 선택값
```

---

## 3.2 review_case_documents

### 역할

심의사례 1건 단위의 구조화 결과를 저장한다.

### 중심 키

```text
review_case_id
review_no
```

### 주요 컬럼

```sql
CREATE TABLE review_case_documents (
    review_case_id TEXT PRIMARY KEY,
    review_no TEXT UNIQUE NOT NULL,
    run_id TEXT REFERENCES review_case_preprocess_runs(run_id),

    party_type TEXT,
    header_title_raw TEXT,
    header_accident_group TEXT,
    header_road_context TEXT,
    header_parse_method TEXT,

    case_title TEXT,
    case_condition TEXT,
    fault_type TEXT,

    reference_chart_key TEXT,
    reference_chart_no TEXT,
    reference_chart_sub_no TEXT,

    standard_scenario_raw TEXT,
    standard_scenario_keywords JSONB,
    signal_condition TEXT,
    road_feature TEXT,
    standard_a_behavior TEXT,
    standard_b_behavior TEXT,

    decision_fault_ratio TEXT,
    a_role TEXT,
    b_role TEXT,
    a_ratio INTEGER,
    b_ratio INTEGER,
    claimant_final_ratio INTEGER,
    respondent_final_ratio INTEGER,
    claimant_standard_behavior TEXT,
    respondent_standard_behavior TEXT,

    accident_content TEXT,
    reference_standard_no TEXT,
    reference_standard_text TEXT,
    base_fault_ratio_text TEXT,

    claimant_argument TEXT,
    respondent_argument TEXT,
    evidence_text TEXT,
    main_issue TEXT,
    decision_basis TEXT,
    decision_reason TEXT,
    final_ratio_text TEXT,

    pdf_page_start INTEGER,
    pdf_page_end INTEGER,
    book_page_start INTEGER,
    book_page_end INTEGER,

    source_type TEXT DEFAULT 'review_case',
    source_reliability_score INTEGER DEFAULT 3,
    parse_status TEXT,
    quality_flags JSONB,
    warning_flags JSONB,
    raw_json JSONB,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);
```

### 왜 이렇게 설계하는가

심의사례는 법원 판례가 아니라 심의번호 기준의 판단 사례다.  
따라서 사건번호, 법원명, 선고일보다 아래 정보가 중요하다.

```text
상단 사고 분류
상단 기준 박스
심의번호
결정비율
사고내용
청구인/피청구인 주장
입증자료
쟁점
결정근거
결정이유
```

### 예상 결과

```text
row 수 = 226
review_no = 226/226
reference_chart_key = 226/226
decision_fault_ratio = 226/226
claimant_argument/respondent_argument = 226/226
decision_basis/decision_reason = 226/226
parse_status = valid 226건
```

---

## 3.3 review_case_source_chunks

### 역할

PDF 원문 추적용 chunk를 저장한다.

### 주요 컬럼

```sql
CREATE TABLE review_case_source_chunks (
    source_chunk_id TEXT PRIMARY KEY,
    review_case_id TEXT REFERENCES review_case_documents(review_case_id),
    review_no TEXT,
    run_id TEXT REFERENCES review_case_preprocess_runs(run_id),
    sequence_no INTEGER,
    chunk_text TEXT,
    clean_text TEXT,
    pdf_page_start INTEGER,
    pdf_page_end INTEGER,
    book_page_start INTEGER,
    book_page_end INTEGER,
    char_count INTEGER,
    raw_json JSONB,
    created_at TIMESTAMP DEFAULT now()
);
```

### 왜 필요한가

RAG 검색용 chunk와 다르다.

```text
source_chunk = 원문 추적/검증용
review_case_chunk = 검색/RAG용
```

파싱 결과가 이상할 때 source_chunk로 돌아가서 원문을 확인한다.

### 예상 결과

현재 preprocessed(9) 기준:

```text
row 수 = 285
일부 사례는 1개 source_chunk
일부 사례는 2개 이상 source_chunk
```

---

## 3.4 review_case_chunks

### 역할

RAG 검색용 section chunk를 저장한다.

### 주요 컬럼

```sql
CREATE TABLE review_case_chunks (
    chunk_id TEXT PRIMARY KEY,
    review_case_id TEXT REFERENCES review_case_documents(review_case_id),
    review_no TEXT,
    run_id TEXT REFERENCES review_case_preprocess_runs(run_id),

    chunk_type TEXT,
    parent_chunk_id TEXT,
    part_index INTEGER DEFAULT 0,
    sequence_no INTEGER,

    chunk_text TEXT NOT NULL,
    search_text TEXT,
    char_count INTEGER,
    token_count INTEGER,

    party_type TEXT,
    case_title TEXT,
    reference_chart_key TEXT,
    standard_scenario_keywords JSONB,
    decision_fault_ratio TEXT,
    claimant_final_ratio INTEGER,
    respondent_final_ratio INTEGER,

    embedding_status TEXT DEFAULT 'pending',
    indexed_to_elasticsearch BOOLEAN DEFAULT false,

    parse_status TEXT,
    quality_flags JSONB,
    raw_json JSONB,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);
```

### chunk_text와 search_text 분리

```text
chunk_text:
  - LLM 답변 근거로 사용할 텍스트
  - PDF에서 뽑은 실제 문장을 최대한 보존
  - embedding 기본 입력

search_text:
  - 검색 성능을 높이기 위한 텍스트
  - 사고유형, 도표번호, 키워드, 과실비율 등을 보강
  - BM25/Nori 검색에 사용
```

예시:

```text
chunk_text:
결정근거: 교통사고사실확인원에 피청구차량의 신호위반으로 기재되어 있고...
결정이유: 신호기 있는 사거리 교차로에서 피청구차량이 적색신호에 직진하였으므로...

search_text:
차대차 직진 대 직진 사고
사거리 교차로
한쪽 차량 신호위반 사고
신호등 있음
사거리
녹색 직진
적색 직진
참고기준 201
청구차량 0%
피청구차량 100%
결정근거: ...
결정이유: ...
```

### 예상 결과

현재 preprocessed(9) 기준:

```text
총 chunk = 904
case_overview = 226
arguments = 226
evidence_issue = 226
decision = 226
```

---

## 3.5 review_case_quality_reports

### 역할

문서별 전처리 검증 결과를 저장한다.

### 주요 컬럼

```sql
CREATE TABLE review_case_quality_reports (
    quality_report_id TEXT PRIMARY KEY,
    review_case_id TEXT REFERENCES review_case_documents(review_case_id),
    review_no TEXT,
    run_id TEXT REFERENCES review_case_preprocess_runs(run_id),
    parse_status TEXT,
    fatal_flags JSONB,
    warning_flags JSONB,
    quality_flags JSONB,
    missing_required_fields JSONB,
    memo TEXT,
    raw_json JSONB,
    created_at TIMESTAMP DEFAULT now()
);
```

### 예상 결과

현재 기준:

```text
row 수 = 226
parse_status = valid 226건
fatal = 0건
warning = 0건
header_road_context null = 116건(정상 선택값)
```

---

## 3.6 review_case_toc_items

### 역할

목차에서 추출한 도표/사례 index를 저장한다.

### 주요 컬럼

```sql
CREATE TABLE review_case_toc_items (
    toc_item_id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES review_case_preprocess_runs(run_id),
    toc_order INTEGER,
    reference_chart_key TEXT,
    toc_title TEXT,
    toc_large_category TEXT,
    toc_middle_category TEXT,
    book_page_start INTEGER,
    book_page_end INTEGER,
    raw_text TEXT,
    raw_json JSONB,
    created_at TIMESTAMP DEFAULT now()
);
```

### 주의

목차는 정답 사고분류가 아니다.

```text
목차 = 보조 인덱스
본문 상단 기준 박스 = 정답 구조화 기준
```

---

## 3.7 review_case_toc_case_links

### 역할

목차와 실제 심의사례 document의 연결 검증 결과를 저장한다.

### 주요 컬럼

```sql
CREATE TABLE review_case_toc_case_links (
    toc_case_link_id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES review_case_preprocess_runs(run_id),
    toc_item_id TEXT REFERENCES review_case_toc_items(toc_item_id),
    review_case_id TEXT REFERENCES review_case_documents(review_case_id),
    review_no TEXT,
    reference_chart_key TEXT,
    link_method TEXT,
    match_status TEXT,
    mismatch_reason TEXT,
    raw_json JSONB,
    created_at TIMESTAMP DEFAULT now()
);
```

---

## 3.8 review_case_chunk_embeddings

### 역할

chunk embedding vector를 저장한다.

### 주요 컬럼

```sql
CREATE TABLE review_case_chunk_embeddings (
    chunk_id TEXT REFERENCES review_case_chunks(chunk_id) ON DELETE CASCADE,
    embedding_model TEXT NOT NULL,
    embedding_version TEXT NOT NULL,
    embedding_dim INTEGER NOT NULL,
    embedding_provider TEXT,
    input_field TEXT DEFAULT 'chunk_text',
    embedding_vector VECTOR,
    embedding_meta JSONB,
    created_at TIMESTAMP DEFAULT now(),
    PRIMARY KEY (chunk_id, embedding_model, embedding_version)
);
```

### 왜 PostgreSQL에도 embedding을 저장하는가

```text
1. Elasticsearch index를 다시 만들어도 embedding API를 다시 호출하지 않기 위해
2. pgvector 검색과 Elasticsearch vector 검색을 같은 embedding으로 비교하기 위해
3. embedding_model/version별 A/B 테스트를 추적하기 위해
4. chunk_text가 바뀌었는지 text_hash로 검증하기 위해
```

### 초기 권장

```text
embedding_model = text-embedding-3-small
embedding_version = openai_text_embedding_3_small_chunk_text_v1
input_field = chunk_text
```

---

## 3.9 review_case_embedding_jobs

### 역할

embedding 생성 작업 이력을 저장한다.

```sql
CREATE TABLE review_case_embedding_jobs (
    embedding_job_id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES review_case_preprocess_runs(run_id),
    embedding_model TEXT,
    embedding_version TEXT,
    embedding_dim INTEGER,
    input_field TEXT,
    target_chunk_count INTEGER,
    success_count INTEGER,
    failed_count INTEGER,
    skipped_count INTEGER,
    status TEXT,
    error_summary JSONB,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT now()
);
```

---

## 3.10 review_case_elasticsearch_index_jobs

### 역할

Elasticsearch index 생성 및 색인 작업 이력을 저장한다.

```sql
CREATE TABLE review_case_elasticsearch_index_jobs (
    index_job_id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES review_case_preprocess_runs(run_id),
    index_name TEXT,
    alias_name TEXT,
    index_mode TEXT,
    analyzer TEXT,
    embedding_model TEXT,
    embedding_version TEXT,
    target_chunk_count INTEGER,
    indexed_chunk_count INTEGER,
    failed_count INTEGER,
    status TEXT,
    error_summary JSONB,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT now()
);
```

---

## 3.11 review_case_search_eval_queries

### 역할

검색 평가용 질문과 기대값을 저장한다.

```sql
CREATE TABLE review_case_search_eval_queries (
    query_id TEXT PRIMARY KEY,
    query_text TEXT NOT NULL,
    query_type TEXT,
    expected_review_no TEXT,
    expected_reference_chart_key TEXT,
    expected_case_title TEXT,
    expected_keywords JSONB,
    expected_party_type TEXT,
    expected_fault_ratio TEXT,
    expected_chunk_types JSONB,
    difficulty TEXT,
    memo TEXT,
    created_at TIMESTAMP DEFAULT now()
);
```

---

## 3.12 review_case_search_eval_runs

### 역할

어떤 검색 설정으로 평가했는지 run 단위로 기록한다.

```sql
CREATE TABLE review_case_search_eval_runs (
    eval_run_id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES review_case_preprocess_runs(run_id),
    retriever TEXT,
    search_mode TEXT,
    index_name TEXT,
    embedding_model TEXT,
    embedding_version TEXT,
    top_k INTEGER,
    candidate_k INTEGER,
    query_count INTEGER,
    metric_summary JSONB,
    status TEXT,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT now()
);
```

---

## 3.13 review_case_search_eval_results

### 역할

검색 평가 결과를 저장한다.

```sql
CREATE TABLE review_case_search_eval_results (
    eval_result_id TEXT PRIMARY KEY,
    eval_run_id TEXT REFERENCES review_case_search_eval_runs(eval_run_id),
    query_id TEXT REFERENCES review_case_search_eval_queries(query_id),
    retriever TEXT,
    rank INTEGER,
    chunk_id TEXT REFERENCES review_case_chunks(chunk_id),
    review_case_id TEXT REFERENCES review_case_documents(review_case_id),
    review_no TEXT,
    chunk_type TEXT,
    retriever_score DOUBLE PRECISION,
    reranker_score DOUBLE PRECISION,
    expected_review_no_hit BOOLEAN,
    expected_chart_key_hit BOOLEAN,
    expected_chunk_type_hit BOOLEAN,
    expected_keyword_coverage DOUBLE PRECISION,
    ratio_match BOOLEAN,
    noise_flag BOOLEAN,
    manual_grade INTEGER,
    memo TEXT,
    raw_result JSONB,
    created_at TIMESTAMP DEFAULT now()
);
```

---

# 4. 심의사례 chunk 전략

## 4.1 A계획: section chunk를 기본으로 한다

심의사례는 section chunk가 기본이다.

```text
case_overview
arguments
evidence_issue
decision
```

## 4.2 section chunk를 기본으로 정한 근거

### 근거 1. 심의사례 PDF 자체가 section 구조다

심의사례 1건은 이미 아래 구조로 나뉜다.

```text
상단 사고 분류
상단 기준 박스
사례 개요
참고 인정기준
주장 내용
입증 자료
주요 쟁점
결정 근거
결정 이유
```

따라서 판례처럼 일정 글자 수로 자르는 것보다, PDF의 의미 단위를 그대로 chunk로 쓰는 것이 더 자연스럽다.

### 근거 2. 현재 산출물에서 chunk 길이가 짧다

현재 preprocessed(9) 기준 chunk 길이는 다음 수준이다.

| chunk_type | 개수 | 최소 | 최대 | 평균 | p95 |
|---|---:|---:|---:|---:|---:|
| case_overview | 226 | 약 209자 | 약 453자 | 약 278자 | 약 325자 |
| arguments | 226 | 약 177자 | 약 426자 | 약 281자 | 약 356자 |
| evidence_issue | 226 | 약 125자 | 약 308자 | 약 218자 | 약 274자 |
| decision | 226 | 약 303자 | 약 915자 | 약 638자 | 약 848자 |

즉, 현재는 1500자를 넘는 chunk가 없다.  
따라서 고정 길이 split이 필요하지 않다.

### 근거 3. section chunk가 검색 의도를 가장 잘 반영한다

사용자 질문은 크게 네 가지로 나뉜다.

```text
사고상황이 비슷한 사례 찾기
양측 주장이 비슷한 사례 찾기
증거/쟁점이 비슷한 사례 찾기
결정근거/결정이유가 비슷한 사례 찾기
```

이 네 가지가 그대로 chunk_type과 대응된다.

| 사용자 질문 의도 | 검색해야 할 chunk_type |
|---|---|
| 사고상황 | case_overview |
| 주장 | arguments |
| 증거/쟁점 | evidence_issue |
| 판단 이유 | decision |

---

## 4.3 section chunk 구성

### case_overview

포함 필드:

```text
review_no
party_type
header_accident_group
header_road_context
case_title
fault_type
reference_chart_key
standard_scenario_keywords
signal_condition
road_feature
standard_a_behavior
standard_b_behavior
decision_fault_ratio
accident_content
```

예상 텍스트:

```text
[심의번호] 2018-051544
[사고분류] 차대차 / 직진 대 직진 사고 / 사거리 교차로
[사례명] 한쪽 차량 신호위반 사고
[참고기준] 201
[기준상황] 신호등 있음, 사거리, 녹색 직진, 적색 직진
[결정비율] A(청구):B(피청구)=0:100
[사고내용] 신호기 있는 사거리 교차로에서 ...
```

예상 길이:

```text
약 250~500자
```

---

### arguments

포함 필드:

```text
claimant_argument
respondent_argument
claimant_final_ratio
respondent_final_ratio
```

예상 텍스트:

```text
[청구인 주장]
청구차량은 녹색신호에 교차로를 직진으로 통과 중이었고...

[피청구인 주장]
피청구차량은 적색신호가 아닌 황색신호에 진입하였고...
```

예상 길이:

```text
약 200~500자
```

---

### evidence_issue

포함 필드:

```text
evidence_text
main_issue
```

예상 텍스트:

```text
[입증자료]
교통사고사실확인원, 차량 파손 사진, 블랙박스 영상

[주요쟁점]
피청구차량이 적색신호에 교차로를 진입하였는지 여부
```

예상 길이:

```text
약 150~350자
```

---

### decision

포함 필드:

```text
decision_basis
decision_reason
final_ratio_text
decision_fault_ratio
```

예상 텍스트:

```text
[결정근거]
교통사고사실확인원에 피청구차량의 신호위반으로 기재되어 있고...

[결정이유]
신호기 있는 사거리 교차로에서 피청구차량이 적색신호에 직진하였으므로...

[최종비율]
청구차량 0% / 피청구차량 100%
```

예상 길이:

```text
약 300~1000자
```

---

# 5. B계획: section chunk가 너무 길 때

## 5.1 왜 B계획이 필요한가

현재는 section chunk가 짧지만, 나중에 다른 심의사례 PDF나 추가 사례집이 들어오면 section이 길어질 수 있다.

따라서 기본은 section chunk지만, 길어졌을 때의 fallback 기준이 필요하다.

---

## 5.2 길이 기준

```text
0~1200자:
  그대로 유지

1201~1800자:
  warning만 남기고 그대로 유지 가능

1801자 이상:
  section 내부 구조 기준으로 split

2500자 이상:
  강제 split + quality warning
```

이 기준을 잡은 이유:

```text
현재 최대 decision chunk가 약 915자이므로 1200자는 정상 범위를 조금 넘는 warning 기준이다.
1800자는 심의사례 section chunk로는 꽤 긴 편이므로 실제 split 기준으로 둔다.
2500자는 embedding/RAG context에서 과도하게 긴 chunk로 보고 강제 split한다.
```

---

## 5.3 split 우선순위

고정 글자 수로 바로 자르지 않는다.  
section 내부 의미를 먼저 본다.

```text
1순위: subsection split
2순위: 문장 단위 split
3순위: 글자 수 window split
```

### arguments split

arguments가 길면 먼저 청구인/피청구인으로 분리한다.

```text
arguments_claimant
arguments_respondent
```

그래도 길면 문장 단위로 나눈다.

### evidence_issue split

evidence_issue가 길면 입증자료와 주요쟁점을 나눈다.

```text
evidence
issue
```

### decision split

decision이 길면 결정근거와 결정이유를 나눈다.

```text
decision_basis
decision_reason
```

그래도 길면 문장 단위로 나눈다.

### case_overview split

case_overview는 원칙적으로 split하지 않는다.  
너무 길면 search_text에서 보조 키워드를 줄이고, chunk_text는 핵심 정보만 남긴다.

---

## 5.4 split 결과 컬럼 처리

split이 발생해도 원래 section과의 관계를 잃으면 안 된다.

```text
parent_chunk_id
part_index
chunk_type
```

예시:

```text
원본:
review_case_2018_051544_decision

분리 후:
review_case_2018_051544_decision_basis
review_case_2018_051544_decision_reason
```

또는:

```text
review_case_2018_051544_decision_part_1
review_case_2018_051544_decision_part_2
```

---

## 5.5 예상 결과

현재 데이터 기준:

```text
split 발생 예상 = 0건
총 chunk = 904건 유지
```

향후 긴 사례집 추가 시:

```text
총 chunk = 904건보다 증가 가능
예상 범위 = 904~1,100건
```

정상 목표:

```text
모든 chunk_text 1800자 이하
decision 계열 chunk도 1200자 내외 유지
case_overview는 500자 내외 유지
```

---

# 6. search_text 설계

## 6.1 search_text가 필요한 이유

사용자는 PDF 원문 표현 그대로 검색하지 않는다.

예를 들어 PDF에는 `진로변경`이라고 되어 있는데 사용자는 `차로변경`이라고 검색할 수 있다.  
또 PDF에는 `피청구차량`이라고 되어 있는데 사용자는 `상대방 차량`이라고 말할 수 있다.

따라서 검색용 텍스트에는 보조 키워드를 추가한다.

---

## 6.2 search_text 생성 기준

### 모든 chunk 공통 prefix

```text
[심의번호]
[사고분류]
[사례명]
[참고기준]
[기준상황]
[결정비율]
```

### case_overview search_text

```text
상단 사고 분류
상단 기준 박스 키워드
사고내용
결정비율
동의어 보조어
```

### arguments search_text

```text
청구인 주장
피청구인 주장
청구/피청구 역할 표현
상대방, 내 차량, 청구차량, 피청구차량 보조어
```

### evidence_issue search_text

```text
입증자료
주요쟁점
교통사고사실확인원
블랙박스
차량 파손 사진
신호위반 여부
선진입 여부
```

### decision search_text

```text
결정근거
결정이유
최종 과실비율
100대0, 80대20 등 숫자형 표현
```

---

## 6.3 예상 효과

```text
BM25/Nori 검색에서 회수율 증가
사용자 자연어와 PDF 원문 표현 차이 보완
LLM 근거 텍스트인 chunk_text는 오염시키지 않음
```

---

# 7. 코드 작성 계획

## 7.1 코드 구조

현재 review_case 전처리는 이미 존재하므로, DB 적재/검색 쪽은 별도 모듈로 분리한다.

권장 구조:

```text
etl/fault_cases/src/review_case/
├── db/
│   ├── __init__.py
│   ├── config.py
│   ├── connection.py
│   ├── schema_manager.py
│   ├── load_preprocessed.py
│   ├── load_documents.py
│   ├── load_source_chunks.py
│   ├── load_chunks.py
│   ├── load_quality_reports.py
│   ├── load_toc.py
│   ├── search_text_builder.py
│   └── run_db_load.py
│
├── embedding/
│   ├── __init__.py
│   ├── embedding_config.py
│   ├── embedding_client.py
│   ├── embedding_jobs.py
│   ├── embed_chunks.py
│   └── run_embedding.py
│
├── search/
│   ├── __init__.py
│   ├── pgvector_search.py
│   ├── elasticsearch_indexer.py
│   ├── elasticsearch_search.py
│   ├── hybrid_search.py
│   └── search_schemas.py
│
└── eval/
    ├── __init__.py
    ├── eval_query_loader.py
    ├── eval_runner.py
    ├── metrics.py
    ├── result_writer.py
    └── report_builder.py
```

schema 파일:

```text
storage/schemas/review_case_db_schema.sql
```

---

## 7.2 왜 코드를 이렇게 나누는가

| 모듈 | 나누는 이유 |
|---|---|
| db/ | 전처리 JSONL을 PostgreSQL에 넣는 책임만 담당 |
| embedding/ | embedding API 호출과 vector 저장을 분리 |
| search/ | pgvector, Elasticsearch, hybrid 검색을 독립 비교 |
| eval/ | 검색 품질 평가를 검색 로직과 분리 |
| schema_manager.py | DB 생성/테이블 생성/extension 적용을 한 곳에서 관리 |
| search_text_builder.py | 검색용 텍스트 생성 규칙을 DB load와 분리 |
| embedding_jobs.py | embedding 재실행/실패 복구를 위해 job 관리 |
| eval_runner.py | 같은 query set으로 여러 retriever를 공정하게 비교 |

이렇게 나눠야 하는 이유:

```text
1. DB 적재 오류와 embedding 오류를 분리해서 볼 수 있다.
2. chunk 구조를 바꾸지 않고 검색 방식만 바꿔 테스트할 수 있다.
3. embedding 모델을 바꿔도 DB 적재 코드는 그대로 둔다.
4. Elasticsearch를 붙이지 않아도 pgvector baseline을 먼저 확인할 수 있다.
5. 검색 평가 기준을 코드에 하드코딩하지 않고 eval query 테이블로 관리할 수 있다.
```

---

## 7.2.1 각 모듈에 들어갈 코드의 구체적 역할

아래는 구현할 때 실제로 어떤 함수나 책임이 들어가야 하는지에 대한 구체적인 기준이다.

### db/config.py

```text
- 환경변수에서 DB 접속 정보 읽기
- review_case_db 이름, host, user, password, port를 관리
- schema 파일 경로와 artifact 경로를 설정
```

### db/connection.py

```text
- psycopg 연결 생성
- connection pool 또는 단일 connection wrapper 제공
- insert/upsert/select 실행 헬퍼 함수 제공
- 트랜잭션 실패 시 rollback 처리
```

### db/schema_manager.py

```text
- create_database()
- create_extension("vector")
- apply_schema(sql_file)
- create_indexes()
- 기존 테이블이 있으면 skip 또는 replace 처리
```

### db/load_preprocessed.py

```text
- preprocessing_summary.json을 읽어 run metadata를 만든다.
- preprocessed 디렉터리에서 JSONL 파일 목록을 찾는다.
- 각 JSONL을 파싱해 적재 함수로 넘긴다.
```

### db/load_documents.py

```text
- review_case_documents.jsonl의 row를 review_case_documents 테이블에 upsert한다.
- review_case_id / review_no 기준으로 중복 처리한다.
- parse_status, quality_flags, warning_flags를 반영한다.
```

### db/load_source_chunks.py

```text
- source chunk JSONL을 읽어 review_case_source_chunks에 적재한다.
- sequence_no, pdf_page_start/end, book_page_start/end를 저장한다.
```

### db/load_chunks.py

```text
- review_case_chunks.jsonl을 읽어 chunk 단위로 적재한다.
- chunk_type, part_index, parent_chunk_id를 함께 저장한다.
- embedding_status, indexed_to_elasticsearch 기본값을 세팅한다.
```

### db/load_quality_reports.py

```text
- quality_report.jsonl을 읽어 review_case_quality_reports에 적재한다.
- fatal_flags / warning_flags / missing_required_fields를 JSONB로 저장한다.
```

### db/load_toc.py

```text
- toc jsonl과 toc_case_links jsonl을 읽어 테이블에 적재한다.
- 목차와 실제 사례 연결의 match_status를 기록한다.
```

### db/search_text_builder.py

```text
- chunk_type별로 search_text를 생성한다.
- chunk_text와 search_text를 분리한다.
- 사고유형, 도표번호, 키워드, 결정비율 등을 search_text에 반영한다.
```

### db/run_db_load.py

```text
- 위 모든 load 함수를 순차적으로 실행하는 CLI 엔트리포인트다.
- --preprocessed-dir 인자를 받아 전체 적재 흐름을 실행한다.
```

### embedding/embedding_config.py

```text
- embedding 모델명, 차원, provider, batch size를 관리한다.
- 모델 버전과 input_field를 설정한다.
```

### embedding/embedding_client.py

```text
- OpenAI 또는 다른 임베딩 API 호출을 담당한다.
- timeout, retry, batch 처리 로직을 포함한다.
- 실패 시 예외를 반환하고 로그를 남긴다.
```

### embedding/embedding_jobs.py

```text
- embedding_job row를 생성한다.
- 성공/실패/스킵 건수를 기록한다.
- 재실행 시 pending 또는 failed 상태의 chunk만 다시 처리한다.
```

### embedding/embed_chunks.py

```text
- review_case_chunks에서 embedding이 필요한 chunk를 조회한다.
- chunk_text를 embedding_client로 보내고 review_case_chunk_embeddings에 저장한다.
- embedding_status를 done/failed로 업데이트한다.
```

### embedding/run_embedding.py

```text
- CLI로 실행되는 embedding 엔트리포인트다.
- --model, --input-field, --version 같은 인자를 받는다.
```

### search/pgvector_search.py

```text
- pgvector 기반 cosine similarity 검색을 수행한다.
- SQL 쿼리로 review_case_chunk_embeddings와 review_case_chunks를 조인한다.
- top-k 결과를 반환한다.
```

### search/elasticsearch_indexer.py

```text
- Elasticsearch index를 생성한다.
- search_text, chunk_text, metadata를 bulk로 색인한다.
- index_job 기록을 남긴다.
```

### search/elasticsearch_search.py

```text
- Elasticsearch 쿼리를 실행한다.
- BM25/Nori 또는 vector 검색을 분리해 테스트할 수 있도록 만든다.
```

### search/hybrid_search.py

```text
- pgvector 결과와 BM25 결과를 합친다.
- score normalization과 weighted sum을 계산한다.
- 최종 top-k를 반환한다.
```

### search/search_schemas.py

```text
- 검색 결과 DTO, score schema, query request/response 타입을 정의한다.
- 검색 결과를 eval 단계로 넘길 때 공통 포맷을 사용한다.
```

### eval/eval_query_loader.py

```text
- eval query를 DB 또는 JSON 파일에서 읽어온다.
- expected_review_no, expected_reference_chart_key, expected_keywords를 파싱한다.
```

### eval/eval_runner.py

```text
- pgvector / BM25 / hybrid 각 retriever로 동일한 query를 실행한다.
- 검색 결과와 정답 기준을 비교해 점수를 계산한다.
```

### eval/metrics.py

```text
- hit@k, MRR, keyword coverage, ratio_match, noise_count 같은 지표를 계산한다.
- manual grade 기준을 지원한다.
```

### eval/result_writer.py

```text
- eval 결과를 CSV/JSON/Markdown으로 export한다.
- report_builder.py에서 읽을 수 있는 구조로 정리한다.
```

### eval/report_builder.py

```text
- retriever별 성능 요약을 만든다.
- 어떤 query 유형에서 어떤 검색 방식이 좋은지 정리한다.
- 이후 팀 공유용 보고서로 출력한다.
```

---

## 7.3 현재 구현에서 부족한 부분

지금까지의 전처리 산출물은 이미 상당 부분 준비되어 있으나, 실제 RAG 운영 단계로 넘어가기 위해서는 아래 부분이 아직 비어 있다.

### 7.3.1 DB 적재 파이프라인이 없다

현재 존재하는 것은 주로 JSONL 산출물이고, 이 산출물을 PostgreSQL에 넣는 로더가 없다.

```text
필요한 것
- review_case_db 생성
- schema 적용
- preprocessed JSONL → 테이블 적재
- run_id 기반 재실행 가능성
```

### 7.3.2 chunk 생성/검색 텍스트 생성 규칙이 코드로 고정되지 않았다

현재는 chunk 구조 자체는 정리되어 있어도, 실제로 어떤 필드를 search_text에 넣을지, 어떤 chunk_type을 만드는지에 대한 코드 규칙이 없다.

```text
필요한 것
- chunk_type별 생성 규칙 정의
- search_text 생성 로직 분리
- chunk_text/search_text 차이 명시
```

### 7.3.3 embedding/검색 평가 흐름이 연결되지 않았다

embedding 생성, pgvector 검색, Elasticsearch 색인, eval 결과 저장까지 한 번에 연결된 실행 흐름이 없다.

```text
필요한 것
- embedding job 기록
- vector 저장
- search eval query 세트 관리
- retriever 결과 저장 및 비교
```

### 7.3.4 평가 기준이 아직 코드화되지 않았다

문서상으로는 평가 지표가 정리되어 있지만, 실제로는 query set, 정답 기준, 점수 계산, 결과 리포트 생성 코드가 필요하다.

```text
필요한 것
- query seed 파일 또는 DB 테이블
- expected_review_no / expected_chart_key 기준
- manual grade 또는 자동 metric 계산
- 결과 CSV/Markdown 리포트 출력
```

### 7.3.5 구현 우선순위가 불명확하다

이 문서의 핵심은 “완벽한 구조”보다 “MVP로 실제 검색까지 가는 것”이어야 한다.

따라서 우선순위는 아래 순서가 가장 현실적이다.

```text
1) schema + DB 적재
2) chunk/search_text 생성
3) embedding 생성
4) pgvector baseline 확인
5) Elasticsearch BM25/Nori index 생성
6) hybrid 검색 연결
7) eval query 세트 + 결과 리포트 작성
```

---

# 8. 실행 단계별 계획

## 8.0 구현 순서 요약 (MVP 기준)

이 문서는 “한 번에 다 만든다”보다 “작게 시작해서 검증하면서 확장한다”는 흐름으로 작성하는 것이 좋다.

```text
Phase 1: DB 적재와 데이터 안정성 확보
Phase 2: 검색용 chunk와 search_text 생성
Phase 3: embedding 생성 및 pgvector baseline 검증
Phase 4: Elasticsearch BM25/Nori/hybrid 연결
Phase 5: eval query 세트와 리포트 생성
```

각 단계는 아래 형식으로 진행한다.

```text
입력 → 처리 → 저장 → 검증 → 완료 기준
```

---

## 8.1 1단계: schema 생성 및 초기 DB 준비

### 목표

review_case_db를 생성하고, 이후 적재/검색/평가에 필요한 기본 테이블과 인덱스를 만든다.

### 작업 내용

```text
1. review_case_db 생성
2. vector extension 활성화
3. 13개 핵심 테이블 생성
4. review_case_* 테이블에 기본 index 추가
5. run_id, review_case_id, chunk_id 기준 join이 가능하도록 설계
```

### 필수 확인 포인트

```text
- review_case_preprocess_runs 테이블이 생성되었는가?
- review_case_documents / review_case_chunks / review_case_chunk_embeddings가 정상 생성되었는가?
- PostgreSQL에서 review_case_db가 확인 가능한가?
```

### 완료 기준

```text
DBeaver 또는 psql에서 review_case_db와 13개 테이블이 확인 가능
```

### 실패 시 대응

```text
schema 적용 실패 시에는 테이블 생성 순서와 FK 의존성을 먼저 점검한다.
vector extension 미설치 시에는 DB 환경에서 extension을 먼저 활성화한다.
```

---

## 8.2 2단계: preprocessed 산출물 적재

### 목표

기존 전처리 결과(JSONL)를 PostgreSQL에 적재하고, 이후 재실행 가능한 run 단위 구조로 만든다.

### 작업 내용

```text
1. preprocessing_summary.json을 읽어 run 정보를 생성한다.
2. review_case_preprocess_runs에 run metadata를 insert한다.
3. review_case_documents.jsonl을 upsert한다.
4. review_case_source_chunks.jsonl을 적재한다.
5. review_case_chunks.jsonl을 적재한다.
6. quality report와 toc 결과를 적재한다.
7. 적재 결과 리포트를 생성한다.
```

### 반드시 확인할 것

```text
- review_case_documents에 226건이 들어갔는가?
- review_case_chunks가 904건으로 생성되었는가?
- review_case_quality_reports와 review_case_toc_case_links가 빠짐없이 적재되었는가?
```

### 완료 기준

```text
review_case_documents = 226 rows
review_case_chunks = 904 rows
review_case_quality_reports = 226 rows
```

### 실패 시 대응

```text
JSONL 필드 누락이 있으면 raw_json으로 백업하고, 필수 컬럼만 먼저 적재한다.
중복 review_no가 있으면 upsert 방식으로 처리한다.
```

---

## 8.3 3단계: search_text 생성 및 chunk 품질 검증

### 목표

RAG 검색 품질이 높아지도록 chunk_text와 search_text를 분리하고, 검색용 텍스트를 생성한다.

### 작업 내용

```text
1. chunk_type별로 search_text 생성 규칙을 적용한다.
2. case_overview / arguments / evidence_issue / decision 구조에 맞게 텍스트를 만든다.
3. reference_chart_key, standard_scenario_keywords, decision_fault_ratio 등을 포함한다.
4. search_text 길이를 확인하고 과도하게 긴 경우 축약한다.
5. chunk_text는 원문 기반으로 유지하고 search_text는 검색용으로 분리한다.
```

### 검증 포인트

```text
- 각 chunk에 search_text가 비어 있지 않은가?
- case_overview에는 사고상황 키워드가 들어가는가?
- decision chunk에는 결정근거/결정이유/최종비율이 들어가는가?
```

### 완료 기준

```text
review_case_chunks의 search_text가 모든 row에 채워짐
```

### 실패 시 대응

```text
필수 필드가 비어 있으면 보조 필드만으로 search_text를 생성하고 warning을 남긴다.
```

---

## 8.4 4단계: embedding 생성 및 저장

### 목표

각 chunk를 embedding으로 변환하고, pgvector용 vector를 저장한다.

### 작업 내용

```text
1. embedding_job 생성
2. pending 상태의 chunk를 조회한다.
3. chunk_text 기준 embedding을 생성한다.
4. review_case_chunk_embeddings에 저장한다.
5. review_case_chunks.embedding_status를 done으로 업데이트한다.
6. 실패 chunk는 재시도 가능하도록 기록한다.
```

### 검증 포인트

```text
- embedding_dim이 기대값과 일치하는가?
- chunk_id 기준으로 embedding row 수가 chunk 수와 일치하는가?
- embedding_model/version이 기록되는가?
```

### 완료 기준

```text
embedding 생성 성공 건수 = chunk 총 건수
```

### 실패 시 대응

```text
API 실패 시에는 batch 단위로 재시도하고, 실패 내역은 embedding_jobs.error_summary에 남긴다.
```

---

## 8.5 5단계: pgvector baseline 검색 검증

pgvector baseline 검색을 실행하기 전에 `review_case_chunk_embeddings.embedding_vector`에 대한 HNSW index를 생성한다.

### 8.4-1 pgvector HNSW index 생성

#### 목적

embedding 저장이 끝난 뒤 vector similarity 검색을 안정적으로 수행하기 위해 `review_case_chunk_embeddings.embedding_vector`에 HNSW index를 생성한다.

심의사례는 현재 904개 chunk라서 데이터 양만 보면 index가 없어도 검색은 가능하다.  
다만 이 단계는 단순 성능 최적화만이 아니라 다음 목적을 가진다.

```text
1. pgvector baseline 검색 구조를 명확히 고정한다.
2. 이후 심의사례 데이터가 늘어나도 같은 검색 구조를 유지한다.
3. 판례 RAG 파이프라인과 동일한 vector 검색 운영 방식을 맞춘다.
4. Elasticsearch vector/hybrid 검색과 비교할 때 PostgreSQL vector 검색 조건을 정리한다.
```

#### 일반 PostgreSQL index와 HNSW index의 차이

일반 index는 `review_no`, `reference_chart_key`, `chunk_type`처럼 값이 정확히 일치하거나 정렬 가능한 컬럼을 빠르게 찾기 위한 index다.

예:

```text
review_no = '2017-032889'
reference_chart_key = '249'
chunk_type = 'decision'
```

반면 HNSW index는 `embedding_vector`처럼 고차원 벡터에서 query vector와 가까운 chunk를 찾기 위한 근사 최근접 탐색 index다.

예:

```text
사용자 질문: 신호 없는 중앙선 설치 도로에서 역주행 차량과 충돌
query embedding
→ review_case_chunk_embeddings.embedding_vector와 cosine distance 비교
→ 의미적으로 가까운 top-k chunk 반환
```

따라서 두 index는 목적이 다르다.

| 구분 | 일반 PostgreSQL index | pgvector HNSW index |
|---|---|---|
| 대상 | review_no, chart_key, chunk_type 등 일반 컬럼 | embedding_vector |
| 검색 방식 | 정확 일치, 범위, 정렬 | 벡터 유사도 검색 |
| 대표 용도 | 특정 심의번호/도표번호 조회 | 자연어 query와 의미가 가까운 chunk 검색 |
| 점수 기준 | 없음 또는 정렬 기준 | cosine distance / cosine similarity |
| RAG 역할 | 필터링, 메타데이터 조회 | 의미 기반 후보 검색 |

#### embedding 저장 후 생성하는 이유

HNSW index는 vector insert/update가 발생할 때마다 index 구조를 갱신해야 한다.  
따라서 embedding을 저장하기 전에 index를 먼저 만들면 대량 insert가 느려질 수 있다.

이번 파이프라인에서는 다음 순서를 기본으로 한다.

```text
1. review_case_chunks 생성
2. review_case_chunk_embeddings에 embedding 전체 저장
3. embedding count 검증
4. HNSW index 생성
5. pgvector baseline 검색
```

#### SQL 기준

기본 index SQL은 다음과 같다.

```sql
CREATE INDEX IF NOT EXISTS idx_review_case_chunk_embeddings_cosine_hnsw
ON review_case_chunk_embeddings
USING hnsw (embedding_vector vector_cosine_ops);
```

`vector_cosine_ops`를 사용하는 이유는 현재 embedding 검색 기준을 cosine similarity로 통일하기 위해서다.

#### 완료 기준

```text
review_case_chunk_embeddings = 904 rows
embedding_vector IS NOT NULL = 904 rows
idx_review_case_chunk_embeddings_cosine_hnsw index 존재
sample query에 대해 top-k 검색 가능
```

#### 주의점

현재 schema의 vector 차원은 `vector(1536)` 기준이다.  
이는 `text-embedding-3-small` 및 `text-embedding-3-large`를 `dimensions=1536`으로 맞춰 비교하기 위한 기준이다.

나중에 `text-embedding-3-large`의 3072 차원을 그대로 사용한다면 기존 `vector(1536)` 컬럼에는 저장할 수 없다.  
그 경우에는 별도 embedding table 또는 schema migration이 필요하다.

---

## 8.5 5단계: pgvector baseline 검색 검증

### 목표

embedding 기반 검색이 실제로 의미 있는 결과를 내는지 먼저 확인한다.

### 작업 내용

```text
1. query를 하나씩 입력한다.
2. review_case_chunk_embeddings를 기준으로 cosine similarity 검색을 수행한다.
3. top-k 결과를 확인한다.
4. reference_chart_key / review_no / decision chunk hit 여부를 검증한다.
```

### 검증 포인트

```text
- query에 대해 관련 사고유형이 상위 결과에 나오는가?
- 기대 reference_chart_key가 top5 안에 들어오는가?
- decision chunk가 잘 잡히는가?
```

### 완료 기준

```text
pgvector baseline에서 최소 1개 이상의 의미 있는 결과가 나옴
```

---

## 8.6 6단계: Elasticsearch BM25/Nori 색인 및 검색

### 목표

키워드 기반 검색을 별도로 구현하고, BM25/Nori가 어떤 성능을 보이는지 확인한다.

### 작업 내용

```text
1. search_text를 대상으로 index mapping을 만든다.
2. BM25/Nori analyzer를 설정한다.
3. review_case_chunks를 Elasticsearch에 색인한다.
4. query를 통해 top-k 결과를 확인한다.
5. index job 이력을 저장한다.
```

### 검증 포인트

```text
- 색인된 chunk 수가 기대 수와 일치하는가?
- 키워드 기반 query에서 사고유형/도표번호가 잘 잡히는가?
```

### 완료 기준

```text
indexed_chunk_count = chunk 총 건수
```

---

## 8.7 7단계: hybrid 검색 연결

### 목표

BM25/Nori와 vector 검색을 조합해 더 안정적인 검색 결과를 만든다.

### 작업 내용

```text
1. BM25/Nori 후보를 가져온다.
2. vector 후보를 가져온다.
3. score normalization 후 weighted sum을 계산한다.
4. 최종 top-k를 정렬한다.
5. 결과를 eval 결과 테이블에 저장한다.
```

### 초기 가중치 권장

```text
bm25_weight = 0.55
vector_weight = 0.45
```

### 완료 기준

```text
hybrid 결과가 pgvector / BM25 각각보다 더 안정적인 top-k를 반환하는지 확인 가능
```

---

## 8.8 8단계: eval query 세트와 평가 실행

### 목표

검색 품질을 객관적으로 비교할 수 있는 평가 세트를 만든다.

### 작업 내용

```text
1. query set을 만든다.
2. expected_review_no / expected_chart_key / expected_keywords를 정의한다.
3. 각 retriever(pgvector, BM25, hybrid)에 대해 평가를 실행한다.
4. 결과를 review_case_search_eval_results에 저장한다.
5. summary metrics를 계산한다.
```

### 최소 query 수

```text
최소 30개 권장
```

### 완료 기준

```text
각 retriever마다 eval_run이 생성되고 결과 row가 쌓임
```

---

## 8.9 9단계: 리포트 작성 및 반복 개선

### 목표

실험 결과를 팀에서 재사용할 수 있는 형태로 정리한다.

### 작업 내용

```text
1. 평가 결과를 CSV/Markdown로 export한다.
2. top-k hit rate, chart hit rate, keyword coverage, decision chunk hit를 요약한다.
3. 어떤 retriever가 어느 query 유형에서 잘 나왔는지 정리한다.
4. 다음 반복에서 바꿀 weight 또는 chunk strategy를 기록한다.
```

### 완료 기준

```text
리포트가 팀 공유 가능한 형태로 남아 있고, 다음 sprint에 바로 이어서 개선할 수 있어야 한다.
```

---

## 8.10 구현 순서에서 가장 중요한 원칙

```text
1. DB 적재가 먼저다.
2. 검색 품질은 chunk_text/search_text 설계에서 결정된다.
3. embedding은 검색 실험의 공통 기반이다.
4. Elasticsearch는 비교 대상이자 운영 옵션이다.
5. eval은 구현이 끝난 뒤에 붙이는 것이 아니라 처음부터 설계에 포함해야 한다.
```

---

## 8.11 한 장 요약: 실제 구현 흐름

실제 코드를 작성할 때는 아래 흐름으로 생각하면 된다.

```text
1. 전처리 산출물(JSONL) 확보
2. review_case_db schema 생성
3. review_case_preprocess_runs / review_case_documents / review_case_chunks 적재
4. search_text 생성 규칙 적용
5. chunk embedding 생성
6. pgvector 검색으로 baseline 확인
7. Elasticsearch BM25/Nori 색인
8. hybrid 검색 조합
9. eval query로 검색 품질 비교
10. 결과 리포트 작성
```

즉, 구현의 핵심은 다음 세 가지다.

```text
- 데이터가 DB에 들어가야 한다.
- 검색용 텍스트와 embedding이 생성되어야 한다.
- 검색 결과를 반복적으로 비교할 수 있어야 한다.
```

---

# 9. 운영/배포 기준 보강

## 9.1 index 및 alias 규칙

실제 운영 단계에서는 검색 인덱스를 바로 덮어쓰지 않고 버전 관리한다.

```text
index_name 형식:
review_case_chunks_bm25_nori_v{version}
review_case_chunks_vector_v{version}
review_case_chunks_hybrid_v{version}
```

alias는 다음처럼 둔다.

```text
review_case_chunks_bm25_alias
review_case_chunks_vector_alias
review_case_chunks_hybrid_alias
```

이유:

```text
1. 실험 중인 인덱스를 바로 교체하지 않기 위해
2. 실패 시 이전 인덱스로 롤백하기 위해
3. 모델/분석기 변경 시 비교 가능하도록 하기 위해
```

---

## 9.2 모델/버전 관리

embedding 모델과 검색 설정은 코드에 하드코딩하지 말고 별도로 관리해야 한다.

```text
embedding_model = text-embedding-3-small
embedding_version = openai_text_embedding_3_small_chunk_text_v1
analyzer = nori
search_mode = bm25|vector|hybrid
```

각 run마다 다음 정보가 기록되어야 한다.

```text
- embedding_model
- embedding_version
- index_name
- analyzer
- top_k / candidate_k
- query_count
- metric_summary
```

---

## 9.3 롤백 전략

검색 품질이 떨어지거나 인덱스가 깨졌을 때를 대비해 다음 기준을 둔다.

```text
1. 이전 alias가 정상이라면 즉시 롤백한다.
2. embedding 생성이 실패하면 기존 검색 결과를 사용하지 않는다.
3. Elasticsearch index 생성 실패 시 pgvector baseline만 유지한다.
4. eval 결과가 나쁘면 hybrid weight를 다시 조정한다.
```

---

# 10. 실패 복구 및 재실행 정책

## 10.1 partial load 정책

적재 과정에서 일부 row만 실패하더라도 전체 파이프라인이 멈추지 않도록 한다.

```text
- 오류가 난 row는 실패 로그로 남긴다.
- 성공한 row는 계속 적재한다.
- 실패 row는 재실행 가능한 상태로 유지한다.
```

### 권장 방식

```text
1. row 단위로 try/except 처리
2. 실패 row는 error_summary에 기록
3. 재실행 시 failed 상태만 다시 처리
```

---

## 10.2 embedding 재시도 정책

embedding API 호출은 일시적 실패가 자주 발생한다.

```text
- retry_count = 3
- backoff = 1s, 2s, 4s
- 실패 chunk는 failed 상태로 남긴다.
```

---

## 10.3 Elasticsearch 재색인 정책

인덱스 생성이 실패하면 다음과 같이 처리한다.

```text
1. 기존 index를 삭제하지 않는다.
2. 새 index 이름을 만든다.
3. 성공하면 alias를 새 인덱스로 이동한다.
4. 실패하면 기존 alias 유지
```

---

# 11. 평가 실험 설계 보강

## 11.1 최소 실험 세트

실험은 단순히 “한두 개 쿼리”로 끝나면 안 된다.

```text
최소 30개 query 권장
```

쿼리 유형은 다음처럼 나누는 것이 좋다.

```text
A. 사고상황형
B. 도표번호형
C. 주장형
D. 증거형
E. 쟁점형
F. 결정이유형
G. 비율형
```

각 query는 다음 정보를 가져야 한다.

```text
- query_text
- expected_review_no
- expected_reference_chart_key
- expected_keywords
- expected_chunk_types
- difficulty
```

---

## 11.2 평가 결과 저장 포맷

eval 결과는 단순 텍스트가 아니라 구조화 저장이 필요하다.

```text
review_case_search_eval_results 테이블에 저장
- query_id
- retriever
- rank
- chunk_id
- review_no
- retriever_score
- reranker_score
- manual_grade
- memo
```

이렇게 저장해야 이후에 다음 분석이 가능하다.

```text
- 어떤 retriever가 어느 query 유형에서 강한지
- 어떤 chunk_type이 자주 잘못 회수되는지
- 어떤 weight가 좋은지
```

---

# 12. 서비스 응답 계약 보강

## 12.1 검색 API가 반환해야 할 필드

최종 서비스 단계에서는 검색 결과가 단순히 chunk_id만 반환하면 안 된다.

```text
반환 필드 예시
- chunk_id
- review_case_id
- review_no
- chunk_type
- score
- snippet
- source_reference
- reference_chart_key
- decision_fault_ratio
```

이렇게 하면 프론트엔드나 LLM이 결과를 바로 활용하기 쉽다.

---

## 12.2 provenance 정보 포함

각 검색 결과는 어디서 나온 결과인지 반드시 남겨야 한다.

```text
source_reference = review_case:2018-051544 / chunk_type=decision / page=42
```

이유:

```text
1. 사용자에게 근거를 제시하기 위해
2. LLM 답변에 citation을 붙이기 위해
3. 잘못된 근거를 추적하기 위해
```

---

## 12.3 사용자 질문 유형별 응답 전략

서비스에서는 질문 유형에 따라 chunk_type 우선순위를 다르게 해도 좋다.

```text
- 사고상황 질문 → case_overview 우선
- 주장 질문 → arguments 우선
- 증거/쟁점 질문 → evidence_issue 우선
- 판단이유 질문 → decision 우선
```

이렇게 하면 검색 결과가 더 자연스럽게 사용자 의도에 맞춰진다.

---

# 13. 최종 정리

심의사례 계획은 이제 다음 수준까지 갖춰야 한다.

```text
1. 구현 가능한 구조
2. 운영 가능한 index/version 관리
3. 재실행 가능한 적재/embedding 정책
4. 비교 가능한 eval 실험 설계
5. 서비스 응답에 바로 쓰는 결과 스키마
```

즉, 이 문서는 단순한 “설계안”이 아니라

```text
실제로 개발팀이 바로 구현하고, 실험하고, 운영할 수 있는 실행 가이드
```

로 발전해야 한다.

## 8.1 1단계: schema 생성

명령 예시:

```bash
python -m etl.fault_cases.src.review_case.db_loading.schema_manager --create-db --apply-schema
```

처리:

```text
1. review_case_db 생성
2. vector extension 활성화
3. 13개 테이블 생성
4. index 생성
```

예상 결과:

```text
DBeaver에 review_case_db가 보임
public 아래 review_case_* 테이블 13개 생성
```

---

## 8.2 2단계: preprocessed 산출물 적재

명령 예시:

```bash
python -m etl.fault_cases.src.review_case.db_loading.run_db_load \
  --preprocessed-dir etl/fault_cases/artifacts/review_case_output/preprocessed
```

처리:

```text
1. preprocessing_summary.json 읽기
2. run_id 생성
3. review_case_preprocess_runs insert
4. review_case_documents.jsonl upsert
5. review_case_source_chunks.jsonl insert
6. review_case_chunks.jsonl insert
7. quality_report.jsonl insert
8. toc jsonl insert
9. 적재 리포트 생성
```

예상 결과:

```text
review_case_documents = 226 rows
review_case_source_chunks = 285 rows
review_case_chunks = 904 rows
review_case_quality_reports = 226 rows
review_case_toc_items = 226 rows
review_case_toc_case_links = 226 rows
```

---

## 8.3 3단계: search_text 생성/검증

처리:

```text
1. chunk_type별 search_text 생성
2. standard_scenario_keywords 포함 여부 확인
3. reference_chart_key 포함 여부 확인
4. decision_fault_ratio 포함 여부 확인
5. search_text 길이 확인
```

예상 결과:

```text
모든 review_case_chunks.search_text 채움
case_overview search_text에는 사고상황 키워드가 들어감
decision search_text에는 결정근거/결정이유/최종비율이 들어감
```

---

## 8.4 4단계: embedding 생성

명령 예시:

```bash
python -m etl.fault_cases.src.review_case.embedding.run_embedding \
  --model text-embedding-3-small \
  --input-field chunk_text \
  --version openai_text_embedding_3_small_chunk_text_v1
```

처리:

```text
1. embedding_job 생성
2. embedding_status=pending chunk 조회
3. chunk_text 기준 embedding 생성
4. review_case_chunk_embeddings insert
5. review_case_chunks.embedding_status=done 업데이트
6. job 성공/실패 수 기록
```

예상 결과:

```text
target_chunk_count = 904
success_count = 904
failed_count = 0
review_case_chunk_embeddings = 904 rows
```

---

## 8.4-1 4-1단계: pgvector HNSW index 생성

embedding 저장과 count 검증이 끝난 뒤에는 pgvector 검색용 HNSW index를 생성한다.

명령 예시:

```bash
python -m etl.fault_cases.src.review_case.search.pgvector.create_index
```

처리:

```text
1. review_case_chunk_embeddings row 수 확인
2. embedding_vector가 비어 있지 않은 row 수 확인
3. embedding_model / embedding_version 기준 확인
4. HNSW cosine index 생성
5. index 존재 여부를 검증하고 report JSON 저장
```

예상 결과:

```text
chunk_count = 904
embedding_count = 904
indexed_embedding_count = 904
hnsw_index_exists = true
```

이 단계가 필요한 이유:

```text
일반 PostgreSQL index는 review_no, reference_chart_key, chunk_type 같은 일반 컬럼 검색용이다.
HNSW index는 embedding_vector에 대해 query vector와 가까운 chunk를 찾기 위한 vector 검색용이다.
두 index는 목적이 다르므로 pgvector baseline 검색 전 별도로 생성한다.
```

생성 시점:

```text
embedding 저장 전이 아니라 embedding 저장 후 생성한다.
대량 embedding insert 중 HNSW index를 계속 갱신하면 insert가 느려질 수 있기 때문이다.
```

주의:

```text
현재 기준은 vector(1536)이다.
text-embedding-3-small 1536 차원 또는 text-embedding-3-large dimensions=1536 비교에는 그대로 사용 가능하다.
large 3072 차원을 그대로 쓰는 실험은 별도 schema/table 설계가 필요하다.
```

---

## 8.5 5단계: pgvector baseline 검색

명령 예시:

```bash
python -m etl.fault_cases.src.review_case.search.pgvector_search \
  --query "신호 없는 중앙선 설치 도로에서 역주행 차량과 충돌" \
  --top-k 5
```

예상 결과:

```text
reference_chart_key가 249 계열인 case_overview/decision chunk가 상위에 나오는지 확인
```

---

## 8.6 6단계: Elasticsearch BM25/Nori index

명령 예시:

```bash
python -m etl.fault_cases.src.review_case.search.elasticsearch_indexer \
  --index-name review_case_chunks_bm25_nori_v1 \
  --analyzer nori \
  --source-field search_text
```

처리:

```text
1. index mapping 생성
2. search_text, chunk_text, metadata 색인
3. review_case_elasticsearch_index_jobs 기록
4. review_case_chunks.indexed_to_elasticsearch 업데이트
```

예상 결과:

```text
indexed_chunk_count = 904
failed_count = 0
```

---

## 8.7 7단계: hybrid 검색

처리:

```text
1. BM25/Nori top candidate 검색
2. vector top candidate 검색
3. score normalize
4. weighted sum
5. top_k 반환
```

초기 weight:

```text
bm25_weight = 0.55
vector_weight = 0.45
```

이유:

```text
심의사례는 도표번호, 신호위반, 중앙선 침범 같은 정확 키워드가 중요하다.
따라서 초기에는 BM25를 약간 더 높게 둔다.
```

---

# 9. 평가 기준

## 9.1 평가 query 유형

최소 30개를 만든다.

```text
A. 사고상황형
B. 도표번호형
C. 주장형
D. 증거형
E. 쟁점형
F. 결정이유형
G. 비율형
```

예시:

```text
사고상황형:
신호등 있는 사거리에서 녹색 직진 차량과 적색 직진 차량이 충돌한 사례

도표번호형:
참고기준 201 신호위반 직진 사고 사례

주장형:
상대방이 황색신호에 진입했다고 주장한 사례

증거형:
교통사고사실확인원에 상대 차량 신호위반이 적힌 사례

쟁점형:
적색신호 진입 여부가 쟁점인 사례

결정이유형:
신호를 지킨 차량에게 과실을 인정하기 어려운 사례

비율형:
청구차량 0%, 피청구차량 100%로 결정된 사례
```

---

## 9.2 핵심 지표

| 지표 | 의미 | 중요도 |
|---|---|---:|
| expected_chart_hit@5 | top5 안에 기대 reference_chart_key가 있는가 | 매우 높음 |
| expected_case_hit@5 | top5 안에 기대 review_no가 있는가 | 높음 |
| scenario_keyword_coverage@5 | 기대 키워드가 얼마나 포함됐는가 | 매우 높음 |
| decision_chunk_hit@5 | 결정근거/결정이유 chunk를 찾았는가 | 높음 |
| argument_chunk_hit@5 | 주장형 query에서 arguments chunk를 찾았는가 | 중간 |
| ratio_match@5 | 기대 과실비율과 맞는 결과가 있는가 | 높음 |
| noise_count@5 | 다른 사고유형/도표가 섞였는가 | 높음 |
| MRR | 첫 관련 결과 순위 | 중간 |

---

## 9.3 심의사례에서 가장 중요한 지표

최우선:

```text
expected_chart_hit@5
scenario_keyword_coverage@5
decision_chunk_hit@5
```

이유:

```text
개별 심의번호 하나를 정확히 맞히는 것보다
같은 참고기준/사고상황 묶음을 찾는 것이 실제 서비스에서 더 중요하다.

사용자는 "2018-051544 사례 찾아줘"가 아니라
"신호 없는 교차로에서 우회전 차량과 충돌했는데 비슷한 사례 있어?"라고 묻기 때문이다.
```

---

## 9.4 평가 등급

```text
3점: 매우 적합
  - 같은 reference_chart_key
  - 기준 키워드 다수 일치
  - 사고내용과 결정이유가 모두 유사

2점: 적합
  - 같은 사고유형 또는 유사 도표
  - 일부 기준 키워드 일치
  - 설명 참고 가능

1점: 부분 적합
  - party_type이나 큰 사고분류만 유사
  - 도표/행동/쟁점은 다름

0점: 부적합
  - 전혀 다른 사고유형
  - 다른 당사자 구조
  - 결정근거도 관련 없음
```

---

## 9.5 검색 방식 비교 원칙

검색기 점수를 직접 비교하지 않는다.

```text
pgvector cosine similarity
BM25 score
hybrid score
```

이 값들은 서로 의미가 다르다.

비교는 아래 값으로 한다.

```text
expected_chart_hit@5
scenario_keyword_coverage@5
decision_chunk_hit@5
manual_grade
필요 시 local_reranker_score
```

---

# 10. A/B 테스트 계획

## 10.1 1차: chunk_text vs search_text BM25 비교

```text
A안:
BM25/Nori source_field = chunk_text

B안:
BM25/Nori source_field = search_text
```

고정:

```text
같은 chunk_id
같은 query set
같은 top_k
같은 analyzer
```

예상:

```text
search_text가 expected_chart_hit@5와 keyword_coverage@5에서 더 좋을 가능성이 높다.
chunk_text는 근거 순도는 높지만 사용자 자연어 표현을 덜 잡을 수 있다.
```

---

## 10.2 2차: pgvector vs BM25/Nori

```text
A안:
pgvector chunk_text embedding

B안:
Elasticsearch BM25/Nori search_text
```

예상:

```text
pgvector는 자연어 사고상황에 강할 가능성
BM25/Nori는 도표번호, 신호위반, 중앙선 침범 같은 정확 키워드에 강할 가능성
```

---

## 10.3 3차: hybrid

```text
A안:
BM25/Nori only

B안:
pgvector/vector only

C안:
hybrid
```

예상:

```text
hybrid가 전체 평균은 가장 좋을 가능성이 높다.
다만 데이터가 904 chunk로 작기 때문에 BM25/Nori만으로도 충분할 가능성이 있다.
```

---

## 10.4 4차: reranker 평가

처음부터 reranker로 검색 결과를 재정렬하지 않는다.

```text
1차 역할:
평가용 점수화

후속 역할:
검색 개선용 재정렬
```

이유:

```text
처음부터 reranker가 결과를 바꾸면
pgvector가 잘한 것인지
BM25가 잘한 것인지
hybrid가 잘한 것인지
reranker가 살린 것인지 알 수 없다.
```

---

# 11. 코드별 상세 근거와 예상 결과

## 11.1 schema_manager.py

### 하는 일

```text
review_case_db 생성
vector extension 활성화
13개 테이블 생성
index 생성
```

### 왜 필요한가

DB 생성과 schema 적용을 수동으로 하면 팀원마다 결과가 달라질 수 있다.

### 예상 결과

```text
한 번 실행하면 DBeaver에서 review_case_db와 13개 테이블 확인 가능
재실행해도 IF NOT EXISTS 기준으로 안전하게 동작
```

---

## 11.2 load_preprocessed.py

### 하는 일

```text
preprocessed 폴더의 JSONL/JSON을 읽어 DB에 적재
```

### 왜 필요한가

현재 전처리 결과는 파일 기반이다.  
서비스 검색과 평가를 하려면 PostgreSQL에 올려야 한다.

### 예상 결과

```text
documents 226건
chunks 904건
quality_reports 226건
toc_items 226건
toc_case_links 226건 적재
```

---

## 11.3 search_text_builder.py

### 하는 일

```text
chunk_type별 search_text 생성
```

### 왜 필요한가

PDF 원문 표현과 사용자 검색 표현이 다르기 때문이다.

### 예상 결과

```text
BM25/Nori 검색에서 신호위반, 중앙선 침범, 비보호좌회전, 도표번호 검색 품질 증가
```

---

## 11.4 embed_chunks.py

### 하는 일

```text
review_case_chunks.chunk_text를 embedding으로 변환
review_case_chunk_embeddings에 저장
```

### 왜 필요한가

사용자 사고 설명이 PDF 문구와 달라도 의미 기반으로 유사 사례를 찾기 위해서다.

### 예상 결과

```text
904개 chunk embedding 생성
pgvector 검색 가능
Elasticsearch vector/hybrid index 생성 가능
```

---

## 11.5 pgvector_search.py

### 하는 일

```text
query embedding 생성
review_case_chunk_embeddings와 cosine similarity 검색
top_k 반환
```

### 왜 필요한가

Elasticsearch를 붙이기 전에도 PostgreSQL만으로 vector baseline을 확인할 수 있다.

### 예상 결과

```text
자연어 사고상황 질의에서 의미적으로 비슷한 case_overview/decision chunk 반환
```

---

## 11.6 elasticsearch_indexer.py

### 하는 일

```text
review_case_chunks와 embedding을 Elasticsearch에 색인
```

### 왜 필요한가

BM25/Nori, vector, hybrid를 테스트하기 위해 필요하다.

### 예상 결과

```text
review_case_chunks_bm25_nori_v1
review_case_chunks_hybrid_v1
같은 index 후보 생성
```

---

## 11.7 eval_runner.py

### 하는 일

```text
평가 query를 실행하고 top_k 결과를 저장
```

### 왜 필요한가

검색이 “되는 것”과 “좋은 것”은 다르다.  
정해진 query set으로 비교해야 한다.

### 예상 결과

```text
retriever별 expected_chart_hit@5
scenario_keyword_coverage@5
decision_chunk_hit@5
noise_count@5 비교 가능
```

---

## 11.8 metrics.py

### 하는 일

```text
검색 결과를 지표로 계산
```

### 왜 필요한가

검색 방식별 raw score는 직접 비교할 수 없기 때문이다.

### 예상 결과

```text
pgvector, BM25/Nori, hybrid 중 어떤 방식이 심의사례에 맞는지 수치로 판단 가능
```

---

# 12. 최종 실행 로드맵

## 12.1 1차 구현

```text
1. review_case_db schema 생성
2. preprocessed 결과 DB 적재
3. search_text 생성
4. 데이터 수 검증
```

성공 기준:

```text
documents = 226
chunks = 904
source_chunks = 285
quality fatal = 0
```

---

## 12.2 2차 구현

```text
1. text-embedding-3-small embedding 생성
2. pgvector 검색 baseline
3. 10개 샘플 query 테스트
```

성공 기준:

```text
embedding = 904
샘플 query에서 같은 reference_chart_key 결과가 top5 안에 포함
```

---

## 12.3 3차 구현

```text
1. Elasticsearch BM25/Nori index 생성
2. chunk_text vs search_text 비교
3. 30개 평가 query 실행
```

성공 기준:

```text
search_text BM25가 chunk_text BM25보다 keyword_coverage@5 개선
```

---

## 12.4 4차 구현

```text
1. pgvector vs BM25/Nori vs hybrid 비교
2. expected_chart_hit@5
3. decision_chunk_hit@5
4. noise_count@5 비교
```

성공 기준:

```text
hybrid 또는 BM25/Nori 중 하나를 운영 후보로 선택
```

---

## 12.5 5차 구현

```text
1. 검색 API 연결
2. RAG 답변 context 구성
3. 사용자 사고 경위 입력 테스트
4. 최종 top5 심의사례 반환
```

성공 기준:

```text
사용자 사고 경위 입력
→ 유사 심의사례 검색
→ 사고상황/주장/쟁점/결정이유/과실비율 설명 가능
```

---

# 13. 최종 기준 요약

## 13.1 테이블

```text
최소 적재 기준 = 7개
운영/평가 기준 = 13개
온라인 로그 포함 = 15개 이상
```

이 문서의 최종 구현 기준:

```text
13개 테이블
```

---

## 13.2 chunk

```text
A계획:
section chunk 유지
case_overview / arguments / evidence_issue / decision

B계획:
1800자 이상이면 section 내부 의미 기준 split
arguments_claimant / arguments_respondent
evidence / issue
decision_basis / decision_reason
```

---

## 13.3 예상 chunk 수

현재 기준:

```text
documents = 226
chunks = 904
4 chunks per case
```

B계획 적용 시 예상:

```text
현재 데이터에서는 split 0건 예상
추가 PDF/긴 사례 포함 시 904~1,100 chunks 예상
```

---

## 13.4 평가

최우선 지표:

```text
expected_chart_hit@5
scenario_keyword_coverage@5
decision_chunk_hit@5
```

보조 지표:

```text
expected_case_hit@5
argument_chunk_hit@5
ratio_match@5
noise_count@5
MRR
manual_grade
```

---

# 14. 최종 결론

심의사례는 판례 파이프라인과 같은 방향으로 가되, 테이블/청크/평가 기준은 심의사례 전용으로 바꿔야 한다.

```text
판례:
긴 본문 기반
1500/250 window chunk
holding/summary/main_text/evidence 중심
case_id 중심

심의사례:
짧고 구조화된 section 기반
section chunk
case_overview/arguments/evidence_issue/decision 중심
review_no 중심
```

따라서 최종 구현은 다음 기준으로 진행한다.

```text
review_case_db 생성
13개 테이블 기준
section chunk 유지
chunk_text/search_text 분리
embedding은 chunk_text 기준으로 시작
BM25/Nori는 search_text 기준으로 비교
pgvector/BM25/hybrid를 오프라인 평가
expected_chart_hit@5와 decision_chunk_hit@5를 핵심 지표로 선택
```

