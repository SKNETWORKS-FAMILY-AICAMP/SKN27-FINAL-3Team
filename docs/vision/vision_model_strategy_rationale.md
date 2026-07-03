# Vision/DL 모델 구성 의도 정리

## 목적

현재 Vision/DL은 단일 모델로 모든 문제를 해결하는 구조가 아니라 역할별 모델을 분리하는 구조다.

- 사고 후보 구간 추출
- 사고 유형 분류
- 사고 장면 설명/JSON 생성
- Supervisor 및 법률/판례 Agent로 전달할 근거 생성

## 왜 기존 모델만 사용하지 않았는가

ResNet18 또는 VideoMAE 하나만 사용하면 사고 유형 분류 정확도는 볼 수 있다. 하지만 실제 서비스에서는 라벨 하나만으로 부족하다.

필요한 출력은 다음과 같다.

- 사고 후보 시점
- 사고 전후 상황
- 객체 위치 변화
- 사고 장면 설명
- Supervisor handoff JSON
- 법률/판례 Agent가 참고할 수 있는 시각 근거

따라서 모델을 하나로 몰지 않고 역할별로 분리했다.

## 모델별 역할

| 구분 | 구성 | 주 역할 | 선택 이유 |
|---|---|---|---|
| 1차 모델 | YOLO + ByteTrack + VideoMAE | 사고 후보 구간 추출 및 사고 유형 분류 | YOLO/Tracking은 객체 변화와 사고 후보 시점 추정에 강하고, VideoMAE는 짧은 clip의 행동/상황 분류에 적합 |
| 2차 모델 | YOLO + ByteTrack + Qwen2.5-VL | 사고 장면 설명, JSON, 보고서 초안 생성 | Qwen2.5-VL은 분류보다 설명 생성에 적합. 과실비율 확정이 아니라 관찰 요약과 근거 생성용 |
| 서비스 구조 | YOLO + ByteTrack + Qwen2.5-VL + 룰 기반 검증 | 최종 서비스 출력 검증 및 Supervisor 전달 | 생성형 모델 출력만 믿지 않고 탐지 결과, 룰, 스키마 검증을 거쳐 Agent handoff 안정성 확보 |
| 보조 baseline | ResNet18 | frame-level 사고 유형 분류 baseline | 비용이 낮고 빠르게 기준 성능을 확인 가능. 최종 서비스 모델이라기보다 비교 기준 |

## 사고 후보 clip 기준

VideoMAE 학습/추론용 입력은 원본 전체 영상이 아니라 사고 후보 지점 중심 clip으로 가져간다.

- 기준: 사고 후보 지점 중심 총 5초
- 구성: 사고 전 약 2.5초 + 사고 후 약 2.5초
- 입력: 5초 clip에서 16프레임 균등 샘플링

전체 블랙박스 영상에는 사고와 무관한 주행 구간이 많다. 전체 영상을 그대로 학습하면 모델이 사고 순간보다 배경, 도로, 날씨, 차량 종류 같은 우연한 특징을 학습할 수 있다.

## 현재 구현 상태

| 영역 | 파일 | 상태 |
|---|---|---|
| 5초 학습 clip 생성 | `etl/vision/build_training_clips.py` | 구현됨 |
| POC clip 후보 생성 | `etl/vision/build_clip_candidates.py` | 5초 기준으로 수정됨 |
| clip 전략 샘플 테스트 | `scripts/vision/vision_clip_strategy_sample_test_runpod.ipynb` | center vs yolo_track 비교용 |
| VideoMAE 학습 | `ai/vision/train_videomae_classifier.py` | clip manifest 입력 가능 |
| ResNet18 baseline | `ai/vision/train_classifier.py` | 유지 |
| Qwen2.5-VL 분석 노트북 | `scripts/vision/vision_model2_yolo_tracking_qwen_vl_runpod.ipynb` | 추론/JSON 생성용 |
| 서비스 흐름 노트북 | `scripts/vision/vision_model3_service_pipeline_runpod.ipynb` | 최종 출력 확인용 |

## 모델별 실행 노트북

| 목적 | 노트북 |
|---|---|
| clip 전략 샘플 테스트 | `scripts/vision/vision_clip_strategy_sample_test_runpod.ipynb` |
| ResNet18 frame baseline | `scripts/vision/vision_training_resnet18_runpod.ipynb` |
| VideoMAE 원본 영상 baseline | `scripts/vision/vision_training_videomae_runpod.ipynb` |
| YOLO/ByteTrack + 5초 clip + VideoMAE | `scripts/vision/vision_model1_yolo_tracking_videomae_runpod.ipynb` |
| YOLO/ByteTrack + Qwen2.5-VL 설명/JSON | `scripts/vision/vision_model2_yolo_tracking_qwen_vl_runpod.ipynb` |
| 서비스 통합 흐름 검증 | `scripts/vision/vision_model3_service_pipeline_runpod.ipynb` |

## RunPod GPU 선택 기준

| 작업 | 권장 GPU | 이유 |
|---|---|---|
| clip 전략 샘플 테스트 | RTX A5000 24GB 이상 또는 RTX 4090 | YOLO/ByteTrack과 영상 clip 생성 검증. 대량 학습은 아님 |
| ResNet18 baseline | RTX A5000 24GB 이상 | batch size 32, image size 224 기준 안정적 |
| VideoMAE 5초 clip 학습 | RTX A5000 24GB 이상, 가능하면 A40/L40/4090 | VideoMAE는 ResNet18보다 메모리 사용량이 큼. batch size 1~2 권장 |
| Qwen2.5-VL 추론 | 최소 24GB VRAM, 가능하면 40GB 이상 | 3B 모델도 영상 입력에서는 메모리를 많이 사용. 부족하면 더 작은 fps/clip 사용 |

## 실행 순서 권장

1. `vision_clip_strategy_sample_test_runpod.ipynb`로 center와 yolo_track clip 품질 비교
2. yolo_track이 느리거나 불안정하면 center 기준으로 1차 전체 학습
3. `vision_model1_yolo_tracking_videomae_runpod.ipynb`로 5초 clip 기반 VideoMAE 학습
4. `vision_model2_yolo_tracking_qwen_vl_runpod.ipynb`로 설명/JSON 품질 확인
5. `vision_model3_service_pipeline_runpod.ipynb`로 Supervisor handoff 구조 확인

## 주의 사항

`ByteTrack` 기반 사고 후보 추정은 전체 700개 x 4라벨 데이터에 바로 적용하면 오래 걸릴 수 있다. 먼저 `center` 기준 5초 clip으로 학습하고, 샘플 검증에서 `yolo_track`을 비교하는 것이 현실적이다.

`Qwen2.5-VL`은 현재 학습 모델이 아니라 추론/설명 생성 모델이다. 사고 유형 분류 성능 비교는 ResNet18/VideoMAE에서 보고, Qwen은 설명 품질과 JSON 구조 안정성을 확인하는 방향이 맞다.
