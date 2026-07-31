#requires -Version 7.2
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{12}$")]
    [string]$ReleaseTag,

    [ValidateRange(600, 3600)]
    [int]$AcceptanceSeconds = 600,

    [ValidateRange(600, 7200)]
    [int]$MaxWaitSeconds = 1200,

    [ValidateRange(10, 300)]
    [int]$IntervalSeconds = 60,

    [string]$TerraformDirectory = (Join-Path $PSScriptRoot "..\..\infra\terraform-pilot"),

    [ValidateRange(660, 7800)]
    [int]$SsmTimeoutSeconds = 1800
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

if ($MaxWaitSeconds -lt $AcceptanceSeconds) {
    throw "MaxWaitSeconds must be greater than or equal to AcceptanceSeconds."
}
if ($SsmTimeoutSeconds -lt ($MaxWaitSeconds + 60)) {
    throw "SsmTimeoutSeconds must allow MaxWaitSeconds plus a 60-second command margin."
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
    throw "Operational acceptance command cancellation did not reach a terminal status."
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

acceptance_seconds=__ACCEPTANCE_SECONDS__
max_wait_seconds=__MAX_WAIT_SECONDS__
interval_seconds=__INTERVAL_SECONDS__
overall_started_at="$(date +%s)"
pass_started_at=0

record_status() {
  current_time="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'release_tag=%s timestamp=%s decision=%s elapsed_seconds=%s\n' \
    '__RELEASE_TAG__' "$current_time" "$decision" "$consecutive_seconds"
}

while :; do
  set +e
  snapshot="$(PILOT_OPS_MONITOR_IP="${PILOT_ONE_OFF_CONTAINER_IP:-172.31.0.11}" compose run --rm --no-deps ops-monitor python backend/manage.py observe_operational_health --once --gate-mode acceptance)"
  gate_status=$?
  set -e
  if test "$gate_status" -ne 0; then
    decision=fail
    consecutive_seconds=0
    record_status
    exit 1
  fi

  decision="$(printf '%s\n' "$snapshot" | python3 -c 'import json,sys; value=(json.load(sys.stdin).get("gate") or {}).get("decision", "fail"); assert value in {"pass", "reset", "fail"}; print(value)')" || {
    decision=fail
    consecutive_seconds=0
    record_status
    exit 1
  }
  now="$(date +%s)"
  case "$decision" in
    pass)
      if test "$pass_started_at" -eq 0; then pass_started_at="$now"; fi
      consecutive_seconds=$((now - pass_started_at))
      ;;
    reset)
      pass_started_at=0
      consecutive_seconds=0
      ;;
    fail)
      consecutive_seconds=0
      record_status
      exit 1
      ;;
  esac
  record_status

  if test "$consecutive_seconds" -ge "$acceptance_seconds"; then
    exit 0
  fi
  waited_seconds=$((now - overall_started_at))
  if test "$waited_seconds" -ge "$max_wait_seconds"; then
    exit 1
  fi
  sleep "$interval_seconds"
done
'@

$remoteScript = $remoteScript.Replace("__RELEASE_TAG__", $ReleaseTag)
$remoteScript = $remoteScript.Replace("__ACCEPTANCE_SECONDS__", [string]$AcceptanceSeconds)
$remoteScript = $remoteScript.Replace("__MAX_WAIT_SECONDS__", [string]$MaxWaitSeconds)
$remoteScript = $remoteScript.Replace("__INTERVAL_SECONDS__", [string]$IntervalSeconds)

$request = Join-Path ([IO.Path]::GetTempPath()) "skn27-operational-acceptance-$([guid]::NewGuid().ToString('N')).json"
try {
    @{
        DocumentName   = "AWS-RunShellScript"
        InstanceIds    = @($instanceId)
        Comment        = "Confirm operational acceptance for $ReleaseTag"
        TimeoutSeconds = $SsmTimeoutSeconds
        Parameters     = @{
            commands         = @($remoteScript)
            executionTimeout = @([string]$SsmTimeoutSeconds)
        }
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $request -Encoding utf8NoBOM

    $commandId = (& aws ssm send-command --region $region --cli-input-json "file://$request" --query "Command.CommandId" --output text --no-cli-pager).Trim()
    Assert-LastExitCode "Submit operational acceptance command"
    $result = Get-SsmCommandResult -Region $region -CommandId $commandId -InstanceId $instanceId -TimeoutSeconds $SsmTimeoutSeconds
    if ($result.Status -ne "Success") {
        throw "Operational acceptance failed with status '$($result.Status)'. Inspect SSM output through the redacted operations workflow."
    }
}
finally {
    Remove-Item -LiteralPath $request -Force -ErrorAction SilentlyContinue
}

Write-Host "Operational acceptance completed for release $ReleaseTag after $AcceptanceSeconds consecutive seconds."
