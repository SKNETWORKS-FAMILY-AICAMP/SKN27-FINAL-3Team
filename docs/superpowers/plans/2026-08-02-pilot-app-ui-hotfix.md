# Pilot App Response and UI Hotfix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox checkpoints and must preserve the scope below.

**Goal:** Fix the approved Pilot App response-display boundary and the 15 reviewed frontend UI/UX defects, then prove the hotfix with local regression tests and a Vite production build.

**Architecture:** Keep backend orchestration, Agent/RAG behavior, deployment assets, and AWS CI/CD untouched. Normalize the existing API/worker payload only at the frontend display boundary, render assistant Markdown safely, isolate keyboard/menu behavior in small testable helpers, and update the existing shell/report workbench without adding routes or product features.

**Tech Stack:** React 19, Vite 7, Node built-in test runner, `react-markdown@10.1.0`, `remark-gfm@4.0.1`, Python pytest, Django test runner.

## Global constraints

- Base commit: `6cd91da405c684a9d01ba76871c3a031299e3d78` (`origin/dev` at planning time).
- Implement only the approved response-boundary and 15 UI/UX hotfix items.
- Do not modify `deploy/**`, `infra/**`, `buildspec*.yml`, pipeline settings, release scripts, or operational approval/deployment state.
- Do not modify backend Agent/RAG/provider/orchestration production code.
- Backend API tests are characterization guards. If a new guard unexpectedly fails, stop and ask the user before changing production backend code.
- Do not add unrelated refactoring, new pages, new features, telemetry, analytics, or provider calls.
- Do not stage, commit, push, or create a PR in this execution. End each task with a review checkpoint and a proposed user-owned commit message.
- Preserve the existing API and worker polling state model: `queued`, `running`, `partial`, `failed`, `needs_input`, `needs_clarification`, and `success`.

## Approved defect coverage

| Review item | Implementation task |
| --- | --- |
| 1. Mobile composer overlap | Task 5 |
| 2. Safe Markdown | Task 2 |
| 3. Answer/limit/question hierarchy | Task 4 |
| 4. Inline current-report entry | Task 4 |
| 5. `[object Object]` in missing items | Task 6 |
| 6. Enter/Shift+Enter/IME | Task 3 |
| 7. Attachment menu dismiss/accessibility | Task 3 |
| 8. Guest My Cases/login CTA | Task 5 |
| 9. Report workbench central width/collapse | Task 6 |
| 10. Contextual legal notice | Task 6 |
| 11. One four-item mobile global nav | Task 5 |
| 12. Korean line breaking | Task 5 |
| 13. Empty state single CTA | Task 6 |
| 14. Icon meaning | Task 5 |
| 15. “AI consultation” terminology | Task 5 |

---

### Task 1: Lock the response contract and add a frontend presentation normalizer

**Files:**

- Create: `app/web/chatResponsePresentation.js`
- Create: `app/web/chatResponsePresentation.test.js`
- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `test/test_chat_orchestration_service.py`
- Modify: `test/test_consultation_v2_contract.py`
- Modify: `backend/chatbot/test_analysis_job_queue.py`

**Interfaces:**

```js
normalizeChatResponsePresentation(result) => {
  semanticStatus,
  tone,
  answerMarkdown,
  followUp,
  pendingQuestions,
  retryAction,
  reportLink,
}
```

- [ ] Add backend characterization assertions showing synchronous `needs_input`, `needs_clarification`, `high_risk_handoff`, and `case_ready` responses contain a non-empty `assistant_message.answer` and are not queued as background work.
- [ ] Run the focused backend guards; they must pass without production backend changes.

```powershell
python -m pytest -q test\test_chat_orchestration_service.py test\test_consultation_v2_contract.py
python backend\manage.py test chatbot.test_analysis_job_queue --verbosity 1
```

- [ ] Write `chatResponsePresentation.test.js` first. Cover each semantic state, nested/string assistant messages, object-valued fields, success-with-empty-answer demotion, pending-question normalization, retry metadata, and report-link extraction.

```js
import test from "node:test";
import assert from "node:assert/strict";
import { normalizeChatResponsePresentation } from "./chatResponsePresentation.js";

test("uses core_answer before other response text", () => {
  const value = normalizeChatResponsePresentation({
    status: "success",
    assistant_message: {
      core_answer: "핵심 답변",
      answer: "일반 답변",
    },
  });
  assert.equal(value.answerMarkdown, "핵심 답변");
  assert.equal(value.semanticStatus, "success");
});

test("never presents an empty successful assistant turn", () => {
  const value = normalizeChatResponsePresentation({ status: "success" });
  assert.equal(value.semanticStatus, "partial");
  assert.match(value.answerMarkdown, /답변을 불러오지 못했습니다/);
  assert.equal(value.retryAction?.kind, "refocus-input");
});

test("does not stringify object-valued text as object Object", () => {
  const value = normalizeChatResponsePresentation({
    status: "needs_input",
    assistant_message: { answer: { unexpected: true } },
  });
  assert.doesNotMatch(value.answerMarkdown, /\[object Object\]/);
  assert.match(value.answerMarkdown, /추가 확인/);
});
```

- [ ] Run the new test and confirm RED because the module does not exist yet.

```powershell
node --test chatResponsePresentation.test.js
```

- [ ] Implement only the normalization boundary. Use explicit text guards; never call `String()` on arbitrary objects.

```js
const STATE_FALLBACKS = {
  queued: "분석을 준비하고 있습니다.",
  running: "분석 상태를 확인하고 있습니다.",
  partial: "일부 결과만 확인되었습니다. 확인 사항을 검토한 뒤 다시 시도해 주세요.",
  failed: "분석을 완료하지 못했습니다. 입력 내용을 확인한 뒤 다시 시도해 주세요.",
  needs_input: "추가 확인이 필요합니다. 아래 질문에 답해 주세요.",
  needs_clarification: "요청을 정확히 이해하려면 내용을 조금 더 알려 주세요.",
  success: "완료된 답변을 불러오지 못했습니다. 잠시 후 다시 확인해 주세요.",
};

export function asNonEmptyText(value) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

export function normalizeChatResponsePresentation(result = {}) {
  const assistant = typeof result.assistant_message === "object" && result.assistant_message
    ? result.assistant_message
    : {};
  const requestedStatus = asNonEmptyText(result.status || result.semantic_status) || "partial";
  const answerMarkdown = [
    assistant.core_answer,
    assistant.answer,
    assistant.summary,
    typeof result.assistant_message === "string" ? result.assistant_message : "",
    result.polling_notice?.message,
    result.analysis_progress?.user_message,
  ].map(asNonEmptyText).find(Boolean) || STATE_FALLBACKS[requestedStatus] || STATE_FALLBACKS.partial;
  const semanticStatus = requestedStatus === "success" && ![
    assistant.core_answer,
    assistant.answer,
    assistant.summary,
    typeof result.assistant_message === "string" ? result.assistant_message : "",
  ].map(asNonEmptyText).some(Boolean) ? "partial" : requestedStatus;

  return {
    semanticStatus,
    tone: semanticStatus === "failed" ? "danger" : semanticStatus === "partial" ? "warning" : "neutral",
    answerMarkdown,
    followUp: asNonEmptyText(assistant.follow_up || result.follow_up),
    pendingQuestions: normalizePendingQuestions(result.pending_questions || assistant.pending_questions),
    retryAction: ["failed", "partial"].includes(semanticStatus)
      ? { kind: "refocus-input", label: "입력 내용을 확인하고 다시 보내기" }
      : null,
    reportLink: normalizeReportLink(result),
  };
}
```

- [ ] Integrate the normalizer at every assistant-message construction/restoration boundary in `FrontendAppShell.jsx`. Store presentation fields on the message; do not insert an assistant message with blank `content`.
- [ ] When `retryAction.kind === "refocus-input"`, prefill/focus the original submitted question only. Do not auto-resubmit and do not create a new backend request path.
- [ ] Run the frontend normalizer tests and focused backend guards GREEN.
- [ ] Review `git diff -- app/web/chatResponsePresentation.js app/web/chatResponsePresentation.test.js app/web/FrontendAppShell.jsx test/test_chat_orchestration_service.py test/test_consultation_v2_contract.py backend/chatbot/test_analysis_job_queue.py`.

Proposed user-owned commit message: `fix: normalize pilot chat response presentation`

---

### Task 2: Render assistant Markdown safely

**Files:**

- Modify: `app/web/package.json`
- Modify: `app/web/package-lock.json`
- Create: `app/web/SafeMarkdown.js`
- Create: `app/web/SafeMarkdown.test.js`
- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `app/web/styles.css`

- [ ] Write server-render tests for headings, lists, tables, safe external links, raw HTML, and `javascript:` URLs.

```js
import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { SafeMarkdown } from "./SafeMarkdown.js";

test("renders GFM structure and wraps tables", () => {
  const html = renderToStaticMarkup(React.createElement(SafeMarkdown, {
    content: "## 결론\n\n- 항목\n\n| A | B |\n| - | - |\n| 1 | 2 |",
  }));
  assert.match(html, /<h2>/);
  assert.match(html, /<ul>/);
  assert.match(html, /markdown-table-scroll/);
});

test("drops raw HTML and unsafe link protocols", () => {
  const html = renderToStaticMarkup(React.createElement(SafeMarkdown, {
    content: "<script>alert(1)</script> [위험](javascript:alert(1))",
  }));
  assert.doesNotMatch(html, /<script|javascript:/i);
});
```

- [ ] Run the test and confirm RED because `SafeMarkdown.js` is absent.

```powershell
node --test SafeMarkdown.test.js
```

- [ ] Install only the two approved rendering dependencies.

```powershell
npm install --save react-markdown@10.1.0 remark-gfm@4.0.1
```

- [ ] Implement `SafeMarkdown` without `rehype-raw`. Set `skipHtml`, a safe `urlTransform`, external-link `rel="noreferrer noopener"`, and a horizontal table wrapper.

```js
import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const SAFE_URL = /^(https?:|mailto:|tel:|\/|#)/i;

export function safeMarkdownUrl(value) {
  return typeof value === "string" && SAFE_URL.test(value.trim()) ? value.trim() : "";
}

export function SafeMarkdown({ content = "" }) {
  return React.createElement(ReactMarkdown, {
    remarkPlugins: [remarkGfm],
    skipHtml: true,
    urlTransform: safeMarkdownUrl,
    components: {
      table: ({ children, ...props }) => React.createElement(
        "div",
        { className: "markdown-table-scroll" },
        React.createElement("table", props, children),
      ),
      a: ({ children, href = "", ...props }) => {
        const safeHref = safeMarkdownUrl(href);
        const external = /^https?:\/\//i.test(safeHref);
        return React.createElement("a", {
          ...props,
          href: safeHref || undefined,
          target: external ? "_blank" : undefined,
          rel: external ? "noreferrer noopener" : undefined,
        }, children);
      },
    },
  }, content);
}
```

- [ ] Replace only assistant answer `<p>{message.content}</p>` rendering with `<SafeMarkdown content={message.content} />`. Keep user messages as plain text.
- [ ] Add scoped typography/list/code/table styles under the assistant message container. Preserve existing colors and spacing tokens.
- [ ] Run `node --test SafeMarkdown.test.js` and the full frontend test suite GREEN.
- [ ] Review the package and rendering diff; verify no raw-HTML plugin was added.

Proposed user-owned commit message: `fix: render assistant answers as safe markdown`

---

### Task 3: Fix composer keyboard behavior and attachment-menu accessibility

**Files:**

- Create: `app/web/composerInteraction.js`
- Create: `app/web/composerInteraction.test.js`
- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `app/web/styles.css`

- [ ] Write keyboard-policy tests first.

```js
import test from "node:test";
import assert from "node:assert/strict";
import { composerKeyAction } from "./composerInteraction.js";

test("Enter sends while Shift+Enter inserts a line break", () => {
  assert.equal(composerKeyAction({ key: "Enter" }, { hasContent: true }), "submit");
  assert.equal(composerKeyAction({ key: "Enter", shiftKey: true }, { hasContent: true }), "newline");
});

test("IME composition and keyCode 229 never submit", () => {
  assert.equal(composerKeyAction({ key: "Enter", isComposing: true }, { hasContent: true }), "ignore");
  assert.equal(composerKeyAction({ key: "Enter", keyCode: 229 }, { hasContent: true }), "ignore");
});

test("empty or busy composers do not submit", () => {
  assert.equal(composerKeyAction({ key: "Enter" }, { hasContent: false }), "ignore");
  assert.equal(composerKeyAction({ key: "Enter" }, { hasContent: true, isSubmitting: true }), "ignore");
});
```

- [ ] Run the test and confirm RED because the helper is absent.
- [ ] Implement the minimal pure helper and wire `textarea.onKeyDown` to call `preventDefault()` plus the existing submit handler only for `"submit"`.
- [ ] Add `attachmentMenuRef` and menu-item refs. While open, handle only:
  - outside pointer/click: close;
  - `Escape`: close and return focus to the trigger;
  - `ArrowDown`/`ArrowUp`: cycle menu items;
  - `Home`/`End`: first/last item;
  - item activation: existing action, close, and restore a sensible focus target.
- [ ] Add `aria-haspopup="menu"`, `aria-expanded`, `aria-controls`, `role="menu"`, `role="menuitem"`, and visible `:focus-visible` styles.
- [ ] Keep the existing attachment choices and upload behavior exactly; do not add attachment types or backend calls.
- [ ] Add/extend the existing source contract test to assert the ARIA attributes and Escape/outside-dismiss wiring.
- [ ] Run focused and full frontend tests GREEN.

```powershell
node --test composerInteraction.test.js
node --test
```

Proposed user-owned commit message: `fix: harden composer and attachment interactions`

---

### Task 4: Establish one assistant-turn hierarchy and inline report entry

**Files:**

- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `app/web/styles.css`
- Modify: `app/web/consultationLayout.test.js`

- [ ] Add failing layout/source-contract assertions for this order inside an assistant turn:
  1. safe answer body;
  2. compact/collapsible limitation or caution;
  3. at most one primary pending question;
  4. retry action when present;
  5. current-report status/link when available.
- [ ] Confirm RED against the current layout.
- [ ] Render limitation/safety content as a compact `<details>` disclosure below the answer, not as a competing full panel.
- [ ] Render only the first actionable pending question as the primary follow-up. Preserve additional questions in the existing detail/report data; do not delete response data.
- [ ] Render a single inline `현재 리포트 보기` action when a current report/report link is available. Use the existing `onOpenReporting` route transition; do not add a route.
- [ ] Connect the retry action from Task 1 to refocus/prefill only.
- [ ] Preserve the existing report, missing-field, and escalation data; only change visual hierarchy.
- [ ] Run the layout contract and full frontend tests GREEN.

Proposed user-owned commit message: `fix: clarify consultation answer hierarchy`

---

### Task 5: Correct mobile navigation, composer geometry, auth IA, icons, and terminology

**Files:**

- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `app/web/styles.css`
- Modify: `app/web/consultationLayout.test.js`

- [ ] Add failing contract assertions for one four-item mobile global navigation in this exact order: `가이드`, `상담`, `리포트`, `내 사건`.
- [ ] Remove `새 상담` from global navigation and keep it as a secondary action inside the chat screen.
- [ ] Map the four items only to existing screens/routes. Do not add a new route or backend endpoint.
- [ ] Make the mobile bottom bar a four-column safe-area-aware grid and reserve its height in the workspace/composer layout.

```css
.mobile-bottom-nav {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  padding-bottom: max(8px, env(safe-area-inset-bottom));
}

@media (max-width: 860px) {
  .workspace-shell {
    padding-bottom: calc(var(--mobile-nav-height) + env(safe-area-inset-bottom));
  }
}
```

- [ ] Keep the composer above the bottom bar at 320, 360, 390, 430, and 768 CSS-pixel widths. Ensure its textarea and buttons do not overlap and the touch targets are at least 44px.
- [ ] Replace the ambiguous `↑` send glyph with an accessible paper-plane icon plus `aria-label="메시지 보내기"`. Keep a text label or tooltip/accessible name for icon-only attachment and navigation controls.
- [ ] Add Korean wrapping rules to titles, labels, answer bodies, and report text.

```css
.assistant-message,
.report-workbench,
.app-top-nav {
  word-break: keep-all;
  overflow-wrap: anywhere;
}
```

- [ ] Standardize user-facing entry terminology to `AI 상담 시작` / `상담`. Do not rename backend models, API fields, route keys, or internal analytics identifiers.
- [ ] For guest `내 사건`, show one clear Google login CTA in the viewport and concise explanatory copy. Remove/hide duplicate login prompts in that same state only.
- [ ] Run the consultation layout contract and full frontend tests GREEN.

Proposed user-owned commit message: `fix: align mobile consultation navigation and layout`

---

### Task 6: Fix report normalization and workbench layout

**Files:**

- Modify: `app/web/reportWorkbenchState.js`
- Modify: `app/web/reportWorkbenchState.test.js`
- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `app/web/styles.css`
- Modify: `app/web/consultationLayout.test.js`

- [ ] Write normalization tests first for string, `question`, `label`, `description`, nested objects, null/empty values, duplicates, and the explicit Korean fallback. Assert no output contains `[object Object]`.

```js
test("normalizes structured missing items without object coercion", () => {
  assert.deepEqual(compactUniqueStrings([
    "보험사",
    { question: "사고 일시는 언제인가요?" },
    { label: "차량 번호" },
    { description: "현장 사진" },
    { unexpected: true },
  ]), ["보험사", "사고 일시는 언제인가요?", "차량 번호", "현장 사진", "추가 확인이 필요한 항목"]);
});
```

- [ ] Confirm RED with `node --test reportWorkbenchState.test.js`.
- [ ] Replace arbitrary `String(value)` coercion with an explicit recursive text extractor using the priority `question`, `label`, `description`, `title`, then fallback `추가 확인이 필요한 항목`.
- [ ] Keep de-duplication and stable input order.
- [ ] Add an inspector-collapse state/action alongside the existing report-list collapse. Both side panels must be independently collapsible.
- [ ] At desktop widths, allocate roughly 65–75% of available workbench width to the report canvas; collapsed panels must return width to the canvas.
- [ ] Move the legal notice out of the report list and place it next to the report canvas/export action where it is contextually relevant.
- [ ] Reduce the report empty state to one primary CTA using the existing `AI 상담 시작` navigation action. Remove competing empty-state buttons only; do not delete non-empty report actions.
- [ ] Add source/layout contract assertions for both collapse controls, contextual notice placement, and one empty-state CTA.
- [ ] Run report tests and the full frontend suite GREEN.

Proposed user-owned commit message: `fix: normalize report gaps and rebalance workbench`

---

### Task 7: Run the complete approved local verification set

**Files:** No production edits unless a scoped test exposes a defect in Tasks 1–6.

- [ ] Run all frontend tests.

```powershell
Set-Location app\web
node --test
```

Expected: all tests pass, including the new response, Markdown, composer, report, and layout contracts.

- [ ] Run the frontend production build.

```powershell
npm run build
```

Expected: Vite production build succeeds without unresolved imports or bundle errors.

- [ ] Run the root Python regression suite.

```powershell
Set-Location ..\..
python -m pytest -q
```

- [ ] Run the full Django chatbot suite with the correct settings-aware runner.

```powershell
python backend\manage.py test chatbot --verbosity 1
```

- [ ] Verify excluded areas are unchanged.

```powershell
git diff --name-only
git diff -- deploy infra
git diff -- buildspec.yml buildspec-release.yml
```

Expected: the excluded-area diffs are empty.

- [ ] Review the complete diff for debugging output, placeholders, copied secrets, unrelated refactors, `TODO`/`TBD`, and accidental `[object Object]` coercion.
- [ ] Record exact commands, exit codes, pass counts, build result, and any pre-existing warnings. Do not claim operational deployment or acceptance.

Proposed user-owned commit message: `test: verify pilot app ui hotfix`

---

### Task 8: Perform local browser acceptance at the approved UI boundary

**Files:** No edits unless a reproducible scoped visual defect is found.

- [ ] Start the existing local frontend preview using the repository’s normal environment. Do not connect to paid providers or production APIs.
- [ ] At 320, 360, 390, 430, 768, 1024, and 1440 CSS-pixel widths, verify:
  - composer and mobile nav do not overlap;
  - the four global tabs remain readable and reachable;
  - Korean titles and response paragraphs wrap without clipping;
  - safe Markdown headings, lists, links, code, and tables remain contained;
  - Enter/Shift+Enter/IME behavior matches the tests;
  - attachment menu supports pointer, Escape, arrow keys, and focus return;
  - guest `내 사건` exposes one login CTA;
  - assistant answer/limitation/question/report order is stable;
  - report list and inspector independently collapse;
  - empty report state has one primary CTA;
  - no `[object Object]` text appears.
- [ ] If a scoped defect appears, add a failing test first, make the smallest fix in the already-approved files, and rerun Tasks 7–8.
- [ ] Stop at local acceptance. Do not approve, trigger, or monitor an AWS deployment.

## Completion criteria

- All 15 review items are covered by code plus regression evidence.
- No assistant turn is blank or presented as successful without answer text.
- No arbitrary object is rendered through implicit string coercion.
- Backend production Agent/RAG/orchestration code is unchanged.
- AWS CI/CD and release files are unchanged.
- Frontend tests, Vite build, root pytest, and Django chatbot tests pass.
- Local browser acceptance passes at the listed widths.
- Final handoff clearly distinguishes “locally implemented and verified” from “operationally deployed.”
