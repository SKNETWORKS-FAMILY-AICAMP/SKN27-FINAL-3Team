# PM API JSON Schema 명세서 - Agent/Supervisor 입출력 계약 초안

작성일: 2026-06-23  
작성자: hi20260204-maker  
공유 대상: PM, Django Backend(`hi20260204-maker`), Frontend, Supervisor Agent, 각 Agent 담당자  
근거 문서: `docs/hi20260204-maker-sequential-action-plan-2026-06-23.md`

## 1. 문서 목적과 상태

이 문서는 각 담당자가 어떤 JSON 값을 주고받아야 하는지 확인하기 위한 API 명세서 형식의 PM 초안이다. 구현 확정 문서가 아니며, 담당자별 최종 output schema와 실제 Agent sample output이 수신되기 전까지 `검증 필요` 상태로 둔다.

이 문서는 아래 범위를 다룬다.

| 구분 | 포함 범위 | 상태 |
|---|---|---|
| 사용자 입력 API | 텍스트, 이미지, 영상, 문서 첨부를 분리해서 Supervisor로 넘기는 계약 | PM 초안 |
| Supervisor input | Django에서 Supervisor Agent로 넘기는 JSON 패키지 | PM 초안 |
| Supervisor analysis plan | Agent 호출 전 입력 검증, 실행 순서, fallback 조건을 담는 내부 계획 | PM 초안 |
| Agent result envelope | 모든 Agent가 공통으로 반환해야 하는 wrapper JSON | PM 초안 |
| Agent별 structured_result | 각 Agent가 envelope 안에 넣어야 하는 핵심 결과 JSON | 담당자 확인 필요 |
| Supervisor display output | LLM 답변과 HTML 화면설계서 결과 카드에 뿌릴 JSON | PM 초안 |
| 이의신청서 초안 API | 고지서 분석, 법령 근거, 사용자 사실관계를 묶어 문서 초안을 생성하는 계약 | PM 초안 |
| 저장소 매핑 | PostgreSQL, Redis, Neo4j/RAG의 데이터 책임 경계 | PM 초안 |

### 1.1 필드 표기 기준

| 표기 | 의미 | 처리 기준 |
|---|---|---|
| 필수 | 항상 있어야 하는 값 | 없으면 API 400 또는 Agent 결과 `partial/failed` |
| 조건부 필수 | 특정 intent, 파일 유형, 선행 분석 결과가 있을 때 필수 | 조건을 만족하는데 없으면 추가 질문 또는 분석 보류 |
| 선택 | 있으면 품질이 좋아지지만 없어도 기본 흐름은 가능 | 없으면 `limitations` 또는 `missing_fields`에 기록 |
| 검증 필요 | PM이 현재 문서와 이슈 기준으로 지정한 초안 | 담당자 최종 schema와 sample output 수신 후 확정 |

### 1.2 공통 enum 초안

| Enum | 값 | 사용 위치 |
|---|---|---|
| `routing_intent` | `fine_notice`, `law_question`, `fault_ratio`, `vision_analysis`, `objection_request`, `general` | 입력 분류, Supervisor routing, analysis job |
| `input_modalities` | `text`, `image`, `video`, `document` | 사용자 입력 분리 |
| `attachment.purpose` | `fine_notice`, `accident_scene`, `accident_statement`, `evidence`, `unknown` | 파일 routing 보조. `accident_statement`는 사고경위서 OCR/문서인식 흐름으로 넘기기 위한 라우팅 힌트다. |
| `job.status` | `queued`, `running`, `success`, `partial`, `failed` | 분석 job 진행 상태 |
| `agent.status` | `success`, `partial`, `failed` | Agent 결과 envelope |
| `card_type` | `fine_notice`, `fault_ratio`, `law_ground`, `vision`, `objection_report` | 화면 결과 카드 |
| `analysis_step.status` | `ready`, `blocked`, `running`, `success`, `partial`, `failed`, `skipped` | `analysis_plan.steps[]`, 진행 상태 |
| `error.code` | `auth_required`, `forbidden`, `missing_required_field`, `invalid_file`, `analysis_failed` | API 오류 응답 |

## 2. 공통 API 오류 응답

모든 API는 실패 시 아래 형태를 우선 사용한다.

```json
{
  "error": {
    "code": "auth_required|forbidden|missing_required_field|invalid_file|analysis_failed",
    "message": "사용자에게 보여줄 수 있는 오류 요약",
    "missing_fields": ["session_id"],
    "retryable": false
  }
}
```

| Field | 필수성 | Type/Allowed | 왜 필요한가 | 사용 위치와 누락 시 처리 |
|---|---|---|---|---|
| `error.code` | 필수 | enum | Frontend가 오류별 UI를 분기해야 한다. | 없으면 공통 오류 카드만 표시 가능하므로 API 응답 실패로 본다. |
| `error.message` | 필수 | string | 사용자에게 현재 상태를 설명해야 한다. | 없으면 FE 기본 문구로 대체하되 BE 응답은 불완전하다. |
| `error.missing_fields` | 조건부 필수 | string[] | 필수 입력이 부족할 때 어떤 값을 보완해야 하는지 알려준다. | `missing_required_field`인데 없으면 추가 질문 생성이 어렵다. |
| `error.retryable` | 필수 | boolean | 재시도 버튼 노출 여부를 결정한다. | 없으면 기본값 `false`로 처리한다. |

## 3. 사용자 메시지 입력 API

### 3.1 `POST /api/chat/messages/`

사용자 텍스트와 첨부 metadata를 받아 Supervisor input으로 변환하는 시작점이다.

#### Request JSON

```json
{
  "session_id": "ses_20260623_0001",
  "user_text": "이 고지서 이의신청서 만들어줘",
  "attachments": [
    {
      "attachment_id": "att_0001",
      "type": "image",
      "purpose": "fine_notice",
      "original_filename": "notice.jpg",
      "mime_type": "image/jpeg",
      "privacy_risk": true
    }
  ]
}
```

#### Response JSON

```json
{
  "message_id": "msg_0001",
  "routing_intent": "objection_request",
  "job_id": "job_0001",
  "status": "queued",
  "pending_questions": [
    {
      "field": "user_facts",
      "question": "이의신청 사유와 당시 상황을 입력해 주세요."
    }
  ]
}
```

#### Request field schema

| Field | 필수성 | Type/Allowed | 왜 필요한가 | 사용 위치와 누락 시 처리 |
|---|---|---|---|---|
| `session_id` | 필수 | string | 메시지를 기존 대화, 파일, 분석 job과 연결한다. | PostgreSQL `messages`, Redis session state. 없으면 400. |
| `user_text` | 조건부 필수 | string | 법령 질문, 사고 설명, 이의신청 사유 등 텍스트 기반 routing에 필요하다. | 첨부만 있는 경우 허용 가능하지만 intent가 불명확하면 추가 질문. |
| `attachments` | 선택 | object[] | 이미지, 영상, 문서 입력을 Supervisor가 routing할 수 있게 한다. | 없으면 텍스트 기반 intent만 처리한다. |
| `attachments[].attachment_id` | 조건부 필수 | string | 업로드 API 결과와 메시지를 연결한다. | 첨부가 있는데 없으면 400 또는 첨부 무시. |
| `attachments[].type` | 조건부 필수 | enum: image/video/document | Vision, OCR, 문서 처리 노드 분기에 필요하다. | 첨부가 있는데 없으면 `invalid_file`. |
| `attachments[].purpose` | 선택 | enum | 고지서, 사고 장면, 사고경위서 같은 문서형 입력, 증빙 자료를 구분한다. | 없으면 Supervisor가 추정하되 `limitations`에 기록. |
| `attachments[].original_filename` | 선택 | string | 사용자 확인, 파일 목록 표시, audit에 필요하다. | 없으면 내부 파일명만 사용한다. |
| `attachments[].mime_type` | 조건부 필수 | string | 허용 파일 검사와 처리 노드 결정에 필요하다. | 첨부가 있는데 없거나 불일치하면 `invalid_file`. |
| `attachments[].privacy_risk` | 필수 | boolean | 개인정보 포함 가능성을 표시해 masking/보관 정책에 연결한다. | 없으면 안전하게 `true`로 간주하고 제한 표시. |

#### Response field schema

| Field | 필수성 | Type/Allowed | 왜 필요한가 | 사용 위치와 누락 시 처리 |
|---|---|---|---|---|
| `message_id` | 필수 | string | 화면 메시지, job, 결과를 같은 사용자 입력에 연결한다. | 없으면 FE가 상태를 매핑할 수 없으므로 실패. |
| `routing_intent` | 필수 | enum | Supervisor가 어떤 분석 흐름을 시작했는지 표시한다. | 없으면 진행 상태와 카드 분기 불가. |
| `job_id` | 조건부 필수 | string/null | 비동기 분석이 필요할 때 진행 상태 조회에 사용한다. | 단순 안내 응답이면 null 가능, 분석이면 필수. |
| `status` | 필수 | enum | 화면 진행 상태를 표시한다. | 없으면 `queued`로 추정하지 말고 API 오류로 본다. |
| `pending_questions` | 필수 | object[] | 필수 입력이 부족할 때 사용자에게 되묻는다. | 없으면 빈 배열. 부족 입력이 있는데 빈 배열이면 schema 검증 실패. |

## 4. 파일 업로드 API

### 4.1 `POST /api/files/`

고지서 이미지, 사고 영상, 증빙 문서 파일을 저장하고 분석 가능한 metadata를 반환한다. 실제 파일 전송은 multipart가 될 수 있으나, API 명세에서는 metadata JSON을 기준으로 설명한다.

> 2026-06-27 Django mock 구현 메모:
> 중간발표용 backend는 운영 후보 `/api/files/` 대신 `POST /api/mock/attachments/`, `GET /api/mock/attachments/`, `GET /api/mock/attachments/{attachment_id}/`를 제공한다. multipart 파일은 `backend/media/mock_uploads/`에 임시 저장하고, JSON metadata-only 등록도 허용한다. 응답의 `attachment.agent_handoff`를 `attachments[]` 입력으로 넘겨 Supervisor/Agent handoff를 검증한다.
> `POST /api/mock/chat/messages/`와 `POST /api/mock/agents/plans/run/`는 `attachments=[{"attachment_id":"att_..."}]`만 받아도 저장된 mock metadata를 조회해 `purpose`, `type`, `storage_uri`, `content_type`, `size_bytes`를 자동 보강한다. 조회 실패 시 `attachment_resolution.unresolved_attachment_ids`와 `limitations`에 남긴다.

#### Request metadata JSON

```json
{
  "session_id": "ses_20260623_0001",
  "purpose": "fine_notice",
  "file": {
    "original_filename": "notice.jpg",
    "mime_type": "image/jpeg",
    "size_bytes": 394820
  }
}
```

#### Response JSON

```json
{
  "attachment_id": "att_0001",
  "file_type": "image",
  "purpose": "fine_notice",
  "privacy_risk": true,
  "status": "stored"
}
```

#### Mock response JSON

```json
{
  "attachment": {
    "attachment_id": "att_0001",
    "session_id": "ses_20260623_0001",
    "purpose": "fine_notice",
    "type": "image",
    "original_filename": "notice.jpg",
    "content_type": "image/jpeg",
    "size_bytes": 394820,
    "storage_uri": "mock://uploads/att_0001/notice.jpg",
    "status": "uploaded",
    "agent_handoff": {
      "attachment_id": "att_0001",
      "purpose": "fine_notice",
      "type": "image",
      "storage_uri": "mock://uploads/att_0001/notice.jpg",
      "content_type": "image/jpeg",
      "size_bytes": 394820
    },
    "limitations": ["mock local storage"]
  }
}
```

| Field | 필수성 | Type/Allowed | 왜 필요한가 | 사용 위치와 누락 시 처리 |
|---|---|---|---|---|
| `session_id` | 필수 | string | 업로드 파일을 대화와 소유자 권한에 연결한다. | 없으면 400. |
| `purpose` | 선택 | enum | 고지서 OCR, 사고 분석, 사고경위서 OCR/문서인식, 증빙 분류에 도움을 준다. | 없으면 `unknown`, Supervisor가 추정. |
| `file.original_filename` | 필수 | string | 사용자 파일 목록과 audit에 필요하다. | 없으면 업로드 실패 처리. |
| `file.mime_type` | 필수 | string | 이미지/영상/문서 허용 여부를 검사한다. | 허용되지 않으면 `invalid_file`. |
| `file.size_bytes` | 필수 | integer | 파일 크기 제한과 보관 정책에 필요하다. | 없으면 업로드 실패 처리. |
| `attachment_id` | 필수 | string | 메시지 API에서 첨부를 참조한다. | 없으면 다음 단계로 전달 불가. |
| `file_type` | 필수 | enum | Supervisor input의 `input_modalities`로 변환된다. | 없으면 routing 불가. |
| `privacy_risk` | 필수 | boolean | 개인정보 보호, masking, 보관 제한에 필요하다. | 없으면 `true`로 간주. |
| `status` | 필수 | string | 업로드 완료 여부를 FE에 표시한다. | 없으면 업로드 성공으로 처리하지 않는다. |
| `storage_uri` | 조건부 필수 | string | Agent adapter가 실제 파일 또는 object storage 위치를 참조한다. | mock은 `mock://...`, 운영은 object storage URI 후보. |
| `agent_handoff` | 조건부 필수 | object | Supervisor/Agent 호출에 넘길 최소 첨부 metadata다. | mock backend에서 우선 제공한다. |

## 5. Supervisor input package

Django service layer가 사용자 메시지와 파일 metadata를 정리해 Supervisor Agent에 넘기는 내부 JSON이다.

```json
{
  "session_id": "ses_20260623_0001",
  "user_id": "usr_0001",
  "user_text": "이 고지서 이의신청서 만들어줘",
  "input_modalities": ["text", "image"],
  "attachments": [
    {
      "attachment_id": "att_0001",
      "type": "image",
      "purpose": "fine_notice",
      "original_filename": "notice.jpg",
      "mime_type": "image/jpeg",
      "privacy_risk": true
    }
  ],
  "routing_intent": "objection_request",
  "missing_inputs": ["user_facts"],
  "limitations": ["고지서 OCR 결과가 아직 확정되지 않았습니다."]
}
```

| Field | 필수성 | Type/Allowed | 왜 필요한가 | 사용 위치와 누락 시 처리 |
|---|---|---|---|---|
| `session_id` | 필수 | string | 대화, 파일, job, 결과를 하나의 흐름으로 묶는다. | 없으면 Supervisor 호출 불가. |
| `user_id` | 조건부 필수 | string/null | 로그인 사용자 권한 검사와 리포트 소유자 연결에 필요하다. | 비회원 정책이 확정되지 않았으면 null 허용 여부는 검증 필요. |
| `user_text` | 조건부 필수 | string | 텍스트 intent와 LLM 답변 생성에 필요하다. | 텍스트가 필요한 intent에서 없으면 추가 질문. |
| `input_modalities` | 필수 | string[] | 텍스트/이미지/영상/문서 처리 노드를 결정한다. | 없으면 routing 불가. |
| `attachments` | 필수 | object[] | 첨부가 없어도 빈 배열로 유지해 parser를 단순화한다. | 누락되면 빈 배열로 보정 가능하나 schema에는 필수. |
| `routing_intent` | 필수 | enum | 어떤 Agent 흐름을 호출할지 결정한다. | 없으면 Supervisor가 intent 판정부터 수행해야 하며 job 생성 보류. |
| `missing_inputs` | 필수 | string[] | Agent 호출 전 부족한 입력을 명시한다. | 없으면 추가 질문 카드 생성 불가. |
| `limitations` | 필수 | string[] | 개인정보, 입력 품질, 근거 부족을 사용자에게 표시한다. | 없으면 빈 배열. |

### 5.1 Supervisor `analysis_plan` package

Supervisor는 사용자 입력을 바로 Agent에 넘기지 않고, 먼저 실행 가능한 호출 계획을 만든다. 이 계획은 내부 상태가 기본이며, 화면에는 `progress`, `pending_questions`, `limitations`로 변환해서 보여준다.

```json
{
  "plan_id": "plan_0001",
  "session_id": "ses_20260623_0001",
  "message_id": "msg_0001",
  "routing_intent": "objection_request",
  "input_summary": {
    "has_user_command": true,
    "modalities": ["text", "image"],
    "attachment_purposes": ["fine_notice"]
  },
  "required_inputs": ["fine_notice_image", "user_facts"],
  "pending_questions": [
    {
      "field": "user_facts",
      "question": "이의신청 사유와 당시 상황을 입력해 주세요."
    }
  ],
  "steps": [
    {
      "order": 1,
      "node_code": "fine_notice_analysis",
      "status": "ready",
      "required_inputs": ["attachments[purpose=fine_notice]"],
      "depends_on": [],
      "fallback": "missing_input_question"
    },
    {
      "order": 2,
      "node_code": "law_ground_search",
      "status": "blocked",
      "required_inputs": ["law_code|violation_text"],
      "depends_on": ["fine_notice_analysis"],
      "fallback": "semantic_search_or_limitations"
    },
    {
      "order": 3,
      "node_code": "objection_report_generation",
      "status": "blocked",
      "required_inputs": ["notice_analysis_result", "law_ground_result", "user_facts"],
      "depends_on": ["fine_notice_analysis", "law_ground_search"],
      "fallback": "pending_questions"
    }
  ],
  "blocked_reason": "user_facts가 없어 초안 생성은 보류합니다.",
  "limitations": []
}
```

| Field | 필수성 | Type/Allowed | 왜 필요한가 | 사용 위치와 누락 시 처리 |
|---|---|---|---|---|
| `plan_id` | 필수 | string | 한 메시지 안에서 호출 계획과 실행 결과를 추적한다. | 없으면 progress와 Agent result 연결이 어렵다. |
| `session_id` | 필수 | string | 대화와 권한 경계를 유지한다. | 없으면 Supervisor 실행 보류. |
| `message_id` | 필수 | string | 사용자 입력과 계획을 연결한다. | 없으면 결과 재조회 시 추적 불가. |
| `routing_intent` | 필수 | enum | 어떤 분석 흐름을 계획했는지 표시한다. | 없으면 계획 생성 실패로 본다. |
| `input_summary` | 필수 | object | 명령문, 첨부, modality를 요약한다. | 없으면 디버깅과 화면 진행 문구 생성이 어렵다. |
| `required_inputs` | 필수 | string[] | 전체 흐름에서 필요한 입력을 표시한다. | 없으면 부족 입력 판단 불가. |
| `pending_questions` | 필수 | object[] | 부족 입력이 있을 때 사용자에게 되물을 질문이다. | 없으면 빈 배열. |
| `steps[]` | 필수 | object[] | 실행할 Agent와 순서를 정의한다. | 비어 있으면 Agent 호출 없이 일반 답변 또는 보류. |
| `steps[].node_code` | 필수 | string | Agent result envelope의 `node_code`와 맞춘다. | 알 수 없는 node면 해당 step은 `skipped`. |
| `steps[].status` | 필수 | enum | 호출 가능, 대기, 실패, 생략 상태를 표시한다. | 없으면 `blocked`로 처리하고 확인 필요. |
| `steps[].depends_on` | 필수 | string[] | 선행 Agent 결과 의존성을 표시한다. | 없으면 빈 배열. |
| `steps[].fallback` | 선택 | string/null | 실패 또는 입력 부족 시 다음 행동을 정한다. | 없으면 Supervisor가 `limitations`에 기록. |
| `blocked_reason` | 선택 | string/null | 계획 전체가 실행 보류된 이유를 설명한다. | 없으면 실행 가능으로 본다. |
| `limitations` | 필수 | string[] | 입력 품질, 권한, 근거 부족 한계를 표시한다. | 없으면 빈 배열. |

## 6. 분석 job API

### 6.1 `POST /api/analysis/jobs/`

Supervisor 분석 job을 생성한다.

> 2026-06-27 Django mock 구현 메모:
> 중간발표용 backend는 운영 후보 `/api/analysis/jobs/` 대신 `POST /api/mock/analysis/jobs/`, `GET /api/mock/analysis/jobs/`, `GET /api/mock/analysis/jobs/{job_id}/`를 제공한다. mock job은 실제 queue, Redis, DB 없이 `backend/media/mock_analysis_jobs/{job_id}/job.json`에 저장하며, 하나의 `job_id` 아래 `chat_response`, `analysis_plan`, `node_execution`, `history`를 묶는다.

#### Request JSON

```json
{
  "session_id": "ses_20260623_0001",
  "message_id": "msg_0001",
  "routing_intent": "fine_notice"
}
```

#### Response JSON

```json
{
  "job_id": "job_0001",
  "status": "queued",
  "active_node": "fine_notice_analysis",
  "progress_message": "고지서 분석을 준비 중입니다."
}
```

| Field | 필수성 | Type/Allowed | 왜 필요한가 | 사용 위치와 누락 시 처리 |
|---|---|---|---|---|
| `session_id` | 필수 | string | job과 대화 권한을 연결한다. | 없으면 400. |
| `message_id` | 필수 | string | 어떤 사용자 입력에서 시작된 job인지 연결한다. | 없으면 결과 추적 불가. |
| `routing_intent` | 필수 | enum | 시작할 Supervisor route를 결정한다. | 없으면 job 생성 보류. |
| `job_id` | 필수 | string | 진행 상태 조회와 결과 조회의 기준이다. | 없으면 job 생성 실패. |
| `status` | 필수 | enum | FE 진행 상태와 Redis progress key에 필요하다. | 없으면 `queued`로 임의 보정하지 않는다. |
| `active_node` | 조건부 필수 | string/null | 현재 실행 중인 Agent node를 표시한다. | 단순 대기 상태면 null 가능. |
| `progress_message` | 선택 | string | 사용자에게 현재 분석 단계를 알려준다. | 없으면 FE 기본 진행 문구 사용. |

### 6.2 `GET /api/analysis/jobs/{id}/`

분석 job의 진행 상태를 조회한다.

```json
{
  "job_id": "job_0001",
  "status": "running",
  "active_node": "law_ground_search",
  "progress_message": "관련 법령 근거를 확인 중입니다.",
  "updated_at": "2026-06-23T10:45:00+09:00"
}
```

| Field | 필수성 | Type/Allowed | 왜 필요한가 | 사용 위치와 누락 시 처리 |
|---|---|---|---|---|
| `job_id` | 필수 | string | polling 대상과 응답이 일치하는지 확인한다. | 없으면 FE가 응답을 폐기한다. |
| `status` | 필수 | enum | 진행, 완료, 실패 UI를 결정한다. | 없으면 job 상태 조회 실패. |
| `active_node` | 선택 | string/null | 어떤 Agent가 실행 중인지 표시한다. | 없으면 단계명 숨김. |
| `progress_message` | 선택 | string | 사용자에게 단계별 상태를 표시한다. | 없으면 기본 문구 사용. |
| `updated_at` | 필수 | ISO datetime | Redis progress가 최신인지 판단한다. | 없으면 cache stale 여부 판단 불가. |

## 7. Agent Result Envelope

모든 Agent는 아래 공통 envelope 안에 자신의 `structured_result`를 넣어 반환한다. Supervisor는 raw output을 그대로 화면에 뿌리지 않고 이 envelope을 병합한다.

```json
{
  "session_id": "ses_20260623_0001",
  "message_id": "msg_0001",
  "job_id": "job_0001",
  "node_name": "고지서 OCR 및 과태료 분석",
  "node_code": "fine_notice_analysis",
  "status": "success",
  "summary": "속도위반 과태료 고지서로 추정됩니다.",
  "structured_result": {},
  "evidence": [
    {
      "source_type": "uploaded_file",
      "source_id": "att_0001",
      "quote": "제한속도 60km/h, 측정속도 78km/h"
    }
  ],
  "next_actions": ["감경 가능 여부를 확인합니다."],
  "limitations": [],
  "missing_fields": []
}
```

| Field | 필수성 | Type/Allowed | 왜 필요한가 | 사용 위치와 누락 시 처리 |
|---|---|---|---|---|
| `session_id` | 필수 | string | 결과를 대화와 권한에 연결한다. | 없으면 저장 불가. |
| `message_id` | 필수 | string | 사용자 질문과 결과를 연결한다. | 없으면 메시지별 결과 표시 불가. |
| `job_id` | 필수 | string | 분석 job과 결과를 연결한다. | 없으면 progress/result 조회 연결 불가. |
| `node_name` | 필수 | string | 사람이 읽는 Agent 단계명이다. | 없으면 FE 단계 표시 품질 저하. |
| `node_code` | 필수 | string | Supervisor 병합과 API 분기에 사용하는 안정적인 식별자다. | 없으면 Agent 결과 식별 불가. |
| `status` | 필수 | enum | 성공, 부분 성공, 실패 처리를 결정한다. | 없으면 실패로 처리. |
| `summary` | 필수 | string | LLM 최종 답변과 카드 요약에 사용된다. | 없으면 카드 생성 불완전. |
| `structured_result` | 필수 | object | 화면 카드, 상세 화면, 리포트 생성의 핵심 데이터다. | 없으면 Supervisor 병합 불가. |
| `evidence` | 필수 | object[] | 근거 표시와 단정 방지에 필요하다. | 없으면 빈 배열 가능하나 `limitations`에 근거 부족 표시. |
| `next_actions` | 필수 | string[] | 사용자에게 다음 단계 버튼/안내를 제공한다. | 없으면 빈 배열. |
| `limitations` | 필수 | string[] | 입력 품질, 법률 판단 한계, 근거 부족을 표시한다. | 없으면 빈 배열. |
| `missing_fields` | 필수 | string[] | 부분 성공 시 필요한 보완 입력을 전달한다. | 없으면 빈 배열. |

## 8. Agent별 structured_result schema 초안

### 8.1 `fine_notice_analysis`

고지서 OCR, 과태료/범칙금 분석 결과다. 이의신청서 생성의 선행 입력으로도 사용된다.

```json
{
  "notice_stage": "사전통지",
  "law_code": "ROAD_TRAFFIC_ACT_ARTICLE_160",
  "violation_text": "제한속도 위반",
  "ocr_status": "success",
  "fine_amount": 40000,
  "issuing_authority": "서울특별시",
  "missing_fields": [],
  "prepayment_amount": 32000,
  "violation_datetime": "2026-06-20T14:30:00+09:00",
  "violation_location": "서울시 중구",
  "demerit_points_base": 15,
  "demerit_points_accumulated": null,
  "name": "홍길동",
  "vehicle_number": "12가3456"
}
```

| Field | 필수성 | Type/Allowed | 왜 필요한가 | 사용 위치와 누락 시 처리 |
|---|---|---|---|---|
| `notice_stage` | 필수 | enum: `"사전통지"` / `"1차 고지서"` / `"2차 고지서"` / `"즉결심판"` | 사전통지, 본고지, 독촉고지, 즉결심판 단계를 구분한다. | 결과 카드와 이의신청 가능성 판단. 영문 snake_case는 사용하지 않는다. 없으면 `partial`. |
| `law_code` | 조건부 필수 | string | 법령 검색 exact 입력으로 사용된다. | 없으면 `violation_text` semantic 검색으로 대체. 둘 다 없으면 추가 질문. |
| `violation_text` | 조건부 필수 | string | 법령/사례 검색의 semantic 입력이다. | `law_code`도 없으면 law search 보류. |
| `ocr_status` | 필수 | enum: `"success"` / `"degraded"` / `"partial"` / `"failed"` | OCR 신뢰 상태를 표시한다. | `degraded`는 일부 중요 필드만 재확인하고, `partial`은 전체 보완 입력 또는 fallback을 요청한다. |
| `fine_amount` | 필수 | number | 과태료/범칙금 카드 핵심 금액이다. | 없으면 금액 카드 표시 불가, `missing_fields` 기록. |
| `issuing_authority` | 필수 | string | 제출 기관과 문의 기관 판단에 필요하다. | 이의신청서 `recipient_agency` 생성 보류. |
| `missing_fields` | 필수 | string[] | OCR로 못 읽은 필드를 명시한다. | 없으면 빈 배열. |
| `prepayment_amount` | 선택 | number/null | 사전납부 감경 금액 표시. | 없으면 감경 카드 생략. |
| `violation_datetime` | 선택 | ISO datetime/null | 사건 요약과 증빙 비교에 필요하다. | 없으면 이의신청서에 날짜 보완 질문. |
| `violation_location` | 선택 | string/null | 사건 요약과 블랙박스/지도 증빙 연결에 필요하다. | 없으면 위치 보완 질문. |
| `demerit_points_base` | 선택 | number/null | 벌점 안내에 필요하다. | 없으면 벌점 카드 생략. |
| `demerit_points_accumulated` | 선택 | number/null | 누적 벌점 안내에 필요하다. | 없으면 누적 판단 생략. |
| `name` | 선택 | string/null | 고지서 대상자 표시. | 개인정보 masking 정책에 따라 표시 제한. |
| `vehicle_number` | 선택 | string/null | 차량 식별과 고지서 확인에 필요하다. | 없으면 사용자 확인 질문. |

#### `notice_stage` 허용값

| 값 | 의미 | 이의 방식 |
|---|---|---|
| `"사전통지"` | 과태료 확정 전 또는 범칙금 통고처분서 전체 | 의견제출 |
| `"1차 고지서"` | 과태료 확정 후 납부 고지 | 기한 내 이의신청 |
| `"2차 고지서"` | 과태료 독촉고지서 | 이의제기 불가, 납부만 가능 |
| `"즉결심판"` | 즉결심판 출석통지서 | 출석 여부에 따라 조건부 |

#### `ocr_status` 처리 기준

| 값 | 의미 | Frontend 처리 |
|---|---|---|
| `"success"` | Critical 필드와 Important 필드를 모두 인식 | 그대로 진행 |
| `"degraded"` | Critical 필드는 있으나 Important 필드 일부 누락 | 누락된 특정 필드만 인라인 재확인 |
| `"partial"` | Critical 필드 누락 | 전체 보완 입력 또는 자연어 입력 fallback 요청 |
| `"failed"` | JSON 파싱 실패 또는 OCR 실패 | 이미지 재업로드 요청 |

### 8.2 `law_ground_search`

법령, 감경, 처분 판단 결과다. 고지서 분석 후 법적 근거 카드와 이의신청서 근거에 사용된다.

```json
{
  "law_code": "ROAD_TRAFFIC_ACT_ARTICLE_160",
  "violation_text": "제한속도 위반",
  "matched_laws": [
    {
      "title": "도로교통법",
      "article": "제160조",
      "summary": "과태료 부과 근거",
      "source_ref": "law_chunk_0001"
    }
  ],
  "reduction_eligible": true,
  "reduction_rate": 0.2,
  "special_reduction": false,
  "objection_possible": null,
  "missing_documents": ["이의신청 사유 증빙"],
  "applicable_reductions": ["사전납부 감경"],
  "inapplicable_reductions": [],
  "objection_reason": "고지 내용과 실제 운행 사실이 다르다는 사용자 주장 검토 필요"
}
```

| Field | 필수성 | Type/Allowed | 왜 필요한가 | 사용 위치와 누락 시 처리 |
|---|---|---|---|---|
| `law_code` | 조건부 필수 | string | exact 법령 검색 결과 연결에 필요하다. | 없으면 semantic 결과만 표시. |
| `violation_text` | 조건부 필수 | string | semantic 검색과 사용자 설명에 필요하다. | `law_code`도 없으면 결과 신뢰도 낮음. |
| `matched_laws` | 필수 | object[] | 화면 법령 근거 카드와 evidence에 필요하다. | 없으면 법령 카드 표시 불가. |
| `matched_laws[].title` | 필수 | string | 법령명을 표시한다. | 없으면 해당 law item 제외. |
| `matched_laws[].article` | 필수 | string | 조항 단위 근거를 표시한다. | 없으면 근거 불충분. |
| `matched_laws[].summary` | 필수 | string | LLM 최종 답변에 쓸 요약이다. | 없으면 원문만 표시하거나 제외. |
| `matched_laws[].source_ref` | 필수 | string | 원천 chunk, Neo4j/RAG source 추적에 필요하다. | 없으면 evidence 불충분. |
| `reduction_eligible` | 필수 | boolean | 감경 가능 여부 카드 핵심 값이다. | 없으면 감경 판단 보류. |
| `reduction_rate` | 조건부 필수 | number/null | 감경 가능 시 적용률 표시. | `reduction_eligible=true`인데 없으면 `partial`. |
| `special_reduction` | 검증 필요 | boolean 또는 string/null, PM 결정 필요 | 특별 감경 여부 또는 특별감경 설명 문구를 구분한다. | Frontend가 boolean 분기만 필요한지, 감경 문구 표시가 필요한지 확정 전 구현 보류. 없으면 `false`로 임의 추정하지 않는다. |
| `objection_possible` | 필수 | boolean/null | 이의신청서 생성 가능 조건 판단에 필요하다. | `null`이면 즉결심판 출석 여부 확인 UI를 먼저 표시한다. 없으면 초안 생성 전 확인 필요. |
| `missing_documents` | 필수 | string[] | 추가 증빙 요청에 사용된다. | 없으면 빈 배열. |
| `applicable_reductions` | 선택 | string[] | 사용자에게 적용 가능한 감경 사유를 보여준다. | 없으면 감경 상세 생략. |
| `inapplicable_reductions` | 선택 | string[] | 적용 불가 사유 설명에 사용된다. | 없으면 미표시. |
| `objection_reason` | 선택 | string/null | 이의신청서 grounds 초안에 도움을 준다. | 없으면 사용자 사실관계 기반으로 추가 질문. |

#### `objection_possible` 처리 기준

| 값 | 의미 | 대표 notice_stage | Frontend 처리 |
|---|---|---|---|
| `true` | 이의제기 가능 | `"사전통지"`, `"1차 고지서"` 기한 내 | 이의신청서/의견제출 초안 생성 흐름 진입 |
| `false` | 이의제기 불가 | `"2차 고지서"`, 기한 경과 | 납부 안내와 추가 상담 안내 표시 |
| `null` | 조건부 판단 필요 | `"즉결심판"` | 출석 여부 확인 UI 표시 후 다음 단계 결정 |

### 8.3 `text_ml_case_search`

텍스트 기반 사례, 판례, 유사 상황 검색 결과다. 과실비율, 사고 설명, 이의신청 근거 보조에 사용된다.

```json
{
  "query_text": "신호위반 단속 위치가 실제 주행 위치와 다릅니다.",
  "top_cases": [
    {
      "case_id": "case_0001",
      "title": "단속 위치 다툼 사례",
      "summary": "위치 정보와 고지서 기재가 다를 때 증빙 확인 필요",
      "reliability_score": 0.78,
      "source_type": "case",
      "source_ref": "case_chunk_0001"
    }
  ],
  "recommended_evidence": ["블랙박스 영상", "위치 기록", "고지서 원본"],
  "limitations": ["사례 검색 결과는 법률 판단 확정이 아닙니다."]
}
```

| Field | 필수성 | Type/Allowed | 왜 필요한가 | 사용 위치와 누락 시 처리 |
|---|---|---|---|---|
| `query_text` | 필수 | string | 어떤 사용자 설명으로 검색했는지 추적한다. | 없으면 검색 재현 불가. |
| `top_cases` | 필수 | object[] | 사례 카드와 LLM 근거 요약에 필요하다. | 없으면 빈 배열과 `limitations` 표시. |
| `top_cases[].case_id` | 필수 | string | 상세 조회와 evidence 연결에 필요하다. | 없으면 해당 case 제외. |
| `top_cases[].title` | 필수 | string | 사용자 화면 표시 제목이다. | 없으면 case item 제외. |
| `top_cases[].summary` | 필수 | string | LLM 답변과 카드 설명에 사용된다. | 없으면 표시 품질 저하. |
| `top_cases[].reliability_score` | 조건부 필수 | number | 유사 사례의 신뢰도/관련도를 표시한다. | 산출 불가 시 null과 `limitations` 기록. |
| `top_cases[].source_type` | 필수 | string | 판례, 사례, 문서 등 출처 유형을 구분한다. | 없으면 evidence 불충분. |
| `top_cases[].source_ref` | 필수 | string | 원천 chunk 또는 문서 추적에 필요하다. | 없으면 근거 표시 불가. |
| `recommended_evidence` | 선택 | string[] | 사용자가 추가로 제출할 자료를 안내한다. | 없으면 추가 증빙 안내 생략. |
| `limitations` | 필수 | string[] | 단정 방지와 법률 판단 한계를 표시한다. | 없으면 빈 배열. |

### 8.4 `vision_media_analysis`

이미지/영상 분석 결과다. 사고 장면, 고지서 이미지 품질, 증빙 자료 해석에 사용된다.

```json
{
  "media_type": "video",
  "observations": [
    {
      "timestamp": "00:00:12",
      "label": "차량 진입",
      "description": "차량이 교차로에 진입하는 장면이 확인됩니다.",
      "confidence": 0.81
    }
  ],
  "detected_objects": ["vehicle", "traffic_light", "lane"],
  "evidence_candidates": [
    {
      "type": "frame",
      "source_ref": "att_0002#00:00:12",
      "description": "신호등과 차량 위치가 함께 보이는 프레임"
    }
  ],
  "privacy_redaction_required": true,
  "limitations": ["영상 해상도가 낮아 번호판 식별은 제한됩니다."]
}
```

| Field | 필수성 | Type/Allowed | 왜 필요한가 | 사용 위치와 누락 시 처리 |
|---|---|---|---|---|
| `media_type` | 필수 | enum: image/video/document | 분석 결과를 어떤 파일 유형으로 해석할지 결정한다. | 없으면 vision 결과 저장 보류. |
| `observations` | 필수 | object[] | 사고 장면 요약과 LLM 답변에 필요하다. | 없으면 분석 실패 또는 `partial`. |
| `observations[].timestamp` | 조건부 필수 | string/null | 영상이면 장면 위치를 특정한다. | 영상인데 없으면 evidence 품질 저하. |
| `observations[].label` | 필수 | string | 관찰 항목 제목이다. | 없으면 item 제외. |
| `observations[].description` | 필수 | string | 사용자에게 설명할 핵심 내용이다. | 없으면 item 제외. |
| `observations[].confidence` | 선택 | number/null | 모델 신뢰도 표시와 단정 방지에 사용된다. | 없으면 `limitations`에 신뢰도 미제공 표시. |
| `detected_objects` | 선택 | string[] | 화면 보조 정보와 후속 검색 query에 사용된다. | 없으면 미표시. |
| `evidence_candidates` | 필수 | object[] | 이의신청서 첨부 증거 후보에 사용된다. | 없으면 evidence 카드 생성 불가. |
| `privacy_redaction_required` | 필수 | boolean | 얼굴, 번호판 등 masking 필요 여부를 판단한다. | 없으면 `true`로 간주. |
| `limitations` | 필수 | string[] | 영상 품질, 추정 한계를 표시한다. | 없으면 빈 배열. |

### 8.5 `objection_report_generation`

이의신청서 초안 생성 결과다. 법률 판단 확정문이 아니라 제출 전 검토가 필요한 문서 초안이다.

```json
{
  "recipient_agency": "서울특별시",
  "document_title": "과태료 부과 이의신청서 초안",
  "case_summary": "2026-06-20 제한속도 위반 고지에 대한 이의신청 요청",
  "violation_summary": "고지서상 제한속도 위반으로 과태료가 부과되었습니다.",
  "objection_purpose": "고지 내용과 실제 운행 사실이 다르다는 점을 소명하기 위함",
  "grounds": [
    {
      "title": "사실관계 확인 요청",
      "body": "사용자는 단속 위치와 실제 주행 위치가 다르다고 주장합니다.",
      "evidence_refs": ["att_0002"]
    }
  ],
  "attachment_list": ["고지서 이미지", "블랙박스 영상"],
  "missing_inputs": [],
  "disclaimer": "본 문서는 제출 전 사용자가 사실관계와 관할 기관 요구 양식을 확인해야 하는 초안입니다.",
  "next_actions": ["관할 기관 제출 양식 확인", "증빙 파일 첨부"]
}
```

| Field | 필수성 | Type/Allowed | 왜 필요한가 | 사용 위치와 누락 시 처리 |
|---|---|---|---|---|
| `recipient_agency` | 필수 | string | 이의신청서 제출 기관을 표시한다. | 없으면 초안 생성 보류. |
| `document_title` | 선택 | string | 다운로드 문서 제목에 사용된다. | 없으면 기본 제목 사용. |
| `case_summary` | 필수 | string | 사건 개요 본문에 들어간다. | 없으면 초안 생성 보류. |
| `violation_summary` | 선택 | string | 고지 위반 내용을 정리한다. | 없으면 고지서 분석 요약으로 대체 가능. |
| `objection_purpose` | 필수 | string | 신청 취지를 명확히 한다. | 없으면 사용자 보완 질문. |
| `grounds` | 필수 | object[] | 이의신청 사유 본문이다. | 없으면 초안 생성 불가. |
| `grounds[].title` | 필수 | string | 사유 항목 제목이다. | 없으면 해당 ground 제외. |
| `grounds[].body` | 필수 | string | 제출 문서 본문 내용이다. | 없으면 해당 ground 제외. |
| `grounds[].evidence_refs` | 선택 | string[] | 첨부 증거와 사유를 연결한다. | 없으면 증거 없는 주장으로 표시. |
| `attachment_list` | 필수 | string[] | 제출 시 첨부할 자료 목록이다. | 없으면 빈 배열 가능하나 증빙 부족 표시. |
| `missing_inputs` | 필수 | string[] | 초안 완성을 위해 부족한 값을 명시한다. | 없으면 빈 배열. |
| `disclaimer` | 필수 | string | 법률 판단 확정이 아님을 사용자에게 알린다. | 없으면 문서 생성 실패로 본다. |
| `next_actions` | 필수 | string[] | 제출 전 사용자 행동을 안내한다. | 없으면 빈 배열. |

## 9. 분석 결과 조회 API

### 9.1 `GET /api/analysis/results/{id}/`

Agent raw output이 아니라 Supervisor가 병합한 display output을 반환한다.

```json
{
  "assistant_message": {
    "summary": "고지서 분석과 이의신청 초안 준비가 일부 완료되었습니다.",
    "answer": "고지서 분석 결과 제한속도 위반 과태료로 보입니다. 이의신청서 작성을 위해 당시 상황 설명이 추가로 필요합니다.",
    "limitations": ["OCR 결과와 법령 근거는 담당자 sample output 수신 전까지 검증 필요입니다."]
  },
  "progress": [
    {
      "label": "고지서 분석",
      "status": "done"
    },
    {
      "label": "이의신청서 초안",
      "status": "waiting"
    }
  ],
  "cards": [
    {
      "card_type": "fine_notice",
      "title": "과태료 고지서 분석",
      "summary": "제한속도 위반 고지서로 추정됩니다.",
      "metrics": [
        {
          "label": "과태료",
          "value": 40000,
          "unit": "KRW"
        }
      ],
      "evidence_refs": ["att_0001"],
      "actions": ["이의신청서 초안 만들기"]
    }
  ],
  "pending_questions": [
    {
      "field": "user_facts",
      "question": "이의신청 사유와 당시 상황을 입력해 주세요."
    }
  ],
  "attachments": [
    {
      "attachment_id": "att_0001",
      "label": "notice.jpg",
      "purpose": "fine_notice"
    }
  ],
  "report_links": []
}
```

| Field | 필수성 | Type/Allowed | 왜 필요한가 | 사용 위치와 누락 시 처리 |
|---|---|---|---|---|
| `assistant_message` | 필수 | object | LLM 최종 답변 영역에 표시한다. | 없으면 결과 화면 표시 불가. |
| `assistant_message.summary` | 필수 | string | 카드 위 요약과 대화 목록 preview에 사용된다. | 없으면 빈 문자열 금지, 기본 요약 생성 필요. |
| `assistant_message.answer` | 필수 | string | 사용자에게 보여줄 답변 본문이다. | 없으면 결과 응답 실패. |
| `assistant_message.limitations` | 필수 | string[] | 단정 방지와 검증 필요 사항 표시. | 없으면 빈 배열. |
| `progress` | 필수 | object[] | 화면 진행 단계 표시. | 없으면 빈 배열 가능하나 job UI 저하. |
| `progress[].label` | 필수 | string | 단계명 표시. | 없으면 해당 단계 제외. |
| `progress[].status` | 필수 | enum: done/waiting/failed | 단계별 상태 표시. | 없으면 `waiting`으로 임의 보정하지 않는다. |
| `cards` | 필수 | object[] | HTML 화면설계서의 각 Agent 결과 카드 영역에 사용된다. | 없으면 빈 배열, 상세 결과 없음 표시. |
| `cards[].card_type` | 필수 | enum | 카드 template 분기에 필요하다. | 없으면 카드 표시 불가. |
| `cards[].title` | 필수 | string | 카드 제목. | 없으면 카드 표시 불가. |
| `cards[].summary` | 필수 | string | 카드 요약. | 없으면 카드 표시 품질 저하. |
| `cards[].metrics` | 선택 | object[] | 금액, 감경률, 신뢰도 등 정량 정보 표시. | 없으면 metric 영역 숨김. |
| `cards[].evidence_refs` | 필수 | string[] | 근거 파일/문서와 연결한다. | 없으면 근거 없는 카드로 제한 표시. |
| `cards[].actions` | 선택 | string[] | 다음 행동 버튼 또는 안내. | 없으면 action 영역 숨김. |
| `pending_questions` | 필수 | object[] | 부족한 입력을 사용자에게 요청한다. | 없으면 빈 배열. |
| `attachments` | 필수 | object[] | 업로드 자료 목록과 evidence 연결 표시. | 없으면 빈 배열. |
| `report_links` | 필수 | object[] | 생성된 PDF/DOCX/텍스트 보고서 링크 표시. | 없으면 빈 배열. |

## 10. 이의신청서 초안 생성 API

### 10.1 `POST /api/reports/objection-draft/`

고지서 분석 결과, 법령 근거, 사용자 사실관계를 받아 이의신청서 초안을 만든다. 선행 분석이 없거나 사용자 사실관계가 부족하면 초안을 만들지 않고 `missing_inputs`를 반환한다.

#### Request JSON

```json
{
  "session_id": "ses_20260623_0001",
  "message_id": "msg_0001",
  "notice_analysis_result": {
    "notice_stage": "사전통지",
    "law_code": "ROAD_TRAFFIC_ACT_ARTICLE_160",
    "violation_text": "제한속도 위반",
    "fine_amount": 40000,
    "issuing_authority": "서울특별시"
  },
  "law_ground_result": {
    "matched_laws": [
      {
        "title": "도로교통법",
        "article": "제160조",
        "summary": "과태료 부과 근거",
        "source_ref": "law_chunk_0001"
      }
    ],
    "objection_possible": true
  },
  "user_facts": {
    "claim_summary": "단속 위치가 실제 주행 위치와 다릅니다.",
    "event_context": "해당 시간에는 우회도로를 이용했습니다.",
    "requested_outcome": "과태료 부과 취소 또는 재검토"
  },
  "attachments": [
    {
      "attachment_id": "att_0002",
      "purpose": "evidence"
    }
  ],
  "additional_explanation": "제출 전 문구를 부드럽게 정리해 주세요.",
  "requested_format": "pdf"
}
```

#### Response JSON

```json
{
  "report_id": "rep_0001",
  "status": "draft_created",
  "draft": {
    "recipient_agency": "서울특별시",
    "document_title": "과태료 부과 이의신청서 초안",
    "case_summary": "2026-06-20 제한속도 위반 고지에 대한 이의신청 요청",
    "objection_purpose": "고지 내용과 실제 운행 사실이 다르다는 점을 소명하기 위함",
    "grounds": [
      {
        "title": "사실관계 확인 요청",
        "body": "사용자는 단속 위치와 실제 주행 위치가 다르다고 주장합니다.",
        "evidence_refs": ["att_0002"]
      }
    ],
    "attachment_list": ["블랙박스 영상"],
    "disclaimer": "본 문서는 제출 전 사용자가 사실관계와 관할 기관 요구 양식을 확인해야 하는 초안입니다."
  },
  "missing_inputs": [],
  "next_actions": ["관할 기관 제출 양식 확인", "증빙 파일 첨부"]
}
```

| Field | 필수성 | Type/Allowed | 왜 필요한가 | 사용 위치와 누락 시 처리 |
|---|---|---|---|---|
| `session_id` | 필수 | string | 리포트와 대화를 연결하고 권한을 검사한다. | 없으면 400. |
| `message_id` | 필수 | string | 어떤 사용자 요청으로 생성된 초안인지 추적한다. | 없으면 audit 불완전. |
| `notice_analysis_result` | 필수 | object | 고지서 정보와 제출 기관, 위반 내용을 만든다. | 없으면 초안 생성 불가. |
| `law_ground_result` | 조건부 필수 | object | 법령 근거와 이의신청 가능 조건 판단에 필요하다. | 없으면 법령 근거 없는 초안으로 제한하거나 보류. |
| `user_facts` | 필수 | object | 사용자의 주장과 사실관계 없이는 이의신청 사유를 만들 수 없다. | 없으면 `missing_inputs=["user_facts"]`. |
| `user_facts.claim_summary` | 필수 | string | 이의신청 사유의 핵심 주장이다. | 없으면 초안 생성 보류. |
| `user_facts.event_context` | 선택 | string | 사건 상황 설명에 사용된다. | 없으면 추가 질문. |
| `user_facts.requested_outcome` | 선택 | string | 취소, 감경, 재검토 등 신청 취지를 구체화한다. | 없으면 일반적인 재검토 요청으로 처리 가능. |
| `attachments` | 선택 | object[] | 증빙 자료를 grounds와 연결한다. | 없으면 증빙 부족 limitation. |
| `additional_explanation` | 선택 | string | 사용자 문체/추가 요청을 반영한다. | 없으면 기본 문체 사용. |
| `requested_format` | 선택 | enum: text/pdf/docx | 다운로드 형식을 결정한다. | 없으면 `text` 또는 서비스 기본값. |
| `report_id` | 필수 | string | 리포트 목록과 다운로드 조회에 필요하다. | 없으면 생성 실패. |
| `status` | 필수 | string | 초안 생성 완료/부분 완료 상태를 표시한다. | 없으면 응답 실패. |
| `draft` | 조건부 필수 | object | 초안 생성 성공 시 본문 구조다. | 성공인데 없으면 schema 오류. |
| `missing_inputs` | 필수 | string[] | 초안 생성이 보류되거나 부분 성공일 때 필요한 값이다. | 없으면 빈 배열. |
| `next_actions` | 필수 | string[] | 제출 전 사용자 행동 안내. | 없으면 빈 배열. |

## 11. 저장소 매핑

### 11.1 PostgreSQL

PostgreSQL은 영속 저장소로 확정한다. 대화 이력, 파일 metadata, 분석 job, Agent 결과, 리포트를 저장한다.

| Logical table | 필수 key 후보 | 저장 이유 | 사용 위치 |
|---|---|---|---|
| `users` | `user_id` | 로그인 사용자, 권한 검사 | 인증/인가 |
| `chat_sessions` | `session_id`, `user_id`, `title`, `created_at`, `updated_at` | 대화 목록과 session 소유자 연결 | `/api/chat/sessions/` |
| `messages` | `message_id`, `session_id`, `role`, `content`, `created_at` | 사용자/assistant 메시지 이력 | `/api/chat/messages/` |
| `uploaded_files` | `attachment_id`, `owner_id`, `session_id`, `file_type`, `purpose`, `privacy_risk`, `storage_uri` | 파일 권한, 분석 job 연결 | `/api/files/` |
| `analysis_jobs` | `job_id`, `session_id`, `routing_intent`, `status`, `active_node` | 분석 진행 이력 | `/api/analysis/jobs/` |
| `agent_results` | `result_id`, `job_id`, `node_code`, `status`, `structured_result`, `evidence`, `limitations` | 결과 카드와 리포트 생성 | `/api/analysis/results/{id}/` |
| `reports` | `report_id`, `owner_id`, `result_id`, `report_type`, `content`, `created_at` | 리포트 목록, 상세, 다운로드 | `/api/reports/` |

### 11.2 Redis

Redis는 챗봇 session별 상태와 분석 진행 상태 cache 서버로 확정한다. TTL 값과 key naming은 아직 확정하지 않는다.

| Redis key 후보 | 필수 값 | 저장 이유 | 사용 위치 |
|---|---|---|---|
| `chat_session_state:{session_id}` | `current_intent`, `pending_questions`, `active_job_id`, `expires_at` | 사용자가 다음 메시지를 보냈을 때 이전 흐름을 이어가기 위함 | Supervisor routing |
| `analysis_job_progress:{job_id}` | `status`, `active_node`, `progress_message`, `updated_at` | 화면이 빠르게 진행 상태를 조회하기 위함 | `/api/analysis/jobs/{id}/` |
| `rate_limit:{user_or_session_id}` | `count`, `reset_at` | 과도한 요청 제한 | API gateway 또는 Django middleware |

### 11.3 Neo4j/RAG

Neo4j는 graph/RAG 계열 저장소로 반영한다. 다만 hi20260204-maker의 책임은 Docker 실행, 제공된 데이터/스크립트 적재, expected count 검증까지다. Cypher query 작성, graph schema 모델링, 검색 query 튜닝은 담당 범위가 아니다.

| Artifact | 필수 값 | 저장 이유 | hi20260204-maker 처리 |
|---|---|---|---|
| `neo4j_load_artifacts` | `artifact_path`, `source_type`, `load_script`, `expected_counts`, `loaded_at` | 법령, 사례, 증거 relation graph 적재 검증 | 제공된 스크립트 실행과 count 확인 |
| `rag_source_metadata` | `source_ref`, `source_type`, `title`, `chunk_id` | Agent evidence와 화면 근거 연결 | 담당자 산출물 수신 후 연결 확인 |
| `law_case_relation_graph` | 담당자 schema 필요 | 법령, 판례, 사례, 증거 관계 탐색 | query/schema 직접 작성하지 않음 |

## 12. 화면설계서 HTML 추적성 확인

본 명세서는 `app/screen-design-mvp-flow.html`과 `docs/screen-design-specification.md`의 화면 구성 기준을 함께 확인해 작성했다. 다만 HTML은 정적 시연 화면이고, 본 문서는 그 정적 화면을 실제 API/Agent 계약으로 바꾸기 위한 PM 초안이다.

### 12.1 화면 영역별 API와 Agent output 매핑

| 화면/HTML 영역 | HTML에서 확인한 표시 내용 | 필요한 API JSON | 필요한 Agent output | 담당자/확인자 |
|---|---|---|---|---|
| `#chat-screen` 최근 상담 | 상담 제목, 마지막 요약, 상태 배지 | `GET /api/chat/sessions/` response: `session_id`, `title`, `last_summary`, `status`, `updated_at` | Supervisor `assistant_message.summary`, job `status` | `hi20260204-maker` |
| `#chat-screen` 챗봇 대화창 | 사용자 질문, AI 응답, 분석 안내 | `GET /api/chat/sessions/{id}/messages/`, `POST /api/chat/messages/` | Supervisor display `assistant_message.answer`, `limitations`, `pending_questions` | `hi20260204-maker`, Frontend |
| `#chat-screen` 빠른 질문 | `고지서 분석하기`, `과실비율 확인하기`, `의견제출서 초안 만들기`, `관련 법령 보기` | `POST /api/chat/messages/` request의 `routing_intent` 또는 user_text 기반 분기 | Supervisor routing result: `fine_notice`, `fault_ratio`, `objection_request`, `law_question` | `hi20260204-maker` |
| `#chat-screen` 입력창 | 텍스트 입력, 파일 첨부, 전송 | `POST /api/files/`, `POST /api/chat/messages/` | Supervisor input package: `user_text`, `input_modalities`, `attachments` | Frontend, `hi20260204-maker` |
| `#chat-screen` 첨부 자료 | 고지서 이미지, 사고경위서 문서, 파일 추가 | `POST /api/files/` response: `attachment_id`, `file_type`, `purpose`, `privacy_risk` | Vision/OCR input으로 전달될 attachment metadata | Frontend, `hi20260204-maker`, `workzion2`, `ohjuheecode` |
| `#chat-screen` 분석 상태 | 고지서 OCR, 법령 근거, 현장 사진, 초안 생성 | `GET /api/analysis/jobs/{id}/` response: `status`, `active_node`, `progress_message` | 각 Agent envelope의 `node_code`, `status`, `missing_fields` | `hi20260204-maker`, 각 Agent 담당자 |
| `#chat-screen` 분석 결과 카드 | 과태료 고지서 분석, 사고 과실비율 상담 | `GET /api/analysis/results/{id}/` response의 `cards[]` | `fine_notice_analysis`, `text_ml_case_search`, `vision_media_analysis` 요약 | `workzion2`, `leejaegang27`, `ohjuheecode`, `hi20260204-maker` |
| `#fine-screen` 요약 metric | 납부 금액, 의견제출 기한, 이의제기 가능성, 필요 자료 | `GET /api/analysis/results/{id}/` 또는 `GET /api/reports/{id}/` | `fine_amount`, `due_date`, `objection_possible`, `missing_documents` | `workzion2`, `hi20260204-maker` |
| `#fine-screen` OCR 결과 | 위반 장소, 처분 유형, 확인된 쟁점, 추가 요청 | `GET /api/analysis/results/{id}/` cards/detail | `notice_stage`, `violation_location`, `violation_text`, `ocr_status`, `missing_fields` | `workzion2` |
| `#fine-screen` 다음 행동/초안 | 현장 자료 보강, 의견제출서 초안, 초안 내려받기 | `POST /api/reports/objection-draft/`, `GET /api/reports/{id}/` | `objection_report_generation` output: `draft`, `next_actions`, `disclaimer` | `hi20260204-maker`, `workzion2`, `techshin31` |
| `#fault-screen` 요약 metric | 사고 유형, 주요 쟁점, 제출 자료, 검토 상태 | `GET /api/analysis/results/{id}/` 또는 `GET /api/reports/{id}/` | `accident_type_candidates`, `issue_tags`, `evidence_candidates`, `status` | `leejaegang27`, `ohjuheecode` |
| `#fault-screen` 사고 장면 정리 | 사고 도식, AI 분석 요약, 다툼 예상 지점, 관련 기준, 추가 자료 | `GET /api/analysis/results/{id}/` cards/detail | `vision_media_analysis.observations`, `text_ml_case_search.top_cases`, `recommended_evidence` | `ohjuheecode`, `leejaegang27`, `techshin31` |
| `#fault-screen` 문의 초안 | 보험사 문의 초안 내려받기 | 현재 문서에는 전용 endpoint 미정. 후보: `POST /api/reports/objection-draft/`와 별도 report 생성 API 분리 필요 | 과실비율 report draft output은 담당자 schema 미수신 | `leejaegang27`, `hi20260204-maker`, 담당자 확인 필요 |
| `#mypage-screen` 내 사건 | 등록 사건, 기한 임박, 저장 리포트, 최근 분석 이력 | 현재 명세에는 `GET /api/reports/`, `GET /api/chat/sessions/`만 포함. `GET /api/mypage/summary/`, `GET /api/history/`는 화면설계서 후보 | Agent output이 아니라 PostgreSQL 집계 결과 | `hi20260204-maker`, Frontend |

### 12.2 현재 명세에 반영된 화면설계서 항목

| 화면설계서 요구 | 반영 위치 | 상태 |
|---|---|---|
| 챗봇에서 텍스트와 첨부를 함께 입력 | `POST /api/chat/messages/`, `POST /api/files/`, Supervisor input package | 반영 |
| 분석 결과 카드가 LLM 답변과 HTML에 노출 | `GET /api/analysis/results/{id}/`의 `assistant_message`, `cards`, `progress` | 반영 |
| OCR/법령/현장 사진/초안 생성 진행 상태 표시 | `GET /api/analysis/jobs/{id}/`와 Agent envelope `status` | 반영 |
| 과태료·범칙금 화면의 OCR, 처분, 이의제기, 필요 증거, 초안 | `fine_notice_analysis`, `law_ground_search`, `objection_report_generation` | 반영, 담당자 sample 필요 |
| 과실비율 화면의 사고 요약, 제출 자료, 쟁점, 유사 사례, 후속 행동 | `text_ml_case_search`, `vision_media_analysis`, `law_ground_search` | 부분 반영, 과실비율 전용 상세 필드는 추가 확인 필요 |
| 마이페이지/과거 이력/리포트 목록 | 저장소 매핑과 `GET /api/reports/` 중심 | 부분 반영, `GET /api/mypage/summary/`, `GET /api/history/`는 별도 확정 필요 |
| 판례/보험사 사례 전체 목록 | `text_ml_case_search.top_cases`, `source_ref` | 부분 반영, 전용 사례 목록 endpoint는 미정 |

## 13. 담당자별 필요 API JSON

이 섹션은 각 담당자가 어떤 API 응답 또는 내부 Agent JSON을 확인해야 하는지 정리한 표다. 실제 endpoint path는 Django API 정의 확정 전까지 PM 초안이다.

### 13.1 Frontend 담당자

Frontend는 Agent raw output을 직접 화면에 뿌리지 않는다. `GET /api/analysis/results/{id}/`의 Supervisor display output을 기준으로 화면을 만든다.

```json
{
  "uses_api": [
    "GET /api/chat/sessions/",
    "GET /api/chat/sessions/{id}/messages/",
    "POST /api/files/",
    "POST /api/chat/messages/",
    "GET /api/analysis/jobs/{id}/",
    "GET /api/analysis/results/{id}/",
    "POST /api/reports/objection-draft/",
    "GET /api/reports/",
    "GET /api/reports/{id}/"
  ],
  "screen_contract": {
    "chat_list": "session_id, title, last_summary, status, updated_at",
    "chat_window": "messages, assistant_message.answer, pending_questions",
    "result_cards": "cards[].card_type, title, summary, metrics, actions",
    "progress_panel": "progress[].label, progress[].status",
    "file_panel": "attachments[].attachment_id, label, purpose",
    "report_buttons": "report_links[], next_actions[]"
  }
}
```

| 확인할 schema | 왜 필요한가 | 담당자에게 요청할 설명 |
|---|---|---|
| `Supervisor display output` | HTML 화면의 채팅 답변, 결과 카드, 진행 상태, 첨부 자료, 리포트 링크를 모두 이 JSON에서 받는다. | 카드 유형별 렌더링 기준, 빈 배열 처리, `partial/failed` UI 처리 |
| `API error response` | 업로드 실패, 응답 생성 실패, 권한 없음, 근거 부족 화면을 표시해야 한다. | `error.code`별 사용자 문구와 재시도 버튼 노출 기준 |
| `POST /api/files/` response | 첨부 자료 카드와 분석 input 연결에 필요하다. | 허용 파일 type, size 제한, `privacy_risk=true` 표시 방식 |

### 13.2 `hi20260204-maker` - Django Backend/API 담당자

`hi20260204-maker`가 담당하는 Django Backend는 화면 API와 Supervisor/Agent 내부 계약 사이의 adapter 역할을 한다.

```json
{
  "required_api_groups": {
    "chat": [
      "GET /api/chat/sessions/",
      "POST /api/chat/sessions/",
      "GET /api/chat/sessions/{id}/messages/",
      "POST /api/chat/messages/"
    ],
    "file": ["POST /api/files/"],
    "analysis": [
      "POST /api/analysis/jobs/",
      "GET /api/analysis/jobs/{id}/",
      "GET /api/analysis/results/{id}/"
    ],
    "report": [
      "POST /api/reports/objection-draft/",
      "GET /api/reports/",
      "GET /api/reports/{id}/"
    ]
  },
  "storage_contract": {
    "postgresql": ["chat_sessions", "messages", "uploaded_files", "analysis_jobs", "agent_results", "reports"],
    "redis": ["chat_session_state:{session_id}", "analysis_job_progress:{job_id}"],
    "neo4j_rag": ["source_ref", "chunk_id", "expected_counts"]
  }
}
```

| 확인할 schema | 왜 필요한가 | 담당자에게 요청할 설명 |
|---|---|---|
| API request/response DTO | 화면과 Supervisor 사이의 boundary다. | DRF serializer 기준 필수/선택 필드, status code |
| 인증/인가 error JSON | 본인 session/report/file만 조회해야 한다. | `auth_required`, `forbidden` 응답 조건 |
| PostgreSQL/Redis 저장 key | session, job, result 조회를 안정적으로 연결해야 한다. | table/key naming, TTL, transaction 처리 |

### 13.3 `hi20260204-maker` - Supervisor/이의신청서/Django-AWS/통합 QA

`hi20260204-maker`는 Supervisor routing, display output 병합, 이의신청서 초안 생성 계약, Django/AWS/PostgreSQL/Redis/Neo4j 운영 경계 확인을 담당한다.

```json
{
  "supervisor_input": {
    "session_id": "ses_20260623_0001",
    "user_id": "usr_0001",
    "user_text": "이 고지서 이의신청서 만들어줘",
    "input_modalities": ["text", "image"],
    "attachments": [
      {
        "attachment_id": "att_0001",
        "type": "image",
        "purpose": "fine_notice",
        "mime_type": "image/jpeg",
        "privacy_risk": true
      }
    ],
    "routing_intent": "objection_request",
    "missing_inputs": ["user_facts"],
    "limitations": []
  },
  "must_emit": [
    "GET /api/analysis/results/{id} display output",
    "POST /api/reports/objection-draft/ response",
    "Agent handoff missing_fields"
  ]
}
```

| 확인할 schema | 왜 필요한가 | 담당자에게 요청할 설명 |
|---|---|---|
| Supervisor input package | 사용자 질의를 텍스트/이미지/영상/문서로 분리해 각 Agent로 보낸다. | intent별 필수 입력, 부족 입력 질문 문구 |
| Agent result envelope | 모든 Agent output을 같은 형태로 받아 병합해야 한다. | `status=partial/failed` 처리, `node_code` enum |
| Objection draft request/response | 이의신청서 초안은 고지서 분석, 법령 근거, 사용자 사실관계가 모두 필요하다. | 초안 생성 보류 조건, `disclaimer`, 다운로드 format |

### 13.4 `workzion2` - 고지서 OCR/과태료/감경/고지서 흐름 law search

```json
{
  "agent_input": {
    "session_id": "ses_20260623_0001",
    "message_id": "msg_0001",
    "job_id": "job_0001",
    "node_code": "fine_notice_analysis",
    "user_text": "고지서 사진과 현장 사진을 첨부했습니다.",
    "attachments": [
      {
        "attachment_id": "att_0001",
        "type": "image",
        "purpose": "fine_notice",
        "mime_type": "image/jpeg"
      }
    ],
    "handoff_context": {
      "law_search_mode": "exact_or_semantic",
      "required_outputs": ["law_code", "violation_text", "fine_amount", "issuing_authority"]
    }
  },
  "agent_output": {
    "node_code": "fine_notice_analysis",
    "status": "success|partial|failed",
    "structured_result": {
      "notice_stage": "사전통지",
      "law_code": "",
      "violation_text": "",
      "ocr_status": "success",
      "fine_amount": 0,
      "issuing_authority": "",
      "reduction_eligible": true,
      "reduction_rate": 0.2,
      "special_reduction": false,
      "objection_possible": null,
      "missing_documents": []
    }
  }
}
```

| 필수 확인 | 왜 필요한가 | 사용 화면/API |
|---|---|---|
| `law_code`와 `violation_text` 중 최소 1개 | 법령 검색 exact/semantic 분기 input이다. | Supervisor routing, `law_ground_search` |
| `fine_amount`, `issuing_authority`, `notice_stage` | 과태료 결과 카드와 이의신청서 제출 기관에 필요하다. | `#fine-screen`, `POST /api/reports/objection-draft/` |
| `reduction_eligible`, `reduction_rate`, `special_reduction`, `objection_possible` | 감경/이의제기 가능성 표시와 초안 생성 조건이다. `special_reduction`은 PM 결정 전까지 구현 보류, `objection_possible=null`은 즉결심판 출석 여부 확인 흐름으로 처리한다. | `#fine-screen` metric, next_actions |
| `ocr_status`, `missing_fields` | OCR 실패/부분 성공 시 추가 질문과 재업로드 안내에 필요하다. `degraded`는 특정 필드 재확인, `partial`은 전체 보완 입력 또는 fallback을 요청한다. | `GET /api/analysis/results/{id}` |

### 13.5 `techshin31` - 법령 metadata/RAG source/chunk 확인

```json
{
  "agent_input": {
    "session_id": "ses_20260623_0001",
    "message_id": "msg_0001",
    "job_id": "job_0001",
    "node_code": "law_ground_search",
    "law_code": "ROAD_TRAFFIC_ACT_ARTICLE_160",
    "violation_text": "제한속도 위반",
    "search_query": "도로교통법 과태료 제한속도 위반",
    "source_scope": ["law", "precedent", "case"]
  },
  "agent_output": {
    "node_code": "law_ground_search",
    "status": "success|partial|failed",
    "structured_result": {
      "matched_laws": [
        {
          "title": "",
          "article": "",
          "summary": "",
          "source_ref": "",
          "chunk_id": "",
          "retrieval_score": 0.0,
          "applicability_limit": ""
        }
      ]
    }
  }
}
```

| 필수 확인 | 왜 필요한가 | 사용 화면/API |
|---|---|---|
| `source_ref`, `chunk_id` | 화면 근거와 Neo4j/RAG source를 연결한다. | 법령 근거 카드, evidence |
| `title`, `article`, `summary` | 사용자가 볼 법령 근거 카드의 최소 단위다. | `#chat-screen`, `#fine-screen`, `#fault-screen` |
| `retrieval_score`, `applicability_limit` | 단정 방지와 근거 신뢰도 표시가 필요하다. | `limitations`, guardrail |
| exact/semantic 검색 sample | `law_code`가 있을 때와 없을 때의 호출 방식이 달라진다. | Supervisor routing |

### 13.6 `leejaegang27` - 과실비율/사례/evidence schema

```json
{
  "agent_input": {
    "session_id": "ses_20260623_0001",
    "message_id": "msg_0001",
    "job_id": "job_0002",
    "node_code": "text_ml_case_search",
    "query_text": "신호 없는 교차로에서 A차 직진, B차 우측 진입 사고",
    "vision_evidence": [
      {
        "source_ref": "att_0002#00:00:12",
        "description": "충돌 직전 차량 위치"
      }
    ],
    "required_outputs": ["accident_type_candidates", "issue_tags", "similar_cases", "reliability_score"]
  },
  "agent_output": {
    "node_code": "text_ml_case_search",
    "status": "success|partial|failed",
    "structured_result": {
      "accident_type_candidates": [],
      "issue_tags": [],
      "evidence_tags": [],
      "similar_cases": [],
      "reliability_score": 0.0,
      "ratio_range_label": "",
      "limitations": []
    }
  }
}
```

| 필수 확인 | 왜 필요한가 | 사용 화면/API |
|---|---|---|
| `accident_type_candidates`, `issue_tags` | 과실비율 화면의 사고 유형과 주요 쟁점 카드에 필요하다. | `#fault-screen` metric/report-grid |
| `similar_cases`, `source_type`, `source_ref` | 근거 보기와 유사 사례 목록으로 연결한다. | `UI-REPORT-003`, evidence |
| `reliability_score` | 단정 방지와 신뢰도 표시 기준이다. | `limitations`, guardrail |
| `ratio_range_label` | 과실비율을 확정 수치가 아니라 범위/라벨로 표시하기 위함이다. | `#fault-screen`, report draft |

### 13.7 `ohjuheecode` - Vision 이미지/영상 분석

```json
{
  "agent_input": {
    "session_id": "ses_20260623_0001",
    "message_id": "msg_0001",
    "job_id": "job_0002",
    "node_code": "vision_media_analysis",
    "attachments": [
      {
        "attachment_id": "att_0002",
        "type": "video",
        "purpose": "accident_scene",
        "mime_type": "video/mp4",
        "privacy_risk": true
      }
    ],
    "analysis_request": {
      "extract_key_frames": true,
      "detect_privacy": true,
      "summarize_scene": true
    }
  },
  "agent_output": {
    "node_code": "vision_media_analysis",
    "status": "success|partial|failed",
    "structured_result": {
      "media_type": "video",
      "observations": [],
      "detected_objects": [],
      "evidence_candidates": [],
      "privacy_redaction_required": true,
      "limitations": []
    }
  }
}
```

| 필수 확인 | 왜 필요한가 | 사용 화면/API |
|---|---|---|
| `observations[].timestamp`, `description` | 사고 장면 정리와 과실비율 분석 input으로 넘긴다. | `#fault-screen`, `leejaegang27` input |
| `evidence_candidates[].source_ref` | 이의신청서/문의 초안의 증거 연결에 필요하다. | report draft, evidence |
| `privacy_redaction_required` | 얼굴, 번호판 등 개인정보 masking 기준이다. | 파일 보관/표시 정책 |
| `limitations` | 영상 품질, 식별 불가, confidence 부족을 표시한다. | `assistant_message.limitations` |

> 확인 메모
>
> - 주희 확정본 기준으로 `vision_media_analysis` 입력 purpose는 `accident_scene`, `damage_image`를 사용한다.
> - `damage_image`는 PM 상위 `attachment.purpose` enum으로 직접 승격하지 않고, Supervisor가 Vision node handoff를 만들 때 사용하는 내부 매핑 값으로 확정한다.
> - 따라서 PM 상위 purpose enum은 유지하고, 차량 파손 이미지 구분은 Supervisor 내부 라우팅/매핑 규칙으로 처리한다.

## 14. Agent node 간 input/output handoff

아래 표는 각 노드가 Supervisor 또는 다른 Agent에게 넘겨야 하는 최소 handoff 계약이다. 담당자 output이 수신되기 전까지는 PM 초안이며, 충돌 시 구현하지 않고 확인한다.

> 2026-06-27 구현 메모:
> Django mock backend는 `GET /api/mock/agents/nodes/`, `POST /api/mock/agents/nodes/run/`, `POST /api/mock/agents/plans/run/`를 제공한다. 이 endpoint들은 실제 Agent, RAG, MCP, LLM을 호출하지 않고 `analysis_plan.steps[].node_code`를 공통 Agent envelope mock output으로 변환해 프론트엔드와 담당자별 node adapter 연결 위치를 검증한다.

| 흐름 | 보내는 쪽 | 받는 쪽 | 전달 JSON 핵심 필드 | 화면/API에서 필요한 이유 | 확인 담당 |
|---|---|---|---|---|---|
| 사용자 입력 분리 | Django Backend(`hi20260204-maker`) | Supervisor | `session_id`, `user_text`, `input_modalities`, `attachments`, `routing_intent` | 챗봇 입력과 파일 첨부를 하나의 분석 job으로 묶는다. `attachments[].purpose=accident_statement`는 사고경위서 문서형 입력의 라우팅 힌트다. | `hi20260204-maker` |
| 고지서 OCR | Supervisor | `workzion2` | `attachments[purpose=fine_notice]`, `user_text`, `required_outputs` | OCR 결과와 과태료 정보를 얻는다. | `workzion2` |
| 고지서 결과 반환 | `workzion2` | Supervisor | Agent envelope + `fine_notice_analysis` | 과태료 카드, OCR 상세, 이의신청서 선행 입력이다. | `workzion2`, `hi20260204-maker` |
| 고지서 law search | `workzion2` 또는 Supervisor | `workzion2` law search / `techshin31` metadata | `law_code`, `violation_text`, `search_query` | 관련 법령/판례 카드와 guardrail에 필요하다. | `workzion2`, `techshin31` |
| 법령 근거 반환 | `techshin31` | Supervisor | `matched_laws`, `source_ref`, `chunk_id`, `applicability_limit` | 근거 보기, 리포트, 이의신청서 grounds 근거다. | `techshin31` |
| 영상/이미지 분석 | Supervisor | `ohjuheecode` | `attachments[purpose=accident_scene/evidence]`, `privacy_risk` | 사고 장면, evidence 후보, 개인정보 처리에 필요하다. | `ohjuheecode` |
| Vision 결과 전달 | `ohjuheecode` | Supervisor, `leejaegang27` | `observations`, `evidence_candidates`, `limitations` | 과실비율/사례 검색 input으로 사용한다. | `ohjuheecode`, `leejaegang27` |
| 과실비율/사례 검색 | Supervisor | `leejaegang27` | `query_text`, `vision_evidence`, `issue_tags` 후보 | 과실비율 화면의 사고 유형, 쟁점, 유사 사례를 만든다. | `leejaegang27` |
| 과실비율 결과 반환 | `leejaegang27` | Supervisor | `accident_type_candidates`, `similar_cases`, `reliability_score`, `limitations` | 과실비율 카드와 report draft에 필요하다. | `leejaegang27` |
| 이의신청서 초안 생성 | Supervisor | `hi20260204-maker` report generation | `notice_analysis_result`, `law_ground_result`, `user_facts`, `attachments` | 고지서 분석과 사용자 사실관계를 문서 초안으로 묶는다. | `hi20260204-maker` |
| 화면 표시 병합 | Supervisor | Frontend/API | `assistant_message`, `progress`, `cards`, `pending_questions`, `attachments`, `report_links` | HTML 화면설계서의 LLM 답변과 결과 카드에 뿌린다. | `hi20260204-maker`, Frontend |

> handoff 추가 확인 메모
>
> - `accident_statement`는 PM 상위 입력 purpose에는 추가됐지만, 이 값을 실제로 받는 node/handoff 행은 아직 본 문서에 명시하지 않았다.
> - 따라서 현재 단계에서 확정된 범위는 "사고경위서를 문서형 입력으로 별도 분류한다"는 상위 입력 계약까지다.
> - 실제 수신 node, handoff JSON 핵심 필드, 후속 output schema 연결은 관련 이슈에서 추가 확정한다.

## 15. 구현 전 확인 필요 항목

| 항목 | 왜 확인해야 하는가 | 확인 전 처리 |
|---|---|---|
| Django 인증 방식 | session, JWT, OAuth 연동 방식에 따라 request header와 권한 검사가 달라진다. | `hi20260204-maker` 확인 전 구현 보류 |
| 비회원 상담 허용 여부 | PostgreSQL 영속 저장, Redis TTL, 파일 보관 정책이 달라진다. | 정책 미확정 |
| 파일 보관 위치 | local, object storage, DB 저장 여부에 따라 `storage_uri`가 달라진다. | metadata만 초안 유지 |
| `accident_statement` handoff 대상 node | 상위 입력 purpose는 추가됐지만 실제 수신 node와 handoff 필드가 문서에 없다. | 상위 입력 라우팅 힌트까지만 확정 |
| Agent별 최종 output schema | PM 초안과 담당자 schema가 충돌할 수 있다. | `검증 필요` 표시 |
| Agent sample output | 실제 LLM/모델 결과가 JSON 계약을 만족하는지 확인해야 한다. | 이슈 close 불가 |
| Neo4j load source와 expected count | 적재 검증 기준이 필요하다. | 담당자 산출물 수신 대기 |

## 16. 담당자에게 보내는 확인 요청 문구

각 Agent 담당자는 아래 기준으로 자신의 output schema를 확인해야 한다.

1. 위 JSON 필드 중 실제로 제공 가능한 필드와 불가능한 필드를 구분한다.
2. 필수 필드가 불가능하면 대체 필드명, 산출 조건, 누락 시 처리 방식을 제안한다.
3. 실제 sample output 1개 이상을 제공한다.
4. `status=partial`이 되는 조건과 `missing_fields` 목록을 명확히 적는다.
5. evidence에 들어갈 source id, source type, quote 또는 source_ref 형식을 정한다.

이 확인 전까지 본 명세서는 구현 확정안이 아니라 PM API/schema 초안이다.
