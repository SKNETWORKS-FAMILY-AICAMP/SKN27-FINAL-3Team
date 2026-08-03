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

    $requiredOutputs = [ordered]@{
        "result bucket" = $ResultBucket
        "worker instance ID" = $WorkerInstanceId
        "worker ECR repository URL" = $WorkerRepositoryUrl
    }
    foreach ($entry in $requiredOutputs.GetEnumerator()) {
        if ([string]::IsNullOrWhiteSpace([string]$entry.Value)) {
            throw "AWS Vision $($entry.Key) output must not be empty."
        }
    }

    $queueUri = $null
    if (
        -not [Uri]::TryCreate($QueueUrl, [UriKind]::Absolute, [ref]$queueUri) -or
        $queueUri.Scheme -cne "https" -or
        -not $queueUri.AbsolutePath.EndsWith(".fifo", [StringComparison]::Ordinal)
    ) {
        throw "AWS Vision queue output must be an HTTPS FIFO queue URL."
    }

    foreach ($name in @("AWS_VISION_TIMEOUT_SECONDS", "AWS_VISION_POLL_INTERVAL_SECONDS")) {
        $rawValue = Get-EnvValue $Content $name
        $number = 0.0
        if (
            -not [double]::TryParse(
                $rawValue,
                [Globalization.NumberStyles]::Float,
                [Globalization.CultureInfo]::InvariantCulture,
                [ref]$number
            ) -or
            $number -le 0
        ) {
            throw "AWS Vision runtime value '$name' must be a positive number."
        }
    }

    $Content = Set-EnvValue $Content "AWS_VISION_QUEUE_URL" $QueueUrl
    $Content = Set-EnvValue $Content "AWS_VISION_RESULT_BUCKET" $ResultBucket
    $Content = Set-EnvValue $Content "AWS_VISION_RESULT_PREFIX" "vision/aws-queue/v1"
    return $Content
}
