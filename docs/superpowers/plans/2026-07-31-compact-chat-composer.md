# Compact Chat Composer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the tall chat intake/composer stack with a compact consultation-type row and an integrated message, attachment, and send surface.

**Architecture:** Keep all React state, handlers, and request construction in place. Change only the `ConsultationIntakePanel` disclosure markup and the composer layout markup/CSS, with source-contract tests protecting behavior and accessibility.

**Tech Stack:** React 19, Vite 7, CSS, Node test runner

## Global Constraints

- Do not change backend endpoints or request field names.
- Do not change attachment authentication, upload registration, MIME acceptance, OCR, or Vision routing.
- Type-specific fields are hidden by default and opened only through `상세 정보`.
- Attachment and send actions remain inside the rounded composer.

---

### Task 1: Lock the compact layout contract

**Files:**
- Modify: `app/web/consultationLayout.test.js`

**Interfaces:**
- Consumes: `FrontendAppShell.jsx` and `styles.css` as source text.
- Produces: regression assertions for disclosure behavior, accessible controls, integrated composer markup, and compact styling.

- [ ] **Step 1: Write failing tests**

Add assertions that the intake starts closed for detail-capable types, renders a compact always-visible type row plus `상세 정보`, removes the always-visible dropzone copy, uses icon-only accessible send content, and caps the textarea/composer sizing.

- [ ] **Step 2: Verify RED**

Run: `npm --prefix app/web test -- consultationLayout.test.js`

Expected: failure because the current intake opens automatically and the current composer renders instructional copy and a text send button.

- [ ] **Step 3: Implement Task 2**

Proceed only after the failure is confirmed to be caused by the missing compact layout.

### Task 2: Implement compact intake and composer

**Files:**
- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `app/web/styles.css`

**Interfaces:**
- Consumes: existing `consultationIntake`, `question`, attachment state, and callbacks.
- Produces: the same callback calls and payload inputs through a smaller DOM layout.

- [ ] **Step 1: Change intake disclosure behavior**

Keep the consultation type select visible in a compact row. Render the native disclosure only when the selected type has structured fields, with `상세 정보` as its closed label and no automatic reopening on type change.

- [ ] **Step 2: Integrate composer actions**

Keep the textarea and toolbar in the same rounded surface, preserve the hidden file input/menu and file state, replace visible instructional copy with conditional status content, and render a circular arrow send button with `aria-label="전송"`.

- [ ] **Step 3: Add compact responsive styles**

Reduce default textarea height and padding, remove the nested dropzone panel appearance, size the action buttons to 36–40px, and let only relevant file/error statuses add height.

- [ ] **Step 4: Verify GREEN**

Run: `npm --prefix app/web test -- consultationLayout.test.js`

Expected: all layout tests pass.

### Task 3: Regression and visual verification

**Files:**
- No production files beyond Task 2.

**Interfaces:**
- Consumes: completed frontend source.
- Produces: test, build, and browser evidence.

- [ ] **Step 1: Run the full frontend test suite**

Run: `npm --prefix app/web test`

Expected: zero failures.

- [ ] **Step 2: Build production assets**

Run: `npm --prefix app/web run build`

Expected: Vite exits with code 0.

- [ ] **Step 3: Inspect in a local browser**

Run the Vite development server, open the AI consultation screen, and verify at desktop and narrow widths that the structured fields are hidden until `상세 정보` is opened and the attachment/send controls remain inside the composer.

- [ ] **Step 4: Review the diff**

Run: `git diff --check` and `git diff -- app/web/FrontendAppShell.jsx app/web/styles.css app/web/consultationLayout.test.js`

Expected: no whitespace errors and no backend or request-construction changes.
