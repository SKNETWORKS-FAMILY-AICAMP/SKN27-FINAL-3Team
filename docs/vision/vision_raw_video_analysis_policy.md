# Vision Raw Video 분석 수정 방향

## 현재 문제

기존 clip 기반 실험은 사고 후보 구간이 정확히 잘리지 않을 경우 Qwen/VideoMAE가 사고 장면을 놓칠 수 있다. 따라서 clip 생성 품질을 고치기 전에, 원본 10초 영상 전체를 그대로 사용하는 비교 실험을 별도로 둔다.

## 새 실험 방향

1. 기존 ipynb 파일은 유지한다.
2. 원본 raw video를 clip으로 자르지 않고 그대로 VideoMAE에 입력한다.
3. 1차는 상위 사고 유형별 50개, 총 200개만 사용한다.
4. 1차가 정상 동작하면 상위 사고 유형별 100개, 총 400개로 확장한다.
5. 프레임 샘플링은 32프레임 기준으로 진행한다.

## 서비스 입력 정책

사용자에게 받는 영상은 5초 이상 30초 이하로 제한한다. 30초를 초과하는 영상은 Vision Agent가 임의로 전체를 처리하지 않고, 사고 지점이 포함된 5~30초 구간으로 다시 제출하도록 요청한다.

## 생성 산출물

- `storage/vision/datasets/classification/manifests/train_50_raw_video_manifest.csv`
- `storage/vision/datasets/classification/manifests/train_100_raw_video_manifest.csv`
- `storage/vision/models/videomae_raw_video/per_label_50/*`
- `storage/vision/models/videomae_raw_video/per_label_100/*`

## 실행 노트북

`D:/dev/SKN27-FINAL-3Team/scripts/vision/vision_raw_video_videomae_runpod.ipynb`
