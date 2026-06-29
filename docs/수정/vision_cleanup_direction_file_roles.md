# Vision/DL 정리 보고서: 방향 전환, 파일 역할, 정리 결과

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-06-29 |
| 목적 | 회의 이후 변경된 Vision/DL 목적을 기준으로 현재 코드와 산출물 역할을 정리하고, 불필요 파일 정리 결과와 다음 구현 순서를 남긴다. |
| 기준 폴더 | `D:\dev\SKN27-FINAL-3Team` |

## 1. 정리 결과

삭제한 파일/폴더는 모두 재생성 가능한 부산물이다.

| 삭제 대상 | 삭제 이유 |
|---|---|
| `ai/vision/__pycache__/` | Python 실행 캐시 |
| `etl/__pycache__/` | Python 실행 캐시 |
| `scripts/__pycache__/` | Python 실행 캐시 |
| `storage/vision/datasets/classification/manifests/sample_500_manifest.csv` | 예전 fine-label 샘플링 산출물. 현재 방향은 coarse label 기준 |
| `storage/vision/datasets/classification/manifests/sample_500_manifest_summary.csv` | 위 파일의 summary. 현재 방향에서는 `sample_500_coarse_manifest_summary.csv` 사용 |`r`n| `storage/vision/manifests/sample_manifest.csv` | 초기 이미지 10장 검증용 manifest. `etl/vision_data.py`로 재생성 가능하고 현재 clip/Agent 흐름에서는 미사용 |

남긴 파일은 아래 이유가 있다.

| 남긴 대상 | 이유 |
|---|---|
| `yolov8n.pt` | 로컬에서 YOLO 재실행 시 다시 다운로드하지 않기 위한 모델 weight |
| `storage/vision/outputs/*` | 노트북에서 바로 확인할 검증 결과 |
| `storage/vision/processed/frames/*` | bbox 시각화와 Agent Output source_ref 확인용 |
| `classification_manifest.csv` | 전체 후보 데이터 목록의 기준 파일 |
| `sample_500_coarse_manifest.csv` | 현재 학습 방향의 기준 샘플 manifest |
| `frame_manifest_dryrun.csv` | frame-level 학습 dry-run 기준 파일 |

## 2. 기존 방향에서 변경된 방향

| 구분 | 기존 방향 | 변경 방향 |
|---|---|---|
| Vision/DL 목적 | 사고유형·사고장소를 영상으로 예측 | 사용자 진술을 대체하지 않고 영상 관찰 근거를 구조화 |
| Key Frame | 영상 전체에서 균등 추출 | 사건 전, 위험 증가, 사건 peak, 사건 직후 흐름을 설명하는 frame으로 확장 |
| Output | 객체 탐지 결과, 사고유형 후보, 장소 후보, generic confidence | 사건 후보 구간, Key Frame 역할, 객체 변화, source_ref, 확인 불가 항목, 관찰 사실 요약 |
| 사고유형/장소 | Vision이 직접 결론처럼 반환 | 사용자 입력과 RAG 판단을 보조하는 장면 맥락 후보로 사용 |
| 과실비율 | Vision 결과에서 추정 가능성 검토 | Vision은 과실비율·책임·가해 차량·신호 위반을 확정하지 않음 |
| 학습 방향 | 이미지/프레임 분류 중심 | 분류 baseline은 유지하되, 서비스 Output은 사건 구간과 근거 구조화 중심 |
| 고도화 모델 | ResNet18/EfficientNet 등 이미지 모델 비교 | VideoMAE V2는 긴 영상의 사건 구간 선별 성능 비교 POC 후보 |

## 3. 현재 코드 흐름

```text
raw video
-> ai/vision/pipeline.py
   균등 Key Frame 추출
-> ai/vision/models.py
   YOLO 객체 탐지, bbox/confidence 생성
-> ai/vision/schemas.py
   사건 후보 구간, 객체 변화, Key Frame 역할, 관찰 요약 생성
-> ai/vision/visualize.py
   bbox 시각화 이미지 생성
-> scripts/vision_situation_analysis_review.ipynb
   결과를 사람이 바로 확인
```

현재 `schemas.py`는 회의 이후 방향에 맞춰 `vision-agent-output-v2`를 생성한다.

주요 반환 항목:

```text
event_window_candidates
key_clips
key_frames
detected_objects
object_change_observations
scene_context_candidates
user_claim_comparison
field_summary
evidence_candidates
unavailable_items
limitations
```

## 4. VideoMAE V2를 바로 구현하지 않은 이유

VideoMAE V2를 지금 바로 넣지 않은 이유는 “다른 모델을 완성한 다음에 무조건 VideoMAE를 하자”가 아니다.

정확히는 다음 순서가 더 안전하기 때문이다.

1. 먼저 현재 YOLO + Key Frame 기반 Output 구조를 확정한다.
2. 어떤 값이 RAG, 리포트, UI에 필요한지 고정한다.
3. 그 Output 구조를 기준으로 VideoMAE V2가 실제로 개선하는 부분이 있는지 검증한다.
4. 개선이 확인될 때만 VideoMAE V2를 학습/추론 파이프라인에 넣는다.

VideoMAE V2는 비용이 큰 모델이다. 바로 넣으면 아래 문제가 생긴다.

| 문제 | 설명 |
|---|---|
| 정답 clip 부족 | 사고 시점 annotation이 없으면 무엇을 positive clip으로 학습할지 불안정함 |
| 비용 증가 | 긴 영상 clip 단위 추론은 GPU 비용과 처리 시간이 큼 |
| 검증 어려움 | 현재 Output 기준이 고정되지 않으면 VideoMAE가 좋아졌는지 판단하기 어려움 |
| 역할 중복 위험 | 사고유형/장소 분류로 쓰면 사용자 입력과 역할이 겹침 |

따라서 현재 생각은 다음과 같다.

```text
1차: YOLO + bbox 변화 + Key Frame 기반 사건 후보 Output 완성
2차: ResNet18은 frame-level 학습 파이프라인 검증용으로 유지
3차: VideoMAE V2는 사건 관련 clip 선별이 실제로 좋아지는지 비교 POC
4차: 성능/비용 이득이 있으면 Agent pipeline에 편입
```

즉 VideoMAE V2는 버리는 것이 아니라, 지금 바로 넣기에는 기준 데이터와 검증 기준이 부족해서 후순위로 둔다.

## 5. 파일별 역할

### 5.1 Vision 분석 코드

| 파일 | 역할 | 현재 상태 |
|---|---|---|
| `ai/vision/pipeline.py` | raw 영상에서 Key Frame을 추출하고 `keyframes_*.json` 생성 | POC용 균등 추출 baseline |
| `ai/vision/models.py` | Key Frame에 YOLO를 실행하고 객체 class/confidence/bbox 생성 | 유지 |
| `ai/vision/schemas.py` | detection 결과를 `vision-agent-output-v2` 구조로 변환 | 회의 방향 반영 완료 |
| `ai/vision/visualize.py` | detection bbox를 이미지에 그려 `visualizations` 저장 | 발표/검증용 유지 |
| `ai/vision/train_classifier.py` | frame-level 사고유형 분류 baseline 학습 | 학습 파이프라인 검증용 유지 |

### 5.2 ETL 코드

| 파일 | 역할 | 현재 상태 |
|---|---|---|
| `etl/vision_data.py` | raw 샘플 이미지 manifest 생성 | 초기 적재 검증용 |
| `etl/attachment_evidence_sample.py` | 사진 1건 attachment/evidence 연결 JSON 생성 | ERD 연결 샘플 |
| `etl/build_classification_manifest.py` | Drive listing에서 전체 classification 후보 manifest 생성 | 유지 |
| `etl/sample_classification_dataset.py` | coarse label 기준 최대 500개 샘플링 및 train/val/test split | 현재 학습 기준 |
| `etl/download_sampled_media.py` | 샘플링된 영상 일부를 다운로드하거나 no-download 검증 | RunPod 전 dry-run용 |
| `etl/extract_training_frames.py` | 다운로드된 영상에서 학습용 frame manifest 생성 | frame-level 학습용 |
| `etl/utils.py` | ETL 공통 CSV/파일명 helper | 중복 제거용 |

### 5.3 확인용 스크립트/노트북

| 파일 | 역할 | 현재 상태 |
|---|---|---|
| `scripts/check_raw_images.py` | raw 이미지 읽기 검증 | 초기 검증용 |
| `scripts/check_raw_media.py` | raw 이미지/영상 읽기 검증 | 초기 검증용 |
| `scripts/vision_situation_analysis_review.ipynb` | 사건 후보 구간, Key Frame, 객체 변화, bbox 이미지, 요약을 바로 확인 | `Untitled.ipynb`에서 이름 변경 완료 |

### 5.4 문서

| 파일 | 역할 |
|---|---|
| `docs/runpod_vision_poc_log.md` | RunPod 설정과 POC 실행 로그 |
| `docs/vision_training_plan.md` | 학습 데이터, 샘플링, baseline 학습 계획 |
| `docs/vision_direction_change_report.md` | 기존 방향에서 수정 방향으로 바뀐 이유 정리 |
| `docs/vision_work_priority_and_issue_mapping.md` | 작업 우선순위와 이슈 매핑 |
| `docs/vision_cleanup_direction_file_roles.md` | 현재 문서. 정리 결과와 파일 역할 요약 |

## 6. 지금 기준으로 가장 중요한 다음 구현

VideoMAE V2가 아니라 아래가 먼저다.

1. `pipeline.py`의 균등 Key Frame 추출을 유지하되, bbox 변화 기반 후보 frame 선택을 추가한다.
2. `schemas.py`의 `object_change_observations` 기준을 더 명확하게 검증한다.
3. 사용자 진술 입력이 들어왔을 때 `user_claim_comparison`에 최소 비교 결과를 넣는다.
4. `field_summary`가 JSON에 없는 사실을 말하지 않는지 검증한다.
5. 그 다음 VideoMAE V2가 사건 후보 구간 선별을 얼마나 개선하는지 비교한다.

## 7. 검증 결과

아래 검증을 통과했다.

```text
python -m py_compile ... 성공
python ai/vision/schemas.py 성공
```

현재 schema 변환 결과:

```text
status: success
event_windows: 1
key_frames: 5
detected_objects: 16
object_change_observations: 4
evidence_candidates: 5
```

