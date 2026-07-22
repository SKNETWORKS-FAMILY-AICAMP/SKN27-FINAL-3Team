# Vision/DL 진행 및 방향성 보고서

| 항목 | 내용 |
|---|---|
| 작성 기준 | 2026-06-25 회의 이후 ~ 2026-07-02 현재 |
| 보고 목적 | 강사님께 Vision/DL의 현재 방향, 진행 결과, 변경 사항, 남은 작업, 향후 계획을 공유하기 위함 |
| 현재 단계 | 단일 영상 POC 완료, 사고 유형 분류 학습 실험 진행 중 |
| 담당 범위 | 차량 사고 이미지/영상 데이터셋, Vision/DL 분석, 영상/이미지 Agent, DL 결과 구조화 |

## 1. 보고 요약

지난주 목요일 회의 이후 Vision/DL 작업은 단순 계획 단계에서 실제 구현 및 RunPod 학습 실험 단계로 이동했다.

초기에는 사고 이미지와 영상을 바로 분석 모델에 넣고 사고 유형이나 사고 장소를 예측하는 방향을 고려했다. 그러나 실제 데이터 구조, GPU 비용, 모델별 역할, Supervisor Agent 연결 방식을 검토하면서 방향을 수정했다.

현재 방향은 다음과 같다.

```text
1. 단일 영상 POC로 Vision 분석 흐름 검증
2. YOLO는 객체 탐지와 bbox 근거 생성용으로 사용
3. VideoMAE는 영상 clip 이해 보조 모델로 사용
4. 사고 유형 분류 학습은 ResNet18 pretrained baseline부터 진행
5. 결과는 Supervisor/RAG/법률/판례 Agent가 사용할 수 있는 구조화 JSON으로 정리
```

현재 가장 중요한 진행 사항은 AI-Hub 사고 영상 데이터를 상위 라벨 4개로 분류하는 학습 실험이다.

## 2. 지난주 목요일 기준 계획과 현재 변경된 방향

### 2.1 기존 계획

지난주 목요일 기준 주요 계획은 다음과 같았다.

```text
RunPod + Google Drive 연동 확인
이미지/영상 데이터 적재 구조 생성
샘플 데이터 manifest 생성
단일 영상 분석 흐름 검증
사진 attachment/evidence 연결 흐름 확인
학습 파이프라인 준비
```

당시에는 아직 실제 데이터가 RunPod에서 정상적으로 읽히는지, 영상 분석 결과를 어떤 schema로 넘겨야 하는지, 전체 학습 데이터는 어떤 기준으로 구성해야 하는지가 확정되지 않은 상태였다.

### 2.2 현재 변경된 방향

현재는 아래 방향으로 정리되었다.

| 구분 | 지난주 기준 | 현재 방향 |
|---|---|---|
| 데이터 적재 | Drive에서 데이터를 가져올 수 있는지 확인 | Drive listing 기반 manifest 생성 후 필요한 데이터만 샘플링 |
| 영상 분석 | 단일 영상에서 key frame 추출 검증 | YOLO + bbox 변화 + clip 후보 + VideoMAE 보조 분석까지 확장 |
| 모델 역할 | 하나의 Vision 모델처럼 막연하게 고려 | YOLO, VideoMAE, ResNet18 역할 분리 |
| 학습 라벨 | 세부 사고 유형/장소까지 고민 | 우선 상위 사고 유형 4개로 단순화 |
| 학습 방식 | 전체 데이터 사용 가능성 검토 | 라벨별 700개 샘플링 후 frame-level 학습 |
| Output | Vision Agent Output 단일 구조 | final_analysis와 Supervisor handoff 구조로 분리 |
| 법률 판단 | 영상 분석 결과가 사고 판단에 가까울 수 있음 | Vision은 관찰 근거만 제공하고 과실/책임은 확정하지 않음 |

## 3. 현재까지 진행된 작업

## 3.1 RunPod 및 Google Drive 연동 검증

RunPod에서 Google Drive 데이터를 다운로드하고 실제로 읽을 수 있는지 확인했다.

완료된 사항은 다음과 같다.

- RunPod Pod 생성 및 PyTorch/CUDA 환경 확인
- Google Drive 샘플 이미지 10장 다운로드
- 이미지 파일 읽기 검증
- Google Drive 샘플 영상 1개 다운로드
- 영상 파일 읽기 검증
- `storage/vision/` 기준 저장 폴더 구조 생성
- 샘플 manifest 생성

검증 결과는 다음과 같다.

```text
샘플 이미지 10장 읽기 성공
샘플 영상 1개 읽기 성공
RunPod에서 Drive 기반 데이터 적재 가능 확인
```

## 3.2 단일 영상 기반 Vision POC 완료

샘플 블랙박스 영상 1개를 기준으로 Vision 분석 흐름을 구현했다.

구현 흐름은 다음과 같다.

```text
원본 영상
-> Key Frame 5장 추출
-> YOLO baseline 객체 탐지
-> detection JSON 생성
-> bbox 시각화 이미지 생성
-> Vision Agent Output JSON 생성
```

이후 단일 영상 POC는 다음 단계까지 확장되었다.

```text
bbox 변화량 기반 event window 후보 생성
-> clip 후보 JSON 생성
-> 10초 이하 영상은 전체 context 사용
-> VideoMAE 입력용 16프레임 샘플링
-> pretrained VideoMAE 추론
-> YOLO 결과와 VideoMAE 결과 병합
-> final_analysis JSON 생성
-> Supervisor handoff JSON 생성
```

이로써 단일 영상 기준 POC는 완료된 상태로 본다.

## 3.3 Vision Output Schema 정리

기존에는 하나의 `agent_output`만 고려했지만, 구현 과정에서 output 구조를 분리했다.

현재 output 구조는 다음과 같다.

```text
1. agent_output_*.json
   - YOLO, key frame, detected object, event window 후보 중심

2. videomae_results_*.json
   - clip 단위 VideoMAE 보조 추론 결과

3. final_analysis_*.json
   - YOLO 결과와 VideoMAE 결과를 병합한 최종 Vision 분석 결과

4. supervisor_handoff_*.json
   - Supervisor Agent와 후속 Agent가 사용할 수 있도록 정리한 전달용 schema
```

중요한 원칙은 다음과 같다.

```text
Vision 결과는 관찰 근거이다.
Vision 결과만으로 과실비율을 확정하지 않는다.
Vision 결과만으로 가해 차량, 피해 차량, 법적 책임을 확정하지 않는다.
법률/판례/RAG Agent는 Vision 결과를 참고 근거로만 사용한다.
```

## 3.4 AI-Hub 학습 데이터 manifest 구성

전체 영상 데이터를 바로 학습에 넣지 않고, Drive listing을 먼저 manifest화했다.

확인된 상위 라벨 기준 데이터 수는 다음과 같다.

| 상위 라벨 | 후보 수 |
|---|---:|
| 차대차 | 12,277 |
| 차대보행자 | 763 |
| 차대이륜차 | 1,928 |
| 차대자전거 | 855 |
| 전체 | 15,823 |

초기에는 500개 샘플링을 사용했지만, 이후 학습 데이터 수를 늘리기 위해 라벨별 최대 700개 기준으로 변경했다.

현재 학습 데이터 구성 기준은 다음과 같다.

```text
상위 라벨 4개
라벨별 최대 700개 영상
총 2,800개 영상 기준
영상당 8프레임 추출
frame-level classification manifest 생성
```

RunPod에서 확인한 frame-level 데이터는 다음과 같다.

```text
frame rows: 22,336
train: 약 15,500건
val: 약 4,470건
test: 약 2,248건
```

## 3.5 ResNet18 사고 유형 분류 학습 진행

현재 실제 학습 중인 모델은 ResNet18 pretrained 기반 frame-level classifier이다.

학습 목적은 다음 4개 상위 사고 유형 분류이다.

```text
차대차
차대보행자
차대이륜차
차대자전거
```

현재까지 확인된 주요 실험 결과는 다음과 같다.

| 실험 | 설정 | 결과 | 해석 |
|---|---|---:|---|
| freeze baseline | freeze_backbone=True, lr=0.001, epoch=5 | test acc 약 0.398 | classifier head만 학습해서 성능 낮음 |
| exp2 | unfreeze, lr=0.0001, epoch=10 | best test acc 약 0.597 | 현재까지 가장 좋은 기준점 |
| exp3 | unfreeze, lr=0.00003, epoch=10 | best test acc 약 0.589 | exp2보다 낮지만 안정적 |
| exp4 | unfreeze, lr=0.00001, epoch=15 | best test acc 약 0.576 | learning rate가 낮아 성능 개선 제한 |
| exp5 | unfreeze, lr=0.00003, weight_decay=0.05, label_smoothing=0.05 | best test acc 약 0.591 | loss는 안정되지만 exp2를 넘지 못함 |

현재까지의 판단은 다음과 같다.

```text
backbone을 freeze하면 성능이 낮다.
unfreeze하면 성능은 크게 오른다.
하지만 train accuracy가 99%까지 빠르게 올라 과적합이 나타난다.
따라서 learning rate와 regularization 조합을 추가로 확인해야 한다.
```

## 3.6 추가 학습 실험 진행 중

현재 RunPod에서 추가 학습 실험을 진행 중이다.

추가 실험 조합은 다음과 같다.

| 실험 | 설정 목적 |
|---|---|
| exp6 | 낮은 learning rate와 regularization 조합 확인 |
| exp7 | 현재 best인 exp2에 regularization을 추가했을 때 성능 유지 여부 확인 |
| exp8 | exp2와 exp5 사이 learning rate에서 성능과 과적합 균형 확인 |

구체적인 설정은 다음과 같다.

```text
exp6: lr=0.00001, weight_decay=0.05, label_smoothing=0.05, epoch=15
exp7: lr=0.0001, weight_decay=0.05, label_smoothing=0.05, epoch=10
exp8: lr=0.00005, weight_decay=0.05, label_smoothing=0.05, epoch=12
```

또한 VideoMAE도 단순 inference가 아니라 학습 비교를 진행할 수 있도록 코드를 추가했다.

현재 VideoMAE 학습 기본 실험은 다음과 같다.

```text
model: VideoMAE pretrained
input: downloaded mp4 video
frame_count: 16
batch_size: 2
epochs: 3
learning_rate: 0.00001
weight_decay: 0.05
```

VideoMAE는 ResNet18보다 훨씬 무겁기 때문에, 우선 작은 batch size와 적은 epoch로 비교 기준만 만든다.

## 4. 모델별 역할 정리

현재 Vision/DL에서 사용하는 모델의 역할은 다음과 같이 구분한다.

| 모델/기능 | 현재 역할 | 학습 여부 | 비고 |
|---|---|---|---|
| YOLO | 객체 탐지, bbox, confidence, 시각화 | 현재 학습 안 함 | 사고 유형 판단 모델이 아니라 관찰 근거 생성용 |
| bbox 변화량 | event window 후보 생성 |  | 사고 발생 가능 구간 후보 생성 |
| VideoMAE | clip-level 영상 이해 보조 | 학습 비교 코드 추가 | 현재는 보조 모델, fine-tuning 실험 시작 가능 |
| ResNet18 | frame-level 사고 유형 4-class 분류 | 현재 학습 중 | 현재 주력 학습 baseline |

정리하면 현재 주력 학습 모델은 ResNet18이고, VideoMAE는 영상 전체 맥락을 더 잘 반영할 수 있는지 비교하기 위해 추가된 상태이다.

## 5. 현재 결과에 대한 해석

현재 best test accuracy는 약 0.60 수준이다.

이는 다음 의미를 가진다.

```text
학습 파이프라인은 정상 동작한다.
상위 라벨 4개 분류는 어느 정도 가능성이 있다.
하지만 서비스 수준 모델로 보기에는 아직 부족하다.
```

성능이 아직 제한적인 이유는 다음과 같이 추정된다.

- 영상 전체가 아니라 frame-level 이미지 기준으로 학습하고 있다.
- 한 영상에서 뽑은 8프레임이 사고 맥락을 충분히 대표하지 못할 수 있다.
- 차대차/차대보행자/차대이륜차/차대자전거가 단일 프레임만으로 명확히 구분되지 않는 경우가 있다.
- train accuracy가 빠르게 99%에 도달해 과적합 가능성이 크다.
- class별 confusion matrix를 아직 확인하지 않았다.

따라서 다음 단계에서는 단순히 epoch를 늘리는 것보다 다음을 확인해야 한다.

```text
regularization 조합
learning rate 조합
VideoMAE와 ResNet18 비교
class별 오분류 패턴
video-level aggregation 가능성
```

## 6. 주요 산출물

### 6.1 문서

| 파일 | 역할 |
|---|---|
| `docs/vision/runpod_vision_poc_log.md` | RunPod 설정, Drive 연동, 단일 영상 POC 실행 기록 |
| `docs/vision/vision_training_plan.md` | AI-Hub 데이터 구조, 샘플링, 학습 전략, RunPod 선택 기준 |
| `docs/vision/vision_direction_change_report.md` | 기존 방향에서 수정 방향으로 변경된 이유 정리 |
| `docs/vision/vision_schema_change_report.md` | Vision input/output schema 변경 및 Supervisor 연결 기준 |
| `docs/vision/vision_test_scenario.md` | Vision/DL 테스트 시나리오 |
| `docs/vision/vision_weekly_progress_report_2026-06-25_to_2026-07-02.md` | 강사님 보고용 진행 및 방향성 보고서 |

### 6.2 구현 파일

| 파일 | 역할 |
|---|---|
| `ai/vision/pipeline.py` | 영상 key frame 추출 |
| `ai/vision/models.py` | YOLO baseline 객체 탐지 |
| `ai/vision/schemas.py` | detection 결과를 Vision Agent Output 형태로 변환 |
| `ai/vision/visualize.py` | bbox 시각화 이미지 생성 |
| `ai/vision/videomae_infer.py` | pretrained VideoMAE clip 추론 |
| `ai/vision/merge_analysis.py` | YOLO 결과와 VideoMAE 결과를 final_analysis로 병합 |
| `ai/vision/build_supervisor_handoff.py` | Supervisor 전달용 handoff JSON 생성 |
| `ai/vision/train_classifier.py` | ResNet18 기반 사고 유형 분류 학습 |
| `ai/vision/train_videomae_classifier.py` | VideoMAE 기반 사고 유형 분류 학습 |
| `etl/vision/build_classification_manifest.py` | Drive listing에서 학습 후보 manifest 생성 |
| `etl/vision/sample_classification_dataset.py` | 상위 라벨별 최대 700개 샘플링 및 split 생성 |
| `etl/vision/download_sampled_media.py` | 샘플링된 영상 다운로드 또는 기존 파일 확인 |
| `etl/vision/extract_training_frames.py` | 학습용 대표 프레임 추출 및 frame manifest 생성 |
| `scripts/vision_training_runpod_full_pipeline.ipynb` | RunPod 학습 전체 실행 및 실험 결과 확인용 노트북 |

## 7. 이제 해야 할 일

### 7.1 단기 작업

```text
1. exp6~exp8 추가 학습 완료
2. VideoMAE 학습 실험 1회 실행
3. ResNet18과 VideoMAE 결과 비교
4. best validation/test accuracy 기준 best run 선정
5. best run의 run_config.json, training_history.csv, model 경로 정리
6. 결과를 GitHub 이슈 #36, #37, #39, #70에 반영
```

### 7.2 학습 결과 확인 후 작업

```text
1. ResNet18 유지 여부 판단
2. VideoMAE가 ResNet18보다 성능/비용 측면에서 의미 있는지 판단
3. EfficientNet-B0 또는 MobileNetV3 비교 필요 여부 결정
4. confusion matrix 생성
5. class별 오분류 패턴 확인
6. frame-level 결과를 video-level로 집계하는 방식 검토
```

### 7.3 Supervisor 연결 작업

```text
1. supervisor_handoff schema 최종 확인
2. Vision 결과를 법률/판례/RAG Agent에 넘길 최소 필드 확정
3. 화면 표시용 summary 문장 정리
4. 과실비율/법적 책임을 확정하지 않는 제한 문구 유지
```

## 8. 향후 진행 방향

향후 방향은 다음과 같다.

```text
1차: ResNet18 frame-level baseline 결과 확정
2차: VideoMAE video-level baseline 결과 확인
3차: 두 모델의 성능/비용/실행시간 비교
4차: best model을 Vision Agent 결과 흐름에 연결
5차: Supervisor handoff schema와 통합 검증
6차: 필요 시 EfficientNet/MobileNet 또는 VideoMAE fine-tuning 확대
```

현재 단계에서 가장 중요한 것은 모델을 무작정 많이 돌리는 것이 아니라, 같은 데이터 기준에서 모델별 결과를 비교 가능하게 저장하는 것이다.

따라서 모든 실험은 다음 산출물을 남겨야 한다.

```text
run_config.json
training_history.csv
class_mapping.json
model.pt 또는 pretrained model directory
best validation accuracy
best test accuracy
실험 해석 메모
```

## 9. 결론

지난주 목요일 이후 Vision/DL 작업은 실제 구현과 RunPod 학습 실험 단계까지 진행되었다.

현재까지 완료된 핵심 성과는 다음과 같다.

```text
RunPod + Google Drive 연동 검증 완료
단일 영상 Vision POC 완료
YOLO 객체 탐지 및 bbox 시각화 완료
VideoMAE 보조 추론 POC 완료
final_analysis 및 supervisor_handoff 생성 완료
AI-Hub 사고 영상 manifest 구성 완료
상위 라벨 4개 기준 700개 샘플링 완료
ResNet18 사고 유형 분류 학습 진행
VideoMAE 학습 비교 코드 추가
```

현재 진행 중인 핵심 분석은 다음이다.

```text
ResNet18 pretrained 기반 사고 유형 4-class 분류 추가 실험
VideoMAE 기반 영상 단위 사고 유형 분류 비교 실험 준비
```

강사님께 공유해야 할 핵심 메시지는 다음과 같다.

```text
Vision/DL은 단일 영상 POC는 완료되었고,
현재는 실제 AI-Hub 데이터 기반 사고 유형 분류 학습 실험 단계입니다.
YOLO는 객체 근거 생성용, VideoMAE는 영상 맥락 비교용, ResNet18은 현재 주력 분류 baseline으로 역할을 분리했습니다.
현재 best test accuracy는 약 0.60 수준이며, 추가 hyperparameter 실험과 VideoMAE 비교를 통해 다음 모델 방향을 결정할 예정입니다.
```
