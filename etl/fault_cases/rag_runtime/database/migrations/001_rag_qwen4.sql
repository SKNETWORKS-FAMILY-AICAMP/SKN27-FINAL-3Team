-- Qwen3-Embedding-4B(2560차원) 전용 운영 스키마.
-- 기존 public/search 스키마 및 기존 법률 테이블은 변경하지 않는다.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS rag_qwen4;

CREATE TABLE IF NOT EXISTS rag_qwen4.documents (
    document_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_reference TEXT NOT NULL,
    title TEXT,
    raw_text TEXT,
    embedding_input TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_sha256 CHAR(64) NOT NULL,
    embedding_input_sha256 CHAR(64),
    loaded_run_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rag_qwen4.chunks (
    chunk_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES rag_qwen4.documents(document_id) ON DELETE RESTRICT,
    chunk_index INTEGER,
    chunk_type TEXT,
    chunk_text TEXT NOT NULL,
    embedding_input TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_sha256 CHAR(64) NOT NULL,
    embedding_input_sha256 CHAR(64) NOT NULL,
    loaded_run_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rag_qwen4.embeddings (
    target_id TEXT PRIMARY KEY,
    target_type TEXT NOT NULL CHECK (target_type IN ('document', 'chunk')),
    document_id TEXT REFERENCES rag_qwen4.documents(document_id) ON DELETE RESTRICT,
    chunk_id TEXT REFERENCES rag_qwen4.chunks(chunk_id) ON DELETE RESTRICT,
    embedding vector(2560) NOT NULL,
    model_name TEXT NOT NULL,
    model_revision TEXT NOT NULL,
    normalization TEXT NOT NULL,
    source_sha256 CHAR(64) NOT NULL,
    embedding_input_sha256 CHAR(64) NOT NULL,
    index_version TEXT NOT NULL,
    loaded_run_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (
        (target_type = 'document' AND document_id IS NOT NULL AND chunk_id IS NULL)
        OR (target_type = 'chunk' AND document_id IS NOT NULL AND chunk_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS documents_source_type_idx
    ON rag_qwen4.documents(source_type);
CREATE INDEX IF NOT EXISTS chunks_document_id_idx
    ON rag_qwen4.chunks(document_id);
CREATE INDEX IF NOT EXISTS embeddings_document_id_idx
    ON rag_qwen4.embeddings(document_id);
CREATE INDEX IF NOT EXISTS embeddings_chunk_id_idx
    ON rag_qwen4.embeddings(chunk_id);

-- vector(2560)은 일반 vector HNSW 차원 한계를 넘길 수 있어 halfvec 표현식 인덱스를 사용한다.
-- 원본 벡터는 vector(2560)에 그대로 보존하고, 검색 인덱스만 halfvec으로 만든다.
CREATE INDEX IF NOT EXISTS embeddings_halfvec_cosine_hnsw_idx
    ON rag_qwen4.embeddings
    USING hnsw ((embedding::halfvec(2560)) halfvec_cosine_ops);

