-- Review case RAG schema.
-- Apply this file to the shared law_db database.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS review_case_preprocess_runs (
    run_id TEXT PRIMARY KEY,
    source_pdf_name TEXT,
    source_pdf_path TEXT,
    preprocessed_artifact_path TEXT,
    document_count INTEGER,
    source_chunk_count INTEGER,
    rag_chunk_count INTEGER,
    quality_report_count INTEGER,
    toc_item_count INTEGER,
    toc_case_link_count INTEGER,
    valid_document_count INTEGER,
    review_required_document_count INTEGER,
    fatal_flag_counts JSONB DEFAULT '{}'::jsonb,
    warning_flag_counts JSONB DEFAULT '{}'::jsonb,
    loader_report JSONB DEFAULT '{}'::jsonb,
    page_coverage JSONB DEFAULT '{}'::jsonb,
    preprocessing_summary JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS review_case_documents (
    review_case_id TEXT PRIMARY KEY,
    review_no TEXT UNIQUE NOT NULL,
    run_id TEXT REFERENCES review_case_preprocess_runs(run_id),
    source_ref TEXT,
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
    standard_scenario_keywords JSONB DEFAULT '[]'::jsonb,
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
    toc_item_id TEXT,
    toc_chart_key TEXT,
    toc_case_title TEXT,
    toc_case_condition TEXT,
    toc_chapter_title TEXT,
    toc_large_category TEXT,
    toc_middle_category TEXT,
    toc_fault_type TEXT,
    metadata_source TEXT,
    metadata_enrichment_flags JSONB DEFAULT '[]'::jsonb,
    pdf_page_start INTEGER,
    pdf_page_end INTEGER,
    book_page_start INTEGER,
    book_page_end INTEGER,
    raw_text TEXT,
    clean_text TEXT,
    source_type TEXT DEFAULT 'review_case',
    source_reliability_score INTEGER DEFAULT 3,
    parse_status TEXT,
    quality_flags JSONB DEFAULT '[]'::jsonb,
    raw_json JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS review_case_source_chunks (
    source_chunk_id TEXT PRIMARY KEY,
    review_case_id TEXT REFERENCES review_case_documents(review_case_id) ON DELETE SET NULL,
    review_no TEXT,
    run_id TEXT REFERENCES review_case_preprocess_runs(run_id),
    sequence_no INTEGER,
    chunk_text TEXT NOT NULL,
    clean_text TEXT,
    page_start INTEGER,
    page_end INTEGER,
    pdf_page_start INTEGER,
    pdf_page_end INTEGER,
    book_page_start INTEGER,
    book_page_end INTEGER,
    char_count INTEGER,
    source_ref TEXT,
    source_type TEXT DEFAULT 'review_case',
    source_reliability_score INTEGER DEFAULT 3,
    raw_json JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS review_case_chunks (
    chunk_id TEXT PRIMARY KEY,
    review_case_id TEXT REFERENCES review_case_documents(review_case_id) ON DELETE CASCADE,
    review_no TEXT NOT NULL,
    run_id TEXT REFERENCES review_case_preprocess_runs(run_id),
    chunk_type TEXT NOT NULL,
    parent_chunk_id TEXT,
    part_index INTEGER DEFAULT 0,
    sequence_no INTEGER,
    chunk_text TEXT NOT NULL,
    search_text TEXT NOT NULL,
    char_count INTEGER,
    token_count INTEGER,
    text_hash TEXT,
    party_type TEXT,
    case_title TEXT,
    reference_chart_key TEXT,
    standard_scenario_keywords JSONB DEFAULT '[]'::jsonb,
    decision_fault_ratio TEXT,
    claimant_final_ratio INTEGER,
    respondent_final_ratio INTEGER,
    embedding_status TEXT DEFAULT 'pending',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    source_ref TEXT,
    source_type TEXT DEFAULT 'review_case',
    source_reliability_score INTEGER DEFAULT 3,
    parse_status TEXT,
    quality_flags JSONB DEFAULT '[]'::jsonb,
    raw_json JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS review_case_quality_reports (
    quality_report_id TEXT PRIMARY KEY,
    review_case_id TEXT REFERENCES review_case_documents(review_case_id) ON DELETE CASCADE,
    review_no TEXT,
    run_id TEXT REFERENCES review_case_preprocess_runs(run_id),
    parse_status TEXT,
    chunk_count INTEGER,
    fatal_flags JSONB DEFAULT '[]'::jsonb,
    warning_flags JSONB DEFAULT '[]'::jsonb,
    missing_fields JSONB DEFAULT '[]'::jsonb,
    quality_flags JSONB DEFAULT '[]'::jsonb,
    source_ref TEXT,
    memo TEXT,
    raw_json JSONB NOT NULL,
    validated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS review_case_toc_items (
    toc_item_id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES review_case_preprocess_runs(run_id),
    toc_order INTEGER,
    reference_chart_key TEXT,
    chart_no TEXT,
    chart_sub_no TEXT,
    toc_title TEXT,
    chapter_title TEXT,
    large_category TEXT,
    middle_category TEXT,
    case_title TEXT,
    case_condition TEXT,
    fault_type TEXT,
    book_page_no INTEGER,
    toc_pdf_page_no INTEGER,
    source_type TEXT DEFAULT 'review_case',
    parse_status TEXT,
    quality_flags JSONB DEFAULT '[]'::jsonb,
    raw_json JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS review_case_toc_case_links (
    toc_case_link_id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES review_case_preprocess_runs(run_id),
    toc_item_id TEXT REFERENCES review_case_toc_items(toc_item_id) ON DELETE SET NULL,
    review_case_id TEXT REFERENCES review_case_documents(review_case_id) ON DELETE CASCADE,
    review_no TEXT,
    reference_chart_key TEXT,
    chart_key TEXT,
    document_reference_chart_key TEXT,
    toc_chart_key TEXT,
    toc_case_title TEXT,
    toc_case_condition TEXT,
    chart_key_relation TEXT,
    toc_book_page_no INTEGER,
    case_book_page_start INTEGER,
    link_method TEXT,
    match_status TEXT,
    match_reason TEXT,
    mismatch_reason TEXT,
    quality_flags JSONB DEFAULT '[]'::jsonb,
    raw_json JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS review_case_chunk_embeddings (
    chunk_id TEXT NOT NULL REFERENCES review_case_chunks(chunk_id) ON DELETE CASCADE,
    embedding_model TEXT NOT NULL,
    embedding_version TEXT NOT NULL,
    -- Shared law/review-case embedding space: text-embedding-3-large, 1024 dimensions.
    embedding_dim INTEGER NOT NULL DEFAULT 1024,
    embedding_provider TEXT,
    input_field TEXT DEFAULT 'chunk_text',
    source_text_hash TEXT NOT NULL,
    embedding_vector vector(1024),
    embedding_meta JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (chunk_id, embedding_model, embedding_version, source_text_hash),
    CHECK (embedding_dim = 1024)
);

CREATE TABLE IF NOT EXISTS review_case_embedding_jobs (
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
    error_summary JSONB DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS review_case_search_eval_queries (
    query_id TEXT PRIMARY KEY,
    query_text TEXT NOT NULL,
    query_type TEXT,
    expected_review_no TEXT,
    expected_reference_chart_key TEXT,
    expected_case_title TEXT,
    expected_keywords JSONB DEFAULT '[]'::jsonb,
    expected_party_type TEXT,
    expected_fault_ratio TEXT,
    expected_chunk_types JSONB DEFAULT '[]'::jsonb,
    difficulty TEXT,
    memo TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS review_case_search_eval_runs (
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
    metric_summary JSONB DEFAULT '{}'::jsonb,
    status TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS review_case_search_eval_results (
    eval_result_id TEXT PRIMARY KEY,
    eval_run_id TEXT REFERENCES review_case_search_eval_runs(eval_run_id) ON DELETE CASCADE,
    query_id TEXT REFERENCES review_case_search_eval_queries(query_id) ON DELETE CASCADE,
    retriever TEXT,
    rank INTEGER,
    chunk_id TEXT REFERENCES review_case_chunks(chunk_id) ON DELETE SET NULL,
    review_case_id TEXT REFERENCES review_case_documents(review_case_id) ON DELETE SET NULL,
    review_no TEXT,
    chunk_type TEXT,
    retriever_score DOUBLE PRECISION,
    reranker_score DOUBLE PRECISION,
    expected_review_no_hit BOOLEAN,
    expected_chart_key_hit BOOLEAN,
    expected_chunk_type_hit BOOLEAN,
    expected_keyword_coverage DOUBLE PRECISION,
    manual_grade INTEGER,
    memo TEXT,
    raw_json JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_review_case_documents_review_no
ON review_case_documents (review_no);

CREATE INDEX IF NOT EXISTS idx_review_case_documents_chart
ON review_case_documents (reference_chart_key);

CREATE INDEX IF NOT EXISTS idx_review_case_documents_keywords_gin
ON review_case_documents USING GIN (standard_scenario_keywords);

CREATE INDEX IF NOT EXISTS idx_review_case_chunks_review_case
ON review_case_chunks (review_case_id);

CREATE INDEX IF NOT EXISTS idx_review_case_chunks_review_no
ON review_case_chunks (review_no);

CREATE INDEX IF NOT EXISTS idx_review_case_chunks_type
ON review_case_chunks (chunk_type);

CREATE INDEX IF NOT EXISTS idx_review_case_chunks_active
ON review_case_chunks (is_active)
WHERE is_active;

CREATE INDEX IF NOT EXISTS idx_review_case_chunks_chart
ON review_case_chunks (reference_chart_key);

CREATE INDEX IF NOT EXISTS idx_review_case_chunks_keywords_gin
ON review_case_chunks USING GIN (standard_scenario_keywords);

CREATE INDEX IF NOT EXISTS idx_review_case_source_chunks_review_no
ON review_case_source_chunks (review_no);

CREATE INDEX IF NOT EXISTS idx_review_case_toc_items_chart
ON review_case_toc_items (reference_chart_key);

CREATE INDEX IF NOT EXISTS idx_review_case_toc_case_links_review_no
ON review_case_toc_case_links (review_no);

CREATE INDEX IF NOT EXISTS idx_review_case_chunk_embeddings_cosine_hnsw
ON review_case_chunk_embeddings
USING hnsw (embedding_vector vector_cosine_ops)
WHERE embedding_provider = 'openai'
  AND embedding_model = 'text-embedding-3-large'
  AND embedding_version = 'openai_text_embedding_3_large_1024_chunk_text_v1'
  AND embedding_dim = 1024
  AND embedding_vector IS NOT NULL;
