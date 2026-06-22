# hi20260204-maker 단독 처리 이슈 진행 및 close 가능성 점검

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-06-22 |
| 기준일 | 2026-06-22 월요일 KST |
| 이번 주 금요일 | 2026-06-26 |
| 기준 저장소 | `SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team` |
| 기준 브랜치 | `docs-wbs-owner-deliverable-plan` |
| 목적 | `hi20260204-maker`가 혼자 진행할 수 있는 문서, PM, QA 기준 작업을 순차 진행하고, 각 이슈의 close 가능 여부를 점검한다. |

## 1. 단독 진행 원칙

- 구현 문서에 없는 기능, API, 모델, schema는 확정하지 않는다.
- 팀원 산출물이 필요한 항목은 PM 초안까지만 작성하고 `검증 필요`로 둔다.
- GitHub Issue close는 사용자가 승인하기 전에는 수행하지 않는다.
- `feat-*` 이슈는 정적 문서나 화면 초안만으로는 구현 완료로 보지 않는다.
- `docs-*` 이슈도 후속 팀원 입력이나 Project 상태 확인이 남아 있으면 close 보류로 둔다.

## 2. 순차 진행 결과

| 순서 | 이슈 | 단독 진행 내용 | 현재 판정 |
|---:|---|---|---|
| 1 | `#11 docs-wbs-owner-deliverable-plan` | 오늘 회의 기준 담당자별 comment 대상, 기한, 공유 방식, PM 확인 항목을 정리한다. | PM 정리는 가능하나 팀원 comment 누락 확인과 Project 상태 갱신이 남아 close 보류 |
| 2 | `#13 docs-requirement-gap-and-risk-log` | 데이터 다운로드/용량, 수집 미구현, OCR schema 미완료, chunking/embedding 문제, API/모델 미정을 리스크로 분리한다. | 살아 있는 리스크 로그라 close 보류 |
| 3 | `#12 docs-mvp-screen-and-process-flows` | `docs/screen-design-specification.md`, `docs/screen-design-ui-ux-flow-guide.md`, `app/screen-design-mvp-flow.html` 기준으로 화면 흐름 반영 상태를 확인한다. | 문서 범위만 보면 조건부 close 가능 |
| 4 | `#14 feat-home-login-chatbot-entry` | 정적 HTML 산출물은 있으나 실제 로그인, 라우팅, 챗봇 기능 구현 여부를 확인한다. | 실제 기능 구현이 없어 close 불가 |
| 5 | `#22 feat-agent-result-schema-and-rag-contract` | 공통 결과 envelope, evidence source type, 상태값 기준은 PM 초안으로 정리한다. | 각 담당자 schema 수신 전이므로 close 불가 |
| 6 | `#29 feat-supervisor-chatbot-routing` | 입력 유형별 routing 초안과 법률 근거 항상 호출 원칙을 정리한다. | `#22`와 담당자별 input/output 확정 전이라 close 불가 |
| 7 | `#27 feat-objection-draft-report-node` | 이의신청서 생성 input/output, 추가 질문 조건, 면책 문구 기준을 정리한다. | 필주 분석 패키지와 동혁 법률 metadata 수신 전이라 close 불가 |
| 8 | `#40 test-cross-mvp-integration-scenarios` | `INT-001`~`INT-006` 통합 시나리오 상태와 남은 샘플/검증 리스크를 정리한다. | 실제 샘플 실행 전이라 close 불가 |
| 9 | `#41 test-legal-ai-guardrail-validation` | 법률 단정, 과실비율 수치 단정, 제출 성공 보장 금지 기준을 PM 초안으로 정리한다. | 실제 Agent 출력 검증 전이라 close 불가 |
| 10 | Project `#47` | 실제 진행 중인데 Backlog인 항목의 Status 갱신 필요 여부를 점검한다. | Project 상태 변경은 PM 확인 후 별도 수행 필요 |

## 3. close 가능성 판정

| 이슈 | close 판정 | 근거 | close 전 확인할 것 |
|---|---|---|---|
| `#12` | 조건부 가능 | 화면 흐름 문서와 정적 HTML 산출물이 존재하고, 로그인/서비스 설명 진입, 챗봇, Supervisor, 결과/리포트 흐름이 문서에 반영되어 있다. | 이슈 범위를 문서 산출물로 한정한다는 사용자 승인 |
| `#11` | 보류 | WBS와 회의 기준 문서는 있으나 담당자별 최신 comment 수신, 누락 확인, Project 상태 갱신이 남아 있다. | 각 담당자 comment URL과 Project 상태 |
| `#13` | 보류 | 리스크 로그는 이번 주 데이터 계약 고정 기간 동안 계속 갱신되어야 한다. | `#22`, `#29`, `#40`, `#41`의 검증 필요 항목 정리 완료 |
| `#14` | 불가 | 정적 HTML은 있으나 실제 Google 로그인, 챗봇 라우팅, 화면 기능 구현은 확인되지 않았다. | 프론트 구현 또는 구현 범위 재정의 |
| `#22` | 불가 | 공통 envelope 초안은 있으나 노드별 `structured_result`가 팀원 입력에 의존한다. | 필주, 동혁, 재강, 주희 schema 수신 |
| `#27` | 불가 | 이의신청서 생성은 필주 분석 결과와 동혁 법률 근거가 선행되어야 한다. | `#23`, `#25`, `#26`, `#22` 산출물 |
| `#29` | 불가 | routing rule은 Agent schema와 화면 입력 구조가 확정되어야 한다. | `#22` 확정, 각 노드 input/output 수신 |
| `#40` | 불가 | 통합 시나리오는 정의되어 있으나 샘플 기반 실행 검증이 없다. | 고지서, 사고 설명, 영상/이미지, 법률 검색 샘플 |
| `#41` | 불가 | guardrail 기준은 있으나 실제 출력 대상으로 검증하지 않았다. | Agent/Supervisor 샘플 출력 |
| `#19`, `#42`, `#43` | 불가 | 최종 마무리 단계 이슈다. | 중간 발표 이후 최종 QA 단계 진입 |

## 4. 2026-06-26까지 PM 단독 마감 기준

| 날짜 | 마감 기준 |
|---|---|
| 2026-06-23 | `#11`, `#13`, `#40`에 최신 현황과 리스크가 정리되어 있어야 한다. |
| 2026-06-24 | 담당자 schema를 받은 범위만 `#22`, `#29`, `#27`에 병합하고, 미수신 항목은 `검증 필요`로 둔다. |
| 2026-06-25 | `#40`에 시나리오별 입력 샘플 확보 여부와 실행 가능 여부가 표시되어야 한다. |
| 2026-06-26 | close 후보는 `#12`만 조건부로 보고하고, 나머지는 보류/불가 사유를 명확히 남긴다. |

## 5. 최종 판단

현재 기준으로 사용자의 승인 없이 바로 close할 수 있는 이슈는 없다.

다만 `#12 docs-mvp-screen-and-process-flows`는 이슈 범위를 문서 산출물로 한정한다면 close 후보로 볼 수 있다. `#14`처럼 실제 기능 구현 성격이 있는 이슈는 정적 HTML이나 문서만으로 close하면 안 된다.
