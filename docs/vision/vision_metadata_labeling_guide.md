# Vision 400건 메타데이터 라벨 기준

대상 파일: `storage/vision/manifests/qwen_adaptive_fixed100.csv`

## viewpoint

| 값 | 기준 |
|---|---|
| `ego_dashcam` | 사고 당사 차량 내부 블랙박스 |
| `third_party_dashcam` | 사고 당사자가 아닌 제3자 차량 블랙박스 |
| `third_party_cctv` | 도로·건물 등에 고정된 제3자 CCTV |
| `unknown` | 화면만으로 신뢰성 있게 확정할 수 없음 |

추정이 불확실하면 `unknown`을 유지한다.

## incident_id

- 동일 사고에서 생성된 영상과 파생본에는 같은 ID를 기록한다.
- 권장 형식은 `incident_<원본 식별자>`이다.
- 파일명, 원본 라벨 또는 제공 메타데이터로 동일 사고임을 확인할 수 없으면 비워 둔다.
- 학습·검증·테스트 분할은 영상이 아니라 `incident_id` 단위로 수행한다.

## lighting

`adaptive_preprocessing.py`의 프레임 판정 기준을 그대로 사용한다.

| 값 | 프레임 기준 |
|---|---|
| `night` | grayscale 평균 `< 45` |
| `low_light` | grayscale 평균 `< 85` |
| `overexposed` | 평균 `> 175`이고 95% 분위값 `>= 245` |
| `day` | 위 조건에 해당하지 않음 |
| `unknown` | 영상 확인 또는 계산 불가 |

영상 전체 값은 분석에 사용된 프레임의 다수 판정을 기록한다. 충돌 후보 프레임이 다른 조건이면 해당 프레임의 조건을 우선한다.

## 작업 순서

1. 자동 계산 가능한 `lighting`을 먼저 채운다.
2. 원본 메타데이터와 영상을 확인해 `viewpoint`를 채운다.
3. 동일 사고 묶음이 확인되는 경우에만 `incident_id`를 채운다.
4. `unknown`과 빈 `incident_id`는 임의 추정하지 않고 검토 대상으로 남긴다.

