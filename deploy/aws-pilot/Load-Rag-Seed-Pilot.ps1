#requires -Version 7.2
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RagSeedS3Uri,

    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[a-z0-9][a-z0-9-]{0,31}$")]
    [string]$ReleaseTag,

    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[A-Za-z0-9._-]+\.json$")]
    [string]$RagSeedManifestRelativePath,

    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$RagSeedManifestSha256,

    [string]$TerraformDirectory = (Join-Path $PSScriptRoot "..\..\infra\terraform-pilot"),
    [ValidateRange(600, 7200)]
    [int]$SsmTimeoutSeconds = 1800,
    [switch]$AllowPaidReviewCaseEmbedding
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $AllowPaidReviewCaseEmbedding) {
    throw "RAG seed maintenance requires explicit -AllowPaidReviewCaseEmbedding consent."
}

function Assert-LastExitCode([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step failed with exit code $LASTEXITCODE." }
}

function Get-SsmCommandResult(
    [string]$Region,
    [string]$CommandId,
    [string]$InstanceId,
    [int]$TimeoutSeconds
) {
    $terminalStatuses = @("Success", "Cancelled", "TimedOut", "Failed")
    # Cancelling is non-terminal and must continue polling before cleanup.
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        $json = & aws ssm get-command-invocation --region $Region --command-id $CommandId --instance-id $InstanceId --output json --no-cli-pager 2>$null
        if ($LASTEXITCODE -eq 0) {
            $result = $json | ConvertFrom-Json
            if ($result.Status -in $terminalStatuses) { return $result }
        }
        Start-Sleep -Seconds 10
    }

    & aws ssm cancel-command --region $Region --command-id $CommandId --no-cli-pager | Out-Null
    for ($attempt = 1; $attempt -le 12; $attempt++) {
        $json = & aws ssm get-command-invocation --region $Region --command-id $CommandId --instance-id $InstanceId --output json --no-cli-pager 2>$null
        if ($LASTEXITCODE -eq 0) {
            $result = $json | ConvertFrom-Json
            if ($result.Status -in $terminalStatuses) { return $result }
        }
        Start-Sleep -Seconds 5
    }
    throw "RAG seed SSM command cancellation did not reach a terminal status."
}

$terraformPath = (Resolve-Path -LiteralPath $TerraformDirectory).Path
Push-Location $terraformPath
try {
    $outputs = (& terraform output -json) | ConvertFrom-Json
    Assert-LastExitCode "terraform output"
}
finally {
    Pop-Location
}

$region = [string]$outputs.aws_region.value
$instanceId = [string]$outputs.instance_id.value
$cleanBucket = [string]$outputs.clean_bucket_name.value
$expectedPrefix = "s3://$cleanBucket/_rag-seed/"
if (-not $RagSeedS3Uri.StartsWith($expectedPrefix, [StringComparison]::Ordinal) -or -not $RagSeedS3Uri.EndsWith("/")) {
    throw "RagSeedS3Uri must be a versioned prefix under $expectedPrefix and end with '/'."
}
if ($RagSeedS3Uri -match "(^|/)\.\.(/|$)") { throw "RAG seed URI cannot contain parent traversal." }
foreach ($descriptorValue in @($RagSeedS3Uri, $RagSeedManifestRelativePath, $RagSeedManifestSha256)) {
    if ($descriptorValue -match "[`r`n=]") {
        throw "RAG seed descriptor values cannot contain control characters or '='."
    }
}

$stageProjectName = "skn27-stage-$ReleaseTag"
$stageComposeCommand = "docker compose --project-name '$stageProjectName' --env-file .compose.env --env-file .stage-compose.env -f docker-compose.pilot.yml"
$runnerCommands = @(
    "set -euo pipefail",
    "exec 9>/var/lock/skn27-pilot-maintenance.lock",
    "flock -w 60 9",
    "test ! -e '/opt/skn27-pilot/maintenance/database-maintenance.active' || { echo 'Database maintenance marker is active.' >&2; exit 75; }",
    "TARGET_RELEASE='/opt/skn27-pilot/releases/$ReleaseTag'",
    "test -d `$TARGET_RELEASE && test ! -L `$TARGET_RELEASE",
    "test -f `$TARGET_RELEASE/.stage-project-name",
    "test `"`$(cat `$TARGET_RELEASE/.stage-project-name)`" = '$stageProjectName'",
    "test -f `$TARGET_RELEASE/.stage-compose.env",
    "CURRENT_RELEASE=`$(readlink -f /opt/skn27-pilot/current 2>/dev/null || true)",
    "IS_UPDATE_STAGE=0",
    "if [ -f `$TARGET_RELEASE/.initial-rag-bootstrap.staged ]; then test -z `"`$CURRENT_RELEASE`" && test ! -L /opt/skn27-pilot/current && test `"`$(cat `$TARGET_RELEASE/.initial-rag-bootstrap.staged)`" = '$ReleaseTag $RagSeedManifestSha256 $stageProjectName'; elif [ -f `$TARGET_RELEASE/.release-update.staged ]; then IS_UPDATE_STAGE=1; test -n `"`$CURRENT_RELEASE`" && test -d `"`$CURRENT_RELEASE`"; test `"`$CURRENT_RELEASE`" != `"`$TARGET_RELEASE`"; test `"`$(cat `$TARGET_RELEASE/.release-update.staged)`" = `"`$(printf '%s %s %s %s' '$ReleaseTag' '$RagSeedManifestSha256' '$stageProjectName' `"`$CURRENT_RELEASE`")`"; else echo 'Exact initial or update stage marker is missing.' >&2; exit 78; fi",
    "CURRENT_CONTAINER_IDS=''; if [ `$IS_UPDATE_STAGE -eq 1 ]; then CURRENT_CONTAINER_IDS=`$(docker ps --filter label=com.docker.compose.project=skn27-pilot --format '{{.ID}}' | sort); test -n `"`$CURRENT_CONTAINER_IDS`"; fi",
    "cd `$TARGET_RELEASE",
    "RUNNING_STAGE_SERVICES=`$($stageComposeCommand ps --services --filter status=running)",
    "for required_service in redis law-neo4j; do printf '%s\n' `"`$RUNNING_STAGE_SERVICES`" | grep -qx `"`$required_service`"; done",
    "$stageComposeCommand --profile seed run --rm --no-deps rag-loader python backend/manage.py help verify_production_rag_seed_manifest >/dev/null",
    "$stageComposeCommand --profile seed run --rm --no-deps rag-loader python backend/manage.py help load_review_case_pgvector_seed >/dev/null",
    "$stageComposeCommand --profile seed run --rm --no-deps rag-loader python backend/manage.py help load_production_rag_seed >/dev/null",
    "$stageComposeCommand --profile seed run --rm --no-deps rag-loader python backend/manage.py help load_legal_graph_seed >/dev/null",
    "$stageComposeCommand --profile seed run --rm --no-deps rag-loader python backend/manage.py help build_legal_operational_evidence >/dev/null",
    "RELEASE_STATE_FILE=`$TARGET_RELEASE/.production-rag-seed.complete",
    "test ! -e `$RELEASE_STATE_FILE",
    "EVIDENCE_DIR=`$TARGET_RELEASE/operational-evidence",
    "EVIDENCE_FILE=`$EVIDENCE_DIR/run_summary.json",
    "EVIDENCE_TMP=`$EVIDENCE_DIR/.run_summary.json.tmp",
    "SEED_SOURCE_DIR='/opt/skn27-pilot/state'",
    "SEED_SOURCE_FILE=`$SEED_SOURCE_DIR/legal-operational-evidence-source.env",
    "SEED_SOURCE_TMP=`$SEED_SOURCE_DIR/.legal-operational-evidence-source.env.tmp",
    "test ! -e `$EVIDENCE_FILE && test ! -e `$EVIDENCE_TMP",
    "load_failed() { status=`$?; trap - ERR EXIT; cleanup_rag_seed 2>/dev/null || true; cd `$TARGET_RELEASE 2>/dev/null || true; $stageComposeCommand down --remove-orphans >/dev/null 2>&1 || true; docker volume rm '${stageProjectName}_redis_data' '${stageProjectName}_clamav_data' '${stageProjectName}_law_neo4j_data' '${stageProjectName}_law_neo4j_logs' >/dev/null 2>&1 || true; rm -rf -- `$TARGET_RELEASE; exit `$status; }",
    "trap load_failed ERR",
    "RAG_DIR='/opt/skn27-pilot/rag-seed/$RagSeedManifestSha256'",
    "cleanup_rag_seed() { rm -rf -- `$RAG_DIR; }",
    "trap cleanup_rag_seed EXIT",
    "install -d -m 0700 `$RAG_DIR",
    "aws s3 cp '$RagSeedS3Uri' `$RAG_DIR/ --region '$region' --recursive --only-show-errors",
    "test -f `$RAG_DIR/$RagSeedManifestRelativePath",
    "printf '%s  %s\n' '$RagSeedManifestSha256' `$RAG_DIR/$RagSeedManifestRelativePath | sha256sum -c -",
    "find `$RAG_DIR -type d -exec chmod 0555 {} +",
    "find `$RAG_DIR -type f -exec chmod 0444 {} +",
    "$stageComposeCommand --profile seed run --rm --no-deps -v `$RAG_DIR:/run/production-rag-seed:ro rag-loader python backend/manage.py verify_production_rag_seed_manifest --manifest /run/production-rag-seed/$RagSeedManifestRelativePath --format json",
    "$stageComposeCommand --profile seed run --rm --no-deps rag-loader python -c `"from pathlib import Path; production=Path('backend/chatbot/management/commands/load_production_rag_seed.py').read_text(); legal=Path('backend/chatbot/management/commands/load_legal_rag_pgvector.py').read_text(); assert 'load_and_validate_rag_seed_manifest' in production; assert 'load_legal_rag_pgvector' in production; assert 'transaction.atomic' in legal`"",
    "$stageComposeCommand --profile seed run --rm --no-deps -v `$RAG_DIR:/run/production-rag-seed:ro rag-loader python backend/manage.py load_review_case_pgvector_seed --manifest /run/production-rag-seed/$RagSeedManifestRelativePath --replace --allow-paid-provider-call --format json",
    "$stageComposeCommand --profile seed run --rm --no-deps -v `$RAG_DIR:/run/production-rag-seed:ro rag-loader python backend/manage.py load_production_rag_seed --manifest /run/production-rag-seed/$RagSeedManifestRelativePath --replace-legal --skip-legal-schema --format json",
    "test `"`$(sed -n 's/^LEGAL_RAG_SEED_MANIFEST_SHA256=//p' .runtime.env)`" = '$RagSeedManifestSha256'",
    "LEGAL_DATASET_VERSION=`$(sed -n 's/^LEGAL_DATASET_VERSION=//p' .runtime.env); test -n `"`$LEGAL_DATASET_VERSION`"",
    "LEGAL_DATASET_VERIFIED_AT=`$(sed -n 's/^LEGAL_DATASET_VERIFIED_AT=//p' .runtime.env); test -n `"`$LEGAL_DATASET_VERIFIED_AT`"",
    "LEGAL_MAX_AGE_HOURS=`$(sed -n 's/^OPERATIONAL_LEGAL_MAX_AGE_HOURS=//p' .runtime.env); test -n `"`$LEGAL_MAX_AGE_HOURS`"",
    "$stageComposeCommand --profile seed run --rm --no-deps -v `$RAG_DIR:/run/production-rag-seed:ro rag-loader python backend/manage.py load_legal_graph_seed --manifest /run/production-rag-seed/$RagSeedManifestRelativePath --dataset-version `"`$LEGAL_DATASET_VERSION`" --replace --format json",
    "$stageComposeCommand --profile seed run --rm --no-deps rag-loader python backend/manage.py verify_legal_graph_readiness --format json",
    "$stageComposeCommand --profile seed run --rm --no-deps rag-loader python backend/manage.py smoke_law_ground_search --require-results --format json",
    "$stageComposeCommand --profile seed run --rm --no-deps rag-loader python backend/manage.py verify_pgvector_rag_readiness --format json",
    "$stageComposeCommand --profile seed run --rm --no-deps rag-loader python backend/manage.py smoke_text_ml_case_search --require-pgvector --require-results --format json",
    "install -d -m 0755 `$EVIDENCE_DIR",
    "$stageComposeCommand --profile seed run --rm --no-deps -v `$RAG_DIR:/run/production-rag-seed:ro rag-loader python backend/manage.py build_legal_operational_evidence --manifest /run/production-rag-seed/$RagSeedManifestRelativePath --dataset-version `"`$LEGAL_DATASET_VERSION`" --release-version '$ReleaseTag' --verified-at `"`$LEGAL_DATASET_VERIFIED_AT`" > `$EVIDENCE_TMP",
    "$stageComposeCommand --profile seed run --rm --no-deps -v `$EVIDENCE_DIR:/run/operational-evidence:ro rag-loader python -m etl.legal.validate_run_summary --summary /run/operational-evidence/.run_summary.json.tmp --max-age-hours `"`$LEGAL_MAX_AGE_HOURS`" --expected-dataset-version `"`$LEGAL_DATASET_VERSION`" --expected-release-version '$ReleaseTag'",
    "chmod 0444 `$EVIDENCE_TMP",
    "mv -f `$EVIDENCE_TMP `$EVIDENCE_FILE",
    "if [ `$IS_UPDATE_STAGE -eq 1 ]; then test `"`$CURRENT_CONTAINER_IDS`" = `"`$(docker ps --filter label=com.docker.compose.project=skn27-pilot --format '{{.ID}}' | sort)`"; fi",
    "printf '%s\n' '$RagSeedManifestSha256' > `$RELEASE_STATE_FILE.tmp",
    "chmod 0444 `$RELEASE_STATE_FILE.tmp && mv -f `$RELEASE_STATE_FILE.tmp `$RELEASE_STATE_FILE",
    "cleanup_rag_seed",
    "trap - EXIT",
    "install -d -m 0700 `$SEED_SOURCE_DIR",
    "printf '%s\n' 'RAG_SEED_S3_URI=$RagSeedS3Uri' 'RAG_SEED_MANIFEST_RELATIVE_PATH=$RagSeedManifestRelativePath' 'RAG_SEED_MANIFEST_SHA256=$RagSeedManifestSha256' > `$SEED_SOURCE_TMP",
    "chmod 0600 `$SEED_SOURCE_TMP",
    "mv -f `$SEED_SOURCE_TMP `$SEED_SOURCE_FILE",
    "trap - ERR"
)

$runnerKey = "_deploy/$ReleaseTag/rag-seed-runner.sh"
$runnerPath = Join-Path ([IO.Path]::GetTempPath()) "skn27-rag-seed-runner-$([guid]::NewGuid().ToString('N')).sh"
try {
    [IO.File]::WriteAllText($runnerPath, ($runnerCommands -join "`n") + "`n", [Text.UTF8Encoding]::new($false))
    & aws s3 cp $runnerPath "s3://$cleanBucket/$runnerKey" --region $region --only-show-errors --no-cli-pager
    Assert-LastExitCode "Upload RAG seed runner"
}
finally {
    Remove-Item -LiteralPath $runnerPath -Force -ErrorAction SilentlyContinue
}

$commands = @(
    "set -euo pipefail",
    "aws s3 cp 's3://$cleanBucket/$runnerKey' /tmp/skn27-rag-seed-runner.sh --region '$region' --only-show-errors",
    "chmod 0700 /tmp/skn27-rag-seed-runner.sh",
    "bash /tmp/skn27-rag-seed-runner.sh"
)

$request = Join-Path ([IO.Path]::GetTempPath()) "skn27-rag-seed-$([guid]::NewGuid().ToString('N')).json"
try {
    @{
        DocumentName = "AWS-RunShellScript"
        InstanceIds  = @($instanceId)
        Comment      = "Load verified SKN27 production RAG seed for $ReleaseTag"
        TimeoutSeconds = $SsmTimeoutSeconds
        Parameters   = @{
            commands         = $commands
            executionTimeout = @([string]$SsmTimeoutSeconds)
        }
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $request -Encoding utf8NoBOM

    $commandId = (& aws ssm send-command --region $region --cli-input-json "file://$request" --query "Command.CommandId" --output text --no-cli-pager).Trim()
    Assert-LastExitCode "Submit RAG seed maintenance command"
    $result = Get-SsmCommandResult -Region $region -CommandId $commandId -InstanceId $instanceId -TimeoutSeconds $SsmTimeoutSeconds
    if ($result.Status -ne "Success") {
        throw "RAG seed maintenance failed with status '$($result.Status)'. Inspect SSM output through the redacted operations workflow."
    }
}
finally {
    Remove-Item -LiteralPath $request -Force -ErrorAction SilentlyContinue
}

Write-Host "RAG seed maintenance reached a successful terminal status."
