# RunPod Vision POC 진행 기록

작성일: 2026-06-26

## 1. 목적

차량 사고 이미지/영상 Vision POC를 위해 RunPod 환경에서 Google Drive 데이터를 불러오고, 이미지와 영상 파일을 실제로 읽을 수 있는지 검증했다.

이번 단계의 완료 기준은 다음과 같다.

- RunPod Pod 생성 및 GPU 환경 확인
- 프로젝트 폴더 구조 생성
- `requirements.txt` 기반 패키지 설치
- Google Drive 샘플 이미지 다운로드
- 이미지 읽기 검증
- Manifest CSV 생성
- Google Drive 샘플 영상 다운로드
- 영상 읽기 검증
- Key Frame 추출 코드 준비

## 2. RunPod 모델 및 Pod 설정

초기 POC 목적이므로 대형 학습용 GPU가 아니라 비용 대비 안정적인 단일 GPU 구성을 선택했다.

선택 기준:

- GPU 1개만 사용
- On-Demand 요금제 사용
- PyTorch/CUDA가 포함된 템플릿 사용
- Jupyter Notebook과 SSH Terminal 활성화
- 저장공간은 샘플/POC 기준 50~100GB 권장

사용한 설정:

```text
Pod template: Runpod Pytorch 2.4.0
Image: runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04
GPU count: 1
Pricing: On-Demand
SSH terminal access: ON
Start Jupyter notebook: ON
Encrypt volume: OFF
```

`Encrypt volume`은 샘플 데이터 기준으로는 끄고 진행했다. 실제 사고 사진, 개인정보, 보험 민감 데이터가 포함될 경우에는 켜는 것이 좋다.

## 3. RunPod 접속 방식

RunPod Pod가 Running 상태가 된 뒤 `HTTP Services`에서 Jupyter Notebook에 접속했다.

Jupyter에서는 Notebook 셀보다 Terminal을 사용했다.

진행 순서:

```text
RunPod Pod Running 확인
HTTP Services 접속
Jupyter Notebook 열기
Launcher 또는 File 메뉴에서 Terminal 열기
Terminal에서 명령 실행
```

## 4. 프로젝트 폴더 구조 생성

로컬 프로젝트 구조와 동일하게 RunPod에도 `/workspace/SKN27-FINAL-3Team` 루트를 만들었다.

```bash
mkdir -p /workspace/SKN27-FINAL-3Team
cd /workspace/SKN27-FINAL-3Team

mkdir -p ai/vision
mkdir -p app
mkdir -p docs
mkdir -p etl
mkdir -p scripts
mkdir -p test
mkdir -p storage/vision/raw
mkdir -p storage/vision/processed
mkdir -p storage/vision/manifests
mkdir -p storage/vision/outputs
mkdir -p storage/vision/models
```

확인 명령:

```bash
find . -maxdepth 3 -type d | sort
```

기대 구조:

```text
.
./ai
./ai/vision
./app
./docs
./etl
./scripts
./storage
./storage/vision
./storage/vision/manifests
./storage/vision/models
./storage/vision/outputs
./storage/vision/processed
./storage/vision/raw
./test
```

## 5. requirements.txt 설정

처음에는 버전을 고정한 `requirements.txt`를 사용했지만, RunPod에서 다음 에러가 발생했다.

```text
No matching distribution found for numpy==2.5.0
```

원인:

- `numpy==2.5.0`처럼 아직 설치 가능한 안정 배포판이 없는 버전이 포함되어 있었다.
- POC 단계에서는 세부 버전 고정보다 설치 가능한 최신 안정 버전을 사용하는 편이 안전하다.

따라서 RunPod에서는 다음처럼 버전 고정을 제거했다.

```bash
cat > requirements.txt << 'EOF'
numpy
pandas
opencv-python
pillow
tqdm
python-dotenv
boto3
gdown
ultralytics
EOF
```

설치:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

설치 완료 후 `numpy`, `pandas`, `opencv-python`, `pillow`, `gdown`, `ultralytics` 등이 설치되었다.

## 6. Google Drive 이미지 샘플 다운로드

전체 데이터는 용량과 하위 폴더 구조가 복잡하므로, 먼저 샘플 이미지 10장만 별도 폴더로 만들어 테스트했다.

다운로드 명령:

```bash
python -m gdown --folder "GOOGLE_DRIVE_SAMPLE_IMAGE_FOLDER_URL" -O storage/vision/raw
```

주의:

Markdown 링크 형식이 아니라 순수 URL만 넣어야 한다.

잘못된 예:

```bash
python -m gdown --folder "[https://drive.google.com/...](https://drive.google.com/...)" -O storage/vision/raw
```

올바른 예:

```bash
python -m gdown --folder "https://drive.google.com/drive/folders/..." -O storage/vision/raw
```

다운로드 확인:

```bash
ls -lh storage/vision/raw
```

확인된 이미지:

```text
864.jpg
865.jpg
866.jpg
867.jpg
868.jpg
869.jpg
870.jpg
871.jpg
872.jpg
873.jpg
```

## 7. 이미지 읽기 검증

생성 파일:

```text
scripts/check_raw_images.py
```

역할:

- `storage/vision/raw` 아래 이미지 파일 검색
- `PIL.Image`로 이미지 열기
- 이미지 해상도와 모드 출력
- 읽기 실패 파일 개수 출력

실행:

```bash
python scripts/check_raw_images.py
```

성공 결과:

```text
raw_dir: storage/vision/raw
found_images: 10
OK   storage/vision/raw/864.jpg | 28x28 RGB
OK   storage/vision/raw/865.jpg | 28x28 RGB
OK   storage/vision/raw/866.jpg | 28x28 RGB
OK   storage/vision/raw/867.jpg | 28x28 RGB
OK   storage/vision/raw/868.jpg | 28x28 RGB
OK   storage/vision/raw/869.jpg | 28x28 RGB
OK   storage/vision/raw/870.jpg | 28x28 RGB
OK   storage/vision/raw/871.jpg | 28x28 RGB
OK   storage/vision/raw/872.jpg | 28x28 RGB
OK   storage/vision/raw/873.jpg | 28x28 RGB
checked_images: 10
failed_images: 0
```

판정:

```text
RunPod에서 Google Drive 이미지 샘플 다운로드 성공
RunPod에서 이미지 파일 읽기 성공
```

## 8. Manifest 생성

생성 파일:

```text
etl/vision_data.py
```

역할:

- `storage/vision/raw` 아래 이미지 파일 검색
- 파일 존재 여부 확인
- 이미지 읽기 가능 여부 확인
- `storage/vision/manifests/sample_manifest.csv` 생성

실행:

```bash
python etl/vision_data.py
```

성공 결과:

```text
manifest_path: storage/vision/manifests/sample_manifest.csv
manifest_rows: 10
```

Manifest 확인:

```bash
head -n 20 storage/vision/manifests/sample_manifest.csv
```

생성 결과:

```csv
asset_id,dataset_name,input_type,file_path,label_path,file_exists,media_readable,planned_use
sample_000001,drive_sample_10,image,storage/vision/raw/864.jpg,,True,True,runpod_drive_ingestion_poc
sample_000002,drive_sample_10,image,storage/vision/raw/865.jpg,,True,True,runpod_drive_ingestion_poc
sample_000003,drive_sample_10,image,storage/vision/raw/866.jpg,,True,True,runpod_drive_ingestion_poc
sample_000004,drive_sample_10,image,storage/vision/raw/867.jpg,,True,True,runpod_drive_ingestion_poc
sample_000005,drive_sample_10,image,storage/vision/raw/868.jpg,,True,True,runpod_drive_ingestion_poc
sample_000006,drive_sample_10,image,storage/vision/raw/869.jpg,,True,True,runpod_drive_ingestion_poc
sample_000007,drive_sample_10,image,storage/vision/raw/870.jpg,,True,True,runpod_drive_ingestion_poc
sample_000008,drive_sample_10,image,storage/vision/raw/871.jpg,,True,True,runpod_drive_ingestion_poc
sample_000009,drive_sample_10,image,storage/vision/raw/872.jpg,,True,True,runpod_drive_ingestion_poc
sample_000010,drive_sample_10,image,storage/vision/raw/873.jpg,,True,True,runpod_drive_ingestion_poc
```

판정:

```text
Manifest CSV 생성 성공
file_exists=True
media_readable=True
```

## 9. Google Drive 영상 샘플 다운로드

영상 샘플 폴더에 `.mp4` 파일 1개를 넣고 RunPod에서 다운로드했다.

다운로드 명령:

```bash
python -m gdown --folder "GOOGLE_DRIVE_SAMPLE_VIDEO_FOLDER_URL" -O storage/vision/raw
```

확인:

```bash
ls -lh storage/vision/raw
```

확인된 영상:

```text
bb_3_190909_pedestrian_226_21450.mp4
```

## 10. 이미지 + 영상 통합 읽기 검증

생성 파일:

```text
scripts/check_raw_media.py
```

역할:

- `storage/vision/raw` 아래 이미지와 영상 파일 검색
- 이미지는 `PIL.Image`로 읽기 검증
- 영상은 `cv2.VideoCapture`로 열기 검증
- 영상 첫 프레임 읽기 검증
- 영상 해상도, FPS, 프레임 수 출력

실행:

```bash
python scripts/check_raw_media.py
```

성공 결과:

```text
raw_dir: storage/vision/raw
found_media: 11
OK   storage/vision/raw/864.jpg | image 28x28 RGB
OK   storage/vision/raw/865.jpg | image 28x28 RGB
OK   storage/vision/raw/866.jpg | image 28x28 RGB
OK   storage/vision/raw/867.jpg | image 28x28 RGB
OK   storage/vision/raw/868.jpg | image 28x28 RGB
OK   storage/vision/raw/869.jpg | image 28x28 RGB
OK   storage/vision/raw/870.jpg | image 28x28 RGB
OK   storage/vision/raw/871.jpg | image 28x28 RGB
OK   storage/vision/raw/872.jpg | image 28x28 RGB
OK   storage/vision/raw/873.jpg | image 28x28 RGB
OK   storage/vision/raw/bb_3_190909_pedestrian_226_21450.mp4 | video 1920x1080 fps=... frames=150
failed_media: 0
```

판정:

```text
RunPod에서 Google Drive 영상 다운로드 성공
RunPod에서 영상 파일 열기 성공
첫 프레임 읽기 성공
이미지 + 영상 통합 검증 성공
```

## 11. Key Frame 추출 코드 준비

생성 파일:

```text
ai/vision/pipeline.py
```

역할:

- `storage/vision/raw` 아래 첫 번째 영상 파일 검색
- 영상 메타데이터 확인
- 총 5개의 대표 프레임 추출
- `storage/vision/processed/frames`에 `.jpg` 저장
- `storage/vision/outputs/keyframes_{video_stem}.json` 생성

실행:

```bash
python ai/vision/pipeline.py
```

기대 결과:

```text
source_video: storage/vision/raw/bb_3_190909_pedestrian_226_21450.mp4
total_frames: 150
fps: ...
keyframe_count: 5
output_path: storage/vision/outputs/keyframes_bb_3_190909_pedestrian_226_21450.json
ok frame_index=0 timestamp_sec=... path=storage/vision/processed/frames/...
ok frame_index=37 timestamp_sec=... path=storage/vision/processed/frames/...
ok frame_index=74 timestamp_sec=... path=storage/vision/processed/frames/...
ok frame_index=112 timestamp_sec=... path=storage/vision/processed/frames/...
ok frame_index=149 timestamp_sec=... path=storage/vision/processed/frames/...
```

생성 확인:

```bash
ls -lh storage/vision/processed/frames
cat storage/vision/outputs/keyframes_bb_3_190909_pedestrian_226_21450.json
```

## 12. 현재 완료 상태

완료:

- RunPod Pod 설정
- Jupyter Terminal 사용
- 프로젝트 폴더 구조 생성
- `requirements.txt` 설치 문제 해결
- Google Drive 이미지 샘플 다운로드
- 이미지 읽기 검증
- Manifest CSV 생성
- Google Drive 영상 샘플 다운로드
- 영상 읽기 검증
- `ai/vision/pipeline.py`로 Key Frame 5장 추출
- `storage/vision/processed/frames`에 프레임 이미지 저장 확인
- `storage/vision/outputs/keyframes_*.json` 생성
- `ai/vision/models.py`로 YOLO/Ultralytics 객체 탐지 baseline 실행
- `storage/vision/outputs/detections/detections_*.json` 생성

RunPod에서 확인된 Key Frame 파일:

```text
storage/vision/processed/frames/bb_3_190909_pedestrian_226_21450_frame_01_000000.jpg
storage/vision/processed/frames/bb_3_190909_pedestrian_226_21450_frame_02_000037.jpg
storage/vision/processed/frames/bb_3_190909_pedestrian_226_21450_frame_03_000074.jpg
storage/vision/processed/frames/bb_3_190909_pedestrian_226_21450_frame_04_000112.jpg
storage/vision/processed/frames/bb_3_190909_pedestrian_226_21450_frame_05_000149.jpg
```

RunPod에서 확인된 detection 결과:

```text
storage/vision/outputs/detections/detections_bb_3_190909_pedestrian_226_21450.json
```

아직 진행 전:

- detection JSON 내용을 계획서 Schema 형태로 정리
- 사진 attachment/evidence ERD 연결 흐름 정리
- 객체 탐지 결과 시각화 이미지 생성
- 더 큰 실제 사고 이미지/영상 샘플로 재검증
## 13. 현재 다음 작업 기준

현재 RunPod에서는 아래 흐름까지 성공했다.

```text
Drive 영상 다운로드
→ 영상 읽기 검증
→ Key Frame 5장 추출
→ YOLO 객체 탐지 baseline
→ PM 기준 Agent Output JSON 생성
→ bbox 시각화 이미지 생성 준비
```

다음 우선순위는 다음과 같다.

```text
1. RunPod에서 ai/vision/visualize.py 실행
2. bbox 시각화 이미지 5장 생성 확인
3. Jupyter 파일 브라우저 또는 Notebook에서 실제 이미지 확인
4. 시각화 결과 경로를 evidence_candidates에 연결할지 결정
5. 사진 1건 attachment/evidence ERD 연결 샘플 생성
```

현재 기준에서 더 이상 해야 할 확인:

```bash
cd /workspace/SKN27-FINAL-3Team
python ai/vision/visualize.py
ls -lh storage/vision/outputs/visualizations
cat storage/vision/outputs/visualizations/visualizations_bb_3_190909_pedestrian_226_21450.json
```
## 14. YOLO 객체 탐지 baseline

생성 파일:

```text
ai/vision/models.py
```

역할:

- `storage/vision/outputs/keyframes_*.json` 중 최신 파일을 찾는다.
- Key Frame JSON에 기록된 `frame_path`를 읽는다.
- Ultralytics YOLO 기본 모델인 `yolov8n.pt`를 사용한다.
- 각 프레임별 객체 탐지 결과를 생성한다.
- `class_id`, `class_name`, `confidence`, `bbox_xyxy`를 저장한다.
- 결과를 `storage/vision/outputs/detections/detections_{video_stem}.json`에 저장한다.

실행 전 Key Frame 추출:

```bash
cd /workspace/SKN27-FINAL-3Team
python ai/vision/pipeline.py
```

객체 탐지 실행:

```bash
python ai/vision/models.py
```

첫 실행 시 `yolov8n.pt` weight가 자동 다운로드될 수 있다. RunPod에서 네트워크가 막히면 weight 다운로드 단계에서 실패할 수 있으므로, 그 경우 모델 파일을 수동 업로드하거나 S3/Drive에 weight를 보관하는 방식으로 바꾼다.

성공 결과 예시:

```text
keyframe_output_path: storage/vision/outputs/keyframes_bb_3_190909_pedestrian_226_21450.json
detection_output_path: storage/vision/outputs/detections/detections_bb_3_190909_pedestrian_226_21450.json
detection_frame_count: 5
ok frame_order=1 frame_index=0 object_count=...
ok frame_order=2 frame_index=37 object_count=...
ok frame_order=3 frame_index=74 object_count=...
ok frame_order=4 frame_index=112 object_count=...
ok frame_order=5 frame_index=149 object_count=...
```

결과 확인:

```bash
ls -lh storage/vision/outputs/detections
cat storage/vision/outputs/detections/detections_bb_3_190909_pedestrian_226_21450.json
```

완료 기준:

```text
Key Frame 5장에 대해 YOLO 객체 탐지 실행
각 프레임별 object_count 생성
객체별 class_name, confidence, bbox_xyxy 생성
detections JSON 파일 생성
```



## 15. PM 기준 Vision Agent Output Schema 정합화

참고 문서:

```text
D:/dev/개인 업무/DeepLearning/docs/수정/vision_agent_input_output_schema.md
D:/dev/회의록/11차 회의(26.06.25)/pm-supervisor-node-schema-owner-summary-2026-06-25.pdf
```

반영 기준:

- Vision Agent 대상 node는 `vision_media_analysis`이다.
- Output은 `agent_output > structured_result` 형태를 사용한다.
- `structured_result`에는 `media_type`, `observations`, `detected_objects`, `road_type_candidates`, `accident_type_candidates`, `risk_event_candidates`, `event_window`, `key_frames`, `damage_area_candidates`, `evidence_candidates`, `limitations`를 둔다.
- PM 상위 `attachments[].purpose` enum은 `fine_notice`, `accident_scene`, `accident_statement`, `evidence`, `unknown`을 기준으로 한다.
- `damage_image`는 PM 상위 purpose enum에 직접 포함하지 않는다.
- `damage_image`는 Supervisor 내부 매핑 또는 Vision 내부 `analysis_mode`에서만 사용한다.

관련 구현 파일:

```text
ai/vision/schemas.py
```

실행:

```bash
cd /workspace/SKN27-FINAL-3Team
python ai/vision/schemas.py
```

생성 결과:

```text
storage/vision/outputs/agent_outputs/agent_output_{video_stem}.json
```

확인:

```bash
cat storage/vision/outputs/agent_outputs/agent_output_bb_3_190909_pedestrian_226_21450.json
```

## 16. 객체 탐지 bbox 시각화

생성 파일:

```text
ai/vision/visualize.py
```

역할:

- `storage/vision/outputs/agent_outputs/agent_output_*.json` 중 최신 파일을 읽는다.
- `structured_result.detected_objects`의 bbox를 key frame 이미지에 그린다.
- `storage/vision/outputs/visualizations`에 bbox 시각화 이미지를 저장한다.
- 생성된 시각화 이미지 목록을 `visualizations_{video_stem}.json`으로 저장한다.

실행:

```bash
cd /workspace/SKN27-FINAL-3Team
python ai/vision/visualize.py
```

결과 확인:

```bash
ls -lh storage/vision/outputs/visualizations
cat storage/vision/outputs/visualizations/visualizations_bb_3_190909_pedestrian_226_21450.json
```

완료 기준:

```text
Key Frame 5장에 대해 bbox 시각화 이미지 생성
각 시각화 이미지 경로가 visualizations JSON에 기록
발표/검증용으로 객체 탐지 결과를 눈으로 확인 가능
```
## 17. RunPod에서 생성 이미지 확인 방법

bbox 시각화 이미지가 생성되면 RunPod 안에서 바로 확인할 수 있다.

### 17.1 Jupyter 파일 브라우저에서 확인

가장 쉬운 방법이다.

RunPod의 Jupyter Notebook 화면에서 왼쪽 파일 브라우저를 열고 아래 경로로 이동한다.

```text
/workspace/SKN27-FINAL-3Team/storage/vision/outputs/visualizations/
```

예상 파일:

```text
bb_3_190909_pedestrian_226_21450_frame_01_000000_bbox.jpg
bb_3_190909_pedestrian_226_21450_frame_02_000037_bbox.jpg
bb_3_190909_pedestrian_226_21450_frame_03_000074_bbox.jpg
bb_3_190909_pedestrian_226_21450_frame_04_000112_bbox.jpg
bb_3_190909_pedestrian_226_21450_frame_05_000149_bbox.jpg
```

파일명을 클릭하면 브라우저에서 bbox가 그려진 이미지를 볼 수 있다.

### 17.2 Jupyter Notebook에서 여러 장 표시

새 Notebook을 열고 아래 코드를 실행한다.

```python
from IPython.display import Image, display
from pathlib import Path

vis_dir = Path("/workspace/SKN27-FINAL-3Team/storage/vision/outputs/visualizations")

for path in sorted(vis_dir.glob("*_bbox.jpg")):
    print(path.name)
    display(Image(filename=str(path)))
```

### 17.3 로컬 PC로 다운로드

이미지 파일을 하나씩 받을 경우 Jupyter 파일 브라우저에서 파일을 선택해 다운로드한다.

여러 장을 한 번에 받을 경우 RunPod 터미널에서 zip으로 묶는다.

```bash
cd /workspace/SKN27-FINAL-3Team
zip -r vision_visualizations.zip storage/vision/outputs/visualizations
```

그 다음 Jupyter 파일 브라우저에서 `vision_visualizations.zip`을 다운로드한다.

## 18. 현재까지 RunPod 산출물 요약

RunPod 작업 루트:

```text
/workspace/SKN27-FINAL-3Team
```

주요 입력:

```text
storage/vision/raw/864.jpg ~ 873.jpg
storage/vision/raw/bb_3_190909_pedestrian_226_21450.mp4
```

중간 산출물:

```text
storage/vision/manifests/sample_manifest.csv
storage/vision/processed/frames/*.jpg
storage/vision/outputs/keyframes_bb_3_190909_pedestrian_226_21450.json
storage/vision/outputs/detections/detections_bb_3_190909_pedestrian_226_21450.json
```

PM 기준 최종 Agent Output:

```text
storage/vision/outputs/agent_outputs/agent_output_bb_3_190909_pedestrian_226_21450.json
```

시각화 예정 산출물:

```text
storage/vision/outputs/visualizations/*_bbox.jpg
storage/vision/outputs/visualizations/visualizations_bb_3_190909_pedestrian_226_21450.json
```

현재 구현 파일:

```text
scripts/check_raw_images.py
scripts/check_raw_media.py
etl/vision_data.py
ai/vision/pipeline.py
ai/vision/models.py
ai/vision/schemas.py
ai/vision/visualize.py
```

다음 개발 후보:

```text
1. visualizations 결과를 evidence_candidates에 연결
2. 사진 1건 attachment/evidence ERD 연결 샘플 JSON 생성
3. 실제 사고 이미지/영상 샘플로 재검증
4. key frame 추출을 균등 샘플링에서 장면 변화/객체 변화 기준으로 개선
```


## 19. 사진 1건 attachment/evidence ERD 연결 샘플

목적:

- 영상 분석 전후 흐름과 별도로, 사진 1건이 서비스 DB의 `attachment`와 `evidence` 개념으로 어떻게 연결될 수 있는지 샘플 JSON으로 검증한다.
- GPU가 필요 없는 구조 검증 작업이므로 로컬에서 진행한다.
- PM 상위 purpose enum에는 `damage_image`를 직접 쓰지 않는다.
- 사진 파손 분석이 필요할 경우 상위 purpose는 `evidence` 또는 `accident_scene`로 두고, Supervisor/Vision 내부에서만 `analysis_mode=damage_image`로 매핑한다.

생성 파일:

```text
etl/attachment_evidence_sample.py
```

실행:

```powershell
cd D:\dev\SKN27-FINAL-3Team
.\.venv\Scripts\python.exe etl\attachment_evidence_sample.py
```

현재 샘플 입력:

```text
storage/vision/raw/864.jpg
```

생성 결과:

```text
storage/vision/outputs/erd_samples/attachment_evidence_sample.json
```

샘플 JSON의 주요 구조:

```text
attachment
- attachment_id
- message_id
- media_type=image
- purpose=evidence
- mime_type
- storage_uri
- file_name
- file_exists
- privacy_risk

evidence
- evidence_id
- attachment_id
- evidence_type=uploaded_image
- source_uri
- source_ref
- description
- usable_for_agent

vision_reference
- node_code=vision_media_analysis
- input_ref
- analysis_mode
- expected_structured_result_fields
- expected_output_link
```

완료 기준:

```text
사진 1건이 attachment_id를 가진다.
evidence가 attachment_id를 참조한다.
Vision Agent가 attachment_id를 input_ref로 받을 수 있다.
evidence_candidates와 detected_objects가 원본 이미지 경로 또는 source_ref로 연결될 수 있다.
```

다음 개선 후보:

```text
1. 실제 DB ERD의 attachment/evidence 테이블명과 컬럼명에 맞춰 필드명 조정
2. attachment/evidence 샘플을 Agent Input Schema와 직접 연결
3. image 단일 입력에 대한 Vision Agent Output 샘플 생성
4. 파손 이미지일 경우 purpose=evidence, analysis_mode=damage_image 매핑 검증
```

---

## 학습 파이프라인 전환: frame-level manifest dry-run

단일 영상 POC 이후 학습 파이프라인 검증으로 전환했다.

추가 파일:

```text
etl/extract_training_frames.py
```

역할:

```text
video-level manifest
→ 각 영상에서 대표 프레임 추출
→ frame-level classification manifest 생성
```

로컬 dry-run 결과:

```text
입력 영상: 라벨별 1개, 총 4개
추출 기준: 영상 1개당 5장
생성 프레임: 총 20장
상위 라벨: 차대보행자, 차대이륜차, 차대자전거, 차대차
결과: extract_status=extracted 20건
```

생성 산출물:

```text
storage/vision/datasets/classification/manifests/frame_manifest_dryrun.csv
storage/vision/datasets/classification/manifests/frame_manifest_dryrun_summary.csv
storage/vision/datasets/classification/frames/
```

판정:

```text
학습 코드 작성 전 필요한 frame-level manifest 생성 검증 완료
다음 단계는 classifier baseline 학습 코드 작성
```

---

## Classifier baseline dry-run

프레임 추출 검증 이후 `ai/vision/train_classifier.py`를 추가하여 학습 루프 dry-run을 수행했다.

입력:

```text
storage/vision/datasets/classification/manifests/frame_manifest_dryrun.csv
```

설정:

```text
model: resnet18
pretrained: false
freeze_backbone: true
epochs: 1
batch_size: 4
image_size: 128
device: cpu
```

결과:

```text
train_rows: 15
val_rows: 5
test_rows: 0
train_loss: 1.554665
train_accuracy: 0.000000
val_loss: 1.414263
val_accuracy: 0.200000
```

판정:

```text
로컬 small sample 기준 학습 루프와 결과 저장이 정상 동작했다.
정확도는 데이터 20장 dry-run 결과이므로 성능 평가로 사용하지 않는다.
```

다음 RunPod 전환 기준:

```text
라벨별 5~10개 영상으로 dry-run 규모를 한 번 더 키운 뒤,
RunPod에서 sample_500_coarse_manifest.csv 기반 학습으로 확장한다.
```

<!-- 2026-06-29-videomae-final-analysis -->

## 18. VideoMAE 보조 추론 및 최종 분석 병합

작성일: 2026-06-29

단일 블랙박스 영상 POC에서 YOLO/bbox 기반 결과와 VideoMAE pretrained clip 추론 결과를 하나의 최종 분석 JSON으로 병합했다.

### 18.1 실행 순서

```bash
cd /workspace/SKN27-FINAL-3Team

python etl/build_clip_candidates.py --short-video-sec 10
python etl/extract_video_clips.py --overwrite
python etl/extract_videomae_frames.py --overwrite
python ai/vision/videomae_infer.py
python ai/vision/merge_analysis.py
```

### 18.2 생성 산출물

```text
storage/vision/outputs/clip_candidates/clip_candidates_*.json
storage/vision/processed/clips/*.mp4
storage/vision/outputs/videomae_inputs/videomae_clip_manifest_*.json
storage/vision/processed/videomae_frames/**/*.jpg
storage/vision/outputs/videomae_results/videomae_results_*.json
storage/vision/outputs/final_analysis/final_analysis_*.json
```

### 18.3 검증 결과

```text
schema_version: vision-final-analysis-v1
status: success
event_windows: 1
key_frames: 5
detected_objects: 16
videomae: clip_01 driving car 0.563136
```

### 18.4 판단

- 짧은 영상 기준은 10초 이하로 정리했다.
- 10초 이하 영상은 clip을 자르지 않고 전체 영상을 VideoMAE 비교 입력으로 사용한다.
- 긴 영상은 bbox 변화 기반 event window 후보를 중심으로 clip을 생성한다.
- VideoMAE 결과는 사고유형 확정 결과가 아니라 clip-level action hint로만 사용한다.
- 최종 결과는 `final_analysis_*.json`에서 YOLO/bbox 결과와 VideoMAE 결과를 함께 확인한다.

### 18.5 Jupyter Notebook 실행 방식

`scripts/vision_situation_analysis_review.ipynb`에 전체 파이프라인 실행 셀을 추가했다.

RunPod Jupyter에서 노트북을 열고 `Run All`을 실행하면 다음 순서가 한 번에 실행된다.

```text
raw media check
-> key frame extraction
-> YOLO detection
-> agent output schema conversion
-> bbox visualization
-> clip candidate build
-> clip extraction
-> VideoMAE 16-frame extraction
-> VideoMAE pretrained inference
-> final analysis merge
-> final_analysis summary review
```

단, VideoMAE 추론은 `transformers`와 pretrained model download가 필요하므로 최초 실행 시 시간이 더 걸릴 수 있다.

