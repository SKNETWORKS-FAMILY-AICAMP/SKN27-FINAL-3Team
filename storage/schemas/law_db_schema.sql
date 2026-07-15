-- database: :memory:
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create law chunks table
CREATE TABLE IF NOT EXISTS law_chunks (
    chunk_id VARCHAR(255) PRIMARY KEY,
    source_id VARCHAR(100) NOT NULL,
    source_name VARCHAR(255) NOT NULL,
    source_type VARCHAR(50) NOT NULL,
    chunk_type VARCHAR(50) NOT NULL,
    article_no VARCHAR(50),
    appendix_no VARCHAR(50),
    form_no VARCHAR(50),
    provision_text TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    source_url TEXT,
    enforce_date DATE,
    expire_date DATE,
    is_searchable BOOLEAN DEFAULT TRUE,
    domain_tags TEXT[] DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create law embeddings table. Production seed/query space is explicit and 1024-dimensional.
CREATE TABLE IF NOT EXISTS law_embeddings (
    chunk_id VARCHAR(255) REFERENCES law_chunks(chunk_id) ON DELETE CASCADE,
    embedding_vector vector(1024) NOT NULL,
    embedding_provider VARCHAR(50) NOT NULL,
    embedding_model VARCHAR(255) NOT NULL,
    embedding_dimensions INTEGER NOT NULL CHECK (embedding_dimensions = 1024),
    PRIMARY KEY (chunk_id)
);

-- Upgrade older pilot tables without guessing metadata for existing vectors.
-- Seed upserts populate these columns; runtime retrieval ignores NULL/mismatched rows.
ALTER TABLE law_embeddings ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(255);
ALTER TABLE law_embeddings ADD COLUMN IF NOT EXISTS embedding_dimensions INTEGER;

-- Create GIN index for domain_tags array
CREATE INDEX IF NOT EXISTS idx_law_chunks_domain_tags ON law_chunks USING GIN (domain_tags);

-- Create B-Tree index for temporal filtering
CREATE INDEX IF NOT EXISTS idx_law_chunks_temporal ON law_chunks (enforce_date, expire_date);

-- Create HNSW index for fast cosine similarity search (using vector_cosine_ops)
CREATE INDEX IF NOT EXISTS law_embeddings_hnsw_idx 
ON law_embeddings 
USING hnsw (embedding_vector vector_cosine_ops);

