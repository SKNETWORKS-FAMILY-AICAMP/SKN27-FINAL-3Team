#requires -Version 7.2
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Confirmation,

    [string]$TerraformDirectory = (Join-Path $PSScriptRoot "..\..\infra\terraform-pilot"),
    [switch]$SkipFinalSnapshot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($Confirmation -ne "DESTROY skn27-pilot") {
    throw "Refusing teardown. Pass -Confirmation 'DESTROY skn27-pilot'."
}

function Assert-LastExitCode([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step failed with exit code $LASTEXITCODE." }
}

function Invoke-BestEffort([string]$Step, [scriptblock]$Action) {
    try {
        & $Action
    }
    catch {
        Write-Warning "$Step did not complete; teardown will continue: $($_.Exception.Message)"
    }
}

function Get-SsmCommandResult([string]$Region, [string]$CommandId, [string]$InstanceId) {
    $terminalStatuses = @("Success", "Cancelled", "TimedOut", "Failed")
    # Cancelling is non-terminal and must continue polling before teardown proceeds.
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        $json = & aws ssm get-command-invocation --region $Region --command-id $CommandId --instance-id $InstanceId --output json --no-cli-pager 2>$null
        if ($LASTEXITCODE -eq 0) {
            $result = $json | ConvertFrom-Json
            if ($result.Status -in $terminalStatuses) { return $result }
        }
        Start-Sleep -Seconds 5
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
    throw "Container stop cancellation did not reach a terminal status."
}

function Remove-VersionedBucket([string]$Bucket, [string]$Region) {
    while ($true) {
        $listing = (& aws s3api list-object-versions --bucket $Bucket --region $Region --max-items 1000 --output json --no-cli-pager) | ConvertFrom-Json
        Assert-LastExitCode "List versions in $Bucket"
        $objects = @()
        foreach ($item in @($listing.Versions) + @($listing.DeleteMarkers)) {
            if ($null -ne $item -and $item.Key -and $item.VersionId) {
                $objects += @{ Key = [string]$item.Key; VersionId = [string]$item.VersionId }
            }
        }
        if ($objects.Count -eq 0) { break }

        $request = Join-Path ([IO.Path]::GetTempPath()) "skn27-delete-$([guid]::NewGuid().ToString('N')).json"
        try {
            @{ Objects = $objects; Quiet = $true } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $request -Encoding utf8NoBOM
            & aws s3api delete-objects --bucket $Bucket --region $Region --delete "file://$request" --no-cli-pager | Out-Null
            Assert-LastExitCode "Delete versions from $Bucket"
        }
        finally {
            Remove-Item -LiteralPath $request -Force -ErrorAction SilentlyContinue
        }
    }
}

function Remove-EcrImages([string]$RepositoryUrl, [string]$Region) {
    $repositoryName = ($RepositoryUrl -split "/", 2)[1]
    $imageIds = (& aws ecr list-images --repository-name $repositoryName --region $Region --query imageIds --output json --no-cli-pager) | ConvertFrom-Json
    Assert-LastExitCode "List ECR images in $repositoryName"
    if (@($imageIds).Count -eq 0) { return }

    $request = Join-Path ([IO.Path]::GetTempPath()) "skn27-ecr-$([guid]::NewGuid().ToString('N')).json"
    try {
        @{ imageIds = @($imageIds) } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $request -Encoding utf8NoBOM
        & aws ecr batch-delete-image --repository-name $repositoryName --region $Region --cli-input-json "file://$request" --no-cli-pager | Out-Null
        Assert-LastExitCode "Delete ECR images in $repositoryName"
    }
    finally {
        Remove-Item -LiteralPath $request -Force -ErrorAction SilentlyContinue
    }
}

$terraformPath = (Resolve-Path -LiteralPath $TerraformDirectory).Path
Push-Location $terraformPath
try {
    $outputs = $null
    Invoke-BestEffort "Read Terraform outputs" {
        $script:outputs = (& terraform output -json) | ConvertFrom-Json
        Assert-LastExitCode "terraform output"
    }

    if ($null -ne $outputs) {
        $region = [string]$outputs.aws_region.value
        $instanceId = [string]$outputs.instance_id.value

        Invoke-BestEffort "Stop pilot containers" {
            $stopRequest = Join-Path ([IO.Path]::GetTempPath()) "skn27-stop-$([guid]::NewGuid().ToString('N')).json"
            try {
                @{
                    DocumentName = "AWS-RunShellScript"
                    InstanceIds  = @($instanceId)
                    Parameters = @{ commands = @(
                            "set -eu",
                            "exec 8>/var/lock/skn27-pilot-maintenance.lock",
                            "flock -w 30 8",
                            "test ! -e '/opt/skn27-pilot/maintenance/database-maintenance.active' || { echo 'Database maintenance marker is active; skipping the remote container stop so Terraform destroy can continue.' >&2; exit 75; }",
                            "test ! -L /opt/skn27-pilot/current || (cd /opt/skn27-pilot/current && docker compose --project-name skn27-pilot --env-file .compose.env --env-file .production-compose.env -f docker-compose.pilot.yml down)",
                            "for staged_dir in /opt/skn27-pilot/releases/*; do test -f `"`$staged_dir/.stage-project-name`" || continue; stage_project=`$(cat `"`$staged_dir/.stage-project-name`"); case `"`$stage_project`" in skn27-stage-*) (cd `"`$staged_dir`" && docker compose --project-name `"`$stage_project`" --env-file .compose.env --env-file .stage-compose.env -f docker-compose.pilot.yml down --remove-orphans) || true ;; esac; done"
                        ) }
                } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $stopRequest -Encoding utf8NoBOM
                $stopCommandId = (& aws ssm send-command --region $region --cli-input-json "file://$stopRequest" --query "Command.CommandId" --output text --no-cli-pager).Trim()
                Assert-LastExitCode "Submit container stop"
                $stopResult = Get-SsmCommandResult $region $stopCommandId $instanceId
                if ($stopResult.Status -ne "Success") { throw "Container stop status was $($stopResult.Status)." }
            }
            finally {
                Remove-Item -LiteralPath $stopRequest -Force -ErrorAction SilentlyContinue
            }
        }

        Invoke-BestEffort "Empty clean bucket" { Remove-VersionedBucket ([string]$outputs.clean_bucket_name.value) $region }
        Invoke-BestEffort "Empty quarantine bucket" { Remove-VersionedBucket ([string]$outputs.quarantine_bucket_name.value) $region }
        Invoke-BestEffort "Empty backend ECR" { Remove-EcrImages ([string]$outputs.backend_repository_url.value) $region }
        Invoke-BestEffort "Empty frontend ECR" { Remove-EcrImages ([string]$outputs.frontend_repository_url.value) $region }
        Invoke-BestEffort "Delete runtime parameter" {
            & aws ssm delete-parameter --region $region --name ([string]$outputs.runtime_env_parameter_name.value) --no-cli-pager | Out-Null
            Assert-LastExitCode "Delete runtime parameter"
        }
    }

    $snapshotFlag = if ($SkipFinalSnapshot) { "true" } else { "false" }
    Invoke-BestEffort "Disable RDS deletion protection" {
        & terraform apply -auto-approve `
            -target=aws_db_instance.postgres `
            -var="database_deletion_protection=false" `
            -var="database_skip_final_snapshot=$snapshotFlag"
        Assert-LastExitCode "Disable RDS deletion protection"
    }

    & terraform destroy -auto-approve `
        -var="database_deletion_protection=false" `
        -var="database_skip_final_snapshot=$snapshotFlag"
    Assert-LastExitCode "Destroy pilot infrastructure"
}
finally {
    Pop-Location
}

Write-Host "Pilot infrastructure teardown completed. Verify final snapshots and the next AWS bill manually."
