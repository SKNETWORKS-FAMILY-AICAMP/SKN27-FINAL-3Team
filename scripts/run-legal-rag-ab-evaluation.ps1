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
