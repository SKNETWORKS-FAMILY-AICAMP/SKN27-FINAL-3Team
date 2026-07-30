# RunPod Serverless Vision API 설계

- 작성일: 2026-07-23
- 대상: `SKN27-FINAL-3Team` Vision Agent
- 목적: 사용자 업로드 영상을 RunPod GPU에서 분석하고 Supervisor handoff JSON으로 반환

## 1. 결정

운영 추론은 기존 일반 Pod/Jupyter가 아니라 RunPod Queue-based Serverless Endpoint를 사용한다.

```text
UX 업로드
→ canonical scan gate
→ object storage의 짧은 수명 서명 URL
→ Worker가 RunPod /run 호출
→ job_id 저장
→ /status/{job_id} polling
→ Vision handoff JSON 검증
→ Supervisor
```

기존 로컬 subprocess는 테스트와 개발 fallback으로만 유지한다. Jupyter proxy를 운영 API로 사용하지 않는다.

## 2. 구성요소

### 2.1 애플리케이션 adapter

현재 `app/services/vision_media_analysis_adapter.py`의 입력 검증과 안전한 handoff 정제 로직은 유지한다. 실행부만 provider에 따라 선택한다.

- `VISION_RUNTIME_PROVIDER=local`: 기존 subprocess
- `VISION_RUNTIME_PROVIDER=runpod`: RunPod 비동기 API

RunPod 설정:

- `RUNPOD_API_KEY`: restricted API key
- `RUNPOD_VISION_ENDPOINT_ID`: 배포된 Endpoint ID
- `RUNPOD_VISION_TIMEOUT_SECONDS`: 전체 polling 제한
- `RUNPOD_VISION_POLL_INTERVAL_SECONDS`: polling 간격

API 키는 환경변수 또는 배포 secret에만 저장하며 로그·DB·payload에 기록하지 않는다.

### 2.2 RunPod worker

Serverless worker는 다음 순서로 처리한다.

1. 입력 schema 검증
2. HTTPS 서명 URL에서 영상 다운로드
3. 크기·content type·다운로드 timeout 검증
4. 임시 작업공간에 영상 저장
5. 기존 `ai.vision.run_to_supervisor` 실행
6. 생성된 handoff JSON 검증
7. 안전한 JSON 결과 반환
8. 임시 영상과 프레임 삭제

worker는 Supervisor를 호출하지 않는다. Vision 분석 결과만 반환한다.

### 2.3 모델 artifact

VideoMAE checkpoint와 Qwen/LLaVA 모델은 Serverless worker에서 접근 가능해야 한다.

초기 배포는 다음 우선순위를 사용한다.

1. RunPod Network Volume 또는 model cache
2. 컨테이너 시작 시 검증된 원격 저장소에서 다운로드
3. 대형 모델을 컨테이너 이미지에 직접 포함하는 방식은 이미지 크기와 cold start 때문에 사용하지 않음

Endpoint 생성 전 32프레임 비교 결과로 운영 VLM을 하나만 선정한다. Qwen과 LLaVA를 동시에 상주시켜 VRAM과 cold start를 늘리지 않는다.

## 3. API 계약

### 3.1 작업 생성

```http
POST https://api.runpod.ai/v2/{endpoint_id}/run
Authorization: Bearer {RUNPOD_API_KEY}
Content-Type: application/json
```

```json
{
  "input": {
    "schema_version": "vision-runpod-request-v1",
    "execution_id": "exec_...",
    "attachment_id": "att_...",
    "video_url": "https://signed-object-url",
    "content_type": "video/mp4"
  }
}
```

영상 바이너리와 API 키는 요청 JSON에 넣지 않는다.

### 3.2 상태 조회

```http
GET https://api.runpod.ai/v2/{endpoint_id}/status/{job_id}
Authorization: Bearer {RUNPOD_API_KEY}
```

애플리케이션 상태 매핑:

| RunPod | Vision |
|---|---|
| `IN_QUEUE`, `IN_PROGRESS` | running |
| `COMPLETED` | 결과 schema 검증 후 completed 또는 partial |
| `FAILED` | `vision_remote_execution_failed` |
| `CANCELLED` | `vision_remote_cancelled` |
| polling timeout | `vision_remote_timeout` |
| HTTP·인증 오류 | `vision_remote_unavailable` |
| invalid output | `vision_remote_invalid_response` |

### 3.3 결과

RunPod `output`에는 기존 `vision_supervisor_handoff` 객체를 반환한다. 애플리케이션은 기존 `_safe_worker_handoff()`를 다시 적용해 내부 경로와 진단정보를 제거한다.

## 4. 보안과 데이터 수명

- scan-ready 상태의 canonical blackbox video만 전송
- `s3://` URI 자체가 아니라 HTTPS 서명 URL만 worker에 전달
- 서명 URL 수명은 분석 대기와 실행 시간을 포함하되 가능한 짧게 설정
- worker는 URL host allowlist와 HTTPS를 검증
- 로그에 API 키, 서명 URL query, 로컬 경로를 남기지 않음
- 원본 영상과 추출 프레임은 job 종료 시 삭제
- RunPod 결과에는 영상 바이너리·서명 URL을 포함하지 않음
- 실제 사용자 영상 사용 전 RunPod Cloud 유형과 개인정보 처리 정책을 팀이 승인

## 5. 오류·재시도

- `/run` 호출은 네트워크 오류에만 제한적으로 재시도
- 동일 `execution_id`를 idempotency key로 사용해 중복 job 생성을 방지
- 상태 polling은 전체 timeout까지만 수행
- RunPod 내부 자동 재시도와 애플리케이션 재시도의 중복 범위를 문서화
- VLM 실패는 VideoMAE·YOLO 결과가 있으면 `partial`
- 전체 worker 실패는 stable error code와 빈 evidence로 반환
- 실패 시 법률·과실·최종 사고유형을 생성하지 않음

## 6. 비용과 배포

- 초기 Endpoint는 `workersMin=0`, `workersMax=1`
- GPU는 smoke에서 모델 VRAM을 만족하는 최소 등급으로 결정
- execution timeout은 단일 영상 최대 분석 시간에 맞춤
- cold start와 모델 다운로드 시간을 smoke 결과에 기록
- Endpoint·GPU·worker 설정 변경은 별도 기록
- Endpoint 생성은 과금 가능한 외부 변경이므로 구현·컨테이너 검증 후 수행

## 7. 테스트

### 로컬 contract test

- provider가 `local`일 때 기존 subprocess 유지
- provider가 `runpod`일 때 checkpoint 로컬 검사를 요구하지 않음
- `/run` 성공 후 `job_id`를 polling
- `COMPLETED`의 handoff 정제
- timeout·failed·cancelled·invalid response의 stable error code
- API 키와 서명 URL 비노출

### worker test

- request schema 검증
- HTTPS URL과 허용 host 검증
- 다운로드 크기·content type·timeout 제한
- handoff JSON 검증
- 임시 파일 삭제

### 실제 smoke

1. 비식별 테스트 영상 업로드
2. 서명 URL 생성
3. Serverless job 생성
4. GPU 추론 완료
5. handoff JSON 수신
6. Supervisor adapter 수신
7. 로그와 결과의 secret·경로 비노출 확인

## 8. 구현 순서

1. RunPod client contract test 작성
2. 표준 라이브러리 기반 최소 HTTP client 구현
3. 기존 adapter에 provider 분기 추가
4. worker handler와 Dockerfile 작성
5. 로컬 worker/adapter 테스트
6. 컨테이너 build와 smoke
7. registry push
8. RunPod restricted key 권한 확인
9. Serverless Endpoint 생성
10. 실제 영상 E2E

## 9. 완료 기준

- 로컬 provider 회귀 테스트 통과
- RunPod provider contract test 통과
- worker 컨테이너가 모델을 로드하고 영상 1건을 분석
- Endpoint가 `/run`과 `/status`로 결과 반환
- 결과가 기존 Supervisor handoff schema를 통과
- timeout·partial·failed 경로가 stable error code를 반환
- API 키·서명 URL·내부 경로가 사용자 payload와 로그에 노출되지 않음
