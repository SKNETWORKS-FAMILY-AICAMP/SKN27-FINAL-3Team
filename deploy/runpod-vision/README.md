# RunPod Serverless Vision worker

이 디렉터리는 `vision_media_analysis`의 Queue-based Serverless worker image를
정의한다. worker는 signed HTTPS URL로 받은 scan-ready 영상만 분석하고
정제된 `vision_supervisor_handoff`만 반환한다.

## 로컬 build

실제 registry와 release tag를 로컬 변수로 넣는다.

```powershell
docker build --platform linux/amd64 `
  -f deploy/runpod-vision/Dockerfile `
  -t <registry>/skn27-vision:<release-tag> .
```

모델, checkpoint, API key와 signed URL은 image layer에 넣지 않는다.

## RunPod 설정

초기 Endpoint는 비용과 중복 실행을 제한하기 위해 다음 값으로 시작한다.

```text
workersMin=0
workersMax=1
```

Endpoint 생성 전에 팀이 승인할 항목:

1. 32-frame 비교 결과로 운영 VLM 하나를 선택한다.
2. VideoMAE checkpoint를 RunPod Network Volume에 배치한다.
3. `VISION_TRAINED_CLASSIFIER_CHECKPOINT`를 volume 내부 read-only 경로로
   설정한다.
4. Hugging Face cache가 필요하면 `HF_HOME=/runpod-volume/huggingface`를
   유지한다.
5. VRAM을 만족하는 최소 GPU와 execution timeout을 smoke 결과로 결정한다.

worker 환경변수:

```text
VISION_TRAINED_CLASSIFIER_CHECKPOINT=/runpod-volume/models/videomae
RUNPOD_VISION_ALLOWED_HOSTS=<approved-bucket>.s3.<region>.amazonaws.com
RUNPOD_VISION_DOWNLOAD_TIMEOUT_SECONDS=60
RUNPOD_VISION_MAX_DOWNLOAD_BYTES=52428800
RUNPOD_VISION_EXECUTION_TIMEOUT_SECONDS=540
```

애플리케이션의 `RUNPOD_API_KEY`는 restricted key로 발급하고 AWS runtime
SecureString에만 입력한다. worker image와 RunPod worker 환경에는
애플리케이션 API key가 필요하지 않다.

## 사람 게이트

- image를 승인된 registry에 push
- 과금 가능한 Endpoint 생성
- 모델 artifact와 GPU/timeout 승인
- 비식별 영상으로 `/run` → `/status` → Supervisor handoff E2E
- worker와 애플리케이션 로그에서 API key, signed URL query, 로컬 경로가
  보이지 않는지 확인

이 증적이 없으면 저장소 contract test와 image 정의가 통과해도 운영 Vision
연결 완료로 표시하지 않는다.
