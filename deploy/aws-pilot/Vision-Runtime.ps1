#requires -Version 7.2

Set-StrictMode -Version Latest

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

function Set-AwsVisionRuntimeValues {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Content,
        [Parameter(Mandatory = $true)]
        [string]$Provider,
        [string]$QueueUrl = "",
        [string]$ResultBucket = "",
        [string]$WorkerInstanceId = "",
        [string]$WorkerRepositoryUrl = ""
    )

    if ($Provider -cne "aws_queue") {
        return $Content
    }

    $Content = Set-EnvValue $Content "AWS_VISION_QUEUE_URL" $QueueUrl
    $Content = Set-EnvValue $Content "AWS_VISION_RESULT_BUCKET" $ResultBucket
    $Content = Set-EnvValue $Content "AWS_VISION_RESULT_PREFIX" "vision/aws-queue/v1"
    return $Content
}
