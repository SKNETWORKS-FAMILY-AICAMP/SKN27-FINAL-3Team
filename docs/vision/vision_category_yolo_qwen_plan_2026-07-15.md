# Vision 카테고리별 YOLO 전처리 및 Qwen 분석 진행 계획

작성일자: 2026-07-15

## 1. 목적

현재 비전 파이프라인에서 가장 먼저 검증해야 하는 부분은 사고 유형 분류 모델 자체보다, Qwen2.5-VL과 VideoMAE에 들어가기 전 단계의 입력 품질이다. 특히 YOLO bbox가 제대로 잡히지 않으면 이후 Qwen 설명과 VideoMAE 학습 데이터 정제 결과도 흔들릴 수 있다.

따라서 앞으로는 사고 유형 카테고리별로 데이터를 분리하고, 각 카테고리 안에서 OpenCV 전처리, YOLO 모델별 bbox 품질 비교, Qwen2.5-VL 출력 비교를 진행한다.

## 2. 전체 진행 방향

카테고리별 전용 노트북을 생성하여 아래 흐름으로 실험한다.

```text
1. 카테고리별 데이터 로드
2. OpenCV 전처리 적용
3. YOLO 모델 5개 bbox 비교
4. 가장 안정적인 YOLO 모델 후보 선정
5. bbox가 표시된 프레임을 Qwen2.5-VL에 전달
6. Qwen 출력 결과 비교
7. 결과 CSV/contact sheet 저장
```

분석 대상 카테고리는 다음 4개이다.

```text
차대차
차대보행자
차대이륜차
차대자전거
```

## 3. 사고 대상 구분 방식

학습 데이터에서는 사고 대상 구분이 이미 폴더명과 manifest에 들어 있다.

예시는 다음과 같다.

```text
TS_차대차_영상_...
TS_차대보행자_영상_...
TS_차대이륜차_영상_...
TS_차대자전거_영상_...
```

따라서 학습 데이터 구성 단계에서는 별도 사고 대상 탐지 모델이 필요하지 않다. 각 노트북은 해당 카테고리 prefix를 기준으로 데이터를 필터링한다.

서비스 단계에서는 사용자가 사고 유형 라벨을 주지 않기 때문에, 최종적으로는 VideoMAE가 사고 유형을 예측한다.

```text
사용자 입력 영상
→ VideoMAE
→ 차대차 / 차대보행자 / 차대이륜차 / 차대자전거 예측
```

즉, 사고 대상 분류를 위한 별도 모델을 새로 추가하기보다, 정제된 데이터로 VideoMAE를 재학습해 이 역할을 맡기는 방향이다.

## 4. 낮/밤 구분 방식

낮/밤 구분은 처음부터 별도 딥러닝 모델을 추가하지 않는다. 우선 OpenCV 기반 밝기 통계와 Qwen2.5-VL의 scene condition 출력을 함께 사용한다.

1차 기준은 다음과 같다.

```text
프레임 밝기 평균 기반 lighting_cv 추정
+ Qwen scene_conditions.lighting 확인
```

예시 기준은 다음과 같다.

```text
gray.mean() < 55       → night
gray.mean() < 85       → low_light
gray.mean() >= 85      → day
```

최종 CSV에는 다음 컬럼을 남긴다.

```text
coarse_label
lighting_cv
is_night
yolo_model
bbox_count
bbox_quality
qwen_accident_visibility
qwen_bbox_helpfulness
```

OpenCV 판단과 Qwen 판단이 다르면 `uncertain` 또는 `review`로 두고, 이후 사람 검수 샘플에서 기준을 보정한다.

## 5. OpenCV 전처리 방향

원본 영상은 절대 덮어쓰지 않는다. 전처리는 프레임 단위로 별도 output 폴더에 저장한다.

적용할 전처리는 다음과 같다.

```text
원본 프레임
대비 조절 프레임
CLAHE 기반 대비 보정 프레임
윤곽선/edge 강조 프레임
```

우선은 가장 단순한 조합을 사용한다.

```text
CLAHE + sharpen
```

야간 영상 전체를 낮처럼 바꿔 원본을 대체하지는 않는다. 원본은 유지하고, 보정본은 YOLO bbox 품질 비교와 Qwen 입력 보조 실험에만 사용한다.

## 6. YOLO 비교 대상

각 카테고리 노트북에서 동일하게 5개 YOLO 모델을 비교한다.

```text
yolov8n.pt
yolov8s.pt
yolov8m.pt
yolo11n.pt
yolo11s.pt
```

비교 기준은 다음과 같다.

```text
frames_with_relevant_detection
total_relevant_box_count
avg_conf
class_counts
contact_sheet_path
```

현재까지의 전체 비교에서는 `yolov8m.pt`가 가장 안정적인 후보로 보였지만, 카테고리별/야간별로 결과가 달라질 수 있으므로 카테고리별 비교를 다시 진행한다.

## 7. Qwen2.5-VL 적용 방식

YOLO 모델별 bbox가 표시된 프레임을 Qwen2.5-VL에 전달한다. 단, 100프레임 전체를 Qwen에 한 번에 전달하면 토큰 초과 및 OOM이 발생하므로 Qwen에는 대표 20프레임만 균등 샘플링해 전달한다.

```text
YOLO/contact sheet: 100프레임 유지
Qwen 입력: 100프레임 중 대표 20프레임
```

Qwen 결과에는 다음 값을 저장한다.

```text
accident_visible
accident_visibility
collision_moment_visible
bbox_helpfulness
bbox_quality
scene_conditions.lighting
summary
accident_situation
```

## 8. 카테고리별 노트북 구성

생성할 노트북은 다음과 같다.

```text
scripts/vision/vision_category_yolo_qwen_compare_car_vs_car_runpod.ipynb
scripts/vision/vision_category_yolo_qwen_compare_car_vs_pedestrian_runpod.ipynb
scripts/vision/vision_category_yolo_qwen_compare_car_vs_motorcycle_runpod.ipynb
scripts/vision/vision_category_yolo_qwen_compare_car_vs_bicycle_runpod.ipynb
```

각 노트북은 하나의 카테고리만 다룬다.

| 노트북 | 카테고리 | Drive 필터 prefix |
|---|---|---|
| car_vs_car | 차대차 | `TS_차대차_영상_` |
| car_vs_pedestrian | 차대보행자 | `TS_차대보행자_영상_` |
| car_vs_motorcycle | 차대이륜차 | `TS_차대이륜차_영상_` |
| car_vs_bicycle | 차대자전거 | `TS_차대자전거_영상_` |

## 9. 데이터 다운로드 방식

각 노트북에는 기존 Google Drive 다운로드 흐름을 참고한 데이터 로드 셀을 포함한다.

우선 순서는 다음과 같다.

```text
1. raw_videos/{카테고리}에 기존 mp4가 있으면 재사용
2. 없으면 DRIVE_FOLDER_URL을 이용해 Google Drive 폴더 다운로드
3. 다운로드된 Train 하위 폴더에서 CATEGORY_PREFIX로 시작하는 폴더만 탐색
4. 해당 카테고리 mp4를 raw_videos/{카테고리} 기준으로 수집
```

전체 데이터를 불러올 수 있도록 구성하되, 실험 실행은 기본적으로 샘플 수를 제한한다.

```text
MAX_VIDEOS = None          # 데이터 로드 제한 없음
ANALYSIS_SAMPLE_COUNT = 5  # YOLO/Qwen 실험 기본 샘플 수
```

전체 분석이 필요하면 `ANALYSIS_SAMPLE_COUNT = None`으로 변경한다.

## 10. 결과 저장 위치

카테고리별 결과는 아래 경로에 저장한다.

```text
storage/vision/outputs/category_yolo_qwen_compare/{category_key}/
```

주요 산출물은 다음과 같다.

```text
yolo_summary.csv
yolo_details.csv
qwen_yolo_compare_results.csv
frames_100/
preprocessed_frames/
annotated_frames/
contact_sheets/
```

## 11. 진행 순서

추천 실행 순서는 다음과 같다.

```text
1. 차대차 노트북 실행
2. 차대보행자 노트북 실행
3. 차대이륜차 노트북 실행
4. 차대자전거 노트북 실행
5. 카테고리별 가장 좋은 YOLO 모델 확인
6. Qwen 출력 품질 비교
7. 야간/저조도 영상만 별도 전처리 성능 확인
8. 최종 YOLO 모델 또는 카테고리별 YOLO 모델 전략 결정
```

## 12. 현재 판단

현재 단계에서는 사고 대상 분류 모델을 추가하거나 야간 전용 모델을 바로 만드는 것보다, metadata와 전처리 비교 결과를 먼저 쌓는 것이 우선이다.

최소 추가 정보는 다음과 같다.

```text
coarse_label
lighting_cv
is_night
yolo_model
bbox_quality
qwen_accident_visibility
qwen_bbox_helpfulness
```

이 정보를 기반으로 카테고리별/야간별로 bbox 품질이 실제로 달라지는지 확인한 뒤, 필요할 경우 야간 전용 augmentation 또는 야간 전용 fine-tuning을 진행한다.
