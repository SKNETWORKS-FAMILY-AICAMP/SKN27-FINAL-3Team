# Vision 로컬 후속 작업 실행 결과

- 실행일: 2026-07-23
- 기준 보고서: `docs/vision/vision_project_status_and_next_steps_2026-07-23.md`
- 브랜치: `feat-accident-image-video-agent-result-flow`

## 완료

- VideoMAE, Qwen, 키프레임 기본 입력 32 확인
- VideoMAE 고정 test 재평가 모듈 및 정량 지표 산출 코드 확인
- test split을 학습 중 반복 평가하지 않고 best validation checkpoint에서 한 번만 평가하도록 확인
- Qwen 실패 시 예외 문자열·로컬 경로를 노출하지 않는 stable error code와 partial handoff 확인
- 낮은 VideoMAE confidence의 `requires_review` 처리 확인
- CPU 환경에서 `--device auto`가 `cpu`로 해석되도록 공통 장치 선택 로직 재사용
- exp4, 고정 split, 메타데이터, Qwen 프레임 수, SHA-256을 한 번에 확인하는 readiness audit 추가
- 로컬 exp3 체크포인트로 실제 영상 1건 VideoMAE → YOLO → partial Supervisor handoff 스모크 완료
- 생성 handoff에 로컬 절대 경로가 포함되지 않음을 확인

## 로컬 readiness 결과

`storage/vision/reports/vision_readiness_20260723.json` 기준:

| 항목 | 상태 | 근거 |
|---|---|---|
| exp4 체크포인트 | 차단 | 지정 경로 없음 |
| 고정 split | 차단 | `videomae_labeled_fixed100_split.csv` 없음 |
| 메타데이터 완결성 | 차단 | 고정 split 없음 |
| incident split 격리 | 차단 | 고정 split 없음 |
| Qwen 32프레임 결과 | 차단 | 현재 400건 모두 4프레임 |
| 로컬 원본 영상 | 확인 | 4개 카테고리, 총 400개 |
| 완전한 로컬 체크포인트 | 확인 | exp3 1개, 16프레임 |

감사 재실행:

```powershell
python -m ai.vision.audit_project_readiness --root .
```

## 실제 E2E 스모크

exp3는 `config.json`과 `run_config.json` 모두 16프레임 모델이다. 따라서 exp4의 32프레임 성능 검증으로 해석하지 않고 파이프라인 연결만 확인했다.

```powershell
python -m ai.vision.run_to_supervisor `
  "storage/vision/datasets/classification/raw_videos/차대보행자/aihub_train_00000001_bb_1_161018_pedestrian_112_331.mp4" `
  --checkpoint "storage/vision/models/videomae_raw_video/per_label_100_exp3_unfreeze_lr1e-5_e50/videomae_cls_20260713_045649" `
  --frame-count 32 `
  --videomae-frame-count 16 `
  --qwen-frame-count 32 `
  --device auto `
  --skip-qwen
```

결과: Supervisor handoff JSON 생성 성공, 상태 `partial`, key frame 32개, 로컬 절대 경로 미노출.

## RunPod 산출물 동기화 후 실행

필수 동기화 대상:

```text
storage/vision/manifests/videomae_labeled_fixed100_split.csv
storage/vision/models/videomae_raw_video/per_label_100_exp4_32frames_adaptive_labeled/videomae_cls_20260722_145601/
```

동기화 직후 순서:

```powershell
python -m ai.vision.audit_project_readiness --root .

python -m ai.vision.evaluate_videomae_classifier `
  --checkpoint "storage/vision/models/videomae_raw_video/per_label_100_exp4_32frames_adaptive_labeled/videomae_cls_20260722_145601" `
  --manifest "storage/vision/manifests/videomae_labeled_fixed100_split.csv" `
  --root-dir . `
  --frame-count 32 `
  --device auto
```

32프레임 Qwen/LLaVA 비교는 동일 400건, 동일 프롬프트·JSON schema·전처리로 RunPod에서 실행한 뒤 결과 CSV만 로컬 결과 저장소에 동기화한다.

## 외부 입력 전에는 진행하지 않는 항목

- exp4 고정 test 성능 확정
