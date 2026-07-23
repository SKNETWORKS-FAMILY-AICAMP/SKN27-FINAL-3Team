-- Precedent RAG schema.
-- Apply this file to both:
--   - traffic_precedent_db
--   - fault_ratio_precedent_db
--
-- Database creation and section-based application are handled by:
--   etl/fault_cases/src/traffic_precedents/precedent_db_loading/schema_loader.py

-- BEGIN COMMON_SCHEMA
CREATE EXTENSION IF NOT EXISTS vector;
-- END COMMON_SCHEMA

-- BEGIN TRAFFIC_SCHEMA
CREATE TABLE IF NOT EXISTS traffic_precedent_cases (
    case_id TEXT PRIMARY KEY,
    raw_case_id TEXT,
    case_name TEXT NOT NULL,
    case_number TEXT,
    court_name TEXT,
    court_type_code TEXT,
    decision_date DATE,
    decision_date_raw TEXT,
    decision_date_parse_ok BOOLEAN,
    decision_label TEXT,
    case_category TEXT,
    case_category_code TEXT,
    judgment_type TEXT,
    holding TEXT,
    summary TEXT,
    main_text TEXT NOT NULL,
    full_text TEXT NOT NULL,
    referenced_laws TEXT,
    referenced_cases TEXT,
    source_reference TEXT,
    source_provider TEXT,
    source_type TEXT,
    source_bucket TEXT,
    same_case_key TEXT,
    matched_keywords JSONB DEFAULT '[]'::jsonb,
    quality_flags JSONB DEFAULT '[]'::jsonb,
    missing_fields JSONB DEFAULT '[]'::jsonb,
    traffic_label TEXT,
    traffic_label_before_verification TEXT,
    traffic_verification_source_label TEXT,
    traffic_verification_final_label TEXT,
    traffic_verification_decision_reasons JSONB DEFAULT '[]'::jsonb,
    traffic_relevance_score INTEGER,
    traffic_reclass_reasons JSONB DEFAULT '[]'::jsonb,
    traffic_evidence_terms JSONB DEFAULT '[]'::jsonb,
    traffic_signal_groups JSONB DEFAULT '[]'::jsonb,
    traffic_signal_group_count INTEGER,
    traffic_term_count INTEGER,
    traffic_terms_for_count JSONB DEFAULT '[]'::jsonb,
    traffic_direct_terms JSONB DEFAULT '[]'::jsonb,
    traffic_legal_terms JSONB DEFAULT '[]'::jsonb,
    traffic_actor_terms JSONB DEFAULT '[]'::jsonb,
    traffic_action_terms JSONB DEFAULT '[]'::jsonb,
    traffic_situation_terms JSONB DEFAULT '[]'::jsonb,
    traffic_fault_terms JSONB DEFAULT '[]'::jsonb,
    has_core_accident_context BOOLEAN,
    has_traffic_legal_plus_accident_context BOOLEAN,
    case_category_disallowed_for_confirmed BOOLEAN,
    duplicate_group_status TEXT,
    duplicate_removed_count INTEGER,
    text_length INTEGER,
    main_text_length INTEGER,
    summary_length INTEGER,
    holding_length INTEGER,
    referenced_laws_length INTEGER,
    referenced_cases_length INTEGER,
    raw_json JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS traffic_precedent_chunks (
    chunk_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES traffic_precedent_cases(case_id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_type TEXT NOT NULL,
    chunk_strategy TEXT NOT NULL DEFAULT 'structured_1500_250',
    chunk_text TEXT NOT NULL,
    search_text TEXT NOT NULL,
    char_count INTEGER,
    token_count INTEGER,
    text_hash TEXT,
    source_fields JSONB DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb,
    embedding_status TEXT DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (case_id, chunk_strategy, chunk_index)
);

CREATE TABLE IF NOT EXISTS traffic_precedent_chunk_embeddings (
    chunk_id TEXT NOT NULL REFERENCES traffic_precedent_chunks(chunk_id) ON DELETE CASCADE,
    embedding_model TEXT NOT NULL,
    embedding_dim INTEGER NOT NULL DEFAULT 1536,
    embedding_version TEXT NOT NULL DEFAULT 'v1',
    embedding_provider TEXT,
    embedding_vector vector(1536),
    embedding_meta JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (chunk_id, embedding_model, embedding_version),
    CHECK (embedding_dim = 1536)
);
-- END TRAFFIC_SCHEMA

-- BEGIN FAULT_RATIO_SCHEMA
CREATE TABLE IF NOT EXISTS fault_ratio_precedent_cases (
    case_id TEXT PRIMARY KEY,
    traffic_case_id TEXT,
    raw_case_id TEXT,
    case_name TEXT NOT NULL,
    case_number TEXT,
    court_name TEXT,
    court_type_code TEXT,
    decision_date DATE,
    decision_date_raw TEXT,
    decision_date_parse_ok BOOLEAN,
    decision_label TEXT,
    case_category TEXT,
    case_category_code TEXT,
    judgment_type TEXT,
    holding TEXT,
    summary TEXT,
    main_text TEXT NOT NULL,
    full_text TEXT NOT NULL,
    referenced_laws TEXT,
    referenced_cases TEXT,
    source_reference TEXT,
    source_provider TEXT,
    source_type TEXT,
    source_bucket TEXT,
    same_case_key TEXT,
    matched_keywords JSONB DEFAULT '[]'::jsonb,
    quality_flags JSONB DEFAULT '[]'::jsonb,
    missing_fields JSONB DEFAULT '[]'::jsonb,
    traffic_label TEXT,
    traffic_label_before_verification TEXT,
    traffic_verification_source_label TEXT,
    traffic_verification_final_label TEXT,
    traffic_verification_decision_reasons JSONB DEFAULT '[]'::jsonb,
    traffic_relevance_score INTEGER,
    traffic_reclass_reasons JSONB DEFAULT '[]'::jsonb,
    traffic_evidence_terms JSONB DEFAULT '[]'::jsonb,
    traffic_signal_groups JSONB DEFAULT '[]'::jsonb,
    traffic_signal_group_count INTEGER,
    traffic_term_count INTEGER,
    traffic_terms_for_count JSONB DEFAULT '[]'::jsonb,
    traffic_direct_terms JSONB DEFAULT '[]'::jsonb,
    traffic_legal_terms JSONB DEFAULT '[]'::jsonb,
    traffic_actor_terms JSONB DEFAULT '[]'::jsonb,
    traffic_action_terms JSONB DEFAULT '[]'::jsonb,
    traffic_situation_terms JSONB DEFAULT '[]'::jsonb,
    traffic_fault_terms JSONB DEFAULT '[]'::jsonb,
    has_core_accident_context BOOLEAN,
    has_traffic_legal_plus_accident_context BOOLEAN,
    fault_ratio_label TEXT,
    fault_ratio_label_before_verification TEXT,
    fault_ratio_verification_source_label TEXT,
    fault_ratio_verification_final_label TEXT,
    fault_ratio_verification_decision_reasons JSONB DEFAULT '[]'::jsonb,
    fault_ratio_score INTEGER,
    fault_ratio_reclass_reasons JSONB DEFAULT '[]'::jsonb,
    fault_ratio_evidence_terms JSONB DEFAULT '[]'::jsonb,
    fault_ratio_signal_groups JSONB DEFAULT '[]'::jsonb,
    fault_ratio_signal_group_count INTEGER,
    fault_ratio_explicit_terms JSONB DEFAULT '[]'::jsonb,
    fault_ratio_party_fault_terms JSONB DEFAULT '[]'::jsonb,
    fault_ratio_damage_terms JSONB DEFAULT '[]'::jsonb,
    fault_ratio_duty_terms JSONB DEFAULT '[]'::jsonb,
    fault_ratio_no_fault_terms JSONB DEFAULT '[]'::jsonb,
    fault_ratio_number_examples JSONB DEFAULT '[]'::jsonb,
    has_core_fault_ratio_context BOOLEAN,
    has_damage_or_insurance_context BOOLEAN,
    no_fault_context_without_core BOOLEAN,
    case_category_disallowed_for_confirmed BOOLEAN,
    duplicate_group_status TEXT,
    duplicate_removed_count INTEGER,
    text_length INTEGER,
    main_text_length INTEGER,
    summary_length INTEGER,
    holding_length INTEGER,
    referenced_laws_length INTEGER,
    referenced_cases_length INTEGER,
    raw_json JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fault_ratio_precedent_chunks (
    chunk_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES fault_ratio_precedent_cases(case_id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_type TEXT NOT NULL,
    chunk_strategy TEXT NOT NULL DEFAULT 'structured_1500_250',
    chunk_text TEXT NOT NULL,
    search_text TEXT NOT NULL,
    char_count INTEGER,
    token_count INTEGER,
    text_hash TEXT,
    source_fields JSONB DEFAULT '[]'::jsonb,
    contains_fault_ratio_terms BOOLEAN DEFAULT false,
    contains_damage_terms BOOLEAN DEFAULT false,
    contains_duty_terms BOOLEAN DEFAULT false,
    metadata JSONB DEFAULT '{}'::jsonb,
    embedding_status TEXT DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (case_id, chunk_strategy, chunk_index)
);

CREATE TABLE IF NOT EXISTS fault_ratio_precedent_chunk_embeddings (
    chunk_id TEXT NOT NULL REFERENCES fault_ratio_precedent_chunks(chunk_id) ON DELETE CASCADE,
    embedding_model TEXT NOT NULL,
    embedding_dim INTEGER NOT NULL DEFAULT 1536,
    embedding_version TEXT NOT NULL DEFAULT 'v1',
    embedding_provider TEXT,
    embedding_vector vector(1536),
    embedding_meta JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (chunk_id, embedding_model, embedding_version),
    CHECK (embedding_dim = 1536)
);
-- END FAULT_RATIO_SCHEMA

-- BEGIN TRAFFIC_INDEXES
CREATE INDEX IF NOT EXISTS idx_traffic_precedent_cases_decision_date
ON traffic_precedent_cases (decision_date);

CREATE INDEX IF NOT EXISTS idx_traffic_precedent_cases_category
ON traffic_precedent_cases (case_category);

CREATE INDEX IF NOT EXISTS idx_traffic_precedent_cases_label
ON traffic_precedent_cases (traffic_verification_final_label);

CREATE INDEX IF NOT EXISTS idx_traffic_precedent_cases_raw_json_gin
ON traffic_precedent_cases USING GIN (raw_json);

CREATE INDEX IF NOT EXISTS idx_traffic_precedent_cases_keywords_gin
ON traffic_precedent_cases USING GIN (matched_keywords);

CREATE INDEX IF NOT EXISTS idx_traffic_precedent_chunks_case
ON traffic_precedent_chunks (case_id);

CREATE INDEX IF NOT EXISTS idx_traffic_precedent_chunks_type
ON traffic_precedent_chunks (chunk_type);
-- END TRAFFIC_INDEXES

-- BEGIN FAULT_RATIO_INDEXES
CREATE INDEX IF NOT EXISTS idx_fault_ratio_precedent_cases_decision_date
ON fault_ratio_precedent_cases (decision_date);

CREATE INDEX IF NOT EXISTS idx_fault_ratio_precedent_cases_category
ON fault_ratio_precedent_cases (case_category);

CREATE INDEX IF NOT EXISTS idx_fault_ratio_precedent_cases_label
ON fault_ratio_precedent_cases (fault_ratio_verification_final_label);

CREATE INDEX IF NOT EXISTS idx_fault_ratio_precedent_cases_raw_json_gin
ON fault_ratio_precedent_cases USING GIN (raw_json);

CREATE INDEX IF NOT EXISTS idx_fault_ratio_precedent_cases_keywords_gin
ON fault_ratio_precedent_cases USING GIN (matched_keywords);

CREATE INDEX IF NOT EXISTS idx_fault_ratio_precedent_cases_signal_groups_gin
ON fault_ratio_precedent_cases USING GIN (fault_ratio_signal_groups);

CREATE INDEX IF NOT EXISTS idx_fault_ratio_precedent_chunks_case
ON fault_ratio_precedent_chunks (case_id);

CREATE INDEX IF NOT EXISTS idx_fault_ratio_precedent_chunks_type
ON fault_ratio_precedent_chunks (chunk_type);
-- END FAULT_RATIO_INDEXES

-- Create HNSW indexes after embeddings are loaded.
-- CREATE INDEX IF NOT EXISTS idx_traffic_precedent_embeddings_hnsw
-- ON traffic_precedent_chunk_embeddings
-- USING hnsw (embedding_vector vector_cosine_ops);
--
-- CREATE INDEX IF NOT EXISTS idx_fault_ratio_precedent_embeddings_hnsw
-- ON fault_ratio_precedent_chunk_embeddings
-- USING hnsw (embedding_vector vector_cosine_ops);
