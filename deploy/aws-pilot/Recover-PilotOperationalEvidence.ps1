#requires -Version 7.2
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RagSeedS3Uri,

    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{12}$")]
    [string]$ReleaseTag,

    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[A-Za-z0-9._-]+\.json$")]
    [string]$RagSeedManifestRelativePath,

    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$RagSeedManifestSha256,

    [string]$TerraformDirectory = (Join-Path $PSScriptRoot "..\..\infra\terraform-pilot"),
    [ValidateRange(600, 7200)]
    [int]$SsmTimeoutSeconds = 1800
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

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
    throw "Evidence recovery SSM command cancellation did not reach a terminal status."
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
if ($RagSeedS3Uri -match "(^|/)\.\.(/|$)") {
    throw "RAG seed URI cannot contain parent traversal."
}
foreach ($descriptorValue in @($RagSeedS3Uri, $RagSeedManifestRelativePath, $RagSeedManifestSha256)) {
    if ($descriptorValue -match '[\s=''"\=]') {
        throw "RAG seed descriptor values contain an unsupported character."
    }
}

$remoteScript = @'
set -euo pipefail
exec 9>/var/lock/skn27-pilot-maintenance.lock
flock -w 60 9
test ! -e /opt/skn27-pilot/maintenance/database-maintenance.active || {
  echo 'Database maintenance marker is active.' >&2
  exit 75
}

CURRENT_RELEASE="$(readlink -f /opt/skn27-pilot/current 2>/dev/null || true)"
test -n "$CURRENT_RELEASE" && test -d "$CURRENT_RELEASE" && test ! -L "$CURRENT_RELEASE"
test -f "$CURRENT_RELEASE/.compose.env"
test -f "$CURRENT_RELEASE/.production-compose.env"
test -f "$CURRENT_RELEASE/docker-compose.pilot.yml"
CURRENT_TAG="$(sed -n 's/^RELEASE_TAG=//p' "$CURRENT_RELEASE/.compose.env")"
test "$CURRENT_TAG" = '__RELEASE_TAG__'
cd "$CURRENT_RELEASE"

compose() {
  docker compose --project-name skn27-pilot --env-file .compose.env --env-file .production-compose.env -f docker-compose.pilot.yml "$@"
}

BACKEND_CONTAINER_ID="$(compose ps -q backend)"
test -n "$BACKEND_CONTAINER_ID"
BACKEND_IMAGE_REF="$(docker inspect --format '{{.Config.Image}}' "$BACKEND_CONTAINER_ID")"
case "$BACKEND_IMAGE_REF" in
  *:__RELEASE_TAG__) ;;
  *) echo 'Running backend image does not match the requested release.' >&2; exit 78 ;;
esac

LEGAL_DATASET_VERSION="$(sed -n 's/^LEGAL_DATASET_VERSION=//p' .runtime.env)"
LEGAL_DATASET_VERIFIED_AT="$(sed -n 's/^LEGAL_DATASET_VERIFIED_AT=//p' .runtime.env)"
LEGAL_MAX_AGE_HOURS="$(sed -n 's/^OPERATIONAL_LEGAL_MAX_AGE_HOURS=//p' .runtime.env)"
test -n "$LEGAL_DATASET_VERSION"
test -n "$LEGAL_DATASET_VERIFIED_AT"
test -n "$LEGAL_MAX_AGE_HOURS"

RELEASE_EVIDENCE_DIR="$CURRENT_RELEASE/operational-evidence"
RELEASE_EVIDENCE_FILE="$RELEASE_EVIDENCE_DIR/run_summary.json"
RELEASE_EVIDENCE_TMP="$RELEASE_EVIDENCE_DIR/.run_summary.json.tmp"
RELEASE_EVIDENCE_BACKUP="$RELEASE_EVIDENCE_DIR/.run_summary.json.before-recovery.$$"
SHARED_EVIDENCE_DIR='/opt/skn27-pilot/operational-evidence'
SHARED_EVIDENCE_FILE="$SHARED_EVIDENCE_DIR/run_summary.json"
SHARED_EVIDENCE_TMP="$SHARED_EVIDENCE_DIR/.run_summary.json.tmp"
SHARED_EVIDENCE_BACKUP="$SHARED_EVIDENCE_DIR/.run_summary.json.before-recovery.$$"
SEED_SOURCE_DIR='/opt/skn27-pilot/state'
SEED_SOURCE_FILE="$SEED_SOURCE_DIR/legal-operational-evidence-source.env"
SEED_SOURCE_TMP="$SEED_SOURCE_DIR/.legal-operational-evidence-source.env.tmp"
SEED_SOURCE_BACKUP="$SEED_SOURCE_DIR/.legal-operational-evidence-source.env.before-recovery.$$"

install -d -m 0755 "$RELEASE_EVIDENCE_DIR"
install -d -m 0755 "$SHARED_EVIDENCE_DIR"
install -d -m 0700 "$SEED_SOURCE_DIR"

RELEASE_EVIDENCE_EXISTED=0
if test -f "$RELEASE_EVIDENCE_FILE"; then
  install -m 0444 "$RELEASE_EVIDENCE_FILE" "$RELEASE_EVIDENCE_BACKUP"
  RELEASE_EVIDENCE_EXISTED=1
fi
SHARED_EVIDENCE_EXISTED=0
if test -f "$SHARED_EVIDENCE_FILE"; then
  install -m 0444 "$SHARED_EVIDENCE_FILE" "$SHARED_EVIDENCE_BACKUP"
  SHARED_EVIDENCE_EXISTED=1
fi
SEED_SOURCE_EXISTED=0
if test -f "$SEED_SOURCE_FILE"; then
  install -m 0600 "$SEED_SOURCE_FILE" "$SEED_SOURCE_BACKUP"
  SEED_SOURCE_EXISTED=1
fi

restore_previous_evidence() {
  if test "$RELEASE_EVIDENCE_EXISTED" -eq 1; then
    install -m 0444 "$RELEASE_EVIDENCE_BACKUP" "$RELEASE_EVIDENCE_TMP"
    mv -f "$RELEASE_EVIDENCE_TMP" "$RELEASE_EVIDENCE_FILE"
  else
    rm -f "$RELEASE_EVIDENCE_FILE" "$RELEASE_EVIDENCE_TMP"
  fi
  if test "$SHARED_EVIDENCE_EXISTED" -eq 1; then
    install -m 0444 "$SHARED_EVIDENCE_BACKUP" "$SHARED_EVIDENCE_TMP"
    mv -f "$SHARED_EVIDENCE_TMP" "$SHARED_EVIDENCE_FILE"
  else
    rm -f "$SHARED_EVIDENCE_FILE" "$SHARED_EVIDENCE_TMP"
  fi
}

restore_previous_descriptor() {
  if test "$SEED_SOURCE_EXISTED" -eq 1; then
    install -m 0600 "$SEED_SOURCE_BACKUP" "$SEED_SOURCE_TMP"
    mv -f "$SEED_SOURCE_TMP" "$SEED_SOURCE_FILE"
  else
    rm -f "$SEED_SOURCE_FILE" "$SEED_SOURCE_TMP"
  fi
}

RAG_DIR='/opt/skn27-pilot/evidence-recovery/__MANIFEST_SHA256__'
cleanup_rag_seed() {
  rm -rf -- "$RAG_DIR"
}
cleanup_backups() {
  rm -f "$RELEASE_EVIDENCE_BACKUP" "$SHARED_EVIDENCE_BACKUP" "$SEED_SOURCE_BACKUP"
}
recovery_failed() {
  status=$?
  trap - ERR EXIT
  restore_previous_evidence 2>/dev/null || true
  restore_previous_descriptor 2>/dev/null || true
  cleanup_rag_seed 2>/dev/null || true
  cleanup_backups 2>/dev/null || true
  exit "$status"
}
trap recovery_failed ERR
trap cleanup_rag_seed EXIT

test ! -e "$RAG_DIR" && test ! -L "$RAG_DIR"
install -d -m 0700 "$RAG_DIR"
aws s3 cp '__RAG_SEED_S3_URI__' "$RAG_DIR/" --region '__AWS_REGION__' --recursive --only-show-errors
test -f "$RAG_DIR/__MANIFEST_RELATIVE_PATH__"
printf '%s  %s\n' '__MANIFEST_SHA256__' "$RAG_DIR/__MANIFEST_RELATIVE_PATH__" | sha256sum -c -
find "$RAG_DIR" -type d -exec chmod 0555 {} +
find "$RAG_DIR" -type f -exec chmod 0444 {} +

PILOT_BACKEND_IP="${PILOT_ONE_OFF_CONTAINER_IP:-172.31.0.11}" compose run --rm --no-deps -v "$RAG_DIR:/run/production-rag-seed:ro" backend \
  python backend/manage.py verify_production_rag_seed_manifest \
  --manifest /run/production-rag-seed/__MANIFEST_RELATIVE_PATH__ --format json
PILOT_BACKEND_IP="${PILOT_ONE_OFF_CONTAINER_IP:-172.31.0.11}" compose run --rm --no-deps -v "$RAG_DIR:/run/production-rag-seed:ro" backend \
  python backend/manage.py build_legal_operational_evidence \
  --manifest /run/production-rag-seed/__MANIFEST_RELATIVE_PATH__ \
  --dataset-version "$LEGAL_DATASET_VERSION" \
  --release-version '__RELEASE_TAG__' \
  --verified-at "$LEGAL_DATASET_VERIFIED_AT" > "$RELEASE_EVIDENCE_TMP"
PILOT_BACKEND_IP="${PILOT_ONE_OFF_CONTAINER_IP:-172.31.0.11}" compose run --rm --no-deps -v "$RELEASE_EVIDENCE_DIR:/run/release-evidence:ro" backend \
  python -m etl.legal.validate_run_summary \
  --summary /run/release-evidence/.run_summary.json.tmp \
  --max-age-hours "$LEGAL_MAX_AGE_HOURS" \
  --expected-dataset-version "$LEGAL_DATASET_VERSION" \
  --expected-release-version '__RELEASE_TAG__'
chmod 0444 "$RELEASE_EVIDENCE_TMP"
mv -f "$RELEASE_EVIDENCE_TMP" "$RELEASE_EVIDENCE_FILE"

install -m 0444 "$RELEASE_EVIDENCE_FILE" "$SHARED_EVIDENCE_TMP"
PILOT_BACKEND_IP="${PILOT_ONE_OFF_CONTAINER_IP:-172.31.0.11}" compose run --rm --no-deps -v "$SHARED_EVIDENCE_DIR:/run/operational-evidence:ro" backend \
  python -m etl.legal.validate_run_summary \
  --summary /run/operational-evidence/.run_summary.json.tmp \
  --max-age-hours "$LEGAL_MAX_AGE_HOURS" \
  --expected-dataset-version "$LEGAL_DATASET_VERSION" \
  --expected-release-version '__RELEASE_TAG__'
mv -f "$SHARED_EVIDENCE_TMP" "$SHARED_EVIDENCE_FILE"

printf '%s\n' \
  'RAG_SEED_S3_URI=__RAG_SEED_S3_URI__' \
  'RAG_SEED_MANIFEST_RELATIVE_PATH=__MANIFEST_RELATIVE_PATH__' \
  'RAG_SEED_MANIFEST_SHA256=__MANIFEST_SHA256__' > "$SEED_SOURCE_TMP"
chmod 0600 "$SEED_SOURCE_TMP"
mv -f "$SEED_SOURCE_TMP" "$SEED_SOURCE_FILE"

PILOT_OPS_MONITOR_IP="${PILOT_ONE_OFF_CONTAINER_IP:-172.31.0.11}" compose run --rm --no-deps ops-monitor \
  python backend/manage.py observe_operational_health --once --gate-mode transaction

cleanup_rag_seed
trap - EXIT
cleanup_backups
trap - ERR
'@

$remoteScript = $remoteScript.Replace("__AWS_REGION__", $region)
$remoteScript = $remoteScript.Replace("__RELEASE_TAG__", $ReleaseTag)
$remoteScript = $remoteScript.Replace("__RAG_SEED_S3_URI__", $RagSeedS3Uri)
$remoteScript = $remoteScript.Replace("__MANIFEST_RELATIVE_PATH__", $RagSeedManifestRelativePath)
$remoteScript = $remoteScript.Replace("__MANIFEST_SHA256__", $RagSeedManifestSha256)

$request = Join-Path ([IO.Path]::GetTempPath()) "skn27-evidence-recovery-$([guid]::NewGuid().ToString('N')).json"
try {
    @{
        DocumentName   = "AWS-RunShellScript"
        InstanceIds    = @($instanceId)
        Comment        = "Recover release-bound operational evidence for $ReleaseTag"
        TimeoutSeconds = $SsmTimeoutSeconds
        Parameters     = @{
            commands         = @($remoteScript)
            executionTimeout = @([string]$SsmTimeoutSeconds)
        }
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $request -Encoding utf8NoBOM

    $commandId = (& aws ssm send-command --region $region --cli-input-json "file://$request" --query "Command.CommandId" --output text --no-cli-pager).Trim()
    Assert-LastExitCode "Submit operational evidence recovery command"
    $result = Get-SsmCommandResult -Region $region -CommandId $commandId -InstanceId $instanceId -TimeoutSeconds $SsmTimeoutSeconds
    if ($result.Status -ne "Success") {
        throw "Operational evidence recovery failed with status '$($result.Status)'. Inspect SSM output through the redacted operations workflow."
    }
}
finally {
    Remove-Item -LiteralPath $request -Force -ErrorAction SilentlyContinue
}

Write-Host "Operational evidence recovery completed for release $ReleaseTag."
