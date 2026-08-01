CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS precedent_newplusplus;

DO $$
DECLARE
    blocks_relkind "char";
BEGIN
    SELECT relation.relkind
      INTO blocks_relkind
      FROM pg_class AS relation
      JOIN pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
     WHERE namespace.nspname = 'precedent_newplusplus'
       AND relation.relname = 'blocks';

    IF blocks_relkind IS NOT NULL AND blocks_relkind <> 'v' THEN
        RAISE EXCEPTION 'unexpected existing precedent_newplusplus.blocks relation';
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS precedent_newplusplus.seed_releases (
    seed_version TEXT PRIMARY KEY,
    source_npy_sha256 CHAR(64) NOT NULL,
    source_metadata_sha256 CHAR(64) NOT NULL,
    model_id TEXT NOT NULL,
    model_revision TEXT NOT NULL,
    block_count INTEGER NOT NULL CHECK (block_count = 3339),
    case_count INTEGER NOT NULL CHECK (case_count = 825),
    embedding_dimension INTEGER NOT NULL CHECK (embedding_dimension = 2560),
    status TEXT NOT NULL CHECK (status IN ('staged', 'active', 'previous')),
    verified_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS precedent_newplusplus.block_versions (
    seed_version TEXT NOT NULL
        REFERENCES precedent_newplusplus.seed_releases(seed_version),
    block_id TEXT NOT NULL,
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
    embedding vector(2560) NOT NULL,
    PRIMARY KEY (seed_version, block_id)
);

CREATE INDEX IF NOT EXISTS precedent_newplusplus_block_versions_record_idx
ON precedent_newplusplus.block_versions (seed_version, record_id);

CREATE INDEX IF NOT EXISTS precedent_newplusplus_block_versions_type_record_idx
ON precedent_newplusplus.block_versions (seed_version, block_type, record_id);

CREATE TABLE IF NOT EXISTS precedent_newplusplus.active_seed (
    singleton BOOLEAN PRIMARY KEY CHECK (singleton),
    active_seed_version TEXT NOT NULL
        REFERENCES precedent_newplusplus.seed_releases(seed_version),
    previous_seed_version TEXT NULL
        REFERENCES precedent_newplusplus.seed_releases(seed_version),
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE OR REPLACE VIEW precedent_newplusplus.blocks AS
SELECT blocks.block_id,
       blocks.record_id,
       blocks.block_type,
       blocks.semantic_role,
       blocks.block_text,
       blocks.case_number,
       blocks.case_name,
       blocks.court_name,
       blocks.decision_date,
       blocks.internal_grade,
       blocks.source_metadata,
       blocks.embedding
FROM precedent_newplusplus.block_versions AS blocks
JOIN precedent_newplusplus.active_seed AS active
  ON active.singleton IS TRUE
 AND active.active_seed_version = blocks.seed_version;
