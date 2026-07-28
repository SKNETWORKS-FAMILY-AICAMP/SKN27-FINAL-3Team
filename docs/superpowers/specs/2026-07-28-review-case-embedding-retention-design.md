# Review-case embedding retention design

## Goal

Keep every successfully generated review-case embedding as an immutable
historical record. Re-running a seed must call the embedding provider only for
new or changed chunk text.

## Retention rules

1. A chunk with the same `chunk_id`, embedding-space identity, and text hash
   reuses its existing vector without an API request.
2. A changed chunk creates a new embedding revision. The earlier vector is
   retained as history and is not eligible for current search.
3. A chunk absent from a later manifest is marked inactive instead of deleted.
   Its document, chunk, and embeddings remain stored.
4. Search only uses an active chunk whose current text hash matches the
   embedding revision text hash.
5. Seed loading must not issue cascading deletes for `review_case` rows.

## Data model

Add a migration that gives `review_case_chunks` an `is_active` marker and gives
`review_case_chunk_embeddings` a non-null `source_text_hash`. The embedding
primary key becomes `(chunk_id, embedding_model, embedding_version,
source_text_hash)`, allowing multiple revisions of one chunk to coexist in one
embedding space.

The vector index and retrieval query are restricted to active chunks and the
embedding row whose source hash equals the chunk's current `text_hash`.
Existing rows are backfilled from `embedding_meta.text_hash`; rows that cannot
be matched are preserved but not selected for search.

## Seed and embedding flow

The loader upserts manifest rows, marks no-longer-present chunks inactive, and
leaves existing embeddings intact. A document with no active chunks is retained
as historical data. The loader marks a chunk pending only when its current text
hash has no matching embedding revision.

The embedding worker selects only pending current revisions. Each successful
batch writes a new revision and records the source text hash. A retry resumes
from already committed batches and does not re-send them to the provider.

## Error handling

An embedding failure records a failed job and retains every successful batch.
No cleanup path deletes source rows or vectors. Operators can retry the same
seed safely; the pending set is recomputed from current hashes.

## Verification

Tests must prove that unchanged seed reloads make zero provider calls, changed
text creates a second retained revision, removed source chunks become inactive
without deletion, and retrieval excludes inactive or stale-hash vectors.

Database migration tests must cover existing production-shaped rows and the
active-revision index/query contract.
