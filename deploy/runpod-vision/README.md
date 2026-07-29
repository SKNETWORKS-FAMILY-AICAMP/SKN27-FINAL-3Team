# RunPod Serverless Vision worker

`vision_media_analysis`의 RunPod Serverless 배포 패키지다. Worker는 scan-ready
영상의 signed HTTPS URL만 받고, 경로·URL query·예외 원문을 제거한
`vision-supervisor-handoff-v1`만 반환한다.

## 고정된 운영 입력

| 항목 | 값 |
|---|---|
| VideoMAE | `per_label_300_32frames/videomae_cls_20260724_002551` |
| VideoMAE weights SHA-256 | `f2c453b9b93f206338ffb5df9f213f196aa9f85ac2c5fcca22ce4fc689ddcff1` |
| Qwen | `Qwen/Qwen2.5-VL-3B-Instruct` |
| Qwen revision | `66285546d2b821cf421d4f5eb2576359d3770cd3` |
| VideoMAE / YOLO / Qwen 프레임 | `32 / 32 / 32` |
| 차대차 / 차대이륜차 YOLO | `yolov8m.pt` (`5d4a90cdc7a21786cc59cd19778e9eafff836df9e2da32524737c7ee6efe4fe5`) |
| 차대보행자 YOLO | `yolo11n.pt` (`0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1`) |
| 차대자전거 YOLO | `yolo11s.pt` (`85a76fe86dd8afe384648546b56a7a78580c7cb7b404fc595f97969322d502d5`) |

VideoMAE 설정 해시는 `config.json`
`80c9bfc42fb74744b68e9ac0282a28bd8350599283c1f637eac6908ae971bb6a`,
`preprocessor_config.json`
`1b8cd6bc1f257539c93390eb0b821fad87687a16c21669d3201942083497f119`,
`class_mapping.json`
`3f968782e9c51ef4c858dca9e6eddcca4827099a884183f4d29054b34ecc0759`,
`run_config.json`
`e010d06c31862cceed2ece4815272984ac7e3c9e412d22a2178df946803fe172`다.

## Network Volume

다음을 `/runpod-volume`에 배치하고 read-only로 사용한다.

```text
/runpod-volume/models/videomae/
  config.json
  model.safetensors
  preprocessor_config.json
  class_mapping.json
  run_config.json
/runpod-volume/models/yolo/
  yolov8m.pt
  yolo11n.pt
  yolo11s.pt
/runpod-volume/huggingface/
```

Worker 환경변수:

```text
VISION_TRAINED_CLASSIFIER_CHECKPOINT=/runpod-volume/models/videomae
VISION_QWEN_MODEL_ID=Qwen/Qwen3-VL-4B-Instruct
VISION_QWEN_MODEL_REVISION=
HF_HOME=/runpod-volume/huggingface
RUNPOD_VISION_ALLOWED_HOSTS=<approved-bucket>.s3.<region>.amazonaws.com
RUNPOD_VISION_DOWNLOAD_TIMEOUT_SECONDS=60
RUNPOD_VISION_MAX_DOWNLOAD_BYTES=52428800
RUNPOD_VISION_EXECUTION_TIMEOUT_SECONDS=540
```

초기 Endpoint는 중복 실행과 비용을 제한하도록 `workersMin=0`,
`workersMax=1`로 시작한다. 애플리케이션의 `RUNPOD_API_KEY`와
`RUNPOD_VISION_ENDPOINT_ID` 설정 및 Supervisor 연결은 Supervisor 담당 범위다.
API key는 restricted key로 발급하고 이미지나 로그에 넣지 않는다.

서비스 계약은 VideoMAE 분류에 32프레임을 사용하고, OpenCV·YOLO·Qwen에는
충돌 후보 중심의 16프레임(context/pre-impact/impact/post-impact 각 4개)을
사용한다. VideoMAE의 사고유형과 `confirmed_accident=true`는 Qwen이 변경할
수 없는 입력이며, Qwen은 보이는 근거만 설명한다.

## 검증 명령

```powershell
Get-FileHash <network-volume-copy>\model.safetensors -Algorithm SHA256
uv run --with pytest pytest -q test/test_vision_run_to_supervisor.py test/test_vision_media_analysis_adapter.py test/test_runpod_vision_worker.py test/test_vlm_input_contract.py test/test_vlm_json.py
docker build --platform linux/amd64 -f deploy/runpod-vision/Dockerfile -t <registry>/skn27-vision:<release-tag> .
```

판정 기준:

- 해시가 위 값과 다르면 배포 중지
- 테스트가 하나라도 실패하면 배포 중지
- `complete`, `partial`, `failed`가 worker와 adapter를 지나 보존되어야 함
- Qwen JSON invalid는 전체 실패가 아니라 `partial`과 `requires_review`여야 함
- 로그에 API key, signed URL query, 로컬/volume 경로, 예외 원문이 없어야 함

## 사람 확인이 필요한 결정

1. 검증 400건에서 Qwen3 JSON valid `394/400`, fallback `6/400`, label
   preservation `400/400` 결과를 운영 기준선으로 승인한다.
2. 비식별 실제 영상으로 `/run → /status → handoff → Supervisor`를 실행해
   success, partial, invalid JSON, timeout, download failure를 각각 확인한다.
3. 관찰 Qwen3 GPU peak `12,991.6 MiB`에 여유를 둔 GPU와 timeout을 선택한다.

LLaVA는 48GB급 환경에서도 OOM이 발생해 운영 후보로 확정하지 않았다. Qwen은
사고 유형이나 과실을 확정하지 않고 VideoMAE·YOLO 결과의 상황 설명만 보조한다.
