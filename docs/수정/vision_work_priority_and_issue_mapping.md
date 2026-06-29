# Vision/DL 진행 현황, 우선순위, 이슈 매핑

작성일: 2026-06-27

## 1. 정리 기준

현재 Vision/DL 작업은 아래 두 흐름으로 나누어 관리한다.

1. Vision POC 검증 흐름
   - RunPod/Drive 연동
   - 샘플 이미지/영상 읽기
   - Key Frame 추출
   - YOLO baseline 탐지
   - PM 기준 Agent Output Schema 생성
   - bbox 시각화

2. 이미지 분류 학습 파이프라인 흐름
   - Google Drive listing 기반 학습 후보 Manifest 생성
   - 상위 라벨 4개 기준 샘플링
   - 일부 영상 dry-run 다운로드
   - 영상에서 프레임 추출
   - ResNet18 등 사전학습 모델 기반 학습
   - 파라미터별 학습 결과 기록

## 2. 진행된 부분

### 2.1 RunPod + Google Drive 연동 검증

상태: 완료

내용:

- RunPod에서 Google Drive 샘플 이미지 10장 다운로드 성공
- RunPod에서 Google Drive 샘플 영상 1개 다운로드 성공
- 이미지/영상 파일 읽기 검증 완료
- Drive 사용이 가능한 1차 데이터 경로임을 확인

관련 파일:

```text
scripts/check_raw_images.py
scripts/check_raw_media.py
docs/runpod_vision_poc_log.md
```

관련 산출물:

```text
storage/vision/raw/864.jpg ~ 873.jpg
storage/vision/raw/bb_3_190909_pedestrian_226_21450.mp4
```

관련 이슈:

```text
#37 Vision 데이터 manifest pipeline
#39 Vision POC validation
```

---

### 2.2 Vision 저장 구조와 Manifest 생성

상태: 완료

내용:

- `storage/vision` 하위 구조 생성
- 샘플 이미지 Manifest 생성
- 파일 존재 여부, 읽기 가능 여부 기록

관련 파일:

```text
etl/vision_data.py
docs/runpod_vision_poc_log.md
```

관련 산출물:

```text
storage/vision/manifests/sample_manifest.csv
```

관련 이슈:

```text
#37 Vision 데이터 manifest pipeline
```

---

### 2.3 단일 영상 기반 Vision POC 분석

상태: 완료

내용:

- 영상 1개에서 Key Frame 5장 추출
- YOLOv8n baseline 객체 탐지 수행
- 객체별 `class_name`, `confidence`, `bbox_xyxy` 생성
- PM 기준 Agent Output Schema로 변환
- bbox 시각화 이미지 생성

관련 파일:

```text
ai/vision/pipeline.py
ai/vision/models.py
ai/vision/schemas.py
ai/vision/visualize.py
docs/runpod_vision_poc_log.md
```

관련 산출물:

```text
storage/vision/processed/frames/*.jpg
storage/vision/outputs/keyframes_bb_3_190909_pedestrian_226_21450.json
storage/vision/outputs/detections/detections_bb_3_190909_pedestrian_226_21450.json
storage/vision/outputs/agent_outputs/agent_output_bb_3_190909_pedestrian_226_21450.json
storage/vision/outputs/visualizations/*_bbox.jpg
```

관련 이슈:

```text
#38 Vision image/video agent result flow
#39 Vision POC validation
#22 Agent result schema and RAG contract
#40 Cross-MVP integration scenario
```

---

### 2.4 PM 기준 purpose 정책 반영

상태: 완료

내용:

- `damage_image`는 PM 상위 `attachments[].purpose` enum에 직접 넣지 않음
- PM 상위 purpose는 `accident_scene`, `evidence`, `accident_statement`, `fine_notice`, `unknown` 기준
- `damage_image`는 Supervisor/Vision 내부 `analysis_mode`로만 사용

관련 파일:

```text
ai/vision/schemas.py
etl/attachment_evidence_sample.py
docs/runpod_vision_poc_log.md
```

관련 이슈:

```text
#22 Agent result schema and RAG contract
#38 Vision image/video agent result flow
#40 Cross-MVP integration scenario
```

---

### 2.5 사진 1건 attachment/evidence ERD 연결 샘플

상태: 완료

내용:

- 사진 1건을 `attachment`와 `evidence` 구조로 연결하는 샘플 JSON 생성
- `attachment_id`, `evidence_id`, `source_ref`, `storage_uri` 연결 검증
- Vision Agent가 해당 attachment를 input으로 참조할 수 있는 구조 정의

관련 파일:

```text
etl/attachment_evidence_sample.py
docs/runpod_vision_poc_log.md
```

관련 산출물:

```text
storage/vision/outputs/erd_samples/attachment_evidence_sample.json
```

관련 이슈:

```text
#38 Vision image/video agent result flow
#40 Cross-MVP integration scenario
```

---

### 2.6 Google Drive 전체 listing 및 AI-Hub 학습 후보 Manifest

상태: 완료

내용:

- Google Drive 전체 listing 조회
- 전체 항목 약 33,162개 확인
- `Ai_Hub/Train` 하위 영상 15,823건을 학습 후보 Manifest로 생성
- 세부 24개 카테고리와 상위 4개 라벨 구조 확인

관련 파일:

```text
etl/build_classification_manifest.py
docs/vision_training_plan.md
```

관련 산출물:

```text
storage/vision/manifests/drive_listing_aihub.json
storage/vision/datasets/classification/manifests/classification_manifest.csv
```

관련 이슈:

```text
#36 Vision 후보 모델 목록과 검증 기준
#37 Vision 데이터 manifest pipeline
#39 Vision POC validation
```

---

### 2.7 상위 4개 라벨 기준 샘플링

상태: 완료

내용:

- 세부 24개 카테고리는 데이터 수 편차가 커서 1차 학습 기준에서 제외
- 상위 라벨 4개 기준으로 학습 방향 변경
- 각 상위 라벨별 500개씩 샘플링
- 총 2,000건 구성
- train/val/test = 70/20/10 분할

상위 라벨:

```text
차대차
차대보행자
차대이륜차
차대자전거
```

샘플링 결과:

```text
차대보행자: original=763, sampled=500, train=350, val=100, test=50
차대이륜차: original=1928, sampled=500, train=350, val=100, test=50
차대자전거: original=855, sampled=500, train=350, val=100, test=50
차대차: original=12277, sampled=500, train=350, val=100, test=50
```

관련 파일:

```text
etl/build_classification_manifest.py
etl/sample_classification_dataset.py
docs/vision_training_plan.md
```

관련 산출물:

```text
storage/vision/datasets/classification/manifests/sample_500_coarse_manifest.csv
storage/vision/datasets/classification/manifests/sample_500_coarse_manifest_summary.csv
```

관련 이슈:

```text
#36 Vision 후보 모델 목록과 검증 기준
#37 Vision 데이터 manifest pipeline
#39 Vision POC validation
```

---

### 2.8 샘플 영상 dry-run 다운로드

상태: 완료

내용:

- 상위 라벨별 1개씩 총 4개 영상 다운로드
- Google Drive URL, 저장 경로, 파일명 정책 검증
- 전체 2,000개 다운로드 전 dry-run 검증 완료

관련 파일:

```text
etl/download_sampled_media.py
docs/vision_training_plan.md
```

관련 산출물:

```text
storage/vision/datasets/classification/manifests/dryrun_download_manifest.csv
storage/vision/datasets/classification/raw_videos/{coarse_label}/*.mp4
```

관련 이슈:

```text
#37 Vision 데이터 manifest pipeline
#39 Vision POC validation
```

## 3. 가장 빠르게 진행되어야 하는 부분

### 3.1 프레임 추출 및 frame-level manifest 생성

우선순위: 최상

이유:

- 현재 학습 데이터는 영상 단위 manifest까지만 준비됨
- 이미지 분류 학습을 하려면 영상에서 프레임을 추출해 이미지 데이터셋으로 바꿔야 함
- 다음 학습 파이프라인의 입력이 frame-level manifest이므로 가장 먼저 필요

다음 파일:

```text
etl/extract_classification_frames.py
```

해야 할 일:

```text
dryrun_download_manifest.csv 읽기
다운로드된 영상에서 대표 프레임 추출
frames/{coarse_label}/ 하위에 이미지 저장
frame_classification_manifest.csv 생성
```

관련 이슈:

```text
#37 Vision 데이터 manifest pipeline
#39 Vision POC validation
```

---

### 3.2 학습 파라미터 설정 구조 설계

우선순위: 최상

이유:

- 학습 시 파라미터별 결과 비교가 반드시 필요
- `epoch`, `batch_size`, `learning_rate`, `model_name`, `freeze_backbone`, `frames_per_video`, `sample_manifest` 등을 설정 가능해야 함
- 결과를 run 단위로 저장해야 5주차 트래킹 가능

다음 파일:

```text
ai/vision/train_classifier.py
```

필수 파라미터:

```text
--manifest
--model-name
--pretrained
--freeze-backbone
--batch-size
--learning-rate
--epochs
--image-size
--num-workers
--output-dir
--run-name
```

필수 기록:

```text
run_id
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
```

관련 이슈:

```text
#36 Vision 후보 모델 목록과 검증 기준
#39 Vision POC validation
```

---

### 3.3 RunPod 학습 전 dry-run 기준 확정

우선순위: 높음

이유:

- RunPod는 비용이 발생하므로 학습 코드가 준비된 뒤 켜야 함
- 로컬에서는 4개 영상 dry-run과 소량 frame 추출만 검증
- RunPod에서는 `sample_500_coarse_manifest.csv` 기준으로 대량 다운로드/프레임 추출/학습 진행

해야 할 일:

```text
로컬 dry-run: 라벨별 1~2개 영상
RunPod 1차: 라벨별 500개 영상
RunPod 2차: 필요 시 전체 또는 추가 샘플
```

관련 이슈:

```text
#39 Vision POC validation
```

## 4. 천천히 진행해도 되는 부분

### 4.1 세부 24개 카테고리 학습

우선순위: 낮음

이유:

- 세부 카테고리별 데이터 수 편차가 큼
- 3개, 7개, 12개뿐인 카테고리가 있어 초기 학습 결과가 불안정할 가능성이 큼
- 1차는 상위 4개 라벨 기준으로 안정적인 baseline을 먼저 확보

관련 이슈:

```text
#36 Vision 후보 모델 목록과 검증 기준
```

---

### 4.2 개인정보 식별/비식별 처리

우선순위: 낮음

이유:

- 회의 기준으로 식별 처리는 우선순위를 낮춤
- 단, 향후 UI 표시, 리포트 출력, 외부 공유 시에는 반드시 필요

관련 이슈:

```text
#41 legal/AI guardrail validation
```

---

### 4.3 영상 원본 전체 수집과 전체 데이터 학습

우선순위: 중간 이하

이유:

- 현재 전략은 영상 원본 학습이 아니라 프레임 기반 이미지 분류
- 전체 데이터 다운로드는 비용과 저장소 부담이 큼
- 샘플 500 기준 학습 후 확장 여부 판단

관련 이슈:

```text
#37 Vision 데이터 manifest pipeline
#39 Vision POC validation
```

---

### 4.4 S3 전환

우선순위: 중간 이하

이유:

- Google Drive 연동은 가능함
- 대량 다운로드 안정성 문제가 생길 경우 S3를 차선책으로 검토

관련 이슈:

```text
#37 Vision 데이터 manifest pipeline
```

## 5. 챗봇/웹/ERD 관련 별도 우선순위

Vision/DL과 별개로 챗봇/웹/ERD 쪽은 아래 우선순위로 분리한다.

### 빠르게 진행 필요

```text
챗봇 시퀀스 다이어그램
챗봇 플로우차트
LangGraph 관점 흐름
RAG 호출 흐름
상담 다시 호출하기 흐름
리포트 저장/다운로드 흐름
사건 상태값 흐름
코드테이블 조회 흐름
Supervisor 최종 검증 노드
```

관련 이슈:

```text
#22 Agent result schema and RAG contract
#29 Supervisor routing
#40 Cross-MVP integration scenario
```

### 화면설계서와 함께 확인 필요

```text
ERD와 화면설계서 연결
개인 화면별 플로우
기본 정렬 기준: 상태 -> 날짜
웹 관련 ERD 1차 애자일 범위 확인
```

관련 이슈:

```text
#12 MVP screen and process flows
#40 Cross-MVP integration scenario
```

### 천천히 진행 가능

```text
경찰 API MCP 관점 정리
대법원 API MCP 관점 정리
API 변경 주기 관리
챗봇 적재 데이터 3개월 기준 정책
최신 질문용 최신 데이터 MCP 호출 전략
인증 방식 JWC/JWT 확인
```

관련 이슈:

```text
#20 traffic law data pipeline
#22 Agent result schema and RAG contract
#41 legal/AI guardrail validation
```

## 6. 다음 액션

바로 다음에 진행할 작업:

```text
1. etl/extract_classification_frames.py 생성
2. dryrun_download_manifest.csv 기준으로 4개 영상에서 프레임 추출
3. frame_classification_manifest.csv 생성
4. ai/vision/train_classifier.py에 파라미터 기반 학습 구조 작성
5. ResNet18 baseline dry-run 준비
```
