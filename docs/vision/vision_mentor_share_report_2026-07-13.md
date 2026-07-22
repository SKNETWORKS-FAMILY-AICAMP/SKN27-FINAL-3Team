# Vision/DL 분석 진행 공유 보고서

## 1. 공유 목적

본 문서는 Vision/DL 파트의 현재 분석 방향, 최근 실험 결과, 발생한 이슈와 해석, 다음 진행 계획을 멘토님께 공유하기 위한 보고서다. 기존 제출용 학습결과서와 별도로, 현재 의사결정 흐름을 빠르게 확인할 수 있도록 정리했다.

## 2. 현재 분석 방향

현재 Vision/DL 파트는 교통사고 블랙박스 영상을 입력으로 받아 상위 사고 유형을 분류하고, 분석 결과를 Supervisor Agent와 후속 법률/판례 Agent가 사용할 수 있는 구조로 정리하는 것을 목표로 한다.

현재 기준 모델 역할은 다음과 같다.

| 모델 | 역할 | 현재 판단 |
|---|---|---|
| VideoMAE | 사고 유형 분류 | 핵심 학습 모델 |
| Qwen2.5-VL | 장면 설명, 도로/날씨/시야 상태 추출 | 설명 보조 모델 |
| YOLOv8 + ByteTrack | 객체 탐지/추적, 긴 영상 사고 후보 구간 추출 | 고도화 방향 |
| ResNet18 | frame-level baseline | 기준선 모델 |

1차 MVP에서는 사용자가 사고 지점이 포함된 5~30초 영상을 업로드한다는 전제를 둔다. 따라서 긴 영상에서 사고 지점을 자동으로 찾는 YOLO/ByteTrack은 후순위 고도화 항목으로 분리하고, 현재는 raw video 기반 VideoMAE 분류 성능 확인에 집중하고 있다.

## 3. 최근 실험 요약

### 3.1 VideoMAE raw video 기반 실험

기존에는 YOLO/ByteTrack 기반 5초 clip을 생성한 뒤 VideoMAE 학습을 진행했다. 그러나 clip 생성 과정에서 사고 장면이 누락될 가능성이 있어, 최근에는 원본 10초 영상을 자르지 않고 그대로 사용하는 raw video 기반 실험을 추가했다.

| 실험 | 데이터 | 설정 | train/val/test | 주요 결과 |
|---|---|---|---:|---|
| raw video 50 | 라벨별 50개 | freeze=True, lr=0.0001, epoch=5 | 140 / 40 / 20 | best test acc 약 0.450 |
| raw video 100 | 라벨별 100개 | freeze=True, lr=0.0001, epoch=5 | 280 / 80 / 40 | best val acc 약 0.550, best test acc 약 0.450 |
| raw video 100 | 라벨별 100개 | freeze=False, lr=0.00001, epoch=5 | 280 / 80 / 40 | best test acc 약 0.500 |

현재까지는 라벨별 100개 실험에서 unfreeze 설정이 test accuracy 기준으로 가장 높았지만, 표본 수가 아직 작아 최종 판단에는 라벨별 700개 실험 결과가 필요하다.

### 3.2 epoch 50 실험과 Early Stopping

라벨별 100개 샘플 실험에서 epoch를 50으로 설정했으나, 실제 출력은 약 10 epoch 전후에서 종료되었다.

이는 설정된 최대 epoch까지 모두 학습한 것이 아니라, validation 성능 개선이 일정 epoch 이후 멈춰 early stopping으로 종료된 것으로 판단한다. 즉, epoch=50은 최대 학습 가능 횟수이고, early stopping 조건이 먼저 만족되면 그 전에 학습이 종료된다.

현재 해석은 다음과 같다.

- epoch=50으로 설정했으나 validation 성능 개선이 일정 epoch 이후 멈춰 early stopping으로 10 epoch 전후에서 종료되었다.
- train 성능과 validation 성능의 차이를 보면 과적합 가능성이 있다.
- 후속 실험에서는 learning rate, freeze 여부, weight decay, early stopping patience 값을 조정할 필요가 있다.

## 4. Qwen2.5-VL 보조 분석 결과

라벨별 100개 raw video split manifest에서 Qwen2.5-VL 장면 설명 결과를 일부 확인했다. 현재 로컬 output 기준으로는 라벨별 3개씩, 총 12개 JSON 결과가 생성되어 있다.

| 항목 | 결과 |
|---|---|
| 확인된 출력 수 | 12개 |
| 라벨 분포 | 차대보행자 3, 차대이륜차 3, 차대자전거 3, 차대차 3 |
| JSON 유효성 | 12개 모두 `qwen_json_valid=True` |
| 출력 언어 | 영어 또는 영어 중심 혼합 출력 |
| 사고 장면 인식 | 8개는 사고/위험 상황 설명, 4개는 사고 미탐지 또는 불명확 |

Qwen2.5-VL은 장면 설명과 도로/날씨/시야 상태 추출은 가능하지만, 사고 장면을 항상 안정적으로 식별하지는 못했다. 따라서 사고 유형 확정은 VideoMAE 결과를 우선하고, Qwen은 설명 보조와 불확실성 기록에 사용하는 방향이 적절하다.

## 5. 현재 이슈

| 이슈 | 현재 대응 |
|---|---|
| 5초 clip에서 사고 장면 누락 가능 | raw video 전체 입력 실험으로 원인 분리 |
| VideoMAE 32프레임 입력 시 구조 불일치 | 현재 체크포인트 기준 frame_count=16 유지 |
| Qwen 출력 언어가 영어 중심 | 한국어 재작성 또는 후처리 Agent 필요 |
| Qwen 사고 판단 단정 위험 | Supervisor 전달 전 JSON 유효성/불확실성 검증 필요 |
| epoch 50 실험 조기 종료 | early stopping으로 판단, patience/lr/freeze 조정 예정 |

## 6. 다음 진행 계획

1. 라벨별 700개, 총 2,800개 raw video split 실험 실행
-> 학습에 활용할 데이터가 부족했다고 판단하여 700개의 원본 데이터를 활용하여 분석을 진행해볼 예정
2. freeze=True / freeze=False 조건 비교
3. learning rate와 weight decay 조합 추가 실험
