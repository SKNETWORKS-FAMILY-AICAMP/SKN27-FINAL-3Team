#requires -Version 7.2
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RuntimeEnvFile,

    [string]$TerraformDirectory = (Join-Path $PSScriptRoot "..\..\infra\terraform-pilot"),

    [ValidatePattern("^[a-z0-9][a-z0-9-]{0,31}$")]
    [string]$ReleaseTag = (Get-Date -Format "yyyyMMdd-HHmmss"),

    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedRagSeedManifestSha256,

    [string]$FineNoticeSmokeS3Uri,

    [switch]$SkipBuild,
    [switch]$StageForInitialRagBootstrap,
    [switch]$StageForReleaseUpdate,
    [switch]$AllowCaddyOfflineForHostNetworkCutover,
    [switch]$AllowPaidNonDlSmoke,
    [switch]$AllowPaidSupervisorSmoke,
    [switch]$RequireGoogleLiveSmoke,
    [ValidateRange(600, 7200)]
    [int]$SsmTimeoutSeconds = 1800
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Assert-LastExitCode([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE."
    }
}

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found."
    }
}

function Assert-IntegrationDependency([string]$Path, [string]$Issue) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Integration dependency $Issue is missing: $Path. Merge the dependency before deploying."
    }
}

function Assert-IntegrationMarkerAbsent(
    [string]$Path,
    [string]$Marker,
    [string]$Issue
) {
    Assert-IntegrationDependency $Path $Issue
    if ((Get-Content -Raw -LiteralPath $Path).Contains($Marker)) {
        throw "Integration dependency $Issue is incomplete: forbidden marker '$Marker' remains in $Path."
    }
}

function Assert-IntegrationMarkerPresent(
    [string]$Path,
    [string]$Marker,
    [string]$Issue
) {
    Assert-IntegrationDependency $Path $Issue
    if (-not (Get-Content -Raw -LiteralPath $Path).Contains($Marker)) {
        throw "Integration dependency $Issue is incomplete: required marker '$Marker' is missing from $Path."
    }
}

function Get-TerraformValue([object]$Outputs, [string]$Name) {
    $property = $Outputs.PSObject.Properties[$Name]
    if ($null -eq $property -or $null -eq $property.Value.value) {
        throw "Terraform output '$Name' is missing. Apply the reviewed pilot plan first."
    }
    return [string]$property.Value.value
}

function Get-EnvValue([string]$Content, [string]$Name) {
    $match = [regex]::Match($Content, "(?m)^$([regex]::Escape($Name))=(.*)$")
    if (-not $match.Success) {
        throw "Runtime environment is missing '$Name'."
    }
    return $match.Groups[1].Value.Trim()
}

function Set-EnvValue([string]$Content, [string]$Name, [string]$Value) {
    if ($Value.Contains("`r") -or $Value.Contains("`n")) {
        throw "Environment value '$Name' must be one line."
    }
    $line = "$Name=$Value"
    $pattern = "(?m)^$([regex]::Escape($Name))=.*$"
    if ([regex]::IsMatch($Content, $pattern)) {
        $literalReplacement = [Text.RegularExpressions.MatchEvaluator]{
            param($match)
            return $line
        }
        return [regex]::Replace($Content, $pattern, $literalReplacement)
    }
    return $Content.TrimEnd() + "`n" + $line + "`n"
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
    throw "SSM command $CommandId exceeded $TimeoutSeconds seconds and terminal cancellation was not confirmed."
}

function Invoke-PublicHealthCheck([string]$Uri, [int]$MaxAttempts = 12) {
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            Invoke-WebRequest -Uri $Uri -Method Get -TimeoutSec 10 | Out-Null
            return
        }
        catch {
            if ($attempt -eq $MaxAttempts) {
                throw "Public health check failed after $MaxAttempts attempts: $Uri"
            }
            Start-Sleep -Seconds 10
        }
    }
}

foreach ($command in @("aws", "docker", "terraform")) {
    Require-Command $command
}

$runtimePath = (Resolve-Path -LiteralPath $RuntimeEnvFile).Path
$terraformPath = (Resolve-Path -LiteralPath $TerraformDirectory).Path
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$runtimeEnv = Get-Content -Raw -LiteralPath $runtimePath

foreach ($dependency in @(
        @("backend/chatbot/management/commands/smoke_google_oauth_code.py", "#192"),
        @("backend/chatbot/management/commands/smoke_non_dl_analysis_reporting_pipeline.py", "#173/#193"),
        @("backend/chatbot/management/commands/load_production_rag_seed.py", "#198"),
        @("backend/chatbot/management/commands/verify_production_rag_seed_manifest.py", "#198"),
        @("backend/chatbot/management/commands/load_legal_rag_pgvector.py", "#198")
    )) {
    Assert-IntegrationDependency (Join-Path $repoRoot $dependency[0]) $dependency[1]
}
$nonDlSmokePath = Join-Path $repoRoot "backend/chatbot/management/commands/smoke_non_dl_analysis_reporting_pipeline.py"
Assert-IntegrationMarkerPresent $nonDlSmokePath "--fine-notice-fixture-s3-uri" "#193"
Assert-IntegrationMarkerPresent $nonDlSmokePath "fine_notice_analysis" "#193"
Assert-IntegrationMarkerPresent $nonDlSmokePath "appeal_decision_flow" "#193"
Assert-IntegrationMarkerPresent $nonDlSmokePath "law_ground_search" "#193"
Assert-IntegrationMarkerPresent $nonDlSmokePath "text_ml_case_search" "#193"
$ragSeedLoaderPath = Join-Path $repoRoot "backend/chatbot/management/commands/load_production_rag_seed.py"
$legalPgvectorLoaderPath = Join-Path $repoRoot "backend/chatbot/management/commands/load_legal_rag_pgvector.py"
$legalGraphLoaderPath = Join-Path $repoRoot "backend/chatbot/management/commands/load_legal_graph_seed.py"
Assert-IntegrationMarkerPresent $ragSeedLoaderPath "load_and_validate_rag_seed_manifest" "#198"
Assert-IntegrationMarkerPresent $ragSeedLoaderPath "load_legal_rag_pgvector" "#198"
Assert-IntegrationMarkerPresent $legalPgvectorLoaderPath "transaction.atomic" "#198"
Assert-IntegrationMarkerPresent $legalGraphLoaderPath "load_and_validate_rag_seed_manifest" "legal graph seed"
Assert-IntegrationMarkerPresent $legalGraphLoaderPath "LegalGraphDataset" "legal graph seed"
$textMlAgentPath = Join-Path $repoRoot "ai/agents/text_ml_case_search/agent.py"
Assert-IntegrationMarkerAbsent $textMlAgentPath "case_text_ml_heuristic_001" "#195"
if ($RequireGoogleLiveSmoke) {
    $googleSmokePath = Join-Path $repoRoot "backend/chatbot/management/commands/smoke_google_oauth_code.py"
    Assert-IntegrationMarkerPresent $googleSmokePath "GOOGLE_OAUTH_SMOKE_CODE" "#192"
    Assert-IntegrationMarkerPresent $googleSmokePath "--verify-replay-rejection" "#192"
}

$appDomain = Get-EnvValue $runtimeEnv "APP_DOMAIN"
if (
    $appDomain -cne $appDomain.ToLowerInvariant() -or
    [Uri]::CheckHostName($appDomain) -ne [UriHostNameType]::Dns
) {
    throw "APP_DOMAIN must be a lowercase DNS hostname without a scheme, port, or path."
}
$expectedOrigin = "https://$appDomain"
$allowedHosts = (Get-EnvValue $runtimeEnv "DJANGO_ALLOWED_HOSTS").Split(",") |
    ForEach-Object { $_.Trim() }
if ($allowedHosts | Where-Object { $_.Contains("*") -or $_.StartsWith(".") }) {
    throw "DJANGO_ALLOWED_HOSTS must not contain wildcards."
}
if ($appDomain -cnotin $allowedHosts) {
    throw "DJANGO_ALLOWED_HOSTS must include APP_DOMAIN '$appDomain'."
}
foreach ($internalHealthHost in @("localhost", "127.0.0.1", "backend")) {
    if ($internalHealthHost -notin $allowedHosts) {
        throw "DJANGO_ALLOWED_HOSTS must include internal health host '$internalHealthHost'."
    }
}
# CORS_ALLOWED_ORIGINS must contain exactly the canonical public origin.
# CSRF_TRUSTED_ORIGINS must contain exactly the canonical public origin.
foreach ($originSetting in @("CORS_ALLOWED_ORIGINS", "CSRF_TRUSTED_ORIGINS")) {
    $origins = @((Get-EnvValue $runtimeEnv $originSetting).Split(",") |
        ForEach-Object { $_.Trim() } |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ($origins.Count -ne 1 -or $origins[0] -cne $expectedOrigin) {
        throw "$originSetting must contain exactly '$expectedOrigin'."
    }
}
$googleRedirect = [Uri](Get-EnvValue $runtimeEnv "GOOGLE_POPUP_REDIRECT_URI")
if (
    -not $googleRedirect.IsAbsoluteUri -or
    $googleRedirect.OriginalString -cnotin @($expectedOrigin, "$expectedOrigin/") -or
    $googleRedirect.Scheme -cne "https" -or
    $googleRedirect.Host -cne $appDomain -or
    -not $googleRedirect.IsDefaultPort -or
    $googleRedirect.Port -ne 443 -or
    $googleRedirect.AbsolutePath -ne "/" -or
    -not [string]::IsNullOrEmpty($googleRedirect.Query) -or
    -not [string]::IsNullOrEmpty($googleRedirect.Fragment) -or
    -not [string]::IsNullOrEmpty($googleRedirect.UserInfo)
) {
    throw "GOOGLE_POPUP_REDIRECT_URI must be the same HTTPS origin as APP_DOMAIN with default port 443 and no path, query, or fragment."
}

if ($RequireGoogleLiveSmoke -and -not $SkipBuild) {
    throw "-RequireGoogleLiveSmoke requires -SkipBuild so the short-lived code is acquired only after images are built and staged."
}

if ($StageForInitialRagBootstrap -and $StageForReleaseUpdate) {
    throw "Initial RAG bootstrap and release update staging are mutually exclusive."
}
if ($AllowCaddyOfflineForHostNetworkCutover -and -not $StageForReleaseUpdate) {
    throw "-AllowCaddyOfflineForHostNetworkCutover requires -StageForReleaseUpdate."
}
$isStageMode = $StageForInitialRagBootstrap -or $StageForReleaseUpdate

if ($isStageMode) {
    if ($RequireGoogleLiveSmoke) {
        throw "RAG staging cannot run Google live smoke; use the final normal -SkipBuild deployment."
    }
}
else {
    if (-not $SkipBuild) {
        throw "Normal promotion requires -SkipBuild and an exact staged release."
    }
    if (-not $AllowPaidNonDlSmoke) {
        throw "Deployment requires explicit -AllowPaidNonDlSmoke consent for the single paid non-DL acceptance smoke."
    }
    if (-not $AllowPaidSupervisorSmoke) {
        throw "Deployment requires explicit -AllowPaidSupervisorSmoke consent for the Supervisor provider acceptance smoke."
    }
}

if ($runtimeEnv -match "(?m)=REPLACE_|(?m)=INJECTED_") {
    $nonGenerated = @(
        $runtimeEnv -split "`r?`n" | Where-Object {
            $_ -match "=REPLACE_"
        }
    )
    if ($nonGenerated.Count -gt 0) {
        throw "Replace all REPLACE_ values in the runtime env file before deployment."
    }
}

Push-Location $terraformPath
try {
    $outputJson = & terraform output -json
    Assert-LastExitCode "terraform output"
}
finally {
    Pop-Location
}
$outputs = $outputJson | ConvertFrom-Json

$instanceId = Get-TerraformValue $outputs "instance_id"
$region = Get-TerraformValue $outputs "aws_region"
$operationalLogGroup = Get-TerraformValue $outputs "operational_log_group_name"
$googleCodeParameterName = if ($RequireGoogleLiveSmoke) {
    Get-TerraformValue $outputs "google_live_code_parameter_name"
}
else {
    ""
}

$staging = $null
$bundle = $null
try {
$cleanBucket = Get-TerraformValue $outputs "clean_bucket_name"
if (-not $isStageMode) {
    if ([string]::IsNullOrWhiteSpace($FineNoticeSmokeS3Uri)) {
        throw "Normal deployment requires -FineNoticeSmokeS3Uri."
    }
    try {
        $fineNoticeFixtureUri = [Uri]$FineNoticeSmokeS3Uri
    }
    catch {
        throw "FineNoticeSmokeS3Uri must be a valid S3 object URI."
    }
    $expectedFineNoticePrefix = "s3://$cleanBucket/canonical/acceptance/"
    if (
        $fineNoticeFixtureUri.Scheme -cne "s3" -or
        $fineNoticeFixtureUri.Host -cne $cleanBucket -or
        -not $FineNoticeSmokeS3Uri.StartsWith($expectedFineNoticePrefix, [StringComparison]::Ordinal)
    ) {
        throw "FineNoticeSmokeS3Uri must use the generated clean bucket and canonical/acceptance/ prefix."
    }
    if (
        -not [string]::IsNullOrEmpty($fineNoticeFixtureUri.Query) -or
        -not [string]::IsNullOrEmpty($fineNoticeFixtureUri.Fragment)
    ) {
        throw "The fine-notice fixture URI cannot contain query or fragment components."
    }
    $fineNoticeFixtureKey = $fineNoticeFixtureUri.AbsolutePath.TrimStart("/")
    if ($fineNoticeFixtureKey -match "(^|/)\.\.(/|$)") {
        throw "The fine-notice fixture URI cannot contain traversal segments."
    }
    if (
        $fineNoticeFixtureKey -cnotmatch "^canonical/acceptance/[A-Za-z0-9._/-]+\.(png|jpg|jpeg|webp|pdf)$" -or
        $fineNoticeFixtureKey.Contains("//") -or
        $FineNoticeSmokeS3Uri -cne "s3://$cleanBucket/$fineNoticeFixtureKey"
    ) {
        throw "FineNoticeSmokeS3Uri must name a sanitized png|jpg|jpeg|webp|pdf object under canonical/acceptance/."
    }
}

$appDatabaseSecretArn = Get-TerraformValue $outputs "app_database_credential_arn"
$appDatabaseCredentialText = (& aws secretsmanager get-secret-value `
    --region $region `
    --secret-id $appDatabaseSecretArn `
    --query SecretString `
    --output text `
    --no-cli-pager 2>$null)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($appDatabaseCredentialText)) {
    throw "Application database secret is not initialized. Run Maintain-PilotDatabase.ps1 before deployment."
}
$appDatabaseCredential = $appDatabaseCredentialText | ConvertFrom-Json

$generatedValues = [ordered]@{
    POSTGRES_HOST                   = Get-TerraformValue $outputs "database_address"
    POSTGRES_PORT                   = Get-TerraformValue $outputs "database_port"
    POSTGRES_USER                   = [string]$appDatabaseCredential.username
    POSTGRES_PASSWORD               = [string]$appDatabaseCredential.password
    POSTGRES_DB                     = Get-TerraformValue $outputs "database_name"
    AWS_REGION                      = $region
    AWS_DEFAULT_REGION              = $region
    OBJECT_STORAGE_REGION           = $region
    OBJECT_STORAGE_BUCKET           = $cleanBucket
    OBJECT_STORAGE_QUARANTINE_BUCKET = Get-TerraformValue $outputs "quarantine_bucket_name"
    BACKEND_REPOSITORY_URL          = Get-TerraformValue $outputs "backend_repository_url"
    FRONTEND_REPOSITORY_URL         = Get-TerraformValue $outputs "frontend_repository_url"
    RELEASE_TAG                     = $ReleaseTag
    OPERATIONAL_LOG_GROUP           = $operationalLogGroup
    LEGAL_RAG_SEED_MANIFEST_SHA256  = $ExpectedRagSeedManifestSha256
}
foreach ($entry in $generatedValues.GetEnumerator()) {
    $runtimeEnv = Set-EnvValue $runtimeEnv $entry.Key $entry.Value
}

if ($runtimeEnv -match "(?m)=(REPLACE_|INJECTED_)") {
    throw "Unresolved template value remains in the runtime environment."
}

$requiredRuntimeValues = @(
    "APP_DOMAIN",
    "ACME_EMAIL",
    "DJANGO_SECRET_KEY",
    "APP_JWT_SECRET",
    "OAUTH_TOKEN_SECRET",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_POPUP_REDIRECT_URI",
    "GOOGLE_OAUTH_CODE_EXCHANGE_DAILY_LIMIT",
    "GOOGLE_OAUTH_TRUSTED_PROXY_CIDRS",
    "OPENAI_API_KEY",
    "CADDY_IMAGE_REF",
    "HAPROXY_IMAGE_REF",
    "REDIS_IMAGE_REF",
    "CLAMAV_IMAGE_REF",
    "NGINX_IMAGE_REF",
    "POSTGRES_MAINTENANCE_IMAGE_REF",
    "LAW_NEO4J_IMAGE_REF",
    "NEO4J_URI",
    "NEO4J_USER",
    "NEO4J_PASSWORD",
    "NEO4J_DATABASE",
    "LAW_GRAPH_REQUIRED",
    "LEGAL_RAG_SEED_MANIFEST_SHA256",
    "OPERATIONAL_LOG_GROUP"
)
foreach ($name in $requiredRuntimeValues) {
    if ([string]::IsNullOrWhiteSpace((Get-EnvValue $runtimeEnv $name))) {
        throw "Runtime environment value '$name' must not be empty."
    }
}
foreach ($name in @("DJANGO_SECRET_KEY", "APP_JWT_SECRET", "OAUTH_TOKEN_SECRET")) {
    if ((Get-EnvValue $runtimeEnv $name).Length -lt 32) {
        throw "Runtime secret '$name' must contain at least 32 characters."
    }
}

foreach ($name in @("CADDY_IMAGE_REF", "HAPROXY_IMAGE_REF", "REDIS_IMAGE_REF", "CLAMAV_IMAGE_REF", "NGINX_IMAGE_REF", "POSTGRES_MAINTENANCE_IMAGE_REF", "LAW_NEO4J_IMAGE_REF")) {
    $imageRef = Get-EnvValue $runtimeEnv $name
    if ($imageRef -notmatch "@sha256:[0-9a-f]{64}$") {
        throw "Runtime image '$name' must be pinned to a reviewed lowercase @sha256 digest."
    }
}

$runtimeBytes = [Text.Encoding]::UTF8.GetByteCount($runtimeEnv)
if ($runtimeBytes -gt 4096) {
    throw "Runtime env is $runtimeBytes bytes; an SSM Standard parameter is limited to 4096 bytes."
}

$parameterName = Get-TerraformValue $outputs "runtime_env_parameter_name"
$parameterRequest = Join-Path ([IO.Path]::GetTempPath()) "skn27-ssm-$([guid]::NewGuid().ToString('N')).json"
try {
    @{
        Name        = $parameterName
        Description = "SKN27 pilot Docker runtime environment"
        Type        = "SecureString"
        Tier        = "Standard"
        Value       = $runtimeEnv
        Overwrite   = $true
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $parameterRequest -Encoding utf8NoBOM
    & aws ssm put-parameter `
        --region $region `
        --cli-input-json "file://$parameterRequest" `
        --no-cli-pager | Out-Null
    Assert-LastExitCode "SSM SecureString update"
}
finally {
    Remove-Item -LiteralPath $parameterRequest -Force -ErrorAction SilentlyContinue
}

$backendRepository = $generatedValues.BACKEND_REPOSITORY_URL
$frontendRepository = $generatedValues.FRONTEND_REPOSITORY_URL
$registry = $backendRepository.Split("/")[0]
$googleClientId = Get-EnvValue $runtimeEnv "GOOGLE_CLIENT_ID"
$nginxImageRef = Get-EnvValue $runtimeEnv "NGINX_IMAGE_REF"
$postgresMaintenanceImageRef = Get-EnvValue $runtimeEnv "POSTGRES_MAINTENANCE_IMAGE_REF"

if (-not $SkipBuild) {
    & aws ecr get-login-password --region $region |
        & docker login --username AWS --password-stdin $registry
    Assert-LastExitCode "ECR login"

    Push-Location $repoRoot
    try {
        & docker build --platform linux/amd64 -f Dockerfile -t "${backendRepository}:${ReleaseTag}" .
        Assert-LastExitCode "docker build backend"
        & docker build `
            --platform linux/amd64 `
            -f deploy/aws-pilot/Dockerfile.frontend `
            --build-arg "VITE_GOOGLE_CLIENT_ID=$googleClientId" `
            --build-arg "NGINX_IMAGE_REF=$nginxImageRef" `
            -t "${frontendRepository}:${ReleaseTag}" .
        Assert-LastExitCode "docker build frontend"
        & docker push "${backendRepository}:${ReleaseTag}"
        Assert-LastExitCode "docker push backend"
        & docker push "${frontendRepository}:${ReleaseTag}"
        Assert-LastExitCode "docker push frontend"
    }
    finally {
        Pop-Location
    }
}

$staging = Join-Path ([IO.Path]::GetTempPath()) "skn27-pilot-$([guid]::NewGuid().ToString('N'))"
$bundle = "$staging.zip"
New-Item -ItemType Directory -Path $staging | Out-Null
try {
    foreach ($name in @("docker-compose.pilot.yml", "Caddyfile", "haproxy.cfg", "configure-imds-firewall.sh")) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $staging
    }
    Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $bundle

    $bucket = $generatedValues.OBJECT_STORAGE_BUCKET
    $bundleKey = "_deploy/$ReleaseTag/pilot-bundle.zip"
    $manifestKey = "_deploy/$ReleaseTag/deployment-manifest.json"
    $BundleSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $bundle).Hash.ToLowerInvariant()
    & aws s3 cp $bundle "s3://$bucket/$bundleKey" `
        --region $region `
        --sse AES256 `
        --no-progress
    Assert-LastExitCode "aws s3 cp deployment bundle"

    $BundleVersionId = (& aws s3api head-object `
        --bucket $bucket `
        --key $bundleKey `
        --region $region `
        --query VersionId `
        --output text `
        --no-cli-pager).Trim()
    Assert-LastExitCode "Resolve deployment bundle version"
    if ([string]::IsNullOrWhiteSpace($BundleVersionId) -or $BundleVersionId -eq "None") {
        throw "Versioned deployment bundle is required. Verify clean-bucket versioning."
    }

    $manifestPath = Join-Path $staging "deployment-manifest.json"
    [ordered]@{
        SchemaVersion   = "skn27-pilot-deployment.v1"
        ReleaseTag      = $ReleaseTag
        BundleKey       = $bundleKey
        BundleSha256    = $BundleSha256
        BundleVersionId = $BundleVersionId
        NginxImageRef    = $nginxImageRef
        PostgresMaintenanceImageRef = $postgresMaintenanceImageRef
    } | ConvertTo-Json | Set-Content -LiteralPath $manifestPath -Encoding utf8NoBOM
    $ManifestSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $manifestPath).Hash.ToLowerInvariant()
    & aws s3 cp $manifestPath "s3://$bucket/$manifestKey" `
        --region $region `
        --sse AES256 `
        --no-progress
    Assert-LastExitCode "Upload deployment manifest"
    $ManifestVersionId = (& aws s3api head-object `
        --bucket $bucket `
        --key $manifestKey `
        --region $region `
        --query VersionId `
        --output text `
        --no-cli-pager).Trim()
    Assert-LastExitCode "Resolve deployment manifest version"
    if ([string]::IsNullOrWhiteSpace($ManifestVersionId) -or $ManifestVersionId -eq "None") {
        throw "Versioned deployment manifest is required."
    }

    $stageProjectName = "skn27-stage-$ReleaseTag"
    $stageComposeCommand = "docker compose --project-name '$stageProjectName' --env-file .compose.env --env-file .stage-compose.env -f docker-compose.pilot.yml"
    $productionComposeCommand = "docker compose --project-name skn27-pilot --env-file .compose.env --env-file .production-compose.env -f docker-compose.pilot.yml"
    $currentReleaseRequiredServices = if ($AllowCaddyOfflineForHostNetworkCutover) {
        "edge-rate-limit frontend backend agent-worker file-scan-worker ops-monitor redis clamav law-neo4j"
    }
    else {
        "caddy edge-rate-limit frontend backend agent-worker file-scan-worker ops-monitor redis clamav law-neo4j"
    }
    $GOOGLE_LIVE_SMOKE_ENABLED = if ($RequireGoogleLiveSmoke) { "1" } else { "0" }
    $commands = @(
        "set -eu",
        "exec 8>/var/lock/skn27-pilot-maintenance.lock",
        "flock -w 60 8 || { echo 'Another pilot maintenance workflow is running.' >&2; exit 75; }",
        "test ! -e '/opt/skn27-pilot/maintenance/database-maintenance.active' || { echo 'Database maintenance marker is active.' >&2; exit 75; }",
        "RELEASE_DIR='/opt/skn27-pilot/releases/$ReleaseTag'",
        "STAGE_PROJECT_NAME='$stageProjectName'"
    )

    $materializeCommands = @(
        "install -d -m 0750 `$RELEASE_DIR",
        "install -d -m 0750 /opt/skn27-pilot/operational-evidence",
        "aws s3api get-object --bucket '$bucket' --key '$manifestKey' --version-id '$ManifestVersionId' --region '$region' /tmp/deployment-manifest.json >/dev/null",
        "printf '%s  %s\n' '$ManifestSha256' /tmp/deployment-manifest.json | sha256sum -c -",
        "python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); assert m[`"ReleaseTag`"]==sys.argv[2] and m[`"BundleKey`"]==sys.argv[3] and m[`"BundleSha256`"]==sys.argv[4] and m[`"BundleVersionId`"]==sys.argv[5] and m[`"NginxImageRef`"]==sys.argv[6] and m[`"PostgresMaintenanceImageRef`"]==sys.argv[7]' /tmp/deployment-manifest.json '$ReleaseTag' '$bundleKey' '$BundleSha256' '$BundleVersionId' '$nginxImageRef' '$postgresMaintenanceImageRef'",
        "install -m 0444 /tmp/deployment-manifest.json `$RELEASE_DIR/deployment-manifest.json",
        "aws s3api get-object --bucket '$bucket' --key '$bundleKey' --version-id '$BundleVersionId' --region '$region' /tmp/skn27-pilot.zip >/dev/null",
        "printf '%s  %s\n' '$BundleSha256' /tmp/skn27-pilot.zip | sha256sum -c -",
        "unzip -o /tmp/skn27-pilot.zip -d `$RELEASE_DIR",
        "aws ssm get-parameter --region '$region' --name '$parameterName' --with-decryption --query Parameter.Value --output text > `$RELEASE_DIR/.runtime.env.tmp",
        "tr -d '\r' < `$RELEASE_DIR/.runtime.env.tmp > `$RELEASE_DIR/.runtime.env",
        "rm -f `$RELEASE_DIR/.runtime.env.tmp",
        "grep -E '^(AWS_REGION|BACKEND_REPOSITORY_URL|FRONTEND_REPOSITORY_URL|RELEASE_TAG|CADDY_IMAGE_REF|HAPROXY_IMAGE_REF|REDIS_IMAGE_REF|CLAMAV_IMAGE_REF|LAW_NEO4J_IMAGE_REF|LEGAL_DATASET_VERSION|LEGAL_DATASET_VERIFIED_AT|NEO4J_USER|NEO4J_PASSWORD|OPERATIONAL_LOG_GROUP)=' `$RELEASE_DIR/.runtime.env > `$RELEASE_DIR/.compose.env",
        "grep -E '^(APP_DOMAIN|ACME_EMAIL)=' `$RELEASE_DIR/.runtime.env > `$RELEASE_DIR/.edge.env",
        "grep -q '^AWS_REGION=' `$RELEASE_DIR/.compose.env && grep -q '^BACKEND_REPOSITORY_URL=' `$RELEASE_DIR/.compose.env && grep -q '^FRONTEND_REPOSITORY_URL=' `$RELEASE_DIR/.compose.env && grep -q '^RELEASE_TAG=' `$RELEASE_DIR/.compose.env && grep -q '^LAW_NEO4J_IMAGE_REF=' `$RELEASE_DIR/.compose.env && grep -q '^LEGAL_DATASET_VERSION=' `$RELEASE_DIR/.compose.env && grep -q '^LEGAL_DATASET_VERIFIED_AT=' `$RELEASE_DIR/.compose.env && grep -q '^NEO4J_USER=' `$RELEASE_DIR/.compose.env && grep -q '^NEO4J_PASSWORD=' `$RELEASE_DIR/.compose.env && grep -q '^OPERATIONAL_LOG_GROUP=' `$RELEASE_DIR/.compose.env",
        "test `$(wc -l < `$RELEASE_DIR/.edge.env) -eq 2",
        "printf '%s\n' 'PILOT_NETWORK_SUBNET=172.30.0.0/24' 'PILOT_EDGE_RATE_LIMIT_IP=172.30.0.3' 'PILOT_FRONTEND_IP=172.30.0.4' 'PILOT_BACKEND_IP=172.30.0.5' 'PILOT_AGENT_WORKER_IP=172.30.0.6' 'PILOT_FILE_SCAN_WORKER_IP=172.30.0.7' 'PILOT_REDIS_IP=172.30.0.8' 'PILOT_OPS_MONITOR_IP=172.30.0.9' 'PILOT_CLAMAV_IP=172.30.0.10' 'PILOT_LAW_NEO4J_IP=172.30.0.12' 'PILOT_REDIS_VOLUME_NAME=${stageProjectName}_redis_data' 'PILOT_CLAMAV_VOLUME_NAME=${stageProjectName}_clamav_data' 'PILOT_LAW_NEO4J_VOLUME_NAME=${stageProjectName}_law_neo4j_data' 'PILOT_LAW_NEO4J_LOG_VOLUME_NAME=${stageProjectName}_law_neo4j_logs' > `$RELEASE_DIR/.stage-compose.env",
        "printf '%s\n' 'PILOT_NETWORK_SUBNET=172.31.0.0/24' 'PILOT_EDGE_RATE_LIMIT_IP=172.31.0.3' 'PILOT_FRONTEND_IP=172.31.0.4' 'PILOT_BACKEND_IP=172.31.0.5' 'PILOT_AGENT_WORKER_IP=172.31.0.6' 'PILOT_FILE_SCAN_WORKER_IP=172.31.0.7' 'PILOT_REDIS_IP=172.31.0.8' 'PILOT_OPS_MONITOR_IP=172.31.0.9' 'PILOT_CLAMAV_IP=172.31.0.10' 'PILOT_LAW_NEO4J_IP=172.31.0.12' 'PILOT_REDIS_VOLUME_NAME=${stageProjectName}_redis_data' 'PILOT_CLAMAV_VOLUME_NAME=${stageProjectName}_clamav_data' 'PILOT_LAW_NEO4J_VOLUME_NAME=${stageProjectName}_law_neo4j_data' 'PILOT_LAW_NEO4J_LOG_VOLUME_NAME=${stageProjectName}_law_neo4j_logs' > `$RELEASE_DIR/.production-compose.env",
        "printf '%s\n' '$stageProjectName' > `$RELEASE_DIR/.stage-project-name.tmp",
        "chmod 0444 `$RELEASE_DIR/.stage-project-name.tmp && mv -f `$RELEASE_DIR/.stage-project-name.tmp `$RELEASE_DIR/.stage-project-name",
        "aws ecr get-login-password --region '$region' | docker login --username AWS --password-stdin '$registry'",
        "cd `$RELEASE_DIR",
        "tr -d '\r' < `$RELEASE_DIR/configure-imds-firewall.sh > /tmp/skn27-imds-firewall.sh",
        "install -m 0755 /tmp/skn27-imds-firewall.sh /usr/local/sbin/skn27-imds-firewall.sh",
        "rm -f /tmp/skn27-imds-firewall.sh",
        "/usr/local/sbin/skn27-imds-firewall.sh",
        "MEM_TOTAL_KB=`$(awk '/MemTotal/ {print `$2}' /proc/meminfo); test `$MEM_TOTAL_KB -ge 7600000",
        "MEM_AVAILABLE_KB=`$(awk '/MemAvailable/ {print `$2}' /proc/meminfo); test `$MEM_AVAILABLE_KB -ge 3000000",
        "docker system df"
    )

    if ($StageForInitialRagBootstrap) {
        $commands += @(
            "test ! -e /opt/skn27-pilot/current && test ! -L /opt/skn27-pilot/current",
            "test ! -e `$RELEASE_DIR && test ! -L `$RELEASE_DIR",
            "test -z `"`$(find /opt/skn27-pilot/releases -mindepth 2 -maxdepth 2 -type f \( -name '.initial-rag-bootstrap.staged' -o -name '.release-update.staged' \) -print -quit 2>/dev/null)`"",
            "stage_failed() { status=`$?; trap - ERR; cd `$RELEASE_DIR 2>/dev/null || true; echo '=== initial RAG stage service states ===' >&2; $stageComposeCommand ps -a >&2 || true; for stage_service in redis law-neo4j clamav backend; do echo `"=== `$stage_service logs ===`" >&2; $stageComposeCommand logs --tail 80 `$stage_service >&2 || true; done; $stageComposeCommand down --remove-orphans >/dev/null 2>&1 || true; docker volume rm '${stageProjectName}_redis_data' '${stageProjectName}_clamav_data' '${stageProjectName}_law_neo4j_data' '${stageProjectName}_law_neo4j_logs' >/dev/null 2>&1 || true; rm -rf -- `$RELEASE_DIR; exit `$status; }",
            "trap stage_failed ERR"
        )
        $commands += $materializeCommands
        $commands += @(
            "$stageComposeCommand pull redis clamav law-neo4j backend",
            "$stageComposeCommand run --rm --no-deps backend python backend/manage.py migrate --check",
            "$stageComposeCommand up -d --wait --wait-timeout 600 --remove-orphans redis clamav law-neo4j backend",
            "RUNNING_SERVICES=`$($stageComposeCommand ps --services --filter status=running)",
            "for forbidden_service in caddy edge-rate-limit frontend agent-worker file-scan-worker ops-monitor; do ! printf '%s\n' `"`$RUNNING_SERVICES`" | grep -qx `"`$forbidden_service`"; done",
            "printf '%s %s %s\n' '$ReleaseTag' '$ExpectedRagSeedManifestSha256' '$stageProjectName' > `$RELEASE_DIR/.initial-rag-bootstrap.staged.tmp",
            "chmod 0444 `$RELEASE_DIR/.initial-rag-bootstrap.staged.tmp && mv -f `$RELEASE_DIR/.initial-rag-bootstrap.staged.tmp `$RELEASE_DIR/.initial-rag-bootstrap.staged",
            "rm -f /tmp/skn27-pilot.zip /tmp/deployment-manifest.json",
            "trap - ERR"
        )
    }
    elseif ($StageForReleaseUpdate) {
        $commands += @(
            "test -L /opt/skn27-pilot/current",
            "CURRENT_RELEASE=`$(readlink -f /opt/skn27-pilot/current)",
            "test -n `"`$CURRENT_RELEASE`" && test -d `"`$CURRENT_RELEASE`"",
            "test `"`$CURRENT_RELEASE`" != `"`$RELEASE_DIR`"",
            "cd `$CURRENT_RELEASE",
            "CURRENT_CONTAINER_IDS=`$($productionComposeCommand ps -q | sort)",
            "test -n `"`$CURRENT_CONTAINER_IDS`"",
            "CURRENT_RUNNING_SERVICES=`$($productionComposeCommand ps --services --filter status=running)",
            "for required_service in $currentReleaseRequiredServices; do printf '%s\n' `"`$CURRENT_RUNNING_SERVICES`" | grep -qx `"`$required_service`"; done",
            "test ! -e `$RELEASE_DIR && test ! -L `$RELEASE_DIR",
            "test -z `"`$(find /opt/skn27-pilot/releases -mindepth 2 -maxdepth 2 -type f \( -name '.initial-rag-bootstrap.staged' -o -name '.release-update.staged' \) -print -quit 2>/dev/null)`"",
            "stage_failed() { status=`$?; trap - ERR; cd `$RELEASE_DIR 2>/dev/null || true; $stageComposeCommand down --remove-orphans >/dev/null 2>&1 || true; docker volume rm '${stageProjectName}_redis_data' '${stageProjectName}_clamav_data' >/dev/null 2>&1 || true; rm -rf -- `$RELEASE_DIR; exit `$status; }",
            "trap stage_failed ERR"
        )
        $commands += $materializeCommands
        $commands += @(
            "$stageComposeCommand pull redis law-neo4j backend",
            "$stageComposeCommand run --rm --no-deps backend python backend/manage.py migrate --check",
            "$stageComposeCommand up -d --wait --wait-timeout 600 --remove-orphans redis law-neo4j",
            "RUNNING_STAGE_SERVICES=`$($stageComposeCommand ps --services --filter status=running)",
            "for required_service in redis law-neo4j; do printf '%s\n' `"`$RUNNING_STAGE_SERVICES`" | grep -qx `"`$required_service`"; done",
            "for forbidden_service in caddy edge-rate-limit frontend backend agent-worker file-scan-worker ops-monitor clamav; do ! printf '%s\n' `"`$RUNNING_STAGE_SERVICES`" | grep -qx `"`$forbidden_service`"; done",
            "cd `$CURRENT_RELEASE",
            "test `"`$CURRENT_CONTAINER_IDS`" = `"`$($productionComposeCommand ps -q | sort)`"",
            "cd `$RELEASE_DIR",
            "printf '%s %s %s %s\n' '$ReleaseTag' '$ExpectedRagSeedManifestSha256' '$stageProjectName' `"`$CURRENT_RELEASE`" > `$RELEASE_DIR/.release-update.staged.tmp",
            "chmod 0444 `$RELEASE_DIR/.release-update.staged.tmp && mv -f `$RELEASE_DIR/.release-update.staged.tmp `$RELEASE_DIR/.release-update.staged",
            "rm -f /tmp/skn27-pilot.zip /tmp/deployment-manifest.json",
            "trap - ERR"
        )
    }
    else {
        $commands += @(
            "test -d `$RELEASE_DIR && test ! -L `$RELEASE_DIR",
            "test -f `$RELEASE_DIR/.stage-project-name",
            "test `"`$(cat `$RELEASE_DIR/.stage-project-name)`" = '$stageProjectName'",
            "test -f `$RELEASE_DIR/.stage-compose.env && test -f `$RELEASE_DIR/.production-compose.env",
            "test `"`$(sed -n 's/^RELEASE_TAG=//p' `$RELEASE_DIR/.compose.env)`" = '$ReleaseTag'",
            "test -f `$RELEASE_DIR/.production-rag-seed.complete",
            "test `"`$(cat `$RELEASE_DIR/.production-rag-seed.complete)`" = '$ExpectedRagSeedManifestSha256'",
            "PREVIOUS_RELEASE=`$(readlink -f /opt/skn27-pilot/current 2>/dev/null || true)",
            "test -z `"`$PREVIOUS_RELEASE`" || test `"`$PREVIOUS_RELEASE`" != `"`$RELEASE_DIR`"",
            "if [ -f `$RELEASE_DIR/.initial-rag-bootstrap.staged ]; then test -z `"`$PREVIOUS_RELEASE`" && test `"`$(cat `$RELEASE_DIR/.initial-rag-bootstrap.staged)`" = '$ReleaseTag $ExpectedRagSeedManifestSha256 $stageProjectName'; elif [ -f `$RELEASE_DIR/.release-update.staged ]; then test -n `"`$PREVIOUS_RELEASE`" && test `"`$(cat `$RELEASE_DIR/.release-update.staged)`" = `"`$(printf '%s %s %s %s' '$ReleaseTag' '$ExpectedRagSeedManifestSha256' '$stageProjectName' `"`$PREVIOUS_RELEASE`")`"; else echo 'Exact RAG stage marker is missing.' >&2; exit 78; fi",
            "GOOGLE_LIVE_SMOKE_ENABLED='$GOOGLE_LIVE_SMOKE_ENABLED'",
            "if [ -z `"`$PREVIOUS_RELEASE`" ] && [ `"`$GOOGLE_LIVE_SMOKE_ENABLED`" != '1' ]; then echo 'Initial promotion requires -RequireGoogleLiveSmoke.' >&2; exit 78; fi",
            "rollback_previous_release() { status=`$?; trap - ERR; cd `$RELEASE_DIR; $productionComposeCommand down >/dev/null 2>&1 || true; if [ -n `"`$PREVIOUS_RELEASE`" ] && [ -d `"`$PREVIOUS_RELEASE`" ]; then cd `$PREVIOUS_RELEASE; $productionComposeCommand up -d --wait --wait-timeout 600 --remove-orphans; ln -sfn `$PREVIOUS_RELEASE /opt/skn27-pilot/current; fi; exit `$status; }",
            "trap rollback_previous_release ERR",
            "cd `$RELEASE_DIR",
            "$stageComposeCommand down --remove-orphans",
            "if [ -n `"`$PREVIOUS_RELEASE`" ]; then cd `$PREVIOUS_RELEASE; $productionComposeCommand down; fi",
            "cd `$RELEASE_DIR",
            "$productionComposeCommand pull",
            "$productionComposeCommand run --rm --no-deps backend python backend/manage.py help smoke_non_dl_analysis_reporting_pipeline >/dev/null",
            "$productionComposeCommand run --rm --no-deps backend python backend/manage.py help smoke_supervisor_conversation_runtime >/dev/null",
            "$productionComposeCommand run --rm --no-deps backend python backend/manage.py migrate --check",
            "$productionComposeCommand up -d --wait --wait-timeout 600 --remove-orphans",
            "$productionComposeCommand exec -T backend python backend/manage.py check_production_readiness --format json --fail-on-error",
            "echo 'IMDS allow smoke'; $productionComposeCommand exec -T backend python -c `"import urllib.request; request=urllib.request.Request('http://169.254.169.254/latest/api/token', method='PUT', headers={'X-aws-ec2-metadata-token-ttl-seconds':'60'}); token=urllib.request.urlopen(request, timeout=3).read(); assert token`"",
            "echo 'IMDS deny smoke'; docker run --rm --network skn27-pilot_pilot --ip 172.31.0.11 '${backendRepository}:${ReleaseTag}' python -c `"import socket; sock=socket.socket(); sock.settimeout(3); assert sock.connect_ex(('169.254.169.254', 80)) != 0`"",
            "$productionComposeCommand exec -T backend python backend/manage.py smoke_object_storage --require-binary --format json"
        )
        if ($RequireGoogleLiveSmoke) {
            $commands += @(
                "$productionComposeCommand exec -T backend python backend/manage.py help smoke_google_oauth_code >/dev/null",
                "GOOGLE_OAUTH_SMOKE_CODE=`$(aws ssm get-parameter --region '$region' --name '$googleCodeParameterName' --with-decryption --query Parameter.Value --output text)",
                "export GOOGLE_OAUTH_SMOKE_CODE",
                "$productionComposeCommand exec -T -e GOOGLE_OAUTH_SMOKE_CODE backend python backend/manage.py smoke_google_oauth_code --require-exchange --verify-replay-rejection --format json",
                "unset GOOGLE_OAUTH_SMOKE_CODE"
            )
        }
        $commands += @(
            "$productionComposeCommand exec -T backend python backend/manage.py smoke_supervisor_conversation_runtime --allow-paid-provider-call --require-llm-used --require-real-agent-results --require-persisted-handoff --require-report --fine-notice-fixture-s3-uri '$FineNoticeSmokeS3Uri' --timeout-seconds 600 --format json",
            "curl --fail --silent --show-error --retry 10 --retry-delay 6 --resolve '${appDomain}:443:127.0.0.1' https://${appDomain}/api/health/live/ >/dev/null",
            "curl --fail --silent --show-error --retry 10 --retry-delay 6 --resolve '${appDomain}:443:127.0.0.1' https://${appDomain}/api/health/ready/ >/dev/null",
            "ln -sfn `$RELEASE_DIR /opt/skn27-pilot/current",
            "rm -f `$RELEASE_DIR/.initial-rag-bootstrap.staged `$RELEASE_DIR/.release-update.staged",
            "PROTECTED_RELEASE_TAGS=`$(find /opt/skn27-pilot/releases -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | head -n 3 | cut -d' ' -f2- | while read -r protected_dir; do sed -n 's/^RELEASE_TAG=//p' `"`$protected_dir/.compose.env`"; done | sort -u)",
            "test -n `"`$PROTECTED_RELEASE_TAGS`"",
            "for repo in '$backendRepository' '$frontendRepository'; do for image in `$(docker images `"`$repo`" --format '{{.Repository}}:{{.Tag}}'); do tag=`${image##*:}; keep=0; for protected_tag in `$PROTECTED_RELEASE_TAGS; do if [ `"`$tag`" = `"`$protected_tag`" ]; then keep=1; fi; done; if [ `$keep -eq 0 ]; then docker image rm `"`$image`" || true; fi; done; done",
            "STALE_RELEASE_DIRS=`$(find /opt/skn27-pilot/releases -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | tail -n +4 | cut -d' ' -f2-)",
            "for stale_dir in `$STALE_RELEASE_DIRS; do test `"`$stale_dir`" != `"`$(readlink -f /opt/skn27-pilot/current)`" || continue; test -f `"`$stale_dir/.stage-project-name`" && test -f `"`$stale_dir/.production-compose.env`" || continue; stale_project=`$(cat `"`$stale_dir/.stage-project-name`"); cleanup_ok=1; for volume_key in PILOT_REDIS_VOLUME_NAME PILOT_CLAMAV_VOLUME_NAME; do stale_volume=`$(sed -n `"s/^`$volume_key=//p`" `"`$stale_dir/.production-compose.env`"); case `"`$stale_volume`" in `"`$stale_project`"_redis_data|`"`$stale_project`"_clamav_data) ;; *) cleanup_ok=0; continue ;; esac; if docker volume inspect `"`$stale_volume`" >/dev/null 2>&1; then docker volume rm `"`$stale_volume`" || cleanup_ok=0; fi; done; if [ `$cleanup_ok -eq 1 ]; then rm -rf -- `"`$stale_dir`"; fi; done",
            "rm -f /tmp/skn27-pilot.zip /tmp/deployment-manifest.json",
            "trap - ERR"
        )
    }

    $requestPath = Join-Path $staging "ssm-request.json"
    @{
        DocumentName = "AWS-RunShellScript"
        InstanceIds  = @($instanceId)
        Comment      = "Deploy SKN27 pilot $ReleaseTag"
        Parameters   = @{ commands = $commands }
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $requestPath -Encoding utf8NoBOM

    $commandId = (& aws ssm send-command `
        --region $region `
        --cli-input-json "file://$requestPath" `
        --query "Command.CommandId" `
        --output text `
        --no-cli-pager).Trim()
    Assert-LastExitCode "aws ssm send-command"

    $commandResult = Get-SsmCommandResult `
        -Region $region `
        -CommandId $commandId `
        -InstanceId $instanceId `
        -TimeoutSeconds $SsmTimeoutSeconds
    if ($commandResult.Status -ne "Success") {
        throw "Remote deployment failed with status '$($commandResult.Status)'. Inspect SSM output using an approved redacted workflow."
    }
    if (-not $isStageMode) {
        Invoke-PublicHealthCheck "https://${appDomain}/api/health/live/"
        Invoke-PublicHealthCheck "https://${appDomain}/api/health/ready/"
    }
}
finally {
    Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $bundle -Force -ErrorAction SilentlyContinue
}
}
finally {
    if ($RequireGoogleLiveSmoke -and -not [string]::IsNullOrWhiteSpace($googleCodeParameterName)) {
        & aws ssm delete-parameter `
            --region $region `
            --name $googleCodeParameterName `
            --no-cli-pager 2>$null | Out-Null
    }
}

if ($StageForInitialRagBootstrap) {
    Write-Host "Pilot release $ReleaseTag staged private services for initial RAG bootstrap; no public current release was promoted."
}
elseif ($StageForReleaseUpdate) {
    Write-Host "Pilot release $ReleaseTag staged an isolated private update project; the current release was not changed."
}
else {
    Write-Host "Pilot release $ReleaseTag passed schema, readiness, provider, and HTTP smoke checks."
}
