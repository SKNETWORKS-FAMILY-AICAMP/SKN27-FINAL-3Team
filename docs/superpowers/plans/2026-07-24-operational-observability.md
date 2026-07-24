# Operational Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 분석 큐·Worker·외부 공급자·법령 데이터 갱신 상태를 개인정보 없는 `operational_health.v1` snapshot으로 집계하고 CloudWatch 알람과 운영 runbook에 연결한다.

**Architecture:** Django ORM 기반의 순수 snapshot service가 운영 상태를 계산하고 관리 명령이 단발 또는 반복 JSON 로그를 출력한다. 파일럿 Compose의 전용 `ops-monitor` 서비스만 비차단 CloudWatch Logs driver를 사용하며 Terraform metric filter와 alarm이 snapshot 숫자를 관측한다.

**Tech Stack:** Python 3.11, Django ORM, PostgreSQL, Docker Compose, Terraform AWS provider 6.x, CloudWatch Logs/Metrics/Alarms, SNS, pytest

## Global Constraints

- 새 DB migration과 새 Python 패키지를 추가하지 않는다.
- 애플리케이션에서 AWS API를 직접 호출하지 않는다.
- 사용자 식별자, 질문, 첨부 파일명·경로, OCR 결과, prompt, secret, signed URL, provider 원문 오류를 snapshot과 로그에 포함하지 않는다.
- `operational_alert_email`은 선택값이며 저장소에 실제 주소를 커밋하지 않는다.
- 임계값은 파일럿 초기값이고 실제 운영 부하 검증 전에는 최종값으로 주장하지 않는다.
- 기존 `legal_ingestion_run_summary.v2`와 `evaluate_run_summary()`를 재사용한다.

---

### Task 1: 운영 상태 snapshot 계약

**Files:**
- Create: `backend/chatbot/operational_observability.py`
- Create: `backend/chatbot/test_operational_observability.py`

**Interfaces:**
- Consumes: `chatbot.models.AgentWorkItem`, `chatbot.models.AgentInvocation`, `etl.legal.validate_run_summary.evaluate_run_summary`
- Produces: `build_operational_health_snapshot(*, observed_at: datetime | None = None, window_minutes: int = 15, queue_age_warn_seconds: int = 300, lease_stale_seconds: int = 300, legal_run_summary_path: str = "", legal_max_age_hours: int = 168, legal_required_sources: list[str] | None = None) -> dict[str, Any]`

- [ ] **Step 1: 빈 큐 snapshot의 실패 테스트 작성**

```python
def test_empty_operational_snapshot_is_safe_and_passes(self):
    snapshot = build_operational_health_snapshot(
        observed_at=self.now,
        legal_run_summary_path="",
    )
    self.assertEqual(snapshot["contract_version"], "operational_health.v1")
    self.assertEqual(snapshot["event_type"], "operational_health")
    self.assertEqual(snapshot["status"], "pass")
    self.assertEqual(snapshot["queue"]["queued_count"], 0)
    self.assertEqual(snapshot["alerts"], [])
```

- [ ] **Step 2: RED 확인**

Run:
`python -m pytest -q backend/chatbot/test_operational_observability.py::OperationalObservabilityTests::test_empty_operational_snapshot_is_safe_and_passes`

Expected: `ModuleNotFoundError: No module named 'chatbot.operational_observability'`

- [ ] **Step 3: 최소 snapshot 뼈대 구현**

```python
HEALTH_CONTRACT_VERSION = "operational_health.v1"

def build_operational_health_snapshot(...):
    now = observed_at or timezone.now()
    return {
        "contract_version": HEALTH_CONTRACT_VERSION,
        "event_type": "operational_health",
        "observed_at": now.astimezone(datetime_timezone.utc).isoformat(),
        "status": "pass",
        "queue": {
            "queued_count": 0,
            "oldest_queued_age_seconds": 0,
            "running_count": 0,
            "stale_running_count": 0,
        },
        "worker": {
            "retrying_count": 0,
            "recent_failure_count": 0,
            "recent_timeout_count": 0,
        },
        "providers": {"recent_failure_count": 0, "roles": {}},
        "legal_data": {"status": "not_configured"},
        "alerts": [],
    }
```

- [ ] **Step 4: GREEN 확인**

Run: `python -m pytest -q backend/chatbot/test_operational_observability.py`

Expected: `1 passed`

- [ ] **Step 5: queued·running·retry 집계 실패 테스트 작성**

테스트 fixture는 `ChatSession`, `AnalysisJob`, `AgentWorkItem`을 만들고
`created_at`, `locked_at`, `next_run_at`을 명시적으로 갱신한다. 다음을 각각
검증한다.

```python
self.assertEqual(snapshot["queue"]["queued_count"], 2)
self.assertGreaterEqual(snapshot["queue"]["oldest_queued_age_seconds"], 600)
self.assertEqual(snapshot["queue"]["stale_running_count"], 1)
self.assertEqual(snapshot["worker"]["retrying_count"], 1)
self.assertEqual(
    [item["code"] for item in snapshot["alerts"]],
    ["queue_backlog", "queue_oldest_age_exceeded", "worker_lease_stale", "worker_retrying"],
)
```

- [ ] **Step 6: RED 확인 후 ORM 집계 구현**

Run: `python -m pytest -q backend/chatbot/test_operational_observability.py -k "queue or running or retry"`

Expected: queue 관련 수치가 0이라 assertion failure

구현은 `AgentWorkItemStatus`별 queryset과 UTC 시간 차이만 사용한다.
snapshot에는 work item ID나 job ID를 포함하지 않는다.

- [ ] **Step 7: Worker·provider 실패 분류 테스트와 구현**

관측 구간 내 `FAILED` work item과 `FAILED`/`PARTIAL` invocation을 생성한다.
오류는 아래 허용된 범주로만 집계한다.

```python
SAFE_PROVIDER_ROLES = {
    "supervisor_llm",
    "ocr",
    "vision",
    "legal",
    "case_search",
    "unknown",
}
TIMEOUT_MARKERS = {"timeout", "timedout", "deadline"}
```

임의 오류 문자열과 사용자 PII를 metadata에 넣은 뒤 snapshot 직렬화 문자열에
나타나지 않는 것을 검증한다.

- [ ] **Step 8: 법령 freshness 테스트와 구현**

임시 `run_summary.json`에 `legal_ingestion_run_summary.v2` fixture를 쓰고
`evaluate_run_summary()` 결과를 다음 형태로 축약한다.

```python
{
    "status": "success" | "failed" | "missing" | "invalid",
    "dataset_version": "...",
    "missing_source_count": 0,
    "failed_source_count": 0,
    "stale_source_count": 0,
}
```

파일 없음은 `legal_data_missing`, stale은 `legal_data_stale`, failed source는
`legal_data_refresh_failed`, JSON/schema 오류는
`monitor_configuration_invalid`를 만든다. 경로와 source ID는 snapshot에
포함하지 않는다.

- [ ] **Step 9: Task 1 전체 테스트와 정적 검사**

Run:

```text
python -m pytest -q backend/chatbot/test_operational_observability.py
python -m ruff check backend/chatbot/operational_observability.py backend/chatbot/test_operational_observability.py
```

Expected: all tests pass, `All checks passed!`

- [ ] **Step 10: 커밋**

```text
git add backend/chatbot/operational_observability.py backend/chatbot/test_operational_observability.py
git commit -m "feat: add safe operational health snapshot"
```

---

### Task 2: 운영 관측 관리 명령

**Files:**
- Create: `backend/chatbot/management/commands/observe_operational_health.py`
- Modify: `backend/chatbot/test_operational_observability.py`
- Modify: `backend/config/settings.py`
- Modify: `.env.example`
- Modify: `.env.production.example`
- Modify: `deploy/aws-pilot/runtime.env.example`

**Interfaces:**
- Consumes: `build_operational_health_snapshot()`
- Produces: `python backend/manage.py observe_operational_health [--loop] [--interval-seconds N] [--once]`

- [ ] **Step 1: 단발 JSON 명령 실패 테스트 작성**

```python
def test_observe_command_prints_one_compact_json_line(self):
    stdout = StringIO()
    call_command("observe_operational_health", "--once", stdout=stdout)
    lines = stdout.getvalue().splitlines()
    self.assertEqual(len(lines), 1)
    self.assertEqual(json.loads(lines[0])["contract_version"], "operational_health.v1")
```

- [ ] **Step 2: RED 확인**

Run:
`python -m pytest -q backend/chatbot/test_operational_observability.py -k command`

Expected: `Unknown command: 'observe_operational_health'`

- [ ] **Step 3: 최소 명령 구현**

명령은 기본 단발 실행이다. `--loop`에서만 `time.sleep()` 후 반복한다.
`--interval-seconds`는 10 이상, `--window-minutes`,
`--queue-age-warn-seconds`, `--lease-stale-seconds`,
`--legal-max-age-hours`는 양수만 허용한다. `KeyboardInterrupt`는 정상 종료한다.
snapshot 생성 예외는 원문 예외를 출력하지 않고 아래 안전한 한 줄을 출력한다.

```python
{
    "contract_version": "operational_health.v1",
    "event_type": "operational_health",
    "status": "fail",
    "alerts": [{"code": "monitor_configuration_invalid", "severity": "critical"}],
}
```

- [ ] **Step 4: 설정 배선**

다음 환경 설정을 `backend/config/settings.py`에서 정수/목록으로 읽는다.

```text
OPERATIONAL_HEALTH_INTERVAL_SECONDS=60
OPERATIONAL_HEALTH_WINDOW_MINUTES=15
OPERATIONAL_QUEUE_AGE_WARN_SECONDS=300
OPERATIONAL_LEASE_STALE_SECONDS=300
OPERATIONAL_LEGAL_RUN_SUMMARY_PATH=
OPERATIONAL_LEGAL_MAX_AGE_HOURS=168
OPERATIONAL_LEGAL_REQUIRED_SOURCES=
```

예제 파일에는 실제 경로, source 또는 이메일을 넣지 않는다.

- [ ] **Step 5: 반복 모드와 안전한 예외 테스트**

`mock.patch("...time.sleep", side_effect=KeyboardInterrupt)`로 한 번 출력 후
종료되는지 확인한다. 서비스가 임의 `RuntimeError("secret...")`를 내도록
patch하고 출력에 예외 원문이 없으며 안전 코드만 있는지 확인한다.

- [ ] **Step 6: Task 2 검증과 커밋**

Run:

```text
python -m pytest -q backend/chatbot/test_operational_observability.py
python backend/manage.py observe_operational_health --once
```

Expected: tests pass; 명령은 compact JSON 한 줄 출력

Commit:

```text
git add backend/chatbot/management/commands/observe_operational_health.py backend/chatbot/test_operational_observability.py backend/config/settings.py .env.example .env.production.example deploy/aws-pilot/runtime.env.example
git commit -m "feat: add operational health monitor command"
```

---

### Task 3: Compose와 CloudWatch 알람

**Files:**
- Modify: `test/test_aws_pilot_infrastructure.py`
- Modify: `deploy/aws-pilot/docker-compose.pilot.yml`
- Modify: `deploy/aws-pilot/Deploy-Pilot.ps1`
- Modify: `infra/terraform-pilot/variables.tf`
- Modify: `infra/terraform-pilot/iam.tf`
- Modify: `infra/terraform-pilot/outputs.tf`
- Modify: `infra/terraform-pilot/terraform.tfvars.example`
- Create: `infra/terraform-pilot/observability.tf`

**Interfaces:**
- Consumes: `ops-monitor` JSON stdout fields
- Produces: CloudWatch Log Group, metric namespace `SKN27/Pilot`, 여섯 metric filters와 alarms, SNS topic, optional email subscription

- [ ] **Step 1: 인프라 계약 실패 테스트 작성**

테스트는 다음을 요구한다.

```python
assert "ops-monitor" in services
assert services["ops-monitor"]["command"] == [
    "python", "backend/manage.py", "observe_operational_health",
    "--loop", "--interval-seconds", "60",
]
assert services["ops-monitor"]["logging"]["driver"] == "awslogs"
assert services["ops-monitor"]["logging"]["options"]["mode"] == "non-blocking"
assert 'resource "aws_cloudwatch_log_group" "operational_health"' in source
assert 'resource "aws_cloudwatch_log_metric_filter" "queue_oldest_age"' in source
assert 'resource "aws_sns_topic" "operational_alerts"' in source
assert 'count = var.operational_alert_email == "" ? 0 : 1' in source
```

IAM에는 `logs:CreateLogStream`, `logs:PutLogEvents`만 허용하고
전용 Log Group ARN으로 resource를 제한해야 한다.

- [ ] **Step 2: RED 확인**

Run:
`python -m pytest -q test/test_aws_pilot_infrastructure.py -k operational`

Expected: `ops-monitor` 또는 `observability.tf` 부재로 실패

- [ ] **Step 3: Compose monitor 서비스 구현**

`ops-monitor`는 backend image/env를 재사용하고 `backend` health 후 시작한다.
64MiB memory limit, read-only root, `/tmp` tmpfs, 외부 port 없음,
`restart: unless-stopped`를 적용한다. CloudWatch driver option은 다음과 같다.

```yaml
driver: awslogs
options:
  awslogs-region: ${AWS_REGION:?AWS_REGION is required}
  awslogs-group: ${OPERATIONAL_LOG_GROUP:?OPERATIONAL_LOG_GROUP is required}
  awslogs-stream: ops-monitor
  awslogs-create-group: "false"
  mode: non-blocking
  max-buffer-size: 1m
```

- [ ] **Step 4: Terraform Log Group·metric filter 구현**

`observability.tf`는 30일 보존, KMS 기본 암호화, destroy 시 삭제 가능한
파일럿 Log Group을 만든다. JSON metric filter는 heartbeat,
`oldest_queued_age_seconds`, `stale_running_count`,
`recent_failure_count`, `providers.recent_failure_count`,
법령 실패 합계를 `SKN27/Pilot` namespace로 변환한다.

- [ ] **Step 5: Terraform alarm·SNS 구현**

초기 변수값은 설계 문서와 동일하다. `operational_alert_email` 기본값은 빈
문자열이며 실제 주소를 예제에 넣지 않는다. 이메일 subscription만 조건부이고
topic과 alarm은 항상 생성한다. 알람 action은 topic ARN에 연결한다.

- [ ] **Step 6: Terraform output과 배포 compose env 연결**

다음 non-secret output을 추가한다.

```text
operational_log_group_name
operational_alert_topic_arn
```

배포 스크립트가 Terraform output에서 Log Group 이름과 region을 읽어
`.compose.env`에 기록하는 계약을 추가한다. 이메일은 Terraform 변수로만
처리하며 `.compose.env`에 복사하지 않는다.

- [ ] **Step 7: 인프라 검증과 커밋**

Run:

```text
python -m pytest -q test/test_aws_pilot_infrastructure.py
terraform -chdir=infra/terraform-pilot fmt -check
terraform -chdir=infra/terraform-pilot init -backend=false -input=false
terraform -chdir=infra/terraform-pilot validate
```

Expected: all tests pass, Terraform configuration valid

Commit:

```text
git add test/test_aws_pilot_infrastructure.py deploy/aws-pilot/docker-compose.pilot.yml deploy/aws-pilot/Deploy-Pilot.ps1 infra/terraform-pilot
git commit -m "feat: connect operational health to CloudWatch"
```

---

### Task 4: Runbook, 체크리스트와 전체 검증

**Files:**
- Create: `docs/ops/operational-observability-runbook.md`
- Modify: `docs/ops/project-readiness-master-checklist.md`
- Modify: `docs/ops/release-checklist.md`
- Modify: `docs/superpowers/reports/2026-07-23-release-readiness-integration-verification.md`
- Modify: `test/test_deployment_readiness_artifacts.py`

**Interfaces:**
- Consumes: alert codes, management command, Terraform outputs
- Produces: alert → 확인 → 완화 → 복구 확인 표와 사람 승인 게이트

- [ ] **Step 1: runbook 계약 실패 테스트 작성**

각 안전 코드와 다음 운영 명령이 문서에 존재하는지 검증한다.

```text
observe_operational_health --once
show_analysis_job_provenance --job-id
queue_backlog
queue_oldest_age_exceeded
worker_lease_stale
worker_failure
worker_timeout
provider_failure
legal_data_missing
legal_data_stale
legal_data_refresh_failed
monitor_configuration_invalid
```

문서는 SNS 확인 링크 클릭, 실제 이메일 비커밋, 실제 부하 후 threshold 승인,
알람 복구 확인 절차를 포함한다.

- [ ] **Step 2: RED 확인 후 runbook 작성**

Run:
`python -m pytest -q test/test_deployment_readiness_artifacts.py -k observability`

Expected: runbook 부재로 실패

- [ ] **Step 3: 체크리스트 증적 갱신**

다음 항목은 `[~]`로 유지하되 코드 증적과 사람 게이트를 분리한다.

- 외부 서비스 장애·데이터 갱신 실패·큐 적체의 운영 관측
- 실제 부하 수치와 CloudWatch 임계값
- #299 성공·부분 실패·실패 trace
- 운영 이메일·SNS subscription 확인

RunPod Serverless Vision 연결은 별도 후속 브랜치에서 제공된
`2026-07-23-runpod-serverless-vision-design.md` 기준으로 구현 예정임을
E-6과 I 항목에 기록한다. 구현 전에는 실제 연결 완료로 표시하지 않는다.

- [ ] **Step 4: 전체 검증**

Run:

```text
python -m pytest -q test
python -m pytest -q backend/chatbot/test_operational_observability.py backend/chatbot/test_analysis_job_provenance.py
python -m ruff check backend/chatbot/operational_observability.py backend/chatbot/management/commands/observe_operational_health.py backend/chatbot/test_operational_observability.py
npm --prefix app/web run build -- --configLoader runner
git diff --check
```

Expected: all tests/build/checks pass with no whitespace errors

- [ ] **Step 5: 검증 결과 기록과 커밋**

실제 통과한 개수와 제한 사항만 검증 보고서에 기록한다. AWS 계정에서 알람을
실제로 발생시키지 않았다면 해당 항목은 사람 게이트로 남긴다.

```text
git add docs/ops/operational-observability-runbook.md docs/ops/project-readiness-master-checklist.md docs/ops/release-checklist.md docs/superpowers/reports/2026-07-23-release-readiness-integration-verification.md test/test_deployment_readiness_artifacts.py
git commit -m "docs: add operational observability runbook"
```
