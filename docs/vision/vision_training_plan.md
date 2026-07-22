# Vision Classification Training Plan

작성일: 2026-06-27

## 1. 목적

전체 영상/이미지 데이터를 바로 GPU 학습에 투입하지 않고, Google Drive 목록을 먼저 Manifest화한 뒤 카테고리별 샘플링으로 학습 파이프라인을 검증한다.

현재 목표는 다음과 같다.

- Google Drive와 RunPod/로컬 연동 가능 여부 확인
- AI-Hub 영상 데이터의 카테고리별 폴더 구조 확인
- 영상 원본 전체 수집보다 프레임 캡처 기반 이미지 학습 데이터셋을 우선 구성
- 각 카테고리별 최대 700개 랜덤 샘플링 전략 수립
- 사전학습 모델 기반 분류 학습 파이프라인 준비
- 학습 시 파라미터, freezing 여부, 비교 모델, epoch별 결과 기록

## 2. Google Drive 확인 결과

대상 Drive 링크:

```text
https://drive.google.com/drive/folders/18uNzs8gH40zYuKaoftih2TpXdsxPc2nf?usp=drive_link
```

`gdown --folder --json`으로 다운로드 없이 목록 조회가 가능했다.

주의 사항:

- 전체 항목 수가 약 33,162개이므로 전체 다운로드부터 진행하지 않는다.
- 일부 파일/폴더명에 중국어 등 비 cp949 문자가 있어 Windows 콘솔에서는 UTF-8 출력 설정이 필요하다.
- 목록은 먼저 `storage/vision/manifests/drive_listing_aihub.json`으로 저장한 뒤 Manifest/Sampling에 사용한다.

목록 저장 명령:

```powershell
cd D:\dev\SKN27-FINAL-3Team
$env:PYTHONIOENCODING='utf-8'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
.\.venv\Scripts\python.exe -m gdown --folder --json "https://drive.google.com/drive/folders/18uNzs8gH40zYuKaoftih2TpXdsxPc2nf?usp=drive_link" | Out-File -LiteralPath "storage\vision\manifests\drive_listing_aihub.json" -Encoding utf8
```

## 3. 확인된 상위 데이터 구조

Drive listing 기준 상위 구조:

```text
Ai_Hub
Accident Images Analysis Dataset
car_crash
CarDD_release
image_sample_10
dada2000
video_smaple_1
```

주요 개수:

```text
Ai_Hub: 15,846
Accident Images Analysis Dataset: 10,511
car_crash: 6,006
CarDD_release: 786
image_sample_10: 10
dada2000: 2
video_smaple_1: 1
```

## 4. AI-Hub Train 카테고리 구조

AI-Hub 영상 학습 데이터는 아래처럼 카테고리별 폴더로 구성되어 있다.

```text
Ai_Hub/Train/TS_차대보행자_영상_육교및지하도부근: 7
Ai_Hub/Train/TS_차대보행자_영상_횡단보도(신호등없음): 64
Ai_Hub/Train/TS_차대보행자_영상_횡단보도(신호등없음)부근: 55
Ai_Hub/Train/TS_차대보행자_영상_횡단보도(신호등있음): 150
Ai_Hub/Train/TS_차대보행자_영상_횡단보도(신호등있음)부근: 110
Ai_Hub/Train/TS_차대보행자_영상_횡단보도없음: 377
Ai_Hub/Train/TS_차대이륜차_영상_T자형교차로: 166
Ai_Hub/Train/TS_차대이륜차_영상_사거리교차로(신호등없음): 219
Ai_Hub/Train/TS_차대이륜차_영상_사거리교차로(신호등있음): 462
Ai_Hub/Train/TS_차대이륜차_영상_직선도로: 958
Ai_Hub/Train/TS_차대이륜차_영상_차도와차도가아닌장소: 120
Ai_Hub/Train/TS_차대이륜차_영상_회전교차로: 3
Ai_Hub/Train/TS_차대자전거_영상_사거리교차로(신호등없음): 148
Ai_Hub/Train/TS_차대자전거_영상_사거리교차로(신호등있음): 91
Ai_Hub/Train/TS_차대자전거_영상_자전거도로: 12
Ai_Hub/Train/TS_차대자전거_영상_직선도로: 604
Ai_Hub/Train/TS_차대차_영상_T자형교차로: 1080
Ai_Hub/Train/TS_차대차_영상_고속도로(자동차전용도로)포함: 1271
Ai_Hub/Train/TS_차대차_영상_사거리교차로(신호등없음): 1238
Ai_Hub/Train/TS_차대차_영상_사거리교차로(신호등있음): 2095
Ai_Hub/Train/TS_차대차_영상_주차장(또는차도가아닌장소): 596
Ai_Hub/Train/TS_차대차_영상_직선도로: 5500
Ai_Hub/Train/TS_차대차_영상_차도와차도가아닌장소: 231
Ai_Hub/Train/TS_차대차_영상_회전교차로: 266
```

## 5. 데이터 읽기 전략

전체 Drive 폴더를 직접 다운로드하지 않는다.

대신 아래 순서로 진행한다.

```text
1. Drive listing JSON 생성
2. listing JSON에서 category, source_path, drive_url 추출
3. 카테고리별 최대 700개 랜덤 샘플링
4. 샘플링된 항목만 다운로드
5. 영상에서 대표 프레임 추출
6. 프레임 이미지를 학습 데이터로 사용
```

영상 원본은 우선 학습 대상으로 직접 사용하지 않고, 적절한 프레임 캡처 기준으로 이미지화한다.

## 6. 샘플링 기준

기본 전략:

```text
각 카테고리별 최대 700개 랜덤 추출
seed 고정: 42
카테고리 파일 수가 700개 미만이면 가능한 전체 사용
```

예시:

```text
TS_차대차_영상_직선도로: 5500개 중 최대 700개 추출
TS_차대차_영상_회전교차로: 266개 전체 사용
TS_차대이륜차_영상_회전교차로: 3개 전체 사용
```

주의:

- 카테고리별 원본 수 편차가 매우 크다.
- 700개 미만 카테고리는 가능한 전체를 사용하고, oversampling 여부는 추후 결정한다.
- 첫 학습은 class imbalance를 기록하고 진행한다.
- 이후 weighted sampler 또는 class weight 적용 여부를 비교한다.

## 7. Train/Val/Test Split

샘플링 후 split 비율:

```text
train: 70%
val: 20%
test: 10%
```

split은 같은 seed로 재현 가능해야 한다.

필수 컬럼:

```text
asset_id
dataset_name
source_dataset
category
label
input_type
source_path
drive_url
local_path
sample_group
split
file_exists
media_readable
planned_use
```

## 8. 프레임 캡처 기준

영상 원본 수집과 전체 비디오 학습은 우선 제외한다.

1차 기준:

```text
각 영상에서 1~5장 대표 프레임 추출
기본은 균등 샘플링
추후 객체 변화, 장면 변화, 사고 변곡점 기준으로 개선
```

초기 학습용으로는 영상 1개당 1장 또는 3장을 우선 검토한다.

- 1장: 데이터 중복과 학습 시간 감소
- 3장: 장면 변화 반영 가능
- 5장: POC 검증에는 좋지만 학습 데이터가 과도하게 늘 수 있음

## 9. 모델 학습 기준

우선 사전학습 모델 위에 classifier head를 붙인다.

후보 모델:

```text
ResNet18
EfficientNet-B0
MobileNetV3-Small
```

1차 baseline:

```text
ResNet18 pretrained=True
freeze_backbone=True
classifier head만 학습
```

비교 실험:

```text
freeze_backbone=True vs False
ResNet18 vs EfficientNet-B0
learning_rate 변경
batch_size 변경
epoch 수 변경
```

## 10. 실험 기록 필드

학습 시 아래 값을 반드시 기록한다.

```text
run_id
run_started_at
run_finished_at
dataset_manifest
sample_size_per_category
num_classes
model_name
pretrained
freeze_backbone
batch_size
learning_rate
epochs
train_loss
val_loss
val_accuracy
test_accuracy
model_path
notes
```

## 11. RunPod 사용 기준

RunPod는 아래 준비가 끝난 뒤 사용한다.

```text
1. Drive listing manifest 생성 완료
2. 카테고리별 700개 샘플링 manifest 생성 완료
3. 샘플 다운로드 코드 준비 완료
4. 프레임 추출 코드 준비 완료
5. train_classifier.py dry-run 완료
```

그 전까지는 로컬에서 코드와 manifest를 검증한다.

## 12. 다음 구현 파일

다음으로 만들 파일:

```text
etl/vision/build_classification_manifest.py
etl/vision/sample_classification_dataset.py
ai/vision/train_classifier.py
```

역할:

```text
build_classification_manifest.py
- drive_listing_aihub.json을 읽어 학습 후보 manifest 생성

sample_classification_dataset.py
- 카테고리별 최대 700개 랜덤 샘플링
- train/val/test split 부여

train_classifier.py
- sampled manifest 기반 이미지 분류 학습
- pretrained model, freezing, epoch 결과 기록
```

## 13. 학습 후보 Manifest 생성 결과

생성 파일:

```text
etl/vision/build_classification_manifest.py
```

실행:

```powershell
cd D:\dev\SKN27-FINAL-3Team
python etl\vision\build_classification_manifest.py
```

로컬 `.venv` 런처가 깨진 경우에는 Codex 번들 Python 또는 정상 Python으로 실행해도 된다. 해당 스크립트는 표준 라이브러리만 사용한다.

생성 결과:

```text
storage/vision/datasets/classification/manifests/classification_manifest.csv
```

생성 요약:

```text
total_rows: 15823
input_type_counts: {'video': 15823}
```

현재 Manifest는 AI-Hub Train 하위 영상 파일만 후보로 수집한다.

주요 컬럼:

```text
asset_id
dataset_name
source_dataset
category
label
input_type
source_path
drive_url
file_name
file_ext
local_path
sample_group
split
file_exists
media_readable
planned_use
```

다음 단계:

```text
etl/vision/sample_classification_dataset.py
```

역할:

```text
classification_manifest.csv 읽기
카테고리별 최대 700개 랜덤 샘플링
train/val/test = 70/20/10 split 부여
sample_700_coarse_manifest.csv 생성
```

## 14. 카테고리별 700개 샘플링 기준

생성 파일:

```text
etl/vision/sample_classification_dataset.py
```

실행:

```powershell
cd D:\dev\SKN27-FINAL-3Team
python etl\vision\sample_classification_dataset.py
```

생성 결과:

```text
storage/vision/datasets/classification/manifests/sample_700_coarse_manifest.csv
storage/vision/datasets/classification/manifests/sample_700_coarse_manifest_summary.csv
```

샘플링 기준:

```text
per_category: 700
seed: 42
train/val/test: 70/20/10
```

생성 요약:

```text
sampled_rows: 6481
category_count: 24
split_counts: {'train': 4530, 'val': 1291, 'test': 660}
```

해석:

- 상위 라벨 4개 기준으로 최대 700개씩 샘플링한다.
- 700개 이상 보유한 상위 라벨은 700개만 랜덤 추출한다.
- 700개 미만 라벨은 가능한 전체를 사용한다.
- 일부 카테고리는 원본 수가 매우 적다. 예: `TS_차대이륜차_영상_회전교차로`는 3개뿐이다.
- 현재는 class imbalance를 그대로 기록하고 진행한다.
- 이후 필요 시 oversampling, class weight, weighted sampler를 비교한다.

다음 단계:

```text
샘플링된 영상 파일만 다운로드
각 영상에서 대표 프레임 추출
프레임 기반 classification 학습 manifest 생성
```

다음 구현 후보:

```text
etl/vision/download_sampled_media.py
etl/extract_classification_frames.py
ai/vision/train_classifier.py
```

## 15. 상위 4개 라벨 기준으로 학습 방향 변경

기존 세부 24개 카테고리는 카테고리별 데이터 수 편차가 크다.

예:

```text
TS_차대이륜차_영상_회전교차로: 3
TS_차대자전거_영상_자전거도로: 12
TS_차대차_영상_직선도로: 5500
```

따라서 1차 학습은 세부 카테고리 24개가 아니라 상위 사고 유형 4개로 진행한다.

상위 라벨:

```text
차대차
차대보행자
차대이륜차
차대자전거
```

Manifest 변경:

```text
label        : 기존 세부 라벨 유지
coarse_label : 1차 학습에 사용할 상위 라벨
```

수정 파일:

```text
etl/vision/build_classification_manifest.py
etl/vision/sample_classification_dataset.py
```

`build_classification_manifest.py`는 category에서 `coarse_label`을 추출한다.

```text
TS_차대차_영상_직선도로 → coarse_label=차대차
TS_차대보행자_영상_횡단보도없음 → coarse_label=차대보행자
TS_차대이륜차_영상_직선도로 → coarse_label=차대이륜차
TS_차대자전거_영상_직선도로 → coarse_label=차대자전거
```

`sample_classification_dataset.py`는 기본적으로 `coarse_label` 기준으로 샘플링한다.

실행 결과:

```text
output_path: storage/vision/datasets/classification/manifests/sample_700_coarse_manifest.csv
summary_path: storage/vision/datasets/classification/manifests/sample_700_coarse_manifest_summary.csv
sampled_rows: 2800
label_count: 4
split_counts: {'train': 1956, 'val': 560, 'test': 284}
```

상위 라벨별 원본/샘플 수:

```text
차대보행자: original=763, sampled=700, train=489, val=140, test=71
차대이륜차: original=1928, sampled=700, train=489, val=140, test=71
차대자전거: original=855, sampled=700, train=489, val=140, test=71
차대차: original=12277, sampled=700, train=489, val=140, test=71
```

결론:

```text
1차 본 학습은 sample_700_coarse_manifest.csv 기준으로 진행한다.
세부 24개 카테고리는 2차 실험 또는 성능 안정화 이후 검토한다.
```

다음 단계:

```text
1. sample_700_coarse_manifest.csv 기준으로 다운로드
2. 다운로드한 영상에서 대표 프레임 추출
3. frame-level classification manifest 생성
4. ResNet18 baseline 학습 코드 준비
```

## 16. 샘플 영상 dry-run 다운로드 결과

생성 파일:

```text
etl/vision/download_sampled_media.py
```

목적:

- `sample_700_coarse_manifest.csv` 전체 2,800개를 RunPod에서 받는다.
- 먼저 상위 라벨별 1개씩만 다운로드해 Drive URL, 저장 경로, 파일명 정책을 검증한다.

실행:

```powershell
cd D:\dev\SKN27-FINAL-3Team
python etl\vision\download_sampled_media.py --per-label 1 --split train
```

생성 결과:

```text
storage/vision/datasets/classification/manifests/dryrun_download_manifest.csv
storage/vision/datasets/classification/raw_videos/{coarse_label}/*.mp4
```

실행 결과:

```text
download_rows: 4
label_counts: {'차대보행자': 1, '차대이륜차': 1, '차대자전거': 1, '차대차': 1}
download_status_counts: {'downloaded': 4}
```

다운로드된 라벨:

```text
차대보행자 1개
차대이륜차 1개
차대자전거 1개
차대차 1개
```

주의:

- 로컬 `.venv` Python launcher가 일부 명령에서 깨지는 현상이 있어, 표준 라이브러리 기반 스크립트는 Codex 번들 Python으로 실행해도 된다.
- `download_sampled_media.py`는 `gdown` 의존성을 제거하고 `urllib` 기반으로 Google Drive `uc?id=...` 파일 URL을 직접 다운로드한다.
- 대량 다운로드는 로컬이 아니라 RunPod 또는 S3/Network Volume 기준으로 진행하는 것이 좋다.

다음 단계:

```text
etl/extract_classification_frames.py
```

역할:

```text
dryrun_download_manifest.csv 읽기
다운로드된 영상에서 대표 프레임 추출
storage/vision/datasets/classification/frames/{coarse_label}/ 에 저장
frame_classification_manifest.csv 생성
```

## 13. 프레임 추출 dry-run 결과

작성일: 2026-06-26

`etl/vision/extract_training_frames.py`를 추가하여 다운로드된 영상 manifest를 frame-level classification manifest로 변환했다.

실행 명령:

```powershell
cd D:\dev\SKN27-FINAL-3Team
.\.venv\Scripts\python.exe etl\vision\extract_training_frames.py `
  --input storage\vision\datasets\classification\manifests\dryrun_download_manifest.csv `
  --output storage\vision\datasets\classification\manifests\frame_manifest_dryrun.csv `
  --frames-per-video 5 `
  --overwrite
```

입력:

```text
storage/vision/datasets/classification/manifests/dryrun_download_manifest.csv
```

출력:

```text
storage/vision/datasets/classification/manifests/frame_manifest_dryrun.csv
storage/vision/datasets/classification/manifests/frame_manifest_dryrun_summary.csv
storage/vision/datasets/classification/frames/{coarse_label}/{asset_id}/*.jpg
```

검증 결과:

```text
video_rows: 4
frame_rows: 20
label_counts: {'차대보행자': 5, '차대이륜차': 5, '차대자전거': 5, '차대차': 5}
split_counts: {'train': 20}
extract_status_counts: {'extracted': 20}
```

주의:

- Windows에서 `cv2.imwrite()`는 한글 경로 저장에 실패할 수 있어 `cv2.imencode()` 후 bytes 저장 방식으로 구현했다.
- 현재는 균등 샘플링 방식이다.
- 실제 학습에서는 영상 1개당 1장, 3장, 5장 중 어떤 기준이 적절한지 실험 결과와 비용을 비교한다.
- 생성된 영상/프레임/CSV manifest는 대용량 산출물이므로 Git 추적에서 제외한다.

다음 단계:

```text
1. frame_manifest_dryrun.csv를 읽는 classification Dataset 구현
2. ResNet18 baseline train_classifier.py 작성
3. 로컬에서 20장 기준 overfit/dry-run 확인
4. RunPod에서 sample_700_coarse_manifest.csv 기반 다운로드·프레임 추출·학습 실행
```

## 14. Classifier baseline dry-run 결과

작성일: 2026-06-26

`ai/vision/train_classifier.py`를 추가하여 frame-level manifest를 입력으로 받는 ResNet18 baseline 학습 루프를 구현했다.

실행 명령:

```powershell
cd D:\dev\SKN27-FINAL-3Team
.\.venv\Scripts\python.exe ai\vision\train_classifier.py `
  --manifest storage\vision\datasets\classification\manifests\frame_manifest_dryrun.csv `
  --epochs 1 `
  --batch-size 4 `
  --image-size 128 `
  --freeze-backbone `
  --output-dir storage\vision\models\classification_dryrun
```

로컬 dry-run 결과:

```text
run_id: vision_cls_20260626_172935
device: cpu
labels: {'차대보행자': 0, '차대이륜차': 1, '차대자전거': 2, '차대차': 3}
rows: train=15 val=5 test=0
epoch=1 train_loss=1.554665 train_acc=0.000000 val_loss=1.414263 val_acc=0.200000
```

생성 산출물:

```text
storage/vision/models/classification_dryrun/vision_cls_20260626_172935/model.pt
storage/vision/models/classification_dryrun/vision_cls_20260626_172935/class_mapping.json
storage/vision/models/classification_dryrun/vision_cls_20260626_172935/run_config.json
storage/vision/models/classification_dryrun/vision_cls_20260626_172935/training_history.csv
```

판정:

```text
frame-level manifest -> Dataset -> DataLoader -> ResNet18 -> loss 계산 -> optimizer step -> 결과 저장까지 정상 동작
```

주의:

- 현재 dry-run은 20장뿐이므로 accuracy는 성능 지표로 해석하지 않는다.
- 목적은 학습 코드가 끝까지 실행되는지 확인하는 것이다.
- 로컬에서는 `pretrained=False`로 실행했다. RunPod 본 학습에서는 `--pretrained` 옵션 사용을 검토한다.
- 현재 dry-run manifest가 train split만 가지고 있어 `--val-ratio-if-missing 0.25` 기준으로 train 일부를 val로 분리했다.

다음 단계:

```text
1. 라벨별 5~10개 영상으로 dry-run 규모 확대
2. frames_per_video 1/3/5 비교
3. RunPod에서 sample_700_coarse_manifest.csv 기준 다운로드·프레임 추출
4. ResNet18 pretrained + freeze_backbone 기준 첫 GPU 학습
5. training_history, run_config, class_mapping을 실험별로 비교
```

## 23. RunPod 학습용 Pod 선택 기준

이번 단계는 단일 영상 POC가 아니라 라벨별 700개, 총 2,800개 영상 기반 학습이다. 따라서 RunPod 선택 기준은 POC 기준과 분리한다.

### 23.1 실행 목표

```text
sample_700_coarse_manifest.csv
-> 라벨별 700개 영상 다운로드
-> 영상 1개당 8프레임 추출
-> frame_manifest_train_700_f8.csv 생성
-> ResNet18 pretrained baseline 학습
-> training_history.csv / model.pt / run_config.json 저장
```

예상 프레임 수:

```text
2,800 videos * 8 frames = 최대 22,400 training frames
```

### 23.2 권장 Pod 기준

| 항목 | 권장 기준 | 이유 |
|---|---|---|
| GPU 개수 | 1개 | ResNet18 baseline 첫 학습은 multi-GPU가 필요하지 않음 |
| GPU VRAM | 최소 16GB, 권장 24GB 이상 | batch size 32, image size 224 기준 안정적 실행 |
| GPU 후보 | RTX A5000, RTX 4090, A40, L40 계열 | 비용 대비 단일 GPU 학습에 적합 |
| 피해야 할 선택 | 너무 저렴한 VRAM 8GB 이하 GPU | batch size 조정이 필요하고 학습 실패 가능성 증가 |
| Pod template | Runpod PyTorch 2.4.0 또는 PyTorch/CUDA 포함 템플릿 | torch/torchvision/CUDA 환경 준비 시간 단축 |
| GPU count | 1 | 비용 절감, 현재 코드가 단일 GPU 기준 |
| Pricing | On-Demand | 실험 후 stop 가능, 장기 예약 불필요 |
| Jupyter Notebook | ON | `vision_training_runpod_full_pipeline.ipynb` 실행 및 결과 확인용 |
| SSH Terminal | 가능하면 ON | 압축 해제, 용량 확인, 긴 로그 확인에 유용 |
| Disk | 최소 150GB, 권장 200GB 이상 | 2,800개 영상 + 추출 프레임 + 모델 결과 저장 필요 |
| Encrypt volume | 샘플/공개 데이터는 OFF 가능, 민감 데이터는 ON | 실제 사고/개인정보 포함 시 보안 필요 |

### 23.3 현재 추천 설정

```text
Pod template: Runpod Pytorch 2.4.0
Image: runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04
GPU count: 1
GPU class: VRAM 24GB 이상이면 우선 선택
Pricing: On-Demand
Start Jupyter notebook: ON
SSH terminal access: ON 가능 시 ON
Disk: 200GB 이상 권장
```

### 23.4 비용 절감 기준

- 전체 2,800개 학습 전에는 코드와 manifest가 로컬에서 검증되어 있어야 한다.
- RunPod에서는 `scripts/vision/vision_training_resnet18_runpod.ipynb ?? scripts/vision/vision_model1_yolo_tracking_videomae_runpod.ipynb`를 기준으로 실행한다.
- 학습 완료 후 아래 산출물을 확인하면 Pod를 stop한다.

```text
storage/vision/datasets/classification/manifests/train_700_download_manifest.csv
storage/vision/datasets/classification/manifests/frame_manifest_train_700_f8.csv
storage/vision/models/classification/vision_cls_*/model.pt
storage/vision/models/classification/vision_cls_*/training_history.csv
storage/vision/models/classification/vision_cls_*/run_config.json
```

### 23.5 RunPod에서 실행할 노트북

```text
/workspace/SKN27-FINAL-3Team/scripts/vision/vision_training_resnet18_runpod.ipynb ?? scripts/vision/vision_model1_yolo_tracking_videomae_runpod.ipynb
```

Run All 실행 순서:

```text
requirements 설치
-> sample_700_coarse_manifest.csv 확인
-> 2,800개 영상 다운로드
-> 8프레임 추출
-> ResNet18 baseline 학습
-> training_history/model/run_config 확인
```

### 23.6 재현성 고정 기준

동일 데이터와 동일 파라미터로 학습했을 때 결과 비교가 가능하도록 아래 값을 고정한다.

| 항목 | 고정값/기준 | 반영 위치 |
|---|---|---|
| seed | 42 | `train_classifier.py --seed 42`, `vision_training_runpod_full_pipeline.ipynb` |
| batch size | 32 | RunPod 학습 노트북의 `BATCH_SIZE` |
| frames per video | 8 | RunPod 학습 노트북의 `FRAMES_PER_VIDEO` |
| image size | 224 | RunPod 학습 노트북의 `IMAGE_SIZE` |
| learning rate | 0.001 | RunPod 학습 노트북의 `LEARNING_RATE` |
| deterministic | True | `--deterministic` 옵션 |
| DataLoader shuffle | seed 기반 generator 사용 | `train_classifier.py` |
| CUDA/CUDNN | deterministic 설정 적용 | `train_classifier.py` |

주의: GPU/CUDA 연산은 환경과 라이브러리 버전에 따라 완전한 bit-level 동일성을 보장하지 못할 수 있다. 그래도 seed, DataLoader generator, deterministic 옵션을 고정해 실험 간 변동을 최소화한다.
## 24. 모델별 RunPod 실행 기준 업데이트

현재 Vision/DL 실험은 모델별 노트북으로 분리한다.

| 목적 | 실행 노트북 | 권장 GPU/설정 |
|---|---|---|
| clip 전략 샘플 테스트 | `scripts/vision/vision_clip_strategy_sample_test_runpod.ipynb` | RTX A5000 24GB 이상, 라벨별 1개부터 실행 |
| ResNet18 baseline | `scripts/vision/vision_training_resnet18_runpod.ipynb` | RTX A5000 24GB 이상, batch size 32 기준 |
| VideoMAE 원본 영상 baseline | `scripts/vision/vision_training_videomae_runpod.ipynb` | RTX A5000 24GB 이상, batch size 1~2 권장 |
| YOLO/ByteTrack + 5초 clip + VideoMAE | `scripts/vision/vision_model1_yolo_tracking_videomae_runpod.ipynb` | RTX A5000 24GB 이상, 가능하면 A40/L40/4090 |
| YOLO/ByteTrack + Qwen2.5-VL | `scripts/vision/vision_model2_yolo_tracking_qwen_vl_runpod.ipynb` | 최소 24GB VRAM, 가능하면 40GB 이상 |
| 서비스 통합 흐름 검증 | `scripts/vision/vision_model3_service_pipeline_runpod.ipynb` | A5000급이면 가능. Qwen까지 포함하면 40GB 이상 권장 |

VideoMAE와 Qwen2.5-VL은 ResNet18보다 메모리 사용량이 크다. VideoMAE는 batch size 1~2부터 시작하고, Qwen2.5-VL은 clip 길이와 fps를 작게 유지한다.

사고 후보 clip 기준은 전체 영상이 아니라 사고 후보 지점 중심 총 5초이다. 구성은 사고 전 약 2.5초와 사고 후 약 2.5초이며, VideoMAE는 해당 clip에서 16프레임을 균등 샘플링한다.

