# 스키마 수신 즉시 구현 준비 체크리스트

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-06-24 |
| 작성자 | `hi20260204-maker` |
| 문서 상태 | 구현 전 준비 체크리스트 |
| 적용 시점 | 담당자별 최종 schema와 sample output 수신 직후 |
| 기준 문서 | `docs/pm-api-json-schema-spec-2026-06-23.md`, `docs/screen-design-specification.md`, `docs/screen-design-ui-ux-flow-guide.md`, `docs/issues/40-cross-mvp-integration-scenarios.md`, `docs/final-demo-scenario-risk-checklist-2026-06-23.md` |

## 1. 목적

이 문서는 최종 schema가 수신되는 즉시 구현에 들어가기 위해 확인해야 할 항목을 정리한다. 현재 단계에서는 구현, endpoint 확정, UI 동작 로직 작성, Django/Agent 코드 작성, 화면에 맞춘 임의 field 보정을 하지 않는다.

핵심 원칙은 아래와 같다.

| 원칙 | 기준 |
|---|---|
| 확정 schema 우선 | PM 초안과 충돌하면 담당자 최종 schema와 sample output을 먼저 확인한다. |
| 문자열 추측 금지 | 챗봇 응답 문자열을 Frontend가 파싱해서 intent나 카드 유형을 추정하지 않는다. |
| Supervisor display output 기준 | 화면은 Agent raw output이 아니라 `GET /api/analysis/results/{id}/`의 병합 결과를 기준으로 만든다. |
| mock data 우선 | 실제 API 연결 전 mock data로 모든 화면 상태를 재현한다. |
| 단정 표현 금지 | 법률 판단, 과실비율 확정, 이의신청 성공 보장, 벌칙 회피 표현을 금지한다. |
| 구현 전 확인 | 문서에 없는 field, enum, endpoint, 화면 상태는 구현하지 않고 확인한다. |

## 2. 구현 착수 조건

아래 조건을 만족하기 전까지는 구현을 시작하지 않는다.

| 구분 | 착수 조건 |
|---|---|
| 공통 schema | Agent result envelope의 필수 field, `status` enum, `node_code` enum이 확정되어야 한다. |
| display output | `assistant_message`, `progress`, `cards`, `pending_questions`, `attachments`, `report_links` 구조가 확정되어야 한다. |
| 고지서 흐름 | `fine_notice_analysis`, `law_ground_search`, `objection_report_generation` sample output이 최소 1개 이상 있어야 한다. |
| 상태 분기 | `success`, `degraded`, `partial`, `failed`의 의미와 화면 처리가 확정되어야 한다. |
| 이의제기 분기 | `objection_possible: true/false/null` 처리 기준이 확정되어야 한다. |
| API 후보 | mock 구현이라도 사용할 endpoint 이름 또는 adapter 함수명이 확정되어야 한다. |
| 화면 범위 | 이번 구현에서 다룰 화면이 `UI-Ai-01`, `UI-REPORT-FINE-001`, `UI-REPORT-FAULT-001`, `UI-MY-001` 중 어디까지인지 확정되어야 한다. |

## 3. 수신 schema 검수 체크리스트

### 3.1 수신 metadata

| 확인 항목 | 기준 |
|---|---|
| 작성자와 담당 이슈 | schema 작성자, 연결 이슈 번호, 작성일을 확인한다. |
| 초안/확정 구분 | `초안`, `검증 필요`, `확정` 상태를 분리한다. |
| sample 포함 여부 | schema만 있고 sample output이 없으면 구현 착수 대상에서 제외한다. |
| PM 초안과 차이 | `docs/pm-api-json-schema-spec-2026-06-23.md`와 field명, enum, null 허용 여부 차이를 표로 기록한다. |
| 충돌 여부 | 같은 field를 서로 다른 타입으로 정의한 경우 구현 전에 확인한다. |

### 3.2 Supervisor display output

화면 구현의 1차 입력은 아래 구조여야 한다.

| Field | 확인 기준 | 화면 사용처 |
|---|---|---|
| `assistant_message.summary` | 대화 목록 preview와 결과 요약에 사용할 수 있어야 한다. | 상담 목록, 결과 상단 |
| `assistant_message.answer` | 사용자에게 보여줄 본문이다. 법률 단정 표현이 없어야 한다. | 챗봇 말풍선 |
| `assistant_message.limitations` | 빈 배열 가능. 근거 부족, sample 미검증, 법률 판단 제한을 표시한다. | 유의사항, 경고 카드 |
| `progress[].label` | 내부 Agent명이 아니라 사용자 언어로 표시 가능한 단계명이어야 한다. | 분석 상태 패널 |
| `progress[].status` | `done`, `waiting`, `failed` 중 하나인지 확인한다. | 상태 dot, 진행 단계 |
| `cards[].card_type` | `fine_notice`, `fault_ratio`, `law_ground`, `vision`, `objection_report` 중 하나인지 확인한다. | 카드 template 분기 |
| `cards[].metrics` | label/value/unit 구조인지 확인한다. 금액, 감경률, 신뢰도 표시 기준으로 사용한다. | 결과 카드, 상세 metric |
| `cards[].evidence_refs` | 첨부 파일, 법령 chunk, 사례 source와 연결되는지 확인한다. | 근거 보기, 파일 패널 |
| `pending_questions[]` | 부족 입력이 있으면 반드시 질문이 있어야 한다. | 추가 질문 UI |
| `attachments[]` | `attachment_id`, `label`, `purpose`가 화면 표시와 evidence 연결에 충분한지 확인한다. | 첨부 자료 카드 |
| `report_links[]` | 생성된 report가 없으면 빈 배열이어야 한다. | 리포트 저장/다운로드 |

### 3.3 Agent result envelope

| Field | 확인 기준 |
|---|---|
| `session_id` | message, job, result, report를 연결할 수 있어야 한다. |
| `message_id` | 사용자 입력과 Agent 결과를 연결해야 한다. |
| `job_id` | progress polling과 결과 조회를 연결해야 한다. |
| `node_name` | 개발 설명용이며 사용자 화면에는 직접 노출하지 않는다. |
| `node_code` | routing과 display 병합의 안정적인 key다. enum 확정 전 구현하지 않는다. |
| `status` | `success`, `partial`, `failed` 중 하나여야 한다. |
| `summary` | Supervisor 병합용 요약이다. 최종 사용자 답변으로 그대로 쓰지 않는다. |
| `structured_result` | 노드별 schema를 따른다. 비어 있으면 카드 생성 불가로 본다. |
| `evidence` | 빈 배열 가능하나, 근거가 없으면 `limitations`에 이유가 있어야 한다. |
| `next_actions` | 사용자 후속 행동 또는 버튼 후보로 쓸 수 있어야 한다. |
| `limitations` | 단정 방지와 품질 제한을 표시한다. |
| `missing_fields` | 부족 입력 질문과 연결되어야 한다. |

### 3.4 고지서·법령·이의신청 흐름

| 영역 | 반드시 확인할 field |
|---|---|
| 고지서 OCR | `notice_stage`, `ocr_status`, `fine_amount`, `issuing_authority`, `missing_fields`, `violation_text`, `law_code`, `violation_datetime`, `violation_location` |
| 고지 단계 | `notice_stage`는 `"사전통지"`, `"1차 고지서"`, `"2차 고지서"`, `"즉결심판"` 중 하나인지 확인한다. 영문 snake_case로 바꾸지 않는다. |
| OCR 상태 | `ocr_status`는 `"success"`, `"degraded"`, `"partial"`, `"failed"` 중 하나인지 확인한다. |
| 감경 판단 | `reduction_eligible`, `reduction_rate`, `applicable_reductions`, `inapplicable_reductions`를 확인한다. |
| 특별 감경 | `special_reduction`은 PM 결정 전까지 boolean/string/null 중 어떤 타입인지 확정되지 않으면 구현하지 않는다. |
| 이의제기 | `objection_possible`은 `boolean | null`이어야 한다. `null`은 즉결심판 출석 여부 확인 UI로 연결한다. |
| 법령 근거 | `matched_laws[].title`, `article`, `summary`, `source_ref`, `applicability_limit`를 확인한다. |
| 이의신청서 | `recipient_agency`, `case_summary`, `objection_purpose`, `grounds`, `attachment_list`, `disclaimer`, `missing_inputs`, `next_actions`를 확인한다. |

### 3.5 과실비율·Vision 흐름

| 영역 | 반드시 확인할 field |
|---|---|
| 사고 텍스트 분석 | `accident_type_candidates`, `issue_tags`, `evidence_tags`, `similar_cases`, `reliability_score`, `ratio_range_label`, `limitations` |
| 과실비율 표현 | 확정 수치가 아니라 정성 라벨, 쟁점, 유사 사례 중심인지 확인한다. |
| 유사 사례 | `source_type`, `source_ref`, `summary`, `similarity_score` 또는 이에 준하는 추적 field가 있어야 한다. |
| Vision 분석 | `media_type`, `observations`, `detected_objects`, `evidence_candidates`, `privacy_redaction_required`, `limitations` |
| 개인정보 | 얼굴, 차량번호, 주소, 연락처 등 원문 노출 방지 기준을 확인한다. |
| 품질 한계 | 영상 흐림, 프레임 누락, 객체 탐지 실패가 `limitations`에 들어가는지 확인한다. |

## 4. mock data 준비 체크리스트

확정 schema 수신 직후 아래 mock case를 먼저 만든다. 하나의 성공 case만 만들면 화면 분기 검증이 불가능하다.

| ID | 목적 | 필수 상태 |
|---|---|---|
| `MOCK-FINE-001` | 고지서 OCR 성공 | `notice_stage="사전통지"`, `ocr_status="success"`, `objection_possible=true` |
| `MOCK-FINE-002` | 일부 필드 재확인 | `ocr_status="degraded"`, 특정 `missing_fields` 존재 |
| `MOCK-FINE-003` | 중요 필드 누락 | `ocr_status="partial"`, `pending_questions` 존재 |
| `MOCK-FINE-004` | OCR 실패 | `ocr_status="failed"`, 재업로드 action 존재 |
| `MOCK-FINE-005` | 이의제기 불가 | `notice_stage="2차 고지서"`, `objection_possible=false` |
| `MOCK-FINE-006` | 즉결심판 조건부 | `notice_stage="즉결심판"`, `objection_possible=null` |
| `MOCK-LAW-001` | 법령 근거 있음 | `matched_laws`와 `source_ref` 존재 |
| `MOCK-LAW-002` | 법령 근거 부족 | `matched_laws=[]`, limitation과 추가 확인 action 존재 |
| `MOCK-OBJECTION-001` | 초안 생성 가능 | `draft`, `disclaimer`, `next_actions` 존재 |
| `MOCK-OBJECTION-002` | 사실관계 부족 | `missing_inputs=["user_facts"]`, 추가 질문 존재 |
| `MOCK-FAULT-001` | 사고 설명 기반 분석 | `accident_type_candidates`, `issue_tags`, `similar_cases` 존재 |
| `MOCK-FAULT-002` | 과실비율 근거 부족 | `limitations`, 추가 자료 요청 action 존재 |
| `MOCK-VISION-001` | 영상 분석 성공 | `observations`, `evidence_candidates`, `privacy_redaction_required` 존재 |
| `MOCK-VISION-002` | 영상 품질 낮음 | quality limitation, `status="partial"` |
| `MOCK-ERROR-001` | 파일 업로드 실패 | `error.code="invalid_file"`, 재시도 action |
| `MOCK-ERROR-002` | 권한 없음 | `error.code="auth_required"` 또는 `forbidden` |

## 5. 챗봇 입력 구분 체크리스트

| 입력 유형 | routing 확인 | 화면 처리 |
|---|---|---|
| 텍스트만 입력 | `routing_intent`가 `law_question`, `fault_ratio`, `general` 중 하나로 분류되는지 확인한다. | 추가 질문 또는 결과 카드 표시 |
| 고지서 이미지 | attachment `purpose="fine_notice"`로 연결되는지 확인한다. | 고지서 OCR 진행 상태 표시 |
| 사고 사진/영상 | attachment `purpose="accident_scene"` 또는 `evidence`로 연결되는지 확인한다. | Vision 진행 상태 표시 |
| 고지서 + 이의신청 요청 | `fine_notice_analysis` 후 `objection_report_generation`으로 이어지는지 확인한다. | 초안 생성 전 부족 입력 질문 |
| 사고 설명 + 영상 | `vision_media_analysis`와 `text_ml_case_search` 병합 순서를 확인한다. | 사고 장면 요약과 유사 사례 카드 |
| 복합 질문 | 우선 intent와 보조 intent를 분리할 수 있는지 확인한다. | 사용자에게 다음 진행 방향 선택 요청 |

## 6. 화면 반영 체크리스트

### 6.1 `UI-Ai-01` AI 교통 상담

| 영역 | 확인 기준 |
|---|---|
| 상담 목록 | `chat_sessions` 또는 mock session에서 `title`, `last_summary`, `status`, `updated_at` 표시 |
| 챗봇 답변 | `assistant_message.answer` 표시, `limitations`는 별도 유의사항으로 분리 |
| 결과 카드 | `cards[].card_type`별 template 분기 |
| 빠른 질문 | user_text 또는 `routing_intent` 후보로만 사용하고 schema를 우회하지 않음 |
| 첨부 자료 | `attachments[]`와 `evidence_refs` 연결 |
| 분석 상태 | `progress[]`로만 렌더링하고 내부 Agent명 직접 노출 금지 |
| 추가 질문 | `pending_questions[]`가 있으면 결과 생성보다 질문 UI 우선 |

### 6.2 `UI-REPORT-FINE-001` 과태료·범칙금 대응 리포트

| 영역 | 확인 기준 |
|---|---|
| 요약 metric | 금액, 기한, 이의제기 가능성, 필요 자료를 schema field에서 가져온다. |
| OCR 결과 | `notice_stage`, `ocr_status`, `violation_location`, `violation_text`, `missing_fields` 표시 |
| 이의제기 가능성 | `true`, `false`, `null`을 각각 다른 안내로 표시 |
| 다음 행동 | `next_actions` 또는 `cards[].actions` 기준으로 표시 |
| 초안 | `objection_report_generation.draft` 또는 report API 결과가 있을 때만 표시 |
| 면책 | `disclaimer`가 없으면 초안 다운로드 버튼을 노출하지 않는다. |

### 6.3 `UI-REPORT-FAULT-001` 사고 과실비율 분석 리포트

| 영역 | 확인 기준 |
|---|---|
| 사고 유형 | `accident_type_candidates` 기반으로 표시 |
| 주요 쟁점 | `issue_tags`와 `evidence_tags` 표시 |
| 유사 사례 | `similar_cases`와 source 추적 field 표시 |
| 과실비율 | 수치 확정 대신 `ratio_range_label` 또는 정성 라벨 표시 |
| Vision 근거 | `observations`, `evidence_candidates`를 텍스트 근거로 병합 |
| 한계 | confidence 낮음, 근거 부족, 영상 품질 문제를 별도 표시 |

### 6.4 `UI-MY-001` 내 사건

| 영역 | 확인 기준 |
|---|---|
| 최근 상담 | session과 report 저장 여부가 연결되어야 한다. |
| 기한 임박 | 고지서 기한 field가 없으면 임의 D-day를 계산하지 않는다. |
| 리포트 목록 | `report_links` 또는 `GET /api/reports/` mock 기준으로 표시한다. |
| 권한 없음 | 비회원/로그인 정책 확정 전에는 구현하지 않고 mock 상태로만 둔다. |

## 7. 예상 파일 배치

확정 schema 수신 후 구현에 들어갈 때의 후보 위치다. 실제 생성은 구현 승인 후 진행한다.

| 위치 | 책임 |
|---|---|
| `app/schemas/` | 화면 표시용 DTO, Supervisor display output schema, API response type |
| `app/services/` | mock data provider, API adapter, response normalization |
| `app/web/` | 챗봇, 결과 카드, 리포트 화면 component |
| `ai/schemas/` | Agent result envelope, evidence metadata, node별 structured_result schema |
| `test/unit/` | schema validation, routing 분기, card mapping 단위 테스트 |
| `test/manual_scenarios/` | `INT-001`~`INT-006` 수동 검증 기록 |

현재 저장소에는 `app/screen-design-mvp-flow.html` 정적 목업만 있으므로, 구현 착수 시 기존 HTML을 바로 수정할지 별도 web 구조를 만들지는 먼저 확인해야 한다.

## 8. 검증 체크리스트

구현 후 완료 판정은 아래 검증을 통과해야 한다.

| 검증 | 기준 |
|---|---|
| schema validation | mock data가 확정 schema를 모두 만족해야 한다. |
| card mapping | 모든 `card_type`이 화면 template에 연결되어야 한다. |
| 상태 분기 | `success`, `degraded`, `partial`, `failed` 화면이 모두 재현되어야 한다. |
| pending question | 부족 입력이 있으면 결과 카드보다 추가 질문이 우선 표시되어야 한다. |
| guardrail | 금지 표현이 mock 답변과 UI 문구에 없어야 한다. |
| evidence 연결 | `evidence_refs`가 첨부 파일 또는 source metadata와 연결되어야 한다. |
| 반응형 | 데스크톱/모바일에서 텍스트 겹침과 버튼 overflow가 없어야 한다. |
| 인코딩 | 문서, HTML, JSON mock이 UTF-8로 저장되고 한글이 깨지지 않아야 한다. |

## 9. 이슈 코멘트 업데이트 기준

schema 수신 후 아래 이슈에는 구현 전 상태 업데이트를 남긴다.

| 이슈 | 업데이트 내용 |
|---|---|
| `#22` | 공통 Agent envelope과 node별 `structured_result` 수신/충돌/미수신 항목 |
| `#23` | 고지서 OCR input/output, `ocr_status`, `missing_fields`, sample 검증 상태 |
| `#24` | 감경/벌칙/법적 위험 field와 guardrail 적용 기준 |
| `#25` | 과태료·범칙금 상세 화면 표시 field와 `notice_stage` 기준 |
| `#26` | 고지서 흐름 law search와 법령 metadata/source 경계 |
| `#27` | 이의신청서 생성 조건, 부족 입력, draft/disclaimer sample |
| `#29` | Supervisor routing, display output, `pending_questions`, progress 상태 |
| `#40` | `INT-001`~`INT-006` mock/sample 기반 실행 가능 여부 |
| `#41` | 금지 표현, limitation, evidence, 개인정보 마스킹 검증 결과 |

## 10. 구현 전 최종 확인 질문

schema가 들어오면 구현 전에 아래 질문만 먼저 확인한다.

1. 이번 1차 구현 범위는 `UI-Ai-01` 챗봇과 `UI-REPORT-FINE-001` 과태료 리포트까지인가, 아니면 과실비율/Vision까지 포함하는가?
2. mock data는 별도 JSON 파일로 둘 것인가, 화면 코드 안의 fixture로 둘 것인가?
3. 기존 `app/screen-design-mvp-flow.html`을 개선할 것인가, 아니면 `app/web/` 하위에 새 구조를 만들 것인가?

## 11. 남은 리스크

| 리스크 | 영향 | 처리 |
|---|---|---|
| 담당자 schema와 PM 초안 충돌 | 구현 로직 재작업 가능 | 충돌 표 작성 후 확인 전 구현 보류 |
| sample output 없음 | 화면 상태 검증 불가 | mock 생성 전 담당자 sample 요청 |
| API endpoint 미확정 | adapter 경계 흔들림 | mock provider와 API adapter를 분리 |
| `special_reduction` 타입 미확정 | 감경 카드 분기 오류 | 타입 확정 전 화면 표시 보류 |
| 과실비율 evidence schema 미수신 | 과실비율 화면 단정 위험 | 정성 라벨과 limitation만 표시 |
| Vision privacy sample 미수신 | 개인정보 노출 위험 | 원문 이미지/영상 화면 노출 보류 |
| 비회원 정책 미확정 | 저장/권한/파일 보관 처리 변경 | 인증/인가 구현 보류 |
