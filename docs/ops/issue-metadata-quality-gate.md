# GitHub 이슈 메타데이터 품질 게이트

## 목적

열린 실행 이슈의 담당자, 분류, 일정과 상태가 누락되거나 서로 다른 위치에 중복되는 문제를 조기에 발견한다. 이 게이트는 누락을 보고하고 CI를 실패시키지만, 이슈나 조직 필드를 자동 수정하거나 삭제하지 않는다.

연결 이슈: #177, #180

## 필수 기준

모든 열린 실행 이슈는 다음 값을 가져야 한다.

- 담당자 1명 이상
- `wbs` 라벨
- `domain:*` 라벨 1개 이상
- `phase:*` 라벨 1개 이상
- 마일스톤
- Issue Type
- 공식 Issue Field: `Priority`, `Status`, `Start date`, `Target date`
- 본문 일정: `기준일: YYYY-MM-DD`, `시작일: YYYY-MM-DD`, `목표일: YYYY-MM-DD`

Pull Request와 닫힌 이슈는 감사 대상에서 제외한다. `Size`와 `Estimate`는 기존 백로그 보정이 끝날 때까지 실패 조건으로 사용하지 않는다.

## 실행 방법

GitHub Actions에서는 기본 `GITHUB_TOKEN`의 `issues: read` 권한으로 실행한다.

```bash
GITHUB_TOKEN=... python scripts/issue_metadata_audit.py \
  --repository SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team
```

PowerShell:

```powershell
$env:GITHUB_TOKEN = "..."
python scripts/issue_metadata_audit.py --repository SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team
```

누락이 없으면 종료 코드 `0`, 하나라도 있으면 종료 코드 `1`을 반환한다. Actions에서는 누락 이슈 링크와 위반 코드가 Job Summary에 기록된다.

## 자동 실행

`.github/workflows/issue-metadata-audit.yml`은 다음 시점에 실행한다.

- 매주 월요일 09:00 KST
- 수동 `workflow_dispatch`
- 이슈 생성·재개와 담당자·라벨·마일스톤·유형·Issue Field 변경

GitHub Issue Field 조회에는 REST API 버전 `2026-03-10`의 `/issue-field-values` 엔드포인트를 사용한다.

## 상태 전환 기준

| 상태 | 전환 기준 |
|---|---|
| Backlog | 범위가 기록됐지만 담당자·일정·선행조건 중 하나 이상이 확정되지 않음 |
| Ready | 필수 메타데이터가 모두 있고 선행조건과 완료 기준이 확인됨 |
| In progress | 담당자가 실제 작업을 시작했고 현재 작업·다음 행동을 설명할 수 있음 |
| In review | 구현 산출물과 검증 증거가 PR 또는 리뷰 문서에 연결됨 |
| Done | 변경이 통합됐고 완료 조건과 검증 증거가 이슈에 남음 |

`closed as not planned` 또는 `duplicate`는 한국어 근거와 대체 이슈 링크를 남긴 뒤 사용한다.

## 중복 일정 필드 정리

조직에 남아 있는 과거 `start`와 `fin`은 다음 순서로 정리한다.

1. 기존 값을 공식 `Start date`와 `Target date`로 이관한다.
2. 감사 결과에서 공식 필드 누락이 0건인지 확인한다.
3. 팀 리뷰 후 과거 필드를 삭제한다.

필드 삭제는 조직 전체에 영향을 주므로 이 스크립트에서 자동 수행하지 않는다.

## 위반 코드

| 코드 | 의미 |
|---|---|
| `missing_assignee` | 담당자 없음 |
| `missing_label:wbs` | WBS 추적 라벨 없음 |
| `missing_label:domain:*` | 도메인 라벨 없음 |
| `missing_label:phase:*` | 단계 라벨 없음 |
| `missing_milestone` | 마일스톤 없음 |
| `missing_type` | Issue Type 없음 |
| `missing_field:<name>` | 공식 Issue Field 값 없음 |
| `missing_body_date:<label>` | 본문 일정 항목이 없거나 ISO 날짜 형식이 아님 |
