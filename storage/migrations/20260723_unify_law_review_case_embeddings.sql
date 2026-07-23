-- Issue #291: move review-case embeddings into the validated law embedding space.
--
-- The first run preserves old 1536-dimensional rows in a dated backup table,
-- then empties the active table before changing the pgvector typmod. A repeated
-- run sees vector(1024) and exits without truncating the newly embedded rows.
-- Re-embedding itself is a separate, explicitly approved operation.

BEGIN;

LOCK TABLE review_case_chunk_embeddings IN ACCESS EXCLUSIVE MODE;

DO $migration$
DECLARE
    active_rows BIGINT;
    backup_rows BIGINT;
    constraint_name TEXT;
    vector_type TEXT;
BEGIN
    SELECT format_type(attribute.atttypid, attribute.atttypmod)
    INTO vector_type
    FROM pg_attribute attribute
    JOIN pg_class relation ON relation.oid = attribute.attrelid
    WHERE relation.relname = 'review_case_chunk_embeddings'
      AND attribute.attname = 'embedding_vector'
      AND NOT attribute.attisdropped;

    IF vector_type = 'vector(1024)' THEN
        RETURN;
    END IF;
    IF vector_type IS DISTINCT FROM 'vector(1536)' THEN
        RAISE EXCEPTION 'unsupported_review_case_vector_type: %', vector_type;
    END IF;

    EXECUTE
        'CREATE TABLE IF NOT EXISTS '
        'review_case_chunk_embeddings_1536_backup_20260723 '
        '(LIKE review_case_chunk_embeddings INCLUDING ALL)';
    EXECUTE
        'INSERT INTO review_case_chunk_embeddings_1536_backup_20260723 '
        'SELECT * FROM review_case_chunk_embeddings '
        'WHERE NOT EXISTS ('
        'SELECT 1 FROM review_case_chunk_embeddings_1536_backup_20260723)';

    SELECT COUNT(*) INTO active_rows FROM review_case_chunk_embeddings;
    EXECUTE
        'SELECT COUNT(*) FROM '
        'review_case_chunk_embeddings_1536_backup_20260723'
        INTO backup_rows;
    IF active_rows <> backup_rows AND active_rows > 0 THEN
        RAISE EXCEPTION
            'backup_row_count_mismatch: active=%, backup=%',
            active_rows,
            backup_rows;
    END IF;

    DROP INDEX IF EXISTS idx_review_case_chunk_embeddings_cosine_hnsw;
    TRUNCATE TABLE review_case_chunk_embeddings;

    FOR constraint_name IN
        SELECT constraint_record.conname
        FROM pg_constraint constraint_record
        WHERE constraint_record.conrelid =
              'review_case_chunk_embeddings'::regclass
          AND constraint_record.contype = 'c'
          AND pg_get_constraintdef(constraint_record.oid)
              ILIKE '%embedding_dim%'
    LOOP
        EXECUTE format(
            'ALTER TABLE review_case_chunk_embeddings DROP CONSTRAINT %I',
            constraint_name
        );
    END LOOP;

    ALTER TABLE review_case_chunk_embeddings
        ALTER COLUMN embedding_vector TYPE vector(1024)
            USING NULL::vector(1024),
        ALTER COLUMN embedding_dim SET DEFAULT 1024;

    ALTER TABLE review_case_chunk_embeddings
        ADD CHECK (embedding_dim = 1024);

    COMMENT ON TABLE review_case_chunk_embeddings_1536_backup_20260723 IS
        'Pre-#291 review-case embeddings; retain until 1024-dimensional re-embedding is validated.';
END
$migration$;

COMMIT;
