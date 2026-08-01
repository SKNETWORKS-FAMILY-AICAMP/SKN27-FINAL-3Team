# Pilot runtime CRLF and Neo4j diagnostic design

## Objective

Restore the private initial-recovery stage without weakening the exact
precedent-seed identity check, then reproduce the legal Neo4j graph load with
enough credential-safe phase evidence to identify the original exception.
Public cutover, live provider smoke, acceptance monitoring, and the 13 E2E
scenarios remain outside this change.

## Confirmed failure chain

1. The exact RAG load verified the manifest, reused all 904 review-case
   embeddings with zero pending provider calls, and loaded 98,664 legal chunks
   plus 98,664 legal embeddings into PostgreSQL.
2. The first failing command was `load_legal_graph_seed`; its catch-all handler
   replaced the original Neo4j exception with `Neo4j legal graph load failed`.
3. Host evidence contains no Docker OOM event, kernel OOM kill, or Docker daemon
   kill for the failure window.
4. A diagnostic restage was blocked locally by
   `Get-VerifiedPrecedentSeedVersion` even though the decrypted SSM parameter
   contains exactly one valid and exact precedent seed line.
5. The false rejection is platform-specific: Windows AWS CLI/PowerShell text
   uses CRLF between parameter lines, while the current multiline regex expects
   the hash to be followed immediately by `$`. The existing `TrimEnd` only
   removes CR/LF at the end of the complete parameter, not on an interior line.

## Selected parser change

Normalize the retrieved runtime parameter text before applying the existing
strict regex:

- convert CRLF to LF;
- convert any remaining CR to LF;
- keep the exact single-match requirement and lowercase `sha256:` contract;
- do not log or return any other runtime value.

This is preferred over adding `\r?` only to one regex because normalization
makes the environment contract platform-independent while preserving all
existing validation behavior. It is preferred over introducing a new general
environment parser because no additional parsing behavior is needed for this
recovery.

## Test design

Add regression coverage before production code changes. The test must prove
the deployed PowerShell contract normalizes line endings before the strict
precedent-seed regex. Verification must cover these behavioral fixtures with
the same parsing logic:

- one exact LF line is accepted;
- one exact interior CRLF line is accepted;
- duplicate exact lines are rejected;
- a malformed or placeholder value is rejected.

The focused regression test must fail against the current script for the CRLF
fixture, then pass after the minimal normalization change. Existing deployment
contract tests and PowerShell parse validation must remain green.

## Credential-safe Neo4j reproduction

After the parser fix is verified, recreate release `76c713ec92d6` only as an
initial private bootstrap stage. Do not run the full RAG runner again. Download
and verify the exact `9bb155...` manifest-bound bundle, then run a temporary
diagnostic wrapper around the unchanged graph loader.

The wrapper records only:

- phase name: connectivity, constraints, clear, sources, versions, chunks,
  relations, hints, or metadata;
- batch index and row count;
- exception class and Neo4j status/error code;
- a credential-redacted message;
- stage Neo4j health and bounded server-log tail if the failure is server-side.

It must never print credentials, the runtime environment, source document text,
or full Cypher row payloads. On failure it preserves the private stage and
Neo4j log volume for inspection; it does not create a complete marker,
descriptor, evidence file, or public `current` link.

## Decision gates after reproduction

The reproduction result determines a separate implementation decision:

- data or Cypher contract error: add a deterministic failing test and correct
  the loader at the source;
- transient connectivity or readiness error: add bounded readiness/retry at the
  failing boundary;
- Neo4j resource or transaction error: change batch/resource settings only with
  measured evidence;
- no reproduction: retain the diagnostic phase markers and do not resume public
  deployment until the original condition is explained.

Any Neo4j loader change, resource increase, new RAG load, public cutover, paid
live smoke, 600-second acceptance run, or 13-scenario E2E run requires its own
verified next step and applicable production approval.
