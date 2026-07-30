CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS precedent_newplusplus;

CREATE TABLE IF NOT EXISTS precedent_newplusplus.blocks (
    block_id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL,
    block_type TEXT NOT NULL,
    block_text TEXT NOT NULL,
    case_number TEXT NOT NULL DEFAULT '',
    case_name TEXT NOT NULL DEFAULT '',
    court_name TEXT NOT NULL DEFAULT '',
    decision_date TEXT NOT NULL DEFAULT '',
    internal_grade TEXT NOT NULL,
    validator_status TEXT NOT NULL,
    enabled_in_general_accident_search BOOLEAN NOT NULL,
    source_metadata JSONB NOT NULL,
    embedding VECTOR(2560) NOT NULL,
    embedding_row_index INTEGER NOT NULL UNIQUE,
    source_sha256 CHAR(64) NOT NULL,
    loaded_run_id TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_newplusplus_blocks_record
ON precedent_newplusplus.blocks(record_id);

CREATE INDEX IF NOT EXISTS idx_newplusplus_blocks_scope
ON precedent_newplusplus.blocks(enabled_in_general_accident_search);

CREATE INDEX IF NOT EXISTS idx_newplusplus_blocks_type_record
ON precedent_newplusplus.blocks(block_type, record_id);

