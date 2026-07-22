# 머신러닝/딥러닝 학습결과서

## 1. 작성 목적

Vision/DL 파트에서 수행한 사고 영상 분류 학습 결과를 정리한다. 본 문서는 학습 데이터, 실험 조건, 성능 결과, 현재 판단, 다음 개선 방향을 보고하기 위한 문서다.

## 2. 학습 목표

교통사고 블랙박스 영상에서 상위 사고 유형을 분류하는 모델을 학습한다.

| 라벨 | 설명 |
|---|---|
| 차대차 | 차량과 차량 간 사고 |
| 차대보행자 | 차량과 보행자 간 사고 |
| 차대이륜차 | 차량과 이륜차 간 사고 |
| 차대자전거 | 차량과 자전거 간 사고 |

## 3. 데이터 구성

AI-Hub 블랙박스 사고 영상을 기반으로 학습 후보 manifest를 구성했다.

| 상위 라벨 | 전체 후보 수 |
|---|---:|
| 차대차 | 12,277 |
| 차대보행자 | 763 |
| 차대이륜차 | 1,928 |
| 차대자전거 | 855 |
| 합계 | 15,823 |

데이터 불균형을 줄이기 위해 라벨별 동일 개수 샘플링을 사용했다.

| 실험 단위 | 라벨별 개수 | 총 영상 수 | 목적 |
|---|---:|---:|---|
| dry-run | 1개 | 4개 | 경로, 다운로드, 학습 코드 동작 확인 |
| sample 50 | 50개 | 200개 | 로컬 소규모 실험 |
| sample 100 | 100개 | 400개 | RunPod 확장 실험 |
| sample 700 | 700개 | 2,800개 | 본 학습 기준 균형 샘플 |

## 4. ResNet18 frame-level baseline

영상에서 추출한 프레임 이미지를 사용해 ResNet18 pretrained 모델을 학습했다.

| 항목 | 내용 |
|---|---|
| 입력 | 영상에서 추출한 frame image |
| 모델 | ResNet18 pretrained |
| 주요 설정 | image_size=224, batch_size=32, seed=42 |
| 최고 성능 | best test accuracy 약 0.597 |

| 실험 | 설정 | 결과 | 해석 |
|---|---|---|---|
| freeze baseline | freeze_backbone=True, lr=0.001, epoch=5 | test acc 약 0.398 | classifier head만 학습하여 성능 낮음 |
| unfreeze lr=1e-4 | freeze_backbone=False, lr=0.0001, epoch=10 | best test acc 약 0.597 | ResNet18 기준 가장 좋은 결과 |
| unfreeze lr=3e-5 | freeze_backbone=False, lr=0.00003, epoch=10 | best test acc 약 0.589 | 안정적이나 최고 성능은 낮음 |

## 5. VideoMAE 5초 clip 기반 학습

초기에는 YOLO/ByteTrack으로 사고 후보 시점을 찾고 5초 clip을 생성한 뒤, VideoMAE로 사고 유형을 분류하는 방식을 실험했다.

| 항목 | 내용 |
|---|---|
| 입력 | YOLO/ByteTrack 기반 5초 clip |
| 모델 | MCG-NJU/videomae-base-finetuned-kinetics |
| frame_count | 16 |
| 목적 | 사고 후보 구간만 사용했을 때 분류 성능 확인 |

| run_id | 설정 | train/val/test rows | best val acc | best test acc |
|---|---|---:|---:|---:|
| videomae_cls_20260702_124642 | freeze=True, lr=0.001, epoch=5 | 1773 / 420 / 212 | 0.538 | 0.552 |
| videomae_cls_20260702_153544 | freeze=False, lr=0.0001, epoch=10 | 1773 / 420 / 212 | 0.381 | 0.368 |
| videomae_cls_20260702_183519 | freeze=False, lr=0.00005, epoch=30 | 1773 / 420 / 212 | 0.552 | 0.604 |

판단:

- 5초 clip 기반 VideoMAE는 시간 정보를 활용할 수 있어 ResNet18보다 모델 구조상 적합하다.
- 다만 자동 clip 생성 품질이 일정하지 않으면 사고 장면이 누락될 수 있다.
- 일부 Qwen2.5-VL 분석에서 "명확한 사고 장면 없음"으로 판단한 사례가 있어 clip 자동 생성 방식은 고도화 대상으로 분리했다.

## 6. VideoMAE raw video 기반 학습

clip 오류를 줄이기 위해 원본 10초 영상을 자르지 않고 그대로 사용하는 실험을 추가했다.

| 항목 | 내용 |
|---|---|
| 입력 | 원본 10초 raw video |
| 모델 | MCG-NJU/videomae-base-finetuned-kinetics |
| frame_count | 16 |
| 목적 | clip 실패 변수를 제거하고 VideoMAE 자체 분류 가능성 확인 |

### 6.1 split 적용 raw video 실험

train/val/test = 70/20/10 split을 적용한 뒤 다시 학습했다.

| run_id | 데이터 | 설정 | train/val/test rows | best val acc | best test acc |
|---|---|---|---:|---:|---:|
| videomae_cls_20260713_112125 | 라벨별 50개 | freeze=True, lr=0.0001, epoch=5 | 140 / 40 / 20 | 0.400 | 0.450 |
| videomae_cls_20260713_022139 | 라벨별 100개 | freeze=True, lr=0.0001, epoch=5 | 280 / 80 / 40 | 0.550 | 0.450 |
| videomae_cls_20260713_033130 | 라벨별 100개 | freeze=False, lr=0.00001, epoch=5 | 280 / 80 / 40 | 0.538 | 0.500 |

판단:

- 라벨별 100개 split 실험 기준으로는 freeze=True 실험이 validation accuracy는 더 높았다.
- unfreeze 실험은 train accuracy가 0.993까지 올라가며 과적합 경향이 보였지만, best test accuracy는 0.500으로 가장 높았다.
- 현재 표본 수가 작아 최종 결론으로 보기는 어렵고, 라벨별 700개 실험에서 재확인이 필요하다.

### 6.2 Qwen2.5-VL 100개 샘플 보조 분석

라벨별 100개 raw video split manifest에서 Qwen2.5-VL 장면 설명 결과를 확인했다. 현재 로컬 `storage/vision/outputs/qwen_vl_raw_video_100` 기준으로는 라벨별 3개씩, 총 12개 결과 JSON이 생성되어 있다.

| 항목 | 내용 |
|---|---|
| 입력 manifest | `train_100_raw_video_manifest_split.csv` |
| 확인된 출력 수 | 12개 |
| 라벨 분포 | 차대보행자 3, 차대이륜차 3, 차대자전거 3, 차대차 3 |
| 출력 위치 | `storage/vision/outputs/qwen_vl_raw_video_100/*.json` |
| 목적 | 사고 장면 설명, 도로/날씨/시야 상태 추출 가능성 확인 |

확인 결과는 다음과 같다.

| 확인 항목 | 결과 |
|---|---|
| JSON 유효성 | 12개 모두 `qwen_json_valid=True` |
| 출력 언어 | 12개 모두 영어 또는 영어 중심 혼합 출력 |
| 사고 장면 인식 | 8개는 사고/위험 상황을 설명, 4개는 사고 미탐지 또는 불명확 응답 |
| 장면 조건 추출 | weather는 대부분 `unknown`, visibility는 대부분 `good`, lighting은 day/night 위주로 추출 |
| 주요 한계 | 사고 여부와 과실 근거를 일부 단정하는 경향이 있어 그대로 법률 판단에 사용하면 위험 |

실제 출력 예시는 다음과 같다.

| 라벨 | asset_id | JSON 유효성 | summary 예시 | accident_situation 예시 | scene_conditions 예시 |
|---|---|---|---|---|---|
| 차대보행자 | `aihub_train_00000029` | True | 주차장을 지나 도로를 횡단하는 구간에서 사고가 발생하는 흐름으로 설명 | 횡단보도에서 보행자가 차량에 충돌한 상황으로 설명 | weather=`unknown`, visibility=`good`, lighting=`day`, confidence=`0.8` |
| 차대이륜차 | `aihub_train_00001228` | True | 야간 도심 도로에서 차량과 보행자가 보이는 장면으로 설명 | 야간 도로에서 이륜차 사고가 발생한 상황으로 설명 | weather=`unknown`, visibility=`good`, lighting=`night`, confidence=`0.8` |
| 차대차 | `aihub_train_00004036` | True | 도심 도로 주행 장면으로 설명 | 사고 장면이 명확히 식별되지 않는다고 응답 | weather=`unknown`, visibility=`unknown`, lighting=`unknown`, confidence=`0.5` |

위 예시에서 보듯 Qwen2.5-VL은 장면 요약과 조건 추출은 가능하지만, 사고 장면을 항상 안정적으로 식별하지는 못한다. 따라서 사고 유형 확정은 VideoMAE 결과를 우선하고, Qwen 결과는 설명 보조와 불확실성 기록에 사용한다.

판단:

- Qwen2.5-VL은 사고 유형 분류 모델로 사용하지 않는다.
- Qwen2.5-VL은 VideoMAE 분류 결과를 보조하는 장면 설명, 도로 상태, 날씨/시야 상태 추출 용도로 사용한다.
- Qwen 결과는 Supervisor로 바로 넘기지 않고 `qwen_json_valid`, `parse_error`, `parsed_output`을 확인한 뒤 보조 근거로만 사용한다.
- 영어 출력이 남아 있으므로 발표/서비스용 결과에는 한국어 후처리 또는 한국어 재작성 Agent 연결이 필요하다.

반영한 수정 사항:

- Qwen 입력 fps를 `2.0`에서 `6.4`로 상향했다.
- 프롬프트를 강화해 JSON 단일 객체 출력과 한국어 문자열 출력을 다시 명시했다.
- Qwen 결과 저장 시 `qwen_json_valid`, `parse_error`, `parsed_output`, `raw_output_text`를 함께 저장하도록 수정했다.
- JSON 파싱 실패 시에도 원문 출력은 보존하고, 후속 Agent에는 invalid 상태로 전달할 수 있게 했다.

진행 상태:

- 라벨별 100개 VideoMAE split 실험 결과와 Qwen 보조 분석 결과는 본 문서에 반영했다.
- 라벨별 50개 추가 실험과 라벨별 700개 실험은 진행 중이며, 결과 확인 후 별도 반영 예정이다.

## 7. 현재 판단

| 구분 | 판단 |
|---|---|
| 사고 유형 분류 | VideoMAE 중심으로 진행 |
| 입력 영상 정책 | 사용자에게 사고 지점이 포함된 5~30초 영상을 받는 방향 |
| clip 자동 생성 | YOLO/ByteTrack 기반 고도화 항목으로 분리 |
| 장면 설명 | Qwen2.5-VL을 보조 분석 모델로 사용 |

## 8. 주요 이슈와 대응

| 이슈 | 대응 |
|---|---|
| 5초 clip에서 사고 장면 누락 가능 | raw video 전체 입력 실험으로 원인 분리 |
| split 없는 학습 결과로 성능 판단 불가 | train/val/test = 70/20/10 split manifest 추가 |
| 32프레임 입력 시 VideoMAE positional embedding 불일치 | 현재 체크포인트 기준 frame_count=16 유지 |
| Qwen을 전체 데이터에 돌릴 경우 비용 과다 | 라벨별 샘플 N개만 분석하도록 설정 |
| YOLO/ByteTrack 대량 처리 병목 | MVP에서는 사용자 입력을 5~30초 사고 포함 영상으로 제한 |

## 9. 다음 진행 계획

1. 라벨별 700개, 총 2,800개 raw video split 실험 실행
2. freeze=True와 freeze=False 실험의 best val/test accuracy 비교
3. 과적합 여부 확인을 위해 train/val/test 차이와 epoch별 loss 확인
4. Qwen2.5-VL 샘플 분석 결과를 Vision output schema에 연결
5. 발표 기준 결론 정리
