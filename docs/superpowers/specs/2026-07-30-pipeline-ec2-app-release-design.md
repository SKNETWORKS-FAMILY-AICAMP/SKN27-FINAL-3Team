# Pilot CodePipeline EC2 app-release design

## Goal

After a `dev` commit passes the existing image build, allow an operator to
approve an application-only release to the Pilot EC2 instance. The release
must update only the backend and frontend images built for that exact commit.

## Scope and non-goals

The release path updates `backend` and `frontend` only. It keeps the existing
Compose configuration and the existing Redis, ClamAV, Neo4j, and RAG data in
place.

It does not run database migrations, RAG seed loading, graph ingestion,
Google OAuth smoke, paid provider smoke, or the Vision Worker. Any change that
needs Compose, Caddy, infrastructure, schema, or data changes remains on the
existing reviewed `Deploy-Pilot.ps1` path.

## Pipeline design

When `ci_enabled` and the new `pilot_app_release_enabled` flag are both true,
the existing pipeline has these stages:

1. `Source` retrieves the `dev` commit through the existing CodeStar
   connection.
2. `Build` runs the existing CodeBuild image build and pushes immutable
   backend, frontend, and Vision image tags.
3. `ApprovePilotAppRelease` pauses for an explicit CodePipeline manual
   approval. The existing operational SNS topic receives the approval notice.
4. `DeployPilotAppRelease` invokes a separate, non-privileged CodeBuild
   release project with the original `SourceArtifact`. It derives the same
   twelve-character commit tag from `CODEBUILD_RESOLVED_SOURCE_VERSION`.

The deploy project does not receive application secrets. Its IAM role may only
read the existing private pipeline source artifact, send and inspect SSM
commands for the configured Pilot instance, and write its own CloudWatch logs.
The instance reads its existing SecureString runtime environment itself. The
CodePipeline role receives scoped SNS publish permission only for the existing
operational-alert topic used by the manual approval notification.

## EC2 release protocol

The CodeBuild deploy command sends one locked `AWS-RunShellScript` command to
the existing Pilot instance. That command:

1. Verifies the tag is a twelve-character lowercase Git SHA and locates the
   current release directory.
2. Records the current `RELEASE_TAG` before changing it.
3. Runs `docker compose run ... migrate --check` with the candidate image.
   A pending migration stops the release before containers are changed.
4. Pulls and recreates only `backend` and `frontend` with the candidate tag.
5. Runs the existing local HTTPS live and ready endpoint checks.
6. If any operation or health check fails, restores the previous tag and
   recreates only those two containers before returning an error.

No RAG, Neo4j, Redis, Caddy, worker, volume, or database-writing operation is
part of this protocol.

## Failure behavior

The CodePipeline execution fails closed on a rejected approval, SSM timeout,
failed migration check, failed container start, or failed health check. A
failed health check attempts the app-image rollback before returning failure.
The prior release tag and command output remain available through SSM and the
dedicated deploy CodeBuild log group.

## Testing and activation

Contract tests verify that the deploy stage is optional by default, follows
the build stage, requires manual approval, and grants only scoped SSM/log
permissions. Buildspec contract tests verify the exact commit-tag derivation,
migration check, health checks, and rollback path, while rejecting paid smoke
and RAG commands.

The Terraform default leaves `pilot_app_release_enabled = false`. After the PR
is merged, a reviewed Terraform plan with the flag enabled creates the deploy
CodeBuild project and updates the existing pipeline. Existing manual
`Deploy-Pilot.ps1` releases remain available throughout.
