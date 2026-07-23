-- Apply only after taking an application database backup and verifying all
-- review-case and fault-ratio source rows have been re-embedded in pgvector.
-- Run `python backend/manage.py verify_pgvector_rag_readiness --format json`
-- immediately before this migration and retain its ready report as evidence.

BEGIN;

ALTER TABLE IF EXISTS traffic_precedent_chunks
    DROP COLUMN IF EXISTS indexed_to_elasticsearch,
    DROP COLUMN IF EXISTS elasticsearch_index_name;

ALTER TABLE IF EXISTS fault_ratio_precedent_chunks
    DROP COLUMN IF EXISTS indexed_to_elasticsearch,
    DROP COLUMN IF EXISTS elasticsearch_index_name;

ALTER TABLE IF EXISTS review_case_chunks
    DROP COLUMN IF EXISTS indexed_to_elasticsearch,
    DROP COLUMN IF EXISTS elasticsearch_index_name;

DROP TABLE IF EXISTS review_case_elasticsearch_index_jobs;

COMMIT;
