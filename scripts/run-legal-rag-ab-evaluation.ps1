[CmdletBinding()]
param(
    [string]$EnvFile = (Join-Path $PSScriptRoot "..\.env.rag-eval"),
    [string]$RunId = (Get-Date -Format "yyyyMMddTHHmmssZ"),
    [switch]$StartPostgres,
    [switch]$RunRagas
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$EnvFile = (Resolve-Path $EnvFile -ErrorAction Stop).Path

if ($StartPostgres) {
    $existingPostgres = docker ps -aq --filter "name=^/skn27-postgres$"
    $runningPostgres = docker ps -q --filter "name=^/skn27-postgres$"
    if ($runningPostgres) {
        Write-Host "Local PostgreSQL container is already running; reusing it."
    }
    elseif ($existingPostgres) {
        docker start skn27-postgres
        if ($LASTEXITCODE -ne 0) {
            throw "Existing local PostgreSQL container could not be started."
        }
        Write-Host "Existing local PostgreSQL container was started."
    }
    else {
        Push-Location $repoRoot
        try {
            docker compose up -d postgres
            if ($LASTEXITCODE -ne 0) {
                throw "Local PostgreSQL startup failed."
            }
        }
        finally {
            Pop-Location
        }
    }
}

# Apply values only to this PowerShell process and never echo source lines or secrets.
foreach ($rawLine in Get-Content -LiteralPath $EnvFile -Encoding UTF8) {
    $line = $rawLine.Trim()
    if ([string]::IsNullOrWhiteSpace($line) -or $line.StartsWith("#")) {
        continue
    }
    $separator = $line.IndexOf("=")
    if ($separator -lt 1) {
        throw "Invalid evaluation environment line."
    }
    $key = $line.Substring(0, $separator).Trim()
    $value = $line.Substring($separator + 1).Trim()
    Set-Item -Path ("Env:" + $key) -Value $value
}

Push-Location $repoRoot
try {
    $arguments = @(
        "-m", "etl.legal.run_evaluation",
        "--env-file", $EnvFile,
        "--run-id", $RunId
    )
    if ($RunRagas) {
        $arguments += "--run-ragas"
    }
    & python @arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
