# #57 React mock 챗봇 화면과 상태 흐름

| 항목 | 내용 |
|---|---|
| Issue | `#57 react chatbot mock flow` |
| Parent | `#55` |
| Related | `#40`, `#56`, `#58` |
| Scope | 질문 입력, 첨부 상태 표시, 진행 상태, 결과 카드, 리포트 action UI |
| Status | React component 초안 |
| 작성일 | 2026-06-26 |

## 1. 추가 파일

| 파일 | 역할 |
|---|---|
| `app/web/ChatbotMockFlow.jsx` | React mock 챗봇 화면 컴포넌트 |

## 2. 포함 상태

| 상태 | UI 표시 |
|---|---|
| `pending` | 분석 중 progress |
| `partial` | 추가 질문과 제한된 결과 카드 |
| `failed` | 재입력 안내 |
| `success` | 고지서 분석, 법령 근거, 리포트 action |

## 3. 동작 기준

- `POST /api/mock/chat/messages`를 우선 호출한다.
- API가 연결되지 않아도 프론트 fallback mock으로 화면 상태를 확인할 수 있다.
- 리포트 저장/다운로드 action은 `POST /api/mock/reports`를 우선 호출한다.
- 실제 LLM, Agent, RAG 호출은 포함하지 않는다.

## 4. 검증 필요

- 실제 React 프로젝트 생성 후 import 경로와 bundler 설정
- CSS/design system 적용
- 파일 업로드 컴포넌트 연결
- 인증 실패와 비회원 정책 UI
- `#56` Django mock endpoint와 실제 URL 일치 여부

