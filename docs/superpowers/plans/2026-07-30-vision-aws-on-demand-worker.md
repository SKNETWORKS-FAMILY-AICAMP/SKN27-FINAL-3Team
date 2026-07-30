# 온디맨드 AWS Vision GPU Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** RunPod 외부 호출과 호환되는 AWS 비동기 Vision worker provider 및 유휴 GPU 정지 인프라를 추가한다.

**Architecture:** provider는 큐 제출·결과 polling만 수행한다. private GPU worker는 SQS를 poll해 기존 handoff를 만들고, controller가 작업 발생 시 EC2를 시작하고 idle 시 정상 중지한다.

**Tech Stack:** Django, SQS, Lambda, EC2 GPU, Terraform, Docker, pytest.

## Global Constraints

- RunPod provider 동작을 변경하지 않는다.
- signed URL, S3 key, local path, secret은 반환값·로그에 포함하지 않는다.
- GPU 인스턴스 실제 생성은 `vision_worker_enabled=false` 기본값을 명시적으로 true로 바꾸고 Terraform apply를 승인한 경우만 가능하다.

---

### Task 1: AWS queue provider contract

**Files:**
- Create: `app/services/aws_vision_queue_client.py`
- Modify: `app/services/vision_media_analysis_adapter.py`
- Test: `test/test_aws_vision_queue_client.py`

- [ ] **Step 1: Write failing client tests**

```python
def test_submit_reuses_execution_id_and_returns_safe_pending_status():
    result = client.submit(request)
    assert result == {"status": "queued", "execution_id": "exec_1"}
```

- [ ] **Step 2: Run focused test and verify failure**

Run: `python -m pytest -q test/test_aws_vision_queue_client.py`

- [ ] **Step 3: Implement provider port**

Add `VISION_RUNTIME_PROVIDER=aws_queue`; validate the same signed HTTPS request contract as RunPod; deduplicate by execution id; poll a safe result record until timeout.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest -q test/test_aws_vision_queue_client.py test/test_vision_media_analysis_adapter.py`

### Task 2: GPU worker queue runner

**Files:**
- Create: `deploy/aws-vision/worker.py`
- Create: `deploy/aws-vision/Dockerfile`
- Create: `deploy/aws-vision/requirements.txt`
- Test: `test/test_aws_vision_worker.py`

- [ ] **Step 1: Write failing worker tests**

```python
def test_worker_deletes_message_only_after_safe_handoff_persisted():
    assert worker.process(message) == "acknowledged"
```

- [ ] **Step 2: Run focused test and verify failure**

Run: `python -m pytest -q test/test_aws_vision_worker.py`

- [ ] **Step 3: Implement private worker**

Reuse `ai.vision.runpod_worker.run_worker_job` as the computation boundary; read one SQS message at a time; write safe handoff status to a dedicated result table/object; acknowledge only after persistence.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest -q test/test_aws_vision_worker.py test/test_runpod_vision_worker.py`

### Task 3: Disabled-by-default AWS infrastructure

**Files:**
- Create: `infra/terraform-pilot/vision_worker.tf`
- Modify: `infra/terraform-pilot/iam.tf`
- Modify: `infra/terraform-pilot/variables.tf`
- Modify: `infra/terraform-pilot/outputs.tf`
- Test: `test/test_aws_vision_worker_infrastructure.py`

- [ ] **Step 1: Write failing infrastructure tests**

```python
assert 'vision_worker_enabled' in variables
assert 'default = false' in variables
assert 'aws_sqs_queue' in terraform
assert 'aws_lambda_function' in terraform
assert 'aws_instance' in terraform
```

- [ ] **Step 2: Run test and verify failure**

Run: `python -m pytest -q test/test_aws_vision_worker_infrastructure.py`

- [ ] **Step 3: Implement queue, controller, and GPU host declarations**

Create queue/DLQ, least-privilege controller roles, start-on-message Lambda, scheduled idle-stop Lambda, and one private GPU EC2 resource gated by `vision_worker_enabled`.

- [ ] **Step 4: Validate and commit**

Run: `terraform -chdir=infra/terraform-pilot fmt -check`

Run: `python -m pytest -q test/test_aws_vision_queue_client.py test/test_aws_vision_worker.py test/test_aws_vision_worker_infrastructure.py`

Commit: `feat: add on-demand AWS vision worker`
