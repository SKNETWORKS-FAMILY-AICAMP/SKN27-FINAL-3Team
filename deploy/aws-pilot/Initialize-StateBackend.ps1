#requires -Version 7.2
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")]
    [string]$StateBucket,

    [string]$Region = "ap-northeast-2"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    throw "Required command 'aws' was not found."
}

& aws s3api head-bucket --bucket $StateBucket --region $Region --no-cli-pager 2>$null
if ($LASTEXITCODE -ne 0) {
    if ($Region -eq "us-east-1") {
        & aws s3api create-bucket --bucket $StateBucket --region $Region --no-cli-pager | Out-Null
    }
    else {
        & aws s3api create-bucket `
            --bucket $StateBucket `
            --region $Region `
            --create-bucket-configuration "LocationConstraint=$Region" `
            --no-cli-pager | Out-Null
    }
    if ($LASTEXITCODE -ne 0) { throw "State bucket creation failed." }
}

& aws s3api put-public-access-block `
    --bucket $StateBucket `
    --region $Region `
    --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" `
    --no-cli-pager
if ($LASTEXITCODE -ne 0) { throw "State bucket public access block failed." }

& aws s3api put-bucket-versioning `
    --bucket $StateBucket `
    --region $Region `
    --versioning-configuration "Status=Enabled" `
    --no-cli-pager
if ($LASTEXITCODE -ne 0) { throw "State bucket versioning failed." }

& aws s3api put-bucket-encryption `
    --bucket $StateBucket `
    --region $Region `
    --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"},"BucketKeyEnabled":true}]}' `
    --no-cli-pager
if ($LASTEXITCODE -ne 0) { throw "State bucket encryption failed." }

Write-Host "State backend bucket is ready. Copy backend.hcl.example, set this bucket, then run terraform init -backend-config=<file>."
