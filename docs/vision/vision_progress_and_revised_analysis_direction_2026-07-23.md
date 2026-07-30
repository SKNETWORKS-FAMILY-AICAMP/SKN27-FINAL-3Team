# Vision 프로젝트 진행 현황과 분석 방향 수정안

- 작성일: 2026-07-23
- 기준 문서: `docs/vision/vision_project_status_and_next_steps_2026-07-23.md`
- 기준 브랜치: `feat-accident-image-video-agent-result-flow`
- 분석 범위: 데이터, VideoMAE, YOLO, Qwen/LLaVA, Vision 실행 모듈, GPU 서버 API 경계, Supervisor handoff

## 1. 결론

Vision POC의 로컬 실행 코드와 기본 handoff 흐름은 구성됐고, RunPod의 exp4 32프레임 체크포인트·고정 split·평가 산출물도 로컬에 동기화됐다. exp4의 기록 성능은 test accuracy 66.67%, Macro F1 66.94%다.

그러나 현재 상태를 서비스 모델 완료로 판단하면 안 된다.

1. 400건 manifest의 `incident_id`, `viewpoint`, `lighting`, `visible_target`이 모두 미입력이다.
2. 따라서 동일 사고가 split을 넘었는지 실제로 검증할 수 없다.
3. Qwen 32프레임 결과는 `car_vs_car` 4건뿐이며 기존 4프레임 400건과 정량 비교할 수 없다.
4. LLaVA 동일 조건 결과는 없다.
5. GPU 추론 API의 provider, endpoint, 인증, 동기·비동기 계약이 미확정이다.
6. exp4 산출물은 RunPod 평가 결과를 동기화한 것이며 로컬 독립 재평가는 아직 수행하지 않았다.

다음 의사결정은 “데이터를 즉시 1,200건으로 늘릴 것인가”가 아니다. 먼저 400건 benchmark의 사고 단위 무결성과 메타데이터를 확정하고, exp4를 독립 재평가한 뒤, 32프레임 VLM 비교를 같은 조건으로 완성해야 한다.

## 2. 현재 확인된 자산

### 2.1 고정 split

경로:

```text
storage/vision/manifests/videomae_labeled_fixed100_split.csv
```

SHA-256:

```text
ce3de14071a0c10dad05a576b5805d7eedcdeeb6e4a5db3fcc33ba2d4cc428b1
```

구성:

| split | 카테고리별 | 전체 |
|---|---:|---:|
| train | 70 | 280 |
| validation | 15 | 60 |
| test | 15 | 60 |
| 합계 | 100 | 400 |

형식상 카테고리 균형은 맞지만 사고 단위 독립성은 아직 증명되지 않았다.

### 2.2 VideoMAE exp4

경로:

```text
storage/vision/models/videomae_raw_video/per_label_100_exp4_32frames_adaptive_labeled/videomae_cls_20260722_145601
```

주요 결과:

| 지표 | 값 |
|---|---:|
| test sample | 60 |
| Accuracy | 66.67% |
| Macro F1 | 66.94% |
| confidence 0.5 미만 | 18.33% |
| test loss | 0.881587 |

카테고리별:

| 카테고리 | Precision | Recall | F1 |
|---|---:|---:|---:|
| 차대자전거 | 77.78% | 46.67% | 58.33% |
| 차대차 | 75.00% | 80.00% | 77.42% |
| 차대이륜차 | 48.00% | 80.00% | 60.00% |
| 차대보행자 | 90.00% | 60.00% | 72.00% |

해석:

- 차대차는 비교적 안정적이다.
- 차대자전거 recall 46.67%는 실제 자전거 사고의 절반 이상을 놓칠 수 있음을 뜻한다.
- 차대이륜차 precision 48%는 이륜차 예측의 절반 이상이 오탐일 수 있음을 뜻한다.
- 차대보행자 20%가 차대차로 잘못 분류됐다.
- confidence 0.5 기준 review 대상이 18.33%이므로 자동화율과 오류율을 함께 평가해야 한다.

### 2.3 Qwen

기존 baseline:

- 4개 카테고리, 총 400건
- 입력 4프레임
- 기존 전체 사고유형 정확도 19.2%
- VLM을 최종 사고유형 분류기로 사용하기 어렵다는 근거

32프레임 결과:

```text
storage/vision/outputs/category_yolo_qwen_compare/car_vs_car/adaptive_preprocess_32frames/qwen_yolo_compare_results.csv
```

현재 4건이며 4건 모두 JSON valid다. 이는 실행 가능성 확인용 smoke sample이지 성능 비교 결과가 아니다.

### 2.4 코드와 검증

완료된 로컬 코드:

- 기본 frame count 32 통일
- best validation checkpoint 선택 후 test 1회 평가
- Accuracy, Macro F1, 카테고리별 Precision/Recall/F1 산출
- confusion matrix와 오분류 목록 산출
- 낮은 VideoMAE confidence의 `requires_review` 처리
- Qwen 실패 시 VideoMAE·YOLO 결과를 보존하는 partial handoff
- Qwen 예외 문자열과 로컬 절대 경로의 Supervisor 노출 방지
- CPU 환경에서 `--device auto` 처리
- 산출물 SHA-256, manifest, Qwen frame count readiness 감사

관련 Vision 회귀 테스트는 마지막 전체 실행에서 21개가 통과했다.

## 3. 기준 보고서 대비 진행 상태

| 우선순위 | 항목 | 상태 | 판단 |
|---|---|---|---|
| P0 | exp4·split·평가 산출물 동기화 | 완료 | RunPod에서 로컬로 동기화, SHA-256 기록 |
| P1 | exp4 고정 test 재평가 | 부분 완료 | RunPod 평가 파일 존재, 로컬 독립 재평가 필요 |
| P2 | 메타데이터 보강 | 미완료 | 4개 핵심 필드가 400건 모두 미입력 |
| P2 | 사고 단위 split 누수 검사 | 차단 | `incident_id`가 없어 검사 불가 |
| P3 | 균등 16 + 이벤트 16 프레임 비교 | 미완료 | 설계만 있고 정식 paired 실험 없음 |
| P4 | 카테고리별 300건 확장 | 보류 | 400건 benchmark 무결성 확정 후 진행 |
| P5 | Qwen/LLaVA 동일 조건 비교 | 미완료 | Qwen 32프레임 4건, LLaVA 결과 없음 |
| P6 | Vision Agent E2E | 부분 완료 | 로컬 exp3 smoke 완료, exp4·GPU API E2E 필요 |
| 병합 | `origin/dev` 반영 | 미완료 | 현재 브랜치가 dev보다 뒤처진 상태 |
| 병합 | commit·push·PR | 미완료 | 작업 트리에 미커밋 변경 존재 |

## 4. 기존 분석 방향의 장점

### 4.1 역할 분리가 올바르다

VideoMAE가 사고유형 4분류를 담당하고, YOLO가 객체와 충돌 후보를 찾고, VLM이 상황 설명과 불확실성을 보완하는 구조는 타당하다. 기존 Qwen 결과가 사고유형 분류에 취약하므로 역할을 분리하는 것이 맞다.

### 4.2 프레임 수를 명시적으로 관리한다

과거 4프레임 결과와 신규 32프레임 결과를 분리해 해석하려는 방향은 올바르다. 입력 조건이 다른 결과를 같은 표에서 직접 비교하면 안 된다.

### 4.3 불확실성을 handoff에 남긴다

`partial`, `requires_review`, stable error code를 사용하는 방향은 서비스 안전성과 Supervisor 통합에 필요하다. Vision이 판단하지 못한 값을 숨기지 않고 보류하는 것이 맞다.

## 5. 기존 분석 방향의 문제점

### 5.1 데이터 행 단위 split을 신뢰하고 있다

현재 split 비율과 카테고리 균형만으로는 평가 무결성을 보장할 수 없다. 동일 사고의 다른 영상이나 유사 클립이 train과 test에 나뉘면 실제 일반화보다 높은 점수가 나온다.

현재 readiness의 `incident_split_isolated=true`는 누수가 없다는 뜻이 아니다. `incident_id`가 전부 비어 있어 비교할 그룹이 없기 때문에 누수가 검출되지 않은 것이다. 이 상태는 `unverifiable`로 해석해야 한다.

### 5.2 32프레임 효과와 전처리 효과가 섞여 있다

4프레임 baseline과 32프레임 결과가 프레임 수뿐 아니라 전처리, 프롬프트, YOLO 정보, 실행 시점까지 다르면 개선 원인을 알 수 없다. 한 번에 하나의 변수만 바꾸는 paired comparison이 필요하다.

### 5.3 정확도 중심 판단이 서비스 위험을 가린다

4개 카테고리가 균형이므로 Accuracy가 무의미하지는 않지만, 차대자전거 recall과 차대이륜차 precision의 문제를 가린다. 서비스에서는 잘못된 자동 확정과 review 전환을 함께 평가해야 한다.

### 5.4 VLM 결과 평가 기준이 불완전하다

VLM을 사고유형 정답률로만 평가하면 역할 정의와 맞지 않는다. JSON 성공률, 객체 관계 설명, 충돌 시점 가시성, 불확실성 표현, 처리시간, partial 전환 품질이 필요하다.

### 5.5 로컬 실행과 운영 실행 경계가 섞여 있다

현재 Worker adapter는 로컬 subprocess와 로컬 checkpoint를 전제로 한다. 예정된 운영 구조는 GPU 서버 API이므로 로컬 smoke 성공을 운영 통합 성공으로 판단하면 안 된다.

## 6. 권장 수정 방향

### 6.1 모델 역할을 고정한다

```text
VideoMAE: 4개 사고유형의 1차 분류와 confidence
YOLO: 관련 객체, 객체 수, 위치 변화, 충돌 후보 구간
Qwen/LLaVA: 객체 관계, 상황 설명, 가시성, 불확실성
Supervisor: Vision 결과와 법률·사례 근거를 결합
```

VLM이 VideoMAE의 사고유형을 임의로 덮어쓰지 않게 한다. 불일치 시 자동 수정 대신 `requires_review` 사유로 남긴다.

### 6.2 benchmark와 개발 데이터를 분리한다

1. 현재 400건을 `benchmark_v1` 후보로 동결한다.
2. 원본 사고 ID를 확보해 `incident_id`를 입력한다.
3. 동일 사고 단위 group split을 다시 생성한다.
4. 새 split의 SHA-256과 생성 seed를 기록한다.
5. 향후 1,200건 확장 데이터는 development pool로 사용한다.
6. 최종 비교용 holdout은 학습과 threshold 조정에 사용하지 않는다.

원본 사고 ID를 확보할 수 없다면 파일명·출처·촬영 연속성 기반의 임시 그룹 규칙을 문서화하되, 그것을 실제 사고 ID와 동일하게 취급하지 않는다.

### 6.3 메타데이터 스키마를 먼저 확정한다

필수 필드:

| 필드 | 권장 값 |
|---|---|
| `incident_id` | 원본 사고 단위 stable ID |
| `viewpoint` | front, rear, side, intersection, unknown |
| `lighting` | day, night, tunnel, low_light, overexposed |
| `visible_target` | car, pedestrian, motorcycle, bicycle, multiple, unclear |
| `label_source` | source_label, reviewer, inferred |
| `review_status` | unreviewed, single_reviewed, double_reviewed |
| `hard_example` | true/false |
| `hard_reason` | occlusion, small_object, class_ambiguity, poor_lighting 등 |

`unknown`은 허용하되 누락과 구분한다. 수기 검수자는 최소한 hard example과 test set부터 우선 처리한다.

### 6.4 프레임 선택 실험을 분리한다

동일 영상·동일 모델·동일 프롬프트에서 다음 세 조건을 비교한다.

| 실험 | 구성 | 목적 |
|---|---|---|
| A | 균등 32 | 현재 기준선 |
| B | 균등 16 + 변화량 상위 16 | 시간 변화 활용 |
| C | 균등 16 + YOLO 충돌 후보 주변 16 | 객체 중심 사건 구간 활용 |

각 조건은 같은 400건에서 paired 결과를 만든다. crop-only 입력은 전체 맥락 손실 위험이 있으므로 전체 프레임과 함께 제공하는 별도 실험으로 둔다.

### 6.5 평가 지표를 확장한다

VideoMAE:

- Accuracy, Macro F1
- 카테고리별 Precision/Recall/F1
- confusion matrix
- confidence calibration 또는 ECE
- threshold별 coverage, review rate, retained accuracy
- 사고 단위 bootstrap confidence interval

VLM:

- JSON valid rate
- 필수 필드 완결률
- 사고 장면 가시성 판단
- 충돌 시점 가시성 판단
- 객체 관계 설명의 reviewer 일치율
- uncertainty 누락률
- partial rate
- 영상당 처리시간과 GPU 비용

E2E:

- 정상 handoff 비율
- partial handoff 비율
- stable error code 분포
- 로컬 경로·예외 문자열 노출 여부
- API timeout·재시도·중복 요청 처리

### 6.6 GPU API 경계를 명확히 한다

운영 경로:

```text
Worker
