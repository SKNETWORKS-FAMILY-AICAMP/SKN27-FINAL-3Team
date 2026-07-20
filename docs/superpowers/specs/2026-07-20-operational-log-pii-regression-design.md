# 운영 로그 개인정보 노출 회귀 검증 설계

## 목적

채팅 요청부터 큐 등록, Worker 실패 처리, 문서 생성, 파일/OCR 처리까지의 운영 관측 경계에서 원문 개인정보와 민감 실행 정보가 외부 로그나 운영 결과에 남지 않도록 회귀 테스트로 고정한다.

이 작업은 OCR·법령·판례의 도메인 판정이나 외부 데이터 품질을 바꾸지 않는다. Supervisor·Django·Worker·문서 생성의 공통 개인정보 통합 QA 범위만 다룬다.

## 확인된 현재 경계

- `backend/chatbot/views.py`는 채팅 분석 작업 예약·계획·큐 저장 실패 시 오류 클래스만 기록한다.
- `backend/chatbot/file_scan_service.py`는 파일 검사와 저장소 승격 실패 시 오류 클래스만 기록한다.
- `ai/agents/objection_report_generation/agent.py`는 문서 초안 생성 실패 시 오류 클래스만 기록한다.
- `backend/chatbot/repositories.py`의 Worker 실패 처리기는 예외 원문 대신 고정 메시지와 오류 코드만 작업 결과·진행 이벤트에 저장한다.
- 전역 Django `LOGGING` 설정이나 CloudWatch 전용 수집 계층은 없다.

## 선택한 접근

기존 로그·운영 결과 경계를 실제 예외와 함께 실행하고, 캡처한 출력에 민감 원문이 없는지 확인한다. 새 전역 logger, logging filter, 외부 수집 인프라는 만들지 않는다.

검증용 예외와 입력에는 다음과 같은 고유 원문을 포함한다.

- 이름, 전화번호, 주민등록번호, 주소, 차량번호
- 원본 파일명과 로컬 파일 경로
- object-storage URI와 비밀값 형태의 문자열

허용되는 관측 값은 오류 클래스, 고정 오류 코드, 마스킹 토큰, 개인정보 범주·개수, 비식별 작업 ID와 상태뿐이다.

Supervisor 런타임 스모크의 `llm.reason`은 예외 원문을 전달하지 않는 공개 안전 코드여야 한다. 허용 코드는 `ok`, `disabled`, `missing_config`, `provider_unavailable`, `invalid_contract`이며, 그 밖의 값은 `unspecified`으로 정규화한다.

## 구성과 데이터 흐름

### 채팅·큐 로그

분석 작업 예약·계획·큐 저장 실패를 유도하고 `chatbot.views` logger를 캡처한다. 예외 메시지 원문은 로그에 없고 `error_type`만 남아야 한다.

### 파일/OCR 처리 로그

파일 검사 또는 저장소 승격 예외를 유도하고 `chatbot.file_scan_service` logger를 캡처한다. 원본 파일명, 경로, URI, OCR 원문은 없어야 한다.

### 문서 생성 Agent 로그

이의신청서 초안 생성 provider 예외를 유도하고 `ai.agents.objection_report_generation.agent` logger를 캡처한다. 프롬프트와 예외 원문은 없어야 하며 오류 클래스만 남아야 한다.

### Worker 운영 결과

Worker 실행 파이프라인에서 민감 원문을 가진 예외를 발생시킨다. `AgentWorkItem.result`, `AnalysisJob.progress_message`, 진행 이벤트와 반환 DTO에는 원문이 없고 고정 메시지·오류 코드만 있어야 한다.

### Supervisor 런타임 스모크 출력

기존 `supervisor_conversation_runtime_smoke.v1` 출력은 상태·비식별 ID·검사 결과만 포함한다. `_safe_llm`은 상태와 허용된 `reason` 코드만 반환하고, 원본 `reason` 문자열은 전달하지 않는다. 안전 출력 회귀 테스트는 사용자 입력, storage URI, provider/model 식별자, secret 또는 허용되지 않은 `reason` 원문이 결과에 포함되지 않음을 확인한다.

## 테스트 전략

- Django `TestCase`와 `assertLogs` 또는 동등한 logger 캡처를 사용한다.
- 외부 LLM, S3, 실제 파일 스캐너 호출은 모두 fake/patch로 대체한다.
- 정상 경로와 실패 경로를 함께 확인하되, 테스트가 검증하는 것은 관측 출력의 비식별성이다.
- 금지 문자열은 원문 그대로 assertion하고, 오류 클래스·고정 코드가 남는지도 함께 assertion해 운영 진단성을 보장한다.
- Supervisor 스모크에는 PII·파일 경로·storage URI·secret·model 문자열을 포함한 `reason`을 주입하고, 출력이 `unspecified`으로 정규화되는지 확인한다.

## 제외 범위

- 전역 `LOGGING` 설정, CloudWatch, 로그 보관·삭제 정책 변경
- 법령 검색·OCR·판례·RAG의 도메인 로직 또는 데이터 품질 변경
- 새 외부 provider, 실제 API 키, 실제 object storage 호출
- 사용자 화면·다운로드 정책 변경

## 완료 기준

- 채팅·큐, 파일/OCR, 문서 생성, Worker 실패, Supervisor 런타임 스모크 출력의 회귀 테스트가 통과한다.
- 금지 문자열이 각 캡처 로그와 Worker 운영 결과에 없음을 확인한다.
- Supervisor 스모크의 허용되지 않은 `reason` 원문이 `unspecified`으로 정규화됨을 확인한다.
- 기존 입력 개인정보·Supervisor 런타임 스모크 테스트가 함께 통과한다.
- `project-readiness-master-checklist.md`의 운영 로그 개인정보 노출 회귀 테스트 상태를 구현 결과에 따라 갱신한다.
