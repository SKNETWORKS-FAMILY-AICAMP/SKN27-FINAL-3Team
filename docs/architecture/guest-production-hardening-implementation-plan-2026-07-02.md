# Guest Production Hardening Implementation Plan

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-07-02 |
| 목적 | 비회원 사용 제한, 실제 파일 저장/검사, LLM slot filling smoke를 실서비스 전환 순서로 정리 |
| 상태 | 구현 전 확인용 설계안 |
| 관련 코드 | `backend/config/middleware.py`, `backend/chatbot/repositories.py`, `backend/chatbot/object_storage.py`, `app/services/chatbot_mock_service.py`, `app/services/supervisor_llm_service.py` |
| 관련 문서 | `docs/architecture/auth-session-policy-2026-06-28.md`, `docs/architecture/history-operating-policy-2026-06-30.md`, `docs/issues/68-hi20260204-maker-follow-up-2026-07-01.md` |
| 참고 thread | `019f2154-b131-77b1-a5bc-7c7bf32fd71b` 실서비스 불가 원인 분석 |

## 1. 현재 확인 결과

요청된 세션 ID `019f2154-b131-77b1-a5bc-7c7bf32fd71b`를 다시 조회했고, Codex thread 목록에서 `실서비스 불가 원인 분석`으로 확인했다. 해당 thread의 결론은 현재 프로젝트가 실서비스가 아니라 "시연 가능한 데모/POC" 상태라는 것이다.

해당 thread에서 확인된 실서비스 차단 사유는 아래와 같다.

| 영역 | 차단 사유 | 이 설계에 반영할 방식 |
|---|---|---|
| 운영 보안 | `DEBUG=1`, dev secret, wildcard host, runserver 실행 | Phase 0에서 readiness baseline으로 고정하고 Phase 5 release gate에 포함 |
| 인증 | mock bearer, mock Google login, guest 허용 경계 잔존 | Phase 1에서 guest/auth action boundary 보강 |
| CORS | 모든 origin 허용 | Phase 5에서 운영 env 체크 항목으로 유지 |
| DB | local 기본 SQLite, production Postgres 검증 필요 | Phase 5에서 database introspection을 필수 release gate로 유지 |
| 파일/객체 저장소 | metadata-only S3 URI, 실제 binary write/scan 부재 | Phase 2, Phase 3의 핵심 구현 대상으로 반영 |
| AI/RAG | Supervisor/RAG mock 또는 fallback 중심 | Phase 4의 mock-off slot smoke와 readiness에 반영 |
| 관측성 | 운영 로그, 감사 로그, 장애 추적, 비용 모니터링 부족 | Phase 5에 최소 운영 이벤트/로그 체크를 포함 |
| 법률 도메인 안전장치 | 면책, 최신성, 근거 검증, 오답 대응 정책 부족 | Phase 5 이후 별도 legal safety gate로 남김 |

따라서 이 문서는 비회원 제한, 파일 scan/S3, LLM slot smoke를 우선 구현하되, 최종 실서비스 판단은 운영 보안/DB/CORS/관측성/법률 안전장치까지 통과해야 한다는 전제로 작성한다.

## 2. 로그인하지 않은 사용자 상태 정의

현재 프로젝트는 로그인하지 않은 사용자를 두 단계로 나눈다.

| 상태 | 식별 기준 | 현재 의도 | 현재 구현 상태 |
|---|---|---|---|
| `anonymous` | Authorization 없음, `X-Guest-Id` 없음 | 공개 정보만 접근 | 대부분 보호 prefix에서 401 |
| `guest` | `POST /api/auth/guest-session/` 또는 `X-Guest-Id` | chat-first 상담 체험 | 상담, 파일, 리포트 action 일부 허용 |
| `authenticated` | backend app JWT 또는 mock bearer | MyPage, History, 저장/다운로드 | 구현됨, real OAuth smoke는 별도 |

현재 middleware 기준 공개 경로는 `health`, mock scenario 정도다. `guest`는 `chat/sessions`, `chat/messages`, `chat/save-state`, `files`, `reports`가 열려 있다.

## 3. 현재 비회원 제한과 구현 정도

| 기능 | anonymous | guest | authenticated | 구현 정도 | 조정 필요성 |
|---|---:|---:|---:|---|---|
| health/scenario 조회 | 가능 | 가능 | 가능 | 구현됨 | 낮음 |
| guest session 발급 | 가능 | 가능 | 가능 | 구현됨 | 낮음 |
| 상담 메시지 | 불가 | 가능, 낮은 quota | 가능 | 구현됨 | 낮음 |
| 파일 업로드 | 불가 | 가능, 낮은 quota | 가능 | multipart UI/API 구현됨 | scan/S3 필요 |
| Agent 실행 | 불가 | 가능, 낮은 quota | 가능 | queue/worker 골격 있음 | quota/scan gate 필요 |
| save-state `pending/session_only` | 불가 | 가능 | 가능 | 구현됨 | 낮음 |
| save-state `saved` | 불가 | 현재 raw API 보강 필요 | 가능 | 프론트는 로그인 유도 | backend enforcement 필요 |
| MyPage | 불가 | 불가 | 가능 | 구현됨 | 낮음 |
| History | 불가 | 정책상 제한 조회 후보 | 가능 | view guard는 있으나 middleware와 정책 정리 필요 | 중간 |
| 리포트 저장 | 불가 | 현재 `/api/reports/` 열림 | 가능 | metadata 저장 가능 | 로그인 유도 정책과 불일치 |
| 리포트 다운로드 | 불가 | 현재 다운로드 path는 막힘 | 가능 | 구현됨 | 정책 명확화 필요 |

## 4. 실서비스 기준 정책 결정안

### 4.1 Guest 허용 범위

비회원은 "상담 체험과 단기 분석"까지만 허용한다.

| 기능 | 결정안 |
|---|---|
| 상담 시작/대화 | 허용 |
| 파일 업로드 | 허용하되 낮은 quota, scan 통과 전 Agent 입력 금지 |
| 리포트 preview metadata | 허용 |
| 리포트 저장 | 로그인 필요 |
| 리포트 다운로드 | 로그인 필요 |
| MyPage | 로그인 필요 |
| History | 로그인 필요. 단, 별도 요구가 있으면 현재 session의 standard-light events만 guest 조회 허용 가능 |
| guest 만료 | 만료된 `guest_id`는 보호 endpoint에서 401 또는 403 |

### 4.2 Save-state

`conversation_save_state=saved`는 authenticated subject에서만 허용한다.

| 요청 상태 | guest 허용 | authenticated 허용 |
|---|---:|---:|
| `pending` | 가능 | 가능 |
| `session_only` | 가능 | 가능 |
| `saved` | 불가, `login_required` | 가능 |

### 4.3 Report action

현재 `POST /api/reports/`는 guest에게 열려 있다. 실서비스 정책과 맞추기 위해 action을 나눈다.

| action | guest | authenticated |
|---|---:|---:|
| `preview` 또는 `prepare` | 가능, 저장 없음 또는 임시 metadata |
| `save` | 불가 |
| `download` | 불가 |

프론트는 guest 상태에서 report panel 버튼을 "Google 로그인 후 저장/다운로드"로 바꾼다.

## 5. 남은 production gap 반영

### 5.1 실제 S3 binary write

현재 `object_storage_policy()`는 `writes_binary=False`, `persistence_state=metadata_only_adapter`다. 즉 `s3://...` URI envelope만 만들고 실제 binary object write는 하지 않는다.

구현 방향:

1. `ObjectStorageAdapter` 인터페이스 추가
   - `put_object(bytes|file, key, content_type, metadata)`
   - `copy_object(source_key, target_key)`
   - `delete_object(key)`
   - `presign_get(key, ttl_seconds)`
2. provider 구현
   - `mock_s3`: 기존 metadata-only 유지 또는 local file adapter
   - `s3`: boto3 또는 S3-compatible client
3. 업로드 저장 정책
   - 최초 업로드는 `quarantine/uploads/...`
   - scan 통과 후 `uploads/...`로 promote
   - rejected는 삭제 또는 격리 보관
4. smoke
   - 기존 `smoke_object_storage --require-binary`가 통과해야 production readiness pass

### 5.2 Virus/PII scan

현재 `UploadedFile`에는 `privacy_risk`, `scan_status` 필드가 있고, 기본값은 `scan_status=not_started`다. 실제 scan pipeline은 없다.

구현 방향:

1. `file_scan_service.py` 추가
   - size/type/extension 정책 검사
   - mock virus scan adapter
   - PII heuristic scan adapter
   - scan result contract: `file_scan_result.v1`
2. 상태 전환
   - `uploaded` -> `scanning` -> `ready`
   - 실패 시 `rejected`
3. Agent gate
   - `scan_status != clean` 또는 `status != ready`인 파일은 Agent handoff에서 `blocked_attachments`로 분리
   - 사용자는 "검사 중/반려" UI를 본다
4. 운영 adapter hook
   - ClamAV, external scanning API, DLP API를 붙일 수 있게 provider boundary만 먼저 둔다

### 5.3 LLM slot filling mock-off credential smoke

현재 `supervisor_llm_service.py`와 `smoke_supervisor_llm --require-used`가 있다. 하지만 실제 credential/model smoke가 `used`를 반환해야 production-ready라고 볼 수 있다.

구현 방향:

1. `slot_filling_state.v1`를 LLM 출력 계약에 명시
2. LLM output validator가 아래를 강제
   - known `node_code`만 허용
   - owner override 금지
   - slot마다 `value`, `source`, `confidence`, `editable` 필요
   - PII/raw reasoning 저장 금지
3. `smoke_supervisor_llm --require-used --require-slot-state` 추가
4. readiness에서 `SUPERVISOR_LLM_ENABLED=1`이면 smoke `used`와 slot contract를 요구

### 5.4 운영 보안/배포 baseline

참고 thread `019f2154-b131-77b1-a5bc-7c7bf32fd71b`의 결론에 따라, 아래 항목은 이번 기능 구현과 별개로 production release gate에 계속 남긴다.

1. Django 운영 보안
   - `DJANGO_DEBUG=0`
   - non-default `DJANGO_SECRET_KEY`
   - production host가 포함된 `DJANGO_ALLOWED_HOSTS`
   - wildcard CORS 금지
2. 운영 실행 방식
   - Docker에서 `runserver`가 아닌 WSGI/ASGI production server 사용
   - health/readiness endpoint와 process manager 정책 정리
3. 운영 DB
   - PostgreSQL connection/introspection 성공
   - migration 적용 상태 확인
   - 기본 비밀번호/외부 포트 노출 정책 정리
4. 인증/OAuth
   - Google OAuth mock off smoke
   - mock bearer 비활성화
   - guest 만료/승격/저장 정책 검증
5. 관측성/감사
   - agent invocation, file scan, report download, auth failure 이벤트 기록
   - production readiness 실패 원인 로그화
6. 법률 안전장치
   - 법률 자문이 아니라 정보 제공이라는 표시
   - 근거 문서/검색 이벤트 추적
   - 최신성/신뢰도/오답 대응 정책 문서화

## 6. 구현 순서

### Phase 0. 실서비스 차단선 baseline과 정책 회귀 테스트

목표: 구현 전 현재 제한 정책과 실서비스 차단선을 테스트/readiness 기준으로 고정한다.

작업:

1. production readiness의 현재 fail/warn 항목을 baseline으로 정리
2. guest/auth restriction matrix 테스트 추가
3. `chat/save-state=saved` guest 거부 테스트 추가
4. guest report `save/download` 거부 테스트 추가
5. authenticated report `save/download` 허용 테스트 유지
6. 문서와 middleware/view 정책이 같은 표를 말하도록 정리
7. 실서비스 차단 항목이 기능 구현 중 조용히 사라지지 않도록 readiness 메시지를 명확히 유지

완료 기준:

- `python backend/manage.py test chatbot` 통과
- `python -m pytest test/test_frontend_auth_session_contract.py` 통과
- `check_production_readiness --skip-database`가 mock/fallback 항목을 명확히 pass/warn/fail로 설명

### Phase 1. Guest 제한 enforcement 정리

목표: middleware coarse auth와 view-level action auth를 분리한다.

작업:

1. `/api/reports/`는 guest path로 두되 view에서 action별로 제한
2. `/api/chat/save-state/`는 guest path로 두되 `saved`는 authenticated만 허용
3. expired guest identity 검사 함수 추가
4. 프론트 guest report panel을 로그인 유도 상태로 변경
5. History/MyPage guest policy를 문서와 코드 중 하나로 확정

완료 기준:

- guest는 상담/업로드/preview만 가능
- guest가 저장/다운로드/MyPage를 시도하면 `login_required` 계약 응답

### Phase 2. File scan pipeline

목표: 실제 파일을 Agent에 넘기기 전에 검사 상태를 강제한다.

작업:

1. `file_scan_service.py` 추가
2. upload 직후 `scan_status=pending` 또는 `not_started`로 저장
3. `process_uploaded_file_scans` management command 추가
4. mock scan 결과에 따라 `ready/rejected` 상태 전환
5. Agent handoff에서 `ready`만 통과
6. UI에 `uploaded/scanning/ready/rejected` 표시

완료 기준:

- scan 전 파일은 Agent package에서 blocked
- scan 통과 파일만 `attachments`로 전달
- `smoke_file_scan --require-clean` 통과

### Phase 3. Object storage binary adapter

목표: metadata-only S3 URI를 실제 binary object write로 전환한다.

작업:

1. storage adapter 인터페이스와 S3 provider 추가
2. upload는 quarantine prefix에 binary write
3. scan 통과 후 canonical prefix로 promote
4. report binary/text output도 object storage에 기록
5. download는 signed URL 또는 Django streaming 응답 정책 중 하나로 확정
6. `smoke_object_storage --require-binary` 통과

완료 기준:

- `object_storage_policy.writes_binary=True`
- uploaded file/report object가 실제 provider에 존재함을 smoke가 확인

### Phase 4. LLM slot filling mock-off smoke

목표: rule/mock slot filling을 real LLM boundary로 교체 가능한 상태로 만든다.

작업:

1. `slot_filling_state.v1` prompt/output schema 확정
2. LLM response validator 강화
3. fallback 사용 여부를 readiness에 노출
4. `smoke_supervisor_llm --require-used --require-slot-state` 추가
5. real credential 환경에서 mock-off smoke 실행

완료 기준:

- Supervisor conversation과 planner 둘 다 `llm.status=used`
- slot state가 모든 ready Agent input package에 포함됨

### Phase 5. Production readiness 통합

목표: 운영 체크 하나로 남은 gap을 드러낸다.

작업:

1. `check_production_readiness`에 아래 항목 추가
   - guest policy enforcement
   - file scan adapter ready
   - object storage binary write ready
   - supervisor LLM slot smoke ready
   - Google OAuth mock off smoke ready
   - Django security/CORS/runserver guard
   - production DB introspection/migration guard
   - minimum audit/progress event persistence guard
2. 문서 `docs/ops/production-env.md` 업데이트
3. issue #68 업데이트용 요약 작성

완료 기준:

- production env에서 `check_production_readiness --fail-on-error` pass
- local dev에서는 어떤 항목이 mock/fallback인지 명확히 warn/fail

### Phase 6. 법률 서비스 안전장치와 운영 관측성

목표: 기능은 돌아가더라도 법률/교통분쟁 도메인에서 외부 사용자에게 열 수 있는 최소 안전장치를 갖춘다.

작업:

1. 답변/리포트에 정보 제공 범위와 책임 제한 문구 계약 추가
2. RAG source/retrieval event 추적과 report 근거 연결
3. agent invocation, progress, retry, failure 이벤트를 운영 로그로 남김
4. report download, file scan rejection, auth failure를 audit event로 남김
5. 오답/정정 요청을 받을 수 있는 feedback endpoint 또는 운영 프로세스 문서화

완료 기준:

- 사용자에게 제공된 판단 근거와 사용된 source를 추적할 수 있음
- 장애/오답/보안 이벤트를 운영자가 확인할 수 있음

## 7. 권장 구현 순서 요약

1. 먼저 실서비스 차단선과 guest 제한 정책을 readiness/test로 고정한다.
2. 그 다음 guest 저장/다운로드/save-state 경계를 코드로 닫는다.
3. 파일 scan gate를 넣고, scan 전 파일은 Agent 입력에서 차단한다.
4. scan gate가 생긴 뒤 S3 binary write를 붙인다.
5. LLM slot filling mock-off smoke를 production readiness에 묶는다.
6. 운영 보안/DB/CORS/Google OAuth/관측성/법률 안전장치를 최종 release gate로 묶는다.

이 순서가 안전한 이유는 S3와 LLM을 먼저 붙여도 guest 저장/다운로드 정책이 느슨하면 개인정보와 비용 리스크가 먼저 커지기 때문이다.

## 8. 2026-07-02 구현 반영 상태

| Phase | 상태 | 반영 내용 |
|---|---|---|
| Phase 0 | 완료 | guest/report/save-state 정책 테스트와 readiness baseline 확인 |
| Phase 1 | 완료 | guest `saved`, report `save/download`, expired guest 차단 및 프론트 로그인 유도 |
| Phase 2 | 완료 | `file_scan_result.v1`, `process_uploaded_file_scans`, `smoke_file_scan`, Agent attachment scan gate |
| Phase 3 | 부분 완료 | `mock_s3` local binary write, report/upload object write, `smoke_object_storage --require-binary` 통과 경계 |
| Phase 4 | 부분 완료 | `slot_filling_state.v1` validator와 `smoke_supervisor_llm --require-slot-state` 추가 |
| Phase 5 | 부분 완료 | readiness에 `file_scan`, object storage binary policy, supervisor slot smoke metadata 반영 |
| Phase 6 | 미착수 | 법률 면책/근거 추적/오답 대응/운영 관측성 상세 구현 필요 |

아직 남은 운영 확인:

1. 실제 `OBJECT_STORAGE_PROVIDER=s3` credential 환경에서 `smoke_object_storage --require-binary` 실행
2. 실제 LLM credential 환경에서 `smoke_supervisor_llm --require-used --require-slot-state` 실행
3. Google OAuth mock-off code exchange smoke
4. PostgreSQL/pgvector/worker queue 포함 `check_production_readiness --fail-on-error`
5. ClamAV 또는 외부 DLP/PII provider 연결 여부 결정

## 9. 정책 결정 기록

아래 네 가지 추천안을 기준으로 구현을 시작했다.

1. Guest report 정책
   - 추천: guest는 preview만 가능, save/download는 로그인 필요
2. Guest history 정책
   - 추천: MyPage/History는 로그인 필요. 단, 현재 session status 정도만 화면 내부에서 표시
3. File scan 초기 구현 수준
   - 추천: mock scanner + PII regex + extension/size policy 먼저, ClamAV/S3 DLP는 provider hook으로 둠
4. S3 provider
   - 추천: `OBJECT_STORAGE_PROVIDER=s3`일 때 boto3/S3-compatible adapter, dev는 `mock_s3` 유지
