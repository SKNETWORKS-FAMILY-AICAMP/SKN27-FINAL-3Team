# Supervisor → Reporting 영속 handoff v1

## 목적

Reporting Agent는 같은 프로세스 메모리에 남아 있는 분석 출력이 아니라, PostgreSQL의
`agent_results`에 먼저 저장되고 다시 조회된 결과만 사용한다. 이 규칙은 분석 결과와
최종 보고서의 추적 가능성, worker 재시도 시 외부 AI 호출 비용 절감, 보고서 생성 여부의
일관성을 보장한다.

DL/비전 노드는 선택 사항이다. 그 외 계획에 포함된 분석 노드는 Reporting gate의 필수
결과로 취급한다.

## 운영 순서

1. canonical API가 Reporting Agent가 포함된 계획을 받으면 요청된 실행 모드와 관계없이
   비동기 worker 큐에 넣는다.
2. worker가 Reporting 이전의 분석 노드만 실행한다.
3. 분석 결과를 `agent_results`에 저장하고 `analysis_persisted` checkpoint를 commit한다.
4. worker가 방금 저장한 행을 DB에서 다시 조회한다.
5. 조회 결과로 `supervisor_reporting_handoff.v1`을 결정론적으로 만들고
   `analysis_jobs.metadata`에 저장한다.
6. `ready_for_reporting=true`인 `ready` gate에서만 Reporting Agent를 별도로 실행한다.
   `draft`와 `blocked`는 Reporting paid guard와 provider 호출을 만들지 않는다. Reporting 입력의
   `upstream_results`는 비우고, 저장된 handoff만 전달한다.
7. Reporting 출력의 handoff ID와 source fingerprint가 입력 handoff와 일치하는지 검사한
   뒤 Reporting 결과를 `agent_results`에 checkpoint한다.
8. 하나의 DB transaction에서 최종 job 상태, `analysis_display_results`, JSON `reports`,
   work item 완료 상태를 저장한다.
9. transaction commit 후에만 progress/session cache를 terminal 상태로 발행한다.

## Gate 규칙

- `ready`: 모든 필수 분석 결과가 정확히 1개이고 `success`이다.
- `draft`: 필수 결과가 정확히 1개씩 존재하지만 하나 이상이 `partial`이다.
- `blocked`: 필수 결과가 없거나, 중복되거나, `failed`이거나, 허용되지 않은 상태다.
- DL/비전 선택 결과가 없거나 실패해도 gate를 차단하지 않지만 handoff에 제약 사항으로
  기록한다.
- handoff는 `source_node_codes`와 boolean `ready_for_reporting`을 명시한다.
- `draft` 또는 `blocked`이면 Reporting Agent를 실행하지 않고 Report도 만들지 않는다.

## 저장 계약과 비용 정책

- 모든 필수 결과와 Reporting 결과가 성공한 Report만 `READY`로 저장한다.
- 부분 분석은 `DRAFT` Report를 합성하지 않고 분석 display의 보완 필요 상태로 남긴다.
- worker 완료에 필요한 영속 artifact는 DB JSON Report뿐이다.
- PDF 렌더링과 S3 업로드는 worker 완료 시 자동 실행하지 않는다. 사용자가 다운로드를
  요청할 때 DB JSON으로 PDF를 생성한다.
- 기존 worker `DRAFT` 데이터는 미리보기 전용이며 직접 다운로드 URL은
  `409 report_not_ready`로 차단한다.
- 이 정책은 실패/재시도마다 PDF와 S3 비용이 반복되는 것을 막는다.

## 재시도와 멱등성

- Case 분석 시작은 같은 확정 사실 버전의 활성 job/work item을 재사용한다. 더블클릭이나
  네트워크 재전송으로 분석 Agent 비용이 중복 발생하지 않는다.
- 동일한 사실확정 payload가 재전송되면 `confirmed_facts_idempotency.v1` fingerprint로 기존
  사실 버전을 반환하고 실행 중인 활성 job을 유지한다.
- 새 사실 버전을 확정하면 이전 활성 job을 즉시 무효화한다. worker claim 시점과 분석
  checkpoint 이후에 다시 확인해 오래된 작업을 취소하며, Reporting Agent와 Report 저장을
  건너뛴다.
- 분석 checkpoint 후 handoff 저장이 실패하면 다음 시도는 기존 분석 행으로 handoff를
  재구성하며 분석 Agent를 다시 호출하지 않는다.
- Reporting checkpoint 후 bundle 저장이 실패하면 기존 Reporting 결과를 재사용한다.
- 분석/Reporting Agent 호출 전 `agent_invocations`에 `paid_agent_call_guard.v1` 요청
  fingerprint를 먼저 저장한다. provider 응답이 불명확하거나 응답 후 checkpoint가 실패하면
  자동 재호출을 막고 `PaidAgentCallRetryBlockedError`로 사람의 확인을 요구한다.
- Reporting 단계가 없는 plan도 같은 paid-call guard를 사용한다. Agent 결과 checkpoint가
  성공한 뒤 최종 저장만 실패하면 다음 worker 시도는 저장된 `agent_results`를 재사용하고
  provider를 다시 호출하지 않는다.
- guard에는 dispatch 당시 실제 실행 가능한 `expected_node_codes` snapshot을 저장한다. raw
  plan의 blocked/waiting step은 checkpoint 완전성 판단에 포함하지 않으며, blocked Reporting
  step은 `reporting_step_not_executable` gate로 차단하고 guard/provider를 만들지 않는다.
- stale worker에 paid-call guard만 있고 대응하는 결과 checkpoint가 없으면 자동 재실행하지
  않고 `paid_agent_call_retry_blocked`로 수동 복구를 요구한다.
- Report ID는 job ID에서 결정론적으로 만들고, source fingerprint가 다르면 기존 Report를
  덮어쓰지 않고 fail-closed 처리한다.
- Case Report는 분석에 사용한 immutable `ConfirmedFactVersion`을
  `source_fact_version` FK와 JSON source에 함께 기록한다.
- terminal cache는 DB transaction이 실제 commit된 뒤에만 갱신한다.
- Case worker의 잠금 순서는 claim, checkpoint, timeout, failure, final bundle 모두
  `Case → Session → Job → WorkItem → Invocation`으로 통일하며 외부 Agent 호출 중에는 행
  잠금을 유지하지 않는다. guard commit을 paid dispatch 승인 시점으로 본다.
- active `queued/retrying/running` WorkItem 또는 legacy `running` Job이 있는 guest Session은
  Case로 늦게 승격하지 않고 `409 case_analysis_in_progress`를 반환한다. enqueue는 같은 Session
  잠금 경계에서 최신 owner/case를 다시 검증하고 새 Job을 authoritative Case에 연결한다.
- WorkItem 생성 전의 `canonical_analysis_job_reservation`도 active로 취급한다. Case-bound worker는
  claim, paid dispatch, 최종 저장, report bundle 각 경계에서 active job ID와 confirmed immutable
  fact version을 독립 검증하며 provenance가 없으면 Agent 호출 전에 fail-closed 처리한다.

## 개인정보·권한 경계

- handoff에는 허용된 결과 필드와 최소 attachment reference만 포함한다.
- raw prompt/user text fallback, OCR 원문, reasoning, token/secret, 로컬 경로, signed URL은
  handoff와 Report JSON에서 제거한다.
- 중첩 key뿐 아니라 일반 문자열 속 Bearer/Basic/JWT/Google `ya29.*`/GitHub classic 및
  `github_pat_*` fine-grained PAT/API/AWS key와 PEM private-key 전체 블록도
  `[REDACTED_CREDENTIAL]`로 치환한다.
- 보고서 접근은 PDF 렌더링 전에 owner 또는 검증된 guest binding으로 승인한다. session ID
  단독 일치는 권한 근거가 아니다.
- 게스트 상담을 로그인 계정에 저장하면 해당 세션의 owner 없는 Report도 같은 transaction
  경계에서 계정 owner로 승격한다.
- 운영 배포는 서명·세션 검증된 App JWT만 허용해야 한다. `auth_session_mock_service`의 임의
  Bearer subject fallback이 제거되는 #192 실인증 전환 전에는 이 object authorization을
  운영 보안 경계로 간주할 수 없으며 배포 gate를 통과시키지 않는다.

## 공개 응답

분석 job/result 응답은 다음 값을 노출한다.

- `supervisor_reporting_handoff`: contract, gate, source result IDs/fingerprint
- `reporting_pipeline`: 현재 checkpoint/bundle 단계
- `reporting_payload`: 화면과 PDF가 함께 쓰는 `reporting_payload.v2`; `source`는
  `supervisor_agent_result_aggregation`이고 handoff ID/fingerprint는 `provenance`에 기록
- `report_links`: READY Report의 detail과 download

canonical `/api/reports/` POST는 새 리포트를 합성하지 않고
`409 worker_report_action_required`를 반환한다. 화면은 worker가 저장한 Report ID로 detail,
save-state, download API만 사용한다.

`/api/agents/plans/run/`의 canonical 경로도 Reporting 단계가 있으면 자동으로 worker를
사용한다. `/api/mock/...` 레거시 데모 동기 경로는 운영 보장의 대상이 아니다.
