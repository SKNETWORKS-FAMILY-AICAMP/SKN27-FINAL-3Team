# Pilot Caddy host-network deployment design

## Goal

Make the Pilot release-update path work when Docker cannot publish host ports
80 and 443 for the Compose Caddy service, while preserving the existing
staging, RAG verification, promotion, rollback, and TLS-volume workflow.

## Decision

Run the Compose-managed `caddy` service with `network_mode: host` instead of
Docker port publishing. Caddy remains a first-class Compose service, so the
existing deployment script can continue to require `caddy` during promotion.

The service will not join the `pilot` network. It reaches HAProxy through a
single explicit `/etc/hosts` mapping from `edge-rate-limit` to
`${PILOT_EDGE_RATE_LIMIT_IP}`. Caddy runs as dedicated UID/GID `10001`, keeps
its current read-only filesystem, least-privilege capabilities, edge
environment, Caddyfile mount, and TLS/log volumes. A one-shot Compose service
owns those writable volumes for that UID before Caddy starts.

The existing IMDS firewall protects bridge-network containers only. Because a
host-network process bypasses that path, the firewall also rejects metadata
traffic from UID `10001` in the host `OUTPUT` chain. The deploy script installs
the versioned firewall script on the existing EC2 host before every release, so
this protection survives reboot as well as new Terraform instances.

## Required changes

1. In `docker-compose.pilot.yml`, replace Caddy `ports` and `networks` with
   `network_mode: host` and an `extra_hosts` entry for `edge-rate-limit`.
2. Remove the obsolete Caddy static-network address from both generated Compose
   environment files in `Deploy-Pilot.ps1`; retain the rate-limit address used
   by Caddy.
3. Add the dedicated Caddy UID, volume-initialization dependency, and IMDS
   `OUTPUT`-chain reject rule.
4. Update infrastructure contract tests to require host networking, prohibit
   Caddy port publishing and pilot-network attachment, and verify the explicit
   edge-rate-limit host mapping and metadata boundary.
5. Update the deployment runbook with the cutover and rollback checks.

## Deployment and rollback

During this recovery, 80/443 stays blocked at the security group. The normal
release-update stage uses the explicit
`-AllowCaddyOfflineForHostNetworkCutover` switch because the old
published-port Caddy is intentionally down. The switch is rejected outside
release-update staging. It runs the existing RAG and readiness checks before
promotion. After local and public health checks pass, restore only the recorded
TCP 80 and 443 IPv4 ingress rules. Rollback uses the existing release rollback
path; Caddy remains Compose-managed and uses the shared TLS volumes in either
release.

## Verification

- A test must fail on the current published-port Compose configuration.
- Contract tests validate the host-network and explicit edge host mapping, the
  dedicated Caddy UID, and the IMDS host-output reject rule.
- `docker compose config` validates the rendered production configuration.
- Release-update stage, RAG readiness, backend readiness, and public health
  checks must pass before restoring public ingress.

## Non-goals

- No manual host-network Caddy container.
- No database, Neo4j, RAG source, or embedding-version change.
- No change to public DNS, TLS issuer, or the rate-limit policy.
