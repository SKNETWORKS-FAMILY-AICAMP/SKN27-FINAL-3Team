-- Preserve review-case embedding revisions across seed reloads.
-- This migration is intentionally idempotent and never removes source rows or vectors.

BEGIN;

LOCK TABLE review_case_chunks IN ACCESS EXCLUSIVE MODE;
LOCK TABLE review_case_chunk_embeddings IN ACCESS EXCLUSIVE MODE;

ALTER TABLE review_case_chunks
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE review_case_chunk_embeddings
    ADD COLUMN IF NOT EXISTS source_text_hash TEXT;

UPDATE review_case_chunk_embeddings AS embedding
SET source_text_hash = COALESCE(
    NULLIF(embedding.embedding_meta->>'text_hash', ''),
    'legacy-unverified:' || embedding.ctid::text
)
WHERE embedding.source_text_hash IS NULL
   OR btrim(embedding.source_text_hash) = '';

ALTER TABLE review_case_chunk_embeddings
    ALTER COLUMN source_text_hash SET NOT NULL;

DO $migration$
DECLARE
    primary_key_name TEXT;
    primary_key_definition TEXT;
BEGIN
    SELECT constraint_record.conname, pg_get_constraintdef(constraint_record.oid)
    INTO primary_key_name, primary_key_definition
    FROM pg_constraint AS constraint_record
    WHERE constraint_record.conrelid = 'review_case_chunk_embeddings'::regclass
      AND constraint_record.contype = 'p';

    IF primary_key_name IS NOT NULL
       AND primary_key_definition IS DISTINCT FROM
           'PRIMARY KEY (chunk_id, embedding_model, embedding_version, source_text_hash)' THEN
        EXECUTE format(
            'ALTER TABLE review_case_chunk_embeddings DROP CONSTRAINT %I',
            primary_key_name
        );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint AS constraint_record
        WHERE constraint_record.conrelid = 'review_case_chunk_embeddings'::regclass
          AND constraint_record.contype = 'p'
    ) THEN
        ALTER TABLE review_case_chunk_embeddings
            ADD PRIMARY KEY (
                chunk_id,
                embedding_model,
                embedding_version,
                source_text_hash
            );
    END IF;
END
$migration$;

CREATE INDEX IF NOT EXISTS idx_review_case_chunks_active
ON review_case_chunks (is_active)
WHERE is_active;

COMMIT;
