# Vision 사고 유형 분류 및 에이전트 완성 보고서

작성일: 2026-07-21
대상: 차대차, 차대보행자, 차대이륜차, 차대자전거

## 1. 목표

라벨이 있는 사고 영상으로 4종 사고 유형 분류 모델을 만들고, 새 영상에 대해 다음 흐름을 자동 실행한다.

```text
새 영상
→ VideoMAE 사고 유형 분류
→ 카테고리별 선정 YOLO 자동 적용
→ Qwen2.5-VL 상황 분석
→ Supervisor handoff JSON 생성
```

노트북은 학습 과정과 결과 확인에만 사용하고, 최종 실행 경로는 Python 모듈로 제공한다.

## 2. 용어와 모델 역할

- VideoMAE: 사전학습 가중치를 4개 사고 유형으로 지도 파인튜닝하고 자동 유형 분류를 담당한다.
- YOLO: 객체 탐지와 주요 프레임 근거 생성을 담당한다.
- Qwen2.5-VL: 프레임과 고정 프롬프트를 이용한 제로샷 상황 분석을 담당한다. 현재 Qwen 자체를 파인튜닝한 것은 아니다.
- LLaVA-OneVision: 향후 동일 평가셋에서 Qwen과 비교할 후보이며, 현재 일정에서는 필수 실행 대상이 아니다.

## 3. 고정 실험 조건

- 카테고리별 영상: 100개
- 전체 영상: 400개
- 모델 비교와 전처리는 기존 산출물을 우선 재사용한다.
- 이미 정상 완료된 결과는 재실행하지 않는다.
- 최종 평가는 동일 영상, 동일 프레임, 동일 프롬프트, 동일 출력 라벨로 수행한다.

### 선정 YOLO

| 사고 유형 | YOLO |
|---|---|
| 차대차 | `yolov8m.pt` |
| 차대보행자 | `yolo11n.pt` |
| 차대이륜차 | `yolov8m.pt` |
| 차대자전거 | `yolo11s.pt` |

## 4. 완료 상태

### 데이터와 YOLO

- 카테고리별 100개 데이터 구성이 확인됐다.
- 네 카테고리의 `yolo_summary.csv`는 각각 100개 고유 영상을 포함한다.
- 각 요약에는 위에서 선정한 YOLO가 100개 모두 적용돼 있다.

### VideoMAE 파인튜닝

| 실험 | 방식 | 최고 검증 정확도 |
|---|---|---:|
| exp1 | backbone 고정 | 55.00% |
| exp2 | 전체 파인튜닝 5 epoch | 53.75% |
| exp3 | 전체 파인튜닝 + 조기 종료 | 56.25% |

현재 기록상 exp3가 가장 좋다. exp3 체크포인트는 로컬에 동기화됐으며 파일 구성과 클래스 매핑이 정상임을 확인했다. 다음 단계는 새 영상 추론 검증이다.

### Qwen 최종 조건 충족 현황

기준은 `yolo_summary.csv`의 100개 영상, 해당 영상의 선정 YOLO, 정상 JSON 결과다.

| 카테고리 | 정상 재사용 가능 | 추가 Qwen 처리 |
|---|---:|---:|
| 차대차 | 60 | 40 |
| 차대보행자 | 68 | 32 |
| 차대이륜차 | 71 | 29 |
| 차대자전거 | 12 | 88 |
| 합계 | 211 | 189 |

기존 Qwen CSV에는 과거 샘플과 여러 YOLO 결과가 섞여 있다. 원본 CSV는 보존하고, 최종 100개 결과는 별도 파일로 생성해야 한다.

## 5. 구현 상태

### Python 모듈

- `ai/vision/train_videomae_classifier.py`: VideoMAE 학습
- `ai/vision/trained_category_classifier.py`: 학습 체크포인트 탐색 및 추론
- `ai/vision/category_vlm_config.py`: 카테고리와 선정 YOLO 설정
- `ai/vision/run_to_supervisor.py`: 기존 통합 실행 파일이며 Supervisor 담당자와 협의 없이 수정하지 않는다.
- `ai/vision/build_supervisor_handoff.py`: Supervisor 담당 영역이므로 Vision 팀에서 수정하지 않는다.
- `ai/vision/audit_category_results.py`: 카테고리별 100개 완료 상태 검사

Vision 팀은 자동 사고 유형 분류 결과, 선정 YOLO, Qwen 분석 결과를 명확한 Python 반환값 또는 JSON으로 제공한다. Supervisor 연결 변경은 담당 팀원에게 인터페이스와 예시 데이터만 전달한다.

## 6. 다음 실행 순서

1. RunPod의 학습 분할 manifest를 로컬로 동기화한다.
2. 라벨 없는 영상 1개로 로컬 exp3 VideoMAE 추론을 검증한다.
3. 기존 Qwen 정상 결과 211개를 재사용한다.
4. 선정 YOLO 기준으로 누락 또는 파싱 실패한 189개만 Qwen으로 보완한다.
5. 카테고리별 정확히 100행인 최종 결과 CSV를 별도 생성한다.
6. Vision 단독 Python 실행으로 자동 분류 → YOLO → Qwen 결과를 검증한다.
7. 검증된 Vision 출력 스키마와 예시 JSON을 Supervisor 담당자에게 전달한다.
8. 시간이 허용될 때 동일 400개 평가셋으로 LLaVA를 실행해 Qwen과 비교한다.

## 7. 필요한 추가 파일

RunPod에서 다음 파일만 추가로 필요하다.

```text
storage/vision/datasets/classification/manifests/train_100_raw_video_manifest_split.csv
```

exp3 체크포인트는 로컬에 있으며 `config.json`, `model.safetensors`, 전처리 설정, 클래스 매핑, 실행 설정, 학습 이력이 모두 확인됐다. 추가 원본 영상은 현재 필요하지 않다. 기존 400개와 전처리 산출물을 재사용한다.

## 8. 완료 판정 기준

- 네 카테고리 모두 YOLO 고유 영상 100개
- 네 카테고리 모두 선정 YOLO 기준 정상 Qwen 결과 100개
- exp3 체크포인트 로컬 검증 완료
- 라벨 없는 새 영상의 자동 사고 유형 분류 성공
- 분류 결과에 맞는 YOLO 자동 선택 확인
- Vision 출력 스키마와 예시 JSON 생성 확인
- Supervisor 연결은 담당 팀원의 별도 검증 대상으로 유지
