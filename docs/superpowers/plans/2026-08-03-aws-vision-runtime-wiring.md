# AWS Vision Runtime Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Pilot deployment derive the AWS Vision queue and result storage runtime values from the reviewed Terraform state whenever `VISION_RUNTIME_PROVIDER=aws_queue` is selected.

**Architecture:** Keep Terraform responsible for the optional private `g5.xlarge`, SQS FIFO, S3, IAM, ECR, and controller resources. Extend `Deploy-Pilot.ps1` to resolve those non-secret outputs into the existing SSM runtime environment and fail before SSM mutation if the worker stack is missing or malformed. Preserve local and RunPod provider compatibility and verify the connection through contract, adapter, worker, and Supervisor tests without applying Terraform or starting paid GPU capacity.

**Tech Stack:** Terraform, PowerShell 7.2, AWS SQS/S3/SSM/EC2/ECR/Lambda/EventBridge, Python 3, pytest, Django Agent Worker.

## Global Constraints

- Keep `vision_worker_enabled=false` and `vision_registry_enabled=false` as repository defaults.
- Keep `vision_worker_instance_type="g5.xlarge"` as the only approved Pilot GPU size.
- Do not run `terraform apply`, create AWS resources, start GPU capacity, push ECR images, or submit live SQS jobs.
- Do not commit AWS credentials, queue URLs, bucket names, AMI IDs, model artifacts, or environment-specific identifiers.
- Keep the canonical handoff schema `vision-supervisor-handoff-v1` and result prefix `vision/aws-queue/v1` unchanged.
- Preserve `local` and `runpod` provider behavior; AWS validation runs only when the runtime template selects `aws_queue`.
- Write every production behavior test first, run it to observe the expected failure, then implement the minimum change required to pass.
- Treat the accepted design at `docs/superpowers/specs/2026-08-03-aws-vision-runtime-wiring-design.md` as authoritative.

---

## File Map

- `infra/terraform-pilot/outputs.tf` — publishes the result bucket name used by the optional AWS Vision worker.
- `deploy/aws-pilot/Vision-Runtime.ps1` — performs provider-specific runtime transformation and validation without AWS or filesystem side effects.
- `deploy/aws-pilot/Deploy-Pilot.ps1` — validates provider-specific AWS outputs and injects generated runtime values before the SSM update.
- `deploy/aws-pilot/runtime.env.example` — documents the operator-controlled provider switch and generated AWS values.
- `.env.production.example` — declares the complete AWS queue provider contract without real identifiers.
- `docs/ops/vision-media-adapter-runbook.md` — explains AWS activation, observation, failure recovery, and rollback.
- `test/test_aws_pilot_infrastructure.py` — executes the real PowerShell runtime transformer with controlled inputs and pins the Terraform-to-deployment assembly contract.
- `test/test_deployment_readiness_artifacts.py` — pins machine-consumed production environment templates without secrets.

---

### Task 1: Build a real, side-effect-free AWS runtime transformer

**Files:**
- Modify: `test/test_aws_pilot_infrastructure.py:1-22, 162-197`
- Create: `deploy/aws-pilot/Vision-Runtime.ps1`
- Modify: `infra/terraform-pilot/outputs.tf:104-127`
- Modify: `deploy/aws-pilot/Deploy-Pilot.ps1:29-107, 327-418`

**Interfaces:**
- Consumes: runtime env text plus literal provider, queue URL, result bucket, worker instance ID, and worker ECR repository URL values.
- Produces: Terraform output `vision_worker_result_bucket_name`; PowerShell function `Set-AwsVisionRuntimeValues([string]$Content, [string]$Provider, [string]$QueueUrl, [string]$ResultBucket, [string]$WorkerInstanceId, [string]$WorkerRepositoryUrl) -> string`.

- [ ] **Step 1: Add a test utility that executes the real PowerShell helper**

Add `base64` and `subprocess` imports to `test/test_aws_pilot_infrastructure.py`, then add:

```python
def _run_vision_runtime(
    content: str,
    *,
    provider: str,
    queue_url: str = "",
    result_bucket: str = "",
    worker_instance_id: str = "",
    worker_repository_url: str = "",
) -> subprocess.CompletedProcess[str]:
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    helper = (DEPLOY_DIR / "Vision-Runtime.ps1").as_posix().replace("'", "''")
    command = f"""
. '{helper}'
$content = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded}'))
$result = Set-AwsVisionRuntimeValues `
  -Content $content `
  -Provider '{provider}' `
  -QueueUrl '{queue_url}' `
  -ResultBucket '{result_bucket}' `
  -WorkerInstanceId '{worker_instance_id}' `
  -WorkerRepositoryUrl '{worker_repository_url}'
[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($result))
"""
    return subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _decoded_vision_runtime(completed: subprocess.CompletedProcess[str]) -> str:
    assert completed.returncode == 0, completed.stderr
    return base64.b64decode(completed.stdout.strip()).decode("utf-8")
```

The production change that makes these helpers useful is the new pure PowerShell transformation boundary; the helpers themselves contain no expected-value logic.

- [ ] **Step 2: Write the failing successful-transformation behavior test**

Add:

```python
def test_aws_vision_runtime_uses_terraform_owned_queue_and_bucket() -> None:
    content = "\n".join(
        (
            "VISION_RUNTIME_PROVIDER=aws_queue",
            "AWS_VISION_QUEUE_URL=https://caller.invalid/stale.fifo",
            "AWS_VISION_RESULT_BUCKET=stale-bucket",
            "AWS_VISION_RESULT_PREFIX=stale-prefix",
            "AWS_VISION_TIMEOUT_SECONDS=900",
            "AWS_VISION_POLL_INTERVAL_SECONDS=2",
            "",
        )
    )

    completed = _run_vision_runtime(
        content,
        provider="aws_queue",
        queue_url="https://sqs.ap-northeast-2.amazonaws.com/123456789012/skn27-vision.fifo",
        result_bucket="skn27-clean-results",
        worker_instance_id="i-0123456789abcdef0",
        worker_repository_url="123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/skn27/vision-worker",
    )

    result = _decoded_vision_runtime(completed)
    assert "AWS_VISION_QUEUE_URL=https://sqs.ap-northeast-2.amazonaws.com/123456789012/skn27-vision.fifo" in result
    assert "AWS_VISION_RESULT_BUCKET=skn27-clean-results" in result
    assert "AWS_VISION_RESULT_PREFIX=vision/aws-queue/v1" in result
    assert "caller.invalid" not in result
    assert "stale-bucket" not in result
```

- [ ] **Step 3: Run the behavior test and verify RED**

Run:

```powershell
python -m pytest test/test_aws_pilot_infrastructure.py::test_aws_vision_runtime_uses_terraform_owned_queue_and_bucket -q
```

Expected: FAIL because `deploy/aws-pilot/Vision-Runtime.ps1` does not exist.

- [ ] **Step 4: Implement the minimal pure transformer**

Create `deploy/aws-pilot/Vision-Runtime.ps1` with `Get-EnvValue` and `Set-EnvValue` moved unchanged from `Deploy-Pilot.ps1`, plus:

```powershell
Set-StrictMode -Version Latest

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
```

- [ ] **Step 5: Run the behavior test and verify GREEN**

Run the Step 3 command again.

Expected: PASS.

- [ ] **Step 6: Write the failing deployment assembly test**

Add:

```python
def test_deploy_resolves_aws_vision_terraform_outputs_before_ssm() -> None:
    outputs = (TERRAFORM_DIR / "outputs.tf").read_text(encoding="utf-8")
    deploy = _read_deploy("Deploy-Pilot.ps1")

    assert 'output "vision_worker_result_bucket_name"' in outputs
    assert "var.vision_worker_enabled ? aws_s3_bucket.clean.id : null" in outputs
    assert '. (Join-Path $PSScriptRoot "Vision-Runtime.ps1")' in deploy
    for output_name in (
        "vision_worker_queue_url",
        "vision_worker_result_bucket_name",
        "vision_worker_instance_id",
        "vision_worker_ecr_repository_url",
    ):
        assert f'Get-TerraformValue $outputs "{output_name}"' in deploy
    assert "$runtimeEnv = Set-AwsVisionRuntimeValues" in deploy
    assert deploy.index("$runtimeEnv = Set-AwsVisionRuntimeValues") < deploy.index("aws ssm put-parameter")
```

This narrow static assembly check is retained because Terraform outputs and the top-level deployment script cannot be executed without live state; transformation behavior remains covered by the real helper execution.

- [ ] **Step 7: Run the assembly test and verify RED**

Run:

```powershell
python -m pytest test/test_aws_pilot_infrastructure.py::test_deploy_resolves_aws_vision_terraform_outputs_before_ssm -q
```

Expected: FAIL because the output and deployment assembly do not exist.

- [ ] **Step 8: Wire Terraform outputs into the pure transformer**

Add this output after `vision_worker_queue_url` in `infra/terraform-pilot/outputs.tf`:

```hcl
output "vision_worker_result_bucket_name" {
  description = "S3 bucket used for sanitized AWS Vision worker result objects."
  value       = var.vision_worker_enabled ? aws_s3_bucket.clean.id : null
}
```

In `Deploy-Pilot.ps1`, dot-source `Vision-Runtime.ps1` after setting strict mode and preferences, remove the now-duplicated `Get-EnvValue` and `Set-EnvValue` definitions, and add after the `$generatedValues` loop:

```powershell
$visionProvider = Get-EnvValue $runtimeEnv "VISION_RUNTIME_PROVIDER"
$visionRuntimeParameters = @{
    Content  = $runtimeEnv
    Provider = $visionProvider
}
if ($visionProvider -ceq "aws_queue") {
    $visionRuntimeParameters.QueueUrl = Get-TerraformValue $outputs "vision_worker_queue_url"
    $visionRuntimeParameters.ResultBucket = Get-TerraformValue $outputs "vision_worker_result_bucket_name"
    $visionRuntimeParameters.WorkerInstanceId = Get-TerraformValue $outputs "vision_worker_instance_id"
    $visionRuntimeParameters.WorkerRepositoryUrl = Get-TerraformValue $outputs "vision_worker_ecr_repository_url"
}
$runtimeEnv = Set-AwsVisionRuntimeValues @visionRuntimeParameters
```

- [ ] **Step 9: Run both Task 1 tests and verify GREEN**

Run:

```powershell
python -m pytest `
  test/test_aws_pilot_infrastructure.py::test_aws_vision_runtime_uses_terraform_owned_queue_and_bucket `
  test/test_aws_pilot_infrastructure.py::test_deploy_resolves_aws_vision_terraform_outputs_before_ssm `
  -q
```

Expected: 2 passed.

- [ ] **Step 10: Commit Task 1**

```powershell
git add test/test_aws_pilot_infrastructure.py deploy/aws-pilot/Vision-Runtime.ps1 infra/terraform-pilot/outputs.tf deploy/aws-pilot/Deploy-Pilot.ps1
git commit -m "feat: wire AWS vision runtime outputs"
```

---

### Task 2: Fail closed before SSM mutation

**Files:**
- Modify: `test/test_aws_pilot_infrastructure.py`
- Modify: `deploy/aws-pilot/Vision-Runtime.ps1`

**Interfaces:**
- Consumes: `Set-AwsVisionRuntimeValues(...) -> string` from Task 1.
- Produces: observable non-zero PowerShell results for malformed HTTPS FIFO URLs, missing worker outputs, and non-positive AWS timeout or polling values; byte-for-byte pass-through for non-AWS providers.

- [ ] **Step 1: Write the failing pass-through and invalid-input behavior tests**

Add `import pytest`, then add:

```python
def test_non_aws_vision_runtime_is_unchanged() -> None:
    content = "VISION_RUNTIME_PROVIDER=runpod\nRUNPOD_VISION_ENDPOINT_ID=endpoint-1\n"
    completed = _run_vision_runtime(content, provider="runpod")
    assert _decoded_vision_runtime(completed) == content


@pytest.mark.parametrize(
    ("overrides", "error_fragment"),
    (
        ({"queue_url": "http://sqs.invalid/not-fifo"}, "HTTPS FIFO queue URL"),
        ({"result_bucket": ""}, "result bucket"),
        ({"worker_instance_id": ""}, "worker instance ID"),
        ({"worker_repository_url": ""}, "worker ECR repository URL"),
    ),
)
def test_aws_vision_runtime_rejects_missing_or_malformed_worker_outputs(
    overrides: dict[str, str],
    error_fragment: str,
) -> None:
    parameters = {
        "provider": "aws_queue",
        "queue_url": "https://sqs.ap-northeast-2.amazonaws.com/123456789012/skn27-vision.fifo",
        "result_bucket": "skn27-clean-results",
        "worker_instance_id": "i-0123456789abcdef0",
        "worker_repository_url": "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/skn27/vision-worker",
    }
    parameters.update(overrides)
    content = "\n".join(
        (
            "VISION_RUNTIME_PROVIDER=aws_queue",
            "AWS_VISION_QUEUE_URL=",
            "AWS_VISION_RESULT_BUCKET=",
            "AWS_VISION_RESULT_PREFIX=vision/aws-queue/v1",
            "AWS_VISION_TIMEOUT_SECONDS=900",
            "AWS_VISION_POLL_INTERVAL_SECONDS=2",
            "",
        )
    )

    completed = _run_vision_runtime(content, **parameters)

    assert completed.returncode != 0
    assert error_fragment in completed.stderr


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("AWS_VISION_TIMEOUT_SECONDS", "0"),
        ("AWS_VISION_POLL_INTERVAL_SECONDS", "-1"),
        ("AWS_VISION_TIMEOUT_SECONDS", "not-a-number"),
    ),
)
def test_aws_vision_runtime_rejects_non_positive_polling_values(
    name: str,
    value: str,
) -> None:
    content = "\n".join(
        (
            "VISION_RUNTIME_PROVIDER=aws_queue",
            "AWS_VISION_QUEUE_URL=",
            "AWS_VISION_RESULT_BUCKET=",
            "AWS_VISION_RESULT_PREFIX=vision/aws-queue/v1",
            f"AWS_VISION_TIMEOUT_SECONDS={value if name == 'AWS_VISION_TIMEOUT_SECONDS' else '900'}",
            f"AWS_VISION_POLL_INTERVAL_SECONDS={value if name == 'AWS_VISION_POLL_INTERVAL_SECONDS' else '2'}",
            "",
        )
    )
    completed = _run_vision_runtime(
        content,
        provider="aws_queue",
        queue_url="https://sqs.ap-northeast-2.amazonaws.com/123456789012/skn27-vision.fifo",
        result_bucket="skn27-clean-results",
        worker_instance_id="i-0123456789abcdef0",
        worker_repository_url="123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/skn27/vision-worker",
    )

    assert completed.returncode != 0
    assert f"AWS Vision runtime value '{name}' must be a positive number." in completed.stderr
```

- [ ] **Step 2: Run the new behavior tests and verify RED**

Run:

```powershell
python -m pytest `
  test/test_aws_pilot_infrastructure.py::test_non_aws_vision_runtime_is_unchanged `
  test/test_aws_pilot_infrastructure.py::test_aws_vision_runtime_rejects_missing_or_malformed_worker_outputs `
  test/test_aws_pilot_infrastructure.py::test_aws_vision_runtime_rejects_non_positive_polling_values `
  -q
```

Expected: pass-through passes, while seven invalid AWS cases FAIL because validation is missing.

- [ ] **Step 3: Add minimal validation to the pure helper**

Before transforming AWS values in `Set-AwsVisionRuntimeValues`, validate:

```powershell
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
```

- [ ] **Step 4: Run all Task 1 and Task 2 behavior tests and verify GREEN**

Run:

```powershell
python -m pytest test/test_aws_pilot_infrastructure.py -q
```

Expected: the complete infrastructure test file passes, including all real PowerShell executions.

- [ ] **Step 5: Parse both PowerShell files without executing deployment**

Run:

```powershell
pwsh -NoProfile -Command '$errors = @(); foreach ($path in @("deploy/aws-pilot/Vision-Runtime.ps1", "deploy/aws-pilot/Deploy-Pilot.ps1")) { [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path $path), [ref]$null, [ref]$errors) > $null }; if ($errors.Count) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }'
```

Expected: exit code 0 and no parser errors.

- [ ] **Step 6: Commit Task 2**

```powershell
git add test/test_aws_pilot_infrastructure.py deploy/aws-pilot/Vision-Runtime.ps1
git commit -m "fix: fail closed on invalid AWS vision wiring"
```

---

### Task 3: Document the production AWS provider contract

**Files:**
- Modify: `test/test_deployment_readiness_artifacts.py:285-349`
- Modify: `.env.production.example:85-99`
- Modify: `deploy/aws-pilot/runtime.env.example:53-74`
- Modify: `docs/ops/vision-media-adapter-runbook.md`

**Interfaces:**
- Consumes: runtime variable names implemented by `AwsVisionQueueConfig.from_environment()` and generated by `Set-AwsVisionRuntimeValues`.
- Produces: complete secret-free environment templates and an operator runbook for selecting, activating, observing, and rolling back `aws_queue`.

- [ ] **Step 1: Write the failing readiness-artifact test**

Add this test to `test/test_deployment_readiness_artifacts.py`:

```python
def test_aws_queue_vision_runtime_templates_are_complete_and_secret_free():
    required_keys = {
        "AWS_VISION_QUEUE_URL",
        "AWS_VISION_RESULT_BUCKET",
        "AWS_VISION_RESULT_PREFIX",
        "AWS_VISION_TIMEOUT_SECONDS",
        "AWS_VISION_POLL_INTERVAL_SECONDS",
    }
    for relative_path in (
        ".env.production.example",
        "deploy/aws-pilot/runtime.env.example",
    ):
        content = read_text(ROOT / relative_path)
        keys = {
            line.split("=", 1)[0]
            for line in content.splitlines()
            if line and not line.startswith("#") and "=" in line
        }
        assert required_keys.issubset(keys), required_keys - keys
        assert "https://sqs." not in content
        assert "arn:aws:" not in content

```

The environment templates are executable configuration inputs, so their key
contract is tested. Do not add brittle assertions for individual runbook prose;
review that human-facing document directly in Step 5.

- [ ] **Step 2: Run the new test and verify RED**

Run:

```powershell
python -m pytest test/test_deployment_readiness_artifacts.py::test_aws_queue_vision_runtime_templates_are_complete_and_secret_free -q
```

Expected: FAIL because `.env.production.example` lacks the AWS variables.

- [ ] **Step 3: Extend the production environment template**

After the existing RunPod block in `.env.production.example`, add exactly these secret-free values:

```dotenv

# Optional private AWS GPU Vision queue. Deploy-Pilot.ps1 overwrites the queue
# URL and result bucket from Terraform outputs when aws_queue is selected.
AWS_VISION_QUEUE_URL=
AWS_VISION_RESULT_BUCKET=
AWS_VISION_RESULT_PREFIX=vision/aws-queue/v1
AWS_VISION_TIMEOUT_SECONDS=900
AWS_VISION_POLL_INTERVAL_SECONDS=2
```

Keep `VISION_RUNTIME_PROVIDER=runpod` in the example so cloning the repository cannot imply that paid AWS infrastructure already exists.

- [ ] **Step 4: Clarify generated values in the Pilot runtime template**

Replace the AWS comment in `deploy/aws-pilot/runtime.env.example` with:

```dotenv
# Optional private AWS GPU Vision queue. After a separately approved Terraform
# apply with vision_worker_enabled=true, select VISION_RUNTIME_PROVIDER=aws_queue.
# Deploy-Pilot.ps1 overwrites the queue URL and result bucket from Terraform
# outputs; do not copy environment-specific identifiers into this template.
```

Keep the five existing `AWS_VISION_*` lines unchanged and empty where they contain generated identifiers.

- [ ] **Step 5: Add the AWS operations section to the runbook**

Append an `AWS 온디맨드 GPU 전환` section to `docs/ops/vision-media-adapter-runbook.md` containing these concrete procedures:

```markdown
## AWS 온디맨드 GPU 전환

AWS 경로는 `VISION_RUNTIME_PROVIDER=aws_queue`를 사용하며, SQS FIFO 요청과
`vision/aws-queue/v1` S3 결과를 통해 Supervisor handoff를 교환합니다. GPU는
승인된 `g5.xlarge`만 사용합니다.

### 활성화 선행 조건

1. GPU-ready AMI, immutable Vision ECR tag, 준비된 모델 볼륨, 허용 S3 host,
   예산 승인을 검토합니다.
2. 별도 승인된 Terraform plan에서 `vision_registry_enabled=true`,
   `vision_worker_enabled=true`를 설정합니다.
3. `terraform apply` 후 `vision_worker_queue_url`,
   `vision_worker_result_bucket_name`, `vision_worker_instance_id`,
   `vision_worker_ecr_repository_url`이 모두 생성됐는지 확인합니다.
4. 저장소 밖 runtime env에서 `VISION_RUNTIME_PROVIDER=aws_queue`를 선택합니다.
5. `Deploy-Pilot.ps1`가 Terraform 출력으로 queue URL과 result bucket을
   덮어쓰고 SSM을 갱신하도록 배포합니다.

### 관찰과 복구

- SQS visible/in-flight message 수, DLQ, GPU EC2 상태, Vision Worker CloudWatch
  log, `vision_remote_*` 오류 코드를 함께 확인합니다.
- cold start를 포함해 `AWS_VISION_TIMEOUT_SECONDS=900`을 기본값으로 사용합니다.
- 큐가 비었는데 EC2가 계속 실행되면 idle-stop Lambda와 EventBridge 규칙을
  확인한 뒤 수동 중지 여부를 승인받습니다.
- 롤백 시 이전 SSM runtime env를 복원합니다. `aws_queue`를 사용하는 release가
  남아 있는 동안 queue, result prefix, GPU worker를 제거하지 않습니다.

실제 Terraform apply, ECR push, 비식별 실영상 GPU smoke, GPU 비용 발생은 각각
별도 승인이 필요합니다.
```

Retain the existing RunPod operations section as a compatibility path.
Review the rendered section directly for the activation, observation, recovery,
rollback, and separate-approval procedures; prose is not treated as executable
test behavior.

- [ ] **Step 6: Run the focused documentation test and verify GREEN**

Run:

```powershell
python -m pytest test/test_deployment_readiness_artifacts.py::test_aws_queue_vision_runtime_templates_are_complete_and_secret_free -q
```

Expected: PASS.

- [ ] **Step 7: Run all deployment artifact and AWS Pilot contract tests**

Run:

```powershell
python -m pytest test/test_deployment_readiness_artifacts.py test/test_aws_pilot_infrastructure.py -q
```

Expected: PASS with no committed identifiers detected.

- [ ] **Step 8: Commit Task 3**

```powershell
git add test/test_deployment_readiness_artifacts.py .env.production.example deploy/aws-pilot/runtime.env.example docs/ops/vision-media-adapter-runbook.md
git commit -m "docs: add AWS vision activation contract"
```

---

### Task 4: Run the integrated regression and static validation gates

**Files:**
- Verify only; no planned production file changes.

**Interfaces:**
- Consumes: Terraform output, deployment runtime, queue client, worker, adapter, Supervisor routing, and documentation contracts from Tasks 1-3.
- Produces: reproducible verification evidence showing the repository is activation-ready without creating AWS resources.

- [ ] **Step 1: Run the complete targeted Python regression**

Run:

```powershell
python -m pytest `
  test/test_aws_vision_queue_client.py `
  test/test_aws_vision_worker.py `
  test/test_aws_vision_worker_infrastructure.py `
  test/test_vision_media_analysis_adapter.py `
  test/test_aws_pilot_infrastructure.py `
  test/test_deployment_readiness_artifacts.py `
  test/test_chat_orchestration_service.py::test_blackbox_video_uses_partial_evidence_plan_without_a_report `
  test/test_supervisor_plan_execution.py::test_blackbox_video_e2e_executes_vision_case_and_law_adapter_boundaries `
  -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Parse the final PowerShell deployment script**

Run:

```powershell
pwsh -NoProfile -Command '$errors = $null; [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path "deploy/aws-pilot/Deploy-Pilot.ps1"), [ref]$null, [ref]$errors) > $null; if ($errors.Count) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }'
```

Expected: exit code 0 and no parser errors.

- [ ] **Step 3: Check Terraform formatting**

Run:

```powershell
terraform -chdir=infra/terraform-pilot fmt -check
```

Expected: exit code 0 with no files requiring formatting. If Terraform is not installed, record that exact limitation and rely on the passing static infrastructure tests; do not install tools or access the network without approval.

- [ ] **Step 4: Validate Terraform configuration when initialized providers are available**

Run:

```powershell
terraform -chdir=infra/terraform-pilot validate
```

Expected: `Success! The configuration is valid.` If local provider plugins are absent, record the exact initialization limitation and do not run `terraform init` without network approval.

- [ ] **Step 5: Check the final diff and repository state**

Run:

```powershell
git diff --check
git status --short --branch
git log -4 --oneline
```

Expected: no whitespace errors, only intentional task commits after the design and plan commits, and no untracked runtime or secret files.

- [ ] **Step 6: Record final verification without a no-op commit**

Do not create a verification-only commit when Step 5 is clean. Report:

- exact tests passed;
- PowerShell parse result;
- Terraform format/validate result or exact local-tool limitation;
- confirmation that no Terraform apply, AWS mutation, paid GPU operation, or live video submission occurred.

---

## Plan Self-Review Mapping

- Design Sections 5.1 and 5.2 are covered by Tasks 1 and 2.
- Design Sections 5.3 and 6 are covered by existing behavioral tests plus Tasks 2 and 4.
- Design Section 7 is preserved by conditional Terraform outputs, generated non-secret values, existing IAM tests, and the no-apply global constraint.
- Design Section 8 maps exactly to the File Map and Tasks 1-3.
- Design Sections 9 and 10 are covered by every RED/GREEN step and Task 4.
- Local and RunPod compatibility is protected because `Set-AwsVisionRuntimeValues` returns unchanged content for every provider except `aws_queue`.
- Live infrastructure activation remains outside this plan and cannot occur through any listed command.
