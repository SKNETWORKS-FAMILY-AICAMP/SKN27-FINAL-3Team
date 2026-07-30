# Vision Agent 프로젝트 현황 및 후속 작업 보고서

- 최초 작성일: 2026-07-23
- 현행화 기준일: 2026-07-24
- 대상 저장소: `D:\dev\SKN27-FINAL-3Team`
- 범위: 데이터·VideoMAE·YOLO·Qwen·Vision handoff·RunPod GPU 실행
- 제외: Supervisor 내부 병합 로직과 최종 UI/UX 구현

## 1. 현재 방향

Vision Agent의 역할은 다음으로 고정한다.

```text
사용자 영상
→ VideoMAE 사고유형 분류
→ 카테고리별 YOLO 객체 탐지
→ Qwen 32프레임 장면 설명과 불확실성 보완
→ partial/requires_review 판정
→ Vision handoff JSON
→ Supervisor
```

- 최종 사고유형 분류는 VideoMAE가 담당한다.
- Qwen은 사고유형 최종 분류기가 아니라 장면·객체 관계·충돌 가시성·불확실성 설명을 담당한다.
- YOLO는 VideoMAE 카테고리에 따라 선택한다.
- VLM 실패 시 VideoMAE·YOLO 결과가 있으면 `partial`로 전환한다.
- 운영 GPU 연결은 Supervisor 연결 담당자가 구현한다.
- 일반 GPU Pod/Jupyter는 학습·평가·배포 준비용으로만 사용한다.
- Vision 팀은 검증된 모델 산출물·실행 명세·handoff 계약까지 제공한다.

## 2. 주요 방향 변경

| 이전 계획 | 현재 결정 |
|---|---|
| Qwen/LLaVA 각 400건 비교 | 1차 배포 전에는 Qwen 1,200건만 완료 |
| 카테고리별 100건 | 중복 제거 후 카테고리별 300건, 총 1,200건 |
| Qwen 완료 후 LLaVA 실행 | LLaVA는 1차 배포 범위에서 제외 |
| 400건 VideoMAE exp4 중심 | 1,200건, 32프레임 VideoMAE 재학습 결과 사용 |
| GPU API 방식 미정 | 연결 방식의 설계 참고문서는 작성했으며 실제 GPU 연결은 Supervisor 담당자가 진행 |
| 400건 결과부터 완결 후 확장 | 일정상 1,200건 확장을 우선 완료하고 품질 의심점은 1차 배포 후 추가 개선 |

분석 원칙은 변경하지 않는다.

- 영상당 32프레임을 사용한다.
- Qwen 결과는 JSON schema와 필수 필드를 통과해야 완료로 센다.
- 출력 자연어는 한국어 또는 영어만 허용한다.
- 처리 성공 여부와 무관하게 자산별 결과를 보존한다.
- 실패 건만 retry queue에서 재실행한다.
- 진행률은 단순 CSV 행 수가 아니라 고유 `asset_id`의 schema·frame·language-valid 결과 수로 계산한다.

## 3. 완료된 사항

### 3.1 데이터와 manifest

- [x] 기존 카테고리별 100건, 총 400건 benchmark 구성
- [x] 400건 manifest의 `incident_id`, `viewpoint`, `lighting`, `visible_target` 보강
- [x] 파생 incident 기준 split 교차 검사
- [x] 중복을 제외한 카테고리별 300건, 총 1,200건 확보
- [x] 1,200건 전처리
- [x] 1,200건 split 생성

1,200건 split:

| split | 카테고리별 | 전체 |
|---|---:|---:|
| train | 210 | 840 |
| validation | 45 | 180 |
| test | 45 | 180 |
| 합계 | 300 | 1,200 |

주의:

- 현재 `incident_id`는 파생 값이다.
- 공식 AIHub 사고 ID와 대조되기 전까지 사고 단위 무결성은 “파생 ID 기준 검증 완료”로 표현한다.
- 공식 ID를 확보하면 group split과 near-duplicate 검사를 다시 수행해야 한다.

### 3.2 VideoMAE

- [x] 32프레임 입력
- [x] 1,200건 기준 학습·validation·test 완료
- [x] train/validation/test를 각각 840/180/180으로 분리
- [x] 3 epoch 학습 완료
- [x] final test 180건 평가 완료

#### 신규 1,200건 실행 결과

확인된 RunPod 최종 로그:

```text
best_epoch=3
test_loss=0.944394
test_acc=0.644444
```

`90/90`은 test 영상 수가 아니라 배치 진행 수다. 최종 test 표본은 180건이다.

현재 확정할 수 있는 값:

| 항목 | 값 |
|---|---:|
| 전체 데이터 | 1,200건 |
| train | 840건 |
| validation | 180건 |
| test | 180건 |
| 카테고리별 test | 45건 |
| 입력 프레임 | 영상당 32프레임 |
| epoch | 3 |
| best epoch | 3 |
| final test loss | 0.944394 |
| final test accuracy | 64.44% |

동기화된 운영 후보 artifact:

```text
storage/vision/models/videomae_raw_video/per_label_300_32frames/
videomae_cls_20260724_002551/
```

| 파일 | 상태 |
|---|---|
| `model.safetensors` | 344,943,488 bytes |
| `config.json` | 동기화 완료 |
| `preprocessor_config.json` | 동기화 완료 |
| `class_mapping.json` | 동기화 완료 |
| `run_config.json` | 동기화 완료 |
| `training_history.csv` | 동기화 완료 |

`model.safetensors` SHA-256:

```text
F2C453B9B93F206338FFB5DF9F213F196AA9F85AC2C5FCCA22CE4FC689DDCFF1
```

현재 로그만으로는 카테고리별 precision·recall·F1, Macro F1, confusion
matrix, confidence 분포를 확정할 수 없다. 해당 산출물을 RunPod에서 로컬로
동기화하기 전까지 64.44%를 운영 모델의 최종 성능으로 단정하지 않는다.

#### 기존 400건 exp4 재평가

기존 exp4는 카테고리별 100건, 총 400건으로 학습했고 고정 test 60건
(카테고리별 15건)을 32프레임으로 독립 재평가했다.

| 지표 | exp4 호환 전처리 재평가 | exp4 로컬 독립 재평가 |
|---|---:|---:|
| test 표본 | 60 | 60 |
| Accuracy | 66.67% | 58.33% |
| Macro F1 | 66.94% | 58.14% |
| loss | 0.881466 | 1.030881 |
| confidence 0.5 미만 | 18.33% | 53.33% |

호환 전처리 재평가의 카테고리별 결과:

| 카테고리 | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| 차대자전거 | 77.78% | 46.67% | 58.33% | 15 |
| 차대차 | 75.00% | 80.00% | 77.42% | 15 |
| 차대이륜차 | 48.00% | 80.00% | 60.00% | 15 |
| 차대보행자 | 90.00% | 60.00% | 72.00% | 15 |

호환 전처리 confusion matrix:

| 실제＼예측 | 자전거 | 차 | 이륜차 | 보행자 |
|---|---:|---:|---:|---:|
| 자전거 | 7 | 0 | 8 | 0 |
| 차 | 0 | 12 | 2 | 1 |
| 이륜차 | 2 | 1 | 12 | 0 |
| 보행자 | 0 | 3 | 3 | 9 |

핵심 취약점:

- 차대자전거 15건 중 8건을 차대이륜차로 분류해 recall이 46.67%다.
- 차대이륜차 recall은 80%지만 precision은 48%다. 자전거와 보행자를
  이륜차로 잘못 확정하는 위험이 있다.
- 차대보행자 15건 중 3건은 차, 3건은 이륜차로 분류됐다.
- 전처리 경로만 달라져 accuracy가 8.34%p, low-confidence rate가
  35.00%p 달라졌다. 모델 비교 시 checkpoint뿐 아니라 resize·normalize·
  frame sampling을 함께 고정해야 한다.

#### 기존 exp4와 신규 1,200건 비교

| 항목 | 기존 exp4 | 신규 1,200건 |
|---|---:|---:|
| 전체 데이터 | 400 | 1,200 |
| split | 280/60/60 | 840/180/180 |
| 카테고리별 test | 15 | 45 |
| 입력 프레임 | 32 | 32 |
| best 확인 Accuracy | 66.67% | 64.44% |
| Macro F1 | 66.94% | 동기화 필요 |
| 카테고리별 지표 | 확보 | 동기화 필요 |
| confusion matrix | 확보 | 동기화 필요 |

신규 accuracy는 기존 호환 재평가보다 2.22%p 낮고 로컬 독립 재평가보다
6.11%p 높다. 그러나 학습 데이터와 test 자산이 모두 달라졌으므로 이 차이를
“데이터 확장으로 성능이 하락/상승했다”라고 해석할 수 없다. 공정한 비교를
위해서는 두 checkpoint를 동일한 고정 holdout과 동일 전처리로 다시 평가해야
한다.

현재 판단:

- 1,200건 학습 파이프라인과 최종 test 실행은 정상 종료됐다.
- 64.44%는 무작위 4분류 기준 25%보다 높지만 자동 확정 서비스에 충분하다는
  근거는 아니다.
- 기존 exp4에서 드러난 자전거↔이륜차 혼동이 신규 모델에서 개선됐는지는
  아직 확인할 수 없다.
- 1차 배포에서는 confidence가 낮거나 자전거·이륜차 경계에 걸린 사례를
  `requires_review`로 보내는 보수적 정책이 필요하다.

운영 판단 전에 필요한 사항:

- 운영 confidence threshold
- 카테고리별 precision·recall·F1 최종 표
- 차대자전거 recall 방어 기준
- 차대이륜차 false positive 방어 기준
- checkpoint와 설정 hash 동결
- 신규 1,200건 `test_predictions.csv`
- 신규 1,200건 `confusion_matrix.csv`
- 신규 1,200건 `test_metrics.json`
- 동일 holdout에서 exp4와 신규 checkpoint의 paired 재평가

### 3.3 Vision 실행 코드와 JSON

- [x] Vision Python 진입점
- [x] VideoMAE·YOLO·Qwen 실행 경로
- [x] 카테고리별 YOLO 선택
- [x] JSON 복구·엄격 파싱·schema 검증
- [x] 파싱 실패 결과 보존
- [x] `schema_valid=false` 기록
- [x] `partial` fallback
- [x] `requires_review`
- [x] 자산별 resume
- [x] 성공·실패 처리 자산 구분
- [x] 실패 건 retry 기반 재처리
- [x] 로컬 smoke test

Qwen JSON 완료 조건:

1. 고유 `asset_id`
2. 입력 프레임 수 32
3. JSON 파싱 성공
4. 필수 schema 통과
5. 필수 필드 완결
6. 자연어가 한국어 또는 영어

### 3.4 GPU 연결 참고 설계

- [x] RunPod Queue-based Serverless 참고 설계 작성
- [x] `/run` 작업 생성 방식 정의
- [x] `/status/{job_id}` polling 방식 정의
- [x] signed HTTPS URL을 통한 영상 전달 방식 정의
- [x] API key와 endpoint ID 환경변수 계약 정의
- [x] timeout·partial·failed 상태 매핑 설계
- [x] 로컬 subprocess와 remote provider 경계 설계

설계 문서:

`docs/superpowers/specs/2026-07-23-runpod-serverless-vision-design.md`

이 문서는 Supervisor 연결 담당자가 참고할 설계 자료다. Endpoint 생성,
컨테이너 배포, remote adapter, polling과 실제 GPU API E2E는 Vision 팀의
현재 작업 범위에서 제외한다.

## 4. 현재 진행 중인 사항

### 4.1 RunPod Qwen 32프레임 1,200건 평가

- 대상: `car_vs_car`, `car_vs_pedestrian`, `car_vs_motorcycle`, `car_vs_bicycle` 각 300건
- 전체: 1,200건
- 입력: 영상당 32프레임
- 모델: Qwen만 실행
- LLaVA: 실행하지 않음
- 완료 기준: 고유 `asset_id` + schema valid + 32프레임 + 한국어/영어
- resume: 기존 유효 결과 보존 후 미완료 건만 처리

2026-07-24 실행 점검:

```text
schema/language-valid: 29/1200
manifest rows: 300/category
resolved source videos: 100/300 for car_vs_car
runner: stopped before inference
```

manifest에는 카테고리별 300건이 있지만 신규 자산 200건의 `local_path`가
현재 존재하지 않는 원본 영상 경로를 가리킨다. 전처리된 `frames32`는 남아
있지만 기존 Qwen 노트북은 원본 영상에서 YOLO 정보를 생성하므로 그대로
실행할 수 없다. 29건의 기존 유효 결과는 보존됐고 신규 추론은 시작하지 않았다.

재개 전에는 다음 중 하나를 확정해야 한다.

1. 신규 800개 원본 영상을 manifest와 일치하는 경로로 복원한다.
2. 기존 `frames32`를 Qwen·YOLO 입력으로 사용하는 동일 조건 실행 경로를
   검증한다.

진행 상태 확인:

```bash
watch -n 10 '
echo "=== PROCESS ==="
ps -p "$(cat /workspace/qwen1200.pid 2>/dev/null)" \
  -o pid,stat,etime,%cpu,%mem,cmd
pgrep -af "nbconvert.*vlm32_qwen"
echo
echo "=== GPU ==="
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
echo
echo "=== LATEST LOG ==="
tail -n 8 /workspace/qwen1200.log
echo
python /workspace/watch_qwen_schema_valid.py
'
```

최근 장애와 조치:

- RunPod 실행 파일이 manifest의 실제 `category`가 아니라 `coarse_label`을 조회했다.
- 대상 영상을 0건으로 인식해 Qwen 추론 전에 종료됐다.
- 조건을 `row.get('category') == CATEGORY_KEY`로 수정했다.
- `qwen --check`에서 네 카테고리가 모두 통과했다.
- `file_exists` 문자열 대신 실제 `Path.is_file()`로 입력 존재 여부를 검증하게
  수정했다.
- 이 검증에서 `car_vs_car` 원본 영상은 100/300만 확인돼 재차 안전 종료됐다.
- 기존 schema/language-valid 29건은 보존했다.

`MissingIDFieldWarning`은 nbformat 향후 호환성 경고이며 현재 실행 실패 원인은 아니다.

## 5. 1차 배포 전 앞으로 진행할 사항

### P0. Qwen 1,200건 완결성과 검수

- [ ] Qwen schema/frame/language-valid 1,200/1,200 확보
- [ ] invalid·timeout·OOM·language-invalid 목록 분리
- [ ] 실패 건만 재실행
- [ ] 중국어·일본어·깨진 문자 결과가 없는지 최종 검사
- [ ] JSON 필수 필드 완결률 계산
- [ ] 카테고리별 처리시간과 전체 GPU 실행시간 기록
- [ ] 대표 정상·partial·실패 결과 수기 검수
- [ ] 결과 CSV·설정·로그를 로컬 저장소 경로로 동기화
- [ ] 파일 수·행 수·SHA-256 비교

동기화 대상 로컬 경로는 오직 다음이다.

```text
D:\dev\SKN27-FINAL-3Team
```

`C:\Users\pc\Documents\최종 프로젝트`에는 RunPod 산출물을 저장하지 않는다.

### P1. VideoMAE 운영 기준 확정

- [ ] 1,200건 test prediction과 confusion matrix 확보
- [ ] accuracy·Macro F1·카테고리별 precision/recall/F1 계산
- [ ] validation에서 confidence threshold 결정
- [ ] threshold별 coverage·review rate·retained accuracy 계산
- [ ] 차대자전거 low-confidence 또는 혼동 사례의 강제 review 기준 확정
- [ ] 차대이륜차 false positive의 강제 review 기준 확정
- [ ] test set은 threshold 선택에 사용하지 않고 최종 1회 평가
- [ ] 운영 checkpoint·class mapping·32프레임 전처리 설정 동결
- [ ] checkpoint와 설정 SHA-256 기록

### P2. Vision handoff 계약 동결

- [ ] Vision input schema 확정
- [ ] Vision handoff output schema version 확정
- [ ] 정상 fixture
- [ ] `partial` fixture
- [ ] `failed` fixture
- [ ] stable error code 목록
- [ ] `requires_review` reason code
- [ ] timeout·retry 책임 경계
- [ ] 로컬 경로·민감정보 비노출 검사
- [ ] Supervisor 담당자에게 schema·fixture·호출 예제 전달

### P3. GPU 연결 담당자에게 전달할 Vision 패키지

- [ ] 운영 VideoMAE checkpoint·class mapping·전처리 설정 전달
- [ ] Qwen 모델·32프레임·프롬프트·JSON schema 실행 명세 전달
- [ ] 영상 입력과 Vision handoff 출력 예제 전달
- [ ] 정상·`partial`·`failed` fixture 전달
- [ ] Vision 실행 명령과 필수 환경 요구사항 전달
- [ ] 모델 artifact hash와 버전 전달
- [ ] Vision 내부 timeout과 오류 의미 전달

GPU Endpoint 생성, worker container, API secret, remote adapter,
polling/callback, 업로드 연결 및 최종 E2E는 Supervisor 연결 담당자가 수행한다.

## 6. 1차 배포 후 품질 개선 사항

일정 단축을 위해 아래 항목은 폐기하지 않고 1차 배포 후 수행한다.

### 6.1 VLM 비교 실험

- [ ] 기존 Qwen 4프레임과 Qwen 32프레임 paired 비교
- [ ] 필요할 경우 LLaVA 32프레임을 같은 자산·전처리·프롬프트로 별도 실행
- [ ] JSON valid rate
- [ ] 필수 필드 완결률
- [ ] 객체 관계 설명 reviewer 일치율
- [ ] 충돌 시점 가시성 판단률
- [ ] uncertainty 표현률
- [ ] 처리시간·GPU 비용
- [ ] `partial`·`requires_review` 전환율
- [ ] 모델별 실패 사례와 대표 샘플

LLaVA는 현재 1차 배포 차단 조건이 아니다.

### 6.2 benchmark 무결성 강화

- [ ] 파생 `incident_id`와 공식 AIHub 사고 ID 대조
- [ ] 공식 ID 확보 시 group split 재생성
- [ ] 영상 hash와 유사도 기반 near-duplicate 검사
- [ ] hard example과 오분류 원인 수기 검수
- [ ] `label_source`, `review_status`, `hard_example`, `hard_reason` 추가
- [ ] benchmark manifest와 SHA-256 버전 동결

### 6.3 성능 개선

- [ ] VideoMAE 오분류 원인 분석
- [ ] 카테고리별 class imbalance·영상 품질 영향 분석
- [ ] 프레임 선택 방식 비교
- [ ] Qwen 언어·schema 실패 패턴 분석
- [ ] review threshold 운영 데이터 기반 재조정

## 7. Supervisor 연결 전 최종 체크리스트

### 데이터·모델

- [x] 중복을 제외한 카테고리별 300건, 총 1,200건 구성
- [x] 1,200건 전처리
- [x] 840/180/180 split
- [x] VideoMAE 32프레임 학습·validation·test 실행
- [ ] VideoMAE 최종 지표표와 confusion matrix 검수
- [ ] VideoMAE 운영 threshold 확정
- [ ] 운영 checkpoint와 hash 동결
- [ ] Qwen 32프레임 schema/language-valid 1,200건 완료
- [ ] Qwen 결과 언어·JSON·대표 샘플 검수

### 코드·계약

- [x] Vision Python 진입점
- [x] VideoMAE·YOLO·Qwen 실행 경로
- [x] JSON 엄격 파싱과 schema 검증
- [x] 실패 결과 보존과 retry
- [x] `partial` fallback
- [x] `requires_review`
- [x] GPU 연결 참고 설계
- [ ] handoff schema version 동결
- [ ] stable error code 동결
- [ ] 정상·partial·failed fixture
- [ ] contract test

### 실행·운영

- [x] 로컬 smoke
- [x] RunPod 일반 GPU Pod에서 VideoMAE 1,200건 실행
- [ ] RunPod Qwen 1,200건 평가 완료
- [ ] RunPod 결과 로컬 동기화와 hash 검증
- [ ] 운영 artifact 동결

### 통합·인계

- [ ] Supervisor 담당자에게 schema와 fixture 전달
- [ ] 모델·전처리·실행 명세와 artifact hash 전달

다음 항목은 Supervisor 연결 담당자 범위이며 Vision 완료 체크리스트에서 제외한다.

- Supervisor의 Vision payload 수신과 검증
- GPU Endpoint·worker·remote adapter 구현
- attachment·job·execution ID 연결
- polling/callback과 timeout·retry·idempotency
- 타 Agent 결과 병합
- 최종 UX의 confidence·review 상태 표시
- 영상 업로드→GPU 분석→Supervisor→UX E2E

## 8. Supervisor 담당자와의 책임 경계

Vision 담당자가 제공:

- request/response/error schema
- VideoMAE·YOLO·Qwen 실행
- 정상·partial·failed handoff fixture
- stable error와 review reason code
- 모델·설정·hash
- 로컬 및 RunPod Pod 실행 근거
- GPU 연결 참고 설계

Supervisor 담당자가 구현:

- RunPod Endpoint와 worker container
- GPU API secret과 배포 설정
- remote Vision adapter
- Vision job 호출
- `/status/{job_id}` polling 또는 callback 처리
- timeout·retry·idempotency
- attachment·job·execution ID 연결
- Vision handoff와 다른 Agent 결과 병합
- 최종 사용자 답변과 guardrail
- UX의 진행·실패·review·완료 상태 표시

Vision 담당자는 GPU 연결, Supervisor 내부 병합 로직이나 최종 UI/UX를
직접 구현하지 않는다.

## 9. 1차 배포 가능 조건

다음 조건을 모두 만족하면 Supervisor 연결과 1차 서비스 배포 단계로 넘어갈 수 있다.

1. Qwen 1,200건 평가가 schema/frame/language-valid 기준으로 완료된다.
2. VideoMAE 운영 checkpoint와 validation 기반 review threshold가 확정된다.
3. Vision handoff schema·fixture·stable error code가 동결된다.
4. 모델·전처리·실행 명세와 artifact hash를 Supervisor 담당자에게 전달한다.

현재 Vision 측에는 Qwen 1,200건 완결, VideoMAE 운영 threshold, handoff
계약 동결과 인계 패키지 작성이 남아 있다. GPU 연결과 서비스 E2E 완료 여부는
Supervisor 연결 담당자가 별도로 관리한다.
