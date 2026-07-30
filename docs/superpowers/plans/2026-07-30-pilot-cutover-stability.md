# Pilot Cutover Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Pilot promotion and rollback exclude seed-only loaders, tolerate Redis append-only recovery, and wait for Caddy ports to release.

**Architecture:** The Compose contract marks `rag-loader` as a `seed` profile service. Both the seed script and normal deployment script use explicit commands: seed runs enable the profile; production and rollback starts use a fixed operational-service list. The deployment script waits for 80 and 443 to have no listening process before host-network Caddy starts.

**Tech Stack:** Docker Compose, PowerShell, pytest, PyYAML contract tests.

## Global Constraints

- Keep RAG/Neo4j data and backend business behavior unchanged.
- Use only the existing `test/test_aws_pilot_infrastructure.py` contract-test pattern.
- Keep runtime environment values out of source and test output.
- Promotion may not start `rag-loader`; only `Load-Rag-Seed-Pilot.ps1` may run it with the `seed` profile.

---

### Task 1: Gate `rag-loader` behind the seed profile

**Files:**
- Modify: `test/test_aws_pilot_infrastructure.py:270-288`
- Modify: `deploy/aws-pilot/docker-compose.pilot.yml:183-198`

**Interfaces:**
- Consumes: Compose `services.rag-loader` mapping parsed with `yaml.safe_load`.
- Produces: `services["rag-loader"]["profiles"] == ["seed"]`.

- [ ] **Step 1: Write the failing test**

```python
assert services["rag-loader"]["profiles"] == ["seed"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q test/test_aws_pilot_infrastructure.py -k private_legal_graph`

Expected: FAIL because `profiles` is absent from the `rag-loader` service.

- [ ] **Step 3: Write minimal implementation**

```yaml
  rag-loader:
    profiles: [seed]
```

Add the mapping directly under the service header; do not change its image, memory limit, network, or environment.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q test/test_aws_pilot_infrastructure.py -k private_legal_graph`

Expected: PASS.

### Task 2: Require the profile only for seed-loader commands

**Files:**
- Modify: `test/test_aws_pilot_infrastructure.py:372,494-500,540-559`
- Modify: `deploy/aws-pilot/Load-Rag-Seed-Pilot.ps1:104-133`

**Interfaces:**
- Consumes: `$stageComposeCommand` string.
- Produces: every `run --rm --no-deps ... rag-loader` command includes `--profile seed` before `run`.

- [ ] **Step 1: Write the failing test**

```python
assert "$stageComposeCommand --profile seed run --rm --no-deps rag-loader" in loader
```

Add equivalent assertions for manifest verification and all seed load/smoke command variants.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q test/test_aws_pilot_infrastructure.py -k rag_loader`

Expected: FAIL because the loader commands currently omit `--profile seed`.

- [ ] **Step 3: Write minimal implementation**

Replace each loader command prefix with:

```powershell
$stageComposeCommand --profile seed run --rm --no-deps rag-loader
```

Preserve every existing command argument, bind mount, ordering, and paid-provider guard.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q test/test_aws_pilot_infrastructure.py -k rag_loader`

Expected: PASS.

### Task 3: Stabilize Redis health and operational startup

**Files:**
- Modify: `test/test_aws_pilot_infrastructure.py:341 and release-update deployment assertions`
- Modify: `deploy/aws-pilot/docker-compose.pilot.yml:261-279`
- Modify: `deploy/aws-pilot/Deploy-Pilot.ps1:555-706`

**Interfaces:**
- Consumes: production Compose command and service names.
- Produces: Redis uses `start_period: 60s`; normal startup and rollback start only the operational-service list; a bounded port-release check appears after previous-release teardown and before new startup.

- [ ] **Step 1: Write the failing tests**

```python
assert services["redis"]["healthcheck"]["start_period"] == "60s"
assert "OPERATIONAL_SERVICES='caddy edge-rate-limit frontend backend agent-worker file-scan-worker ops-monitor redis clamav law-neo4j'" in deploy
assert "$productionComposeCommand up -d --wait --wait-timeout 600 --remove-orphans `$OPERATIONAL_SERVICES" in deploy
assert "for attempt in `$(seq 1 30); do ! ss -ltnp | grep -E '(:80|:443)'" in deploy
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q test/test_aws_pilot_infrastructure.py -k 'redis or release_update'`

Expected: FAIL because Redis has no start period and the deployment script has no operational-service or port-release contract.

- [ ] **Step 3: Write minimal implementation**

Add the following Redis health field without changing interval, timeout, or retries:

```yaml
start_period: 60s
```

Add this remote-script variable before the promotion/rollback commands:

```sh
OPERATIONAL_SERVICES='caddy edge-rate-limit frontend backend agent-worker file-scan-worker ops-monitor redis clamav law-neo4j'
```

Use it in both production startup and `rollback_previous_release` startup. Immediately after previous production teardown, add a loop that succeeds only when `ss -ltnp` reports neither port 80 nor 443 and exits 78 after 30 attempts with a clear error.

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `python -m pytest -q test/test_aws_pilot_infrastructure.py -k 'redis or release_update'`

Expected: PASS.

### Task 4: Verify the complete infrastructure contract

**Files:**
- Verify: `test/test_aws_pilot_infrastructure.py`

- [ ] **Step 1: Run the complete infrastructure suite**

Run: `python -m pytest -q test/test_aws_pilot_infrastructure.py`

Expected: all tests pass.

- [ ] **Step 2: Inspect the diff for scope**

Run: `git diff --check; git diff -- deploy/aws-pilot/docker-compose.pilot.yml deploy/aws-pilot/Load-Rag-Seed-Pilot.ps1 deploy/aws-pilot/Deploy-Pilot.ps1 test/test_aws_pilot_infrastructure.py`

Expected: only profile gating, Redis health timing, explicit operation service selection, port-release waiting, and associated contract tests are present.
