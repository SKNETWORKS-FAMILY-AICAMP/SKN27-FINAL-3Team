#requires -Version 7.2
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[a-z0-9][a-z0-9-]{0,31}$")]
    [string]$ReleaseTag,

    [string]$TerraformDirectory = (Join-Path $PSScriptRoot "..\..\infra\terraform-pilot"),
    [ValidateRange(600, 7200)]
    [int]$SsmTimeoutSeconds = 1800
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Get-SsmCommandResult(
    [string]$Region,
    [string]$CommandId,
    [string]$InstanceId,
    [int]$TimeoutSeconds
) {
    $terminalStatuses = @("Success", "Cancelled", "TimedOut", "Failed")
    # Pending, InProgress, Delayed, and Cancelling remain non-terminal.
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        $json = & aws ssm get-command-invocation `
            --region $Region `
            --command-id $CommandId `
            --instance-id $InstanceId `
            --output json `
            --no-cli-pager 2>$null
        if ($LASTEXITCODE -eq 0) {
            $result = $json | ConvertFrom-Json
            if ($result.Status -in $terminalStatuses) {
                return $result
            }
        }
        Start-Sleep -Seconds 10
    }

    & aws ssm cancel-command `
        --region $Region `
        --command-id $CommandId `
        --no-cli-pager | Out-Null
    for ($attempt = 1; $attempt -le 12; $attempt++) {
        $json = & aws ssm get-command-invocation `
            --region $Region `
            --command-id $CommandId `
            --instance-id $InstanceId `
            --output json `
            --no-cli-pager 2>$null
        if ($LASTEXITCODE -eq 0) {
            $result = $json | ConvertFrom-Json
            if ($result.Status -in $terminalStatuses) {
                return $result
            }
        }
        Start-Sleep -Seconds 5
    }
    throw "Rollback SSM command exceeded $TimeoutSeconds seconds and terminal cancellation was not confirmed."
}

Push-Location (Resolve-Path -LiteralPath $TerraformDirectory)
try {
    $outputs = (& terraform output -json) | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw "terraform output failed." }
}
finally {
    Pop-Location
}

$instanceId = [string]$outputs.instance_id.value
$region = [string]$outputs.aws_region.value
$parameterName = [string]$outputs.runtime_env_parameter_name.value
$registry = ([string]$outputs.backend_repository_url.value).Split("/")[0]
$releaseDirectory = "/opt/skn27-pilot/releases/$ReleaseTag"
$composeCommand = "docker compose --project-name skn27-pilot --env-file .compose.env --env-file .production-compose.env -f docker-compose.pilot.yml"
$commands = @(
    "set -eu",
    "exec 8>/var/lock/skn27-pilot-maintenance.lock",
    "flock -w 60 8",
    "test ! -e '/opt/skn27-pilot/maintenance/database-maintenance.active' || { echo 'Database maintenance marker is active.' >&2; exit 75; }",
    "test -d '$releaseDirectory'",
    "test -f '$releaseDirectory/.production-compose.env'",
    "PREVIOUS_RELEASE=`$(readlink -f /opt/skn27-pilot/current 2>/dev/null || true)",
    "cd '$releaseDirectory'",
    "aws ssm get-parameter --region '$region' --name '$parameterName' --with-decryption --query Parameter.Value --output text > .runtime.env.tmp",
    "tr -d '\r' < .runtime.env.tmp > .runtime.env",
    "rm -f .runtime.env.tmp",
    "grep -E '^(BACKEND_REPOSITORY_URL|FRONTEND_REPOSITORY_URL|CADDY_IMAGE_REF|HAPROXY_IMAGE_REF|REDIS_IMAGE_REF|CLAMAV_IMAGE_REF)=' .runtime.env > .compose.env",
    "printf 'RELEASE_TAG=%s\n' '$ReleaseTag' >> .compose.env",
    'for image_key in CADDY_IMAGE_REF HAPROXY_IMAGE_REF REDIS_IMAGE_REF CLAMAV_IMAGE_REF; do image_ref=$(sed -n "s/^${image_key}=//p" .compose.env); printf "%s\n" "$image_ref" | grep -Eq "@sha256:[0-9a-f]{64}$"; done',
    "test -f deployment-manifest.json",
    "python3 -c 'import json,re; m=json.load(open(`"deployment-manifest.json`")); assert re.search(`"@sha256:[0-9a-f]{64}$`",m[`"NginxImageRef`"]); assert re.search(`"@sha256:[0-9a-f]{64}$`",m[`"PostgresMaintenanceImageRef`"]);'",
    "grep -E '^(APP_DOMAIN|ACME_EMAIL)=' .runtime.env > .edge.env",
    "chmod 0600 .runtime.env .compose.env .edge.env",
    "/usr/local/sbin/skn27-imds-firewall.sh",
    "aws ecr get-login-password --region '$region' | docker login --username AWS --password-stdin '$registry'",
    "rollback_previous_release() { status=`$?; trap - ERR; cd '$releaseDirectory'; $composeCommand down >/dev/null 2>&1 || true; if [ -n `"`$PREVIOUS_RELEASE`" ] && [ -d `"`$PREVIOUS_RELEASE`" ]; then cd `$PREVIOUS_RELEASE; $composeCommand up -d --remove-orphans >/dev/null 2>&1 || echo 'Previous release restart needs operator attention.' >&2; ln -sfn `$PREVIOUS_RELEASE /opt/skn27-pilot/current; fi; exit `$status; }",
    "trap rollback_previous_release ERR",
    "$composeCommand up -d --wait --wait-timeout 600 --remove-orphans",
    "$composeCommand exec -T backend python backend/manage.py check_production_readiness --format json --fail-on-error",
    "$composeCommand exec -T backend python -c `"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health/live/', timeout=3)`"",
    "ln -sfn '$releaseDirectory' /opt/skn27-pilot/current",
    "trap - ERR"
)

$request = Join-Path ([IO.Path]::GetTempPath()) "skn27-rollback-$([guid]::NewGuid().ToString('N')).json"
try {
    @{
        DocumentName = "AWS-RunShellScript"
        InstanceIds  = @($instanceId)
        Comment      = "Rollback SKN27 pilot to $ReleaseTag"
        Parameters   = @{ commands = $commands }
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $request -Encoding utf8NoBOM

    $commandId = (& aws ssm send-command --region $region --cli-input-json "file://$request" --query "Command.CommandId" --output text --no-cli-pager).Trim()
    if ($LASTEXITCODE -ne 0) { throw "Rollback SSM command submission failed." }
    $commandResult = Get-SsmCommandResult `
        -Region $region `
        -CommandId $commandId `
        -InstanceId $instanceId `
        -TimeoutSeconds $SsmTimeoutSeconds
    if ($commandResult.Status -ne "Success") {
        throw "Remote rollback failed with status '$($commandResult.Status)'. Inspect SSM output through the redacted operations workflow."
    }
}
finally {
    Remove-Item -LiteralPath $request -Force -ErrorAction SilentlyContinue
}

Write-Host "Pilot runtime rolled back to release $ReleaseTag. Database migrations were not reversed."
