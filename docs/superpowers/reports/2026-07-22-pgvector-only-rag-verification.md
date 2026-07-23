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

## Local follow-up verification (2026-07-23)

| Command scope | Result |
|---|---:|
| focused pgvector-only pytest suites | 326 passed in 2.60s |
| Django `chatbot.tests` suite | 38 passed in 1.723s |
| repository pytest excluding independent `etl/fault_cases/rag_runtime` | 911 passed, 38 skipped in 68.20s |
| root Compose config | passed |
| Pilot Compose config with example variables and runtime env resolution disabled | passed |
| active production-code reference scan | 0 references |
| changed-file whitespace validation | passed |

The local full-suite collection still cannot import the independent
`etl/fault_cases/rag_runtime` tests. The shared virtual environment runs Python
3.14.3, while the declared `pyarrow>=20,<22` range has no compatible Windows
wheel. An attempted install fell back to a C++ source build and failed because
the Arrow/CMake build toolchain is not installed. This is an environment
compatibility limitation, not a failure in a collected pgvector-only test.

## Post-PR CI contract correction

The initial Python 3.13 CI run found four stale deployment-contract assertions
that still required the removed search service, its client package, and its
Terraform resource. The production environment template and current `docs/ops`
runbooks now require pgvector-only readiness instead. The corrected deployment
and hardening contract suite passed `22 passed in 4.24s` locally.

The local workspace uses Python 3.14, while the production gate uses Python
3.13 with `requirements-dev.txt`. The latter declares `pyarrow` for the
offline fault-RAG collection tests; its 3.13 wheel is not available in the
local Python 3.14 environment. The final full-suite verdict must therefore be
taken from the GitHub Actions Python 3.13 production gate after this correction
is pushed.

The legacy ES-only seed-loader tests were removed rather than retained as skipped tests. The
pgvector readiness test covers the legal, review-case, and fault-ratio domains and requires their
embedding/HNSW checks to be ready.

## Operational limitations

This verification did not run live re-embedding, database migration, Terraform apply/destroy, or
cloud resource deletion. Those actions require the owner-approved maintenance window and the
cutover runbook.
