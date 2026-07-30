# Vision Local Completion Design

## Goal

Complete every locally executable item from the 2026-07-23 Vision status report without inventing substitutes for missing RunPod artifacts or experiment results.

## Approach

Reuse the existing VideoMAE evaluator and Vision-to-Supervisor runner. Add one standard-library readiness audit that reports artifact checksums, manifest metadata completeness and incident-level split leakage, and observed Qwen input frame counts.

Alternatives rejected:

- Manual checklist only: not repeatable and cannot catch later artifact drift.
- A new experiment-management framework: unnecessary for a four-category POC.

## Data flow

The audit reads the expected exp4 checkpoint directory, fixed split CSV, and Qwen result CSV files. It emits one JSON report under `storage/vision/reports/`. Missing external artifacts are reported as blockers, not fabricated or copied from older experiments.

## Error handling

Unreadable CSV/JSON inputs fail with a clear exception. Missing expected files remain structured readiness failures so the audit can still report every blocker in one run.

## Verification

One focused unit test covers SHA-256 generation, metadata completeness, incident leakage detection, and Qwen frame-count detection. Existing Vision tests protect evaluation and Supervisor handoff behavior.

## Explicit limits
