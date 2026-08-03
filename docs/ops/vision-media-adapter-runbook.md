# Vision media adapter 운영 진단 가이드

## 목적

`vision_media_analysis`는 canonical scan gate를 통과한 MP4/MOV 첨부파일만
격리된 Worker 작업공간에서 처리하고, 정규화된 Agent 결과만 Supervisor에
반환합니다. 로컬 개발은 subprocess provider를 유지하고, 운영은
`VISION_RUNTIME_PROVIDER=runpod`의 RunPod Serverless queue API 또는
`VISION_RUNTIME_PROVIDER=aws_queue`의 private AWS GPU queue를 사용합니다.
Jupyter proxy는 모델 점검용 도구일 뿐 운영 API로 사용하지 않습니다.

## Provider와 사전 점검

### local

1. `VISION_RUNTIME_PROVIDER=local`인지 확인합니다.
2. 승인된 checkpoint에 `config.json`과 가중치 파일이 함께 있는지 확인합니다.
3. 비민감 MP4/MOV fixture로 격리된 환경에서 한 번만 smoke test를 수행합니다.

```bash
python -m ai.vision.run_to_supervisor <fixture.mp4> --checkpoint <approved-checkpoint-dir>
```

### runpod

1. RunPod registry에 `deploy/runpod-vision/Dockerfile`로 만든 immutable image를
   게시하고 승인된 모델 artifact 또는 Network Volume을 연결합니다.
2. Endpoint에 restricted API key를 발급하고 `workersMin=0`,
   `workersMax=1`로 시작합니다.
3. private runtime environment에 `RUNPOD_API_KEY`,
   `RUNPOD_VISION_ENDPOINT_ID`, `RUNPOD_VISION_ALLOWED_HOSTS`를 입력합니다.
   실제 값은 Git, 채팅, 로그에 기록하지 않습니다.
4. object storage provider가 S3이고, presigned GET URL의 수명이 전체
   `RUNPOD_VISION_TIMEOUT_SECONDS`보다 긴지 확인합니다.
5. allowlist에는 승인된 S3 HTTPS hostname만 입력합니다. worker는 HTTPS,
   MIME, 크기, timeout을 다시 검증합니다.

## 안전한 오류 코드별 조치

| Safe code | Verify | Operator action |
| --- | --- | --- |
| `attachment_not_scan_ready` | `UploadedFile.status=ready`, `scan_status=clean`, canonical scan marker | Wait for scan or re-upload; do not retry Agent execution first. |
| `vision_checkpoint_missing` | checkpoint environment value exists and contains `config.json` plus `model.safetensors` or `pytorch_model.bin` | Deploy a complete approved checkpoint and rerun one smoke test. |
| `vision_dependency_missing` | Worker image contains `requirements-vision-runpod.txt` dependencies | Rebuild the Worker image; do not expose dependency diagnostics to chat users. |
| `vision_media_decode_failed` | Reproduce with a non-sensitive fixture in the isolated worker workspace | Ask for re-upload in MP4/MOV; preserve only stable trace IDs. |
| `vision_execution_timeout` | Compare `latency_ms` and configured timeout | Review runtime capacity and retry through the queue. |
| `vision_execution_failed` | Query `job_id`, `execution_id`, `attachment_id`, node code, result status | Investigate server-only logs; return generic retry guidance to the user. |
| `vision_remote_execution_failed` | Check the safe RunPod job ID and worker/model health | Inspect server-only logs without copying provider errors; retry only after the cause is corrected. |
| `vision_remote_cancelled` | Check whether an operator or RunPod policy cancelled the job | Explain that processing stopped and create a new job only when retry is safe. |
| `vision_remote_timeout` | Compare queue, cold-start, download, and execution time with the configured bound | Check capacity and artifact size; do not increase the timeout blindly. |
| `vision_remote_unavailable` | Check endpoint ID, key validity, provider status, and presigned HTTPS access | Restore the dependency without printing the key or signed URL. |
| `vision_remote_invalid_response` | Compare worker output with the `vision_supervisor_handoff` contract | Stop rollout and fix the worker/provider contract before retrying. |

## 로그와 데이터 최소화

운영자는 `job_id`, `execution_id`, `attachment_id`, node code, result status,
stable error code, `latency_ms`만 사용해 작업을 추적합니다. 채팅 사용자에게는
재업로드 또는 재시도 안내만 반환합니다.

파일명, 원본 영상/프레임, presigned URL, 로컬·스토리지 경로, checkpoint 값,
API/access key, provider 원문 오류, 모델 내부 출력은 운영 문서·사용자 응답·
persisted Agent metadata에 기록하거나 노출하지 않습니다. worker의 임시
다운로드 파일과 handoff 파일은 성공·실패 모두 작업 종료 시 삭제합니다.

## 재시도와 비용 기준

- scan 미완료와 checkpoint/의존성 오류는 원인을 해결하기 전 재시도하지 않습니다.
- decode 오류는 MP4/MOV 재업로드를 요청한 뒤 새 첨부 ID로 재실행합니다.
- RunPod `POST /run`은 응답 유실 시 유료 작업을 중복 생성할 수 있으므로
  자동 재전송하지 않습니다.
- 제출 직후 받은 RunPod job ID는 `execution_id`별 cache에 보존하고,
  같은 실행은 `GET /status/{job_id}` polling부터 재개합니다.
- status GET의 일시적 네트워크 오류는 한 번만 재시도합니다. provider가
  caller idempotency key를 보장하지 않으므로 응답 유실 경계의 exactly-once를
  주장하지 않습니다.
- 비용 이상 시 신규 제출을 중단하고 Endpoint 동시성, 최대 worker 수,
  다운로드·실행 timeout, 입력 크기 제한을 먼저 확인합니다.

## RunPod 운영 활성화 사람 게이트

다음은 비밀값·결제·모델 및 실데이터 승인 권한이 필요합니다.

1. restricted RunPod API key와 유료 Serverless Endpoint 생성
2. immutable worker image와 승인된 모델 artifact/Network Volume 연결
3. private runtime environment에 endpoint ID와 S3 hostname allowlist 입력
4. 비식별 MP4/MOV fixture smoke 후, 승인된 비식별 실제 영상 1건으로
   upload → scan → Agent handoff → RunPod → 결과 화면 E2E 확인
5. RunPod dashboard에서 `workersMin=0`, `workersMax=1`, timeout과 비용 상한 확인

실제 키와 Endpoint가 없더라도 local provider 및 mock HTTP 경계 테스트는
자동화할 수 있지만, 위 절차가 끝나기 전에는 운영 Vision 연결 완료로 표시하지
않습니다.

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

`vision_worker_enabled=false`이거나 출력이 비어 있으면 배포는 SSM 갱신 전에
중단되어야 합니다. queue URL이나 bucket 값을 수동 복사해 우회하지 않습니다.

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
