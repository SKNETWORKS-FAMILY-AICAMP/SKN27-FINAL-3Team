# AI 교통분쟁 상담 v2 구현 설계

- 기준일: 2026-07-10
- 갱신일: 2026-07-12
- 상태: 계약 및 비활성 기본 구현
- 상위 로드맵: GitHub #178
- 관련 이슈: #170, #171, #172, #173, #174, #175, #176

## 1. 목표

상담 v2는 사용자의 문장에 고정 답변을 붙이는 기능이 아니다. 사건 단위로
입력, 파일, 확인된 사실, Vision 관찰 결과, 법령·판례·외부 근거, 분석 작업과
리포트를 연결하는 운영 계약이다.

핵심 처리 순서는 다음과 같다.

1. 사용자 입력과 첨부 파일을 Case에 연결한다.
2. 파일을 quarantine 영역에 저장하고 악성 파일 검사를 수행한다.
3. 개인정보가 제거된 프레임만 Vision 경계에 전달한다.
4. 사용자 진술과 OCR/Vision 관찰 결과를 사실 카드로 분리한다.
5. 외부 근거는 출처와 조회 시각을 보존한 `external_evidence.v1`로 변환한다.
6. 핵심 사실이 충분할 때만 잠정 과실 범위를 표시한다.
7. Agent 결과와 한계를 리포트에 함께 저장한다.

## 2. 점진적 활성화 원칙

다음 feature flag는 모두 기본값이 `0`이다.

| 환경변수 | 책임 | 활성화 조건 |
|---|---|---|
| `CASE_WORKSPACE_V2_ENABLED` | Case workspace API와 UI | migration·소유권·회귀 테스트 통과 |
| `VISION_PIPELINE_ENABLED` | 비식별 프레임 Vision 분석 | scan·redaction·strict schema 검증 통과 |
| `EVIDENCE_MCP_ENABLED` | 교통·경찰·법령 외부 근거 | source metadata·partial 계약 검증 통과 |
| `SQS_WORKER_ENABLED` | 비동기 Agent worker | retry·stale recovery·graceful shutdown 검증 |
| `EMAIL_NOTIFICATION_ENABLED` | 완료 알림 | 수신 동의·재시도·중복 방지 검증 |

flag가 꺼졌거나 의존 서비스가 없으면 mock 성공을 반환하지 않는다. 기능별로
`partial`, `dependency_unavailable` 또는 명시적인 disabled 상태를 반환한다.

## 3. Vision v2 경계

### 3.1 입력 정책

- 원본 이미지·영상 경로를 OpenAI 요청에 직접 전달하지 않는다.
- ClamAV 또는 지정된 scan provider가 clean으로 판정한 파일만 처리한다.
- 얼굴·차량번호 등 식별 정보가 제거된 `selected_redacted_frames`만 전달한다.
- 영상은 최대 50MiB로 제한하고 분석 전에 오디오를 제거한다.
- 공간 위치 판단이 중요한 프레임은 `original`, 일반 프레임은 `high` detail을
  사용한다.

### 3.2 모델 호출

- 기본 모델은 `VISION_PIPELINE_MODEL=gpt-5.6-terra`이며 환경변수로 교체한다.
- OpenAI Responses API를 사용한다.
- `store=False`로 요청 저장을 비활성화한다.
- `text.format`의 strict JSON Schema로 `vision_media_result.v2`를 요구한다.
- detector 정책 이름은 `RT-DETRv2-S`, `YOLO26n`으로 기록하되, 모델 설치나
  GPU 가용성을 성공으로 가정하지 않는다.

### 3.3 출력 정책

`vision_media_result.v2`는 다음 항목을 포함한다.

- 관찰 요약
- 시간 순서 사건
- 객체 탐지 결과
- 후속 사실 카드로 변환할 evidence
- 한계와 불확실성
- redaction, audio removal, 선택 프레임 수

Vision 결과는 법률 판단이나 확정 과실비율이 아니다. 사용자가 확인하기 전에는
`confirmed_fact`로 승격하지 않는다.

## 4. 외부 근거 MCP 경계

상담 근거와 운영 명령은 서로 다른 서비스로 분리한다.

### 4.1 Evidence MCP

`evidence_mcp_service.py`는 다음 provider 결과만 취합한다.

- `traffic_context_mcp`
- `police_context_mcp`
- `court_law_mcp`

모든 evidence에는 다음 필드가 필요하다.

- `source_type`
- `source_url` 또는 내부 `source_ref`
- `retrieved_at`
- `data_revision`
- `limitation`

TAAS와 대법원 provider는 접근 방식과 자격증명이 검증될 때까지 disabled로
표시한다. 일부 provider만 성공하면 `partial`, 근거가 하나도 없으면
`dependency_unavailable`을 반환한다.

### 4.2 AWS Ops MCP

`aws_ops_mcp_service.py`는 애플리케이션 근거 검색에 사용하지 않는다. 허용된
조회 명령은 ECS 상태, CloudWatch 오류, SQS DLQ 깊이로 제한한다. worker 재시작과
실패 work item 재처리는 staging에서만 허용하고 별도의 approval token을 요구한다.
production 변경은 token 유무와 관계없이 차단한다.

## 5. 과실 범위 안전 게이트

다음 네 요소가 모두 사용자 확인 또는 검증된 근거로 채워져야 잠정 범위를
표시할 수 있다.

1. 도로 형태
2. 양 차량 행동
3. 신호 또는 우선권
4. 최초 충돌 위치

하나라도 없으면 범위를 표시하지 않고 보완 질문을 반환한다. 사망·중상·도주·
음주 또는 무면허 의심 등 고위험 표지가 있으면 자동 산출을 중지하고 전문가
연계와 증거 보존 절차를 우선한다.

## 6. 데이터와 보안

- access token은 브라우저 메모리, refresh token은 HttpOnly Secure cookie로
  분리한다.
- Case, file, report, notification 조회는 소유자 검사를 통과해야 한다.
- 원본 media와 redacted derivative를 서로 다른 object key로 관리한다.
- API key, approval token, OAuth token, 개인정보를 로그에 기록하지 않는다.
- 익명·guest·회원 보관 기간은 환경 설정과 cleanup job으로 적용한다.

## 7. Worker와 알림

SQS worker는 idempotency key로 중복 실행을 방지한다. 실패는 retry 가능 여부와
원인을 기록하며 stale work recovery와 graceful shutdown을 지원해야 한다.
이메일 알림은 사용자 동의가 있는 경우에만 발송하고 같은 job 완료를 중복
발송하지 않는다.

## 8. 테스트와 활성화 게이트

### Offline

- Case schema와 공개 route 계약
- redacted frame 강제 및 50MiB 제한
- Responses API request 구조와 strict schema
- MCP source metadata와 partial/dependency unavailable 처리
- production Ops 변경 차단
- 과실 범위 네 요소와 고위험 차단

### Integration

- PostgreSQL/pgvector, Redis, ClamAV, OpenSearch/Nori
- quarantine→scan→redaction→Vision job→evidence→report
- worker retry와 stale recovery

### Staging

- Google authorization code 1회 교환
- S3 binary write/presign과 EICAR 차단
- OpenAI Responses API Vision 결과
- MCP 실제 provider와 source metadata
- ECS/CloudWatch/SQS 조회 및 승인된 worker 복구

실제 자격증명과 staging runtime 검증이 끝나기 전에는 운영 완료로 표시하지
않는다.

## 9. 현재 제한

- Vision 서비스는 비활성 기본이며 실제 frame extraction/redaction worker 연결이
  남아 있다.
- Evidence MCP는 source-aware aggregation 계약이며 실제 provider adapter가 남아
  있다.
- AWS Ops MCP는 allowlist와 승인 경계만 제공하며 실제 boto3 adapter가 남아 있다.
- Neo4j 사건 그래프와 통합 RAG mapper는 #171, #172에서 구현한다.

