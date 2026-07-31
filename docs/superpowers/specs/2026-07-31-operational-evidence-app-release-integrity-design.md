# Pilot app-release operational evidence integrity design

## Goal

Keep the approved `PR merge -> CodePipeline app-only release` path while
making legal operational evidence readable, release-bound, atomic, and
rollback-safe. The recovery and future app releases must reuse the already
approved immutable RAG seed and must not reload databases or call a paid
embedding/provider API.

The immediate production symptom is an `ops-monitor` critical
`monitor_configuration_invalid` result. The shared
`/opt/skn27-pilot/operational-evidence/run_summary.json` is missing and its
parent directory is root-owned mode `0750`, while the monitor runs as the
non-root image user. The app-only release path can nevertheless report
success because it gates only migrations and HTTP live/ready checks.

The current production release is `818199aee975`. It predates the seed-source
descriptor. The first release using this design must therefore not require a
descriptor before the one-time evidence-only recovery has created it. The
bootstrap is an evidence control-plane operation against the still-running
`818199aee975` images; it is not an application deployment.

## Existing contracts that remain authoritative

- Backend and frontend images remain immutable twelve-character Git SHA tags.
- App-only release does not mutate PostgreSQL, pgvector, Neo4j, Redis, RAG
  datasets, Caddy, or Terraform infrastructure.
- `build_legal_operational_evidence` derives a content-free run summary from a
  fully verified seed manifest and local JSONL artifacts. It performs no
  provider call.
- `validate_run_summary` remains the schema, freshness, dataset-version, and
  release-version gate.
- `observe_operational_health --once` remains the final application-level
  deployment gate.
- Full seed loading continues to require the explicit
  `-AllowPaidReviewCaseEmbedding` switch. Evidence-only recovery never accepts
  or forwards that switch.

## Considered approaches

### 1. Reuse an approved immutable seed and rebuild evidence only -- selected

Persist a root-owned locator for the last successfully verified seed. App-only
release downloads that exact versioned S3 prefix, verifies the manifest hash
and bundle, and derives evidence for the candidate release tag. No database
loader or provider command is invoked.

This preserves the existing deployment workflow, establishes a durable
provenance chain, and adds no provider cost. It requires a one-time recovery
command for hosts deployed before the locator existed.

### 2. Run the full seed loader on every app release -- rejected

This would recreate evidence, but it also replaces review-case embeddings and
requires explicit paid-provider consent. It expands the blast radius from an
image-only release to database and graph mutation and is unnecessary when the
immutable artifact is already available.

### 3. Manually copy or synthesize `run_summary.json` -- rejected

This can clear the immediate missing-file symptom but provides no reproducible
manifest verification, can bind evidence to the wrong release, and cannot be
reliably rolled back. It is not an acceptable production recovery path.

## Persistent seed-source contract

The host keeps a small root-owned descriptor outside container-mounted paths:

`/opt/skn27-pilot/state/legal-operational-evidence-source.env`

It contains only three validated, non-secret values:

- `RAG_SEED_S3_URI`: a versioned prefix below the Terraform-managed clean
  bucket `_rag-seed/` namespace and ending in `/`.
- `RAG_SEED_MANIFEST_RELATIVE_PATH`: a basename-style JSON relative path
  accepted by the current seed loader contract.
- `RAG_SEED_MANIFEST_SHA256`: the exact lowercase SHA-256 of the manifest.

The directory is root-owned mode `0700`; the descriptor is written through a
temporary file, set to mode `0600`, and atomically renamed only after the seed
manifest and complete bundle have been verified. It is not mounted into any
application container and is never written to command output.

`Load-Rag-Seed-Pilot.ps1` records or refreshes this descriptor after a
successful verified full seed load. This means a normal reviewed full deploy
automatically enables future evidence-only app releases.

## Evidence-only recovery command

A dedicated operator command accepts the same URI, manifest path, manifest
SHA, and release tag validation boundaries as the full loader, but has no paid
consent switch and invokes no loader. It performs these steps under the shared
maintenance lock:

1. Resolve the current release and require its current image tag to equal the
   requested release tag.
2. Download the approved versioned seed to a private temporary directory.
3. Verify the supplied manifest SHA and validate the complete bundle using the
   currently running immutable backend image.
4. Build a content-free run summary using the current
   `LEGAL_DATASET_VERSION`, `LEGAL_DATASET_VERIFIED_AT`, and release tag.
5. Validate the temporary summary for schema, freshness, dataset version, and
   release version.
6. Atomically install it as the shared `run_summary.json`.
7. Persist the verified seed-source descriptor atomically.
8. Run one operational-health preflight and require overall `status=pass`.
9. Delete the downloaded seed in all success and failure paths.

If the manifest or bundle is missing or incompatible, the command fails
without altering the shared evidence or descriptor. Only that outcome can
justify a separate decision to run the paid full seed loader.

## Permissions and container boundary

The shared evidence directory is root-owned mode `0755`, and
`run_summary.json` is root-owned mode `0444`. The non-root monitor therefore
has traversal and read access but cannot create, replace, or modify evidence.
Temporary evidence files are created by the host and are never writable by an
application container.

Both full deployment and full seed loading use the same permissions. Static
tests reject the previous `0750` shared-directory mode.

## App-only release protocol

The pipeline keeps the existing manual approval and uses the current EC2
instance role for S3 access. The CodeBuild release role receives no seed bucket
permission and no application secret.

Under the existing maintenance lock, the remote release performs:

1. Validate the candidate Git SHA tag, current release directory, current
   release tag, repositories, and seed-source descriptor.
2. Snapshot the running backend/frontend image IDs under the actual previous
   release tag and snapshot the existing shared evidence, including whether it
   was absent.
3. Download the descriptor's exact immutable seed to a private temporary
   directory, verify the manifest SHA, and validate the complete bundle.
4. Pull candidate backend/frontend images and run `migrate --check`.
5. With the candidate backend image, build and validate candidate evidence in
   a host-owned temporary file. No load command and no provider flag is
   permitted.
6. Stop the app processes that share the backend image, including
   `ops-monitor`, then set the candidate release tag and recreate backend and
   frontend.
7. Require HTTPS live and ready checks.
8. Atomically promote candidate evidence, then start workers and monitor.
9. Run `observe_operational_health --once`, parse its JSON, and apply the
   immediate transaction gate below before reporting pipeline success.

The monitor is stopped while image tag and evidence are switched, avoiding a
window in which it can observe mixed provenance.

## Immediate transaction gate and ten-minute acceptance gate

Deployment mutation and operational acceptance are separate gates.
`Deploy-Pilot.ps1`, `Release-PilotApp-FromPipeline.sh`, and
`Rollback-Pilot.ps1` must share the same immediate-gate evaluator rather than
embedding three different interpretations of the health snapshot. The
ten-minute acceptance command uses the same evaluator in strict-pass mode.

The immediate transaction gate runs after the candidate evidence, images,
workers, and monitor are active. It fails and rolls back when any of the
following is true:

- live or ready HTTP checks fail;
- the health snapshot is not valid `operational_health` JSON;
- `status=fail` or any `critical` alert is present;
- legal data is missing, invalid, stale, failed, or not bound to the exact
  candidate dataset and release versions;
- any warning other than `queue_backlog` is present.

The immediate gate may accept `status=warn` only when every alert is the
warning-level `queue_backlog` code and legal data is otherwise exact and
successful. This narrow exception prevents an in-flight queue item observed
during worker restart from causing a false rollback. It does not allow
`queue_oldest_age_exceeded`, `worker_lease_stale`, `worker_retrying`, worker or
provider failures, or any legal-data warning.

Pipeline transaction success means only that the atomic release switch is
safe. It is not production acceptance. Acceptance requires a separate
observation window lasting at least 600 seconds in which every sampled
operational-health snapshot has `status=pass`, no alerts, and exact legal
dataset and release versions. A warning resets the consecutive-pass window.
A critical result invokes the approved rollback path; a non-critical warning
that does not clear keeps G8 and the thirteen E2E scenarios blocked and
requires operator investigation.

## Automatic rollback and failure behavior

The error trap is armed before any candidate mutation. On failure it:

1. Restores `.compose.env` to the actual previous release tag, not a synthetic
   rollback tag.
2. Restores the prior shared evidence atomically, or restores its prior absent
   state.
3. Recreates backend, frontend, workers, and monitor from the snapshotted
   previous images.
4. Returns the original nonzero status so CodePipeline fails closed.

Downloaded seed data, candidate evidence, and evidence backups are removed on
both success and failure. Logs may contain status, tag, and safe validation
errors, but never seed contents, runtime secrets, provider responses, OCR,
prompts, or user data.

## Manual rollback evidence transaction

`Rollback-Pilot.ps1` uses the same maintenance lock and evidence boundary as
the automatic rollback. Before it stops or recreates any service it must:

1. Resolve the requested target release directory and require its
   `.compose.env` release tag to equal the requested release tag.
2. Require the target release's `operational-evidence/run_summary.json`.
3. Validate that summary with the target backend image for schema, freshness,
   dataset version, and the exact target release version.
4. Snapshot the currently shared evidence, including its absent state, into a
   root-owned temporary backup.

After switching the images and release tag, the command installs the validated
target evidence as root-owned mode `0444` through a temporary file and atomic
rename, starts workers and monitor, and runs the same immediate transaction
gate. It updates `/opt/skn27-pilot/current` only after that gate succeeds.

If any rollback step fails, the rollback error trap restores the pre-command
release, shared evidence, services, and current symlink before returning the
original nonzero status. A missing or invalid target evidence file prevents
all mutation; the command must never roll an application release back while
leaving evidence bound to another release.

## Test strategy

1. Static contract tests require shared-directory `0755`, evidence `0444`, and
   the root-only descriptor path and modes.
2. Tests require full seed load to write the descriptor only after manifest
   and evidence validation.
3. Recovery-command tests require manifest and bundle verification, evidence
   build/validation, atomic promotion, cleanup, and operational-health pass.
4. Negative tests reject database load commands, paid-provider flags, and
   provider smoke from the evidence-only path.
5. App-release tests require descriptor validation, candidate-bound evidence,
   monitor stop/switch/start ordering, a fail-closed critical gate, and the
   narrow immediate `queue_backlog` warning exception.
6. Rollback tests require the real previous tag and prior evidence state to be
   restored before services restart.
7. Manual-rollback tests require target evidence validation before mutation,
   atomic shared-evidence restoration, monitor preflight, and restoration of
   the pre-command release and evidence when the rollback itself fails.
8. Acceptance tests require at least 600 seconds of consecutive `pass`
   snapshots; warnings reset the window and critical alerts select rollback.
9. Focused Python infrastructure and evidence tests run first, followed by the
   full pytest suite, frontend tests/build, Terraform formatting/validation,
   and shell/YAML syntax checks.
10. Production acceptance requires the shared summary to validate, operational
   health to stay `pass` for ten minutes, and only then may the remaining G8
   checks and thirteen E2E scenarios begin.

## Operational activation sequence

1. Merge this hotfix into the latest `dev` commit, but do not approve or start
   the app-release pipeline yet.
2. From that reviewed source, run only the evidence-recovery operator command
   against the still-running production release `818199aee975`, passing the
   previously approved seed URI/path/SHA and `-ReleaseTag 818199aee975`. The
   command must verify that the running image tag is exactly `818199aee975`.
3. Confirm the recovery created both the shared validated evidence and the
   root-only seed-source descriptor without changing images, databases, RAG
   data, or providers.
4. Require the immediate critical preflight, then observe at least 600 seconds
   of consecutive operational-health `pass` snapshots for `818199aee975`.
5. Only after that bootstrap acceptance may an operator approve the new
   app-release pipeline. The new release must exercise descriptor validation,
   candidate evidence generation, atomic promotion, and fail-closed rollback.
6. Apply the immediate transaction gate to the new release, then complete a
   separate minimum-600-second consecutive-`pass` acceptance window before G8
   and the thirteen E2E scenarios begin.
7. If the approved seed cannot be retrieved or verified, stop and request
   explicit approval before any full seed reload or paid provider call.
