# pgvector-only RAG verification report

Date: 2026-07-22

## Implemented contract

- Legal retrieval has no lexical or Django-table fallback.
- text-ML retrieval calls unified review-case and fault-ratio pgvector retrievers.
- The readiness command verifies legal, review-case, and fault-ratio embedding/HNSW state.
- Seed and Pilot smoke contracts use `--require-pgvector`; no seed action recreates a separate search index.
- Local Compose, Pilot Compose, Terraform, runtime templates, Python requirements, and DB schemas no
  longer provision a separate search service.

## Test evidence

| Command scope | Result |
|---|---:|
| text-ML agent test suite after ES module deletion | 50 passed |
| legal evaluation and environment tests | 34 passed |
| post-rebase core RAG and Pilot infrastructure suite | 305 passed in 22.16s (241 core RAG + 64 infrastructure) |
| post-rebase Django `chatbot` integration suite | 346 passed in 40.534s |
| active runtime/config reference scan | 0 references to Elasticsearch, OpenSearch, BM25, Nori, or lexical fallback |
| changed-file whitespace validation | `git diff --check` passed |

The legacy ES-only seed-loader tests were removed rather than retained as skipped tests. The
pgvector readiness test covers the legal, review-case, and fault-ratio domains and requires their
embedding/HNSW checks to be ready.

## Operational limitations

This verification did not run live re-embedding, database migration, Terraform apply/destroy, or
cloud resource deletion. Those actions require the owner-approved maintenance window and the
cutover runbook.
