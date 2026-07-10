# 이의가능성 판단 에이전트 — Supervisor 연동 세션 기록 (2026-07-09~10)

과태료·범칙금 이의가능성 판단 에이전트(`appeal_decision_flow`)를 다듬고, 실제로 Supervisor
챗봇 파이프라인에 배선해서 프론트까지 값이 보이게 만든 세션의 변경 기록이다. `dev` 브랜치
기준으로 작업했다(초반 RG/MG 개선 일부는 별도 feature 브랜치에서 시작해 이후 `dev`로 옮겨왔다).

---

## 요약 (다음 세션에서 이 문서만 읽고 맥락 복구할 때 참고)

**한 줄 요약**: `appeal_decision_flow`(RG=위험도·MG=승산 판정)는 로직상 잘 만들어져 있었지만
① Supervisor 노드 레지스트리에 아예 연결이 안 돼 있었고(`objection_report_generation`이
mock 응답만 반환), ② 연결한 뒤에도 Docker 이미지에 `ai/`·`etl/` 소스 자체가 빠져 있어서
컨테이너 안에서는 항상 `ModuleNotFoundError`로 죽고 있었다. 이 두 가지를 고쳐서 실제로 프론트
화면까지 판정 결과(승산·위험·관련 법률·기한)가 나오는 걸 확인했고, 그 과정에서 딸려나온 자잘한
버그(로그인 ALLOWED_HOSTS, PDF 한글 폰트, OCR/RG/MG temperature 미설정으로 인한 비결정성,
과태료/범칙금 오분류, Vite HMR이 Windows 바인드 마운트를 못 잡는 문제 등)도 같이 고쳤다.

**핵심 구조 이해**
- 판정 로직 소스: `ai/agents/appeal_decision_flow/`(그래프: `deadline_gate → law_code_check →
  reason_intake → RG‖MG(병렬) → verdict → guide_generation`). RG/MG는 OpenAI 호출, MG는
  `law_refs.py`의 코드 라우팅(notice_stage×위반유형)으로 참조 조문을 고정 선택 — RAG 검색이
  아니라 하드코딩 규칙이라 항상 신뢰 가능.
- Supervisor 쪽 진입점: `app/services/agent_node_service.py`의 `NODE_REGISTRY` 7개 노드 중
  `objection_report_generation`이 `appeal_decision_flow.graph`를 감싸는 sync 어댑터
  (`_run_objection_report_generation_adapter` / `_appeal_judgment_state`). `execution_mode=sync`
  요청일 때만 실제 코드가 돌고, 기본은 mock. 프론트는 기본값이 `sync`라 실사용 경로에서 실제로
  돈다.
- 프론트 표시: `app/web/FrontendAppShell.jsx`의 `SupervisorFlowPanel` 안에
  `AppealJudgmentInsightPanel`(판정 결과)·`LawGroundSearchInsightPanel`(법령 검색, 판정 있을 땐
  숨김) — `chat_response.supervisor_execution.node_results[].structured_result`를 그대로
  렌더링한다.
- 채팅 말풍선(`assistant_message`) 자체는 `app/services/chatbot_mock_service.py`의
  `MOCK_SCENARIO_RESULTS` 정적 fixture에서 나온다 — **판정 결과와 무관하게 고정 문구**이고
  이번 세션에서 안 건드렸다(알려진 한계로 남겨둠).

**환경/검증 방식 관련 주의사항 (다음에 또 헷갈리지 않도록)**
- `backend`/`ai`/`etl`은 `Dockerfile`에 `COPY`로 이미지에 구워 넣는 방식이라 **바인드 마운트가
  아니다** — 이 디렉터리들 밑 어떤 `.py`를 고쳐도 `docker compose build backend` →
  `docker compose up -d backend`로 재빌드·재기동해야 반영된다. `frontend`만 볼륨 마운트라
  즉시 반영된다(단 Windows에서는 `vite.config.js`에 넣어둔 `usePolling` 덕분에 정상 반영됨).
- 백엔드 코드를 컨테이너 안에서 직접 검증할 때 `docker exec -w /app -e
  PYTHONPATH=/app:/app/backend skn27-demo-backend python -c "..."`처럼 **cwd를 반드시 `/app`으로
  맞춰야 한다** — `/app/backend`로 잘못 잡으면 object storage 로컬 경로 계산이
  `backend/backend/...`로 중복되면서 파일을 못 찾는 것처럼 보이는 착시가 생긴다(실제로 이걸로
  한 번 잘못된 결론을 낼 뻔했다).
- `docker compose up -d <service>`는 필요할 때만 관련 컨테이너를 재생성하는데, 가끔 의도치 않게
  `postgres`까지 재생성될 수 있다 — named volume이라 데이터는 안 날아가지만, Postgres는
  최초 초기화 때의 비밀번호를 계속 쓰기 때문에 `.env`의 `POSTGRES_PASSWORD`를 나중에 바꾸면
  어긋난다(이번 세션에 실제로 겪음 → `ALTER USER`로 동기화).
- 이 저장소엔 아직 파이썬/Django 유닛테스트가 없는 부분에 대해 `docker exec`로 실제 함수
  (`chatbot_mock_service.submit_message` + `agent_node_service.execute_mock_plan`)를 직접
  호출해 응답 JSON을 까보는 방식으로 회귀 검증했다 — HTTP 레벨 재현(guest 세션 발급 → bearer
  토큰 → POST)은 인증 핸드셰이크가 번거로워서 꼭 필요할 때만 썼다.
- 로컬(`python -m pytest`, Docker 밖)에서 `test/unit/test_appeal_decision_flow_nodes.py`와
  `test/integration/test_appeal_decision_flow_graph.py`를 다른 테스트 파일과 **묶어서** 실행하면
  2건이 실패하는데, 각각 단독 실행하면 통과한다 — 오늘 세션에 Postgres에 실제 법령 데이터를
  적재하면서 로컬 머신이 처음으로 라이브 DB에 닿게 된 부작용으로 보이는 **기존부터 있던 테스트
  격리 문제**이지 이번 변경들이 만든 회귀가 아니다(git stash로 원상복구 후 재현해서 확인함).

**남은 것(요약)**: 채팅 말풍선 정적 문구, `이의가능성_판단_에이전트_미비점_조사_2026-07-09.md`의
미반영 항목들, OCR temperature 수정의 실사용 검증(실제 이미지로 반복 테스트 필요).

---

## 1. appeal_decision_flow 판정 로직 개선

| 파일 | 변경 |
|---|---|
| `ai/agents/appeal_decision_flow/state.py` | `risk_judgment_failed`, `reference_laws` 필드 추가 |
| `ai/agents/appeal_decision_flow/risk_gate.py` | LLM 호출 실패 시 `risk_judgment_failed=True` 설정 — `merit_judgment_failed`와 대칭. "위험을 감지한 것"과 "판단을 못 한 것"을 구분 |
| `ai/agents/appeal_decision_flow/merit_gate.py` | `get_merit_reference_articles()`로 계산한 `reference_laws`(실제 참조 조문 목록)를 반환값에 포함 |
| `ai/agents/appeal_decision_flow/law_refs.py` | `get_merit_reference_articles()` 신설 — `get_merit_context()`가 쓰던 조문 선택 로직을 재사용해 (법령명, 조문, 원문) 구조로 반환. RAG 재검색 없이 코드 라우팅만으로 "이번 판정에 실제로 쓴 조문"을 신뢰성 있게 노출 |
| `ai/agents/appeal_decision_flow/guide.py` | `_structured_result()`에 `merit_basis`(LLM 판단 근거 요약), `reference_laws` 노출 — 계산은 되고 있었는데 응답에서 누락돼 있었음 |
| `ai/agents/fine_notice_analysis/agent.py` | OCR(GPT-4o Vision) 호출에 `temperature=0` 추가 — 미설정 시 기본값 1.0으로 인해 같은 고지서 이미지도 호출마다 title/발급기관 추출이 흔들려 과태료/범칙금 분류가 비결정적이었음 |
| `ai/agents/appeal_decision_flow/prompts.py` | RG(`RISK_CLASSIFICATION_PROMPT`) 카테고리 B를 "범칙금이라는 단어" 기준에서 "전환 의도" 기준으로 재정의 + few-shot 예시 추가. MG(`MERIT_CLASSIFICATION_PROMPT`)에 "강조어 유무가 아니라 사실관계가 조문 요건에 해당하는지가 기준"이라는 지침 추가 — 패러프레이즈(표현만 다른 같은 의미 문장)에도 판정이 흔들리던 문제 수정 |

**발견 계기**: `temperature` 미설정 재현성 문제는 RG/MG에서 먼저 발견해 고쳤고, 같은 클래스의
버그가 `fine_notice_analysis`의 OCR 호출에도 있다는 걸 나중에 알아채 동일하게 수정했다.

---

## 2. 테스트 · 문서 (appeal_decision_flow)

| 파일 | 변경 |
|---|---|
| `test/test_appeal_decision_flow_paraphrase_robustness.py` | 신설 — RG 카테고리별·MG 승산별로 같은 의미의 다른 문장을 여러 개 넣어, 판정이 서로 일치하는지 확인하는 회귀 테스트 |
| `docs/architecture/appeal-judgment/이의가능성_판단_에이전트_설계정리.md` | 전체 흐름도를 v24로 갱신 — MG `merit=강함` 2차 판단(면제/감경) 분기를 다이어그램에 반영 |
| `docs/architecture/appeal-judgment/이의가능성_판단_에이전트_미비점_조사_2026-07-09.md` | 신설 — 그래프 분기별 미비점 조사 7건(relief_type 2차 호출 실패 미감지, 사유 부실 검증 부재, 프롬프트 인젝션 무방비 등), 확신도별 정리 |
| `docs/architecture/appeal-judgment/업데이트_기록_요약.md` | 신설 — `업데이트_기록.md`의 트러블슈팅 사례를 케이스당 1줄로 압축한 표 |

---

## 3. 인프라 (Docker / DB)

| 파일 | 변경 |
|---|---|
| `Dockerfile` | ① `fonts-noto-cjk` 설치 — PDF 리포트 다운로드에서 한글이 미매핑 글리프(`·`)로 깨지던 문제 해결. ② **`COPY ai ./ai`, `COPY etl ./etl` 추가 — 가장 근본적인 수정.** 기존엔 `app/`·`backend/`만 이미지에 들어가 있어서, `fine_notice_analysis`·`objection_report_generation` 등 모든 sync 어댑터가 컨테이너 안에서 `ModuleNotFoundError: No module named 'ai'`로 항상 조용히 실패하고 있었음 — 오늘 배선한 것도, 원래 있던 어댑터도 배포 환경에서는 한 번도 제대로 실행된 적이 없었던 상태였음 |
| `docker-compose.yml` | `DJANGO_ALLOWED_HOSTS`에 `backend` 추가 — 프론트가 도커 네트워크 안에서 `http://backend:8000`으로 프록시하는데 Django가 그 Host 헤더를 거부하고 있어서, 구글 로그인을 포함한 프론트→백엔드 요청 전체가 400으로 막혀 있었음 |
| `backend/chatbot/tests.py` | `extract_pdf_text()` 헬퍼가 PDF 추출 시 공백을 `\xa0`로 뽑아내는 걸 정규화 — 실제 렌더링엔 영향 없는 텍스트 추출 특성이었지만 테스트 문자열 비교가 깨졌던 것 수정 |
| (파일 변경 아님) | PostgreSQL 재생성 후 `.env`의 `POSTGRES_PASSWORD`와 실제 DB 비밀번호가 어긋난 문제를 `ALTER USER`로 동기화 |
| (파일 변경 아님) | `etl.legal.run_pipeline`로 법령DB 적재 — law_chunks 99,315건, Neo4j law_relations 351,808건 |

---

## 4. Supervisor 배선 — `objection_report_generation` 노드 연결

과태료 이의가능성 판단 로직은 다 만들어져 있었는데 Supervisor 노드 레지스트리에 등록만
안 돼 있어서, 사용자가 실제로 써도 항상 mock 캔 응답만 받고 있던 상태였다.

| 파일 | 변경 |
|---|---|
| `app/services/agent_node_service.py` | `NODE_REGISTRY["objection_report_generation"]` 상태를 `mock_contract_only` → `sync_adapter_ready`로 변경. `_should_use_sync_adapter`에 추가. `_run_objection_report_generation_adapter()` 신설 — `ai.agents.appeal_decision_flow.graph`를 실제로 호출. `_appeal_judgment_state()` 신설 — Supervisor의 `upstream_results`/`context.user_facts`/`slot_state`를 `AppealJudgmentState`로 매핑. `_infer_fine_type_from_text()` 신설 — OCR이 아직 안 돌았을 때(텍스트만 있는 턴) 채팅 텍스트에서 "범칙금"/"과태료" 키워드로 fine_type을 추론하는 폴백 |
| `test/test_agent_node_service.py` | 옛 mock-only 상태를 가정하던 테스트 2개를 새 sync 상태에 맞게 갱신(`appeal_decision_flow.graph.invoke`를 monkeypatch로 스텁 처리해 실제 LLM 호출 없이 어댑터 배선만 검증) |

---

## 5. 프론트엔드

| 파일 | 변경 |
|---|---|
| `app/web/FrontendAppShell.jsx` | 데모 페르소나(`정민서`) 샘플 문구 교체 |
| `app/web/vite.config.js` | `server.watch.usePolling` 추가 — Windows Docker Desktop 바인드 마운트가 파일 변경 이벤트를 컨테이너로 전달 못 해서, 프론트 수정이 반영 안 되는 문제를 여러 번 겪은 뒤 근본 수정 |
| `app/web/FrontendAppShell.jsx`, `app/web/styles.css` | 이미지 첨부 UI를 기본적으로 접혀 있는 "개발용 Agent 점검" 패널에서 메인 채팅 입력창으로 이동 — 로직은 이미 있었는데 일반 사용자 눈에 안 보이는 곳에 있었음 |
| `app/web/FrontendAppShell.jsx`, `app/web/styles.css` | `AppealJudgmentInsightPanel` 신설 — 판정상태·과태료/범칙금 구분·승산(merit)·신원노출 위험(risk_flag)·기한·법조항 검증·관련 법률(`reference_laws`)·안내문구(guide 6종)를 표시. `LawGroundSearchInsightPanel` 신설 — 다만 `objection_report_generation` 결과가 있을 땐 중복·무관 검색결과 방지를 위해 숨김 처리 |
| `app/web/FrontendAppShell.jsx` | `runCurrentReportAction`에 로그인 세션 자동 재시도 추가 — `authSessionId`는 남아있는데 access token이 만료/유실된 경우 `guest_report_download_requires_login` 에러로 죽는 대신, 자동으로 재로그인 후 재시도 |

---

## 남은 이슈 / 후속 검토 대상

- **채팅 말풍선(`assistant_message`) 텍스트는 여전히 정적 fixture**(`MOCK_SCENARIO_RESULTS`)에서 나온다 — 판정 결과(`AppealJudgmentInsightPanel`)는 이제 실제 값을 보여주지만, 대화창 상단 문구 자체는 판정과 무관하게 몇 가지 고정 패턴 중 하나로 나온다. 별도 작업으로 분리 필요.
- `이의가능성_판단_에이전트_미비점_조사_2026-07-09.md`에 정리된 나머지 미반영 항목(사유 부실 검증, 프롬프트 인젝션 방어 등).
- OCR `temperature=0` 수정은 재현성을 높이지만 완전한 결정론을 보장하진 않음 — 실제 이미지로 반복 검증 필요.
