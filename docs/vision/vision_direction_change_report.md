# Vision/DL 프로젝트 방향성 수정 보고서

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-06-27 |
| 목적 | Vision/DL POC 진행 중 확인된 비용, 데이터 규모, 구현 난이도, 팀 역할 범위를 반영하여 기존 방향과 수정 방향을 정리한다. |
| 적용 범위 | RunPod 데이터 적재, 영상 프레임 추출, 이미지 분류 학습 파이프라인, Vision 결과 스키마, 산출물 관리 |
| 기준 산출물 | `docs/vision/runpod_vision_poc_log.md`, `docs/vision/vision_training_plan.md`, `docs/vision/vision_schema_change_report.md`, `ai/vision/train_classifier.py`, `etl/extract_training_frames.py` |

## 1. 요약

초기에는 전체 영상 데이터를 RunPod에서 바로 다루고, 모델 학습까지 빠르게 진행하는 방향으로 생각했다. 그러나 실제 검증 과정에서 Google Drive 데이터 구조가 깊고, 전체 데이터 용량이 크며, GPU 비용이 발생한다는 점이 확인되었다.

따라서 수정 방향은 다음과 같다.

- 전체 데이터 학습 전에 Drive listing과 manifest를 먼저 만든다.
- 영상 원본 직접 학습보다 대표 프레임 기반 이미지 분류를 먼저 검증한다.
- 세부 사고 유형 전체를 바로 쓰지 않고 상위 라벨 4개로 시작한다.
- RunPod GPU는 학습 코드가 로컬 dry-run을 통과한 뒤 사용한다.
- YOLO는 사고 유형 분류 모델이 아니라 객체 탐지/시각화 POC 근거로 유지한다.
- VideoMAE는 사고 판단 모델이 아니라 보조 clip 이해 결과로 사용한다.

## 2. 기존 방향 -> 수정 방향

| 구분 | 기존 방향 | 수정 방향 | 변경 이유 | 다음 액션 |
|---|---|---|---|---|
| 데이터 적재 | Google Drive 전체 데이터를 RunPod로 바로 다운로드 | Drive listing 기반 manifest를 먼저 생성하고, 필요한 샘플만 다운로드 | 전체 데이터 용량과 Drive 폴더 구조 때문에 무작정 다운로드하면 비용과 시간이 커짐 | `classification_manifest.csv` 기준으로 샘플 단위 다운로드 유지 |
| RunPod 사용 | RunPod에서 바로 분석과 학습 진행 | 로컬에서 코드와 dry-run을 검증한 뒤 RunPod GPU 사용 | GPU 비용 절감, 오류를 로컬에서 먼저 제거 가능 | 로컬 dry-run 완료 후 `sample_700_coarse_manifest.csv` 기준 RunPod 학습 |
| 영상 처리 | 영상 원본을 학습 데이터로 직접 사용 | 영상에서 대표 프레임을 추출해 이미지 분류 데이터셋으로 사용 | 영상 모델은 비용과 복잡도가 높음. 초기 baseline은 이미지 분류가 더 빠름 | `etl/extract_training_frames.py`로 frame-level manifest 확장 |
| 라벨 기준 | AI-Hub 세부 카테고리를 그대로 사용 | 상위 라벨 4개로 단순화: 차대차, 차대보행자, 차대이륜차, 차대자전거 | 세부 라벨은 불균형이 심하고 초기 성능 검증이 어려움 | coarse label 기준 700개 샘플링 유지 |
| 샘플링 전략 | 전체 15,823건을 바로 학습에 사용 | 카테고리별 최대 700개 랜덤 샘플링 후 train/val/test 분할 | 데이터 규모를 통제하면서 baseline 성능 확인 가능 | label별 700개 영상에서 프레임 추출 후 첫 GPU 학습 |
| 단일 영상 POC | 단일 영상 분석을 계속 반복 | 단일 영상 POC는 검증 완료로 보고 학습 파이프라인으로 이동 | 단일 영상 반복은 학습 목표와 직접 연결되지 않음 | 이후 단일 영상은 데모/검증 예시로만 유지 |
| 객체 탐지 | YOLO를 전체 Vision 모델처럼 사용 | YOLO는 bbox, confidence, 시각화, evidence 후보 생성용으로 제한 | 사고 유형 분류와 객체 탐지는 목적이 다름 | 분류 모델은 ResNet18/EfficientNet 계열로 별도 진행 |
| VideoMAE 활용 | 바로 사고 판단 모델로 사용 | pretrained VideoMAE는 clip-level action hint로만 사용하고, 최종 판단은 하지 않음 | Kinetics 라벨은 사고 도메인 라벨이 아니므로 과실비율/법적 책임 판단에 부적합 | `ai/vision/videomae_infer.py`, `ai/vision/merge_analysis.py`로 보조 결과만 병합 |
| 분류 모델 | 여러 모델을 동시에 비교 | ResNet18 pretrained baseline부터 시작하고 이후 EfficientNet/MobileNet 비교 | 변수를 한 번에 늘리면 원인 분석이 어려움 | `ai/vision/train_classifier.py` 기준 ResNet18 dry-run 후 확장 |
| 학습 파라미터 | 결과만 확인 | epoch, batch size, learning rate, freeze 여부, sample size를 run 단위로 기록 | 발표/보고 시 실험 재현성과 비교 근거 필요 | `run_config.json`, `training_history.csv`, `class_mapping.json` 유지 |
| 스키마 | `damage_image`를 attachment purpose처럼 사용 가능 | `damage_image`는 Vision 내부 `analysis_mode`로 처리하고, PM 상위 purpose와 분리 | PM 상위 enum과 node 내부 세분화 purpose의 정합성 문제 방지 | `vision_agent_input_output_schema.md` 기준 유지 |
| 챗봇/웹/ERD 문서 | 주희 담당 범위와 팀 공통 범위가 섞임 | 주희는 Vision 결과가 Supervisor/RAG/ERD에 연결 가능한 산출물 제공에 집중 | 챗봇 전체 플로우는 팀 공통/혜림 담당 비중이 큼 | Vision 플로우차트/시퀀스만 직접 산출물로 관리 |
| 코드 구조 | ETL 파일마다 CSV/파일명 처리 코드가 반복 | 공통 ETL helper를 `etl/utils.py`로 분리 | 중복 제거. 단, 실행 방식은 유지 | ETL 스크립트는 `from utils import ...` 사용 유지 |

## 3. 현재까지 완료된 기준

### 3.1 데이터 적재/검증

- RunPod + Google Drive 연동 확인 완료
- 샘플 이미지 10장 다운로드 및 읽기 검증 완료
- 샘플 영상 1개 다운로드 및 읽기 검증 완료
- `storage/vision/` 기본 폴더 구조 생성 완료
- 이미지 샘플 manifest 생성 완료

### 3.2 단일 영상 POC

- 영상 1개에서 Key Frame 5장 추출 완료
- YOLO baseline 객체 탐지 완료
- detection JSON 생성 완료
- PM 기준 agent output JSON 생성 완료
- bbox 시각화 이미지 생성 완료
- clip 후보 생성 및 10초 이하 영상 전체 context 처리 완료
- VideoMAE 입력용 16프레임 추출 완료
- pretrained VideoMAE 추론 완료
- YOLO/bbox 결과와 VideoMAE 결과를 `final_analysis_*.json`으로 병합 완료

### 3.4 VideoMAE 보조 분석 POC

- VideoMAE 결과는 `driving car` 같은 사전학습 action label을 반환한다.
- 이 결과는 사고유형, 과실비율, 법적 책임을 확정하지 않는다.
- 현재 사용 목적은 YOLO/bbox 기반 event evidence에 clip 전체 맥락을 보조로 붙이는 것이다.
- 최종 확인 파일은 `storage/vision/outputs/final_analysis/final_analysis_*.json`이다.

### 3.3 학습 파이프라인 준비

- AI-Hub Drive listing 기반 classification manifest 생성 완료
- 전체 후보 데이터 15,823건 확인
- 상위 라벨 4개 기준 카운트 확인
  - 차대차: 12,277
  - 차대보행자: 763
  - 차대이륜차: 1,928
  - 차대자전거: 855
- 카테고리별 최대 700개 샘플링 manifest 생성 완료
- 라벨별 1개씩 dry-run 다운로드 완료
- 라벨별 1개 영상에서 각 5장씩 프레임 추출 완료
- 총 20장 기준 `frame_manifest_dryrun.csv` 생성 완료
- ResNet18 분류 학습 dry-run 코드 작성 완료

## 4. 수정 방향에 따라 정리된 주요 파일

| 파일 | 역할 |
|---|---|
| `docs/vision/runpod_vision_poc_log.md` | RunPod 설정부터 POC, 학습 dry-run까지 진행 로그 |
| `docs/vision/vision_training_plan.md` | 상위 라벨, 샘플링, 학습 모델, 파라미터 기록 기준 |
| `docs/vision/vision_schema_change_report.md` | 급한 일/천천히 해도 되는 일/이슈 매핑 |
| `etl/build_classification_manifest.py` | Drive listing에서 classification 후보 manifest 생성 |
| `etl/sample_classification_dataset.py` | 상위 라벨별 최대 700개 샘플링 및 split 생성 |
| `etl/download_sampled_media.py` | 샘플링된 영상 다운로드 검증 |
| `etl/extract_training_frames.py` | 영상에서 학습용 프레임 추출 및 frame manifest 생성 |
| `etl/utils.py` | ETL 공통 CSV/파일명 helper |
| `ai/vision/train_classifier.py` | frame-level classification baseline 학습 |
| `etl/build_clip_candidates.py` | bbox 변화/event window 기준으로 VideoMAE 비교용 clip 후보 생성 |
| `etl/extract_video_clips.py` | clip 후보 JSON을 기준으로 mp4 clip 파일 생성 |
| `etl/extract_videomae_frames.py` | clip별 16프레임을 균등 샘플링해 VideoMAE 입력 manifest 생성 |
| `ai/vision/videomae_infer.py` | pretrained VideoMAE로 clip-level action hint 추론 |
| `ai/vision/merge_analysis.py` | Vision Agent Output과 VideoMAE 결과를 final_analysis JSON으로 병합 |
| `scripts/vision_situation_analysis_review.ipynb` | Run All로 전체 Vision POC 실행 및 결과 확인이 가능한 Jupyter 리뷰 노트북 |

## 5. 앞으로의 권장 진행 순서

### 5.1 바로 진행할 일

1. RunPod에서 라벨별 700개 학습 결과를 기준으로 파라미터 비교
2. `freeze_backbone`, `learning_rate`, `epochs` 조합을 순차 비교
3. 필요 시 `frames_per_video` 값을 8에서 16으로 늘려 비교
4. RunPod에서 `sample_700_coarse_manifest.csv` 기준 다운로드/프레임 추출 실행
5. RunPod GPU에서 ResNet18 baseline 실험 결과를 기록

### 5.2 RunPod 학습 시 우선 기록할 파라미터

- model_name
- pretrained 여부
- freeze_backbone 여부
- epochs
- batch_size
- learning_rate
- image_size
- frames_per_video
- sample_size_per_class
- train_loss
- train_accuracy
- val_loss
- val_accuracy
- model_path

### 5.3 나중에 해도 되는 일

- 전체 15,823건 전체 학습
- EfficientNet/MobileNet 본격 비교
- fine label 세분화 학습
- 사고 변곡점 기반 key frame 추출
- S3 이관
- 파손 segmentation
- 과실비율 추정 보조 모델

## 6. 주의할 점

20장짜리 dry-run 결과는 모델 성능으로 해석하지 않는다. 실제 성능 판단은 라벨별 700개 영상에서 추출한 frame manifest와 RunPod GPU 학습 결과를 기준으로 본다.

## 7. 결론

수정된 방향은 “큰 모델을 빨리 돌리는 것”이 아니라 “비용을 통제하면서 학습 가능한 데이터 구조를 먼저 고정하는 것”이다.

현재 프로젝트는 단일 영상 POC 단계에서 학습 파이프라인 단계로 넘어갈 수 있는 상태다. 다음 핵심 작업은 RunPod에서 상위 라벨 4개 기준 샘플 데이터 학습을 실행하고, 파라미터별 결과를 기록하는 것이다.

