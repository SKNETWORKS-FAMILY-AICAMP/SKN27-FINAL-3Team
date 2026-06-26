# #56 Django mock 챗봇 API와 응답 fixture

| 항목 | 내용 |
|---|---|
| Issue | `#56 django chatbot mock api fixtures` |
| Parent | `#55` |
| Related | `#22`, `#29`, `#40`, `#58` |
| Scope | 실제 Agent 호출 없이 mock response fixture로 챗봇 API 응답 구성 |
| Status | mock service 초안 |
| 작성일 | 2026-06-26 |

## 1. 추가 파일

| 파일 | 역할 |
|---|---|
| `app/services/chatbot_mock_service.py` | 순수 Python mock fixture와 service 함수 |
| `app/api/django_chatbot_mock_views.py` | Django에 연결 가능한 optional view adapter |

## 2. Endpoint 후보

| Endpoint | 함수 | 목적 |
|---|---|---|
| `POST /api/mock/chat/sessions` | `create_chat_session` | mock chat session 생성 |
| `POST /api/mock/chat/messages` | `submit_chat_message` | 사용자 질문/첨부 입력 후 mock 분석 결과 반환 |
| `POST /api/mock/reports` | `report_action` | 리포트 저장/다운로드 mock action |

## 3. 응답 fixture 상태

| 상태 | 포함 내용 |
|---|---|
| `pending` | 입력 분류 중 progress |
| `partial` | 추가 질문, 제한된 분석 카드 |
| `failed` | 분석 가능한 입력 없음 |
| `success` | 고지서/과실비율 분석 카드와 report action |

## 4. 중간발표 우선 시나리오

MCP, 외부 법령 API, 최신 판례 조회는 중간발표 범위에서 제외한다. mock service는 앱 흐름 확인을 위해 다음 두 시나리오를 우선 지원한다.

| Scenario | routing_intent | 목적 |
|---|---|---|
| `fine_notice` | `objection_request` | 고지서 분석, 이의신청서 초안, 리포트 저장/다운로드 흐름 |
| `fault_ratio` | `fault_ratio` | 사고 설명 기반 과실비율 쟁점, 유사 사례 후보, 추가 증거 안내 흐름 |

과실비율 시나리오는 수치를 확정하지 않고 `accident_type_candidates`, `issue_tags`, `similar_cases`, `reliability_score`, `ratio_range_label`, `limitations`를 반환한다.

## 5. 구현 제외

- 실제 Django project settings
- URL router 등록
- 실제 DB 저장
- 실제 Agent, RAG, MCP, LLM 호출
- 실제 인증/JWT 검증

## 6. 검증 필요

- Django 프로젝트 생성 후 URLConf 연결 방식
- `#22` 공통 result envelope와 필드명 정렬
- `#29` Supervisor routing rule과 fixture intent 정렬
- 실제 업로드 파일 처리 endpoint와 연결

