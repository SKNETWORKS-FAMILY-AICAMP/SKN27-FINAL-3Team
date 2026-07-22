# Vision/DL 테스트 시나리오

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-06-29 |
| 문서 목적 | Vision/DL POC와 Supervisor 연동 흐름을 누락 없이 검증하기 위한 테스트 시나리오를 정의한다. |
| 참고 자료 | `C:/Users/pc/Downloads/테스트시나리오.pdf` |
| 적용 범위 | RunPod, raw media 검증, key frame 추출, YOLO 객체 탐지, VideoMAE 보조 추론, final_analysis, supervisor handoff |
| 관련 이슈 | #38, #37, #39, #22, #70 |

---

## 1. 테스트 시나리오 정의

테스트 시나리오(Test Scenario, TS)는 Vision/DL 기능이 사용자와 Supervisor Agent 관점에서 기대한 흐름대로 동작하는지 확인하기 위한 큰 테스트 흐름이다.

이 문서에서는 개별 코드 단위 테스트보다 다음 흐름이 실제로 연결되는지를 중심으로 검증한다.

```text
사용자 영상/이미지 입력
-> Vision 분석
-> 근거 프레임/객체/clip 생성
-> VideoMAE 보조 추론
-> final_analysis 생성
-> Supervisor handoff 생성
-> 법률/판례/RAG Agent로 전달 가능한 구조 확인
```

---

## 2. 테스트 시나리오가 담는 내용

| 항목 | 설명 |
|---|---|
| 사용자 관점 흐름 | 사용자가 사고 영상 또는 증빙 이미지를 업로드했을 때 어떤 분석 결과를 받는지 확인한다. |
| 시스템 처리 흐름 | raw media, key frame, detection, clip, VideoMAE, final output 생성 흐름을 확인한다. |
| 기대 결과 | 각 단계에서 생성되어야 하는 파일, JSON 필드, 요약 문장, 제한 사항을 정의한다. |
| Agent 연동 | Vision 결과가 Supervisor를 거쳐 법률/판례/RAG Agent로 전달 가능한지 확인한다. |
| 제한 사항 | Vision이 과실비율, 법적 책임, 최종 사고유형을 확정하지 않는지 확인한다. |

---

## 3. 테스트 시나리오의 역할

| 역할 | 설명 |
|---|---|
| 품질 검증 | Vision/DL 분석 파이프라인이 처음부터 끝까지 실행되는지 검증한다. |
| 팀 소통 | Vision 결과가 Supervisor, 법률 Agent, 판례 Agent, RAG Agent에 어떤 형태로 전달되는지 공유한다. |
| 범위 통제 | 단일 영상 POC, 학습 파이프라인, 후속 Agent 연동 범위를 구분한다. |
| 재사용 | 이후 다른 영상/이미지 샘플에도 동일한 기준으로 테스트를 반복할 수 있게 한다. |

---

## 4. TS와 TC 구분

| 구분 | 테스트 시나리오(TS) | 테스트 케이스(TC) |
|---|---|---|
| 목적 | 전체 흐름과 검증 방향 정의 | 개별 입력, 실행 조건, 예상 결과 정의 |
| 관점 | 사용자/Agent 흐름 중심 | 기능 단위 검증 중심 |
| 예시 | 사고 영상 1개가 Vision을 거쳐 Supervisor에 전달되는지 확인 | `python ai/vision/merge_analysis.py` 실행 후 `final_analysis_*.json` 생성 여부 확인 |

이 문서는 TS 중심으로 작성하되, 각 시나리오 안에 필요한 TC 수준의 확인 항목도 함께 포함한다.

---

## 5. 테스트 목표

| 목표 ID | 테스트 목표 | 설명 |
|---|---|---|
| TG-01 | RunPod/로컬 실행 환경 검증 | requirements 기반 패키지 설치와 raw media 접근 가능 여부 확인 |
| TG-02 | Vision POC 분석 흐름 검증 | key frame, YOLO, bbox 변화, event window 생성 확인 |
| TG-03 | VideoMAE 보조 분석 검증 | clip에서 16프레임을 추출하고 pretrained VideoMAE 추론 확인 |
| TG-04 | 최종 Output 생성 검증 | `final_analysis_*.json` 생성 및 필수 필드 확인 |
| TG-05 | Supervisor 연결 검증 | `vision_supervisor_handoff`로 후속 Agent 전달 가능 여부 확인 |
| TG-06 | 제한 사항 검증 | Vision이 과실비율/법적 책임/최종 사고유형을 확정하지 않는지 확인 |

---

## 6. 요구사항 분석

| 요구사항 유형 | 요구사항 | 테스트 반영 |
|---|---|---|
| 기능 요구사항 | 사고 영상에서 key frame을 추출한다. | key frame 5장 생성 여부 확인 |
| 기능 요구사항 | key frame에서 차량/보행자 객체를 탐지한다. | `detected_objects`와 bbox/confidence 확인 |
| 기능 요구사항 | 사고 후보 구간을 생성한다. | `event_window_candidates` 확인 |
| 기능 요구사항 | 짧은 영상은 전체 context로 처리한다. | 10초 이하 영상은 `short_video_full_context`인지 확인 |
| 기능 요구사항 | VideoMAE 보조 추론 결과를 생성한다. | `videomae_results_*.json` 확인 |
| 기능 요구사항 | 최종 분석 결과를 병합한다. | `final_analysis_*.json` 확인 |
| 연동 요구사항 | Supervisor가 후속 Agent로 전달 가능한 스키마가 필요하다. | `vision_supervisor_handoff` 생성 여부 확인 |
| 비기능 요구사항 | RunPod 비용을 줄인다. | GPU가 필요한 단계와 로컬 가능 단계를 분리 |
| 정책 요구사항 | Vision이 법적 판단을 확정하지 않는다. | `unavailable_items`, `limitations` 확인 |

---

## 7. 사용자 관점 테스트 설계

실제 사용자는 내부 모델명을 알 필요가 없다. 따라서 테스트는 다음 사용자 관점 흐름을 기준으로 한다.

```text
1. 사용자가 사고 영상을 업로드한다.
2. 시스템이 영상에서 사고 후보 구간과 근거 프레임을 추출한다.
3. 시스템이 차량/보행자 등 객체 탐지 결과를 생성한다.
4. 시스템이 보조 영상 이해 결과를 생성한다.
5. 시스템이 최종 분석 JSON을 Supervisor에게 전달한다.
6. Supervisor는 법률/판례/RAG Agent로 필요한 항목만 전달한다.
7. 사용자에게는 관찰 근거와 한계를 포함한 설명이 제공된다.
```

---

## 8. 우선순위 및 실행 가능성

| 우선순위 | 시나리오 | 이유 |
|---|---|---|
| P0 | 단일 영상 POC 전체 실행 | 현재 #73 완료 근거이며 모든 후속 흐름의 기준 |
| P0 | final_analysis 생성 | Supervisor에 전달할 최종 Vision 산출물 |
| P0 | vision_supervisor_handoff 생성 | #38 핵심 작업, 법률/판례/RAG 연동 기준 |
| P1 | Run All Notebook 검증 | 발표/검증 시 재현성 확보 |
| P1 | 학습용 manifest 검증 | #37 학습 파이프라인 확장 기준 |
| P2 | 대량 데이터 학습 | GPU 비용과 시간이 크므로 handoff 이후 진행 |
| P2 | VideoMAE fine-tuning | pretrained POC 이후 비교 검증 단계 |

---

## 9. 테스트 시나리오 목록

| TS ID | 시나리오명 | 관련 이슈 | 우선순위 | 테스트 목적 | 예상 결과 |
|---|---|---|---|---|---|
| TS-VISION-001 | raw media 접근 검증 | #37, #39 | P0 | 이미지/영상 파일을 읽을 수 있는지 확인 | `failed_media: 0` |
| TS-VISION-002 | key frame 추출 검증 | #73, #39 | P0 | 단일 영상에서 대표 frame 생성 확인 | `keyframes_*.json`, frame jpg 생성 |
| TS-VISION-003 | YOLO 객체 탐지 검증 | #73, #36 | P0 | 차량/보행자 bbox 탐지 확인 | `detections_*.json` 생성 |
| TS-VISION-004 | Agent Output 생성 검증 | #38, #22 | P0 | YOLO 결과를 Vision Agent Output으로 변환 | `agent_output_*.json` 생성 |
| TS-VISION-005 | bbox 시각화 검증 | #39 | P1 | 탐지 결과를 이미지로 확인 | `*_bbox.jpg` 생성 |
| TS-VISION-006 | clip 후보 생성 검증 | #73, #38 | P0 | event window 또는 짧은 영상 전체 context 기준 clip 후보 생성 | `clip_candidates_*.json` 생성 |
| TS-VISION-007 | clip mp4 추출 검증 | #73, #39 | P0 | 후보 clip을 실제 mp4로 저장 | `processed/clips/*.mp4` 생성 |
| TS-VISION-008 | VideoMAE 입력 프레임 검증 | #73, #38 | P0 | clip별 16프레임 균등 샘플링 확인 | `videomae_clip_manifest_*.json`, 16 jpg 생성 |
| TS-VISION-009 | VideoMAE pretrained 추론 검증 | #73, #36 | P1 | clip-level action hint 생성 확인 | `videomae_results_*.json` 생성 |
| TS-VISION-010 | final_analysis 병합 검증 | #38, #22 | P0 | agent_output과 VideoMAE 결과 병합 | `final_analysis_*.json` 생성 |
| TS-VISION-011 | Supervisor handoff 생성 검증 | #38, #22 | P0 | 후속 Agent 전달용 경량 스키마 생성 | `vision_supervisor_handoff_*.json` 생성 |
| TS-VISION-012 | 제한 사항 검증 | #38, #22 | P0 | Vision이 법률/과실 판단을 확정하지 않는지 확인 | `not_determined_by_vision` 포함 |
| TS-VISION-013 | Notebook 재현성 검증 | #39, #70 | P1 | Jupyter Run All로 전체 흐름 재실행 가능 여부 확인 | 오류 없이 최종 요약 출력 |
| TS-VISION-014 | 학습 manifest 검증 | #37 | P1 | 상위 라벨 기준 샘플링/프레임 manifest 확인 | `frame_manifest_*.csv` 생성 |

---

## 10. 상세 테스트 시나리오

### TS-VISION-001 raw media 접근 검증

| 항목 | 내용 |
|---|---|
| 목적 | RunPod 또는 로컬에서 raw 이미지/영상 파일을 실제로 읽을 수 있는지 확인한다. |
| 사전 조건 | `storage/vision/raw`에 이미지 또는 영상 파일이 존재한다. |
| 실행 명령 | `python scripts/vision/check_raw_media.py` |
| 기대 결과 | 파일 개수와 media 정보가 출력되고 `failed_media: 0`이 출력된다. |
| 실패 시 조치 | 파일 경로, Drive 다운로드 상태, 파일 확장자, OpenCV/Pillow 설치 여부를 확인한다. |

### TS-VISION-002 key frame 추출 검증

| 항목 | 내용 |
|---|---|
| 목적 | 영상에서 대표 key frame을 추출할 수 있는지 확인한다. |
| 사전 조건 | raw 영상 파일이 존재한다. |
| 실행 명령 | `python ai/vision/pipeline.py` |
| 기대 결과 | `storage/vision/processed/frames/*.jpg`, `keyframes_*.json` 생성 |
| 확인 기준 | frame path, timestamp, frame_order가 존재해야 한다. |

### TS-VISION-003 YOLO 객체 탐지 검증

| 항목 | 내용 |
|---|---|
| 목적 | key frame에서 차량/보행자 등 주요 객체를 탐지한다. |
| 사전 조건 | key frame 이미지가 생성되어 있다. |
| 실행 명령 | `python ai/vision/models.py` |
| 기대 결과 | `storage/vision/outputs/detections/detections_*.json` 생성 |
| 확인 기준 | `class_name`, `confidence`, `bbox_xyxy`가 포함되어야 한다. |

### TS-VISION-004 Agent Output 생성 검증

| 항목 | 내용 |
|---|---|
| 목적 | detection 결과를 Supervisor/RAG가 사용할 수 있는 Vision Agent Output으로 변환한다. |
| 사전 조건 | detection JSON이 존재한다. |
| 실행 명령 | `python ai/vision/schemas.py` |
| 기대 결과 | `agent_output_*.json` 생성 |
| 확인 기준 | `event_window_candidates`, `key_frames`, `detected_objects`, `evidence_candidates`, `unavailable_items` 포함 |

### TS-VISION-005 bbox 시각화 검증

| 항목 | 내용 |
|---|---|
| 목적 | 객체 탐지 결과를 사람이 검토 가능한 이미지로 확인한다. |
| 사전 조건 | `agent_output_*.json` 존재 |
| 실행 명령 | `python ai/vision/visualize.py` |
| 기대 결과 | `storage/vision/outputs/visualizations/*_bbox.jpg` 생성 |
| 확인 기준 | 주요 객체 bbox가 이미지에 표시되어야 한다. |

### TS-VISION-006 clip 후보 생성 검증

| 항목 | 내용 |
|---|---|
| 목적 | VideoMAE 또는 후속 검토에 사용할 clip 후보를 생성한다. |
| 사전 조건 | `agent_output_*.json` 존재 |
| 실행 명령 | `python etl/vision/build_clip_candidates.py --short-video-sec 5` |
| 기대 결과 | `clip_candidates_*.json` 생성 |
| 확인 기준 | 10초 이하 영상은 `basis=short_video_full_context`로 전체 영상 사용 |

### TS-VISION-007 clip mp4 추출 검증

| 항목 | 내용 |
|---|---|
| 목적 | clip 후보를 실제 mp4 파일로 저장한다. |
| 사전 조건 | `clip_candidates_*.json` 존재 |
| 실행 명령 | `python etl/vision/extract_video_clips.py --overwrite` |
| 기대 결과 | `storage/vision/processed/clips/*.mp4` 생성 |
| 확인 기준 | `status=ok`, `written_frames > 0` |

### TS-VISION-008 VideoMAE 입력 프레임 검증

| 항목 | 내용 |
|---|---|
| 목적 | clip에서 VideoMAE 입력용 16프레임을 추출한다. |
| 사전 조건 | clip mp4 존재 |
| 실행 명령 | `python etl/vision/extract_videomae_frames.py --overwrite` |
| 기대 결과 | `videomae_clip_manifest_*.json`, clip별 16장 이미지 생성 |
| 확인 기준 | `target_frame_count=16`, `frame_exists=true` |

### TS-VISION-009 VideoMAE pretrained 추론 검증

| 항목 | 내용 |
|---|---|
| 목적 | pretrained VideoMAE로 clip-level action hint를 생성한다. |
| 사전 조건 | VideoMAE input manifest 존재, `transformers` 설치 |
| 실행 명령 | `python ai/vision/videomae_infer.py` |
| 기대 결과 | `videomae_results_*.json` 생성 |
| 확인 기준 | `top_predictions[].label`, `score` 존재 |

### TS-VISION-010 final_analysis 병합 검증

| 항목 | 내용 |
|---|---|
| 목적 | YOLO/bbox 결과와 VideoMAE 보조 결과를 하나의 최종 POC Output으로 병합한다. |
| 사전 조건 | `agent_output_*.json`, `videomae_results_*.json` 존재 |
| 실행 명령 | `python ai/vision/merge_analysis.py` |
| 기대 결과 | `final_analysis_*.json` 생성 |
| 확인 기준 | `vision_agent_output`, `video_understanding`, `comparison_summary`, `limitations` 포함 |

### TS-VISION-011 Supervisor handoff 생성 검증

| 항목 | 내용 |
|---|---|
| 목적 | Supervisor가 법률/판례/RAG Agent로 넘길 경량 스키마를 생성한다. |
| 사전 조건 | `final_analysis_*.json` 존재 |
| 실행 명령 | `python ai/vision/build_supervisor_handoff.py` |
| 기대 결과 | `vision_supervisor_handoff_*.json` 생성 |
| 확인 기준 | `event_candidates`, `visual_evidence`, `video_understanding_hint`, `not_determined_by_vision`, `routing_recommendation` 포함 |
| 비고 | 이 파일은 다음 구현 대상이다. |

### TS-VISION-012 제한 사항 검증

| 항목 | 내용 |
|---|---|
| 목적 | Vision 결과가 법률적 판단을 확정하지 않는지 확인한다. |
| 사전 조건 | `final_analysis_*.json` 또는 `vision_supervisor_handoff_*.json` 존재 |
| 실행 방법 | JSON 필드 확인 |
| 기대 결과 | `fault_ratio`, `liable_party`, `traffic_violation`, `final_accident_type`이 확정값이 아니라 제한/후속 판단 항목으로 표시됨 |

### TS-VISION-013 Notebook 재현성 검증

| 항목 | 내용 |
|---|---|
| 목적 | Jupyter Notebook 하나로 전체 POC 흐름을 실행하고 결과를 확인한다. |
| 사전 조건 | RunPod 또는 로컬에 raw media와 코드가 준비되어 있다. |
| 실행 방법 | `scripts/vision/vision_situation_analysis_review.ipynb`에서 `Run All` 실행 |
| 기대 결과 | 전체 파이프라인 실행 후 final_analysis summary 출력 |
| 실패 시 조치 | `transformers`, `ffmpeg`, raw media 경로, GPU/CPU 환경 확인 |

### TS-VISION-014 학습 manifest 검증

| 항목 | 내용 |
|---|---|
| 목적 | 상위 라벨 기준 학습 데이터 manifest와 frame-level manifest를 검증한다. |
| 사전 조건 | Drive listing 또는 sample manifest 존재 |
| 실행 명령 | `python etl/vision/sample_classification_dataset.py`, `python etl/vision/extract_training_frames.py` |
| 기대 결과 | `sample_700_coarse_manifest.csv`, `frame_manifest_train_700_f8.csv` 생성 |
| 확인 기준 | coarse label, split, frame_path, file_exists 필드 확인 |

---

## 11. 테스트 실행 순서

현재 POC 기준으로 권장 실행 순서는 다음과 같다.

```bash
cd /workspace/SKN27-FINAL-3Team

python scripts/vision/check_raw_media.py
python ai/vision/pipeline.py
python ai/vision/models.py
python ai/vision/schemas.py
python ai/vision/visualize.py
python etl/vision/build_clip_candidates.py --short-video-sec 5
python etl/vision/extract_video_clips.py --overwrite
python etl/vision/extract_videomae_frames.py --overwrite
python ai/vision/videomae_infer.py
python ai/vision/merge_analysis.py
```

Supervisor handoff 구현 후 추가 실행:

```bash
python ai/vision/build_supervisor_handoff.py
```

---

## 12. 테스트 완료 기준

| 완료 기준 | 확인 방법 |
|---|---|
| raw media 읽기 성공 | `failed_media: 0` |
| key frame 생성 성공 | `processed/frames/*.jpg` 존재 |
| detection 생성 성공 | `detections_*.json` 존재 |
| agent output 생성 성공 | `agent_output_*.json` 존재 |
| clip 생성 성공 | `processed/clips/*.mp4` 존재 |
| VideoMAE 입력 생성 성공 | clip별 16프레임 존재 |
| VideoMAE 추론 성공 | `videomae_results_*.json` 존재 |
| final analysis 생성 성공 | `final_analysis_*.json` 존재 |
| Supervisor handoff 생성 성공 | `vision_supervisor_handoff_*.json` 존재 |
| 법률 판단 미확정 명시 | `not_determined_by_vision` 또는 `unavailable_items` 확인 |

---

## 13. 실패/예외 시나리오

| 실패 상황 | 예상 원인 | 조치 |
|---|---|---|
| raw media 읽기 실패 | 파일 없음, Drive 다운로드 실패, 확장자 문제 | raw 경로와 파일 포맷 확인 |
| YOLO 실행 실패 | `ultralytics` 미설치, 모델 weight 없음 | `pip install -r requirements.txt`, `yolov8n.pt` 확인 |
| VideoMAE 실행 실패 | `transformers` 미설치, 모델 다운로드 실패 | `pip install transformers`, 네트워크 확인 |
| Jupyter 영상 재생 실패 | 브라우저 codec 문제, ffmpeg 미설치 | h264 변환 또는 파일 다운로드 후 확인 |
| final_analysis 없음 | merge 이전 단계 결과 없음 | `agent_output`, `videomae_results` 존재 확인 |
| handoff 없음 | `build_supervisor_handoff.py` 미구현 | #38에서 구현 진행 |

---

## 14. 재활용 및 확장 기준

이 테스트 시나리오는 다음 상황에서 재사용한다.

- 새로운 사고 영상 1개를 추가로 검증할 때
- RunPod 환경을 새로 만들었을 때
- 모델 또는 Output Schema가 변경되었을 때
- Supervisor/법률/판례/RAG Agent와 통합 테스트를 진행할 때
- 중간 발표 또는 최종 발표용 샘플 결과를 재현해야 할 때

확장 시 우선 추가할 테스트:

```text
- 여러 영상 batch 처리 테스트
- 10초 초과 긴 영상 clip 분할 테스트
- vision_supervisor_handoff 실제 생성 테스트
- 법률 Agent 전달 mock 테스트
- 판례 Agent 전달 mock 테스트
- RAG 리포트 생성 mock 테스트
```

---

## 15. 정리

현재 Vision/DL 테스트 시나리오의 핵심은 모델 정확도를 바로 평가하는 것이 아니라, 분석 결과가 후속 Agent로 안전하게 전달될 수 있는지를 검증하는 것이다.

따라서 테스트 완료 여부는 다음 기준으로 판단한다.

```text
1. 분석 파이프라인이 끝까지 실행되는가
2. 결과 JSON이 정해진 위치에 생성되는가
3. Supervisor가 읽을 수 있는 필드가 존재하는가
4. 법률/판례/RAG Agent에 넘기면 안 되는 확정 판단이 포함되지 않았는가
5. 후속 Agent로 넘길 handoff 구조가 명확한가
```

