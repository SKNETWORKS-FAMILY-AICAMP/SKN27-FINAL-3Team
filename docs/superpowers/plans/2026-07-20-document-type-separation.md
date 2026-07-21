# 문서 유형 분리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 이의신청서 초안·사실관계 정리·보험사 제출용 요약을 안전한 화면/복사 카드로 분리하면서, 공식 이의신청서 DOCX의 기존 게이트를 보존한다.

**Architecture:** 하나의 순수 카드 매퍼가 기존 공개 `sections`, 준비도, appeal gate를 세 카드로 재구성한다. 동기 Supervisor 경로와 worker 영속화 경로가 모두 이 매퍼를 호출하고, 공개 DTO는 새 선택 필드를 투영한다. 프런트엔드는 카드의 표시·클립보드 복사만 담당하며 어떤 새 다운로드 요청도 만들지 않는다.

**Tech Stack:** Python 3.13, Django, Pydantic, React JSX, CSS, pytest, Django test runner.

## Global Constraints

- `objection_form`만 DOCX 다운로드할 수 있으며 일반 리포트의 다운로드/PDF 경로를 추가하거나 되살리지 않는다.
- `denied`, `not_applicable`, 기한 경과 등 appeal gate 차단 상태에서는 이의신청서 초안을 제출 가능한 내용으로 노출하지 않는다.
- 카드의 공개 내용은 이미 공개되는 `sections`만 재사용한다. `form_data`, 확인 지문, 내부 사용자 ID, 원본 첨부파일 메타데이터를 새 필드에 넣지 않는다.
- 새 `document_cards`는 선택적 추가 필드다. 저장된 과거 리포트에 이 필드가 없어도 기존 섹션 UI가 유지돼야 한다.
- 보험 약관 판단, 보험금·합의금·과실 확정, 새 DB/마이그레이션, 새 파일 다운로드는 이 이슈 범위가 아니다.
- 기존 공식 DOCX 최종 확인 API와 `document_confirmation` 지문 계약은 변경하지 않는다.

---

## File Structure

- Create: `app/services/report_document_card_service.py` — 비공개 입력을 공개 카드로 결정적으로 재구성하는 순수 함수.
- Create: `test/test_report_document_card_service.py` — 카드 유형, 차단, 부분 자료, 민감 필드 미노출 단위 테스트.
- Modify: `app/services/agent_node_service.py` — 동기 Supervisor 결과에 카드를 붙인다.
- Modify: `backend/chatbot/repositories.py` — worker 영속화 결과에 같은 카드를 붙인다.
- Modify: `ai/agents/objection_report_generation/agent.py` — 더 이상 허용되지 않는 일반 `download_report` 액션을 생성하지 않는다.
- Modify: `app/contracts/report.py` — 공개 `ReportDocumentCard` DTO와 `document_cards` 필드를 선언한다.
- Modify: `app/services/report_query_service.py` — 새 필드를 명시적으로 정제·투영한다.
- Modify: `docs/api/openapi-v1.yaml` — DTO에서 생성한 OpenAPI 스냅샷을 갱신한다.
- Modify: `backend/chatbot/test_supervisor_reporting_pipeline.py`, `test/test_agent_node_service.py`, `test/test_report_query_service.py`, `test/test_consultation_v2_contract.py` — 생성 경로·DTO·UI·다운로드 회귀를 검증한다.
- Modify: `app/web/FrontendAppShell.jsx`, `app/web/styles.css` — 카드 표시와 복사 UX를 구현한다.
- Modify: `docs/ops/project-readiness-master-checklist.md` — #241 최종 확인 완료와 #245 진행/완료 상태를 반영한다.

### Task 1: 공개 문서 카드 매퍼와 단위 계약

**Files:**

- Create: `app/services/report_document_card_service.py`
- Create: `test/test_report_document_card_service.py`

**Interfaces:**

- Consumes: `document_variant: object`, `sections: object`, `document_readiness: object`, `appeal_gate: object`.
- Produces: `build_report_document_cards(...) -> list[dict[str, object]]` with exactly the types `objection_draft`, `fact_summary`, `insurance_submission`.
- Invariants: only title/body/items from supplied sections become `sections` or `copy_text`; blocked official objection cards return `status="unavailable"` and no `copy_text`.

- [ ] **Step 1: Write failing card-mapper tests**

```python
from app.services.report_document_card_service import build_report_document_cards


def test_official_report_builds_three_copyable_document_cards() -> None:
    cards = build_report_document_cards(
        document_variant="fine_notice",
        sections=[
            {"title": "1. 이의신청 취지", "body": "처분 재검토를 요청합니다."},
            {"title": "2. 사실관계", "body": "고지서의 일시와 장소를 확인했습니다."},
            {"title": "4. 관련 법령 및 근거", "body": "관련 조문을 검토합니다."},
            {"title": "5. 첨부자료", "body": "고지서 사본"},
        ],
        document_readiness={"ready_for_docx": True},
        appeal_gate={"blocked": False},
    )

    assert [card["type"] for card in cards] == [
        "objection_draft", "fact_summary", "insurance_submission",
    ]
    assert all(card["status"] == "ready" for card in cards)
    assert all(card["copy_text"] for card in cards)


def test_blocked_appeal_never_exposes_copyable_objection_draft() -> None:
    cards = build_report_document_cards(
        document_variant="fine_notice",
        sections=[{"title": "1. 이의신청 취지", "body": "처분 재검토"}],
        document_readiness={"ready_for_docx": True},
        appeal_gate={"blocked": True, "reason": "기한이 지났습니다."},
    )

    objection = cards[0]
    assert objection["type"] == "objection_draft"
    assert objection["status"] == "unavailable"
    assert "copy_text" not in objection
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `C:\Python314\python.exe -m pytest -q test\test_report_document_card_service.py`

Expected: collection error because `report_document_card_service` does not exist.

- [ ] **Step 3: Implement the smallest pure mapper**

```python
DOCUMENT_CARD_TYPES = (
    "objection_draft",
    "fact_summary",
    "insurance_submission",
)


def build_report_document_cards(*, document_variant: object, sections: object,
                                document_readiness: object, appeal_gate: object) -> list[dict[str, object]]:
    safe_sections = _normalize_sections(sections)
    official = _text(document_variant) in {"fine_notice", "traffic_accident"}
    blocked = bool(_mapping(appeal_gate).get("blocked"))
    return [
        _objection_draft_card(safe_sections, official=official, blocked=blocked,
                              ready_for_docx=bool(_mapping(document_readiness).get("ready_for_docx"))),
        _fact_summary_card(safe_sections),
        _insurance_submission_card(safe_sections),
    ]
```

Implement `_normalize_sections` so each returned item contains only non-empty `title`, `body`, and string `items`. Implement `_card` so `copy_text` is built only from that card's normalized sections; do not pass through arbitrary mapping keys. Use title-pattern selectors for 신청/이의, 사실/경위/개요, and 사실/근거/첨부/자료 respectively. Mark absent source sections `partial`, not `ready`.

- [ ] **Step 4: Add privacy and partial-data assertions, then run the unit suite**

```python
def test_cards_drop_form_data_and_attachment_metadata() -> None:
    cards = build_report_document_cards(
        document_variant="general",
        sections=[{"title": "사실관계", "body": "공개 문장", "storage_uri": "s3://private"}],
        document_readiness={},
        appeal_gate={},
    )

    assert "storage_uri" not in repr(cards)
    assert cards[0]["status"] == "unavailable"
    assert cards[1]["status"] == "ready"
```

Run: `C:\Python314\python.exe -m pytest -q test\test_report_document_card_service.py`

Expected: all card mapper tests pass.

- [ ] **Step 5: Commit the isolated mapper**

```powershell
git add app/services/report_document_card_service.py test/test_report_document_card_service.py
git commit -m "feat: build report document cards"
```

### Task 2: 생성·영속화·공개 DTO 연결

**Files:**

- Modify: `app/services/agent_node_service.py`
- Modify: `backend/chatbot/repositories.py`
- Modify: `ai/agents/objection_report_generation/agent.py`
- Modify: `app/contracts/report.py`
- Modify: `app/services/report_query_service.py`
- Modify: `docs/api/openapi-v1.yaml`
- Modify: `test/test_agent_node_service.py`
- Modify: `backend/chatbot/test_supervisor_reporting_pipeline.py`
- Modify: `test/test_report_query_service.py`
- Modify: `test/test_openapi_v1_generation.py`

**Interfaces:**

- Consumes: `build_report_document_cards` from Task 1.
- Produces: persisted and synchronous `reporting_payload["document_cards"]`; public `ReportReportingPayload.document_cards: list[ReportDocumentCard]`.
- Preserves: `document_confirmation`, `objection_form` DOCX endpoint, existing list/detail response fields and `report_actions` for `download_objection` only.

- [ ] **Step 1: Write failing integration and DTO tests**

```python
def test_worker_reporting_payload_persists_safe_document_cards(self) -> None:
    report = self._persist_completed_reporting_job()
    payload = report.content["reporting_payload"]

    assert [card["type"] for card in payload["document_cards"]] == [
        "objection_draft", "fact_summary", "insurance_submission",
    ]
    assert "download_report" not in [item["type"] for item in payload["report_actions"]]


def test_public_report_projection_keeps_document_cards_and_drops_private_keys() -> None:
    payload = _public_reporting_payload({
        "document_cards": [{
            "type": "fact_summary", "title": "사실관계 정리", "status": "ready",
            "sections": [{"title": "사실관계", "body": "공개", "storage_uri": "s3://private"}],
        }],
    })

    assert payload["document_cards"][0]["sections"] == [{"title": "사실관계", "body": "공개", "items": []}]
```

- [ ] **Step 2: Run targeted tests to verify the missing contract fails**

Run: `C:\Python314\python.exe -m pytest -q test\test_agent_node_service.py test\test_report_query_service.py`

Expected: `document_cards` is absent from the reporting payload or rejected by `ReportReportingPayload`.

- [ ] **Step 3: Wire the mapper into both reporting paths and declare the DTO**

```python
# app/contracts/report.py
class ReportDocumentCard(ReportApiContractModel):
    type: Literal["objection_draft", "fact_summary", "insurance_submission"]
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=280)
    status: Literal["ready", "partial", "unavailable"]
    sections: list[ReportSection] = Field(default_factory=list)
    copy_text: str | None = None
    notice: str | None = None


class ReportReportingPayload(ReportApiContractModel):
    # existing fields remain unchanged
    document_cards: list[ReportDocumentCard] = Field(default_factory=list)
```

```python
# app/services/agent_node_service.py and backend/chatbot/repositories.py
sections = ...  # the existing normalized form_sections value
document_readiness = ...
appeal_gate = ...
payload["document_cards"] = build_report_document_cards(
    document_variant=payload.get("document_variant"),
    sections=sections,
    document_readiness=document_readiness,
    appeal_gate=appeal_gate,
)
```

Filter `structured["report_actions"]` before storing or returning it so `type == "download_report"` is removed but `download_objection` and non-download completion actions retain their shape. Add `document_cards` to `PUBLIC_REPORTING_PAYLOAD_KEYS` and project it with a dedicated `_public_document_cards` function that calls `_public_sections` and explicitly keeps only the declared card keys.

- [ ] **Step 4: Regenerate the OpenAPI snapshot and run backend contracts**

Run: `C:\Python314\python.exe -m pytest -q test\test_agent_node_service.py test\test_report_query_service.py test\test_openapi_v1_generation.py backend\chatbot\test_report_api_contract.py backend\chatbot\test_supervisor_reporting_pipeline.py`

Expected: both sync/worker paths contain safe cards; public response schema accepts them; official DOCX confirmation regression tests remain green.

Update `docs/api/openapi-v1.yaml` using the repository's existing schema-generation test/command so it reflects `ReportDocumentCard`; do not hand-edit unrelated routes.

- [ ] **Step 5: Commit the backend contract slice**

```powershell
git add app/services/agent_node_service.py backend/chatbot/repositories.py ai/agents/objection_report_generation/agent.py app/contracts/report.py app/services/report_query_service.py docs/api/openapi-v1.yaml test/test_agent_node_service.py backend/chatbot/test_supervisor_reporting_pipeline.py test/test_report_query_service.py test/test_openapi_v1_generation.py
git commit -m "feat: expose typed report documents"
```

### Task 3: 카드 표시·복사 UX와 체크리스트

**Files:**

- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `app/web/styles.css`
- Modify: `test/test_consultation_v2_contract.py`
- Modify: `docs/ops/project-readiness-master-checklist.md`

**Interfaces:**

- Consumes: `reportingPayload.document_cards: Array<{type, title, description, status, sections, copy_text?, notice?}>`.
- Produces: `DocumentTypeCards` component with visual status and copy-only controls.
- Preserves: `ReportActionPanel`, `ReportReadyNotice`, `DocumentConfirmationPanel`, and their only-DOCX-for-`objection_form` behavior.

- [ ] **Step 1: Write the failing front-end contract tests**

```python
def test_frontend_renders_document_cards_as_copy_only_content() -> None:
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")

    assert "function DocumentTypeCards" in shell
    assert "document_cards" in shell
    assert "navigator.clipboard.writeText" in shell
    assert "보험사 제출용 요약" in shell
    assert 'onRunReportAction?.("download_report")' not in shell


def test_document_cards_do_not_reintroduce_generic_download_ui() -> None:
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")
    cards = shell[shell.index("function DocumentTypeCards"):shell.index("function groupReportSections")]

    assert "downloadReport" not in cards
    assert "PDF" not in cards
```

- [ ] **Step 2: Run the static contract test to verify it fails**

Run: `C:\Python314\python.exe -m pytest -q test\test_consultation_v2_contract.py -k document_card`

Expected: FAIL because `DocumentTypeCards` is not defined.

- [ ] **Step 3: Implement a copy-only card component and attach it to the report canvas**

```jsx
function DocumentTypeCards({ cards, onCopy }) {
  if (!Array.isArray(cards) || cards.length === 0) return null;
  return (
    <section className="document-type-cards" aria-label="문서 유형별 정리">
      {cards.map((card) => (
        <article className="document-type-card" data-status={card.status} key={card.type}>
          <span className="tag">{card.status === "ready" ? "복사 가능" : card.status === "partial" ? "자료 보완 필요" : "제출 불가"}</span>
          <strong>{card.title}</strong>
          <p>{card.description}</p>
          {card.notice && <p className="document-type-notice">{card.notice}</p>}
          {card.copy_text && card.status !== "unavailable" && (
            <button className="button" type="button" onClick={() => onCopy(card.copy_text, card.title)}>
              내용 복사
            </button>
          )}
        </article>
      ))}
    </section>
  );
}
```

In `ReportingScreen`, read `activeReportingPayload?.document_cards`, add an async `copyDocumentCardText` helper using `navigator.clipboard.writeText`, and pass it to `DocumentTypeCards` immediately below the report summary grid. On unavailable clipboard support or rejection, set the existing report-action status with a retry message; never fall back to a download or a new browser window. Add responsive `.document-type-cards`, `.document-type-card`, and `.document-type-notice` styles based on the existing report grid classes.

- [ ] **Step 4: Update checklist status and verify UI/build contracts**

Change only these checklist entries:

```md
- [x] 이의신청서 초안, 사실관계 정리, 보험사 제출 자료를 문서 종류로 분리 — #245
- [x] 문서 생성 전 사용자 최종 확인: 사실관계, 관할기관, 기한, 첨부자료 — #241 / PR #242
```

Run:

```powershell
C:\Python314\python.exe -m pytest -q test\test_consultation_v2_contract.py test\test_report_query_service.py
Set-Location app\web
npm.cmd run build
```

Expected: static contracts pass and Vite build exits 0 without a generic report download control.

- [ ] **Step 5: Commit the UI and checklist slice**

```powershell
git add app/web/FrontendAppShell.jsx app/web/styles.css test/test_consultation_v2_contract.py docs/ops/project-readiness-master-checklist.md
git commit -m "feat: display separated report documents"
```

### Task 4: Final integration verification and handoff

**Files:**

- Verify only the files changed in Tasks 1–3.

**Interfaces:**

- Consumes: complete #245 branch.
- Produces: evidence-backed commit/push handoff for a user-created PR.

- [ ] **Step 1: Inspect the complete branch diff and scope**

Run:

```powershell
git status -sb
git diff --check origin/dev...HEAD
git diff --stat origin/dev...HEAD
```

Expected: only #245 implementation, tests, OpenAPI snapshot, and checklist/spec/plan documentation are present.

- [ ] **Step 2: Run final regression suites**

Run:

```powershell
& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' backend\manage.py test chatbot -v 1
C:\Python314\python.exe -m pytest -q --timeout=30
Set-Location app\web
npm.cmd run build
```

Expected: all selected Django tests, full static suite, and production frontend build pass.

- [ ] **Step 3: Prepare PR handoff without creating the PR**

Use title `feat: 이의신청·사실관계·보험사 제출 문서 유형 분리`. State that cards are copy-only, official DOCX still requires #242 final confirmation, and generic report/PDF downloads remain unavailable. Include the exact verification output and any environment-only skipped tests.

- [ ] **Step 4: Push completed commits**

```powershell
git push origin feat/245-document-type-separation
```

Expected: branch is up to date and ready for the user to create PR #245.
