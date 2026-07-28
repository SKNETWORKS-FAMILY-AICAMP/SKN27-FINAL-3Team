#requires -Version 7.2
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RuntimeEnvFile,

    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[a-zA-Z0-9._-]+$")]
    [string]$ReleaseTag,

    [string]$TerraformDirectory = (Join-Path $PSScriptRoot "..\..\infra\terraform-pilot"),
    [switch]$SkipBuild,
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

function Get-EnvValue([string]$Content, [string]$Name) {
    $match = [regex]::Match($Content, "(?m)^$([regex]::Escape($Name))=(.*)$")
    if (-not $match.Success) {
        throw "Runtime environment is missing '$Name'."
    }
    return $match.Groups[1].Value.Trim()
}

function Get-SsmCommandResult([string]$Region, [string]$CommandId, [string]$InstanceId, [int]$TimeoutSeconds) {
    $terminalStatuses = @("Success", "Cancelled", "TimedOut", "Failed")
    # Cancelling is non-terminal and must continue polling before profile restoration.
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
    throw "Database maintenance cancellation did not reach a terminal status; the maintenance profile and marker remain active."
}

function Invoke-SsmScript(
    [string]$Comment,
    [string[]]$Commands,
    [switch]$TrackDatabaseMaintenance
) {
    $request = Join-Path ([IO.Path]::GetTempPath()) "skn27-db-maint-$([guid]::NewGuid().ToString('N')).json"
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
        if ($result.Status -ne "Success") { throw "$Comment failed with status '$($result.Status)'." }
    }
    finally {
        Remove-Item -LiteralPath $request -Force -ErrorAction SilentlyContinue
    }
}

$terraformPath = (Resolve-Path -LiteralPath $TerraformDirectory).Path
$runtimePath = (Resolve-Path -LiteralPath $RuntimeEnvFile).Path
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$runtimeEnv = Get-Content -Raw -LiteralPath $runtimePath
$postgresMaintenanceImageRef = Get-EnvValue $runtimeEnv "POSTGRES_MAINTENANCE_IMAGE_REF"
if ($postgresMaintenanceImageRef -notmatch "^postgres:16\.14-alpine3\.24@sha256:[0-9a-f]{64}$") {
    throw "POSTGRES_MAINTENANCE_IMAGE_REF must use the reviewed postgres:16.14-alpine3.24 lowercase @sha256 digest."
}
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
$masterSecretArn = [string]$outputs.database_master_credential_arn.value # master_user_secret is maintenance-only
$appSecretArn = [string]$outputs.app_database_credential_arn.value
$appUsername = [string]$outputs.database_app_username.value
$databaseHost = [string]$outputs.database_address.value
$databasePort = [string]$outputs.database_port.value
$databaseName = [string]$outputs.database_name.value
$parameterName = [string]$outputs.runtime_env_parameter_name.value
$backendRepository = [string]$outputs.backend_repository_url.value
$registry = $backendRepository.Split("/")[0]
$maintenanceImageTag = "db-maint-$ReleaseTag"
$maintenanceMarker = "/opt/skn27-pilot/maintenance/database-maintenance.active"

if (-not $SkipBuild) {
    & aws ecr get-login-password --region $region | & docker login --username AWS --password-stdin $registry
    Assert-LastExitCode "ECR login"
    Push-Location $repoRoot
    try {
        & docker build --platform linux/amd64 -f Dockerfile -t "${backendRepository}:${maintenanceImageTag}" .
        Assert-LastExitCode "Build migration image"
        & docker push "${backendRepository}:${maintenanceImageTag}"
        Assert-LastExitCode "Push migration image"
    }
    finally {
        Pop-Location
    }
}

$parameterRequest = Join-Path ([IO.Path]::GetTempPath()) "skn27-db-runtime-$([guid]::NewGuid().ToString('N')).json"
try {
    @{
        Name      = $parameterName
        Type      = "SecureString"
        Tier      = "Standard"
        Value     = $runtimeEnv
        Overwrite = $true
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $parameterRequest -Encoding utf8NoBOM
    & aws ssm put-parameter --region $region --cli-input-json "file://$parameterRequest" --no-cli-pager | Out-Null
    Assert-LastExitCode "Store migration runtime environment"
}
finally {
    Remove-Item -LiteralPath $parameterRequest -Force -ErrorAction SilentlyContinue
}

$associationId = (& aws ec2 describe-iam-instance-profile-associations --region $region --filters "Name=instance-id,Values=$instanceId" --query "IamInstanceProfileAssociations[0].AssociationId" --output text --no-cli-pager).Trim()
Assert-LastExitCode "Discover runtime instance profile association"

Invoke-SsmScript "Fence runtime before database maintenance" @(
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
        "if ! aws secretsmanager get-secret-value --region '$region' --secret-id '$appSecretArn' --query SecretString --output text > `$WORK/app.json 2>/dev/null; then export APP_USERNAME='$appUsername' DB_HOST='$databaseHost' DB_PORT='$databasePort' DB_NAME='$databaseName' APP_JSON=`$WORK/app.json APP_PASSWORD=`$(openssl rand -base64 48 | tr -d '\n'); python3 -c 'import json,os; json.dump({`"username`":os.environ[`"APP_USERNAME`"],`"password`":os.environ[`"APP_PASSWORD`"],`"host`":os.environ[`"DB_HOST`"],`"port`":int(os.environ[`"DB_PORT`"]),`"dbname`":os.environ[`"DB_NAME`"]},open(os.environ[`"APP_JSON`"],`"w`"))'; aws secretsmanager put-secret-value --region '$region' --secret-id '$appSecretArn' --secret-string file://`$WORK/app.json >/dev/null; unset APP_PASSWORD; fi",
        "aws ssm get-parameter --region '$region' --name '$parameterName' --with-decryption --query Parameter.Value --output text > `$WORK/base.env",
        "python3 -c 'import json,sys; b=open(sys.argv[1]).read().splitlines(); m=json.load(open(sys.argv[2])); u=m[`"username`"]; p=m[`"password`"]; out=[x for x in b if not x.startswith(`"POSTGRES_`") and not x.startswith(`"DJANGO_DATABASE_ENGINE=`") and not x.startswith(`"PGSSLMODE=`")]; out += [`"DJANGO_DATABASE_ENGINE=postgres`",`"PGSSLMODE=require`",f`"POSTGRES_HOST={sys.argv[4]}`",f`"POSTGRES_PORT={sys.argv[5]}`",f`"POSTGRES_DB={sys.argv[6]}`",f`"POSTGRES_USER={u}`",f`"POSTGRES_PASSWORD={p}`"]; open(sys.argv[3],`"w`").write(`"\\n`".join(out)+`"\\n`")' `$WORK/base.env `$WORK/master.json `$WORK/master.env '$databaseHost' '$databasePort' '$databaseName'",
        "python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); u=m[`"username`"]; p=m[`"password`"]; out=[f`"PGHOST={sys.argv[3]}`",f`"PGPORT={sys.argv[4]}`",f`"PGDATABASE={sys.argv[5]}`",f`"PGUSER={u}`",f`"PGPASSWORD={p}`",`"PGSSLMODE=require`"] ; open(sys.argv[2],`"w`").write(`"\\n`".join(out)+`"\\n`")' `$WORK/master.json `$WORK/libpq.env '$databaseHost' '$databasePort' '$databaseName'",
        "python3 -c 'import json,sys; a=json.load(open(sys.argv[1])); open(sys.argv[2],`"w`").write(a[`"password`"])' `$WORK/app.json `$WORK/app-password",
        "aws ecr get-login-password --region '$region' | docker login --username AWS --password-stdin '$registry'",
        "docker pull '${backendRepository}:${maintenanceImageTag}'",
        "docker pull '$postgresMaintenanceImageRef'",
        "docker run --rm --env-file `$WORK/libpq.env '$postgresMaintenanceImageRef' psql -v ON_ERROR_STOP=1 -c 'CREATE EXTENSION IF NOT EXISTS vector'",
        "docker run --rm --env-file `$WORK/libpq.env '$postgresMaintenanceImageRef' psql -tAc `"SELECT 1 FROM pg_roles WHERE rolname='$appUsername'`" | grep -q 1 || docker run --rm --env-file `$WORK/libpq.env '$postgresMaintenanceImageRef' psql -v ON_ERROR_STOP=1 -c `"CREATE ROLE $appUsername LOGIN`"",
        "APP_PASSWORD=`$(cat `$WORK/app-password); docker run --rm --env-file `$WORK/libpq.env '$postgresMaintenanceImageRef' psql -v ON_ERROR_STOP=1 -c `"ALTER ROLE $appUsername PASSWORD '`$APP_PASSWORD'`"",
        "docker run --rm --env-file `$WORK/master.env '${backendRepository}:${maintenanceImageTag}' python backend/manage.py shell -c `"from django.db import connection; assert connection.vendor == 'postgresql'; cursor = connection.cursor(); cursor.execute('select current_database()'); assert cursor.fetchone()[0] == '$databaseName'`"",
        "docker run --rm --env-file `$WORK/master.env '${backendRepository}:${maintenanceImageTag}' python backend/manage.py migrate --noinput",
        "docker run --rm --env-file `$WORK/master.env '${backendRepository}:${maintenanceImageTag}' python -m etl.fault_cases.src.review_case.db_loading.schema_manager --apply-schema",
        "docker run --rm --env-file `$WORK/libpq.env '$postgresMaintenanceImageRef' psql -v ON_ERROR_STOP=1 -c 'GRANT CONNECT ON DATABASE $databaseName TO $appUsername' -c 'GRANT USAGE ON SCHEMA public TO $appUsername' -c 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO $appUsername' -c 'GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO $appUsername' -c 'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO $appUsername' -c 'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO $appUsername'",
        "cleanup_db_secrets",
        "trap - EXIT"
    )
    Invoke-SsmScript "Bootstrap app role and run migrations" $commands -TrackDatabaseMaintenance
}
finally {
    if ($databaseMaintenanceCommandSubmitted -and -not $databaseMaintenanceTerminalConfirmed) {
        Write-Warning "Remote database command terminal status is unconfirmed; the maintenance profile and marker remain active. Confirm termination before manual recovery."
    }
    else {
        & aws ec2 replace-iam-instance-profile-association --region $region --association-id $associationId --iam-instance-profile "Name=$runtimeProfile" --no-cli-pager | Out-Null
        Assert-LastExitCode "Restore database_runtime_instance_profile_name"
        Start-Sleep -Seconds 20
        Invoke-SsmScript "Confirm runtime role and clear marker" @(
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

Write-Host "Database migrations and least-privilege app role maintenance completed; run Deploy-Pilot.ps1 next."
