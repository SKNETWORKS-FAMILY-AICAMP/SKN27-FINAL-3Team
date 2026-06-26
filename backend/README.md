# Django Demo Backend Workspace

중간발표용 mock API 워크스페이스다. 실제 Agent, RAG, MCP, 외부 API 호출 없이 프론트엔드가 앱 흐름을 붙일 수 있도록 최소 Django endpoint를 제공한다.

## 실행

```powershell
python backend/manage.py runserver 127.0.0.1:8000
```

## 주요 endpoint

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health/` | backend health와 demo scenario 목록 |
| `GET` | `/api/mock/chat/scenarios/` | `fine_notice`, `fault_ratio` 시나리오 목록 |
| `POST` | `/api/mock/chat/sessions/` | mock chat session 생성 |
| `POST` | `/api/mock/chat/messages/` | 챗봇 mock 분석 응답 반환 |
| `POST` | `/api/mock/reports/` | 리포트 저장/다운로드 action mock |
| `GET` | `/api/mock/reports/{report_id}/download/` | mock report 다운로드 |

## 테스트

```powershell
python backend/manage.py check
python backend/manage.py test chatbot
python -m pytest test/test_chatbot_mock_service.py
```

## 발표 우선 범위

- 과태료/이의신청 흐름: `mock_scenario=fine_notice`
- 과실비율 흐름: `mock_scenario=fault_ratio`
- MCP, 최신 법령 조회, 외부 API, 실제 ML/RAG 호출은 제외

