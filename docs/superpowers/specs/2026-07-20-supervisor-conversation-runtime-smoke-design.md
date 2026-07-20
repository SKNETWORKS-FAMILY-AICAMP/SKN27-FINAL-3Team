# Supervisor 대화-실행-리포트 통합 런타임 스모크 설계

## 목적

Supervisor LLM 계획 스모크와 비DL Agent·Worker·Reporting 스모크 사이의 단절을 없앤다. 안전한 fixture 하나가 공개 채팅 요청에서 시작해 Supervisor 계획, 큐, Worker, 영속 handoff, Reporting, 사용자용 결과 조회까지 이어지는지를 검증한다.

이 작업은 사용자 화면의 정책이나 Agent 업무 규칙을 바꾸지 않는다. 검증 경로와 증빙을 추가해, 정상 연결과 안전한 차단을 반복 가능하게 확인하는 것이 목표다.

## 범위와 비범위

포함 범위:

- Django 공개 채팅 처리 경로를 사용한 통합 스모크 명령
- 실제 LLM strict 모드, LLM 비활성 대체 모드, LLM 실패·계약 오류 차단 모드의 구분
- 큐·Worker·Agent 결과·persisted Supervisor handoff·Reporting·사용자용 결과 조회 검증
- 공식 이의신청서에 한한 기존 최종 확인 게이트 후 DOCX 다운로드 증빙
- 일반 분석 리포트에는 다운로드 파일이 없다는 정책 증빙
- 로컬/CI의 fake provider·adapter 계약 테스트와 운영 strict 실행 문서
- 마스터 체크리스트에서 #229 서버 handoff 완료와 새 통합 E2E 항목 분리

제외 범위:

- Supervisor 라우팅·프롬프트·Agent 업무 규칙 변경
- 신규 Agent, 외부 LLM 공급자·모델, 운영 API 키 또는 실제 개인정보 도입
- 일반 분석 리포트의 DOCX/PDF 다운로드 복구
- 최종 확인 게이트 우회
- `issue/objection-report-generation` 브랜치 수정·병합·삭제

## 접근 방식

새 `smoke_supervisor_conversation_runtime` 관리 명령을 만든다. 명령은 테스트 fixture로 만든 공개 채팅 요청을 Django의 `submit_chat_message` view에 전달하고, 반환된 work item을 기존 Worker 처리 경로로 실행한다. 따라서 관리 명령이 상담 계획·큐 등록 로직을 복제하지 않고, 실제 공개 경로의 503·queued 응답 계약을 그대로 검증한다.

정상 경로에서는 공개 응답이 `queued`이고 `execution_mode`가 `async_worker`여야 한다. 그 뒤 Worker가 분석 결과를 저장하고, persisted `supervisor_reporting_handoff.v1`을 소비한 Reporting 결과, `Report`, `AnalysisDisplayResult`를 생성해야 한다. 결과 조회는 공개 DTO만 사용하며, 내부 저장 URI·첨부 원문·프롬프트를 증빙 출력에 포함하지 않는다.

실패 경로에서는 Supervisor LLM이 `failed` 또는 계약 오류 상태가 되어 공개 채팅 응답이 HTTP 503과 `supervisor_unavailable`을 반환해야 한다. 이 경우 AnalysisJob, AgentWorkItem, AgentResult, Report, paid guard가 생성되지 않아야 한다.

LLM이 비활성인 로컬·개발 모드는 fallback/disabled 상태를 결과에 명시한다. 이 경로는 기능 회귀 확인에는 사용할 수 있지만, strict 성공으로 판정하지 않는다.

## 명령 계약

명령은 기본적으로 실제 provider를 호출하지 않는다. strict 운영 실행에는 다음을 모두 요구한다.

- `--allow-paid-provider-call`
- `--require-llm-used`
- `--require-real-agent-results`
- `--require-persisted-handoff`
- `--require-report`
- clean S3 `canonical/acceptance/` 아래의 운영자 검토 완료 fixture URI

출력 계약은 `supervisor_conversation_runtime_smoke.v1`이다. JSON에는 상태, LLM 상태, HTTP 상태, execution mode, job/work item/report 식별자, 검증 boolean, 실패 검사명만 포함한다. 사용자 입력, provider 원문, 문서 본문, secret, storage URI는 출력하지 않는다.

## 문서·다운로드 정책

정상 Reporting 결과는 #245의 세 문서 카드(이의신청 초안·사실관계 정리·보험사 제출 자료)를 공개 DTO로 조회한다. 카드 자체는 화면 열람·복사 대상이며 다운로드 산출물이 아니다.

공식 `fine_notice` 또는 `traffic_accident` 이의신청서는 기존 #241 최종 확인 네 항목을 모두 충족할 때만 DOCX를 다운로드할 수 있다. 증빙 fixture는 이 확인을 명시적으로 수행한 뒤 생성한 DOCX 파일을 확인한다. 일반 분석 리포트에는 다운로드 action·파일이 없어야 한다.

## 테스트와 증빙

CI는 외부 provider·실제 S3·유료 adapter 없이 Django test client, fake Supervisor provider, fake Agent adapter로 정상·대체·차단 세 경로를 재현한다. 각 테스트는 공개 응답과 영속 결과를 함께 확인한다.

구현 완료 시 로컬 fixture로 다음을 제시한다.

- 정상 연결의 터미널 JSON 및 브라우저 결과 화면
- fallback이 strict 성공으로 취급되지 않는 터미널 JSON
- `supervisor_unavailable` 차단 화면과 후속 작업 0건 증빙
- 최종 확인 뒤 내려받은 공식 DOCX 파일
- 일반 분석 리포트에서 다운로드가 보이지 않는 화면

실제 LLM·운영 S3 strict 실행은 운영 비용과 clean fixture가 준비된 뒤 사용자가 명시적으로 승인할 때만 수행한다.

## 일반 리포트 후속 행동 정리

기존 `_next_actions`의 일반 `download_report` 문자열은 공개 결과와 사건 요약까지 전달될 수 있다. 이를 `review_report_screen`으로 바꾸고, 일반 리포트의 공개 `next_actions`와 `report_actions` 어디에도 `download_report`가 남지 않는지 회귀 테스트한다. 이는 #238·#241·#245에서 확정한 일반 리포트 화면 열람 정책을 일관되게 적용하는 최소 수정이다.

## 관련 파일 예상 범위

- `backend/chatbot/management/commands/smoke_supervisor_conversation_runtime.py`
- `backend/chatbot/test_supervisor_conversation_runtime_smoke.py`
- `docs/ops/supervisor-conversation-runtime-smoke.md`
- `docs/ops/non-dl-analysis-reporting-smoke.md`
- `docs/ops/project-readiness-master-checklist.md`

필요한 경우 공개 채팅 view 테스트 파일을 보완하되, 운영 서비스 코드의 동작은 변경하지 않는다.
