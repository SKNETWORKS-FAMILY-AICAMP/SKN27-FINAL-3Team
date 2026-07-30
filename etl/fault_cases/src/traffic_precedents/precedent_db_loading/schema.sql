CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS precedent_newplusplus;

CREATE TABLE IF NOT EXISTS precedent_newplusplus.blocks (
    block_id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL,
    block_type TEXT NOT NULL,
    semantic_role TEXT NOT NULL,
    block_text TEXT NOT NULL,
    case_number TEXT,
    case_name TEXT,
    court_name TEXT,
    decision_date TEXT,
    internal_grade TEXT NOT NULL CHECK (
        internal_grade IN ('GENERAL_READY_DIRECT', 'SEED_READY')
    ),
    source_metadata JSONB NOT NULL,
    embedding vector(2560) NOT NULL
);

CREATE INDEX IF NOT EXISTS precedent_newplusplus_blocks_record_idx
ON precedent_newplusplus.blocks (record_id);
