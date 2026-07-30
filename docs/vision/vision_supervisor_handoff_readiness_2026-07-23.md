# Vision Agent 진행 현황 및 Supervisor 연결 전 체크리스트

- 기준일: 2026-07-23
- 대상 저장소: `SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team`
- 담당 범위: Vision 데이터, VideoMAE, YOLO, Qwen/LLaVA, Vision 실행 모듈, Supervisor handoff 계약
- 범위 제외: Supervisor 그래프 구현, 타 Agent 결과 병합, 최종 법률·과실 판단, UX 화면 구현

## 1. 현재 전체 방향

Vision Agent는 사고 유형을 단독으로 최종 확정하는 Agent가 아니다. 모델별 책임을 다음처럼 분리한다.

| 구성요소 | 책임 | 최종 출력에서의 역할 |
|---|---|---|
| VideoMAE | 사고 유형 4분류 | 1차 사고 유형과 confidence |
| YOLO | 차량·보행자·이륜차·자전거 등 객체 검출 | 객체 존재, 위치, 충돌 후보 구간 |
| Qwen/LLaVA | 프레임의 객체 관계와 사고 장면 설명 | 상황 설명, 충돌 시점 가시성, 불확실성 |
| Vision Agent | 세 모델의 실행과 오류 격리 | `success`·`partial`·`failed`, `requires_review`, stable error code |
| Supervisor | Vision과 법률·과실·과태료 Agent 결과 병합 | 사용자에게 전달할 최종 답변 |

핵심 원칙은 다음과 같다.

1. 동일 사고가 train·validation·test에 섞이지 않은 benchmark만 성능 근거로 사용한다.
2. 4프레임과 32프레임 비교에서는 프레임 수 외의 모델·프롬프트·전처리·평가 기준을 고정한다.
3. Accuracy만 보지 않고 카테고리별 Precision·Recall·F1, review rate, partial rate를 함께 본다.
4. VLM은 사고 유형 최종 분류기가 아니라 상황 설명 보조 모델로 사용한다.
5. 파싱되거나 스키마 검증을 통과하지 못한 VLM 결과는 완료 결과로 인정하지 않는다.
6. 로컬 subprocess 성공과 운영 GPU API 통합 성공을 구분한다.
7. Vision은 Supervisor가 바로 연결할 수 있는 계약과 fixture까지 제공하고, Supervisor 내부 구현은 담당자에게 인계한다.

## 2. 현재 상태 요약

| 영역 | 상태 | 현재 판단 |
|---|---|---|
| 400건 benchmark 원본 구성 | 완료 | 4개 카테고리 각 100건 |
| benchmark metadata | 완료(잠정 ID 주의) | 필수 4개 필드 400건 보강 |
| 사고 단위 split 검증 | 완료(잠정 근거) | 파생 incident group 397개, split 교차 0개 |
| exp4 독립 재평가 | 완료 | 고정 test 60건, Accuracy 66.67%, Macro F1 66.94% |
| 기존 Qwen 4프레임 분석 | 완료·baseline 보존 | 400건, JSON valid 351건, 사고유형 정확도 19.2% |
| VLM JSON 안정화 | 코드 완료 | 엄격 파싱·스키마 검증·재시도·유효 결과만 resume |
| Qwen 32프레임 400건 | 실행 중 | RunPod 순차 재평가 시작, 2026-07-23 11:35 기준 0/400 |
| LLaVA 32프레임 400건 | 대기 | 동일 실행 체인에서 Qwen 뒤에 순차 실행 |
| 4프레임 대 32프레임 paired 비교 | 미완료 | 32프레임 양 모델 결과 완료 후 산출 |
| Vision 로컬 handoff | 부분 완료 | 실제 영상으로 `partial` handoff smoke 성공 |
| GPU API adapter | 보류 | RunPod Serverless/FastAPI, endpoint, 인증, polling 계약 미확정 |
| Supervisor 연결 | Vision 준비 진행 중 | schema·fixture·오류 계약·GPU API 경계 확정 필요 |
| UX 영상 업로드→결과 | 미완료 | GPU API와 Supervisor 연결 후 가능 |

## 3. 완료된 사항

### 3.1 benchmark와 metadata

- [x] 4개 사고 유형 각각 100건, 총 400건 고정
- [x] train 280건·validation 60건·test 60건 구성
- [x] `incident_id`, `viewpoint`, `lighting`, `visible_target` 400건 보강
- [x] viewpoint 분포 기록: `blackbox_unspecified` 393건, `cctv_fixed` 7건
- [x] lighting 분포 기록: day 148건, night 130건, low_light 122건
- [x] visible target을 카테고리별 100건으로 확정
- [x] 파생 incident group 397개 생성
- [x] train·validation·test 사이 incident group 교차 0건 확인
- [x] readiness에서 빈 `incident_id`를 `isolated=true`로 처리하지 않고 `unverifiable`로 판정하도록 수정

주의: 현재 `incident_id`는 AIHub 원본이 제공한 공식 사고 ID가 아니라 파일명에서 검증 가능한 토큰을 이용한 파생 ID다. 공식 원본 사고 ID를 확보하면 교체 후 split 검증을 다시 수행해야 한다.

### 3.2 exp4 독립 재평가

- [x] RunPod의 고정 split과 exp4 checkpoint를 로컬로 동기화
- [x] 독립 평가 모듈로 test 60건을 다시 평가
- [x] Accuracy·Macro F1·카테고리별 Precision/Recall/F1 산출
- [x] confusion matrix와 오분류 목록 산출
- [x] confidence 0.5 미만을 `requires_review` 후보로 측정

주요 결과:

| 지표 | 결과 |
|---|---:|
| Accuracy | 66.67% |
| Macro F1 | 66.94% |
| confidence 0.5 미만 | 18.33% |
| 차대자전거 Recall | 46.67% |
| 차대이륜차 Precision | 48.00% |

현재 모델은 POC로는 사용 가능하지만 자동 확정 모델로 배포하기에는 취약 카테고리의 위험이 크다. 낮은 confidence 및 모델 간 불일치는 `requires_review`로 보내야 한다.

### 3.3 Vision 실행 경로

- [x] VideoMAE → 카테고리별 YOLO 선택 → VLM → handoff JSON 실행 모듈 구성
- [x] 입력 프레임 기본값 32로 통일
- [x] 낮은 VideoMAE confidence의 review 전환
- [x] VLM 실패 시 VideoMAE·YOLO 결과를 보존하는 `partial` 처리
- [x] 로컬 파일 경로가 사용자 결과에 노출되지 않도록 처리
- [x] CPU 환경의 `--device auto` fallback 확인
- [x] 실제 영상 1건으로 로컬 `partial` handoff smoke 성공

### 3.4 VLM JSON 파싱 안정화

기존 4프레임 Qwen 결과는 400건 중 49건이 JSON 파싱에 실패했다. 47건은 응답이 `max_new_tokens=256`에서 문자열·배열 중간에 잘렸고, 2건은 완전한 JSON 객체를 찾지 못했다.

- [x] 짧은 영어 JSON 전용 프롬프트 적용
- [x] 불필요한 bbox 반복 제거 및 객체 목록 제한
- [x] 출력 한도 256에서 512 tokens로 확대
- [x] 첫 출력 실패 시 compact JSON 재시도 1회
- [x] `json.JSONDecoder.raw_decode()`로 첫 완전한 객체 추출
- [x] 필수 필드·자료형·enum 엄격 검증
- [x] 스키마 invalid 결과는 완료로 간주하지 않고 다음 실행에서 재처리
- [x] Qwen과 LLaVA에 동일 규칙 적용
- [x] 관련 테스트 15개 통과

잘린 JSON을 추측해 채우는 복구는 사고 근거를 조작할 수 있어 사용하지 않는다.

## 4. 현재 진행 중인 사항

### 4.1 RunPod Qwen/LLaVA 32프레임 동일 조건 평가

- 대상: car, pedestrian, motorcycle, bicycle 각 100건
- 조건: 동일 영상, 동일 32프레임, 동일 전처리, 동일 JSON schema, 동일 평가 기준
- 순서: Qwen 4개 카테고리 완료 후 LLaVA 4개 카테고리
- 현재 상태: RunPod 실행 중
- 프로세스 PID: `388481`
- 2026-07-23 11:35 기준: Qwen 0/400, LLaVA 0/400

진행률 확인:

```bash
python /workspace/watch_vlm32.py
```

프로세스 확인:

```bash
ps -p 388481 -o pid,etime,stat,cmd
```

로그 확인:

```bash
tail -f /workspace/vlm32_jsonfix_car.log
tail -f /workspace/vlm32_jsonfix_master.log
```

완료 판정은 단순 CSV 행 수가 아니라 `json_valid=true`이고 필수 schema를 통과한 400건을 기준으로 해야 한다. 첫 pass 이후 invalid 건이 있으면 해당 건만 재실행한다.

## 5. 앞으로 진행할 사항

### P0. RunPod 결과 완결성과 동기화

- [ ] Qwen 32프레임 유효 결과 400/400 확보
- [ ] LLaVA 32프레임 유효 결과 400/400 확보
- [ ] invalid·timeout·OOM 건 목록 분리
- [ ] 실패 건만 재실행해 schema-valid 결과를 채움
- [ ] 결과 CSV·실행 설정·로그를 로컬로 동기화
- [ ] 파일 수·행 수·SHA-256 비교
- [ ] 기존 4프레임 baseline과 새 32프레임 결과를 별도 경로에 보존

### P1. 동일 조건 정량 비교

- [ ] Qwen 4프레임 대 Qwen 32프레임 paired 비교
- [ ] Qwen 32프레임 대 LLaVA 32프레임 paired 비교
- [ ] JSON valid rate
- [ ] 필수 필드 완결률
- [ ] 객체 관계 설명의 reviewer 일치율
- [ ] 충돌 시점 가시성 판단률
- [ ] uncertainty 표현률
- [ ] 처리시간·GPU 비용
- [ ] `partial`·`requires_review` 전환율
- [ ] 모델별 실패 사례와 대표 샘플 정리

VLM 사고유형 정답률은 참고 지표로만 유지한다. 최종 사고유형은 VideoMAE가 담당하고, VLM은 장면 설명과 불확실성 보완에 사용한다.

### P2. benchmark 품질 보강

- [ ] 파생 `incident_id`를 공식 AIHub 사고 ID와 대조
- [ ] 공식 ID 확보 시 group split 재생성
- [ ] 영상 유사도·중복 클립 탐지로 near-duplicate 누수 검사
- [ ] hard example과 오분류 원인 수기 검수
- [ ] metadata에 `label_source`, `review_status`, `hard_example`, `hard_reason` 추가
- [ ] benchmark v1 manifest와 SHA-256 동결

1,200건 확장은 위 작업이 끝난 뒤 진행한다. 무결성이 확정되지 않은 상태에서 데이터만 늘리면 잘못된 split과 label 문제도 함께 확대된다.

### P3. VideoMAE 서비스 판단 기준

- [ ] confidence threshold별 coverage·review rate·retained accuracy 계산
- [ ] 차대자전거 Recall 개선 또는 강제 review 기준 확정
- [ ] 차대이륜차 false positive 억제 또는 강제 review 기준 확정
- [ ] threshold를 test set에 맞추지 않고 validation에서 결정
- [ ] 고정 holdout에서 최종 1회 평가
- [ ] 운영 모델·class mapping·전처리 설정·checkpoint hash 동결

### P4. GPU API 계약

현재는 구현을 보류한다. RunPod Serverless Endpoint인지 별도 FastAPI GPU 서버인지 확정되지 않았기 때문이다.

- [ ] GPU API 방식 결정
- [ ] endpoint와 API version 확정
- [ ] 인증과 secret 저장 방식 확정
- [ ] object storage URI 전달 방식 확정
- [ ] 동기·비동기 job 생성 방식 확정
- [ ] polling 또는 callback 계약 확정
- [ ] timeout·retry·idempotency 규칙 확정
- [ ] request/response/error schema 확정
- [ ] 로컬 subprocess adapter와 remote API adapter의 경계 확정
- [ ] 실제 GPU API를 포함한 smoke test

### P5. Supervisor 인계 패키지

- [ ] Vision input schema 확정
- [ ] Vision handoff output schema version 확정
- [ ] 정상 fixture 작성
- [ ] `partial` fixture 작성
- [ ] `failed` fixture 작성
- [ ] stable error code 목록 확정
- [ ] `requires_review` 조건과 reason code 확정
- [ ] timeout과 재시도 책임 경계 문서화
- [ ] 로컬 경로·민감정보 비노출 테스트
- [ ] Supervisor 담당자와 contract test 1회
- [ ] 영상 업로드부터 Supervisor 수신까지 최소 E2E 1건

Supervisor 담당자가 구현할 범위:

- Vision job 호출과 상태 polling/callback
- attachment·job·execution ID 연결
- Vision handoff와 타 Agent 결과 병합
- 최종 사용자 답변과 guardrail
- UX의 진행·실패·review·완료 상태 표시

## 6. Supervisor 연결 전 최종 체크리스트

### 데이터·평가

- [x] 400건 benchmark 구성
- [x] metadata 필수 4개 필드 보강
- [x] 파생 incident 기준 split 교차 검사
- [ ] 공식 incident ID 검증 또는 파생 ID 한계 승인
- [x] exp4 독립 test 재평가
- [ ] Qwen 32프레임 400건 완료
- [ ] LLaVA 32프레임 400건 완료
- [ ] paired 비교 보고서 완료
- [ ] hard example 검수
- [ ] 서비스 threshold 확정

### 코드·계약

- [x] Vision Python 진입점
- [x] VideoMAE·YOLO·VLM 실행 경로
- [x] JSON 엄격 파싱과 schema 검증
- [x] `partial` fallback
- [x] `requires_review`
- [ ] handoff schema version 동결
- [ ] stable error code 동결
- [ ] 정상·partial·failed fixture
- [ ] remote GPU API adapter
- [ ] contract test

### 실행·운영

- [x] 로컬 smoke
- [ ] RunPod 400건×2 모델 평가 완료
- [ ] RunPod 결과 로컬 동기화와 hash 검증
- [ ] 실제 GPU API smoke
- [ ] timeout·retry·idempotency 검증
- [ ] 로그에서 파일 경로·secret 비노출 검증
- [ ] 운영 모델 artifact 동결

### 통합·인계

- [ ] Supervisor 담당자에게 schema와 fixture 전달
- [ ] Supervisor가 Vision payload를 수신·검증
- [ ] 타 Agent 병합 시 Vision 판단 책임이 섞이지 않음
- [ ] 최종 답변에서 Vision confidence·review 상태 표시
- [ ] 영상 업로드→GPU 분석→Supervisor→UX 최소 1건 E2E
- [ ] 실패·partial·timeout 각 1건 E2E

## 7. 현재 UX 연결 가능 여부

로컬 데모 수준에서는 영상 입력 후 Vision handoff JSON을 생성할 수 있다. 하지만 사용자가 UX에 영상을 업로드하고 운영 GPU에서 분석한 뒤 최종 결과를 받는 흐름은 아직 완료되지 않았다.

필요한 연결은 다음과 같다.

```text
UX 업로드
→ object storage URI
→ Worker/Supervisor의 Vision job 생성
→ GPU API
→ status polling/callback
→ schema 검증
→ partial/requires_review 처리
→ Supervisor 병합
→ UX 결과
```

따라서 현재 판단은 **Vision 로컬 실행 가능, Supervisor 연결 준비 중, 운영 UX E2E 미완료**다.

## 8. 완료 판단 기준

Vision 측 Supervisor 연결 준비 완료는 다음 조건을 모두 만족할 때 선언한다.

1. Qwen/LLaVA 동일 조건 평가가 schema-valid 400건씩 완료된다.
2. VideoMAE·VLM 선택과 review threshold가 문서화된다.
3. handoff schema, status, error code, fixture가 동결된다.
4. GPU API request/response와 job 상태 계약이 확정된다.
5. 실제 GPU API를 이용한 Vision smoke가 성공한다.
6. Supervisor 담당자와 contract test 및 최소 E2E 1건이 성공한다.

이후 UX 최종 연결과 타 Agent 병합은 Supervisor 담당자가 진행한다.
