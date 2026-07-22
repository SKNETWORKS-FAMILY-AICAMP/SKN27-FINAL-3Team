# 사고 유형 지도학습 방향 전환 보고서

- 작성일: 2026-07-20
- 대상 분류: 차대차, 차대보행자, 차대이륜차, 차대자전거
- 목표: 라벨이 확실한 영상으로 사고 유형 분류기를 학습하고, 라벨이 없는 신규 영상의 사고 유형을 예측

## 1. 수정된 결론

서비스 입력에 사고 유형 라벨이 항상 존재한다고 가정하지 않는다. 현재 데이터셋의 라벨은 신뢰할 수 있으므로 **최종 결과에 복사하는 값이 아니라 모델이 사고 유형을 학습하기 위한 정답**으로 사용한다.

권장 흐름은 다음과 같다.

```text
라벨이 확실한 4개 사고 유형 영상
→ train/validation/test 분리
→ VideoMAE 4분류 파인튜닝
→ 검증 성능이 가장 좋은 체크포인트 저장
→ 라벨이 없는 신규 영상 입력
→ 학습 모델이 사고 유형과 confidence 예측
→ YOLO/Qwen이 객체·충돌 장면·상황 설명 근거 생성
→ Supervisor 전달
```

최종 사고 유형은 학습된 분류기의 예측이어야 한다. 데이터 라벨은 학습과 평가에서만 사용하며 신규 영상 추론에는 사용할 수 없다.

## 2. 모델별 역할

### VideoMAE 사고 유형 분류기

- 4개 사고 유형 라벨을 실제로 학습한다.
- 영상의 시간적 변화와 여러 프레임을 함께 사용한다.
- 신규 영상에 `predicted_accident_target`과 confidence를 제공한다.
- 저장된 체크포인트를 로컬·RunPod·Supervisor가 공통으로 사용한다.

### YOLO

- 차량, 사람, 자전거, 이륜차 등 객체 위치를 검출한다.
- 사고 유형을 직접 학습한 모델이 아니라 분류 결과의 시각적 근거를 제공한다.
- 카테고리별 비교에서 선택한 기존 가중치는 객체 검출 단계에 사용한다.

### Qwen/LLaVA

- 충돌 순간, 사고 가시성, 도로·조명·날씨와 사고 상황을 설명한다.
- 독립 사고 유형 추론값은 `vlm_predicted_accident_target`으로 남겨 보조 검수에 사용한다.
- 학습 분류기 결과와 다르면 불일치 사례로 기록한다.

### 데이터 라벨

- `labeled_accident_target`으로 평가 결과에만 기록한다.
- 모델 입력 또는 서비스 최종값으로 복사하지 않는다.
- 학습 손실과 정확도, 혼동행렬 계산의 정답으로 사용한다.

## 3. 기존 known-label 방향을 사용하지 않는 이유

기존 방향은 입력 라벨을 `predicted_accident_target`에 그대로 복사했다. 이 경우 현재 데이터 결과는 안정적으로 보이지만 라벨 없는 신규 영상을 분류할 수 없고 정확도가 인위적으로 100%가 되는 라벨 누수가 발생한다.

수정된 방향에서는 다음과 같이 분리한다.

```text
labeled_accident_target   = 평가 정답
predicted_accident_target = 학습된 VideoMAE 예측
trained_prediction_confidence = 학습 모델 신뢰도
vlm_predicted_accident_target = VLM 보조 예측
```

## 4. 구현 현황

프로젝트에는 이미 필요한 공통 코드가 있다.

- `ai/vision/train_videomae_classifier.py`: 4분류 VideoMAE 파인튜닝
- `ai/vision/run_to_supervisor.py`: 학습 체크포인트 기반 신규 영상 추론
- `etl/vision/build_training_clips.py`: 사고 중심 학습 클립 생성
- `etl/vision/sample_classification_dataset.py`: 카테고리별 표본 및 split 생성

따라서 새로운 학습 프레임워크를 추가하지 않고 기존 코드를 공통 경로로 사용한다. 카테고리별 노트북은 별도로 모델을 학습하지 않으며, 하나의 4분류 체크포인트를 불러와 해당 카테고리 평가 데이터를 분석한다.

## 5. 앞으로의 진행 계획

### 1단계. 데이터와 split 검증

- 네 카테고리의 라벨 수와 파일 존재 여부를 확인한다.
- train/validation/test 비율을 고정한다.
- 같은 원본 사고의 파생 영상이나 클립이 서로 다른 split에 들어가지 않도록 `asset_id` 또는 원본 사고 단위로 묶는다.
- 클래스 불균형을 확인하고 필요하면 카테고리별 표본 수를 맞춘다.

### 2단계. RunPod GPU 학습

공통 manifest로 VideoMAE를 한 번 학습한다.

```bash
python ai/vision/train_videomae_classifier.py \
  --manifest storage/vision/datasets/classification/manifests/train_100_raw_video_manifest.csv \
  --output-dir storage/vision/models/videomae_raw_video/per_label_100 \
  --epochs 3 \
  --batch-size 2 \
  --device cuda \
  --show-progress
```

학습 결과는 timestamp별 디렉터리에 저장하며 `best_val_accuracy`가 가장 높은 체크포인트를 선택한다. 더 긴 학습은 3 epoch 결과와 과적합 여부를 확인한 뒤 진행한다.

### 3단계. 카테고리별 평가

수정된 네 노트북이 동일한 최적 체크포인트를 사용한다.

- 차대차 노트북: 차대차 평가 행의 예측과 confidence 확인
- 차대보행자 노트북: 차대보행자 평가 행 확인
- 차대이륜차 노트북: 차대이륜차 평가 행 확인
- 차대자전거 노트북: 차대자전거 평가 행 확인

카테고리별 노트북은 정답을 복사하지 않고 VideoMAE 예측을 `predicted_accident_target`에 저장한다. VLM의 독립 판단은 별도 필드에 보존한다.

### 4단계. 오류 분석

- 전체 정확도와 카테고리별 recall을 계산한다.
- 혼동행렬로 어떤 카테고리가 서로 자주 혼동되는지 확인한다.
- 학습 모델과 VLM이 모두 틀린 사례, 둘 중 하나만 틀린 사례를 나눠 검수한다.
- contact sheet와 원본 영상을 연결해 프레임 부족, 가림, 야간, 객체 크기 문제를 분류한다.

### 5단계. 신규 영상 추론

테스트셋과 겹치지 않는 새 영상으로 다음 흐름을 확인한다.

```bash
python ai/vision/run_to_supervisor.py NEW_VIDEO.mp4 \
  --checkpoint storage/vision/models/.../videomae_cls_YYYYMMDD_HHMMSS
```

Supervisor에는 학습 모델의 분류 결과와 YOLO/Qwen 근거를 함께 전달한다.

### 6단계. 운영 기준 확정

- confidence 임계값은 validation 결과로 결정한다.
- 임계값 미만은 `uncertain` 또는 사용자 확인으로 처리한다.
- 새 데이터가 쌓이면 라벨 검수 후 재학습 후보에 추가한다.
- 운영 모델 버전과 학습 manifest 버전을 결과에 기록한다.

## 6. 장점

- 라벨 없는 신규 영상을 실제로 분류할 수 있다.
- 모델의 사고 유형 성능을 정직하게 측정할 수 있다.
- 시간 정보를 사용하는 VideoMAE가 단일 프레임보다 충돌 전후 맥락을 반영할 수 있다.
- YOLO의 객체 근거와 Qwen의 상황 설명을 결합해 결과를 설명할 수 있다.
- 하나의 공통 체크포인트를 네 카테고리와 Supervisor가 공유해 동작이 일관된다.
- 학습·평가·서비스 추론의 역할이 명확해진다.

## 7. 단점과 위험 및 대처 방안

### 데이터 누수

같은 사고의 유사 클립이 train과 test에 동시에 들어가면 성능이 과대평가된다.

**대처:** 파일 단위가 아니라 원본 사고 또는 `asset_id` 단위로 split하고 중복 해시를 검사한다.

### 라벨 오류

잘못된 라벨은 모델이 잘못된 규칙을 학습하게 만든다.

**대처:** 무작위 표본과 모델 불일치 사례를 사람이 재검수하고 수정 이력을 보존한다.

### 클래스 불균형

차대차처럼 수가 많은 범주로 예측이 치우칠 수 있다.

**대처:** 카테고리별 표본 수를 맞추고 macro F1·카테고리별 recall·혼동행렬을 함께 본다.

### 장면 중심이 아닌 배경 학습

모델이 사고 유형 대신 촬영 위치, 폴더별 화질, 자막 같은 우연한 특징을 학습할 수 있다.

**대처:** 출처별 split을 점검하고 사고 중심 클립, 다양한 촬영 환경, augmentation을 사용한다. Grad-CAM 또는 오류 영상 검수로 모델이 본 근거를 확인한다.

### 낮은 현재 성능

기존 로컬 실험에서 100개/라벨 VideoMAE의 최고 validation accuracy는 약 56.25%였다. 현재 가중치를 곧바로 운영 모델로 확정하기에는 부족할 수 있다.

**대처:** 데이터 증가, 사고 중심 클립, 학습률·freeze/unfreeze 비교, class balance를 순차적으로 검증한다. test 성능과 카테고리별 recall이 기준에 도달하기 전에는 보조 판단으로 사용한다.

### 과적합

표본이 적은 상태에서 epoch를 늘리면 train accuracy만 높아질 수 있다.

**대처:** validation 기반 early stopping과 최적 체크포인트 저장을 사용하고 test는 최종 1회 평가에만 사용한다.

### 낮은 신뢰도 예측의 오사용

모델은 항상 네 클래스 중 하나를 선택하므로 확신이 없어도 단정적으로 보일 수 있다.

**대처:** confidence와 상위 예측을 함께 저장하고 validation에서 결정한 임계값 미만은 `uncertain`으로 처리한다.

### 체크포인트 불일치

로컬과 RunPod가 서로 다른 가중치를 사용하면 결과가 재현되지 않는다.

**대처:** `VISION_TRAINED_CLASSIFIER_CHECKPOINT` 또는 자동 최적 체크포인트 탐색을 사용하고 결과에 체크포인트 경로와 모델 버전을 기록한다.

### 계산 비용

VideoMAE 학습과 영상별 추론은 단일 프레임 모델보다 느리고 GPU 메모리를 더 사용한다.

**대처:** RunPod GPU에서 학습하고, 모델은 한 번만 로드해 여러 영상을 처리하며, 프레임 수와 batch size를 검증 범위에서 조정한다.

## 8. 검증 통과 기준

- train/validation/test 간 원본 사고 중복이 없다.
- 네 카테고리가 모두 train과 validation/test에 존재한다.
- 체크포인트와 class mapping이 함께 저장된다.
- 전체 accuracy뿐 아니라 macro F1과 카테고리별 recall을 보고한다.
- 신규 영상 결과에 예측 클래스, confidence, 체크포인트 버전이 기록된다.
- 낮은 confidence 결과가 사용자에게 확정 사실처럼 전달되지 않는다.
- Supervisor가 라벨이 아니라 학습 모델 예측을 사용한다.

## 9. 최종 권고

사용자가 제안한 지도학습 방향이 프로젝트의 실제 서비스 목적에 더 적합하다. 기존 라벨은 모델의 정답으로 사용하고, 최종 사고 유형은 학습된 VideoMAE가 신규 영상에서 예측해야 한다.

다만 현재 확인된 최고 validation accuracy가 약 56.25%이므로 기존 가중치를 즉시 확정 모델로 배포하지 않는다. 우선 RunPod에서 동일한 100개/카테고리 데이터로 재현 학습하고, 차대차와 차대보행자 오류를 검수한 뒤 데이터·클립·학습 설정을 개선한다. 목표 성능에 도달하기 전까지는 모델 결과를 보조 판단으로 표시하고 confidence가 낮은 경우 사용자 확인을 요구하는 것이 안전하다.
