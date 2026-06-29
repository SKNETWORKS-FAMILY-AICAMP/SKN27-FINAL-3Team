param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Owner = "SKNETWORKS-FAMILY-AICAMP"
$Repo = "SKN27-FINAL-3Team"
$ApiBase = "https://api.github.com"

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

function Ensure-Label {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Color,
        [Parameter(Mandatory = $true)][string]$Description
    )

    try {
        Invoke-GitHubApi -Method "GET" -Path "/repos/$Owner/$Repo/labels/$([uri]::EscapeDataString($Name))" | Out-Null
    }
    catch {
        Invoke-GitHubApi -Method "POST" -Path "/repos/$Owner/$Repo/labels" -Body @{
            name = $Name
            color = $Color
            description = $Description
        } | Out-Null
    }
}

function Ensure-Milestone {
    param(
        [Parameter(Mandatory = $true)][string]$Title,
        [Parameter(Mandatory = $true)][string]$DueOn,
        [Parameter(Mandatory = $true)][string]$Description
    )

    $milestones = Invoke-GitHubApi -Method "GET" -Path "/repos/$Owner/$Repo/milestones?state=all&per_page=100"
    $matched = $milestones | Where-Object { $_.title -eq $Title } | Select-Object -First 1
    if ($matched) {
        Invoke-GitHubApi -Method "PATCH" -Path "/repos/$Owner/$Repo/milestones/$($matched.number)" -Body @{
            title = $Title
            due_on = $DueOn
            description = $Description
            state = "open"
        } | Out-Null
        return $matched.number
    }

    $created = Invoke-GitHubApi -Method "POST" -Path "/repos/$Owner/$Repo/milestones" -Body @{
        title = $Title
        due_on = $DueOn
        description = $Description
        state = "open"
    }
    return $created.number
}

function Format-IssueBody {
    param([object]$Issue)

    $outputs = ($Issue.outputs | ForEach-Object { "- $_" }) -join "`n"
    $acceptance = ($Issue.acceptance | ForEach-Object { "- $_" }) -join "`n"
    $notes = ($Issue.notes | ForEach-Object { "- $_" }) -join "`n"

    return @"
## 최신 WBS 기준

- 기준일: 2026-06-18
- 중간 기준일: 2026-07-14
- 최종 기준일: 2026-08-04
- 담당자: $($Issue.assignees -join ", ")
- 목표: $($Issue.summary)

## 산출물

$outputs

## 완료 기준

$acceptance

## 메모

$notes
"@
}

$All = @("hi20260204-maker", "leejaegang27", "ohjuheecode", "techshin31", "workzion2")
$Middle = "2026-07-14 중간 발표 MVP"
$Final = "2026-08-04 최종 마무리"

$Labels = @(
    @{ name = "wbs"; color = "5319E7"; description = "WBS and owner tracking" },
    @{ name = "phase:middle"; color = "1D76DB"; description = "Targeted for 2026-07-14 midpoint" },
    @{ name = "phase:final"; color = "0052CC"; description = "Targeted for 2026-08-04 final" },
    @{ name = "scope:out"; color = "BFD4F2"; description = "Out of current MVP scope" },
    @{ name = "domain:docs"; color = "0075CA"; description = "Documentation and planning" },
    @{ name = "domain:supervisor"; color = "5319E7"; description = "Supervisor graph and final response" },
    @{ name = "domain:fine"; color = "FBCA04"; description = "Penalty, fine, notice OCR flow" },
    @{ name = "domain:legal"; color = "0E8A16"; description = "Law source data and legal basis DB" },
    @{ name = "domain:fault"; color = "D93F0B"; description = "Fault ratio text, precedent, review cases" },
    @{ name = "domain:vision"; color = "B60205"; description = "Accident image and video vision flow" },
    @{ name = "domain:qa"; color = "C5DEF5"; description = "Integration QA and guardrails" }
)

$IssueUpdates = @(
    @{
        number = 1; title = "feat-fault-youtube-caption-case-collector"; assignees = @("leejaegang27"); milestone = $Middle; labels = @("enhancement", "wbs", "phase:middle", "domain:fault")
        summary = "과실비율 분석에 사용할 유튜브 자막 기반 사고 사례 데이터를 수집하고 원천 metadata를 정리한다."
        outputs = @("유튜브 자막 원천 데이터", "영상/자막 출처 metadata", "사고 유형 후보 태그")
        acceptance = @("공개 자막 수집 가능 범위가 문서화됨", "전처리 전 원문과 metadata가 분리 저장됨", "재강 ML/RAG 파이프라인 입력으로 넘길 수 있음")
        notes = @("기존 한문철TV 자막 ETL 이슈를 재강 담당 과실비율 사례 데이터 수집으로 재정렬한다.", "우회 수집, 로그인 필요 데이터, 접근 제한 회피는 제외한다.")
    },
    @{
        number = 2; title = "epic-planning-wbs-scope"; assignees = @("hi20260204-maker"); milestone = $Middle; labels = @("documentation", "wbs", "phase:middle", "domain:docs")
        summary = "최신 회의 기준으로 WBS, 범위, 담당자, 산출물, 일정 기준을 확정한다."
        outputs = @("WBS 문서", "역할 매트릭스", "이슈 재배정 기준")
        acceptance = @("중간 2026-07-14, 최종 2026-08-04 기준이 반영됨", "담당자별 책임 경계가 문서화됨")
        notes = @("요청자 담당 이의신청서 생성 노드를 명시한다.")
    },
    @{
        number = 3; title = "epic-common-architecture-data-pipeline"; assignees = $All; milestone = $Middle; labels = @("enhancement", "wbs", "phase:middle", "domain:supervisor")
        summary = "데이터 타입별 Agent 흐름, RAG metadata, DB 적재, Supervisor 통합 구조를 맞춘다."
        outputs = @("공통 schema", "Agent 결과 스키마", "RAG metadata 계약", "파이프라인 상태 계약")
        acceptance = @("법률, 과태료, 판례/텍스트, 영상 결과가 같은 통합 계약으로 연결됨", "Supervisor가 각 Agent 결과를 받아 최종 답변을 만들 수 있음")
        notes = @("개별 Agent는 최종 답변을 확정하지 않고 근거/분석 결과 스키마를 반환한다.")
    },
    @{
        number = 4; title = "epic-fine-ocr-penalty-analysis"; assignees = @("workzion2", "hi20260204-maker"); milestone = $Middle; labels = @("enhancement", "wbs", "phase:middle", "domain:fine")
        summary = "고지서 OCR, 과태료·범칙금·벌칙 분석, 이의신청서 생성 입력까지 연결한다."
        outputs = @("고지서 OCR 구조화", "과태료·범칙금 분석 결과", "이의신청서 생성 입력 schema")
        acceptance = @("필주 분석 결과가 요청자 이의신청서 생성 노드로 전달됨", "동혁 법률 근거 데이터와 연결됨")
        notes = @("필주는 분석용 룰/매핑 데이터를 담당하고, 동혁은 법률 원문/근거 DB를 담당한다.")
    },
    @{
        number = 5; title = "epic-fault-ratio-precedent-vision-flow"; assignees = @("leejaegang27", "ohjuheecode", "techshin31", "hi20260204-maker"); milestone = $Middle; labels = @("enhancement", "wbs", "phase:middle", "domain:fault", "domain:vision")
        summary = "경위서/OCR/텍스트 ML, 판례·자막·심의사례, 영상/이미지 분석, 법률 근거를 과실비율 흐름에서 통합한다."
        outputs = @("과실비율 텍스트 RAG", "Vision/DL 결과", "법률 근거 metadata", "Supervisor 통합 응답")
        acceptance = @("과실비율을 확정 수치로 단정하지 않음", "근거와 한계를 포함한 결과를 Supervisor가 생성함")
        notes = @("재강과 주희 결과는 병렬로 실행 가능해야 하며 한쪽 결과를 다른 쪽 필수 입력으로 묶지 않는다.")
    },
    @{
        number = 6; title = "epic-settlement-helper-mvp"; assignees = @(); milestone = $null; labels = @("wbs", "scope:out")
        summary = "합의금 기능은 최신 WBS 핵심 경로에서 제외한다."
        outputs = @("후순위 기록")
        acceptance = @("현재 MVP 범위에서 닫힘 처리")
        notes = @("필요 시 최종 이후 별도 스프린트로 재개한다.")
        state = "closed"; state_reason = "not_planned"
    },
    @{
        number = 7; title = "epic-vision-accident-image-video-agent"; assignees = @("ohjuheecode"); milestone = $Middle; labels = @("enhancement", "wbs", "phase:middle", "domain:vision")
        summary = "차량 사고 이미지·영상 데이터셋과 Vision/DL Agent 흐름을 구축한다."
        outputs = @("비전 데이터셋", "영상 frame/key frame", "장면 요약", "confidence metadata")
        acceptance = @("Vision 결과가 과실비율 흐름의 참고 근거로 반환됨", "과실비율 자동 확정 판단은 제외됨")
        notes = @("주희 담당으로 재정렬한다.")
    },
    @{
        number = 8; title = "epic-integration-qa-final-demo"; assignees = $All; milestone = $Final; labels = @("enhancement", "wbs", "phase:final", "domain:qa")
        summary = "중간 MVP 이후 최종 QA, guardrail, 배포, 발표 산출물을 마무리한다."
        outputs = @("통합 QA", "최종 데모 시나리오", "운영/배포 문서")
        acceptance = @("2026-08-04 최종 제출 기준을 만족함")
        notes = @("중간 발표 이후 피드백을 반영한다.")
    },
    @{
        number = 9; title = "epic-legal-precedent-data-ingestion-and-rag"; assignees = @("techshin31", "leejaegang27"); milestone = $Middle; labels = @("enhancement", "wbs", "phase:middle", "domain:legal", "domain:fault")
        summary = "동혁 법률 데이터와 재강 판례/과실비율 사례 데이터를 분리해 수집·전처리·RAG 등록한다."
        outputs = @("법률 원문 DB", "판례/사례 RAG", "근거 metadata")
        acceptance = @("동혁은 판례를 담당하지 않음", "재강은 법률 원문 DB를 담당하지 않음")
        notes = @("최종 답변은 Supervisor가 생성한다.")
    },
    @{
        number = 10; title = "docs-project-scope-and-role-matrix"; assignees = @("hi20260204-maker"); milestone = $Middle; labels = @("documentation", "wbs", "phase:middle", "domain:docs")
        summary = "최신 역할 매트릭스와 MVP 범위를 문서화한다."
        outputs = @("역할 매트릭스", "도메인 경계", "담당자 기준")
        acceptance = @("workzion2 보험 텍스트 파이프라인 오배정이 제거됨", "재강/필주/동혁/주희/요청자 역할이 반영됨")
        notes = @("한국어 이름과 GitHub 계정 매핑을 명시한다.")
    },
    @{
        number = 11; title = "docs-wbs-owner-deliverable-plan"; assignees = @("hi20260204-maker"); milestone = $Middle; labels = @("documentation", "wbs", "phase:middle", "domain:docs")
        summary = "중간/최종 일정 기준 WBS와 산출물을 작성한다."
        outputs = @("WBS 문서", "Issue 매핑", "산출물 계획")
        acceptance = @("2026-07-14와 2026-08-04 기준 일정이 반영됨")
        notes = @("본 스크립트 기준 문서는 docs/wbs-owner-deliverable-plan.md이다.")
    },
    @{
        number = 12; title = "docs-mvp-screen-and-process-flows"; assignees = @("hi20260204-maker"); milestone = $Middle; labels = @("documentation", "wbs", "phase:middle", "domain:docs", "domain:supervisor")
        summary = "홈, 로그인 모달, 챗봇 진입, Supervisor 분기, 리포트 흐름을 문서화한다."
        outputs = @("화면 흐름", "시퀀스 다이어그램", "LangGraph 흐름도")
        acceptance = @("로그인 후 챗봇 페이지로 진입하는 흐름이 반영됨")
        notes = @("상세 설명보다 사용자가 이해하기 쉬운 간단한 설명 중심으로 둔다.")
    },
    @{
        number = 13; title = "docs-requirement-gap-and-risk-log"; assignees = $All; milestone = $Middle; labels = @("documentation", "wbs", "phase:middle", "domain:qa")
        summary = "기존 요구사항과 최신 회의 기준의 충돌, 리스크, 남은 결정을 추적한다."
        outputs = @("Gap/Risk 로그", "결정 필요 사항", "범위 변경 기록")
        acceptance = @("보험 약관 후순위, 합의금 scope-out, Supervisor 최종 답변 구조가 기록됨")
        notes = @("구현 전 불명확한 요구사항은 확인 대상으로 남긴다.")
    },
    @{
        number = 14; title = "feat-home-login-chatbot-entry"; assignees = @("hi20260204-maker"); milestone = $Middle; labels = @("enhancement", "wbs", "phase:middle", "domain:supervisor")
        summary = "홈 화면, 로그인 모달, 로그인 후 챗봇 진입 흐름을 구성한다."
        outputs = @("홈 화면", "로그인 모달", "챗봇 진입 라우팅")
        acceptance = @("사용자는 로그인 후 바로 챗봇 페이지로 이동함", "질문/자료 유형에 따라 Supervisor가 분기함")
        notes = @("동혁은 이 UI를 담당하지 않고 법률 데이터만 담당한다.")
    },
    @{
        number = 15; title = "feat-common-analysis-job-model"; assignees = @("ohjuheecode"); milestone = $Middle; labels = @("enhancement", "wbs", "phase:middle", "domain:vision")
        summary = "RAG, OCR, ML, DL, 문서 생성 작업 상태를 공통 모델로 관리한다."
        outputs = @("Job 상태 모델", "실패 사유", "재시도/검증 상태")
        acceptance = @("영상/DL 흐름과 다른 Agent 작업 상태를 추적할 수 있음")
        notes = @("기존 주희 담당 Job 모델 흐름을 유지한다.")
    },
    @{
        number = 16; title = "feat-data-source-registry-schema"; assignees = $All; milestone = $Middle; labels = @("enhancement", "wbs", "phase:middle", "domain:legal", "domain:fault", "domain:fine", "domain:vision")
        summary = "법률, 과태료 룰, 판례/사례, 영상 데이터 출처를 추적하는 registry schema를 정리한다."
        outputs = @("source registry schema", "source_type/domain 규칙", "원문 위치 metadata")
        acceptance = @("각 데이터가 출처, 수집일, 이용조건, 원문 위치를 가진다")
        notes = @("동혁/재강/필주/주희 데이터가 같은 출처 계약을 사용한다.")
    },
    @{
        number = 17; title = "feat-incremental-ingestion-run-tracking"; assignees = $All; milestone = $Middle; labels = @("enhancement", "wbs", "phase:middle", "domain:legal", "domain:fault", "domain:fine", "domain:vision")
        summary = "각 데이터 파이프라인 실행 이력과 증분 수집 상태를 추적한다."
        outputs = @("pipeline run log", "증분 수집 기준", "실패/성공 건수")
        acceptance = @("중복 수집과 누락 필드를 검증할 수 있음")
        notes = @("최소 중간 발표에서는 실행 로그 형태를 먼저 고정한다.")
    },
    @{
        number = 18; title = "feat-separate-domain-case-schemas"; assignees = $All; milestone = $Middle; labels = @("enhancement", "wbs", "phase:middle", "domain:supervisor")
        summary = "과태료·범칙금, 과실비율, 법률, Vision 결과 schema를 분리하고 Supervisor에서 병합한다."
        outputs = @("domain schema", "Agent result schema", "Supervisor merge contract")
        acceptance = @("도메인별 판단 책임이 섞이지 않음")
        notes = @("동혁 법률 원문 DB와 필주 분석용 룰/매핑을 분리한다.")
    },
    @{
        number = 19; title = "docs-data-governance-retention-policy"; assignees = @("hi20260204-maker"); milestone = $Final; labels = @("documentation", "wbs", "phase:final", "domain:docs")
        summary = "고지서, 영상, OCR, 리포트 데이터의 보관/삭제/마스킹 정책을 정리한다."
        outputs = @("데이터 보관 정책", "개인정보 마스킹 기준", "삭제 기준")
        acceptance = @("최종 제출 전 운영 리스크가 문서화됨")
        notes = @("중간 발표 이후 최종 마무리 단계에서 보강한다.")
    },
    @{
        number = 20; title = "feat-traffic-law-data-pipeline"; assignees = @("techshin31"); milestone = $Middle; labels = @("enhancement", "wbs", "phase:middle", "domain:legal")
        summary = "도로교통법, 시행령, 시행규칙, 행정 기준 등 법률 데이터를 수집·전처리·DB 적재한다."
        outputs = @("법률 원천 데이터 목록", "전처리된 법률 데이터", "DB 적재 결과", "적재 검증 로그")
        acceptance = @("판례 데이터는 포함하지 않음", "과태료·범칙금 분석과 Supervisor 근거 검색에 사용할 수 있음")
        notes = @("동혁 담당 범위는 법률 데이터만이다.")
    },
    @{
        number = 21; title = "feat-fault-ratio-precedent-caption-review-case-pipeline"; assignees = @("leejaegang27"); milestone = $Middle; labels = @("enhancement", "wbs", "phase:middle", "domain:fault")
        summary = "과실비율 판례, 유튜브 자막 사례, 과실비율심의사례 데이터를 수집·전처리한다."
        outputs = @("과실비율 판례 데이터", "유튜브 자막 사례 데이터", "과실비율심의사례 데이터", "RAG 등록 metadata")
        acceptance = @("보험 텍스트 수집/전처리 파이프라인은 재강 담당으로 정리됨", "workzion2 담당으로 남지 않음")
        notes = @("경위서/OCR 결과 처리와 텍스트 ML 입력으로 연결한다.")
    },
    @{
        number = 22; title = "feat-agent-result-schema-and-rag-contract"; assignees = $All; milestone = $Middle; labels = @("enhancement", "wbs", "phase:middle", "domain:supervisor")
        summary = "각 Agent가 반환할 결과 스키마와 RAG 근거 metadata 계약을 정의한다."
        outputs = @("Agent result schema", "RAG chunk metadata", "Supervisor 통합 답변 포맷")
        acceptance = @("개별 Agent는 근거/분석 결과를 반환하고 최종 답변은 Supervisor가 생성함")
        notes = @("법률 답변 Agent를 동혁 개인 담당으로 두지 않는다.")
    },
    @{
        number = 23; title = "feat-fine-notice-ocr-intake-flow"; assignees = @("workzion2"); milestone = $Middle; labels = @("enhancement", "wbs", "phase:middle", "domain:fine")
        summary = "고지서 이미지/OCR 원문을 받아 위반 정보 필드로 구조화한다."
        outputs = @("고지서 OCR 구조화 결과", "필드 누락/신뢰도 상태")
        acceptance = @("위반 일시, 장소, 유형, 통지일, 납부기한, 기관 필드가 구조화됨")
        notes = @("필주 담당에서 고지서 OCR을 제외하지 않는다.")
    },
    @{
        number = 24; title = "feat-fine-penalty-rule-mapping"; assignees = @("workzion2"); milestone = $Middle; labels = @("enhancement", "wbs", "phase:middle", "domain:fine")
        summary = "과태료, 범칙금, 벌칙 데이터를 분석용 룰/매핑 데이터로 정리한다."
        outputs = @("과태료 룰", "범칙금 룰", "벌칙 매핑", "처분 단계 상태값")
        acceptance = @("동혁 법률 원문 DB와 중복되지 않는 분석용 데이터로 분리됨")
        notes = @("법률 근거 원문은 동혁 데이터에서 참조한다.")
    },
    @{
        number = 25; title = "feat-fine-analysis-detail-view"; assignees = @("workzion2"); milestone = $Middle; labels = @("enhancement", "wbs", "phase:middle", "domain:fine")
        summary = "과태료·범칙금 분석 상세보기에서 OCR 결과, 처분 단계, 부족 서류, 필요 증거를 표시한다."
        outputs = @("상세보기 응답 구조", "분석 결과 화면 항목", "부족 서류/필요 증거 목록")
        acceptance = @("사용자가 고지서 분석 결과를 한 화면에서 확인함")
        notes = @("리포팅 상세 분석과 분리된 과태료·범칙금 상세 화면이다.")
    },
    @{
        number = 26; title = "feat-fine-law-ground-search"; assignees = @("workzion2", "techshin31"); milestone = $Middle; labels = @("enhancement", "wbs", "phase:middle", "domain:fine", "domain:legal")
        summary = "필주 과태료·범칙금 분석 결과에 동혁 법률 근거 검색 결과를 연결한다."
        outputs = @("법률 근거 검색 연결", "근거 metadata", "분석 결과 evidence")
        acceptance = @("관련 법령/행정 기준 근거가 분석 결과에 포함됨")
        notes = @("최종 자연어 답변은 Supervisor가 생성한다.")
    },
    @{
        number = 27; title = "feat-objection-draft-report-node"; assignees = @("hi20260204-maker", "workzion2"); milestone = $Middle; labels = @("enhancement", "wbs", "phase:middle", "domain:fine", "domain:supervisor")
        summary = "필주 분석 결과와 동혁 법률 근거를 받아 이의신청서 초안을 생성한다."
        outputs = @("이의신청서 생성 입력 schema", "초안 생성 결과", "복사/다운로드 연계")
        acceptance = @("이의신청서 생성은 요청자 담당으로 고정됨", "필주 분석 결과를 입력으로 사용함")
        notes = @("혜림 담당으로 두지 않고 요청자 담당으로 정리한다.")
    },
    @{
        number = 28; title = "test-fine-mvp-sample-case-validation"; assignees = @("workzion2"); milestone = $Middle; labels = @("wbs", "phase:middle", "domain:fine", "domain:qa")
        summary = "과태료·범칙금 샘플 케이스로 OCR/분석/근거 연결 흐름을 검증한다."
        outputs = @("샘플 케이스 검증표", "실패 케이스", "누락 필드 목록")
        acceptance = @("중간 발표 샘플 케이스가 통과됨")
        notes = @("검증 결과는 Supervisor 통합 QA로 넘긴다.")
    },
    @{
        number = 29; title = "feat-supervisor-chatbot-routing"; assignees = @("hi20260204-maker"); milestone = $Middle; labels = @("enhancement", "wbs", "phase:middle", "domain:supervisor")
        summary = "메인 챗봇에서 질문/자료 유형을 분류하고 적절한 Agent 흐름으로 분기한다."
        outputs = @("Supervisor routing", "질문 의도 분류", "자료 유형 분기", "통합 답변 생성")
        acceptance = @("이미지, 영상, 고지서 OCR, 경위서/OCR, 법률 질문이 올바른 노드로 분기됨")
        notes = @("최종 답변은 각 Agent 결과 스키마를 보고 Supervisor가 형성한다.")
    },
    @{
        number = 30; title = "feat-fault-ratio-ml-knowledge-base"; assignees = @("leejaegang27"); milestone = $Middle; labels = @("enhancement", "wbs", "phase:middle", "domain:fault")
        summary = "과실비율 판례, 자막 사례, 심의사례, 경위서/OCR 결과를 ML/RAG 지식베이스로 구성한다."
        outputs = @("텍스트 chunk", "embedding", "summary", "metadata", "tags")
        acceptance = @("분류값, 요약값, 태그값, 유사도/추천값을 산출함", "최종 과실비율 확정 판단 모델로 정의하지 않음")
        notes = @("재강 담당 ML 모델 범위를 명확히 둔다.")
    },
    @{
        number = 31; title = "feat-fault-ratio-structured-question-flow"; assignees = @("leejaegang27", "hi20260204-maker"); milestone = $Middle; labels = @("enhancement", "wbs", "phase:middle", "domain:fault", "domain:supervisor")
        summary = "사고 설명 텍스트를 기반으로 추가 질문과 사고 유형 후보를 구성한다."
        outputs = @("사고유형 후보", "추가 질문 schema", "쟁점/증거 태그")
        acceptance = @("Supervisor가 사용자에게 필요한 추가 정보를 간단히 요청할 수 있음")
        notes = @("경위서/OCR 결과와 일반 텍스트 질문 모두 처리한다.")
    },
    @{
        number = 32; title = "feat-fault-ratio-result-range-view"; assignees = @("hi20260204-maker", "leejaegang27"); milestone = $Middle; labels = @("enhancement", "wbs", "phase:middle", "domain:fault")
        summary = "과실비율 결과를 단정 수치가 아니라 정성 범위와 근거 중심으로 표시한다."
        outputs = @("결과 범위 표시", "근거 카드", "한계/주의 문구")
        acceptance = @("법적 구속력 있는 판단처럼 보이지 않음")
        notes = @("리포트 화면에서 과실비율 수치는 참고용으로만 표시한다.")
    },
    @{
        number = 33; title = "feat-fault-response-evidence-schema"; assignees = @("leejaegang27", "hi20260204-maker"); milestone = $Middle; labels = @("enhancement", "wbs", "phase:middle", "domain:fault", "domain:supervisor")
        summary = "과실비율 흐름에서 대응 스크립트가 아니라 Supervisor 답변에 들어갈 근거/후속 행동 스키마를 만든다."
        outputs = @("후속 행동", "근거 요약", "대응 문구 후보")
        acceptance = @("판례/사례/영상/법률 근거가 분리된 evidence로 반환됨")
        notes = @("최종 답변 문장은 Supervisor가 조합한다.")
    },
    @{
        number = 34; title = "feat-settlement-checklist-flow"; assignees = @(); milestone = $null; labels = @("wbs", "scope:out")
        summary = "합의금 체크리스트 기능은 최신 핵심 WBS에서 제외한다."
        outputs = @("후순위 기록")
        acceptance = @("현재 MVP 범위에서 닫힘 처리")
        notes = @("보험 약관/합의금 확장은 후순위로 관리한다.")
        state = "closed"; state_reason = "not_planned"
    },
    @{
        number = 35; title = "feat-settlement-document-draft"; assignees = @(); milestone = $null; labels = @("wbs", "scope:out")
        summary = "합의금/보험 문서 초안 기능은 최신 핵심 WBS에서 제외한다."
        outputs = @("후순위 기록")
        acceptance = @("현재 MVP 범위에서 닫힘 처리")
        notes = @("이의신청서 생성과 혼동하지 않는다.")
        state = "closed"; state_reason = "not_planned"
    },
    @{
        number = 36; title = "spike-vision-model-use-case-decision"; assignees = @("ohjuheecode"); milestone = $Middle; labels = @("enhancement", "wbs", "phase:middle", "domain:vision")
        summary = "차량 사고 이미지/영상 분석에서 사용할 Vision/DL 베이스라인 범위를 결정한다."
        outputs = @("Vision/DL 적용 범위", "모델 후보", "샘플 검증 기준")
        acceptance = @("영상/이미지 Agent의 입력과 출력이 정리됨")
        notes = @("고지서 OCR은 필주 흐름으로 분리한다.")
    },
    @{
        number = 37; title = "feat-accident-vision-data-manifest-pipeline"; assignees = @("ohjuheecode"); milestone = $Middle; labels = @("enhancement", "wbs", "phase:middle", "domain:vision")
        summary = "차량 사고 이미지·영상 데이터셋 manifest와 전처리 구조를 만든다."
        outputs = @("데이터셋 manifest", "영상 metadata", "프레임 추출 결과")
        acceptance = @("DL/RAG 입력으로 사용할 수 있는 파일/metadata 구조가 만들어짐")
        notes = @("주희 담당으로 단일화한다.")
    },
    @{
        number = 38; title = "feat-accident-image-video-agent-result-flow"; assignees = @("ohjuheecode", "hi20260204-maker"); milestone = $Middle; labels = @("enhancement", "wbs", "phase:middle", "domain:vision", "domain:supervisor")
        summary = "영상·이미지 분석 결과를 텍스트 요약과 confidence metadata로 변환해 Supervisor에 넘긴다."
        outputs = @("영상 분석 결과", "이미지 분석 결과", "텍스트 요약", "confidence")
        acceptance = @("재강 텍스트 ML/판례 결과와 과실비율 흐름에서 병합 가능")
        notes = @("주희 DL 결과가 재강 ML의 필수 입력이 되지 않도록 병목을 피한다.")
    },
    @{
        number = 39; title = "test-vision-accident-poc-validation"; assignees = @("ohjuheecode"); milestone = $Middle; labels = @("wbs", "phase:middle", "domain:vision", "domain:qa")
        summary = "Vision/DL POC의 정확도, 한계, 실패 케이스를 검증한다."
        outputs = @("검증 샘플", "성공/실패 케이스", "한계 문서")
        acceptance = @("중간 발표에서 보여줄 수 있는 샘플 결과가 준비됨")
        notes = @("과실비율 확정 판단은 제외한다.")
    },
    @{
        number = 40; title = "test-cross-mvp-integration-scenarios"; assignees = $All; milestone = $Middle; labels = @("wbs", "phase:middle", "domain:qa")
        summary = "과태료·범칙금, 과실비율, 법률, Vision, 이의신청서 생성 흐름의 통합 시나리오를 검증한다."
        outputs = @("통합 시나리오", "E2E 검증 결과", "실패 목록")
        acceptance = @("중간 발표 MVP 흐름이 최소 1개 이상 끝까지 연결됨")
        notes = @("Supervisor 결과 스키마 통합을 함께 검증한다.")
    },
    @{
        number = 41; title = "test-legal-ai-guardrail-validation"; assignees = $All; milestone = $Middle; labels = @("wbs", "phase:middle", "domain:qa", "domain:legal")
        summary = "법률/과실비율/과태료 답변이 확정 판단처럼 보이지 않도록 guardrail을 검증한다."
        outputs = @("guardrail 체크리스트", "금지 표현 목록", "면책/한계 문구")
        acceptance = @("성공 보장, 법률 확정 판단, 과실비율 단정 수치를 피함")
        notes = @("최종 답변은 Supervisor가 생성하므로 Supervisor 레이어에서 검증한다.")
    },
    @{
        number = 42; title = "docs-final-demo-scenario-and-risk-checklist"; assignees = @("hi20260204-maker"); milestone = $Final; labels = @("documentation", "wbs", "phase:final", "domain:docs", "domain:qa")
        summary = "최종 발표 시나리오와 리스크 체크리스트를 작성한다."
        outputs = @("최종 데모 시나리오", "리스크 체크리스트", "발표 흐름")
        acceptance = @("2026-08-04 최종 제출 전 데모 시나리오가 확정됨")
        notes = @("중간 발표 피드백을 반영한다.")
    },
    @{
        number = 43; title = "chore-final-stabilization-and-release-readiness"; assignees = @("hi20260204-maker"); milestone = $Final; labels = @("enhancement", "wbs", "phase:final", "domain:qa")
        summary = "최종 안정화, 배포 상태, 문서 제출 상태를 마무리한다."
        outputs = @("최종 QA 결과", "배포 확인", "제출 문서 확인")
        acceptance = @("2026-08-04 최종 마무리 기준을 만족함")
        notes = @("production 배포와 운영 문서가 포함된다.")
    }
)

foreach ($label in $Labels) {
    Ensure-Label -Name $label.name -Color $label.color -Description $label.description
}

$MiddleMilestone = Ensure-Milestone -Title $Middle -DueOn "2026-07-14T14:59:59Z" -Description "중간 발표용 연결 MVP 기준일"
$FinalMilestone = Ensure-Milestone -Title $Final -DueOn "2026-08-04T14:59:59Z" -Description "최종 마무리 및 제출 기준일"

$MilestoneNumbers = @{
    $Middle = $MiddleMilestone
    $Final = $FinalMilestone
}

foreach ($issue in $IssueUpdates) {
    $body = Format-IssueBody -Issue $issue
    $patch = @{
        title = $issue.title
        body = $body
        assignees = $issue.assignees
        labels = $issue.labels
    }

    if ($issue.ContainsKey("milestone")) {
        if ($null -eq $issue.milestone) {
            $patch["milestone"] = $null
        }
        else {
            $patch["milestone"] = $MilestoneNumbers[$issue.milestone]
        }
    }

    if ($issue.ContainsKey("state")) {
        $patch["state"] = $issue.state
    }
    if ($issue.ContainsKey("state_reason")) {
        $patch["state_reason"] = $issue.state_reason
    }

    Invoke-GitHubApi -Method "PATCH" -Path "/repos/$Owner/$Repo/issues/$($issue.number)" -Body $patch | Out-Null
    Write-Host "Updated issue #$($issue.number): $($issue.title)"
}

Write-Host "GitHub issue sync completed."

