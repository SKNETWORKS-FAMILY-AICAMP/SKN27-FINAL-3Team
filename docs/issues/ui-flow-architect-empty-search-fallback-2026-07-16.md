# UI flow architect - 검색결과 없음 안내 문구 + Supervisor LLM 점검 - 2026-07-16

브랜치: `issue/ui-flow-architect`

## Summary

`law_ground_search`(또는 다른 Agent 노드)가 `success`가 아닌 상태로 끝났을 때, 채팅 답변에 원본 요약 문구만 보여주는 대신 사용자에게 추가 정보를 요청하는 안내 문구를 이어붙이도록 `compose_agent_response()`를 수정했다. 같이 진행된 프론트 정리(`FrontendAppShell.jsx`)와, 이 작업 검증 중 발견된 Supervisor LLM 회귀를 함께 기록한다.

## Root cause

로컬 환경에는 법령 검색용 시드 데이터(Neo4j/Postgres vector, `law_chunks`/`law_embeddings`)가 아직 적재되어 있지 않다. 그래서 `law_ground_search`는 로컬에서 항상 빈 결과(`source_status: "empty"`)를 반환할 수 있다 — 이는 버그가 아니라 로컬 시드 데이터 부재에 따른 정상적인 현상이다.

## Implementation

- `app/services/chat_orchestration_service.py`
  - `NEEDS_MORE_INFO_PROMPT` 상수 추가:
    > "조금 더 구체적으로 알려주시면 이어서 확인해드릴게요. 정확한 위반·분쟁 유형, 발생 일시와 장소, 받으신 고지서나 통지 내용을 알려주시면 도움이 됩니다."
  - `compose_agent_response()`: 결과 요약(`answer`)이 있고 combined `status != "success"`이면 `NEEDS_MORE_INFO_PROMPT`를 `\n\n`으로 이어붙인다.
- `app/web/FrontendAppShell.jsx`
  - `ChatScreenV2`의 assistant 메시지 버블에서 고정 안내 문구(`<strong>` 헤더, "상담 내용을 분석에 필요한 정보로 정리했습니다." 등)를 제거했다. `supervisorState`는 다른 곳(`MissingFieldsPrompt` 등)에서 계속 쓰이므로 dangling 참조는 없음을 확인했다.

## Verification (end-to-end, 실제 API 호출)

`dev-local.ps1`로 뜬 backend(8010)/agent-worker/file-scan-worker/frontend(5173) 중 backend는 Django 자동 리로드로 코드 변경을 이미 반영한 상태였고, agent-worker는 자동 리로드가 없어 재시작했다.

1. `POST /api/auth/guest-session/` → guest_id 발급
2. `POST /api/chat/sessions/` (`X-Guest-Id` 헤더) → 세션 생성
3. `POST /api/chat/messages/`에 `user_text="신호위반 관련 도로교통법 조문이 궁금해요"` 전송 (고지서 첨부 없음 → `traffic_law_search` → `law_ground_search` 단일 노드로 라우팅)
4. `GET /api/analysis/results/{job_id}/` 결과:
   - `status: "partial"`, `structured_results.law_ground_search.adapter_trace.source_status: "empty"`
   - `assistant_message.answer`:
     ```
     검색 조건에 맞는 유효한 조문이 없습니다.

     조금 더 구체적으로 알려주시면 이어서 확인해드릴게요. 정확한 위반·분쟁 유형,
     발생 일시와 장소, 받으신 고지서나 통지 내용을 알려주시면 도움이 됩니다.
     ```
   - 의도한 `요약 + "\n\n" + NEEDS_MORE_INFO_PROMPT` 조합과 일치. PASS.

이 검증은 로컬 backend에 실제 OpenAI API를 호출(supervisor 비활성 상태에서는 `law_ground_search` 내부 gpt-4o-mini fallback만 해당)하므로, 매 호출 전 사용자에게 비용 발생을 고지하고 승인받은 뒤 진행했다.

## Finding: `_combined_status`가 노드별이 아니라 job 전체 기준으로 안내 문구를 붙임

`_combined_status()` (`app/services/chat_orchestration_service.py:472-477`)는 노드 중 하나라도 `success`가 아니면 전체 job 상태를 `"partial"`로 만든다. 즉 `fine_notice_objection` 플랜(`fine_notice_analysis → law_ground_search → appeal_decision_flow → objection_report_generation`)에서 사용자가 이미 고지서를 업로드하고 완전한 이의제기 분석 결과까지 받은 경우에도, `law_ground_search`만 empty로 끝나면 `NEEDS_MORE_INFO_PROMPT`가 그대로 이어붙는다. 이 문구는 위반 유형·일시/장소·고지서 내용을 다시 알려달라는 내용이라, 이미 그 정보를 다 제공한 사용자에게는 혼란을 줄 수 있다.

로컬에는 시드 데이터가 없어 `law_ground_search`가 항상 empty이므로, 이 상태는 로컬에서 이의제기 플로우를 테스트할 때마다 재현된다. 전체 job 상태가 아니라 "empty로 끝난 노드가 어떤 노드인지"를 기준으로 안내 문구를 붙일지 조건을 좁히는 방안을 다음 작업으로 검토할 필요가 있다.

(라이브 재현은 하지 않았다 — fine_notice_objection 전체 실행은 gpt-4o + gpt-4o-mini×3 호출 비용이 들어서, `_combined_status` 코드 레벨 확인까지만 진행했다.)

## Supervisor LLM 활성화 시도 - 회귀 발견 후 원복

같은 세션에서 `SUPERVISOR_LLM_ENABLED=1`로 켜서 실제로 동작하게 만드는 작업도 시도했다.

- 켜자 gpt-5.4-mini 호출 자체는 성공했지만, 응답이 `_valid_llm_state_candidate` (`app/services/supervisor_llm_service.py:365-380`)의 엄격한 계약 검증을 통과하지 못해 `blocked_reason: "invalid_contract"`로 fail-closed 처리됐다.
- 그 결과 `POST /api/chat/messages/`가 `status: "supervisor_unavailable"` → HTTP 503을 반환하며 **채팅 전체가 막히는 회귀**가 발생했다 (`backend/chatbot/views.py:1214-1218`).
- 원인 추정: `_llm_request_payload`/`_llm_plan_request_payload` (`app/services/supervisor_llm_service.py:187-250`)가 모델에게 `required_output_keys`로 **키 이름만** 알려줄 뿐, `contract_version`의 정확한 문자열(`"supervisor_conversation.v1"`)이나 `stage`의 enum 값(`"need_more_input"` / `"agent_execution_ready"`) 같은 정확한 값 규칙은 프롬프트에 명시하지 않는다. gpt-5.4-mini가 이 암묵적 스키마를 맞추지 못한 것으로 보인다.
- 즉시 `.env`의 `SUPERVISOR_LLM_ENABLED`를 다시 `0`으로 되돌렸다 (파일에 이미 "Keep this off for deterministic local tests" 주석이 있었다). backend를 재기동해 채팅이 다시 정상(`status: "queued"`) 동작하는 것까지 확인했다.
- **미해결**: Supervisor LLM을 실제로 켜서 쓰게 만드는 작업은 이번에 완료하지 못했다. 프롬프트에 `contract_version`/`stage` 등 필드의 정확한 값을 명시적으로 지시하도록 고치고, 재검증(추가 OpenAI 비용 필요)하는 후속 작업이 필요하다.

## 로컬 프로세스 정리

`dev-local.ps1`을 여러 번 실행한 뒤 정리가 안 되어 `runserver`/`process_agent_work_items`/`process_uploaded_file_scans`가 각각 중복 실행 중이었다 (Django autoreload 특성상 하나의 실행이 여러 단계 프로세스 체인으로 뜨는 것은 정상이며, 실제 중복은 "서로 다른 루트 프로세스가 여러 개" 있는 경우였다). 각 서비스를 정확히 하나의 체인만 남도록 정리하고 재기동했다. 프론트(5173)는 건드리지 않았다.

## Next steps

1. ~~`_combined_status`/`compose_agent_response`가 job 전체가 아니라 empty로 끝난 노드 단위로 안내 문구를 붙이도록 조건을 좁히는 방안 검토.~~ → 2026-07-17에 evidence 기준으로 조건을 좁혀 해결 (아래).
2. Supervisor LLM 프롬프트에 `contract_version`/`stage` 등 필드의 정확한 값/enum을 명시적으로 지시하도록 수정한 뒤, `SUPERVISOR_LLM_ENABLED=1`로 재검증. (미해결, 유지)
3. ~~로컬 법령 검색용 시드 데이터(Neo4j/Postgres vector) 적재~~ → 2026-07-17에 진행, 데이터는 이미 있었고 연결/설정 문제였음이 밝혀짐 (아래).

## 2026-07-17 로컬 개발 비용 절감: OpenAI → Ollama 리다이렉트

작업 중 `law_ground_search`/`risk_gate`/`merit_gate`/`fine_notice_analysis`가 계속 실제 GPT API(gpt-4o, gpt-4o-mini)를 호출해 비용이 나가고 있어서, 로컬 작업 중에는 로컬 Ollama로 대체했다.

- `ollama cp qwen2.5:7b gpt-4o-mini`, `ollama cp gemma3:4b gpt-4o`로 하드코딩된 모델명과 동일한 이름의 로컬 alias 생성 (코드 무수정 — `ai/agents/*`는 다른 팀원 소유라 직접 안 건드림).
- `.env`에 `OPENAI_BASE_URL=http://localhost:11434/v1` 추가 — OpenAI Python SDK가 `base_url`을 명시하지 않은 모든 `OpenAI()` 호출을 이 값으로 리다이렉트하는 점을 이용했다.
- `SUPERVISOR_LLM_ENABLED=1`로 실제로 켜봤다가 `invalid_contract`로 채팅 전체가 503으로 막히는 회귀를 발견해 즉시 `0`으로 원복 (위 섹션 참고, 미해결 상태 유지).
- 부작용: `legal_rag_service.py`의 쿼리 임베딩 호출도 이 전역 리다이렉트를 상속받아버려서, 이후 실제 OpenAI 임베딩이 필요해졌을 때 `base_url`을 명시적으로 고정해야 했다 (아래 참고).

## 2026-07-17 검색결과 없음 안내 문구를 필드별로 구체화 + evidence 기준으로 조건 좁힘

사용자 요청: "부족한 필드를 더 자세히 요구하게 하고 싶어" — 고정 문구 대신 사용자가 이미 준 정보는 다시 묻지 않고, 진짜 부족한 항목만 짚어주도록 개선.

- `app/services/chat_orchestration_service.py`
  - `NEEDS_MORE_INFO_PROMPT` 고정 문자열을 제거하고, `user_text`/`attachments`를 키워드·정규식으로 검사해 "위반유형/일시장소/고지서" 3개 카테고리 중 실제로 빠진 것만 나열하는 로직(`_missing_info_categories`, `_needs_more_info_follow_up`)으로 교체.
  - `assistant_message`에 `core_answer`(안내문 안 섞인 순수 답변)와 `follow_up`(`{message, items}` 구조화 객체) 필드를 추가. 기존 `answer`/`summary`는 여러 소비처(`backend/chatbot/repositories.py`의 히스토리·리포트 요약 등)가 이미 의존하고 있어 하위 호환을 위해 그대로 유지(둘 다 안내문 포함 풀텍스트).
  - 안내문 부착 조건을 `status != "success"` → **`status != "success" and not evidence`**로 좁힘. 노드 하나가 이미 evidence 있는 결과를 줬으면(`status: partial`이어도) 더 이상 안내문을 안 붙인다 — 이 변경 전에는 기존 테스트(`test_agent_response_is_composed_from_execution_results`, evidence 있는 partial 케이스)가 이미 깨져 있었음을 발견해 같이 고쳤다.
  - "도로" 키워드가 "도로교통법"에 항상 오탐하는 버그를 발견해, 날짜/장소 판정을 정규식(`\d+(월|일|시|분)`) + 상대적 날짜·장소 키워드 목록으로 분리.
- `app/services/analysis_job_query_service.py`: `compose_response` 호출 시 `supervisor_state`/`attachments`를 같이 넘기도록 수정 (기존엔 `compose_agent_response`가 이 정보에 접근할 수 없었음).
- `app/web/FrontendAppShell.jsx` / `styles.css`: `core_answer`는 채팅 버블 본문에, `follow_up`은 별도의 amber 배경 박스(`FollowUpNote`)로 시각적으로 분리해서 표시.
- 테스트: `test_chat_orchestration_service.py`에 케이스 2개 추가, 기존 케이스에 `follow_up`/`core_answer` 검증 추가. `test_analysis_job_query_service.py`, `test_consultation_v2_contract.py`도 새 호출 시그니처/소스 문자열에 맞게 업데이트. `npm run build` 통과.
- 라이브 검증: 실제 API로 `"신호위반 관련 도로교통법 조문이 궁금해요"` 전송 → `follow_up.items == ["발생 일시와 장소", "받으신 고지서나 통지 내용"]`, "정확한 위반·분쟁 유형"은 이미 언급됐다고 판단해 제외됨을 확인.

## 2026-07-17 "리포트 준비중" 무한 대기 버그 수정

증상: 모든 질문에 답한 뒤에도 "리포트 준비중" 상태가 안 풀림.

- 원인: `isReportingPayloadReady()`(`FrontendAppShell.jsx`)가 `reportingPayload.stage`를 봤는데, 이 필드는 Supervisor LLM 경로에서만 채워진다(`supervisor_llm_service._normalized_reporting_payload`). 로컬 기본값인 폴백 경로(`SUPERVISOR_LLM_ENABLED=0`)가 만드는 `reporting_payload`엔 애초에 `stage` 필드가 없어서 조건이 영원히 `false`였다. 정작 "완료됨" 정보는 `supervisor_state.stage`(최상위)에 두 경로 모두에서 정확히 들어가 있었다 — 프론트가 엉뚱한 객체를 보고 있었다.
- 수정: `reportingPayload.stage` → `supervisorState.stage` 체크로 변경.

## 2026-07-17 리포트 노드 없는 시나리오에서 저장/다운로드 버튼 숨김

증상: 위 버그를 고치고 나니, `traffic_law_search`(법령검색만, `objection_report_generation` 노드가 플랜에 아예 없음)에서도 저장/다운로드 버튼이 뜨고, 누르면 "분석 워커가 리포트를 저장할 때까지 기다린 뒤 다시 시도해 주세요"가 무한 반복됨 — 이 시나리오는 애초에 리포트를 절대 만들지 않으므로 오해 소지 있는 문구였다.

- `hasReportGenerationNode(supervisorState)` 추가: `agent_input_packages`에 `objection_report_generation` 노드가 있을 때만 `ReportActionPanel`/`ReportReadyNotice`를 렌더링하도록 게이팅.
- `runCurrentReportAction`의 fallback 메시지도 리포트 노드가 없는 경우 "이번 상담 유형은 별도 리포트 문서를 만들지 않습니다"로 변경(다른 화면에서 호출될 경우 대비한 defense-in-depth).
- 검증: `npm run build` 통과, `test_consultation_v2_contract.py` 회귀 없음(기존에 있던 무관한 실패 2건은 `git stash`로 이 변경과 무관함을 확인).

## 2026-07-17 로컬 법령 검색 DB 연결 — 근본 원인은 "미적재"가 아니라 인프라/설정 불일치

사용자 질문("이 이슈 내가 db적재를 안 한거야 아니면 우리 db구조가 문제인거야?")에 대한 조사 결과, DB 구조 문제가 아니었다.

- `docker ps -a` 확인 결과 Postgres/Neo4j 컨테이너가 20시간째 내려가 있었고, 지금까지 테스트해온 backend는 `.venv`로 직접 띄운 프로세스라 docker network와 무관하게 로컬 `db.sqlite3`를 쓰고 있었다(`.env`에 `DJANGO_DATABASE_ENGINE=postgres`가 없었음). 응답의 `"backend": "postgresql"`은 실제 엔진이 아니라 계약상 고정 라벨이었다.
- `skn27-data-seed` 컨테이너가 47시간 전 `openai.AuthenticationError: 401`로 실패한 로그를 확인 — 그러나 `docker-compose.yml`의 `data-seed` 기본 커맨드는 애초에 `--provider sentence-transformers`(무료)라, 그 실패는 누군가 OpenAI 방식으로 수동 재실행하다 키 문제로 죽은 것으로 추정된다.
- **Postgres를 띄워서 확인해보니 `law_chunks`/`law_embeddings`에 이미 99,315건이 전부 적재되어 있었다** (`output/law_ingestion/embeddings/law_embeddings_openai.jsonl`, 7/10 생성분과 개수 일치). 재임베딩 자체가 불필요했다.
- 진짜 원인: 저장된 임베딩은 `openai`/`text-embedding-3-large`(1024차원)인데, `.env`의 쿼리 임베딩 설정은 `sentence-transformers`/`multilingual-e5-large`(우연히 같은 1024차원이지만 완전히 다른 임베딩 공간)였다 — 공간 불일치로 검색이 항상 비어 나올 수밖에 없었다.

### 조치

- `.env`: `DJANGO_DATABASE_ENGINE=postgres` 추가, `LEGAL_RAG_QUERY_EMBEDDING_PROVIDER=openai` / `LEGAL_RAG_QUERY_EMBEDDING_MODEL=text-embedding-3-large`로 변경 (저장된 공간과 맞춤 — 검색 1회당 실제 OpenAI 임베딩 API 초소액 과금, 사용자 승인 받고 진행).
- `app/services/legal_rag_service.py`의 `_openai_embedding()`에 `base_url="https://api.openai.com/v1"`을 명시적으로 고정 — 안 그러면 위에서 설정한 `OPENAI_BASE_URL`(Ollama 리다이렉트)을 상속받아 이 호출도 엉뚱한 곳으로 새서 또 실패했을 것.
- backend/agent-worker/file-scan-worker 재시작(파일 스캔 워커가 SQLite를 계속 보고 있어서 Postgres에 등록된 첨부파일을 못 찾는 문제도 같이 발견해 해결).
- 검증: `python -m pytest test/test_legal_rag_service.py` 25 passed. 라이브 API 호출로 `"신호위반 관련 도로교통법 조문이 궁금해요"` 재전송 → `status: "success"`, 조문 5건 검색됨(1위 "도로교통법 시행규칙 별표6의2 — 무인 교통단속용 장비 설치·관리기준", score 0.6, 관련성 있음).

### 남은 gap (이번엔 해결 안 됨)

`fine_notice_objection` 전체 플로우(고지서 이미지 업로드 → OCR → 법령검색 → 이의제기판단 → 리포트생성)를 실제로 재현해보니, 리포트 생성까지는 여전히 못 간다:

1. `law_ground_search`가 이제 조문을 찾긴 하지만, 신뢰도 평가(confidence check)에서 "낮음" 판정을 받아 `success`가 아니라 `partial`로 다운그레이드된다 — 버그라기보단 설계된 안전장치로 보임.
2. `appeal_decision_flow`의 `legal_evidence_status: "unavailable"`은 오늘 고친 RAG(`law_ground_search`)와는 별개로, `ai/agents/appeal_decision_flow/law_refs.py`에 하드코딩된 검증된 조문 세트를 참조하는 로직에서 나는 것으로 보인다. `hi20260204-maker` 소유 코드라 이번엔 건드리지 않았다.
3. 리포트 생성 게이트(`supervisor_reporting_handoff.gate`)는 `fine_notice_analysis`/`law_ground_search`/`appeal_decision_flow` 3개 노드가 전부 `success`여야 열리는데, 위 두 가지 때문에 계속 `partial`로 막혀 `objection_report_generation`이 실행되지 않고 `report_links`가 항상 빈 채로 남는다.

로컬에서 이의제기 리포트 생성까지 끝까지 확인하려면 위 1, 2번을 후속으로 봐야 한다.
