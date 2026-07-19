# Supervisor 패키지 메타데이터 정규화

## 목적

#229에서 남긴 후속 보안 경계를 닫는다. Supervisor LLM 또는 fallback 상태를
저장하기 전에 Agent 패키지의 첨부파일은 안정적인 `attachment_id` 선택자만
유지해야 한다. 원문 내용, 객체·저장소 위치, 스캔 정보, 모델이 임의로 넣은
메타데이터는 Supervisor handoff나 실행 계획에 저장하지 않는다.

## 범위

`app/services/supervisor_llm_service.py`의 다음 두 LLM 정규화 경로에 적용한다.

- `_safe_agent_input_packages`가 만드는 상담 상태 패키지
- `_safe_plan_agent_packages`가 만드는 분석 계획 패키지

라우팅, Agent 업무 규칙, 외부 LLM 호출, 파일 저장소, PR #230에서 도입한
Worker 실행 시점의 파일 재결합은 변경하지 않는다.

## 설계

1. 승인된 각 `node_code`는 서버가 만든 fallback 패키지부터 복원한다. schema
   version, node, 담당자, 허용된 payload 구조는 fallback 패키지가 기준이다.
2. LLM 후보의 payload는 fallback payload에 이미 존재하는 필드만 병합한다.
   후보에만 있는 필드는 버린다.
3. `payload.attachments`와 패키지 루트 `attachments`의 모든 항목은
   `{ "attachment_id": "..." }`로 바꾼다. 중복·잘못된 ID는 제거하고, 후보에
   쓸 수 있는 선택자가 없으면 fallback 선택자 목록을 유지한다.
4. 기존의 패키지 상태·누락 필드 정규화 규칙은 유지한다. 잘못된 패키지가
   정규화 때문에 유효한 패키지로 바뀌면 안 된다.
5. PR #230의 Worker 경계는 그대로 둔다. 실행 시점에는 scan-gated canonical
   attachment 목록을 기준으로 선택자 ID만 실제 파일 메타데이터와 재결합한다.

## 오류 처리

- 알 수 없는 패키지, 잘못된 패키지 구조, 중복·미승인 node code는 기존의
  fail-closed 검증 경로를 유지한다.
- 잘못된 첨부 항목은 복사하지 않고 버린다. 클라이언트나 LLM의 저장소 URI,
  원문 내용을 대신 사용하는 fallback은 추가하지 않는다.

## 검증

테스트를 먼저 작성해 state와 plan 정규화 경로 모두에서 `content_base64`,
저장소 URI, scan 메타데이터, 후보 전용 payload 필드가 제거되고 유효한
`attachment_id` 선택자는 남는지 검증한다. PR 준비 전에는 Supervisor LLM
집중 테스트, #229 Worker 경계 회귀 테스트, 관련 Django queue 테스트를 실행한다.

## 완료 기준

- 저장된 LLM·fallback 패키지의 첨부파일은 selector ID만 가진다.
- LLM 후보 패키지가 서버 fallback 계약에 없는 payload 필드를 추가할 수 없다.
- 기존의 유효한 패키지 동작과 Worker의 scan-gated 파일 재결합이 유지된다.
- 마스터 체크리스트는 병합·CI 확인 전까지 이 후속 작업을 진행 중으로 표시한다.
