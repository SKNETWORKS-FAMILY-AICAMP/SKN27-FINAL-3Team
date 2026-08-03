# AWS Vision Runtime Wiring Design

**Date:** 2026-08-03

**Status:** Approved for implementation planning

**Target branch:** `feat-aws-vision-runtime-wiring`

## 1. Goal

Connect the existing canonical `vision_media_analysis` flow to the existing
private AWS GPU worker stack without requiring an operator to copy Terraform
outputs into the application runtime environment by hand.

The production deployment must derive the AWS Vision FIFO queue URL and result
bucket from the same Terraform state that created the worker. The deployment
must fail before updating the SSM runtime environment when that infrastructure
is absent or inconsistent.

## 2. Scope

This change includes:

- production deployment wiring for `VISION_RUNTIME_PROVIDER=aws_queue`;
- an explicit Terraform output for the Vision result bucket;
- fail-closed validation of the AWS Vision worker outputs;
- automatic generation of the AWS Vision runtime values stored in the existing
  SSM SecureString;
- AWS Vision deployment and operations documentation;
- contract and regression tests for the deployment, provider, worker, and
  blackbox-video routing path.

This change does not include:

- running `terraform apply`;
- creating or starting a paid GPU instance;
- choosing a GPU type other than the approved `g5.xlarge` pilot size;
- changing the Vision model, checkpoint format, Qwen model, or Supervisor
  handoff schema;
- removing the local or RunPod providers;
- committing AWS credentials, queue URLs, bucket names, or model artifacts.

## 3. Existing Architecture

The repository already contains the functional boundaries required for AWS
execution:

1. `vision_media_analysis_adapter.py` selects the `aws_queue` provider.
2. `aws_vision_queue_client.py` submits a deduplicated request to an SQS FIFO
   queue and polls a sanitized result object in S3.
3. `aws_vision_worker.py` consumes one message at a time, runs the existing
   Vision computation boundary, writes the safe Supervisor handoff to S3, and
   acknowledges the SQS message only after persistence.
4. `vision_worker.tf` declares the FIFO queue and DLQ, immutable ECR repository,
   private `g5.xlarge` EC2 worker, least-privilege IAM, VPC endpoints, and the
   Lambda/EventBridge start and idle-stop controllers.
5. `docker-compose.pilot.yml` passes the private `.runtime.env` file to the
   canonical Agent Worker.

The missing production connection is between the optional Terraform outputs
and the SSM runtime environment written by `Deploy-Pilot.ps1`. The current
runtime template exposes empty AWS Vision values and still defaults to RunPod.

## 4. Considered Approaches

### 4.1 Terraform outputs injected by the deployment script — selected

`Deploy-Pilot.ps1` reads the worker outputs from the already-applied Terraform
state. When the selected provider is `aws_queue`, it writes the queue URL,
result bucket, and fixed result prefix into the runtime environment before the
existing SSM SecureString update.

This preserves the current security boundary: Terraform manages infrastructure,
while the deployment script owns the complete application runtime environment.
It also prevents configuration drift between the queue the app sends to and the
worker Terraform created.

### 4.2 Manually copy values into `runtime.env`

This requires fewer code changes but permits stale queue URLs, wrong buckets,
and accidental cross-environment routing. It is rejected because a deployment
could succeed while Vision jobs are permanently unconsumable.

### 4.3 Make Terraform manage the complete runtime SSM parameter

This would centralize configuration but would also couple application secrets
to Terraform state and replace the established deployment workflow. It is
rejected because it expands secret exposure and change scope without improving
the Vision worker boundary.

## 5. Proposed Architecture

### 5.1 Terraform output contract

The pilot Terraform module will expose:

- `vision_worker_queue_url`: existing optional FIFO queue URL;
- `vision_worker_instance_id`: existing optional GPU worker instance ID;
- `vision_worker_ecr_repository_url`: existing optional immutable ECR
  repository URL;
- `vision_worker_result_bucket_name`: new optional output naming the S3 bucket
  used for `vision/aws-queue/v1/<execution_id>.json` results.

All four outputs are non-empty only when their corresponding infrastructure
gate is enabled. The result bucket output is conditional on
`vision_worker_enabled`, matching the queue and EC2 lifecycle.

### 5.2 Deployment runtime resolution

After loading Terraform outputs and before writing the SSM SecureString,
`Deploy-Pilot.ps1` will inspect `VISION_RUNTIME_PROVIDER` from the operator's
runtime template.

For `aws_queue`, the script will:

1. require non-empty queue URL, result bucket, worker instance ID, and Vision
   ECR repository outputs;
2. require an HTTPS queue URL whose path ends in `.fifo`;
3. require the result bucket to equal the Terraform-generated Vision result
   bucket output;
4. set `AWS_VISION_QUEUE_URL` from `vision_worker_queue_url`;
5. set `AWS_VISION_RESULT_BUCKET` from
   `vision_worker_result_bucket_name`;
6. set `AWS_VISION_RESULT_PREFIX=vision/aws-queue/v1`;
7. require positive `AWS_VISION_TIMEOUT_SECONDS` and
   `AWS_VISION_POLL_INTERVAL_SECONDS` values;
8. continue through the existing unresolved-template, required-value, byte-size,
   and SSM update gates only after these checks pass.

For `runpod` and `local`, the script will preserve the current behavior. No
RunPod values are copied into the AWS fields, and no AWS output is required.

The deployment script will never accept a caller-supplied AWS queue URL or
result bucket as authoritative when `aws_queue` is selected; Terraform outputs
overwrite those two values.

### 5.3 Runtime data flow

The resulting production flow is:

1. The authenticated user uploads an MP4 or MOV file.
2. The file-scan worker marks the canonical attachment clean and ready.
3. Supervisor routing maps `blackbox_video` to
   `accident_evidence_analysis` and includes `vision_media_analysis`.
4. The canonical Agent Worker selects `VISION_RUNTIME_PROVIDER=aws_queue`.
5. The adapter creates a short-lived signed HTTPS URL for the clean upload.
6. The queue client submits a deduplicated FIFO message using `execution_id`.
7. EventBridge invokes the start controller; the controller starts the stopped
   private `g5.xlarge` instance when the queue is non-empty.
8. The GPU worker downloads the signed input, runs the existing VideoMAE/Qwen
   boundary, and writes a sanitized handoff object to the result prefix.
9. The Agent Worker polls the result object and returns it to the Supervisor.
10. The idle controller stops the GPU instance after the queue has no visible or
    in-flight work.

## 6. Failure and Recovery Behavior

- If `vision_worker_enabled=false`, the queue and worker outputs are null and an
  `aws_queue` deployment fails before changing SSM.
- If the queue URL is not HTTPS or does not end in `.fifo`, deployment fails.
- If the result bucket output is missing, deployment fails.
- If the timeout or polling interval is missing, non-numeric, or non-positive,
  deployment fails.
- If a job is submitted but no result appears within the configured timeout,
  the existing stable `vision_remote_timeout` response is preserved.
- Invalid or oversized result payloads continue to return
  `vision_remote_invalid_response` without exposing AWS identifiers.
- SQS redrive remains limited to three receives before the DLQ.
- Existing SSM update and release staging remain atomic; no partial runtime
  environment is installed.
- Rollback continues to restore the previously stored runtime environment. The
  AWS worker infrastructure must not be destroyed until every release using
  `aws_queue` has been retired.

## 7. Security and Cost Controls

- The GPU EC2 instance remains private with no inbound access and no public IP.
- App IAM may only send to the declared Vision queue and read the declared
  result prefix.
- Worker IAM may only receive and acknowledge that queue, read canonical clean
  uploads, write the result prefix, pull its private ECR image, and write logs.
- Signed video URLs remain short-lived and restricted to approved S3 hosts.
- Runtime identifiers and secrets remain in SSM or AWS-generated outputs; none
  are committed.
- `vision_worker_enabled` remains `false` by default, so this code change cannot
  create paid capacity.
- Live activation requires a separate reviewed Terraform apply with an approved
  GPU-ready AMI, immutable ECR tag, prepared model volume, allowed S3 hosts, and
  budget approval.

## 8. Files and Responsibilities

- `infra/terraform-pilot/outputs.tf`: expose the explicit Vision result bucket
  output.
- `deploy/aws-pilot/Deploy-Pilot.ps1`: resolve and validate provider-specific
  runtime values before the SSM update.
- `deploy/aws-pilot/runtime.env.example`: document the AWS selection and retain
  empty non-secret placeholders.
- `.env.production.example`: expose the AWS queue provider variables for
  production-compatible local configuration.
- `docs/ops/vision-media-adapter-runbook.md`: describe AWS activation,
  observability, timeout, DLQ, and rollback procedures while preserving the
  RunPod compatibility section.
- `test/test_aws_pilot_infrastructure.py`: assert the Terraform-to-runtime
  deployment contract.
- `test/test_deployment_readiness_artifacts.py`: assert complete secret-free AWS
  production documentation.
- Existing AWS queue, worker, adapter, Supervisor, and attachment tests remain
  the behavioral regression suite.

## 9. Test Strategy

Implementation will follow test-first cycles.

1. Add a failing deployment contract test requiring the result bucket output
   and `Deploy-Pilot.ps1` consumption of every AWS Vision output.
2. Add a failing deployment contract test requiring automatic queue, bucket,
   and prefix generation plus fail-closed checks.
3. Add a failing readiness-artifact test requiring AWS provider variables and
   activation documentation in both production examples and the runbook.
4. Implement the minimal Terraform, PowerShell, example, and documentation
   changes to make each test pass.
5. Run the AWS Vision queue client, worker, adapter, infrastructure, Supervisor
   execution, blackbox routing, and deployment artifact suites together.
6. Run PowerShell syntax validation for the modified deployment script.
7. Run `terraform fmt -check` and `terraform validate` when the local Terraform
   runtime is available; otherwise retain the existing static Terraform
   contract tests and report the unavailable validation explicitly.

No live video, SQS message, ECR push, Terraform apply, or paid GPU smoke is part
of this implementation verification.

## 10. Acceptance Criteria

The implementation is complete when:

- selecting `VISION_RUNTIME_PROVIDER=aws_queue` makes deployment derive the
  queue URL and result bucket from Terraform outputs;
- deployment refuses to update SSM when the AWS worker stack is disabled or
  inconsistent;
- the runtime values used by the Agent Worker match the Terraform-managed
  queue and result bucket;
- the `g5.xlarge` worker, SQS, S3 handoff, and automatic start/stop architecture
  remain unchanged;
- RunPod and local provider behavior remains compatible;
- no credentials or environment-specific identifiers are committed;
- all targeted tests and syntax checks pass;
- actual AWS provisioning remains impossible without a separate explicit
  `vision_worker_enabled=true` Terraform apply.
