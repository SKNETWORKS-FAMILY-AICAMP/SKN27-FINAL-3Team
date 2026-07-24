# RunPod Serverless Vision 운영 연결 설계

- 작성일: 2026-07-24
- 사용자 승인 원본: `2026-07-23-runpod-serverless-vision-design.md`
- 대상: `SKN27-FINAL-3Team`의 `vision_media_analysis`

## 1. 목표와 완료 경계

운영 Vision 추론은 일반 Pod/Jupyter가 아니라 RunPod Queue-based
Serverless Endpoint를 사용한다.

```text
canonical scan-ready 영상
→ S3의 짧은 수명 HTTPS 서명 URL
→ POST /run
→ RunPod job id 보존
→ GET /status/{job_id} polling
→ Vision handoff JSON 검증·정제
→ Supervisor
```

`VISION_RUNTIME_PROVIDER=local`은 기존 격리 subprocess를 유지하고,
`VISION_RUNTIME_PROVIDER=runpod`만 원격 실행을 사용한다. Jupyter proxy는
운영 API로 사용하지 않는다.

이 브랜치가 증명하는 범위는 HTTP client, provider 분기, signed URL 경계,
worker handler, Dockerfile, 오류·개인정보 비노출 계약과 로컬 컨테이너
구성이다. 다음은 사람 게이트다.

- restricted `RUNPOD_API_KEY` 발급
- 과금 가능한 Serverless Endpoint 생성
- VideoMAE checkpoint와 VLM artifact 승인
- registry push와 Endpoint image 연결
- 비식별 실제 영상 1건의 GPU E2E

## 2. 애플리케이션 구성

### 2.1 Provider 선택

`app/services/vision_media_analysis_adapter.py`가 provider를 선택한다.

- `local`: 기존 checkpoint preflight, S3 bytes materialize, subprocess
- `runpod`: checkpoint 로컬 검사와 영상 bytes 다운로드를 하지 않고 S3
  reference를 HTTPS signed URL로 변환해 RunPod client 호출
- 그 밖의 값: `vision_remote_unavailable`

두 provider 모두 canonical scan gate를 통과한 MP4/MOV만 처리하고, 마지막에
동일한 handoff allowlist를 적용한다.

### 2.2 RunPod HTTP client

`app/services/runpod_vision_client.py`는 Python 표준 라이브러리만 사용한다.

- `POST https://api.runpod.ai/v2/{endpoint_id}/run`
- `GET https://api.runpod.ai/v2/{endpoint_id}/status/{job_id}`
- `Authorization: Bearer ...`
- HTTP body 최대 크기 제한
- GET의 일시적 네트워크 오류만 제한적으로 재시도
- 전체 polling deadline 이후 `vision_remote_timeout`
- API key, signed URL, 응답 원문과 예외 문자열을 반환값·로그에 포함하지 않음

RunPod 공식 queue API에는 애플리케이션이 지정하는 idempotency header가
문서화되어 있지 않다. 따라서 응답을 받지 못한 `POST /run`을 자동 반복하면
과금 job이 중복될 수 있어 자동 재시도하지 않는다. 응답으로 받은 job id는
Redis/Django cache에 `execution_id` 기준으로 즉시 보존하고, 같은 execution의
재진입은 기존 job을 polling한다. 이 방식은 응답을 받은 뒤의 재시도 중복은
막지만, 전송 성공 후 응답 유실 상황의 exactly-once를 보장한다고 주장하지
않는다.

### 2.3 요청과 상태 매핑

요청:

```json
{
  "input": {
    "schema_version": "vision-runpod-request-v1",
    "execution_id": "exec_...",
    "attachment_id": "att_...",
    "video_url": "https://short-lived-signed-url",
    "content_type": "video/mp4"
  }
}
```

영상 binary와 API key는 JSON에 넣지 않는다.

| RunPod 상태/결과 | 애플리케이션 결과 |
|---|---|
| `IN_QUEUE`, `IN_PROGRESS` | polling 계속 |
| `COMPLETED` + 유효 handoff | 기존 partial Vision 결과 |
| `FAILED` | `vision_remote_execution_failed` |
| `CANCELLED` | `vision_remote_cancelled` |
| deadline 초과 | `vision_remote_timeout` |
| HTTP·인증·설정·signed URL 실패 | `vision_remote_unavailable` |
| job id·status·output schema 불일치 | `vision_remote_invalid_response` |

`COMPLETED` output도 신뢰하지 않고 기존 allowlist를 다시 적용한다.

## 3. Signed URL 경계

기존 `chatbot.object_storage.presign_get()`을 사용한다.

- `object_storage.provider`가 `s3`인 clean canonical object만 허용
- 반환 URL은 `https`만 허용
- userinfo와 fragment 금지
- signed URL TTL은 polling timeout보다 길어야 함
- URL 전체와 query는 DB, 로그, exception, adapter 결과에 남기지 않음

로컬 `mock_s3://` URL은 RunPod로 전달하지 않는다. 로컬 개발은
`VISION_RUNTIME_PROVIDER=local`을 사용한다.

## 4. RunPod worker

`ai/vision/runpod_worker.py`는 공식 SDK의 다음 handler 형태를 사용한다.

```python
def handler(job):
    request = job["input"]
    return run_worker_job(request)

runpod.serverless.start({"handler": handler})
```

worker 처리 순서:

1. `vision-runpod-request-v1` schema와 safe identifier 검증
2. HTTPS와 `RUNPOD_VISION_ALLOWED_HOSTS` allowlist 검증
3. 다운로드 timeout, content type, Content-Length와 streaming byte 상한 검증
4. job별 `TemporaryDirectory`에 MP4/MOV 저장
5. `ai.vision.run_to_supervisor.run()` 실행
6. 정확히 한 handoff JSON을 읽어 schema 검증
7. 경로·진단·URL을 제거한 `vision_supervisor_handoff` 반환
8. success·partial·failure와 무관하게 임시 영상·frame·output 삭제

worker는 Supervisor, 법령 검색, 과실비율 판단을 호출하지 않는다. 내부
exception은 원문으로 반환하지 않고 safe worker error만 반환한다.

## 5. Worker 이미지와 모델

`deploy/runpod-vision/Dockerfile`은 CUDA/PyTorch runtime 위에 repository
Vision 코드와 `requirements-vision-runpod.txt`를 설치하고
`python -u -m ai.vision.runpod_worker`를 실행한다.

- 모델은 image에 포함하지 않음
- checkpoint는 `VISION_TRAINED_CLASSIFIER_CHECKPOINT`
- Hugging Face cache는 Network Volume 경로 사용 가능
- Qwen/LLaVA 중 운영 VLM은 32-frame 비교 후 하나만 승인
- 초기 Endpoint는 `workersMin=0`, `workersMax=1`

현재 repository pipeline은 Qwen을 기본값으로 사용한다. 실제 Endpoint 전에
모델 artifact, VRAM, cold start, 최대 실행시간을 사람이 승인한다.

## 6. 환경변수

```text
VISION_RUNTIME_PROVIDER=local|runpod
VISION_RUNTIME_TIMEOUT_SECONDS=180
RUNPOD_API_KEY=<secret>
RUNPOD_VISION_ENDPOINT_ID=<endpoint-id>
RUNPOD_VISION_TIMEOUT_SECONDS=600
RUNPOD_VISION_POLL_INTERVAL_SECONDS=2
RUNPOD_VISION_ALLOWED_HOSTS=<comma-separated-s3-hosts>
RUNPOD_VISION_DOWNLOAD_TIMEOUT_SECONDS=60
RUNPOD_VISION_MAX_DOWNLOAD_BYTES=52428800
```

`RUNPOD_API_KEY`는 `.runtime.env`/SSM SecureString 또는 RunPod secret에만
입력한다. 예시 파일에는 빈 값만 둔다.

## 7. 검증

### 로컬 자동 검증

- local provider 기존 subprocess 회귀
- runpod provider가 local checkpoint/bytes를 요구하지 않음
- signed URL과 request schema
- job 생성·polling·기존 job 재사용
- completed/failed/cancelled/timeout/invalid response
- API key·signed URL·내부 경로·원문 오류 비노출
- worker URL host/content type/크기/timeout 검증
- worker handoff schema·정제·임시 파일 삭제
- Dockerfile와 환경 예시 계약

### 사람 검증

1. 비식별 영상 업로드와 scan-ready 확인
2. 실제 S3 signed URL 발급
3. `/run` job 생성과 `/status` polling
4. GPU 추론과 handoff 수신
5. Supervisor adapter 수신
6. 로그·DB·결과의 secret, URL query, 경로 비노출 표본 확인
7. cold start, 실행시간, GPU, 비용 기록

실제 Endpoint 증적 전에는 체크리스트를 `[x]`로 바꾸지 않는다.
