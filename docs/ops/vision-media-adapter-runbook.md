# Vision media adapter 운영 진단 가이드

## 목적

`vision_media_analysis`는 canonical scan gate를 통과한 MP4/MOV 첨부파일만 격리된 Worker 작업공간에서 처리하고, 정규화된 Agent 결과만 Supervisor에 반환합니다. 이 문서는 연결 실패를 안전하게 진단하기 위한 운영 절차이며, Vision 모델 품질·학습·새 provider 도입을 다루지 않습니다.

## 사전 점검

1. 업로드 자료가 `blackbox_video` 목적이며 scan 완료 상태인지 확인합니다.
2. 승인된 checkpoint 설정값이 있고 필요한 구성 파일과 가중치 파일이 함께 배포됐는지 확인합니다.
3. Worker 이미지에 Vision 실행 의존성이 포함됐는지 확인합니다.
4. 운영 데이터가 아닌 비민감 MP4/MOV fixture로 격리된 환경에서 한 번만 smoke test를 수행합니다.

선택적 smoke 명령은 아래와 같습니다. 보안이 적용된 런타임에서만, 운영 영상이 아닌 fixture에 한해 실행합니다.

```bash
python -m ai.vision.run_to_supervisor <fixture.mp4> --checkpoint <approved-checkpoint-dir>
```

## 안전한 오류 코드별 조치

| Safe code | Verify | Operator action |
| --- | --- | --- |
| `attachment_not_scan_ready` | `UploadedFile.status=ready`, `scan_status=clean`, canonical scan marker | Wait for scan or re-upload; do not retry Agent execution first. |
| `vision_checkpoint_missing` | checkpoint environment value exists and contains `config.json` plus `model.safetensors` or `pytorch_model.bin` | Deploy a complete approved checkpoint and rerun one smoke test. |
| `vision_dependency_missing` | Worker image contains `requirements-vision-runpod.txt` dependencies | Rebuild the Worker image; do not expose dependency diagnostics to chat users. |
| `vision_media_decode_failed` | Reproduce with a non-sensitive fixture in the isolated worker workspace | Ask for re-upload in MP4/MOV; preserve only stable trace IDs. |
| `vision_execution_timeout` | Compare `latency_ms` and configured timeout | Review runtime capacity and retry through the queue. |
| `vision_execution_failed` | Query `job_id`, `execution_id`, `attachment_id`, node code, result status | Investigate server-only logs; return the generic retry guidance to the user. |

## 로그 확인 범위

운영자는 `job_id`, `execution_id`, `attachment_id`, node code, result status, stable error code, `latency_ms`만 사용해 작업을 추적합니다. 채팅 사용자에게는 재업로드 또는 재시도 안내만 반환합니다.

파일명, 원본 영상/프레임, 로컬·스토리지 경로, checkpoint 값, access key, provider 원문 오류, 모델 내부 출력은 운영 문서·사용자 응답·persisted Agent metadata에 기록하거나 노출하지 않습니다.

## 재시도 기준

- scan 미완료와 checkpoint/의존성 오류는 원인을 해결하기 전 재시도하지 않습니다.
- decode 오류는 MP4/MOV 재업로드를 요청한 뒤 새 첨부 ID로 재실행합니다.
- timeout과 일반 실행 실패는 Worker 용량과 stable trace ID를 확인한 뒤 큐를 통해 재시도합니다.
