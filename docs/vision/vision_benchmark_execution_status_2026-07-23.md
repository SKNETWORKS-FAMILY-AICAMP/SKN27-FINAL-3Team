# Vision benchmark 실행 현황 및 판정 기준

- 기준일: 2026-07-23
- benchmark: 400건, 4개 사고유형 각 100건
- 원칙: 완료된 결과와 실행 중 결과를 구분하고, 검증 불가능한 상태를 성공으로 표시하지 않는다.

## 1. 현재 판정

| 항목 | 상태 | 판정 |
|---|---|---|
| 400건 메타데이터 | 완료 | 필수 4개 필드 누락 0건 |
| 사고 단위 split 무결성 | 완료 | 사고 그룹 397개, split 교차 0개 |
| readiness 의미 수정 | 완료 | 빈 `incident_id`는 `unverifiable`, 400건 완료 결과만 VLM ready |
| exp4 독립 재평가 | 완료 | 60/60 예측 label 및 전체 지표 재현 |
| Qwen 32프레임 400건 | RunPod 실행 중 | 기존 4건 결과를 resume하여 실제 notebook execute 시작 |
| LLaVA 32프레임 400건 | RunPod 실행 중 | Qwen과 같은 notebook/입력/프롬프트 조건으로 순차 실행 |
| GPU API 운영 연결 | 보류 | provider, endpoint, 인증, polling 계약 미확정 |
| UX 업로드→결과 | 부분 가능 | 로컬 subprocess 경로는 있으나 운영 GPU API 경로는 아직 없음 |

## 2. 400건 benchmark 확정

확정 manifest:

`storage/vision/manifests/videomae_labeled_fixed100_metadata.csv`

### 2.1 필수 메타데이터

| 필드 | 누락/unknown | 생성 근거 |
|---|---:|---|
| `incident_id` | 0 | AIHub 원천 파일명 끝 2개 토큰 |
| `viewpoint` | 0 | 파일명 capture code: `bb`, `cc` |
| `lighting` | 0 | 첫·중간·마지막 프레임의 조도 다수결 |
| `visible_target` | 0 | 고정 benchmark의 `coarse_label` |

분포:

- viewpoint: `blackbox_unspecified` 393건, `cctv_fixed` 7건
- lighting: day 148건, night 130건, low_light 122건
- visible_target: car/pedestrian/motorcycle/bicycle 각 100건
- split: train 280건, validation 60건, test 60건

### 2.2 사고 단위 무결성

`incident_id`는 `aihub_source_suffix:<마지막 두 토큰>` 형식이다. 이 규칙으로 397개 그룹이 만들어졌다.

- 1건 그룹: 394개
- 2건 그룹: 3개
- 3개 중복 그룹은 영상 SHA-256도 각각 동일했다.
- train/validation/test를 동시에 포함한 사고 그룹: 0개

따라서 현재 split은 재분할하지 않고 유지했다. 불필요한 재분할은 기존 실험과의 비교 가능성을 깨뜨리기 때문이다.

주의: 이 ID는 AIHub가 별도로 제공한 공식 사고 ID가 아니라, 현재 확보한 파일에서 검증 가능한 원천 클립 키다. 향후 공식 사고 ID를 받으면 이 열을 교체하고 같은 검사를 다시 수행해야 한다.

## 3. readiness 판정 규칙

이전 로직은 `incident_id`가 비어 있어 비교 그룹이 하나도 없어도 `incident_split_isolated=true`가 될 수 있었다. 이를 다음처럼 수정했다.

- `incident_id` 누락이 1건 이상이면 `incident_integrity=unverifiable`
- 사고 그룹이 여러 split에 있으면 `leak_detected`
- ID가 모두 있고 교차 그룹이 없을 때만 `verified_no_split_leak`
- `incident_split_isolated=true`는 마지막 상태에서만 허용
- Qwen/LLaVA 32프레임 ready는 각 모델 결과가 정확히 400건일 때만 허용

현재 readiness:

- `exp4_checkpoint=true`
- `fixed_split=true`
- `metadata_complete=true`
- `incident_split_isolated=true`
- `qwen_32_frame_results=false`
- `llava_32_frame_results=false`

마지막 두 값은 RunPod 실행이 400건을 채울 때까지 false가 정상이다.

## 4. exp4 독립 재평가

기존 RunPod 저장 결과:

- test 60건
- Accuracy 0.666667
- Macro F1 0.669382
- low-confidence rate 0.183333

로컬 기본 환경의 첫 독립 실행은 Accuracy 0.583333, Macro F1 0.581434로 달랐고 13/60개의 예측이 불일치했다. 이 실행에서는 `transformers 5.12.1`이 checkpoint의 attention bias 키 일부를 새로 초기화했다. 따라서 모델 성능 하락으로 해석하지 않고 환경 비호환 결과로 폐기한다.

정식 독립 재평가는 checkpoint를 변경하지 않고 `transformers 4.51.3`, `tokenizers 0.21.4`를 격리 적용해 완료했다.

- Accuracy 0.666667
- Macro F1 0.669382
- low-confidence rate 0.183333
- asset 순서 60/60 일치
- predicted label 60/60 일치
- 최대 class probability 차이 0.000835

합격 기준:

1. missing/unexpected checkpoint key가 없어야 한다.
2. test asset 60건의 순서와 정답이 원본 평가와 같아야 한다.
3. predicted label이 60/60 일치해야 한다.
4. 확률 차이는 부동소수점 허용오차 안이어야 한다.
5. Accuracy, Macro F1, 클래스별 precision/recall/F1이 재현되어야 한다.

모든 기준을 통과했으므로 기존 RunPod exp4 test 결과를 재현된 결과로 확정한다.

## 5. 32프레임 VLM 비교

기존 자동 실행기는 notebook을 실행하지 않고 변환만 수행해 성공으로 기록했다. 이것이 Qwen 결과가 `car_vs_car` 4건에서 멈춘 원인이었다.

RunPod에서는 실제 `jupyter nbconvert --execute`로 변경했다. GPU 메모리 충돌을 피하려고 다음 순서로 한 카테고리씩 실행한다.

1. car_vs_car
2. car_vs_pedestrian
3. car_vs_motorcycle
4. car_vs_bicycle

각 카테고리에서 Qwen과 LLaVA는 같은 100개 asset, 같은 32개 프레임, 같은 전처리 프레임, 같은 YOLO 정보, 같은 JSON 스키마, 같은 프롬프트 의미를 사용한다. Qwen의 한국어 설명이 JSON 안정성을 떨어뜨리면 설명 문자열만 영어로 전환하고 enum 값과 평가 스키마는 유지한다.

### 5.1 4프레임과 32프레임의 올바른 비교

32프레임 결과와 기존 4프레임 결과를 바로 “프레임 수 효과”라고 부르지 않는다. 아래 열이 모두 같을 때만 paired comparison으로 인정한다.

- 동일 `asset_id`
- 동일 모델과 모델 revision
- 동일 프롬프트
- 동일 YOLO 모델과 bbox 제공 방식
- 동일 resize/crop/lighting 전처리
- 동일 decoding 설정
- 다른 값은 입력 프레임 수뿐

현재 32프레임 실험은 Qwen 대 LLaVA 동일조건 비교를 먼저 완성한다. 기존 4프레임 실행과 위 조건이 다르면 별도 baseline으로 표시하고, 이후 4프레임을 같은 파이프라인으로 재실행해야 프레임 수 효과를 확정할 수 있다.

## 6. 서비스 위험 중심 평가 기준

### 6.1 VideoMAE

필수:

- Accuracy와 Macro F1
- 클래스별 precision, recall, F1
- confusion matrix
- confidence 구간별 정확도
- low-confidence/review 전환율
- 잘못된 자동 확정률

특히 확인:

- `car_vs_bicycle` recall
- `car_vs_motorcycle` precision
- 보행자·이륜차·자전거를 차량으로 오분류하는 비율

운영 판정은 “Accuracy가 가장 높은 모델”이 아니라 “위험한 자동 확정을 제한하면서 review 양이 감당 가능한 모델”로 한다.

### 6.2 Qwen/LLaVA

자동 산출:

- 전체/고유 asset 수
- JSON valid rate
- 필수 필드 완전성
- target accuracy 및 클래스별 precision/recall/F1
- `accident_visible`, `collision_moment_visible`, `accident_visibility=clear` 비율
- `uncertain` 사용률
- parse 실패와 partial 전환율
- 영상당 처리시간

사람 검토 표본:

- 객체 관계 설명의 사실성
- 충돌 전·순간·후 시간관계
- bbox가 설명에 실제로 도움이 됐는지
- 보이지 않는 사실을 단정하지 않는지
- 불확실성 사유가 구체적인지

VLM은 VideoMAE 사고유형을 임의로 덮어쓰지 않는다. 둘이 불일치하면 자동 수정이 아니라 `requires_review`로 전환한다.

## 7. Vision 팀 인계 범위

Supervisor 연결 담당자가 별도로 있으므로 Vision 작업의 완료 범위는 다음까지다.

Vision 담당:

1. scan-ready 영상 또는 접근 가능한 영상 URI 입력 계약
2. VideoMAE·YOLO·VLM 실행과 오류 격리
3. 사고유형, confidence, 객체/장면 설명, 불확실성 산출
4. `success`/`partial`/`failed`, `requires_review`, stable error code
5. Supervisor가 소비할 handoff JSON schema와 예제
6. GPU API request/response 계약 및 Vision adapter
7. 단위·계약·Vision E2E 테스트

Supervisor 담당자에게 인계:

1. handoff 수신과 노드 orchestration
2. 다른 에이전트 결과와 병합
3. 최종 사용자 응답 정책
4. Supervisor 자체 retry/routing
5. UX 결과 화면까지의 최종 연결

Vision 쪽에서는 Supervisor 내부 구현을 중복 개발하지 않는다. 대신 담당자가 바로 연결할 수 있도록 schema, status 의미, 샘플 payload, timeout/error 규칙을 확정해 제공한다.

## 8. GPU API와 UX 연결 가능 여부

여기까지의 benchmark 완료만으로 운영 UX가 완성되지는 않는다.

현재 가능한 경로:

`영상 업로드 → scan-ready attachment → 로컬 Worker subprocess → Vision handoff → Supervisor`

운영에 필요한 경로:

`영상 업로드 → object storage URI → GPU API job 생성 → 상태 polling/callback → 결과 schema 검증 → partial/review 처리 → Supervisor → UX 결과`

남은 필수 구현:

1. GPU API provider와 endpoint 확정
2. 인증 및 secret 보관 방식
3. 동기/비동기 job 계약과 timeout
4. request/response JSON schema
5. object storage 접근 방식
6. 재시도, idempotency, 실패/partial 매핑
7. Worker의 로컬 subprocess를 remote API adapter로 교체
8. 업로드 화면의 진행·실패·review·완료 상태 표시
9. 실제 GPU API를 포함한 E2E 테스트

결론적으로 benchmark와 모델 비교가 끝나면 “어떤 결과를 보여줄지”는 확정된다. 사용자가 UX에서 동영상을 넣고 운영 GPU 결과를 받으려면 위 GPU API adapter와 프론트 상태 연결이 추가로 필요하다. API 종류가 확정되기 전에는 특정 RunPod Serverless 또는 FastAPI 구현을 추측해 넣지 않는다.
