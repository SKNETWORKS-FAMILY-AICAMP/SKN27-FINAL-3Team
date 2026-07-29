# Pilot Caddy Host-Network Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the Compose-managed Pilot Caddy service with host networking so release-update staging and promotion do not rely on Docker 80/443 port publishing.

**Architecture:** Caddy stays a `skn27-pilot` Compose service but uses `network_mode: host`. Its Caddyfile resolves HAProxy with one explicit `extra_hosts` mapping for `edge-rate-limit`; the deploy script no longer generates an unused Caddy private address. Caddy runs as UID/GID `10001`, after a least-privilege volume initializer, and the host IMDS firewall rejects metadata traffic from that UID. RAG, TLS volumes, staging, promotion, rollback, and rate limiting remain unchanged.

**Tech Stack:** Docker Compose, Caddy 2, HAProxy, PowerShell, pytest, PyYAML.

## Global Constraints

- Preserve Caddy TLS/config/log volumes, read-only filesystem, `no-new-privileges`, and `NET_BIND_SERVICE`.
- Do not modify application code, RDS, Neo4j, RAG manifests, chunks, embeddings, DNS, or rate limits.
- Caddy resolves only `edge-rate-limit:${PILOT_EDGE_RATE_LIMIT_IP:-172.31.0.3}`.
- Caddy must have neither `ports` nor a `pilot` network attachment.
- Caddy must run as UID/GID `10001`, and host-network metadata traffic from
  that UID must be rejected persistently.
- Keep public 80/443 ingress blocked until release verification succeeds.
- Permit an offline current Caddy only through an explicit release-update-only
  cutover switch, after public 80/443 ingress has been blocked.

---

### Task 1: Write and prove the failing topology and IMDS-boundary tests

**Files:**
- Modify: `test/test_aws_pilot_infrastructure.py:262-293`
- Modify: `test/test_aws_pilot_infrastructure.py:1531-1548`
- Modify: `test/test_aws_pilot_infrastructure.py:1010-1046`

**Interfaces:**
- Consumes: parsed `docker-compose.pilot.yml` via `_read_deploy`.
- Produces: Caddy host-network regression assertions.

- [ ] **Step 1: Add the failing Compose contract**

```python
caddy = services["caddy"]
assert caddy["network_mode"] == "host"
assert "ports" not in caddy
assert "networks" not in caddy
assert caddy["extra_hosts"] == [
    "edge-rate-limit:${PILOT_EDGE_RATE_LIMIT_IP:-172.31.0.3}"
]
assert caddy["user"] == "10001:10001"
```

- [ ] **Step 2: Add the failing generated-environment contract**

```python
assert "PILOT_CADDY_IP=" not in deploy
assert "PILOT_EDGE_RATE_LIMIT_IP=172.31.0.3" in deploy
```

- [ ] **Step 3: Add the failing host-network IMDS contract**

Require the one-shot Caddy volume initializer, the UID `10001` host `OUTPUT`
metadata reject rule, and deploy-time installation of the versioned firewall
script. Remove Caddy from bridge-address assertions.

- [ ] **Step 4: Verify RED**

Run `C:\tmp\skn27-pytest\Scripts\python.exe -m pytest test/test_aws_pilot_infrastructure.py -k "compose_runs_private_legal_graph or deployment_uses_static_private_service_addresses" -v`.

Expected: FAIL because Caddy currently publishes ports, joins `pilot`, and deployment emits `PILOT_CADDY_IP`.

### Task 2: Implement the minimal Compose, firewall, and deployment change

**Files:**
- Modify: `deploy/aws-pilot/docker-compose.pilot.yml:64-88`
- Modify: `deploy/aws-pilot/Deploy-Pilot.ps1:580-581`
- Modify: `infra/terraform-pilot/user_data.sh.tftpl`
- Create: `deploy/aws-pilot/configure-imds-firewall.sh`

**Interfaces:**
- Consumes: stage and production `PILOT_EDGE_RATE_LIMIT_IP` values.
- Produces: a host-network Caddy that resolves HAProxy through `/etc/hosts`.

- [ ] **Step 1: Replace only the Caddy topology blocks**

```yaml
network_mode: host
extra_hosts:
  - "edge-rate-limit:${PILOT_EDGE_RATE_LIMIT_IP:-172.31.0.3}"
```

Delete the Caddy `ports` block and `networks.pilot.ipv4_address` block. Add a
`network_mode: none` one-shot initializer that owns Caddy writable volumes for
UID/GID `10001`; Caddy depends on its successful completion. Leave every Caddy
volume, security setting, environment file, and HAProxy dependency intact.

- [ ] **Step 2: Remove only `PILOT_CADDY_IP` from generated stage and production environment lines**

Keep stage `PILOT_EDGE_RATE_LIMIT_IP=172.30.0.3`, production `PILOT_EDGE_RATE_LIMIT_IP=172.31.0.3`, all other service addresses, and all volume names unchanged.

- [ ] **Step 3: Persist the host-network IMDS deny boundary**

Install a versioned firewall script from the release to `/usr/local/sbin` before
starting Compose. It must retain the bridge allowlist/reject behavior and add
an idempotent `OUTPUT -m owner --uid-owner 10001` reject for metadata. Keep the
Terraform boot script on the same implementation.

- [ ] **Step 4: Permit the controlled offline-Caddy stage**

Add `-AllowCaddyOfflineForHostNetworkCutover`. Reject it outside
`-StageForReleaseUpdate`; when enabled, retain every current-service check
except the old published-port Caddy service. Document that public 80/443 must
already be blocked.

- [ ] **Step 5: Verify GREEN**

Run `C:\tmp\skn27-pytest\Scripts\python.exe -m pytest test/test_aws_pilot_infrastructure.py -k "compose_runs_private_legal_graph or deployment_uses_static_private_service_addresses" -v`.

Expected: PASS.

- [ ] **Step 6: Render Compose**

Run `docker compose --project-name skn27-pilot --env-file deploy/aws-pilot/runtime.env.example -f deploy/aws-pilot/docker-compose.pilot.yml config`.

Expected: Caddy contains `network_mode: host` and no `ports` section.

### Task 3: Document cutover and complete regression verification

**Files:**
- Modify: `deploy/aws-pilot/README.ko.md:19-26`
- Modify: `docs/ops/production-env.md`
- Test: `test/test_aws_pilot_infrastructure.py`
- Test: `test/test_deployment_readiness_artifacts.py`

**Interfaces:**
- Consumes: host-network Caddy topology from Task 2.
- Produces: a cutover/rollback runbook and verified deployment contract.

- [ ] **Step 1: Document exact operator sequence**

Record and block only public 80/443 security-group rules; stage and verify; promote with Compose Caddy; verify `/api/health/live/` and `/api/health/ready/`; restore recorded 80/443 rules; on failure keep ingress blocked and use the existing rollback path.

- [ ] **Step 2: Run deployment-contract tests**

Run `C:\tmp\skn27-pytest\Scripts\python.exe -m pytest test/test_aws_pilot_infrastructure.py test/test_deployment_readiness_artifacts.py -v`.

Expected: PASS.

- [ ] **Step 3: Run latest-dev release regression selection**

Run `C:\tmp\skn27-pytest\Scripts\python.exe -m pytest test/test_ui_v3_frontend_contract.py test/test_appeal_decision_frontend_contract.py test/test_law_graph_seed.py test/test_legal_graph_seed_commands.py test/test_pgvector_rag_readiness.py test/test_production_rag_seed.py test/test_review_case_embedding_retention.py test/test_review_case_seed_service.py test/test_aws_pilot_infrastructure.py test/test_deployment_readiness_artifacts.py`.

Expected: PASS with 231 or more tests and no failures.

- [ ] **Step 4: Review scope before user-owned Git publication**

Run `git diff --check` and inspect only `docker-compose.pilot.yml`, `Deploy-Pilot.ps1`, the two runbooks, and infrastructure tests.

Expected: no scope outside the approved Caddy topology, generated environment, documentation, and regression contract.
