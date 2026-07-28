# Checklist Non-Human Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사람 승인, 유료 호출 승인, 외부 실환경 검증 없이 진행 가능한 마스터 체크리스트 미완료 항목과 2026-07-26 오류 메모 5건을 순차 구현해 제품의 런타임 정합성과 준비 상태를 끌어올린다.

**Architecture:** 첫 번째 레이어는 즉시 재현 가능한 런타임 결함 4개와 `appeal_decision_flow` 정합화다. 두 번째 레이어는 사건 메모리, 최신성 노출, adapter E2E, 구조화 입력 UX, CloudFront 코드 준비를 트랙 단위로 독립 구현해 각각 테스트와 체크리스트 근거를 남긴다.

**Tech Stack:** Python 3, Django, pytest, React/Vite, JSON policy files, Terraform, PowerShell deploy scripts

## Global Constraints

- 사람 게이트, 유료 호출 승인, 운영 DB 실제 적재, CloudFront/Google OAuth/RunPod 실환경 smoke는 구현 범위에서 제외한다.
- 체크리스트는 실제로 전진한 범위만 갱신하고, 사람 게이트가 남아 있으면 `[x]`로 올리지 않는다.
- 기존 attachment 우선 라우팅, public API contract, DB schema 안정성을 불필요하게 깨지 않는다.
- 새 기능은 가능한 한 기존 서비스 경계 안에 추가하고, 새 파일이 필요할 때만 책임이 분명한 단위로 분리한다.
- 각 Task는 독립 커밋 단위로 끝내고, 테스트 근거를 남긴다.

---

### Task 1: 라우팅과 세션 재사용 결함을 먼저 고정한다

**Files:**
- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `app/services/supervisor_routing_service.py`
- Modify: `app/config/supervisor_routing_policy.v1.json`
- Create or Modify: `test/test_supervisor_routing_service_quick_examples.py`
- Modify: `test/test_frontend_auth_session_contract.py`

**Interfaces:**
- Consumes: `startNewConversation()`, `route_supervisor_input(user_text, attachments)`
- Produces: 새 상담 시 빈 `session_id`, AND keyword group을 지원하는 라우팅 규칙, `"벌금 걱정"` 오분류 회귀 테스트

- [ ] **Step 1: 새 상담 시 sessionId가 비워지는 실패 테스트를 먼저 추가한다**

```javascript
it("clears the previous session id when starting a new conversation", async () => {
  const state = buildShellState({ sessionId: "ses_old" });
  startNewConversation(state);
  expect(state.sessionId).toBe("");
});
```

- [ ] **Step 2: 라우팅 서비스에 AND keyword group 실패 테스트를 추가한다**

```python
def test_fine_notice_keyword_group_does_not_override_accident_context():
    intent = route_supervisor_input(
        "고속도로에서 벌금 걱정이 되는데 사고 과실비율이 어떻게 되나요?",
        [],
    )
    assert intent == "accident_initial_consultation"


def test_fine_notice_keyword_group_still_routes_real_notice_procedure():
    intent = route_supervisor_input("과태료 벌금 걱정 때문에 이의신청 절차를 알고 싶어요", [])
    assert intent == "fine_notice_procedure"
```

- [ ] **Step 3: 테스트가 실제로 실패하는지 확인한다**

Run:

```powershell
python -m pytest -p no:timeout -p no:cacheprovider test/test_supervisor_routing_service_quick_examples.py -q
python -m pytest -p no:timeout -p no:cacheprovider test/test_frontend_auth_session_contract.py -q
```

Expected: 기존 단순 OR 키워드 매칭과 `sessionId` 미초기화 때문에 최소 한 테스트가 실패한다.

- [ ] **Step 4: 최소 구현으로 결함을 고친다**

```python
def _keyword_groups(raw_value: Any) -> list[tuple[str, ...]]:
    groups = []
    for item in raw_value or []:
        if isinstance(item, str):
            term = _text(item).lower()
            if term:
                groups.append((term,))
        elif isinstance(item, list):
            terms = tuple(_text(sub).lower() for sub in item if _text(sub))
            if terms:
                groups.append(terms)
    return groups


if groups and any(all(term in normalized_text for term in group) for group in groups):
    return intent
```

```json
"keywords": ["과태료", "범칙금", "이의신청", ["벌금", "걱정"]]
```

```javascript
function startNewConversation() {
  setSessionId("");
  setChatMessages([]);
  setAnalysisResponse(null);
}
```

- [ ] **Step 5: 회귀 테스트를 다시 돌린다**

Run:

```powershell
python -m pytest -p no:timeout -p no:cacheprovider test/test_supervisor_routing_service_quick_examples.py -q
python -m pytest -p no:timeout -p no:cacheprovider test/test_frontend_auth_session_contract.py -q
```

Expected: PASS

- [ ] **Step 6: 커밋한다**

```powershell
git add app/web/FrontendAppShell.jsx app/services/supervisor_routing_service.py app/config/supervisor_routing_policy.v1.json test/test_supervisor_routing_service_quick_examples.py test/test_frontend_auth_session_contract.py
git commit -m "fix: prevent stale routing and session reuse"
```

### Task 2: law_ground_search fallback과 유사도 필터를 연결한다

**Files:**
- Modify: `app/services/agent_node_service.py`
- Modify: `app/services/legal_rag_service.py`
- Modify: `test/test_agent_node_service.py`
- Create or Modify: legal RAG query regression tests under `test/`

**Interfaces:**
- Consumes: `_run_law_ground_search_adapter(agent_input, adapter_context)`, `_query_pgvector_rows(...)`
- Produces: 실제 주입된 `OpenAILawKeywordExtractor`, `LEGAL_RAG_MIN_SIMILARITY_SCORE`, low-similarity 결과 제거

- [ ] **Step 1: adapter가 추출기를 실제로 주입하는 실패 테스트를 추가한다**

```python
def test_law_ground_search_adapter_passes_llm_extractor(monkeypatch):
    captured = {}

    def fake_run(agent_input, context, llm_extractor=None, neo4j_session=None):
        captured["extractor"] = llm_extractor
        return {"status": "success", "structured_result": {"law_provisions": []}}

    monkeypatch.setattr("ai.agents.law_ground_search.run_law_ground_search", fake_run)
    _run_law_ground_search_adapter({}, {})
    assert captured["extractor"] is not None
```

- [ ] **Step 2: similarity threshold 실패 테스트를 추가한다**

```python
def test_pgvector_query_filters_results_below_similarity_threshold(fake_connection, monkeypatch):
    monkeypatch.setenv("LEGAL_RAG_MIN_SIMILARITY_SCORE", "0.75")
    rows = _query_pgvector_rows(
        fake_connection,
        query_vector=[0.1, 0.2],
        top_k=3,
        source_type="law",
        allowed_source_types=("law",),
        effective_at=date(2026, 7, 27),
        embedding_space={"provider": "openai", "model": "text-embedding-3-large", "dimensions": 1024},
    )
    assert rows == []
```

- [ ] **Step 3: 테스트가 실패하는지 확인한다**

Run:

```powershell
python -m pytest -p no:timeout -p no:cacheprovider test/test_agent_node_service.py -q
python -m pytest -p no:timeout -p no:cacheprovider test -k "legal_rag and similarity" -q
```

Expected: extractor 미주입과 threshold 미적용으로 실패한다.

- [ ] **Step 4: 최소 구현을 추가한다**

```python
from ai.agents.law_ground_search.llm_extractor import OpenAILawKeywordExtractor

raw_output = run_law_ground_search(
    agent_input,
    adapter_context,
    llm_extractor=OpenAILawKeywordExtractor(),
)
```

```python
def _float_setting(name: str, default: float) -> float:
    try:
        return float(_setting(name, str(default)))
    except (TypeError, ValueError):
        return default
```

```sql
AND (1 - (e.embedding_vector <=> %s::vector)) >= %s
ORDER BY e.embedding_vector <=> %s::vector
LIMIT %s
```

- [ ] **Step 5: 관련 테스트를 다시 돌린다**

Run:

```powershell
python -m pytest -p no:timeout -p no:cacheprovider test/test_agent_node_service.py -q
python -m pytest -p no:timeout -p no:cacheprovider test -k "legal_rag and similarity" -q
```

Expected: PASS

- [ ] **Step 6: 커밋한다**

```powershell
git add app/services/agent_node_service.py app/services/legal_rag_service.py test/test_agent_node_service.py
git commit -m "fix: wire law ground fallback and similarity guard"
```

### Task 3: fine notice와 appeal_decision_flow 정합성을 고정한다

**Files:**
- Modify: `test/test_chat_orchestration_service.py`
- Modify: `test/test_agent_node_service.py`
- Modify: `docs/ops/project-readiness-master-checklist.md`

**Interfaces:**
- Consumes: `submit_message(...)`, OCR confirmation path, `report_required_nodes`
- Produces: OCR 확인 완료 후 `appeal_decision_flow` 포함 회귀, 체크리스트 정합화 근거

- [ ] **Step 1: 현재 동적 삽입 규칙을 고정하는 회귀 테스트를 정리한다**

```python
def test_confirmed_ocr_fields_enable_law_and_appeal_only_after_first_pass():
    response = submit_message({...})
    assert [step["node_code"] for step in response["analysis_plan"]["steps"]] == [
        "input_context_validation",
        "fine_notice_analysis",
        "law_ground_search",
        "appeal_decision_flow",
        "agent_result_validation",
        "final_response_merge",
    ]
```

- [ ] **Step 2: 테스트와 체크리스트 설명이 현재 코드와 모순되는지 확인한다**

Run:

```powershell
python -m pytest -p no:timeout -p no:cacheprovider test/test_chat_orchestration_service.py -q
```

Expected: 현재 동작을 고정하는 테스트는 이미 통과하거나, 설명 불일치를 드러내는 테스트만 보강하면 된다.

- [ ] **Step 3: 체크리스트 문장을 현재 런타임 모델에 맞게 갱신한다**

```markdown
- [~] fine notice OCR 확인 완료 후 `law_ground_search`와 `appeal_decision_flow`가 동적 plan에 삽입되며 ...
```

- [ ] **Step 4: 관련 테스트를 다시 실행한다**

Run:

```powershell
python -m pytest -p no:timeout -p no:cacheprovider test/test_chat_orchestration_service.py -q
python -m pytest -p no:timeout -p no:cacheprovider test/test_agent_node_service.py -q
```

Expected: PASS

- [ ] **Step 5: 커밋한다**

```powershell
git add test/test_chat_orchestration_service.py test/test_agent_node_service.py docs/ops/project-readiness-master-checklist.md
git commit -m "docs: align appeal flow readiness with runtime behavior"
```

### Task 4: 사건 메모리와 장기 대화 압축을 도입한다

**Files:**
- Create: `app/services/case_memory_service.py`
- Modify: `app/services/chat_orchestration_service.py`
- Modify: `app/services/chat_session_followup_service.py`
- Create or Modify: `test/test_case_memory_service.py`
- Modify: `docs/ops/project-readiness-master-checklist.md`

**Interfaces:**
- Consumes: user text, attachments, follow-up state, existing summary
- Produces: 구조화된 `case_memory`, 압축 후에도 유지되는 facts/claims/evidence/deadlines, 관련 회귀 테스트

- [ ] **Step 1: 사건 메모리의 실패 테스트를 먼저 정의한다**

```python
def test_case_memory_preserves_facts_claims_and_unknowns():
    memory = update_case_memory(
        current={},
        turn_input={"user_text": "교차로에서 접촉사고가 났고 제 차는 직진 중이었어요"},
        extracted={"facts": ["교차로", "직진"], "claims": ["상대가 끼어들었다"], "unknowns": ["신호등 상태"]},
    )
    assert memory["facts"] == ["교차로", "직진"]
    assert memory["claims"] == ["상대가 끼어들었다"]
    assert memory["unknowns"] == ["신호등 상태"]
```

- [ ] **Step 2: 압축 후 소실 방지 회귀 테스트를 추가한다**

```python
def test_compaction_keeps_deadlines_and_evidence_references():
    compacted = compact_case_memory({...})
    assert compacted["deadlines"] == ["2026-07-30"]
    assert compacted["evidence_refs"] == ["att_notice_1", "law:road-traffic-act-1"]
```

- [ ] **Step 3: 테스트가 실패하는지 확인한다**

Run:

```powershell
python -m pytest -p no:timeout -p no:cacheprovider test/test_case_memory_service.py -q
```

Expected: 새 서비스 미구현으로 실패한다.

- [ ] **Step 4: 최소 구현을 추가하고 orchestration에 연결한다**

```python
def update_case_memory(current: dict[str, Any], turn_input: dict[str, Any], extracted: dict[str, Any]) -> dict[str, Any]:
    next_state = deepcopy(current or {})
    for key in ("parties", "vehicles", "time_place", "incident_type", "facts", "claims", "evidence_refs", "unknowns", "deadlines", "stage"):
        next_state[key] = _merge_list(next_state.get(key), extracted.get(key))
    return next_state
```

- [ ] **Step 5: 서비스와 연동 테스트를 다시 돌린다**

Run:

```powershell
python -m pytest -p no:timeout -p no:cacheprovider test/test_case_memory_service.py -q
python -m pytest -p no:timeout -p no:cacheprovider test/test_chat_orchestration_service.py -q
```

Expected: PASS

- [ ] **Step 6: 커밋한다**

```powershell
git add app/services/case_memory_service.py app/services/chat_orchestration_service.py app/services/chat_session_followup_service.py test/test_case_memory_service.py docs/ops/project-readiness-master-checklist.md
git commit -m "feat: preserve structured case memory across long chats"
```

### Task 5: 최신성 노출과 법령 회귀를 사용자 결과에 연결한다

**Files:**
- Modify: `app/services/legal_rag_service.py`
- Modify: `app/services/law_ground_contract.py`
- Modify: result composition services under `app/services/`
- Create or Modify: freshness regression tests under `test/`
- Modify: `docs/ops/project-readiness-master-checklist.md`

**Interfaces:**
- Consumes: `effective_at`, `retrieved_at`, `dataset_version`, source summaries
- Produces: 사용자 응답용 freshness payload, 변경된 법령 fixture 회귀 테스트

- [ ] **Step 1: freshness 노출 실패 테스트를 추가한다**

```python
def test_law_ground_result_exposes_effective_and_retrieved_dates():
    result = normalize_law_structured_result({...})
    assert result["freshness"]["effective_at"] == "2026-07-27"
    assert result["freshness"]["retrieved_at"] == "2026-07-27T09:00:00Z"
    assert "limitation" in result["freshness"]
```

- [ ] **Step 2: 변경된 기준 fixture 회귀 테스트를 추가한다**

```python
def test_changed_law_fixture_marks_previous_reference_as_stale():
    response = build_law_result_from_fixture("changed_deadline_fixture")
    assert response["freshness"]["stale_sources"] == ["law_source_a"]
```

- [ ] **Step 3: 테스트가 실패하는지 확인한다**

Run:

```powershell
python -m pytest -p no:timeout -p no:cacheprovider test -k "freshness or changed_law" -q
```

Expected: freshness payload 부재로 실패한다.

- [ ] **Step 4: 최소 구현을 추가한다**

```python
structured_result["freshness"] = {
    "effective_at": effective_at,
    "retrieved_at": retrieved_at,
    "dataset_version": dataset_version,
    "limitation": limitation_text,
}
```

- [ ] **Step 5: 관련 테스트를 다시 돌린다**

Run:

```powershell
python -m pytest -p no:timeout -p no:cacheprovider test -k "freshness or changed_law" -q
```

Expected: PASS

- [ ] **Step 6: 커밋한다**

```powershell
git add app/services/legal_rag_service.py app/services/law_ground_contract.py docs/ops/project-readiness-master-checklist.md
git commit -m "feat: expose freshness metadata in law search results"
```

### Task 6: adapter E2E와 품질 공개 형식을 고정한다

**Files:**
- Modify: attachment and adapter integration tests under `backend/chatbot/` and `test/`
- Modify: DTO/result formatting services under `app/services/`
- Modify: `docs/ops/project-readiness-master-checklist.md`

**Interfaces:**
- Consumes: PDF/image/video attachment flows, unsupported file paths
- Produces: 5개 adapter E2E 회귀, 품질 공개 DTO, 체크리스트 근거

- [ ] **Step 1: 다섯 시나리오의 실패 테스트를 추가한다**

```python
SCENARIOS = [
    ("fine_notice_pdf", "fine_notice_analysis"),
    ("accident_scene_image", "text_ml_case_search"),
    ("blackbox_video", "vision_media_analysis"),
    ("unsupported_file", "safe_rejection"),
    ("unknown_classification", "classification_followup"),
]
```

- [ ] **Step 2: 테스트를 실행해 현재 누락 경로를 확인한다**

Run:

```powershell
python -m pytest -p no:timeout -p no:cacheprovider backend/chatbot -k "attachment or adapter or vision" -q
```

Expected: 적어도 일부 시나리오에서 adapter 경계 assertion이 부족해 실패한다.

- [ ] **Step 3: 결과 공개 DTO를 최소 구현으로 정리한다**

```python
quality_payload = {
    "contract_version": "analysis_quality.v1",
    "analysis_kind": analysis_kind,
    "confidence_band": confidence_band,
    "limitations": limitations,
}
```

- [ ] **Step 4: 테스트를 다시 돌린다**

Run:

```powershell
python -m pytest -p no:timeout -p no:cacheprovider backend/chatbot -k "attachment or adapter or vision" -q
```

Expected: PASS

- [ ] **Step 5: 커밋한다**

```powershell
git add backend/chatbot app/services docs/ops/project-readiness-master-checklist.md
git commit -m "test: cover adapter e2e readiness scenarios"
```

### Task 7: 구조화 입력 UI와 접근성을 추가한다

**Files:**
- Create: `app/web/components/StructuredIntakePanel.jsx`
- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `app/web/styles.css`
- Create or Modify: frontend tests under `app/web`
- Modify: `docs/ops/project-readiness-master-checklist.md`

**Interfaces:**
- Consumes: 상담 시작 화면, existing chat input flow
- Produces: 사고 유형, 사실관계, 주장, 첨부 목적, 누락 정보 확인 UI와 접근성 속성

- [ ] **Step 1: 구조화 입력 UI 실패 테스트를 추가한다**

```jsx
it("shows incident type, fact, and claim sections before first submission", () => {
  render(<StructuredIntakePanel />);
  expect(screen.getByLabelText("사고 유형")).toBeInTheDocument();
  expect(screen.getByLabelText("확인된 사실")).toBeInTheDocument();
  expect(screen.getByLabelText("사용자 주장")).toBeInTheDocument();
});
```

- [ ] **Step 2: 키보드와 접근성 실패 테스트를 추가한다**

```jsx
it("supports keyboard navigation order across structured inputs", async () => {
  render(<StructuredIntakePanel />);
  await user.tab();
  expect(screen.getByLabelText("사고 유형")).toHaveFocus();
});
```

- [ ] **Step 3: 테스트가 실패하는지 확인한다**

Run:

```powershell
npm test -- --runInBand
```

Working directory: `app/web`

Expected: 새 패널 미구현으로 실패한다.

- [ ] **Step 4: 최소 구현을 추가한다**

```jsx
export function StructuredIntakePanel({ value, onChange }) {
  return (
    <section aria-labelledby="structured-intake-title">
      <h2 id="structured-intake-title">상담 시작 정보</h2>
      <select aria-label="사고 유형" />
      <textarea aria-label="확인된 사실" />
      <textarea aria-label="사용자 주장" />
    </section>
  );
}
```

- [ ] **Step 5: 프런트 테스트와 빌드를 다시 돌린다**

Run:

```powershell
npm test -- --runInBand
npm run build
```

Working directory: `app/web`

Expected: PASS

- [ ] **Step 6: 커밋한다**

```powershell
git add app/web docs/ops/project-readiness-master-checklist.md
git commit -m "feat: add structured intake and accessibility groundwork"
```

### Task 8: CloudFront 2차 고도화의 코드 측 준비를 마무리한다

**Files:**
- Modify: `infra/terraform-pilot/*.tf`
- Modify: deploy scripts under `deploy/`
- Create or Modify: Terraform/deploy contract tests under `test/`
- Modify: `docs/ops/project-readiness-master-checklist.md`

**Interfaces:**
- Consumes: current pilot terraform and deploy packaging
- Produces: S3/OAC/CloudFront/rewrite/cache/rollback code, validation tests, still-human-gated apply row updates

- [ ] **Step 1: Terraform과 deploy contract 실패 테스트를 추가한다**

```python
def test_cloudfront_distribution_uses_private_frontend_bucket_and_oac():
    text = read_text(ROOT / "infra" / "terraform-pilot" / "frontend_distribution.tf")
    assert "origin_access_control_id" in text
    assert "block_public_acls" in text
```

```python
def test_release_script_uploads_index_last_and_sets_cache_headers():
    script = read_text(ROOT / "deploy" / "aws-pilot" / "Deploy-Pilot.ps1")
    assert "index.html" in script
    assert "Cache-Control" in script
```

- [ ] **Step 2: 테스트를 실행해 현재 빈 부분을 확인한다**

Run:

```powershell
python -m pytest -p no:timeout -p no:cacheprovider test -k "cloudfront or terraform_pilot or deploy_pilot" -q
```

Expected: 새 자산 파일 또는 헤더 정책 부재로 실패한다.

- [ ] **Step 3: 최소 구현을 추가한다**

```hcl
resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "${var.project_name}-frontend"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}
```

```powershell
$ImmutableCacheControl = "public,max-age=31536000,immutable"
$IndexCacheControl = "no-cache,no-store,must-revalidate"
```

- [ ] **Step 4: fmt, validate, 테스트를 다시 돌린다**

Run:

```powershell
terraform fmt -check -recursive infra/terraform-pilot
terraform validate infra/terraform-pilot
python -m pytest -p no:timeout -p no:cacheprovider test -k "cloudfront or terraform_pilot or deploy_pilot" -q
```

Expected: PASS

- [ ] **Step 5: 커밋한다**

```powershell
git add infra/terraform-pilot deploy test docs/ops/project-readiness-master-checklist.md
git commit -m "feat: prepare cloudfront delivery code path"
```

## 계획 전체 검토

- Spec coverage: Track 1~6가 오류 메모 5건과 체크리스트의 비인간 게이트 항목을 대응한다.
- Placeholder scan: 각 Task에 실제 파일, 테스트, 명령, 최소 구현 스니펫을 넣었다.
- Type consistency: 새 사건 메모리 서비스는 `dict[str, Any]` 기반으로 기존 orchestration 서비스와 연결하고, frontend 새 패널은 `value`/`onChange` 인터페이스만 추가해 기존 화면 상태와 결합한다.
