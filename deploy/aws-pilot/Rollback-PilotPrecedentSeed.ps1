#requires -Version 7.2
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^sha256:[0-9a-f]{64}$")]
    [string]$ExpectedActiveSeedVersion,

    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[a-z0-9][a-z0-9-]{0,31}$")]
    [string]$ReleaseTag,

    [string]$TerraformDirectory = (Join-Path $PSScriptRoot "..\..\infra\terraform-pilot"),
    [ValidateRange(600, 3600)]
    [int]$SsmTimeoutSeconds = 1200
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$databaseMaintenanceCommandSubmitted = $false
$databaseMaintenanceTerminalConfirmed = $false

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
    # Pending, InProgress, Delayed, and Cancelling remain non-terminal.
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
    throw "Precedent seed rollback cancellation did not reach a terminal status; the maintenance profile and marker remain active."
}

function Invoke-SsmScript(
    [string]$Comment,
    [string[]]$Commands,
    [switch]$TrackDatabaseMaintenance
) {
    $request = Join-Path ([IO.Path]::GetTempPath()) "skn27-precedent-rollback-$([guid]::NewGuid().ToString('N')).json"
    try {
        @{
            DocumentName = "AWS-RunShellScript"
            InstanceIds  = @($instanceId)
            Comment      = $Comment
            Parameters   = @{ commands = $Commands }
        } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $request -Encoding utf8NoBOM
        $commandId = (& aws ssm send-command --region $region --cli-input-json "file://$request" --query "Command.CommandId" --output text --no-cli-pager).Trim()
        Assert-LastExitCode "Submit $Comment"
        if ($TrackDatabaseMaintenance) {
            $script:databaseMaintenanceCommandSubmitted = $true
        }
        $result = Get-SsmCommandResult $region $commandId $instanceId $SsmTimeoutSeconds
        if ($TrackDatabaseMaintenance) {
            $script:databaseMaintenanceTerminalConfirmed = $true
        }
        if ($result.Status -ne "Success") {
            throw "$Comment failed with status '$($result.Status)'. Inspect the redacted SSM output."
        }
    }
    finally {
        Remove-Item -LiteralPath $request -Force -ErrorAction SilentlyContinue
    }
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
$runtimeProfile = [string]$outputs.database_runtime_instance_profile_name.value
$runtimeRoleName = [string]$outputs.database_runtime_role_name.value
$maintenanceProfile = [string]$outputs.database_maintenance_instance_profile_name.value
$maintenanceRoleName = [string]$outputs.database_maintenance_role_name.value
$masterSecretArn = [string]$outputs.database_master_credential_arn.value
$appSecretArn = [string]$outputs.app_database_credential_arn.value
$databaseHost = [string]$outputs.database_address.value
$databasePort = [string]$outputs.database_port.value
$databaseName = [string]$outputs.database_name.value
$parameterName = [string]$outputs.runtime_env_parameter_name.value
$backendRepository = [string]$outputs.backend_repository_url.value
$registry = $backendRepository.Split("/")[0]
$maintenanceMarker = "/opt/skn27-pilot/maintenance/database-maintenance.active"

$associationId = (& aws ec2 describe-iam-instance-profile-associations --region $region --filters "Name=instance-id,Values=$instanceId" --query "IamInstanceProfileAssociations[0].AssociationId" --output text --no-cli-pager).Trim()
Assert-LastExitCode "Discover runtime instance profile association"

Invoke-SsmScript "Fence runtime before precedent seed rollback" @(
    "set -euo pipefail",
    "exec 8>/var/lock/skn27-pilot-maintenance.lock",
    "flock -w 60 8",
    "test ! -e '$maintenanceMarker' || { echo 'Database maintenance marker is already active.' >&2; exit 75; }",
    "RUNTIME_ROLE_ARN=`$(aws sts get-caller-identity --query Arn --output text --no-cli-pager)",
    "case `"`$RUNTIME_ROLE_ARN`" in */$runtimeRoleName/*) ;; *) echo 'Runtime role identity check failed.' >&2; exit 77 ;; esac",
    "test ! -L /opt/skn27-pilot/current || (cd /opt/skn27-pilot/current && docker compose --project-name skn27-pilot --env-file .compose.env --env-file .production-compose.env -f docker-compose.pilot.yml down)",
    "install -d -o root -g root -m 0700 /opt/skn27-pilot/maintenance",
    "install -m 0600 /dev/null '$maintenanceMarker'"
)

try {
    $associationId = (& aws ec2 replace-iam-instance-profile-association `
        --region $region `
        --association-id $associationId `
        --iam-instance-profile "Name=$maintenanceProfile" `
        --query "IamInstanceProfileAssociation.AssociationId" `
        --output text `
        --no-cli-pager).Trim()
    Assert-LastExitCode "Activate database maintenance profile"
    Start-Sleep -Seconds 20

    $commands = @(
        "set -euo pipefail",
        "exec 8>/var/lock/skn27-pilot-maintenance.lock",
        "flock -w 60 8",
        "test -f '$maintenanceMarker'",
        "test `$(stat -c '%u' '$maintenanceMarker') -eq 0",
        "test `$(stat -c '%a' '$maintenanceMarker') -eq 600",
        "MAINTENANCE_ROLE_ARN=`$(aws sts get-caller-identity --query Arn --output text --no-cli-pager)",
        "case `"`$MAINTENANCE_ROLE_ARN`" in */$maintenanceRoleName/*) ;; *) echo 'Maintenance role identity check failed.' >&2; exit 77 ;; esac",
        "WORK=`$(mktemp -d)",
        "cleanup_db_secrets() { find `$WORK -type f -exec shred -u -- {} + 2>/dev/null || true; rm -rf -- `$WORK; }",
        "trap cleanup_db_secrets EXIT",
        "umask 077",
        "aws secretsmanager get-secret-value --region '$region' --secret-id '$masterSecretArn' --query SecretString --output text > `$WORK/master.json",
        "aws secretsmanager get-secret-value --region '$region' --secret-id '$appSecretArn' --query SecretString --output text > `$WORK/app.json",
        "aws ssm get-parameter --region '$region' --name '$parameterName' --with-decryption --query Parameter.Value --output text > `$WORK/base.env",
        "python3 -c 'import json,sys; b=open(sys.argv[1]).read().splitlines(); m=json.load(open(sys.argv[2])); u=m[`"username`"]; p=m[`"password`"]; out=[x for x in b if not x.startswith(`"POSTGRES_`") and not x.startswith(`"DJANGO_DATABASE_ENGINE=`") and not x.startswith(`"PGSSLMODE=`")]; out += [`"DJANGO_DATABASE_ENGINE=postgres`",`"PGSSLMODE=require`",f`"POSTGRES_HOST={sys.argv[4]}`",f`"POSTGRES_PORT={sys.argv[5]}`",f`"POSTGRES_DB={sys.argv[6]}`",f`"POSTGRES_USER={u}`",f`"POSTGRES_PASSWORD={p}`"]; open(sys.argv[3],`"w`").write(`"\n`".join(out)+`"\n`")' `$WORK/base.env `$WORK/master.json `$WORK/master.env '$databaseHost' '$databasePort' '$databaseName'",
        "python3 -c 'import json,sys; b=open(sys.argv[1]).read().splitlines(); a=json.load(open(sys.argv[2])); u=a[`"username`"]; p=a[`"password`"]; out=[x for x in b if not x.startswith(`"POSTGRES_`") and not x.startswith(`"DJANGO_DATABASE_ENGINE=`") and not x.startswith(`"PGSSLMODE=`")]; out += [`"DJANGO_DATABASE_ENGINE=postgres`",`"PGSSLMODE=require`",f`"POSTGRES_HOST={sys.argv[4]}`",f`"POSTGRES_PORT={sys.argv[5]}`",f`"POSTGRES_DB={sys.argv[6]}`",f`"POSTGRES_USER={u}`",f`"POSTGRES_PASSWORD={p}`"]; open(sys.argv[3],`"w`").write(`"\n`".join(out)+`"\n`")' `$WORK/base.env `$WORK/app.json `$WORK/app.env '$databaseHost' '$databasePort' '$databaseName'",
        "python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); u=m[`"username`"]; p=m[`"password`"]; out=[f`"PGHOST={sys.argv[3]}`",f`"PGPORT={sys.argv[4]}`",f`"PGDATABASE={sys.argv[5]}`",f`"PGUSER={u}`",f`"PGPASSWORD={p}`",`"PGSSLMODE=require`"]; open(sys.argv[2],`"w`").write(`"\n`".join(out)+`"\n`")' `$WORK/master.json `$WORK/libpq.env '$databaseHost' '$databasePort' '$databaseName'",
        "POSTGRES_MAINTENANCE_IMAGE_REF=`$(sed -n 's/^POSTGRES_MAINTENANCE_IMAGE_REF=//p' `$WORK/base.env); printf '%s' `"`$POSTGRES_MAINTENANCE_IMAGE_REF`" | grep -Eq '^postgres:16\.14-alpine3\.24@sha256:[0-9a-f]{64}$'",
        "aws ecr get-login-password --region '$region' | docker login --username AWS --password-stdin '$registry'",
        "docker pull '${backendRepository}:$ReleaseTag'",
        "docker pull `"`$POSTGRES_MAINTENANCE_IMAGE_REF`"",
        "CURRENT_POINTER=`$(docker run --rm --env-file `$WORK/libpq.env `"`$POSTGRES_MAINTENANCE_IMAGE_REF`" psql -AtF '|' -c `"SELECT active_seed_version, COALESCE(previous_seed_version, '') FROM precedent_newplusplus.active_seed WHERE singleton IS TRUE`")",
        "CURRENT_ACTIVE=`${CURRENT_POINTER%%|*}; CURRENT_PREVIOUS=`${CURRENT_POINTER#*|}; test `"`$CURRENT_ACTIVE`" = '$ExpectedActiveSeedVersion'",
        "if [ -z `"`$CURRENT_PREVIOUS`" ]; then echo 'PREVIOUS_SEED_UNAVAILABLE' >&2; exit 78; fi",
        "docker run --rm --env-file `$WORK/master.env '${backendRepository}:$ReleaseTag' python backend/manage.py rollback_precedent_newplusplus_seed --expected-active-seed-version '$ExpectedActiveSeedVersion' --format json > `$WORK/precedent-rollback.json",
        "python3 -c 'import json,re,sys; r=json.load(open(sys.argv[1])); a=r.get(`"active_seed_version`",`"`"); p=r.get(`"previous_seed_version`",`"`"); assert r.get(`"status`")==`"rolled_back`"; assert re.fullmatch(r`"sha256:[0-9a-f]{64}`",a); assert p==sys.argv[3]; open(sys.argv[2],`"w`").write(a)' `$WORK/precedent-rollback.json `$WORK/precedent-seed-version '$ExpectedActiveSeedVersion'",
        "python3 -c 'import sys; p=sys.argv[1]; v=open(sys.argv[2]).read(); lines=open(p).read().splitlines(); hits=[i for i,x in enumerate(lines) if x.startswith(`"PRECEDENT_NEWPLUSPLUS_SEED_VERSION=`")]; assert len(hits)==1; lines[hits[0]]=f`"PRECEDENT_NEWPLUSPLUS_SEED_VERSION={v}`"; open(sys.argv[3],`"w`").write(`"\n`".join(lines)+`"\n`")' `$WORK/base.env `$WORK/precedent-seed-version `$WORK/runtime-next.env",
        "aws ssm put-parameter --region '$region' --name '$parameterName' --type SecureString --overwrite --value file://`$WORK/runtime-next.env --no-cli-pager > /dev/null",
        "aws ssm get-parameter --region '$region' --name '$parameterName' --with-decryption --query Parameter.Value --output text > `$WORK/runtime-readback.env",
        "python3 -c 'import re,sys; v=open(sys.argv[2]).read(); m=re.findall(r`"(?m)^PRECEDENT_NEWPLUSPLUS_SEED_VERSION=(sha256:[0-9a-f]{64})$`",open(sys.argv[1]).read()); assert m==[v]' `$WORK/runtime-readback.env `$WORK/precedent-seed-version",
        "SEED_VERSION=`$(cat `$WORK/precedent-seed-version); docker run --rm --env-file `$WORK/master.env '${backendRepository}:$ReleaseTag' python backend/manage.py verify_precedent_newplusplus_seed --expected-seed-version `"`$SEED_VERSION`" --format json > `$WORK/precedent-master-verify.json",
        "SEED_VERSION=`$(cat `$WORK/precedent-seed-version); docker run --rm --env-file `$WORK/app.env '${backendRepository}:$ReleaseTag' python backend/manage.py verify_precedent_newplusplus_seed --expected-seed-version `"`$SEED_VERSION`" --format json > `$WORK/precedent-app-verify.json",
        "python3 -c 'import json,sys; v=open(sys.argv[3]).read(); results=[json.load(open(p)) for p in sys.argv[1:3]]; assert all(r.get(`"status`")==`"verified`" and r.get(`"seed_version`")==v for r in results)' `$WORK/precedent-master-verify.json `$WORK/precedent-app-verify.json `$WORK/precedent-seed-version",
        "cleanup_db_secrets",
        "trap - EXIT"
    )
    Invoke-SsmScript "Rollback precedent NEW++ seed and synchronize evidence" $commands -TrackDatabaseMaintenance
}
finally {
    if ($databaseMaintenanceCommandSubmitted -and -not $databaseMaintenanceTerminalConfirmed) {
        Write-Warning "Remote seed rollback terminal status is unconfirmed; the maintenance profile and marker remain active. Confirm termination before manual recovery."
    }
    else {
        & aws ec2 replace-iam-instance-profile-association --region $region --association-id $associationId --iam-instance-profile "Name=$runtimeProfile" --no-cli-pager | Out-Null
        Assert-LastExitCode "Restore database_runtime_instance_profile_name"
        Start-Sleep -Seconds 20
        Invoke-SsmScript "Confirm runtime role and clear seed rollback marker" @(
            "set -euo pipefail",
            "exec 8>/var/lock/skn27-pilot-maintenance.lock",
            "flock -w 60 8",
            "RUNTIME_ROLE_ARN=`$(aws sts get-caller-identity --query Arn --output text --no-cli-pager)",
            "case `"`$RUNTIME_ROLE_ARN`" in */$runtimeRoleName/*) ;; *) echo 'Runtime role restoration check failed; maintenance marker remains active.' >&2; exit 77 ;; esac",
            "test -f '$maintenanceMarker'",
            "rm -f '$maintenanceMarker'"
        )
    }
}

Write-Host "Precedent NEW++ seed rollback completed and the SSM evidence was synchronized."
