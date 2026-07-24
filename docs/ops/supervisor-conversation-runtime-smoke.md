# Supervisor 대화 런타임 스모크

`smoke_supervisor_conversation_runtime`은 공개 채팅 API에서 시작한 요청이
Supervisor 계획, canonical queue, Worker, persisted handoff, Reporting,
공개 결과 조회까지 이어지는지 확인한다.

검증 범위는 다음과 같다.

```text
POST /api/chat/messages/
  -> Supervisor 계획
  -> AnalysisJob / AgentWorkItem queue
  -> Worker 분석 결과 저장
  -> supervisor_reporting_handoff.v1 저장·소비
  -> Report / AnalysisDisplayResult
  -> GET /api/analysis/results/{job_id}/
```

## 안전한 기본 검증

로컬/CI에서는 실제 provider를 호출하지 않는다. 아래 Django 테스트가
Supervisor와 Agent adapter 경계를 fake로 고정하고 공개 view와 Worker 경계는
실제로 실행한다. 운영 명령 자체는 큐를 직접 처리하지 않고 배포된 Worker가 DB
lease를 획득해 terminal 상태를 저장할 때까지 bounded polling한다.

```powershell
python backend/manage.py test chatbot.test_supervisor_conversation_runtime_smoke -v 1
```

이 테스트는 다음을 포함한다.

- 비용 호출 동의 또는 clean S3 acceptance fixture가 없으면 Job/Worker/Report를
  만들지 않는지
- `supervisor_unavailable`이 HTTP 503과 `planning_blocked`로 끝나고, 이번
  smoke session에는 후속 Job/Worker/Report가 생기지 않는지
- 리포트 요청 계획에서 `objection_report_generation`이 마지막 Worker 단계인지
- 전체 분석 결과를 저장한 뒤 handoff provenance를 가진 Reporting 결과와
  `ready` Report/`AnalysisDisplayResult`가 생기는지

## 실제 provider 검증

실제 provider 또는 외부 검색 adapter를 호출할 수 있으므로 운영자가 명시적으로
동의하고, 개인정보가 제거된 clean S3 fixture를 준비했을 때만 실행한다.

```powershell
python backend/manage.py smoke_supervisor_conversation_runtime `
  --allow-paid-provider-call `
  --fine-notice-fixture-s3-uri "s3://<clean-bucket>/canonical/acceptance/<reviewed-file>.png" `
  --require-llm-used `
  --require-real-agent-results `
  --require-persisted-handoff `
  --require-report `
  --timeout-seconds 600 `
  --format json
```

`canonical/acceptance/` 밖의 경로, query/fragment가 붙은 URI, 지원하지 않는
확장자는 queue 생성 전 거부된다. API key, 원문 고지서, 사용자 개인정보를 명령행
또는 출력에 넣지 않는다.

## 결과 판정

출력 계약은 `supervisor_conversation_runtime_smoke.v1`이다. 출력에는 Job/Work
item 식별자, 상태, boolean check만 포함하며 prompt, 원문 첨부, provider 응답,
비밀값, storage URI는 포함하지 않는다.

strict 실행에서 다음이 모두 참이어야 통과다.

- `chat.status=queued` 및 public chat의 HTTP 202
- `llm.status=used`
- `job_success`, `all_agent_results_success`, `worker_loop_consumed`,
  `worker_completed`
- `persisted_handoff_consumed`
- `report_ready`, `analysis_display_persisted`, `public_result_loaded`

`supervisor_unavailable`, fallback/disabled LLM, partial Agent 결과는 strict
통과가 아니다. `planning_failure_has_no_followup_rows`가 거짓이면 해당 실행을
중단하고 queue 생성 경계를 먼저 조사한다.

## 문서 다운로드 정책

이 smoke는 리포트 생성과 결과 조회까지만 증명한다. 일반 분석 리포트는 화면에서
열람·복사만 가능하며 PDF/DOCX 다운로드를 제공하지 않는다. `fine_notice`와
`traffic_accident`의 공식 이의신청서 DOCX는 별도 최종 확인 및 appeal gate
(`denied`, `not_applicable`, 기한 경과 차단)를 통과한 뒤에만 다운로드한다.
