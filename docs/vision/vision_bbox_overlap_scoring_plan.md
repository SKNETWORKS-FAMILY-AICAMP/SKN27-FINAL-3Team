# Vision bbox overlap 기반 사고 후보 탐지 계획

## 1. 목적

Qwen2.5-VL이 사고 장면을 항상 안정적으로 식별하지 못하는 문제가 있어, 사고 후보 시점은 Qwen 단독 판단이 아니라 YOLO/ByteTrack 기반 bbox 수치 근거로 먼저 잡는다.

## 2. 변경 방향

기존 흐름:

```text
영상
→ YOLO/ByteTrack
→ bbox 개수 변화와 면적 변화 중심으로 사고 후보 시점 추정
→ clip 생성
→ VideoMAE/Qwen 분석
```

수정 흐름:

```text
영상
→ YOLO/ByteTrack
→ 객체 쌍 bbox IoU, 중심점 거리, 객체 조합 score 계산
→ 사고 후보 시점과 근거 metric 저장
→ clip 생성
→ VideoMAE 사고 유형 분류
→ Qwen 장면 설명/도로상태/불확실성 보조
```

## 3. 사고 후보 score 기준

현재 구현은 다음 값을 manifest에 저장한다.

| 필드 | 의미 |
|---|---|
| `accident_candidate_sec` | 사고 후보 시점 |
| `accident_candidate_score` | bbox overlap/거리 기반 사고 후보 점수 |
| `accident_candidate_iou` | 후보 시점의 객체 bbox IoU |
| `accident_candidate_center_distance_px` | 후보 객체 쌍 중심점 거리 |
| `accident_candidate_object_pair` | 예: `car-person`, `car-bicycle` |
| `accident_candidate_track_pair` | ByteTrack track id 조합 |

score는 사고 확정값이 아니라 후보 시점 선정을 위한 근거값이다.

## 4. 모델별 역할

| 모델 | 역할 |
|---|---|
| YOLOv8 | 차량/보행자/이륜차/자전거 객체 탐지 |
| ByteTrack | 객체 track id 연결 |
| bbox overlap score | 사고 후보 시점 산출 |
| VideoMAE | 사고 유형 분류 |
| Qwen2.5-VL | 장면 설명, 도로/날씨/시야 상태, 불확실성 기록 |

## 5. 산출물 저장 기준

모든 분석 결과는 발표/보고서에 재사용할 수 있도록 아래 구조로 저장한다.

```text
storage/vision/reports/
  tables/
    model_runs_summary.csv
    qwen_outputs_summary.csv
    clip_accident_candidates.csv
  figures/
    model_accuracy_figure_source.csv
    clip_score_figure_source.csv
  appendix/
    model_runs_appendix.md
    qwen_outputs_appendix.md
    clip_candidates_appendix.md
```

## 6. 주의사항

- bbox가 겹친다고 사고가 확정되는 것은 아니다.
- 블랙박스 원근감 때문에 bbox overlap은 오탐이 생길 수 있다.
- 따라서 bbox score는 사고 후보 시점 추정에만 사용하고, 최종 설명에는 VideoMAE/Qwen 결과와 함께 불확실성을 남긴다.
