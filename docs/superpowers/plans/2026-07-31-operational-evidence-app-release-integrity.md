# Operational Evidence App-Release Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make full deploy, app-only release, evidence-only recovery, and manual rollback preserve release-bound legal operational evidence with a shared immediate gate and a separate ten-minute acceptance gate.

**Architecture:** Put health-gate policy in one pure Python service and expose it through the existing `observe_operational_health` management command. Operator PowerShell and pipeline Bash scripts call that shared evaluator; they never duplicate alert policy. Persist a root-only immutable-seed descriptor, rebuild content-free evidence without loaders or providers, and switch evidence with images under the existing maintenance lock.

**Tech Stack:** Python 3.13+, Django management commands and `TestCase`, PowerShell 7.2+, Bash, Docker Compose, AWS SSM/S3/ECR, pytest static infrastructure contracts.

## Global Constraints

- Production bootstrap target is exactly `818199aee975`; do not approve the new app pipeline before evidence-only recovery and a minimum 600-second consecutive-pass window complete.
- Backend and frontend image tags remain lowercase twelve-character Git SHAs.
- Evidence-only paths must not call database loaders, RAG loaders, embeddings, LLMs, OCR, Vision, or any paid provider.
- Full seed loading remains the only path that accepts `-AllowPaidReviewCaseEmbedding`.
- The descriptor is `/opt/skn27-pilot/state/legal-operational-evidence-source.env`, root-owned `0600` in a root-owned `0700` directory.
- The shared evidence directory is root-owned `0755`; `run_summary.json` is root-owned `0444` and atomically renamed on the same filesystem.
- Immediate transaction mode accepts `pass` with no alerts, or `warn` only when every alert is warning-level `queue_backlog` and legal provenance is exact.
- Acceptance mode accepts only `pass`, no alerts, exact dataset/release provenance, continuously for at least 600 seconds.
- Any critical result fails closed; a non-critical acceptance warning resets the consecutive-pass window.
- No log or artifact may expose seed content, secrets, provider responses, OCR, prompts, user content, or raw exception text.
- Implementation and local/CI verification must use deterministic fixtures only. Production recovery, pipeline approval, and paid smoke remain separate operator-authorized steps.

---

### Task 1: Shared operational-health release gate

**Files:**
- Create: `app/services/operational_health_gate.py`
- Create: `test/test_operational_health_gate.py`
- Modify: `backend/chatbot/management/commands/observe_operational_health.py`
- Modify: `backend/chatbot/test_operational_observability.py`

**Interfaces:**
- Consumes: an `operational_health.v1` mapping plus exact expected dataset and release versions.
- Produces: `evaluate_operational_health_gate(snapshot, *, expected_dataset_version, expected_release_version, mode) -> dict[str, object]` with `contract_version`, `mode`, `decision`, and privacy-safe `reason_codes`.
- Produces: `observe_operational_health --once --gate-mode transaction|acceptance`; default `--once` and `--loop` output remain backward compatible.

- [ ] **Step 1: Write the pure evaluator RED tests**

Add table-driven tests covering the exact policy:

```python
from app.services.operational_health_gate import evaluate_operational_health_gate


def _snapshot(*, status="pass", alerts=None, release="818199aee975"):
    return {
        "contract_version": "operational_health.v1",
        "event_type": "operational_health",
        "status": status,
        "legal_data": {
            "status": "success",
            "issue_count": 0,
            "dataset_version": "dataset-v1",
            "release_version": release,
        },
        "alerts": list(alerts or []),
    }


def test_transaction_gate_accepts_only_transient_queue_backlog_warning():
    result = evaluate_operational_health_gate(
        _snapshot(
            status="warn",
            alerts=[{"code": "queue_backlog", "severity": "warning"}],
        ),
        expected_dataset_version="dataset-v1",
        expected_release_version="818199aee975",
        mode="transaction",
    )
    assert result["decision"] == "pass"


def test_transaction_gate_rejects_every_other_warning():
    for code in ("queue_oldest_age_exceeded", "worker_lease_stale", "worker_retrying", "legal_data_stale"):
        result = evaluate_operational_health_gate(
            _snapshot(status="warn", alerts=[{"code": code, "severity": "warning"}]),
            expected_dataset_version="dataset-v1",
            expected_release_version="818199aee975",
            mode="transaction",
        )
        assert result["decision"] == "fail"


def test_acceptance_gate_resets_on_warning_and_fails_on_critical():
    warning = evaluate_operational_health_gate(
        _snapshot(status="warn", alerts=[{"code": "queue_backlog", "severity": "warning"}]),
        expected_dataset_version="dataset-v1",
        expected_release_version="818199aee975",
        mode="acceptance",
    )
    critical = evaluate_operational_health_gate(
        _snapshot(status="fail", alerts=[{"code": "provider_failure", "severity": "critical"}]),
        expected_dataset_version="dataset-v1",
        expected_release_version="818199aee975",
        mode="acceptance",
    )
    assert warning["decision"] == "reset"
    assert critical["decision"] == "fail"
```

Also reject malformed contracts, non-list alerts, unknown status, missing legal evidence, nonzero issue counts, and dataset/release mismatch.

- [ ] **Step 2: Run the evaluator tests and verify RED**

Run: `python -m pytest -q test/test_operational_health_gate.py`

Expected: collection fails because `app.services.operational_health_gate` does not exist.

- [ ] **Step 3: Implement the minimal pure evaluator**

Use only safe fixed reason codes:

```python
from collections.abc import Mapping


HEALTH_GATE_CONTRACT_VERSION = "operational_health_gate.v1"
ALLOWED_TRANSACTION_WARNINGS = frozenset({"queue_backlog"})


def evaluate_operational_health_gate(snapshot, *, expected_dataset_version, expected_release_version, mode):
    if mode not in {"transaction", "acceptance"}:
        raise ValueError("unsupported operational health gate mode")
    reasons = []
    if not isinstance(snapshot, Mapping):
        reasons.append("snapshot_invalid")
        snapshot = {}
    if snapshot.get("contract_version") != "operational_health.v1" or snapshot.get("event_type") != "operational_health":
        reasons.append("snapshot_contract_invalid")
    status = snapshot.get("status")
    if status not in {"pass", "warn", "fail"}:
        reasons.append("snapshot_status_invalid")
    legal = snapshot.get("legal_data")
    if not isinstance(legal, Mapping):
        reasons.append("legal_data_invalid")
        legal = {}
    if legal.get("status") != "success" or legal.get("issue_count") != 0:
        reasons.append("legal_data_not_ready")
    if legal.get("dataset_version") != expected_dataset_version:
        reasons.append("dataset_version_mismatch")
    if legal.get("release_version") != expected_release_version:
        reasons.append("release_version_mismatch")
    alerts = snapshot.get("alerts")
    if not isinstance(alerts, list) or any(not isinstance(item, Mapping) for item in alerts):
        reasons.append("alerts_invalid")
        alerts = []
    if reasons:
        decision = "fail"
    elif mode == "transaction":
        queue_only = bool(alerts) and all(
            item.get("code") in ALLOWED_TRANSACTION_WARNINGS and item.get("severity") == "warning"
            for item in alerts
        )
        decision = "pass" if (status == "pass" and not alerts) or (status == "warn" and queue_only) else "fail"
        if decision == "fail":
            reasons.append("transaction_gate_rejected")
    elif status == "pass" and not alerts:
        decision = "pass"
    elif status == "fail" or any(item.get("severity") == "critical" for item in alerts):
        decision = "fail"
        reasons.append("acceptance_critical")
    else:
        decision = "reset"
        reasons.append("acceptance_window_reset")
    return {
        "contract_version": HEALTH_GATE_CONTRACT_VERSION,
        "mode": mode,
        "decision": decision,
        "reason_codes": sorted(set(reasons)),
    }
```

- [ ] **Step 4: Run the evaluator tests and verify GREEN**

Run: `python -m pytest -q test/test_operational_health_gate.py`

Expected: all gate-policy cases pass.

- [ ] **Step 5: Write management-command RED tests**

Extend `OperationalObservabilityTests` to assert:

```python
@mock.patch("chatbot.management.commands.observe_operational_health.build_operational_health_snapshot")
def test_transaction_gate_exits_cleanly_for_queue_backlog_only(self, snapshot_builder):
    snapshot_builder.return_value = {
        "contract_version": "operational_health.v1",
        "event_type": "operational_health",
        "status": "warn",
        "legal_data": {
            "status": "success",
            "issue_count": 0,
            "dataset_version": "dataset-v1",
            "release_version": "release-abc123",
        },
        "alerts": [{"code": "queue_backlog", "severity": "warning"}],
    }
    stdout = StringIO()
    call_command("observe_operational_health", "--once", "--gate-mode", "transaction", stdout=stdout)
    rendered = json.loads(stdout.getvalue())
    self.assertEqual(rendered["gate"]["decision"], "pass")

@mock.patch("chatbot.management.commands.observe_operational_health.build_operational_health_snapshot")
def test_acceptance_gate_raises_safe_error_for_critical_snapshot(self, snapshot_builder):
    snapshot_builder.return_value = {
        "contract_version": "operational_health.v1",
        "event_type": "operational_health",
        "status": "fail",
        "legal_data": {
            "status": "success",
            "issue_count": 0,
            "dataset_version": "dataset-v1",
            "release_version": "release-abc123",
        },
        "alerts": [{"code": "provider_failure", "severity": "critical"}],
    }
    with self.assertRaisesMessage(CommandError, "operational health gate rejected snapshot"):
        call_command("observe_operational_health", "--once", "--gate-mode", "acceptance")
```

Assert `--gate-mode` is rejected with `--loop`, and error text never contains mocked raw exception data.

- [ ] **Step 6: Run command tests and verify RED**

Run: `python backend/manage.py test chatbot.test_operational_observability.OperationalObservabilityTests -v 1`

Expected: failure because `--gate-mode` is not registered.

- [ ] **Step 7: Add the gate-mode adapter to the existing command**

Keep default output unchanged. With a gate mode, add a top-level `gate` public envelope to the emitted snapshot and raise the fixed `CommandError` only for `decision=fail`; return `decision=reset` to acceptance callers without leaking unsafe details.

```python
parser.add_argument("--gate-mode", choices=("transaction", "acceptance"))

snapshot = self._snapshot(options)
if options["gate_mode"]:
    if options["loop"]:
        raise CommandError("--gate-mode cannot be combined with --loop")
    snapshot = dict(snapshot)
    snapshot["gate"] = evaluate_operational_health_gate(
        snapshot,
        expected_dataset_version=getattr(settings, "LEGAL_DATASET_VERSION", ""),
        expected_release_version=getattr(settings, "APP_RELEASE_VERSION", ""),
        mode=options["gate_mode"],
    )
self.stdout.write(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
if snapshot.get("gate", {}).get("decision") == "fail":
    raise CommandError("operational health gate rejected snapshot")
```

- [ ] **Step 8: Run focused gate tests and verify GREEN**

Run: `python -m pytest -q test/test_operational_health_gate.py`

Run: `python backend/manage.py test chatbot.test_operational_observability.OperationalObservabilityTests -v 1`

Expected: both commands pass.

- [ ] **Step 9: Prepare the Task 1 commit handoff**

```powershell
git add app/services/operational_health_gate.py test/test_operational_health_gate.py backend/chatbot/management/commands/observe_operational_health.py backend/chatbot/test_operational_observability.py
git diff --cached --check
git commit -m "fix: separate operational release health gates"
```

---

### Task 2: Immutable seed descriptor and evidence-only bootstrap recovery

**Files:**
- Create: `deploy/aws-pilot/Recover-PilotOperationalEvidence.ps1`
- Modify: `deploy/aws-pilot/Load-Rag-Seed-Pilot.ps1`
- Modify: `test/test_aws_pilot_infrastructure.py`

**Interfaces:**
- Consumes: `-RagSeedS3Uri`, `-ReleaseTag`, `-RagSeedManifestRelativePath`, `-RagSeedManifestSha256`, Terraform outputs, and the existing maintenance lock.
- Produces: root-only descriptor containing exactly `RAG_SEED_S3_URI`, `RAG_SEED_MANIFEST_RELATIVE_PATH`, and `RAG_SEED_MANIFEST_SHA256`.
- Produces: release-local and shared validated `run_summary.json` for the exact running release without loaders or provider flags.

- [ ] **Step 1: Write descriptor and recovery RED contracts**

Add tests that require:

```python
def test_full_seed_load_persists_root_only_seed_descriptor_after_evidence_validation():
    loader = _read_deploy("Load-Rag-Seed-Pilot.ps1")
    validate = loader.index("etl.legal.validate_run_summary --summary")
    descriptor_move = loader.index("mv -f `$SEED_SOURCE_TMP `$SEED_SOURCE_FILE")
    assert validate < descriptor_move
    assert "install -d -m 0700 /opt/skn27-pilot/state" in loader
    assert "chmod 0600 `$SEED_SOURCE_TMP" in loader
    assert "install -d -m 0755 `$EVIDENCE_DIR" in loader
    assert "install -d -m 0750 `$EVIDENCE_DIR" not in loader
    assert loader.count("RAG_SEED_S3_URI=") == 1


def test_evidence_recovery_is_locked_verified_atomic_and_provider_free():
    recovery = _read_deploy("Recover-PilotOperationalEvidence.ps1")
    for token in (
        "/var/lock/skn27-pilot-maintenance.lock",
        "sha256sum -c -",
        "verify_production_rag_seed_manifest",
        "build_legal_operational_evidence",
        "etl.legal.validate_run_summary",
        "mv -f `$SHARED_EVIDENCE_TMP `$SHARED_EVIDENCE_FILE",
        "observe_operational_health --once --gate-mode transaction",
    ):
        assert token in recovery
    for forbidden in (
        "AllowPaidReviewCaseEmbedding",
        "allow-paid-provider-call",
        "load_review_case_pgvector_seed",
        "load_production_rag_seed",
        "load_legal_graph_seed",
    ):
        assert forbidden not in recovery
```

Require running `.compose.env` tag equality before S3 download or shared-file mutation, same-filesystem temporary files, cleanup traps, descriptor value validation, and shared directory mode `0755`.

- [ ] **Step 2: Run infrastructure tests and verify RED**

Run: `python -m pytest -q test/test_aws_pilot_infrastructure.py -k "descriptor or evidence_recovery"`

Expected: failure because the recovery script and descriptor writes do not exist.

- [ ] **Step 3: Add the descriptor write to the full seed loader**

Change the release evidence directory from `0750` to `0755`. After bundle/evidence validation and before cleanup, write the three literal keys with `printf`, reject newline/control characters, set `0600`, and atomically rename inside `/opt/skn27-pilot/state`. Do not echo descriptor content.

```bash
SEED_SOURCE_DIR='/opt/skn27-pilot/state'
SEED_SOURCE_FILE="$SEED_SOURCE_DIR/legal-operational-evidence-source.env"
SEED_SOURCE_TMP="$SEED_SOURCE_DIR/.legal-operational-evidence-source.env.tmp"
install -d -m 0700 "$SEED_SOURCE_DIR"
printf 'RAG_SEED_S3_URI=%s\nRAG_SEED_MANIFEST_RELATIVE_PATH=%s\nRAG_SEED_MANIFEST_SHA256=%s\n' \
  '__RAG_SEED_S3_URI__' '__MANIFEST_RELATIVE_PATH__' '__MANIFEST_SHA256__' > "$SEED_SOURCE_TMP"
chmod 0600 "$SEED_SOURCE_TMP"
mv -f "$SEED_SOURCE_TMP" "$SEED_SOURCE_FILE"
```

- [ ] **Step 4: Implement the recovery operator command**

Follow existing `Get-SsmCommandResult` and Terraform-output patterns. The remote command must:

```bash
set -euo pipefail
exec 9>/var/lock/skn27-pilot-maintenance.lock
flock -w 60 9
CURRENT_RELEASE="$(readlink -f /opt/skn27-pilot/current)"
CURRENT_TAG="$(sed -n 's/^RELEASE_TAG=//p' "$CURRENT_RELEASE/.compose.env")"
test "$CURRENT_TAG" = '__RELEASE_TAG__'
```

Download to a private SHA-named directory, verify manifest SHA and full bundle with the running immutable backend image, build release-local evidence, validate it, atomically install shared evidence at `0444`, atomically write the descriptor, invoke transaction gate once, and clean the downloaded seed on every exit. The error trap must restore prior release-local/shared evidence and descriptor state.

```bash
RELEASE_EVIDENCE_DIR="$CURRENT_RELEASE/operational-evidence"
RELEASE_EVIDENCE_TMP="$RELEASE_EVIDENCE_DIR/.run_summary.json.tmp"
RELEASE_EVIDENCE_FILE="$RELEASE_EVIDENCE_DIR/run_summary.json"
SHARED_EVIDENCE_DIR='/opt/skn27-pilot/operational-evidence'
SHARED_EVIDENCE_TMP="$SHARED_EVIDENCE_DIR/.run_summary.json.tmp"
SHARED_EVIDENCE_FILE="$SHARED_EVIDENCE_DIR/run_summary.json"
install -d -m 0755 "$SHARED_EVIDENCE_DIR"
"${compose[@]}" run --rm --no-deps -v "$RAG_DIR:/run/production-rag-seed:ro" backend \
  python backend/manage.py build_legal_operational_evidence \
  --manifest '/run/production-rag-seed/__MANIFEST_RELATIVE_PATH__' \
  --dataset-version "$LEGAL_DATASET_VERSION" --release-version "$CURRENT_TAG" \
  --verified-at "$LEGAL_DATASET_VERIFIED_AT" > "$RELEASE_EVIDENCE_TMP"
"${compose[@]}" run --rm --no-deps -v "$RELEASE_EVIDENCE_DIR:/run/release-evidence:ro" backend \
  python -m etl.legal.validate_run_summary --summary /run/release-evidence/.run_summary.json.tmp \
  --max-age-hours "$LEGAL_MAX_AGE_HOURS" --expected-dataset-version "$LEGAL_DATASET_VERSION" \
  --expected-release-version "$CURRENT_TAG"
chmod 0444 "$RELEASE_EVIDENCE_TMP"
mv -f "$RELEASE_EVIDENCE_TMP" "$RELEASE_EVIDENCE_FILE"
install -m 0444 "$RELEASE_EVIDENCE_FILE" "$SHARED_EVIDENCE_TMP"
mv -f "$SHARED_EVIDENCE_TMP" "$SHARED_EVIDENCE_FILE"
"${compose[@]}" run --rm --no-deps ops-monitor python backend/manage.py observe_operational_health --once --gate-mode transaction
```

- [ ] **Step 5: Run recovery tests and verify GREEN**

Run: `python -m pytest -q test/test_aws_pilot_infrastructure.py -k "descriptor or evidence_recovery or rag_seed_builds_release_bound_operational_evidence"`

Expected: all selected tests pass.

- [ ] **Step 6: Prepare the Task 2 commit handoff**

```powershell
git add deploy/aws-pilot/Recover-PilotOperationalEvidence.ps1 deploy/aws-pilot/Load-Rag-Seed-Pilot.ps1 test/test_aws_pilot_infrastructure.py
git diff --cached --check
git commit -m "fix: bootstrap release-bound operational evidence"
```

---

### Task 3: Full deploy and app-only atomic evidence release

**Files:**
- Modify: `deploy/aws-pilot/Deploy-Pilot.ps1`
- Modify: `deploy/aws-pilot/Release-PilotApp-FromPipeline.sh`
- Modify: `test/test_aws_pilot_infrastructure.py`
- Modify: `test/test_codebuild_pilot_contract.py`

**Interfaces:**
- Consumes: the root-only seed descriptor, current release tag/images/evidence, candidate twelve-character SHA images, and Task 1 transaction gate.
- Produces: candidate-bound evidence atomically promoted with candidate images and a fail-closed restoration of actual prior tag/images/evidence.

- [ ] **Step 1: Write full/app release RED contracts**

Require `Deploy-Pilot.ps1` to use directory mode `0755` and `--gate-mode transaction`, not its inline `status != fail` parser. Require app release ordering:

```python
def test_app_release_verifies_descriptor_and_switches_candidate_evidence_atomically():
    release = _read_deploy("Release-PilotApp-FromPipeline.sh")
    descriptor = release.index("legal-operational-evidence-source.env")
    manifest = release.index("sha256sum -c -", descriptor)
    bundle = release.index("verify_production_rag_seed_manifest", manifest)
    build = release.index("build_legal_operational_evidence", bundle)
    validate = release.index("etl.legal.validate_run_summary", build)
    stop = release.index('"${compose[@]}" rm -sf', validate)
    promote = release.index("mv -f \"$candidate_evidence_tmp\" \"$shared_evidence_file\"", stop)
    gate = release.index("observe_operational_health --once --gate-mode transaction", promote)
    assert descriptor < manifest < bundle < build < validate < stop < promote < gate
```

Also require prior shared/release-local evidence state snapshots, actual `previous_tag` restoration, monitor stop during switch, cleanup traps, no database/seed load commands, and no provider flags.

- [ ] **Step 2: Run release contract tests and verify RED**

Run: `python -m pytest -q test/test_aws_pilot_infrastructure.py -k "operational_evidence or app_release"`

Expected: failures for `0755`, shared gate usage, descriptor validation, candidate evidence, and evidence rollback.

- [ ] **Step 3: Update full deploy to the shared transaction gate**

Change only the evidence directory mode and preflight boundary:

```powershell
"install -d -m 0755 /opt/skn27-pilot/operational-evidence"
"$productionComposeCommand run --rm --no-deps ops-monitor python backend/manage.py observe_operational_health --once --gate-mode transaction"
```

Keep HTTPS live/ready, legal validation, monitor ordering, and automatic rollback intact.

- [ ] **Step 4: Implement app-release descriptor and candidate evidence flow**

Before pulling or mutating images, load the descriptor without shell evaluation, validate exact key set/URI/path/SHA, snapshot actual current images under `previous_tag`, and snapshot shared plus release-local evidence including absent states. Build and validate candidate evidence with the candidate backend image before stopping services. Promote only after live/ready succeed, start workers/monitor, run transaction gate, then disarm the trap.

On failure, restore `.compose.env` to `previous_tag`, restore both evidence locations atomically or to their absent state, recreate all app services from the snapshotted image IDs, and preserve the original nonzero status.

```bash
seed_source_file='/opt/skn27-pilot/state/legal-operational-evidence-source.env'
declare -A seed_source=()
while IFS='=' read -r key value; do
  case "$key" in
    RAG_SEED_S3_URI|RAG_SEED_MANIFEST_RELATIVE_PATH|RAG_SEED_MANIFEST_SHA256) seed_source["$key"]="$value" ;;
    *) echo 'Seed source descriptor contains an unsupported key.' >&2; exit 78 ;;
  esac
done < "$seed_source_file"
[[ "${seed_source[RAG_SEED_MANIFEST_SHA256]:-}" =~ ^[0-9a-f]{64}$ ]]

backup_evidence() {
  shared_evidence_existed=0
  if [[ -f "$shared_evidence_file" ]]; then
    install -m 0444 "$shared_evidence_file" "$shared_evidence_backup"
    shared_evidence_existed=1
  fi
}

promote_candidate_evidence() {
  install -m 0444 "$candidate_evidence_file" "$candidate_evidence_tmp"
  mv -f "$candidate_evidence_tmp" "$shared_evidence_file"
}

restore_previous_evidence() {
  if (( shared_evidence_existed )); then
    install -m 0444 "$shared_evidence_backup" "$candidate_evidence_tmp"
    mv -f "$candidate_evidence_tmp" "$shared_evidence_file"
  else
    rm -f "$shared_evidence_file" "$candidate_evidence_tmp"
  fi
}
```

- [ ] **Step 5: Run release tests and verify GREEN**

Run: `python -m pytest -q test/test_aws_pilot_infrastructure.py -k "normal_promotion_validates_promotes_and_preflights_operational_evidence or app_release or operational_evidence"`

Expected: all selected contracts pass and forbidden loader/provider strings remain absent from app release.

- [ ] **Step 6: Prepare the Task 3 commit handoff**

```powershell
git add deploy/aws-pilot/Deploy-Pilot.ps1 deploy/aws-pilot/Release-PilotApp-FromPipeline.sh test/test_aws_pilot_infrastructure.py test/test_codebuild_pilot_contract.py
git diff --cached --check
git commit -m "fix: bind app releases to atomic evidence"
```

---

### Task 4: Manual rollback evidence transaction and ten-minute acceptance watcher

**Files:**
- Create: `deploy/aws-pilot/Confirm-PilotOperationalAcceptance.ps1`
- Modify: `deploy/aws-pilot/Rollback-Pilot.ps1`
- Modify: `test/test_aws_pilot_infrastructure.py`

**Interfaces:**
- Consumes: a requested target release, its local evidence, the pre-command current release/evidence, and Task 1 gate modes.
- Produces: rollback with target-bound evidence and pre-command restoration on rollback failure.
- Produces: an SSM-backed acceptance watcher requiring 600 elapsed consecutive pass seconds with a bounded 1,200-second maximum wait.

- [ ] **Step 1: Write rollback and acceptance RED contracts**

Add tests requiring target evidence validation before any compose mutation, current evidence backup before switch, atomic target evidence promotion, transaction preflight before symlink update, and restoration on error:

```python
def test_manual_rollback_validates_and_restores_release_bound_evidence():
    rollback = _read_deploy("Rollback-Pilot.ps1")
    validate = rollback.index("etl.legal.validate_run_summary")
    mutate = rollback.index("$composeCommand up -d", validate)
    promote = rollback.index("mv -f `$TARGET_EVIDENCE_TMP `$SHARED_EVIDENCE_FILE", mutate)
    gate = rollback.index("observe_operational_health --once --gate-mode transaction", promote)
    symlink = rollback.index("ln -sfn '$releaseDirectory' /opt/skn27-pilot/current", gate)
    assert validate < mutate < promote < gate < symlink
    assert "restore_precommand_evidence" in rollback
```

For the watcher require `ValidateRange(600, 3600)`, default 600 seconds, maximum wait 1200 seconds, 60-second sampling, acceptance-mode gate calls, timer reset on `decision=reset`, immediate exit on `decision=fail`, and no provider/load commands.

- [ ] **Step 2: Run rollback/acceptance tests and verify RED**

Run: `python -m pytest -q test/test_aws_pilot_infrastructure.py -k "manual_rollback or operational_acceptance"`

Expected: failures because rollback does not manage evidence and the watcher does not exist.

- [ ] **Step 3: Implement manual rollback evidence transaction**

Validate the target summary using the target release compose/backend image before service mutation. Back up the current shared evidence and symlink target. Install target evidence to a same-directory temporary file with `0444`, atomically rename, start services, call transaction gate, then update the current symlink. The trap restores the prior release, evidence or absent state, and symlink.

```bash
TARGET_EVIDENCE_FILE="$releaseDirectory/operational-evidence/run_summary.json"
SHARED_EVIDENCE_DIR='/opt/skn27-pilot/operational-evidence'
SHARED_EVIDENCE_FILE="$SHARED_EVIDENCE_DIR/run_summary.json"
TARGET_EVIDENCE_TMP="$SHARED_EVIDENCE_DIR/.run_summary.json.rollback.tmp"
test -f "$TARGET_EVIDENCE_FILE"
"${compose[@]}" run --rm --no-deps -v "$releaseDirectory/operational-evidence:/run/target-evidence:ro" backend \
  python -m etl.legal.validate_run_summary --summary /run/target-evidence/run_summary.json \
  --max-age-hours "$LEGAL_MAX_AGE_HOURS" --expected-dataset-version "$LEGAL_DATASET_VERSION" \
  --expected-release-version "$ReleaseTag"
install -m 0444 "$TARGET_EVIDENCE_FILE" "$TARGET_EVIDENCE_TMP"
mv -f "$TARGET_EVIDENCE_TMP" "$SHARED_EVIDENCE_FILE"
"${compose[@]}" run --rm --no-deps ops-monitor python backend/manage.py observe_operational_health --once --gate-mode transaction
ln -sfn "$releaseDirectory" /opt/skn27-pilot/current
```

- [ ] **Step 4: Implement the acceptance watcher**

Use existing Terraform/SSM discovery and maintenance lock. The remote loop calls:

```bash
docker compose --project-name skn27-pilot --env-file .compose.env --env-file .production-compose.env -f docker-compose.pilot.yml run --rm --no-deps ops-monitor python backend/manage.py observe_operational_health --once --gate-mode acceptance
```

Parse only `gate.decision`. Accumulate elapsed time only across consecutive `pass`; set it to zero on `reset`; exit immediately on `fail`; fail safely when maximum wait is reached. Record only release tag, timestamps, decision, and elapsed seconds.

```bash
consecutive_seconds=0
waited_seconds=0
while (( consecutive_seconds < acceptance_seconds && waited_seconds < max_wait_seconds )); do
  snapshot="$(${compose[@]} run --rm --no-deps ops-monitor python backend/manage.py observe_operational_health --once --gate-mode acceptance)" || exit 1
  decision="$(printf '%s\n' "$snapshot" | python3 -c 'import json,sys; print((json.load(sys.stdin).get("gate") or {}).get("decision", "fail"))')"
  case "$decision" in
    pass) consecutive_seconds=$((consecutive_seconds + interval_seconds)) ;;
    reset) consecutive_seconds=0 ;;
    *) exit 1 ;;
  esac
  waited_seconds=$((waited_seconds + interval_seconds))
  (( consecutive_seconds >= acceptance_seconds )) || sleep "$interval_seconds"
done
(( consecutive_seconds >= acceptance_seconds ))
```

- [ ] **Step 5: Run rollback/acceptance tests and verify GREEN**

Run: `python -m pytest -q test/test_aws_pilot_infrastructure.py -k "manual_rollback or operational_acceptance or rollback_refreshes"`

Expected: all selected tests pass.

- [ ] **Step 6: Prepare the Task 4 commit handoff**

```powershell
git add deploy/aws-pilot/Confirm-PilotOperationalAcceptance.ps1 deploy/aws-pilot/Rollback-Pilot.ps1 test/test_aws_pilot_infrastructure.py
git diff --cached --check
git commit -m "fix: restore evidence during pilot rollback"
```

---

### Task 5: Runbooks, master checklist, and complete regression evidence

**Files:**
- Modify: `deploy/aws-pilot/README.ko.md`
- Modify: `docs/ops/operational-observability-runbook.md`
- Modify: `docs/tech-validation-reports/2026-07-31-pilot-hotfix-master-checklist.md`
- Modify: `test/test_deployment_readiness_artifacts.py`
- Modify: `test/test_aws_pilot_infrastructure.py`

**Interfaces:**
- Consumes: operator commands and gate semantics from Tasks 1-4.
- Produces: exact bootstrap order, no-cost boundary, rollback procedure, and G8/13-E2E hold point.

- [ ] **Step 1: Write documentation RED contracts**

Require all exact operator artifacts and ordering:

```python
def test_operational_runbook_documents_bootstrap_and_two_gate_acceptance():
    runbook = read_text(ROOT / "docs" / "ops" / "operational-observability-runbook.md")
    for token in (
        "818199aee975",
        "Recover-PilotOperationalEvidence.ps1",
        "Confirm-PilotOperationalAcceptance.ps1",
        "queue_backlog",
        "600초",
        "Rollback-Pilot.ps1",
        "13개 E2E",
    ):
        assert token in runbook
    assert runbook.index("Recover-PilotOperationalEvidence.ps1") < runbook.index("app-release pipeline")
```

The checklist must leave production recovery, pipeline approval, ten-minute candidate acceptance, G8, and thirteen E2E unchecked until actually run.

- [ ] **Step 2: Run documentation tests and verify RED**

Run: `python -m pytest -q test/test_deployment_readiness_artifacts.py test/test_aws_pilot_infrastructure.py -k "runbook or checklist or bootstrap"`

Expected: missing new command and ordering assertions fail.

- [ ] **Step 3: Update runbooks and checklist**

Document the exact no-cost sequence:

1. Merge implementation.
2. Run recovery against `818199aee975` with approved URI/path/SHA.
3. Run transaction preflight.
4. Run 600-second acceptance watcher.
5. Approve app pipeline.
6. Run candidate transaction gate and candidate 600-second acceptance.
7. Only then start G8 and thirteen E2E scenarios.

State that recovery/acceptance have no provider consent switch and that a failed immutable-seed verification stops for explicit paid-loader approval.

- [ ] **Step 4: Run focused operational regression**

Run: `python -m pytest -q test/test_operational_health_gate.py test/test_aws_pilot_infrastructure.py test/test_deployment_readiness_artifacts.py test/test_legal_operational_evidence.py`

Run: `python backend/manage.py test chatbot.test_operational_observability -v 1`

Expected: all focused tests pass.

- [ ] **Step 5: Run syntax and formatting verification**

PowerShell parser check:

```powershell
$parseErrors = @()
Get-ChildItem deploy/aws-pilot -Filter '*.ps1' | ForEach-Object {
  [void][System.Management.Automation.Language.Parser]::ParseFile($_.FullName, [ref]$null, [ref]$parseErrors)
}
if ($parseErrors.Count -ne 0) { $parseErrors | Format-List; exit 1 }
```

Bash syntax: `bash -n deploy/aws-pilot/Release-PilotApp-FromPipeline.sh`

Terraform: `terraform -chdir=infra/terraform-pilot fmt -check -recursive`

Terraform: `terraform -chdir=infra/terraform-pilot validate`

Expected: no parse, format, or validation error. If Terraform providers are unavailable locally, record the exact validation blocker without changing configuration.

- [ ] **Step 6: Run complete project regression**

Run: `python -m pytest -q`

Run in `app/web`: `node --test *.test.js`

Run in `app/web`: `npm run build`

Expected: Python and all 66 frontend Node tests pass and Vite production build succeeds.

- [ ] **Step 7: Perform final diff/security review**

Run:

```powershell
git diff --check
git status --short
$forbiddenMatches = rg -n "AllowPaidReviewCaseEmbedding|allow-paid-provider-call|load_review_case_pgvector_seed|load_production_rag_seed|load_legal_graph_seed" deploy/aws-pilot/Recover-PilotOperationalEvidence.ps1 deploy/aws-pilot/Release-PilotApp-FromPipeline.sh deploy/aws-pilot/Confirm-PilotOperationalAcceptance.ps1
if ($LASTEXITCODE -eq 0) { $forbiddenMatches; throw 'Forbidden paid/load token found.' }
if ($LASTEXITCODE -gt 1) { throw "ripgrep failed with exit code $LASTEXITCODE." }
```

Treat ripgrep exit code `1` as the expected zero-match result; exit code `0` is a security-test failure and any code above `1` is a command error. Expected: clean diff checks and zero forbidden paid/load tokens in all evidence-only/app-release/acceptance scripts.

- [ ] **Step 8: Prepare the Task 5 commit handoff**

```powershell
git add deploy/aws-pilot/README.ko.md docs/ops/operational-observability-runbook.md docs/tech-validation-reports/2026-07-31-pilot-hotfix-master-checklist.md test/test_deployment_readiness_artifacts.py test/test_aws_pilot_infrastructure.py
git diff --cached --check
git commit -m "docs: define pilot evidence release acceptance"
```

## Production hold point

Local implementation completion does not authorize AWS mutation. After merge, stop before `Recover-PilotOperationalEvidence.ps1` and obtain explicit operator approval for the exact production command and approved seed URI/path/SHA. Recovery itself is evidence-only and free of provider calls. Any later full seed reload or paid smoke still requires its separate explicit consent switch.
