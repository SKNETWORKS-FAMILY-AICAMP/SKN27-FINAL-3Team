# Compact Quick Examples Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the prominent top-level service-example card with a quiet, first-visit example-question disclosure inside the empty conversation state.

**Architecture:** Reuse `ChatScreenV2`'s existing `quickQuestionGroups` array and `setQuestion(item)` behavior. Move only the example disclosure markup into the existing `!hasConversation` branch and restyle it; do not create or modify any API, schema, request builder, authentication, upload, or AI-routing code.

**Tech Stack:** React 19, CSS, Node test runner, Vite 7

## Global Constraints

- Allowed production files: `app/web/FrontendAppShell.jsx` and `app/web/styles.css`.
- Allowed test file: `app/web/consultationLayout.test.js`.
- Forbidden files include `app/web/apiClient.js`, `app/web/consultationIntake.js`, `app/services/`, `app/schemas/`, `app/api/`, `backend/`, and `ai/`.
- Do not change `user_text`, `consultation_type`, `facts`, `attachments`, `conversation_history`, authentication, guest-session, upload, OCR, Vision, or AI-routing behavior.
- Keep the current example category names and question strings unchanged.
- Selecting an example calls `setQuestion(item)` and never calls `onSubmit`.
- The example entry point is visible only before the first conversation message.

---

### Task 1: Lock the frontend-only layout contract

**Files:**
- Modify: `app/web/consultationLayout.test.js`

**Interfaces:**
- Consumes: `FrontendAppShell.jsx` and `styles.css` as source text.
- Produces: regression assertions that constrain DOM placement, copy, selection behavior, and allowed visual hierarchy.

- [ ] **Step 1: Write the failing source-contract test**

Add a test with assertions equivalent to:

```js
test("quick examples live quietly inside the empty conversation state", () => {
  const emptyState = shell.slice(
    shell.indexOf('className="chat-empty-state"'),
    shell.indexOf("</section>", shell.indexOf('className="chat-empty-state"')) + 10,
  );
  const topLevelBeforeMessages = shell.slice(
    shell.indexOf('className="chat-main"'),
    shell.indexOf('className="messages"'),
  );

  assert.match(emptyState, /어떤 내용을 적어야 할지 막막하신가요/);
  assert.match(emptyState, /예시 질문 보기/);
  assert.match(emptyState, /quickQuestionGroups\.map/);
  assert.match(emptyState, /setQuestion\(item\)/);
  assert.doesNotMatch(topLevelBeforeMessages, /서비스 예시 작동 방식/);
  assert.doesNotMatch(emptyState, /onSubmit/);
});
```

Add a style assertion that the final quick-example override has no outer border or card background and that its trigger uses compact text sizing.

- [ ] **Step 2: Run the focused test to verify RED**

Run:

```powershell
node --test consultationLayout.test.js
```

Working directory: `app/web`

Expected: FAIL because `quick-examples` is currently a top-level card before `.messages`, and the empty state does not contain `예시 질문 보기`.

- [ ] **Step 3: Confirm the failure is contractual**

The failure must mention the missing empty-state prompt or the still-present `서비스 예시 작동 방식` copy. Fix any test slicing error before production changes.

### Task 2: Move and restyle the existing examples

**Files:**
- Modify: `app/web/FrontendAppShell.jsx:2707-2728`
- Modify: `app/web/FrontendAppShell.jsx:2731-2735`
- Modify: `app/web/styles.css:3374-3465`
- Test: `app/web/consultationLayout.test.js`

**Interfaces:**
- Consumes: `quickQuestionGroups: Array<{title: string, questions: string[]}>`, `hasConversation: boolean`, and React state setter `setQuestion(item: string)`.
- Produces: an empty-state-only disclosure labeled `예시 질문 보기` that writes, but does not submit, the selected example.

- [ ] **Step 1: Remove the top-level example card**

Delete only the current top-level:

```jsx
<details className="quick-examples">
  ...
</details>
```

Do not edit `quickQuestionGroups`, `onSubmit`, `api.submitChatMessage`, or any request payload construction.

- [ ] **Step 2: Add the quiet disclosure inside the empty state**

Inside the existing `!hasConversation` `chat-empty-state`, after its explanatory paragraph, add:

```jsx
<div className="empty-state-examples">
  <span>어떤 내용을 적어야 할지 막막하신가요?</span>
  <details className="quick-examples">
    <summary className="quick-examples-header">예시 질문 보기</summary>
    <div className="quick-example-groups">
      {quickQuestionGroups.map((group) => (
        <section className="quick-example-group" aria-label={group.title} key={group.title}>
          <h4>{group.title}</h4>
          <div className="quick-row">
            {group.questions.map((item) => (
              <button className="quick-chip" type="button" key={item} onClick={() => setQuestion(item)}>
                {item}
              </button>
            ))}
          </div>
        </section>
      ))}
    </div>
  </details>
</div>
```

The button remains `type="button"` and must not reference `onSubmit`.

- [ ] **Step 3: Replace the card styling with a quiet local hierarchy**

Add a final `/* Compact quick examples */` override that:

```css
.empty-state-examples {
  display: grid;
  justify-items: center;
  gap: 4px;
  color: #65708a;
  font-size: 12px;
}

.empty-state-examples .quick-examples {
  width: min(100%, 680px);
  margin: 0;
  overflow: visible;
  border: 0;
  background: transparent;
}

.empty-state-examples .quick-examples-header {
  min-height: 28px;
  padding: 3px 8px;
  justify-content: center;
  color: #4b5694;
  font-size: 12px;
  font-weight: 800;
}
```

Keep the expanded example groups compact, wrapped, and free of horizontal overflow. Preserve visible focus styles for summary and question buttons.

- [ ] **Step 4: Run the focused test to verify GREEN**

Run:

```powershell
node --test consultationLayout.test.js
```

Working directory: `app/web`

Expected: all consultation layout tests pass.

### Task 3: Prove contract isolation and visual behavior

**Files:**
- Verify only; do not modify additional production files.

**Interfaces:**
- Consumes: committed frontend diff and local Vite preview.
- Produces: evidence that tests, build, file scope, and browser behavior satisfy the design.

- [ ] **Step 1: Run the full frontend test suite**

Run:

```powershell
node --test
```

Working directory: `app/web`

Expected: zero failed tests.

- [ ] **Step 2: Run the production build**

Run:

```powershell
npm run build
```

Working directory: `app/web`

Expected: Vite exits with code 0.

- [ ] **Step 3: Verify the changed-file allowlist**

Run:

```powershell
git diff --name-only HEAD~1
```

Expected implementation file set:

```text
app/web/FrontendAppShell.jsx
app/web/consultationLayout.test.js
app/web/styles.css
```

The design and plan documents may appear in earlier documentation commits. No `apiClient.js`, backend, AI, schema, or service file may appear in the implementation commit.

- [ ] **Step 4: Verify request construction is byte-for-byte unchanged**

Run:

```powershell
git diff HEAD~1 -- app/web/apiClient.js app/web/consultationIntake.js app/services app/schemas app/api backend ai
```

Expected: no output.

- [ ] **Step 5: Inspect the local browser**

Verify:

1. The initial empty state quietly shows `어떤 내용을 적어야 할지 막막하신가요?` and `예시 질문 보기`.
2. Opening the disclosure reveals the unchanged categories and question text.
3. Selecting a question populates the composer without sending a request.
4. Once a user message exists, the empty-state example entry point is absent.
5. No horizontal overflow occurs at desktop or mobile widths.

- [ ] **Step 6: Commit the implementation**

Stage only:

```powershell
git add app/web/FrontendAppShell.jsx app/web/styles.css app/web/consultationLayout.test.js
```

Commit:

```powershell
git commit -m "feat: tuck examples into chat empty state"
```
