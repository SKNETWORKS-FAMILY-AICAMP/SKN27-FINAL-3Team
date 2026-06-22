param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Owner = "SKNETWORKS-FAMILY-AICAMP"
$Repo = "SKN27-FINAL-3Team"
$ApiBase = "https://api.github.com"
$Marker = "<!-- wbs-meeting-update-2026-06-18 -->"

function Get-GitHubToken {
    $token = [Environment]::GetEnvironmentVariable("GITHUB_TOKEN")
    if ([string]::IsNullOrWhiteSpace($token)) {
        $token = [Environment]::GetEnvironmentVariable("GH_TOKEN")
    }
    if (-not [string]::IsNullOrWhiteSpace($token)) {
        return $token
    }

    $credentialInput = "protocol=https`nhost=github.com`n`n"
    $credential = $credentialInput | git credential fill
    $passwordLine = ($credential -split "`n" | Where-Object { $_ -like "password=*" } | Select-Object -First 1)
    if (-not $passwordLine) {
        throw "GitHub token was not found in environment variables or Git Credential Manager."
    }
    return $passwordLine.Substring("password=".Length)
}

$Token = if ($DryRun) { "dry-run-token" } else { Get-GitHubToken }
$Headers = @{
    "Accept" = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
    "User-Agent" = "Codex"
    "Authorization" = "Bearer $Token"
}

function Invoke-GitHubApi {
    param(
        [Parameter(Mandatory = $true)][string]$Method,
        [Parameter(Mandatory = $true)][string]$Path,
        [object]$Body = $null
    )

    $uri = "$ApiBase$Path"
    if ($DryRun) {
        Write-Host "[DRY-RUN] $Method $uri"
        return $null
    }

    if ($null -eq $Body) {
        return Invoke-RestMethod -Method $Method -Uri $uri -Headers $Headers
    }

    $jsonBody = $Body | ConvertTo-Json -Depth 20
    return Invoke-RestMethod -Method $Method -Uri $uri -Headers $Headers -Body $jsonBody -ContentType "application/json; charset=utf-8"
}

function Get-Section {
    param(
        [string]$Body,
        [string]$Heading
    )

    if ([string]::IsNullOrWhiteSpace($Body)) {
        return ""
    }

    $pattern = "(?s)## $([regex]::Escape($Heading))\s*\r?\n(.*?)(\r?\n## |\z)"
    $match = [regex]::Match($Body, $pattern)
    if ($match.Success) {
        return $match.Groups[1].Value.Trim()
    }
    return ""
}

function Get-GoalLine {
    param([string]$Body)

    if ($Body -match "- 목표:\s*(.+)") {
        return $Matches[1].Trim()
    }
    return "최신 WBS 기준으로 담당 범위와 산출물을 수행한다."
}

function Get-DomainGuidance {
    param([object]$Issue)

    $labels = @($Issue.labels | ForEach-Object { $_.name })
    $guidance = New-Object System.Collections.Generic.List[string]

    if ($labels -contains "domain:fine") {
        $guidance.Add("필주 담당 범위다. 고지서 OCR, 과태료·범칙금·벌칙 분석용 룰/매핑, 처분 단계, 이의제기 가능성, 부족 서류/필요 증거를 명확히 구조화한다.")
    }
    if ($labels -contains "domain:legal") {
        $guidance.Add("동혁 담당 법률 데이터는 판례가 아니라 법령, 시행령, 시행규칙, 행정 기준, 고시 등 법률 원문/조문/근거 metadata에 한정한다.")
    }
    if ($labels -contains "domain:fault") {
        $guidance.Add("재강 담당 흐름은 경위서/OCR 결과, 텍스트 ML, 과실비율 판례, 유튜브 자막 사례, 과실비율심의사례 데이터를 ML/RAG 입력으로 만드는 것이다.")
        $guidance.Add("과실비율을 단일 확정 수치로 단정하거나 최종 법률 판단 모델로 정의하지 않는다.")
    }
    if ($labels -contains "domain:vision") {
        $guidance.Add("주희 담당 Vision/DL 흐름은 차량 사고 이미지·영상에서 장면 요약, key frame, 객체/상황 후보, confidence를 만들고 과실비율 흐름의 참고 근거로 반환한다.")
        $guidance.Add("영상 분석 결과가 재강 텍스트 ML의 필수 입력이 되도록 묶지 않는다.")
    }
    if ($labels -contains "domain:supervisor") {
        $guidance.Add("최종 자연어 답변은 개별 Agent가 아니라 Supervisor가 각 Agent의 결과 스키마를 통합해 생성한다.")
        $guidance.Add("개별 Agent는 summary, structured_result, evidence, next_actions, limitations를 반환하는 방향으로 맞춘다.")
    }
    if ($labels -contains "domain:docs") {
        $guidance.Add("문서는 구현 source of truth 역할을 하므로 역할, 범위, 제외 항목, 일정, 산출물, 검증 기준을 모호하지 않게 기록한다.")
    }
    if ($labels -contains "domain:qa") {
        $guidance.Add("QA에서는 법률 판단 확정, 성공 보장, 과실비율 단정, 근거 없는 답변을 막는 guardrail을 반드시 확인한다.")
    }
    if ($labels -contains "scope:out") {
        $guidance.Add("이 이슈는 최신 핵심 WBS에서 제외된 후순위 범위다. 삭제하지 않고 닫힌 상태로 남겨 추적성을 보존한다.")
    }

    if ($guidance.Count -eq 0) {
        $guidance.Add("담당자는 parent issue와 연결된 WBS 기준을 먼저 확인하고, 산출물과 완료 기준을 이슈 comment에 업데이트한다.")
    }

    return ($guidance | ForEach-Object { "- $_" }) -join "`n"
}

function Build-Comment {
    param(
        [object]$Issue,
        [string]$ParentText,
        [string]$ChildrenText
    )

    $goal = Get-GoalLine -Body $Issue.body
    $outputs = Get-Section -Body $Issue.body -Heading "산출물"
    $acceptance = Get-Section -Body $Issue.body -Heading "완료 기준"
    $notes = Get-Section -Body $Issue.body -Heading "메모"
    $assignees = ($Issue.assignees | ForEach-Object { $_.login }) -join ", "
    if ([string]::IsNullOrWhiteSpace($assignees)) { $assignees = "미배정 또는 scope-out" }
    $milestone = if ($Issue.milestone) { $Issue.milestone.title } else { "없음" }
    $stateNote = if ($Issue.state -eq "closed") { "현재 이슈는 닫힌 상태다. scope-out 또는 완료 사유를 먼저 확인한다." } else { "현재 이슈는 open 상태다." }
    $guidance = Get-DomainGuidance -Issue $Issue

    if ([string]::IsNullOrWhiteSpace($outputs)) { $outputs = "- 산출물은 담당자가 작업 시작 전 parent issue 기준으로 보완한다." }
    if ([string]::IsNullOrWhiteSpace($acceptance)) { $acceptance = "- 완료 기준은 중간/최종 일정에 맞춰 보완한다." }
    if ([string]::IsNullOrWhiteSpace($notes)) { $notes = "- 추가 메모 없음." }

    return @"
$Marker
## 2026-06-18 회의 반영 상세 코멘트

### 왜 이 이슈가 변경됐는가

오늘 회의에서 기존 보험/범칙금/RAG 중심 배정이 Supervisor 기반 멀티 Agent 구조로 재정렬됐다. 이에 따라 이 이슈도 최신 WBS, 담당자, parent/child 구조, 중간/최종 마일스톤을 기준으로 다시 해석해야 한다.

### 담당자와 일정

- 담당자: $assignees
- 마일스톤: $milestone
- 상태: $stateNote
- 목표: $goal

### 작업자가 바로 확인해야 할 책임 경계

$guidance

### 산출물

$outputs

### 완료 기준

$acceptance

### parent/child 연결

- Parent: $ParentText
- Child: $ChildrenText

### 회의 기준 공통 주의사항

- 2026-07-14는 중간 발표 MVP 기준일이다.
- 2026-08-04는 최종 마무리 기준일이다.
- 보험 약관과 합의금 기능은 후순위로 분리한다.
- 최종 답변은 Supervisor가 각 Agent의 결과 스키마를 보고 형성한다.
- 새로운 구현이나 범위 확장은 문서 또는 회의 결정 없이 임의로 추가하지 않는다.

### 기존 메모

$notes
"@
}

$ParentMap = @{
    1 = "#9 epic-legal-precedent-data-ingestion-and-rag"
    10 = "#2 epic-planning-wbs-scope"; 11 = "#2 epic-planning-wbs-scope"; 12 = "#2 epic-planning-wbs-scope"; 13 = "#2 epic-planning-wbs-scope"
    14 = "#3 epic-common-architecture-data-pipeline"; 15 = "#3 epic-common-architecture-data-pipeline"; 16 = "#3 epic-common-architecture-data-pipeline"; 17 = "#3 epic-common-architecture-data-pipeline"; 18 = "#3 epic-common-architecture-data-pipeline"; 19 = "#3 epic-common-architecture-data-pipeline"; 22 = "#3 epic-common-architecture-data-pipeline"; 29 = "#3 epic-common-architecture-data-pipeline"
    23 = "#4 epic-fine-ocr-penalty-analysis"; 24 = "#4 epic-fine-ocr-penalty-analysis"; 25 = "#4 epic-fine-ocr-penalty-analysis"; 26 = "#4 epic-fine-ocr-penalty-analysis"; 27 = "#4 epic-fine-ocr-penalty-analysis"; 28 = "#4 epic-fine-ocr-penalty-analysis"
    30 = "#5 epic-fault-ratio-precedent-vision-flow"; 31 = "#5 epic-fault-ratio-precedent-vision-flow"; 32 = "#5 epic-fault-ratio-precedent-vision-flow"; 33 = "#5 epic-fault-ratio-precedent-vision-flow"
    34 = "#6 epic-settlement-helper-mvp"; 35 = "#6 epic-settlement-helper-mvp"
    36 = "#7 epic-vision-accident-image-video-agent"; 37 = "#7 epic-vision-accident-image-video-agent"; 38 = "#7 epic-vision-accident-image-video-agent"; 39 = "#7 epic-vision-accident-image-video-agent"
    40 = "#8 epic-integration-qa-final-demo"; 41 = "#8 epic-integration-qa-final-demo"; 42 = "#8 epic-integration-qa-final-demo"; 43 = "#8 epic-integration-qa-final-demo"
    20 = "#9 epic-legal-precedent-data-ingestion-and-rag"; 21 = "#9 epic-legal-precedent-data-ingestion-and-rag"
}

$ChildrenMap = @{
    2 = "#10, #11, #12, #13"
    3 = "#14, #15, #16, #17, #18, #19, #22, #29"
    4 = "#23, #24, #25, #26, #27, #28"
    5 = "#30, #31, #32, #33"
    6 = "#34, #35"
    7 = "#36, #37, #38, #39"
    8 = "#40, #41, #42, #43"
    9 = "#1, #20, #21"
}

$issues = Invoke-GitHubApi -Method "GET" -Path "/repos/$Owner/$Repo/issues?state=all&per_page=100"
$targetIssues = $issues | Where-Object { $_.number -ge 1 -and $_.number -le 43 } | Sort-Object number

foreach ($issue in $targetIssues) {
    $parentText = if ($ParentMap.ContainsKey([int]$issue.number)) { $ParentMap[[int]$issue.number] } else { "없음. 이 이슈가 parent 또는 독립 관리 이슈다." }
    $childrenText = if ($ChildrenMap.ContainsKey([int]$issue.number)) { $ChildrenMap[[int]$issue.number] } else { "없음. 이 이슈는 leaf child issue다." }
    $commentBody = Build-Comment -Issue $issue -ParentText $parentText -ChildrenText $childrenText

    $comments = Invoke-GitHubApi -Method "GET" -Path "/repos/$Owner/$Repo/issues/$($issue.number)/comments?per_page=100"
    $existing = $comments | Where-Object { $_.body -like "$Marker*" } | Select-Object -First 1

    if ($existing) {
        Invoke-GitHubApi -Method "PATCH" -Path "/repos/$Owner/$Repo/issues/comments/$($existing.id)" -Body @{ body = $commentBody } | Out-Null
        Write-Host "Updated comment on issue #$($issue.number)"
    }
    else {
        Invoke-GitHubApi -Method "POST" -Path "/repos/$Owner/$Repo/issues/$($issue.number)/comments" -Body @{ body = $commentBody } | Out-Null
        Write-Host "Created comment on issue #$($issue.number)"
    }
}

Write-Host "Detailed WBS meeting comments synced."

