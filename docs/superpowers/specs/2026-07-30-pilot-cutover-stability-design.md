# Pilot Cutover Stability Design

## Goal

Promote a staged Pilot release without starting the RAG loader in the public Compose project, without treating Redis append-only recovery as an immediate failure, and without racing the Caddy host-network cutover.

## Observed failure modes

1. `rag-loader` is defined as an ordinary Compose service. A normal `up` starts it, and it may consume the first unassigned bridge address. Legacy releases reserve that address for Caddy during rollback.
2. Redis can need more than the initial health-check window while append-only data is recovered. The normal promotion currently treats that transient state as a hard failure and invokes rollback.
3. The release transition calls Compose teardown and then starts host-network Caddy immediately. Docker port publishing from the previous release can take a short time to disappear.

## Decision

Use a minimal Compose and deployment-script hardening change.

- Assign `rag-loader` to a `seed` Compose profile. Normal `up` and rollback flows will exclude it. `Load-Rag-Seed-Pilot.ps1` will explicitly enable the `seed` profile for every `rag-loader` run.
- Make normal production startup and rollback startup use the explicit operational-service list (`caddy`, edge proxy, application services, Redis, ClamAV, and Neo4j), never a bare `up` that can start an unlisted helper from an older release.
- Give Redis a 60-second health-check `start_period`. The existing 10-second interval and five retries remain, so the release can wait up to 110 seconds before treating Redis as unhealthy.
- After production Compose teardown, wait until TCP ports 80 and 443 have no listener before the new Compose project starts. The wait is bounded and fails before any new Caddy container is created.

## Non-goals

- Do not change RAG seed data, Neo4j content, API business behavior, or frontend assets.
- Do not change the approved Caddy host-network model or public security-group policy.
- Do not delete the current release or its persistent data as part of a failed promotion.

## Rollback and safety

The normal rollback remains the release script's responsibility. Its explicit operational-service list also protects rollback to a legacy Compose release that does not yet declare the `seed` profile. The port-release wait runs only after the prior production project has been stopped.

## Acceptance criteria

1. Compose contract tests prove `rag-loader` has only the `seed` profile and Redis has a 60-second `start_period`.
2. Seed loader script contract tests prove each `rag-loader` command enables the `seed` profile.
3. Deployment script contract tests prove it waits for ports 80 and 443 to be released after production teardown and before production startup.
4. The Pilot infrastructure test suite passes.
