# RunPod Serverless Vision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 local Vision adapter를 보존하면서 scan-ready S3 영상을 RunPod Queue-based Serverless worker로 분석하고 안전한 Supervisor handoff로 반환한다.

**Architecture:** 표준 라이브러리 HTTP client가 `/run`과 `/status`를 담당하고, 기존 adapter가 provider와 signed URL 경계를 담당한다. 별도 RunPod worker는 다운로드·Vision pipeline·handoff 정제만 수행하며, 운영 key·Endpoint·실영상은 사람 게이트로 남긴다.

**Tech Stack:** Python 3.11+, Django cache/Redis, `urllib.request`, RunPod Python SDK `~1.7.6`, PyTorch/CUDA, pytest, Docker

## Global Constraints

- canonical scan-ready MP4/MOV만 RunPod로 보낸다.
- 영상 binary, API key, signed URL, 사용자 원문, 로컬 경로와 원문 예외를 결과·로그·DB에 남기지 않는다.
- `VISION_RUNTIME_PROVIDER=local`의 기존 subprocess 동작을 유지한다.
- RunPod `POST /run`은 문서화된 idempotency key가 없어 자동 재시도하지 않는다.
- GET polling은 전체 timeout 안에서만 제한적으로 재시도한다.
- worker는 Supervisor·법령 검색·과실비율 판단을 호출하지 않는다.
- 실제 restricted key, 유료 Endpoint, 모델 artifact와 실영상 E2E는 사람 게이트다.

---

### Task 1: 설계와 구현 계획 고정

**Files:**
- Create: `docs/superpowers/specs/2026-07-24-runpod-serverless-vision-design.md`
- Create: `docs/superpowers/plans/2026-07-24-runpod-serverless-vision.md`

**Interfaces:**
- Consumes: 사용자 제공 `2026-07-23-runpod-serverless-vision-design.md`
- Produces: provider, HTTP, worker, 보안, 완료 경계의 승인된 기준

- [ ] **Step 1: 사용자 설계와 현재 adapter/object storage 계약을 대조한다**

Run:

```powershell
rg -n "VISION_RUNTIME_PROVIDER|presign_get|_safe_worker_handoff|run_to_supervisor" app backend ai test
```

Expected: 기존 local adapter, S3 presign 함수와 handoff allowlist가 확인된다.

- [ ] **Step 2: 저장소 설계와 계획 문서를 작성한다**

설계에는 RunPod 공식 handler, `/run`·`/status`, application-level job id
reuse, signed URL 제한과 사람 게이트를 명시한다.

- [ ] **Step 3: 문서 금지 placeholder를 검사한다**

Run:

```powershell
$terms = @("T" + "BD", "T" + "ODO", "implement " + "later", "fill " + "in")
Select-String -Path docs/superpowers/specs/2026-07-24-runpod-serverless-vision-design.md,docs/superpowers/plans/2026-07-24-runpod-serverless-vision.md -Pattern $terms
```

Expected: no matches.

- [ ] **Step 4: 커밋한다**

```powershell
git add docs/superpowers/specs/2026-07-24-runpod-serverless-vision-design.md docs/superpowers/plans/2026-07-24-runpod-serverless-vision.md
git commit -m "docs: design RunPod Serverless Vision"
```

### Task 2: Queue-based RunPod HTTP client

**Files:**
- Create: `app/services/runpod_vision_client.py`
- Create: `test/test_runpod_vision_client.py`

**Interfaces:**
- Consumes: `RunPodVisionConfig.from_environment()`
- Produces: `RunPodVisionClient.run(request, existing_job_id="") -> RunPodVisionResult`
- Produces: `RunPodVisionError.code` with the five remote stable error codes

- [ ] **Step 1: status mapping과 개인정보 비노출 실패 테스트를 작성한다**

테스트 transport는 `(method, url, headers, payload, timeout)`을 받아 JSON
dict를 반환한다. 아래 동작을 각각 검증한다.

```python
client = RunPodVisionClient(config, transport=fake_transport, sleep=lambda _: None)
result = client.run({
    "schema_version": "vision-runpod-request-v1",
    "execution_id": "exec_1",
    "attachment_id": "att_1",
    "video_url": "https://signed.example/video?secret=query",
    "content_type": "video/mp4",
})
assert result.job_id == "job_1"
assert result.output["vision_supervisor_handoff"]["schema_version"] == "vision-supervisor-handoff-v1"
```

`FAILED`, `CANCELLED`, deadline, malformed job id/status/output, HTTP failure가
각각 승인된 stable code를 내고 repr에 API key와 signed query가 없음을
검증한다.

- [ ] **Step 2: RED를 확인한다**

Run:

```powershell
python -m pytest -p no:cacheprovider test/test_runpod_vision_client.py -q
```

Expected: `app.services.runpod_vision_client` import failure.

- [ ] **Step 3: 최소 client를 구현한다**

핵심 public 계약:

```python
@dataclass(frozen=True)
class RunPodVisionResult:
    job_id: str
    output: dict[str, Any]

class RunPodVisionError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code

class RunPodVisionClient:
    def run(
        self,
        request: dict[str, Any],
        *,
        existing_job_id: str = "",
    ) -> RunPodVisionResult:
        ...
```

POST는 한 번만 수행하고 job id를 받은 뒤 status를 polling한다. transport
exception과 HTTP body는 외부로 복사하지 않는다.

- [ ] **Step 4: GREEN과 Ruff를 확인한다**

```powershell
python -m pytest -p no:cacheprovider test/test_runpod_vision_client.py -q
ruff check --no-cache app/services/runpod_vision_client.py test/test_runpod_vision_client.py
```

Expected: all pass.

- [ ] **Step 5: 커밋한다**

```powershell
git add app/services/runpod_vision_client.py test/test_runpod_vision_client.py
git commit -m "feat: add RunPod Vision queue client"
```

### Task 3: 기존 Vision adapter provider 분기

**Files:**
- Modify: `app/services/vision_media_analysis_adapter.py`
- Modify: `test/test_vision_media_analysis_adapter.py`

**Interfaces:**
- Consumes: `chatbot.object_storage.presign_get(reference, ttl_seconds=...)`
- Consumes: `RunPodVisionClient.run(request, existing_job_id=...)`
- Produces: 기존 `_success()` 또는 `_failure(stable_code)` envelope

- [ ] **Step 1: runpod provider 테스트를 먼저 추가한다**

검증할 동작:

```python
monkeypatch.setenv("VISION_RUNTIME_PROVIDER", "runpod")
monkeypatch.setattr(adapter, "_presign_runpod_video", lambda _: "https://s3.example/video?sig=private")
monkeypatch.setattr(adapter, "_run_runpod_provider", fake_remote)
result = adapter.run_vision_media_analysis(_canonical_video_input(), {"execution_id": "exec_remote"})
assert result["status"] == "partial"
assert "sig=private" not in repr(result)
```

- runpod에서는 `_configured_checkpoint()`와 `_read_scan_ready_video_bytes()`를
  호출하지 않는다.
- `https`가 아닌 URL, TTL 부족, missing key/endpoint는
  `vision_remote_unavailable`이다.
- COMPLETED output에는 기존 `_safe_worker_handoff()`가 다시 적용된다.
- cache의 기존 job id를 전달하고 새 job id를 timeout보다 긴 TTL로 보존한다.
- remote error 다섯 종류는 원문 없이 동일 code로 반환한다.

- [ ] **Step 2: RED를 확인한다**

```powershell
python -m pytest -p no:cacheprovider test/test_vision_media_analysis_adapter.py -q
```

Expected: provider 분기와 helper가 없어 새 테스트가 실패한다.

- [ ] **Step 3: local 경로를 보존하며 최소 분기를 구현한다**

```python
provider = os.getenv("VISION_RUNTIME_PROVIDER", "local").strip().lower()
if provider == "local":
    return _run_local_provider(attachment, adapter_context)
if provider == "runpod":
    return _run_runpod_provider(attachment, adapter_context)
return _failure("vision_remote_unavailable")
```

RunPod request에는 schema version, safe execution/attachment id, signed URL과
content type만 포함한다.

- [ ] **Step 4: GREEN과 기존 호출자 회귀를 확인한다**

```powershell
python -m pytest -p no:cacheprovider test/test_vision_media_analysis_adapter.py test/test_agent_node_service.py test/test_supervisor_plan_execution.py -q
ruff check --no-cache app/services/vision_media_analysis_adapter.py test/test_vision_media_analysis_adapter.py
```

Expected: all pass.

- [ ] **Step 5: 커밋한다**

```powershell
git add app/services/vision_media_analysis_adapter.py test/test_vision_media_analysis_adapter.py
git commit -m "feat: route Vision analysis through RunPod"
```

### Task 4: RunPod worker와 안전한 handoff

**Files:**
- Create: `ai/vision/runpod_worker.py`
- Create: `test/test_runpod_vision_worker.py`
- Create: `deploy/runpod-vision/Dockerfile`
- Create: `deploy/runpod-vision/README.md`
- Modify: `requirements-vision-runpod.txt`

**Interfaces:**
- Consumes: `run_worker_job(request: dict[str, Any]) -> dict[str, Any]`
- Consumes: `ai.vision.run_to_supervisor.run(input_path, checkpoint=...)`
- Produces: allowlisted `{"vision_supervisor_handoff": {...}}` 또는
  `{"vision_worker_error": {"error_code": "vision_worker_*"}}`

- [ ] **Step 1: worker validation·cleanup 테스트를 작성한다**

아래를 개별 테스트로 고정한다.

- schema version, safe id, MP4/MOV content type
- HTTPS와 exact/suffix allowlist host
- Content-Type, Content-Length, streaming max bytes
- download timeout
- 유효 handoff의 path, signed URL, 원문 error 제거
- pipeline 예외의 safe worker error
- success와 failure 모두 temporary workspace 삭제

- [ ] **Step 2: RED를 확인한다**

```powershell
python -m pytest -p no:cacheprovider test/test_runpod_vision_worker.py -q
```

Expected: `ai.vision.runpod_worker` import failure.

- [ ] **Step 3: worker를 최소 구현한다**

```python
def handler(job: dict[str, Any]) -> dict[str, Any]:
    request = job.get("input") if isinstance(job, dict) else None
    return run_worker_job(request)

if __name__ == "__main__":
    import runpod
    runpod.serverless.start({"handler": handler})
```

`TemporaryDirectory` 내부에서만 input, frames와 handoff를 생성하고 반환 전
allowlist 변환을 수행한다.

- [ ] **Step 4: worker 이미지 계약을 추가한다**

Dockerfile은 PyTorch CUDA runtime, ffmpeg/OpenCV runtime libraries,
`requirements-vision-runpod.txt`, repository Vision 코드와 module entrypoint를
포함한다. README에는 다음 명령과 사람 입력값을 기록한다.

```powershell
docker build --platform linux/amd64 -f deploy/runpod-vision/Dockerfile -t <registry>/skn27-vision:<release-tag> .
```

- [ ] **Step 5: GREEN, Ruff와 Dockerfile 계약을 확인한다**

```powershell
python -m pytest -p no:cacheprovider test/test_runpod_vision_worker.py -q
ruff check --no-cache ai/vision/runpod_worker.py test/test_runpod_vision_worker.py
```

Expected: all pass and no secret/path leakage.

- [ ] **Step 6: 커밋한다**

```powershell
git add ai/vision/runpod_worker.py test/test_runpod_vision_worker.py deploy/runpod-vision requirements-vision-runpod.txt
git commit -m "feat: add RunPod Vision worker"
```

### Task 5: 환경, 운영 문서와 체크리스트

**Files:**
- Modify: `.env.example`
- Modify: `.env.production.example`
- Modify: `deploy/aws-pilot/runtime.env.example`
- Modify: `docker-compose.yml`
- Modify: `docs/ops/vision-media-adapter-runbook.md`
- Modify: `docs/ops/project-readiness-master-checklist.md`
- Modify: `docs/ops/release-checklist.md`
- Modify: `docs/superpowers/reports/2026-07-23-release-readiness-integration-verification.md`
- Modify: `test/test_deployment_readiness_artifacts.py`
- Modify: `test/test_aws_pilot_infrastructure.py`

**Interfaces:**
- Consumes: Task 2~4의 환경변수와 stable codes
- Produces: key를 비워 둔 배포 예시, 운영자 절차와 사람 게이트

- [ ] **Step 1: 배포 계약 테스트를 먼저 작성한다**

예시 파일에 모든 RunPod 변수 이름이 있고 실제 key 값, Jupyter proxy,
`workersMin>0`, `workersMax>1`이 없음을 검증한다. runbook에는 five remote
stable codes, restricted key, Endpoint, registry, actual video smoke가 있어야
한다.

- [ ] **Step 2: RED를 확인한다**

```powershell
python -m pytest -p no:cacheprovider test/test_deployment_readiness_artifacts.py test/test_aws_pilot_infrastructure.py -q
```

Expected: RunPod 환경·문서 token 부재로 실패한다.

- [ ] **Step 3: 환경 예시와 runbook을 갱신한다**

운영 예시는 `VISION_RUNTIME_PROVIDER=runpod`, local 예시는 `local`로 두고
`RUNPOD_API_KEY=`는 빈 값으로 유지한다. 실제 key와 endpoint는 커밋하지 않은
runtime env/SSM에만 입력한다.

- [ ] **Step 4: 체크리스트를 증적 기준으로 갱신한다**

- PR #303 운영 관측 병합 완료와 merge commit `5f3728e` 기록
- RunPod client/worker 로컬 계약은 `[~]`
- restricted key, 유료 Endpoint, artifact 승인, 실영상 E2E는 `[ ]`

- [ ] **Step 5: GREEN을 확인한다**

```powershell
python -m pytest -p no:cacheprovider test/test_deployment_readiness_artifacts.py test/test_aws_pilot_infrastructure.py -q
```

Expected: all pass.

- [ ] **Step 6: 커밋한다**

```powershell
git add .env.example .env.production.example deploy/aws-pilot/runtime.env.example docker-compose.yml docs/ops test/test_deployment_readiness_artifacts.py test/test_aws_pilot_infrastructure.py docs/superpowers/reports/2026-07-23-release-readiness-integration-verification.md
git commit -m "docs: wire RunPod Vision operations"
```

### Task 6: 전체 검증과 GitHub 통합

**Files:**
- Verify: all branch changes

**Interfaces:**
- Consumes: Tasks 1~5
- Produces: review-ready PR과 실제 Endpoint 전에 남은 사람 작업 목록

- [ ] **Step 1: 집중 회귀를 실행한다**

```powershell
python -m pytest -p no:cacheprovider test/test_runpod_vision_client.py test/test_runpod_vision_worker.py test/test_vision_media_analysis_adapter.py test/test_agent_node_service.py test/test_supervisor_plan_execution.py test/test_deployment_readiness_artifacts.py test/test_aws_pilot_infrastructure.py -q
```

Expected: all pass.

- [ ] **Step 2: 전체 pytest, Django, Ruff, Vite를 실행한다**

```powershell
python -m pytest -p no:cacheprovider test
python backend/manage.py test
ruff check --no-cache app/services/runpod_vision_client.py app/services/vision_media_analysis_adapter.py ai/vision/runpod_worker.py test/test_runpod_vision_client.py test/test_runpod_vision_worker.py test/test_vision_media_analysis_adapter.py
npm --prefix app/web run build -- --configLoader runner
```

Expected: all pass.

- [ ] **Step 3: diff와 비밀값을 검토한다**

```powershell
git diff --check origin/dev...HEAD
git status --short
git diff --name-status origin/dev...HEAD
```

Expected: clean worktree, 의도한 파일만 포함, 실제 key/email/path literal 없음.

- [ ] **Step 4: push와 ready PR을 만든다**

```powershell
git push -u origin feat-runpod-serverless-vision
gh pr create --base dev --head feat-runpod-serverless-vision --title "feat: connect RunPod Serverless Vision"
```

- [ ] **Step 5: CI를 확인하고 merge한다**

```powershell
gh pr checks <PR_NUMBER> --watch
gh pr merge <PR_NUMBER> --merge --match-head-commit <HEAD_SHA>
```

Expected: production gate success and PR state `MERGED`.

## Self-review

- Spec coverage: provider, queue client, signed URL, stable errors, worker,
  Dockerfile, model/cost gate, privacy, cleanup과 E2E 경계를 Tasks 2~6에 연결했다.
- Placeholder scan: 실행을 미루는 placeholder 표현은 없고 사람 게이트에는
  필요한 실제 입력과 증적을 명시했다.
- Type consistency: `RunPodVisionClient.run()` → `RunPodVisionResult.output` →
  adapter allowlist → worker `vision_supervisor_handoff` 계약을 동일하게 사용한다.
