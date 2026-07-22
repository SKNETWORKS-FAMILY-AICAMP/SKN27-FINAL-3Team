---
title: "[chatbot] \"새 상담 시작\"을 눌러도 첨부 자료(sessionId)가 리셋되지 않음 — 의도 확인 필요"
labels: "question, frontend, needs-product-decision"
assignees: ""
---

## 배경

"챗봇에서 이미지를 첨부하면 다음 채팅 세션에도 반영되는지" 질문을 계기로 프론트/백엔드
코드를 확인한 결과, **"새 상담 시작" 버튼이 실제로는 새 세션을 만들지 않는다**는 것을
확인했다. 버그인지 의도된 설계인지 코드만으로는 판단할 수 없어 이슈로 남긴다.

## 확인된 동작

- `app/web/FrontendAppShell.jsx`의 `startNewConversation()`은 `chatMessages`,
  `analysisResponse`, `currentReport`, `reportActionStatus` 등 화면 표시용 상태만
  초기화하고, `sessionId`와 `registeredAttachments`는 그대로 둔다.
- `sessionId`(`setSessionId(...)`)가 갱신되는 지점은 다음 5곳뿐이다: 게스트 세션 생성,
  Google 로그인, 미리보기/더미데이터 모드, 로그아웃(빈 문자열로 초기화), 히스토리 항목
  복원. "새 상담 시작" 흐름은 이 중 어디에도 해당하지 않는다.
- 백엔드 `backend/chatbot/models.py`를 보면 `ChatSession.session_id`는 unique 필드이고,
  `UploadedFile`은 `ChatSession`에 FK로 연결된다(`session = models.ForeignKey(ChatSession, ...)`).
  즉 첨부파일은 "대화 턴"이 아니라 "세션(=사건/Case)" 단위로 귀속된다.
- 결과적으로: 브라우저를 새로고침하거나 로그아웃하기 전까지는, 사용자가 "새 상담 시작"을
  여러 번 눌러도 같은 `session_id`가 계속 재사용되고, 그 세션에 먼저 첨부했던 이미지/파일이
  이후 대화에도 계속 연결된 채로 남는다.

## 확인이 필요한 질문

"새 상담 시작"이 의미하는 바가 둘 중 무엇인지 기획/백엔드 담당자 확인이 필요하다.

- (A) 같은 사건(Case) 안에서 대화창만 비우는 기능 — 첨부파일이 사건 단위로 유지되는 게
  맞는 설계. 이 경우 현재 동작은 버그가 아니며, 대신 사용자에게 "이전에 첨부한 자료가
  이 사건에 계속 연결되어 있다"는 걸 UI로 알려주는 게 필요할 수 있음.
- (B) 완전히 새로운 사건/세션으로 분리되어야 함 — 이 경우 `startNewConversation()`에서
  `sessionId`를 새로 발급하고 `registeredAttachments`도 초기화해야 하는 프론트 버그.

## 관련 코드

- `app/web/FrontendAppShell.jsx`
  - `startNewConversation()` (약 1080번째 줄)
  - `registerAttachmentMetadata()` — 업로드 시 `session_id: activeSession`으로 첨부 등록 (약 497번째 줄)
  - `setSessionId(...)` 호출 지점 전체 (약 60, 235, 292, 326, 337, 479, 1195번째 줄)
- `backend/chatbot/models.py`
  - `class ChatSession` (181번째 줄) — `session_id` unique
  - `class UploadedFile` (241번째 줄) — `session = models.ForeignKey(ChatSession, ...)`

## 재현 방법

1. 챗봇 화면에서 이미지/파일을 첨부하고 상담 진행
2. "새 상담 시작" 클릭 (페이지 새로고침 없이)
3. 첨부 자료 목록/개수를 확인 — 이전 첨부가 그대로 남아 있음

## 제외 범위

- 이 이슈에서는 코드 수정을 하지 않았다. 조사 및 재현까지만 확인했고, 실제 수정은 (A)/(B)
  방향이 결정된 뒤 별도 작업으로 진행한다.

## 담당자

- 담당자:
- 연결 parent issue:

## 일정

- 시작 예정일:
- 최종 기준일:

## 참고 메모

- 최초 질문: "지금 챗봇에서 이미지 첨부하면 다음 채팅세션에 반영되는거야?"
