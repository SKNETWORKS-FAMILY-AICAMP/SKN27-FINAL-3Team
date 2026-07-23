# Production RAG seed bundle

Production retrieval is PostgreSQL/pgvector-only. A seed bundle contains four
verified JSONL artifacts and a manifest, but the legal loader and the two
source-specific precedent loaders have distinct responsibilities.

| role | pgvector target | readiness requirement |
| --- | --- | --- |
| `legal_chunks` | `law_chunks` | searchable rows and matching embeddings |
| `legal_embeddings` | `law_embeddings` | matching embedding space and HNSW index |
| `review_case_chunks` | review-case source database | source load, re-embedding, and HNSW index |
| `precedent_fault_ratio_chunks` | precedent source database | source load, re-embedding, and HNSW index |

The manifest contract is `production_rag_seed_manifest.v1`. Each artifact has
a safe relative path, SHA-256 digest, byte count, and JSONL row count. The
legal embedding space must use one provider/model/dimension combination and
every vector must have 1024 finite, non-zero coordinates.

## Build and validate the manifest

Create the manifest outside Git after source extraction:

```powershell
python backend/manage.py build_production_rag_seed_manifest `
  --bundle-root C:/secure/rag-seed-2026-07-22 `
  --manifest rag-seed-manifest.json `
  --legal-chunks data/legal_chunks.jsonl `
  --legal-embeddings data/legal_embeddings.jsonl `
  --review-case-chunks data/review_case_chunks.jsonl `
  --precedent-fault-ratio-chunks data/precedent_fault_ratio_chunks.jsonl
```

Validate the approved manifest before any database write:

```powershell
python backend/manage.py verify_production_rag_seed_manifest `
  --manifest C:/secure/rag-seed-2026-07-22/rag-seed-manifest.json

python backend/manage.py load_production_rag_seed `
  --manifest C:/secure/rag-seed-2026-07-22/rag-seed-manifest.json `
  --dry-run
```

`--dry-run` verifies the manifest and its artifacts without creating external
connections or writing data.

## Load and readiness order

1. Take and record a recoverable PostgreSQL backup.
2. Load and re-embed review-case source data, then create/validate its HNSW
   index.
3. Load and re-embed fault-ratio precedent source data, then create/validate
   its HNSW index.
4. Load the legal bundle:

   ```powershell
   python backend/manage.py load_production_rag_seed `
     --manifest C:/secure/rag-seed-2026-07-22/rag-seed-manifest.json `
     --batch-size 500
   ```

   This command loads legal pgvector data. It intentionally reports the
   review-case and fault-ratio source loaders as prerequisites rather than
   writing into a shared fallback index.

5. Require all three domains to be ready:

   ```powershell
   python backend/manage.py verify_pgvector_rag_readiness --format json
   python backend/manage.py smoke_law_ground_search --require-results --format json
   python backend/manage.py smoke_text_ml_case_search --require-pgvector --require-results --format json
   ```

Do not promote when any domain is unavailable, has zero embeddings, or lacks a
valid HNSW index. Repair the source-specific data/embedding/index step and
repeat readiness instead of enabling an alternate search backend.

## Schema and infrastructure removal

After backup and successful readiness evidence, apply
`storage/migrations/20260722_remove_es_search_artifacts.sql` in the approved
maintenance window. External search resource deletion is a separately approved
cloud operation; it is not performed by the seed command.
