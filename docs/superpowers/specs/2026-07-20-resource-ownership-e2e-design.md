# 세션·분석·첨부파일·리포트 소유권 E2E 검증 설계

## 목적

한 사용자가 만든 세션, 첨부파일, 분석 Job, Worker 결과, 리포트와 문서 다운로드가 다른 사용자에게 노출되거나 연결되지 않도록, 실제 Django API 요청 흐름의 회귀 테스트로 고정한다.

## 현재 확인된 계약

- `backend/chatbot/repositories.py`의 `authorize_resource_access()`가 사용자·게스트·세션 식별자를 기준으로 자원 접근을 판단한다.
- 첨부 메타데이터, 분석 Job 상세·결과, 리포트 상세·다운로드는 최소 접근 메타데이터를 먼저 읽고 권한을 확인한다.
- 비소유자 접근의 현재 안전한 HTTP 계약은 `403`과 `error.code == "object_access_denied"`다. 이 작업은 존재 여부를 감추는 `404`로 변경하지 않는다.
- 현재 개별 테스트는 채팅 follow-up, 다른 사용자의 리포트 다운로드, 다른 사용자의 Case 파일 등록을 각각 확인한다. 그러나 하나의 소유자 자원을 두 사용자 요청과 Worker 결과까지 이어 검증하는 테스트는 없다.

## 선택한 접근

새 Django `TestCase` 하나에서 소유자와 비소유자 인증 Client를 생성한다. 소유자의 `ChatSession`, `UploadedFile`, `AnalysisJob`, `Report`를 실제 모델·저장소 계약으로 준비하고, Job의 결과·Report가 같은 `owner_id`와 `session_id`에 연결됐는지 확인한다.

동일 Client는 각 자원의 정상 API 흐름을 통과해야 한다. 비소유자 Client는 같은 식별자를 사용해도 모든 경계에서 `403 object_access_denied`를 받아야 하며, 응답과 문서 본문에는 소유자 ID, storage URI, 원문 리포트 내용, 파일 경로가 없어야 한다.

외부 LLM, OCR, S3, 실제 백그라운드 프로세스는 사용하지 않는다. Worker 연결은 테스트 DB의 Job·Report 영속 결과와 기존 Worker 저장소 함수를 사용해 검증한다. 따라서 API 권한·저장소 연결을 검증하면서 CI 재현성을 유지한다.

## 대안과 제외 이유

### A. 단일 Django API E2E 테스트 (선택)

두 인증 주체가 동일한 자원 식별자에 요청하는 실제 URL 경계를 확인한다. 라우팅, 인증 주체 전달, 접근 메타데이터, 오류 직렬화를 한 번에 검증할 수 있다.

### B. 기존 단위 테스트 파일에 항목별 추가

개별 기능에는 가깝지만 세션·첨부·Job·리포트가 같은 소유권 체인으로 유지되는지 증명하지 못한다.

### C. 외부 Worker와 Provider를 포함한 런타임 E2E

운영과 가장 유사하지만 외부 자격 증명·큐·LLM·저장소에 의존해 CI 회귀 테스트로 부적합하다.

## 검증 대상

### A. 소유자 정상 흐름

- 소유자는 자신이 만든 세션의 분석 Job 목록과 상세·결과를 조회할 수 있다.
- 소유자는 자신의 첨부 메타데이터를 조회할 수 있다.
- 소유자는 자신의 리포트 상세를 조회하고, 기존 문서 확인·appeal gate 조건을 만족하는 경우에만 DOCX를 다운로드할 수 있다.
- Worker 결과로 영속된 Job과 Report의 `owner_id`, `session_id`, 연결된 Case 또는 Job 참조는 원래 소유자 세션과 일치한다.

### B. 비소유자 차단 흐름

비소유자 Client가 소유자의 `session_id`, `attachment_id`, `job_id`, `report_id`를 사용해 다음 경로를 요청한다.

- 분석 Job 목록의 `session_id` 필터, Job 상세와 결과
- 첨부 메타데이터 상세
- 리포트 상세와 DOCX 다운로드
- 저장 상태 변경 또는 분석 요청에서 소유자 세션 재사용

각 요청은 `403 object_access_denied`를 반환하며 성공 데이터나 다운로드 응답을 반환하면 안 된다.

### C. 비노출 보장

비소유자 거부 JSON과 응답 헤더·본문을 직렬화해 다음 값이 없음을 확인한다.

- `owner_id`
- `storage_uri`, 버킷 이름, 내부 파일 경로
- 리포트 `content`, `content_summary`, 문서 바이트
- Worker 내부 실행 메타데이터와 요청 지문

요청자가 이미 알고 있는 `session_id`, `attachment_id`, `job_id`, `report_id`는 오류 자원 식별자로 표시될 수 있으므로 비노출 검사 대상이 아니다.

## 구현 경계

- 새 테스트는 `backend/chatbot/test_resource_ownership_e2e.py`에 둔다.
- 기존 `authenticated_client()` 패턴과 Django Test DB를 사용한다.
- API·저장소 코드의 결함을 회귀 테스트가 재현할 때만 최소 수정한다. 인증 공급자, DB 권한 체계, 문서 형식, OCR·RAG·LLM 동작은 변경하지 않는다.
- 체크리스트는 독립 PR로 만들지 않는다. 구현 PR 링크를 검토한 뒤 같은 브랜치에서 #254의 진행 또는 완료 상태를 함께 반영한다.

## 완료 기준

- 소유자 정상 경로와 비소유자 차단 경로가 자동 테스트로 통과한다.
- Worker로 생성된 Job·Report 소유자 연결이 테스트 DB에서 일치한다.
- 모든 비소유자 거부 응답은 현재 `403 object_access_denied` 계약을 유지하고 민감한 메타데이터나 문서 내용을 포함하지 않는다.
- 집중 테스트, 전체 pytest, `git diff --check`가 통과한다.

## 제외 범위

- 인증 Provider 또는 JWT 형식 변경
- 행 수준 보안(RLS)·DB 스키마 전면 재설계
- 실제 S3·OCR·LLM·외부 Worker 실행
- OCR·법령·판례 데이터 품질과 도메인 판단 변경
