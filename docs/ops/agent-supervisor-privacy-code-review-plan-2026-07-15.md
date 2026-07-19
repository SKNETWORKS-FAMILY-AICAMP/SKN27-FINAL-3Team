# Agent·Supervisor·채팅 보안 코드 리뷰 계획

작성일: 2026-07-15

작업 브랜치: `feat-agent-flow-security-review`

기준 원격: `origin/dev` `107a9b3`

연계 문서: `docs/ops/chat-input-privacy-security-update-2026-07-14.md`

## 2026-07-16 Supervisor 구현 진행 상태

완료:

- `general_consultation`, `fine_notice_procedure`, `fine_notice_analysis`,
  `accident_initial_consultation`, `traffic_law_search` 라우팅 경계 분리
- `consultation_fact_state_reducer`, `case_promotion_gate`, `final_response_merge` 등록 및 구현
- 모든 일반 분석 계획에 `input_context_validation` → 업무 Agent →
  `agent_result_validation` → `final_response_merge` 경계 적용
- 명시적 문서 생성 요청이 있을 때만 보고서 노드를 계획하고, 검증 결과의
  `report_ready=true`일 때만 실제 호출
- 검증에서 승인된 Agent 결과만 사용자 응답에 노출
- 자유서술 사고 사실은 Supervisor LLM이 후보만 추출하고, 후보의 병합·충돌·확정 상태는
  결정론적 reducer가 처리. LLM 비활성화 시에는 추정하지 않고 필드별 역질문으로 수집
- 라우팅 키워드, intent별 plan, 보고서 요청 판별어를
  `app/config/supervisor_routing_policy.v1.json`으로 외부화하고 계약 버전을 검증
- Agent별 근거 필수 규칙과 보고서 선행 Agent 조합도 같은 정책 파일로 외부화

비-Supervisor Agent의 남은 문제와 담당·구현 이력은
`docs/ops/non-supervisor-agent-issues-2026-07-16.md`로 분리했다.

## 1. 판정 기준

담당과 구현 이력을 다음 세 항목으로 분리한다.

- **업무 담당**: `docs/wbs-owner-deliverable-plan.md`에 명시된 책임 영역
- **실제 구현자**: `origin/dev`의 해당 경로 커밋 작성자 집계
- **통합 수정 담당**: Agent를 Supervisor·Django·UI에 연결하는 공통 계층 담당

미커밋 파일은 Git으로 작성자를 확정할 수 없다. 특히 개인정보 보안 계획 문서는 현재
미추적 파일이므로 내용의 작성자를 Git 이력으로 단정하지 않는다.

## 2. Agent·기능별 담당과 실제 구현 이력

| Agent/기능 | 업무 담당 | 실제 주요 구현 이력 | 현재 판정 | 다음 수정 주체 |
|---|---|---|---|---|
| Supervisor·라우팅·최종 통합 | 요청자/QA `hi20260204-maker` | `chat_orchestration_service.py` 5회, `ai/supervisor` 1회, `agent_node_service.py` 19회가 LeeHyerim 중심 | 실제 LLM 선택 연결은 있으나 fallback plan이 질문 종류와 무관하게 보고서까지 조기 예약. 최종 검증/병합 노드 미실행 | 통합 계층은 `hi20260204-maker`; 도메인 필수조건은 각 Agent 담당과 공동 검토 |
| `fine_notice_analysis` | 필주 `workzion2` | kama42kanne 9회, LeeHyerim 4회, LeeJaekang 1회 | 실제 sync adapter 연결. 첨부 없이 텍스트만 있어도 분석 경로가 열리는 계약은 보강 필요 | 도메인 판정·OCR은 `workzion2`, 어댑터/게이트는 `hi20260204-maker` |
| `law_ground_search` | 동혁 `techshin31` | LeeHyerim 7회, techshin31 3회 | 실제 adapter/RAG 경계 존재. 이 브랜치에서 retrieval provenance와 공통 출력 필드를 정규화하고 기본 Neo4j 비밀번호를 제거 | 법령 데이터·검색 품질은 `techshin31`, 출력 계약 통합은 `hi20260204-maker` |
| `appeal_decision_flow` | 과태료 흐름 기준 필주 `workzion2` | kama42kanne 19회, LeeHyerim 4회, LeeJaekang 1회 | 실제 LangGraph 연결 확인. 법령 fail-closed는 원격 최신에 강화됨. 모델 설정 하드코딩은 이 브랜치에서 제거 | 판단 규칙은 `workzion2`, 런타임/보안/통합은 `hi20260204-maker` |
| `text_ml_case_search` | 재강 `leejaegang27` | `ai/agents` wrapper는 LeeHyerim 8회, ETL Agent는 LeeHyerim 2회·LeeJaekang 1회 | 실제 sync adapter는 연결. 대화에서 확정된 사고 사실이 전달되지 않아 호출 전 상태 수집이 막힘 | ML/RAG 결과는 `leejaegang27`, 상태/어댑터 연결은 `hi20260204-maker` |
| 교통사고 사실확인원 OCR | 재강 `leejaegang27` | OCR 구현 `a0516b8` LeeJaekang, 마스킹 통합 `8e457bc`·`3ce136c` LeeHyerim | 구현은 존재하지만 `NODE_REGISTRY`와 실행 계획에 미등록 | OCR 계약은 `leejaegang27`, registry/plan 연결은 `hi20260204-maker` |
| `vision_media_analysis` | 주희 `ohjuheecode` | 현재 Agent 경로 커밋은 LeeHyerim 1회이며 실구현 파일은 없음 | registry만 있고 `mock_contract_only`; 생성형/실모델 미연결 상태 | Vision/DL 구현은 `ohjuheecode`, adapter/plan 연결은 `hi20260204-maker` |
| `objection_report_generation` | 요청자/QA `hi20260204-maker` | LeeHyerim 4회 | 실제 sync adapter와 DOCX 경로가 연결됨. 선행 결과 실패 시 보고서 차단 조건 보강 필요 | `hi20260204-maker` |
| 개인정보 마스킹·파일 보안 | 요청자/QA·통합 영역 | `pii_masking.py` LeeHyerim 2회, `file_scan_service.py` LeeHyerim 3회·LeeJaekang 1회 | OCR/로그/파일은 부분 보호였으나 채팅 원문 ingress가 비어 있었음 | 정책·통합은 `hi20260204-maker`; 법적 보존 결정은 팀/서비스 책임자 |

## 3. 최근 48커밋 확인

- merge commit: 24개
- 내용 commit: 24개
- 내용 commit 작성자: LeeHyerim 19개, LeeJaekang 3개, kama42kanne 2개
- 최신 주요 변경: production RAG seed, non-DL runtime mock 제거, Text ML 가짜 근거 차단,
  Supervisor reporting handoff, appeal RAG fail-closed, AWS 저비용 pilot
- 현재 로컬은 원격보다 41커밋 뒤인 기존 dirty worktree에서 분기했다. 원격 변경을 pull/merge하면
  기존 35개 수정 파일과 충돌할 수 있으므로 코드 리뷰 전 별도 통합 절차가 필요하다.

## 4. Supervisor 전체 흐름 점검

### 4.1 입력 스키마

확인 결과:

- `AgentAdapterInput`과 구조 검증 함수는 존재한다.
- 기존 런타임은 검증 함수를 호출하지 않아, 테스트만 존재하고 실제 실행 전 검증은 생략됐다.
- 이 브랜치에서 `execute_agent_node()`가 입력·context 계약을 검사하고, 실패 시 adapter를
  호출하지 않도록 연결했다.
- 개인정보 Gateway가 `user_text`, 대화 이력, facts, context, slot state를 마스킹한 뒤
  Supervisor로 전달하도록 연결했다.

남은 문제:

- 구조 검증은 연결됐지만 Agent별 의미 검증은 아직 분산돼 있다.
- 예: `fine_notice_analysis`의 실제 첨부 필수, appeal의 검증된 법령 근거 필수,
  Text ML의 확정 사고 사실 필수 조건을 공통 readiness 계약으로 승격해야 한다.

### 4.2 호출 플랜

확인 결과:

- 일반 미일치 질문은 `traffic_law_search`로 기본 라우팅된다.
- 과태료 키워드만 포함해도 OCR→법령→이의판단→보고서 전체 플랜이 만들어진다.
- 사고 질문은 `facts` 네 항목을 요구하지만 프론트가 다음 턴에 facts를 보내지 않아 같은
  질문이 반복된다.
- LLM planner의 node allowlist는 fallback plan에 있는 노드로 제한된다.
- prompt injection 입력이 system/tool/node 권한을 바꿀 수 없다는 system 규칙은 이
  브랜치에서 명시했다.

필수 수정:

1. 일반 상담/절차 질문/문서 분석/사고 초기 상담/사고 정밀 분석 intent 분리
2. 세션별 fact state reducer 추가
3. readiness가 충족되기 전 Agent plan 생성 금지
4. `agent_result_validation`을 보고서 전 필수 노드로 실행
5. `final_response_merge`를 registry에 등록하고 실제 사용자 응답 생성기로 연결

### 4.3 Agent 출력과 최종 응답

확인 결과:

- 공통 output envelope와 검증 함수가 존재했다.
- 기존 실행 경로는 output 검증을 호출하지 않았다.
- 이 브랜치에서 output 검증 실패 결과가 Supervisor handoff와 다음 Agent로 전달되지 않도록
  실행 경계에 연결했다.
- 현재 최종 답변은 Agent summary 문자열을 단순 연결한다. `final_response_merge`는 handoff
  대상 이름으로만 존재하고 registry/실행 구현이 없다.
- 보고서 준비 여부는 `실패 결과 없음`만으로 계산돼, `partial` 결과도 보고서 준비 완료가 될 수 있다.

### 4.4 부족 정보 역질문

확인 결과:

- 빈 입력과 사고 필수 facts 누락에 대한 `pending_questions` 계약은 존재한다.
- 실제 브라우저에서는 후속 답변 후에도 같은 도로 형태 질문이 반복됐다.
- 원인은 UI payload에 `facts`가 없고 서버도 conversation history에서 facts를 추출·병합하지
  않기 때문이다.

필수 수정:

- `consultation_fact_state_reducer`: 이전 facts + 현재 답변 + 출처 + confidence + conflict 병합
- `missing_input_question`은 별도 생성형 Agent보다 reducer 결과를 Supervisor가 문장화
- 후속 턴 회귀 테스트: 질문 1회 → 사용자 답변 → 해당 field가 missing 목록에서 제거

## 5. 생성형 Agent 연결과 테스트 설계 판정

확인된 사실:

- non-DL Agent 런타임은 `execute_agent_node/execute_agent_plan`의 실제 sync adapter로 연결됐다.
- 과거 호환 함수 `execute_mock_node()`도 non-DL Agent에서는 실제 adapter로 위임한다.
- 다수 기존 테스트는 이름과 import가 여전히 `execute_mock_*`이고 `_run_sync_adapter`를 mock한다.
  이 테스트들은 배선만 검증하며 실제 Agent 그래프나 provider 연결을 증명하지 않는다.
- appeal 실제 GPT 테스트는 `OPENAI_API_KEY`와 `--run-live`가 모두 있어야 한다. 일반 pytest에서는
  연결돼 있어도 7개가 skip된다.
- `test_agent_execution_service.py`의 appeal graph 테스트는 provider를 mock하지만 실제 LangGraph
  진입과 upstream 결과 전달을 확인한다.

권장 테스트 3계층:

1. contract unit: provider mock, 입력/출력/분기 결정론 검증
2. local adapter integration: `_run_sync_adapter`를 mock하지 않고 실제 graph/RAG port 진입 검증
3. live smoke: `--run-live` 및 secret store 사용, 별도 CI job에서만 실행

테스트 이름에서 `mock`을 제거하거나 `legacy_compat`로 바꿔 실제 연결 상태가 오해되지 않게 한다.

## 6. 개인정보·보안 설계 및 현재 브랜치 구현

이 브랜치에서 구현한 P0:

- `app/security/chat_input_privacy.py` 중앙 Gateway 추가
- secret·JWT/API key, 주민번호, 면허번호 차단
- 전화·이메일·주소·성명·차량번호 마스킹
- 최대 입력 길이 환경 설정
- canonical chat, canonical analysis job, legacy mock Supervisor 우회 방지
- ChatMessage와 scalar metadata 저장 전 재마스킹
- Supervisor prompt에서 사용자/첨부/RAG 내용을 비신뢰 데이터로 분리
- 분류명과 개수만 반환하고 원문은 오류·metadata에 넣지 않음

이번 브랜치에서 제외한 정책 변경:

- 기존 DB 원문 일괄 삭제/마이그레이션
- 증빙 원본 파일의 전면 PII 차단
- 원문 별도 암호화 저장소
- 운영 CloudWatch·S3·백업 보존기간 변경

위 항목은 법적 보존과 제품 UX 결정 후 별도 이슈로 진행한다.

## 7. 코드 리뷰 구현 우선순위

### P0 — 리뷰 전 필수

1. 현재 브랜치 privacy Gateway·Agent 계약 검증 리뷰 및 원격 dev 통합 전략 결정
2. 세션 fact reducer와 역질문 회귀 테스트
3. general consultation 라우팅 및 보고서 조기 실행 제거
4. `agent_result_validation` 실제 실행과 report gate
5. 실제 adapter integration 테스트를 mock 기반 테스트와 분리

### P1 — Agent 품질

1. 교통사고 사실확인원 OCR registry 연결
2. law output 계약 변경에 맞춘 frontend/DB retrieval 표시 회귀 검토
3. Text ML 확정 facts 입력 계약과 빈 RAG fail-closed
4. Vision Agent 실구현 또는 capability 비노출
5. `final_response_merge` 구현

### P2 — 운영/정리

1. `execute_mock_*`, `chatbot_mock_service` 호환 이름과 dead code 제거
2. registry의 owner metadata와 GitHub CODEOWNERS/Issue 담당 동기화
3. 기존 데이터·백업·로그 보존 정책 확정 후 migration/runbook
4. AWS staging privacy E2E 증적

## 8. 2026-07-16 최종 검증

```powershell
.\.venv\Scripts\python.exe -m pytest -q
# 478 passed, 37 skipped

.\.venv\Scripts\python.exe backend\manage.py test chatbot
# 181 tests, OK

cd app/web
npm run build
# Vite production build success, 32 modules transformed
```

외부 LLM live 테스트는 API key와 `--run-live`가 필요한 별도 검증이므로 위 일반 pytest에서는
의도적으로 skip된다. 이번 작업에서는 Git stage, commit, rebase, merge, push를 실행하지 않았다.
