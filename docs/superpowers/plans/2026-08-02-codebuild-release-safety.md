# CodeBuild Release Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Release CodeBuild가 SSM timeout을 스스로 취소하고, 계층형 timeout과 명확한 rollback 결과를 제공하도록 기존 Pilot 배포 안전성을 개선한다.

**Architecture:** 기존 `dev -> Build -> Manual Approval -> Release CodeBuild -> SSM EC2` 구조와 원격 배포 트랜잭션은 유지한다. Terraform IAM과 CodeBuild timeout, release runner의 SSM request·polling·rollback logging만 최소 변경하고 계약 테스트로 권한 범위와 실행 순서를 고정한다.

**Tech Stack:** Terraform 1.11+, AWS Provider 6.x, AWS CodeBuild, AWS CodePipeline, AWS Systems Manager, Bash, pytest 9.1.1

## Global Constraints

- Build CodeBuild 역할에는 SSM 권한을 추가하지 않는다.
- Release CodeBuild에는 `ssm:CancelCommand` 외의 신규 EC2·RDS·IAM·ECR push·Parameter Store 권한을 추가하지 않는다.
- SSM command timeout은 1,500초, runner polling timeout은 1,680초, Release CodeBuild timeout은 40분으로 고정한다.
- Release CodeBuild `queued_timeout`은 30분으로 유지한다.
- 원래 배포 실패 코드는 rollback 결과와 관계없이 비영 상태로 유지한다.
- rollback은 모든 복구 단계를 best-effort로 시도하고 `ROLLBACK_STATUS=complete` 또는 `ROLLBACK_STATUS=incomplete`를 출력한다.
- 앱 release의 RAG, schema, paid smoke, Vision, Compose 및 Caddy 범위는 변경하지 않는다.
- 실제 AWS apply는 saved plan 검토와 사용자 승인 후에만 실행한다.

---

### Task 1: IAM 및 timeout 계약 테스트

**Files:**
- Modify: `test/test_codebuild_pilot_contract.py`
- Later modify: `infra/terraform-pilot/codebuild.tf`
- Later modify: `deploy/aws-pilot/Release-PilotApp-FromPipeline.sh`

**Interfaces:**
- Consumes: Terraform의 `data "aws_iam_policy_document" "pilot_app_release"`, `aws_codebuild_project.pilot_app_release`; release runner 상수 및 SSM request JSON
- Produces: IAM 최소 권한과 `1500 < 1680 < 2400` timeout 순서를 고정하는 계약 테스트

- [ ] **Step 1: IAM 취소 권한 테스트 작성**

`test_pilot_app_release_requires_manual_approval_and_scoped_ssm_access`의 Release policy assertion에 다음을 추가한다.

```python
assert '"ssm:CancelCommand"' in release_policy
```

Build policy에는 SSM 권한이 없어야 한다는 별도 테스트를 추가한다.

```python
def test_build_codebuild_role_has_no_ssm_release_permissions() -> None:
    codebuild = (ROOT / "infra" / "terraform-pilot" / "codebuild.tf").read_text(
        encoding="utf-8"
    )
    build_start = codebuild.index('data "aws_iam_policy_document" "codebuild"')
    build_end = codebuild.index(
        'resource "aws_iam_role_policy" "codebuild"', build_start
    )
    build_policy = codebuild[build_start:build_end]

    for forbidden in ("ssm:SendCommand", "ssm:GetCommandInvocation", "ssm:CancelCommand"):
        assert forbidden not in build_policy
```

- [ ] **Step 2: timeout 계층 테스트 작성**

```python
def test_app_release_uses_layered_ssm_and_codebuild_timeouts() -> None:
    codebuild = (ROOT / "infra" / "terraform-pilot" / "codebuild.tf").read_text(
        encoding="utf-8"
    )
    runner = (
        ROOT / "deploy" / "aws-pilot" / "Release-PilotApp-FromPipeline.sh"
    ).read_text(encoding="utf-8")

    release_start = codebuild.index(
        'resource "aws_codebuild_project" "pilot_app_release"'
    )
    release_project = codebuild[release_start:]
    assert "build_timeout  = 40" in release_project
    assert "queued_timeout = 30" in release_project
    assert "readonly ssm_timeout_seconds=1500" in runner
    assert "readonly polling_timeout_seconds=1680" in runner
    assert '"TimeoutSeconds": int(ssm_timeout_seconds)' in runner
```

- [ ] **Step 3: timeout 처리 순서 테스트 작성**

```python
def test_app_release_collects_timeout_evidence_before_cancelling_ssm() -> None:
    runner = (
        ROOT / "deploy" / "aws-pilot" / "Release-PilotApp-FromPipeline.sh"
    ).read_text(encoding="utf-8")

    timeout_branch = runner.index("SSM command exceeded")
    evidence = runner.index("StandardOutputContent", timeout_branch)
    cancel = runner.index("aws ssm cancel-command", evidence)
    cancel_result = runner.index("SSM_CANCEL_STATUS=", cancel)

    assert timeout_branch < evidence < cancel < cancel_result
```

- [ ] **Step 4: 새 테스트가 예상 원인으로 실패하는지 확인**

Run:

```powershell
python -m pytest -q `
  test/test_codebuild_pilot_contract.py::test_pilot_app_release_requires_manual_approval_and_scoped_ssm_access `
  test/test_codebuild_pilot_contract.py::test_build_codebuild_role_has_no_ssm_release_permissions `
  test/test_codebuild_pilot_contract.py::test_app_release_uses_layered_ssm_and_codebuild_timeouts `
  test/test_codebuild_pilot_contract.py::test_app_release_collects_timeout_evidence_before_cancelling_ssm
```

Expected: Build 역할 금지 테스트만 통과하고, 나머지는 `CancelCommand`, timeout 상수 또는 처리 순서가 아직 없어서 실패한다.

### Task 2: IAM과 timeout 구현

**Files:**
- Modify: `infra/terraform-pilot/codebuild.tf`
- Modify: `deploy/aws-pilot/Release-PilotApp-FromPipeline.sh`
- Test: `test/test_codebuild_pilot_contract.py`

**Interfaces:**
- Consumes: Task 1의 정확한 문자열 계약
- Produces: 40분 Release CodeBuild, 1,500초 SSM request, 1,680초 polling 및 timeout 취소 결과 로그

- [ ] **Step 1: Release IAM에 취소 권한 추가**

`ReadReleaseCommandInvocation` statement의 actions를 다음처럼 변경한다.

```hcl
actions = [
  "ssm:CancelCommand",
  "ssm:GetCommandInvocation",
]
```

AWS API resource-level 지원 범위 때문에 기존 `resources = ["*"]`는 유지한다. statement SID는 `ManageReleaseCommandInvocation`으로 변경해 의미를 명확히 한다.

- [ ] **Step 2: Release CodeBuild timeout을 40분으로 변경**

```hcl
build_timeout  = 40
queued_timeout = 30
```

- [ ] **Step 3: runner timeout 상수 분리**

파일 상단을 다음처럼 변경한다.

```bash
readonly ssm_timeout_seconds=1500
readonly polling_timeout_seconds=1680
readonly poll_seconds=10
```

- [ ] **Step 4: SSM request에 command timeout 전달**

Python 호출 인자에 `"$ssm_timeout_seconds"`를 추가하고 JSON 생성 코드를 다음 계약으로 변경한다.

```python
request_path, instance_id, command, ssm_timeout_seconds = sys.argv[1:]
with open(request_path, "w", encoding="utf-8") as handle:
    json.dump(
        {
            "DocumentName": "AWS-RunShellScript",
            "InstanceIds": [instance_id],
            "Comment": "Release immutable Pilot app images",
            "TimeoutSeconds": int(ssm_timeout_seconds),
            "Parameters": {"commands": [command]},
        },
        handle,
    )
```

- [ ] **Step 5: polling deadline 변경**

```bash
deadline=$((SECONDS + polling_timeout_seconds))
```

- [ ] **Step 6: timeout evidence 수집과 취소 결과 기록**

polling loop 아래에서 timeout을 먼저 출력하고 invocation 결과를 best-effort로 수집한다. 이어 취소 성공 여부를 명시적으로 기록한다.

```bash
echo "SSM command exceeded ${polling_timeout_seconds} seconds." >&2
aws ssm get-command-invocation \
  --region "$AWS_DEFAULT_REGION" \
  --command-id "$command_id" \
  --instance-id "$PILOT_INSTANCE_ID" \
  --query '{Status:Status,StandardOutputContent:StandardOutputContent,StandardErrorContent:StandardErrorContent}' \
  --output json \
  --no-cli-pager >&2 || true

if aws ssm cancel-command \
  --region "$AWS_DEFAULT_REGION" \
  --command-id "$command_id" \
  --no-cli-pager >/dev/null; then
  echo "SSM_CANCEL_STATUS=complete" >&2
else
  echo "SSM_CANCEL_STATUS=incomplete" >&2
fi
exit 1
```

- [ ] **Step 7: Task 1 테스트 통과 확인**

Run:

```powershell
python -m pytest -q test/test_codebuild_pilot_contract.py
```

Expected: 모든 CodeBuild 계약 테스트 통과.

### Task 3: rollback 결과 계약 및 구현

**Files:**
- Modify: `test/test_codebuild_pilot_contract.py`
- Modify: `deploy/aws-pilot/Release-PilotApp-FromPipeline.sh`

**Interfaces:**
- Consumes: 원격 `rollback_app_release` 함수와 기존 `restore_tag`, `restore_previous_evidence`, compose 복구 명령
- Produces: 실패 단계 목록과 `ROLLBACK_STATUS` 표식

- [ ] **Step 1: rollback 관측성 실패 테스트 작성**

```python
def test_app_release_reports_complete_or_incomplete_rollback() -> None:
    runner = (
        ROOT / "deploy" / "aws-pilot" / "Release-PilotApp-FromPipeline.sh"
    ).read_text(encoding="utf-8")

    rollback_start = runner.index("rollback_app_release()")
    rollback_end = runner.index("trap rollback_app_release ERR", rollback_start)
    rollback = runner[rollback_start:rollback_end]

    assert "rollback_failures=()" in rollback
    assert "ROLLBACK_STATUS=complete" in rollback
    assert "ROLLBACK_STATUS=incomplete" in rollback
    for step in (
        "restore_tag",
        "restore_previous_evidence",
        "remove_runtime_services",
        "start_frontend_backend",
        "start_workers",
        "cleanup_seed_and_evidence",
    ):
        assert step in rollback
```

- [ ] **Step 2: 테스트가 기존 rollback 구현에서 실패하는지 확인**

Run:

```powershell
python -m pytest -q test/test_codebuild_pilot_contract.py::test_app_release_reports_complete_or_incomplete_rollback
```

Expected: `rollback_failures=()` 또는 `ROLLBACK_STATUS`가 없어 실패.

- [ ] **Step 3: rollback 단계 실행 helper 추가**

원격 스크립트에 배열과 helper를 둔다.

```bash
rollback_failures=()

record_rollback_step() {
  local step="$1"
  shift
  if ! "$@"; then
    rollback_failures+=("$step")
    echo "Rollback step failed: $step" >&2
  fi
}
```

복합 compose 명령은 함수로 감싸 exact command와 단계 이름을 분리한다.

- [ ] **Step 4: 모든 rollback 단계를 best-effort로 실행**

`rollback_app_release`는 진입 즉시 원래 `$?`를 저장하고 `trap - ERR` 후 다음 단계를 순서대로 호출한다.

```text
restore_tag
restore_previous_evidence
remove_runtime_services
start_frontend_backend
start_workers
cleanup_seed_and_evidence
```

각 단계는 실패해도 다음 단계로 진행한다.

- [ ] **Step 5: 최종 rollback 상태 출력**

```bash
if (( ${#rollback_failures[@]} == 0 )); then
  echo "ROLLBACK_STATUS=complete" >&2
else
  printf 'ROLLBACK_STATUS=incomplete steps=%s\n' "${rollback_failures[*]}" >&2
fi
exit "$status"
```

- [ ] **Step 6: rollback 계약 테스트 통과 확인**

Run:

```powershell
python -m pytest -q test/test_codebuild_pilot_contract.py
```

Expected: 모든 CodeBuild 계약 테스트 통과.

### Task 4: 운영 문서 동기화

**Files:**
- Modify: `deploy/aws-pilot/README.ko.md`
- Modify: `docs/aws-codebuild-constraints-review.ko.md`
- Test: `test/test_codebuild_pilot_contract.py`

**Interfaces:**
- Consumes: 확정된 timeout 값과 rollback 로그 계약
- Produces: 운영자가 timeout·취소·불완전 rollback을 판별하는 runbook 설명

- [ ] **Step 1: Pilot 운영 문서 수정**

CodePipeline 앱 이미지 승인 배포 절에 다음 내용을 추가한다.

- SSM command 최대 실행 1,500초
- runner polling 최대 1,680초
- Release CodeBuild 최대 실행 40분
- timeout 시 `SSM_CANCEL_STATUS` 확인
- 실패 시 `ROLLBACK_STATUS` 및 실패 단계 확인
- `incomplete`면 재승인하지 말고 EC2 상태와 서비스별 compose 상태를 수동 확인

- [ ] **Step 2: 제약 검토 보고서 상태 갱신**

`docs/aws-codebuild-constraints-review.ko.md`의 P0/P1 항목에 구현 후 검증 결과를 기록할 수 있는 상태 절을 추가한다. 실제 AWS apply 전에는 저장소 구현 완료와 AWS 적용 완료를 구분한다.

- [ ] **Step 3: 문서 형식 검사**

Run:

```powershell
git diff --check
```

Expected: whitespace 오류 없음.

### Task 5: 저장소 검증과 Terraform saved plan 준비

**Files:**
- Verify: `infra/terraform-pilot/*.tf`
- Verify: `deploy/aws-pilot/Release-PilotApp-FromPipeline.sh`
- Verify: `test/test_codebuild_pilot_contract.py`
- Verify: `test/test_aws_pilot_infrastructure.py`
- Verify: `test/test_aws_vision_worker_infrastructure.py`

**Interfaces:**
- Consumes: Tasks 1~4의 변경 전체
- Produces: 로컬 검증 증거와 실제 AWS 적용에 사용할 reviewed saved plan

- [ ] **Step 1: 관련 Python 계약 테스트 실행**

Run:

```powershell
python -m pytest -q `
  test/test_codebuild_pilot_contract.py `
  test/test_aws_pilot_infrastructure.py `
  test/test_aws_vision_worker_infrastructure.py
```

Expected: 모든 테스트 통과.

- [ ] **Step 2: Bash 구문 검사**

Run in a Bash-capable environment:

```bash
bash -n deploy/aws-pilot/Release-PilotApp-FromPipeline.sh
```

Expected: exit 0, 출력 없음.

- [ ] **Step 3: Terraform format 검사**

Run:

```powershell
terraform -chdir=infra/terraform-pilot fmt -check
```

Expected: exit 0.

- [ ] **Step 4: Terraform 초기화 및 validate**

승인된 운영 checkout에서 비공개 `backend.hcl`을 사용한다.

```powershell
terraform -chdir=infra/terraform-pilot init -backend-config=backend.hcl -input=false
terraform -chdir=infra/terraform-pilot validate
```

Expected: 초기화 및 구성 검증 성공.

- [ ] **Step 5: saved plan 생성**

```powershell
terraform -chdir=infra/terraform-pilot plan `
  -var-file=terraform.tfvars `
  -out=pilot-codebuild-safety.tfplan
```

Expected changes:

- Release CodeBuild IAM inline policy 변경
- Release CodeBuild timeout 30분에서 40분으로 변경
- 소스 artifact 변경에 따른 Pipeline 실행 가능성 외 런타임 리소스 변경 없음

- [ ] **Step 6: plan JSON 범위 검사**

```powershell
terraform -chdir=infra/terraform-pilot show `
  -json pilot-codebuild-safety.tfplan
```

검토 기준:

- EC2, RDS, VPC, security group, S3 data bucket의 create/delete/replace 없음
- Build CodeBuild IAM에 SSM 권한 없음
- Release 역할에 `CancelCommand` 외 예상하지 않은 권한 없음
- Release CodeBuild timeout만 예상값으로 변경

### Task 6: 실제 AWS 적용 및 운영 검증

**Files:**
- Apply artifact: `infra/terraform-pilot/pilot-codebuild-safety.tfplan` (Git에 커밋하지 않음)
- Evidence: CloudWatch CodeBuild log 및 SSM command invocation

**Interfaces:**
- Consumes: Task 5에서 검토된 동일 saved plan
- Produces: 적용된 IAM·CodeBuild 설정과 정상/timeout 운영 검증 증거

- [ ] **Step 1: 사용자에게 saved plan 요약과 변경 리소스 제시**

적용 전에 create/update/delete/replace 수와 변경 리소스 주소를 보고한다. delete 또는 replace가 하나라도 있으면 적용을 중단하고 원인을 조사한다.

- [ ] **Step 2: 명시적 승인 후 동일 saved plan 적용**

```powershell
terraform -chdir=infra/terraform-pilot apply pilot-codebuild-safety.tfplan
```

Expected: IAM inline policy와 Release CodeBuild 설정만 업데이트.

- [ ] **Step 3: 적용 후 drift 확인**

```powershell
terraform -chdir=infra/terraform-pilot plan `
  -var-file=terraform.tfvars `
  -detailed-exitcode
```

Expected: exit 0, `No changes`.

- [ ] **Step 4: 정상 release 경로 검증**

새 immutable app-only commit에 대해 Build 성공, 수동 승인, SSM 성공, HTTPS health, transaction gate와 `ROLLBACK_STATUS` 미출력을 확인한다.

- [ ] **Step 5: 통제된 timeout 경로 검증**

운영 서비스 전환을 수행하지 않는 승인된 검증 command 또는 별도 테스트 환경에서 timeout을 재현한다. 다음을 확인한다.

- CodeBuild 역할의 `CancelCommand` 성공
- `SSM_CANCEL_STATUS=complete`
- CodeBuild가 40분 전에 종료
- 원격 command가 종료됨
- timeout 증거에 command ID와 stdout/stderr가 남음

- [ ] **Step 6: 2차 release-class 계획 착수 조건 확인**

정상 release와 통제된 timeout 검증이 모두 확보된 경우에만 `frontend-only`, `backend-schema-free`, `full-release` 분리 계획을 시작한다.

