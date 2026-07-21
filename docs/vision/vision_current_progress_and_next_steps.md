# Vision 현재 진행 현황 및 고도화 계획

- 기준일: 2026-07-21
- 범위: Vision 전용 데이터·학습·추론·Python 파이프라인
- 제외: Supervisor 소스 수정, 과실비율 및 법률 판단 확정

## 1. 최종 방향

데이터는 다음 4개 사고 유형별 100개, 총 400개로 고정한다.

| 사고 유형 | 데이터 수 | 선정 YOLO |
|---|---:|---|
| 차대차 | 100 | `yolov8m.pt` |
| 차대보행자 | 100 | `yolo11n.pt` |
| 차대이륜차 | 100 | `yolov8m.pt` |
| 차대자전거 | 100 | `yolo11s.pt` |

추가 데이터를 무조건 확보하거나 완료된 실험을 다시 실행하지 않는다. 동일 데이터·동일 split·동일 전처리 조건을 유지하고, 기존 결과와 캐시를 재사용해 미완료 항목만 수행한다.

최종 목표는 라벨이 없는 새 영상에 대해 다음 흐름을 자동 실행하는 Vision Agent다.

```text
새 영상
→ 공통 전처리
→ VideoMAE 4종 사고 유형 분류
→ 예측 유형에 맞는 YOLO 자동 선택
→ 객체·사고 후보 분석
→ 선정 VLM의 상황 설명
→ confidence·limitations를 포함한 Vision JSON 생성
→ Supervisor 담당자에게 전달
```

실제 실행 경로는 `.py` 모듈로 구성한다. `.ipynb`는 실험 진행과 결과 시각화에만 사용한다.

## 2. 모델별 역할

- **VideoMAE**: 사전학습 가중치를 400개 라벨 데이터로 파인튜닝한 4종 사고 유형 자동 분류기
- **YOLO**: 객체 위치와 주요 프레임 근거 생성. 사고 유형을 직접 확정하지 않음
- **Qwen2.5-VL / LLaVA-OneVision**: 동일 프레임과 프롬프트를 이용한 제로샷 상황 설명·보조 분류 비교

Qwen과 LLaVA는 현재 파인튜닝 대상이 아니다. 서비스 사용자가 텍스트를 입력하지 않아도 Vision 모듈이 내부 고정 프롬프트를 생성한다.

## 3. 현재 상태

### 완료

- 카테고리별 100개, 총 400개 데이터 고정
- 카테고리별 YOLO 비교 및 모델 선정
- 전처리 프레임과 YOLO 결과 저장·재사용 구조 확보
- VideoMAE 4-class 파인튜닝 3개 실험 수행

| 실험 | 방식 | 최고 validation accuracy |
|---|---|---:|
| exp1 | backbone 고정 | 55.00% |
| exp2 | 전체 파인튜닝 5 epoch | 53.75% |
| exp3 | 전체 파인튜닝 + 조기 종료 | 56.25% |

현재 기록상 exp3가 가장 좋지만 56.25%는 validation 결과다. 고정 test set 평가 전에는 운영 모델로 확정하지 않는다.

### 진행 중

- RunPod에서 Qwen 누락 결과 보완
- 기존 유효 결과는 재사용하고 미완료 asset만 처리
- `car_vs_car` 완료 후 기존 VideoMAE split manifest와 exp3 체크포인트 검증 예정

### 미완료

- 기존 train/validation/test split 확보 및 영상 단위 누수 검사
- exp3 고정 test set 최종 평가
- LLaVA 동일 조건 비교
- VideoMAE 분류 결과 기반 YOLO 자동 라우팅 검증
- 라벨 없는 새 영상 end-to-end 테스트
- 최종 Vision JSON 및 실행 명령 전달

## 4. 고정 평가 조건

기존 학습 split이 있으면 반드시 재사용한다. 기존 split을 찾지 못한 상태에서 새 랜덤 split을 만들지 않는다.

권장 구조는 카테고리별 `train 70 / validation 15 / test 15`지만, 기존 실험 재현성이 우선이다. 동일 원본 영상이나 파생 프레임이 서로 다른 split에 포함되지 않도록 `asset_id` 또는 원본 사고 단위로 검사한다.

최종 비교 지표는 다음으로 고정한다.

- Accuracy
- Macro F1
- 카테고리별 Precision / Recall
- Confusion Matrix
- JSON 파싱 성공률
- 영상당 처리시간
- 실패 및 `unknown` 비율
- 오분류 영상 목록

## 5. 순차 실행 계획

1. **Qwen `car_vs_car` 100건 완료 확인**
   - 결과 100건, asset 중복, JSON 유효성 검증
2. **기존 학습 자산 검증**
   - VideoMAE split manifest, exp3 체크포인트, class mapping 확인
3. **데이터 누수 검사**
   - 원본 영상·asset 단위 train/validation/test 중복 확인
4. **VideoMAE test 평가**
   - 고정 test set으로 정량 지표와 오분류 목록 생성
5. **Qwen 결과 완성 및 LLaVA 최소 비교**
   - 먼저 동일 test set에서 비교하고 필요할 때만 전체 400개로 확대
6. **최종 VLM 선정**
   - 정확도뿐 아니라 JSON 안정성·처리시간을 함께 비교
7. **Vision Python 파이프라인 통합**
   - 전처리 → VideoMAE → YOLO 라우팅 → VLM → Vision JSON
8. **새 영상 통합 테스트**
   - 학습에 포함되지 않은 영상 1~5개로 자동 분류와 실패 처리를 검증
9. **Supervisor 담당자 전달**
   - Vision 출력 schema, 샘플 JSON, 실행 명령만 전달

## 6. 고도화 원칙

- 완료된 전처리·YOLO·VLM 결과를 재사용한다.
- 모델 비교를 위해 전처리와 YOLO를 반복 실행하지 않는다.
- VideoMAE confidence가 기준보다 낮으면 확정 분류 대신 `unknown`으로 반환한다.
- 객체 미검출과 VLM JSON 실패를 별도 `failure_reason`으로 기록한다.
- Vision은 사고 유형·객체·상황·confidence·limitations를 제공하고 과실비율을 확정하지 않는다.
- Supervisor 관련 코드는 Vision 담당 범위에서 수정하지 않는다.

## 7. 완료 기준

- 4개 카테고리 데이터와 평가 split이 고정됨
- VideoMAE test 지표와 오분류 결과가 문서화됨
- Qwen/LLaVA 중 사용할 VLM의 선정 근거가 있음
- 새 영상에서 사고 유형에 맞는 YOLO가 자동 선택됨
- Vision Python 진입점이 결과 JSON을 생성함
- 실패·낮은 confidence가 확정 결과로 위장되지 않음
- Supervisor 담당자에게 schema·샘플·실행 방법이 전달됨
