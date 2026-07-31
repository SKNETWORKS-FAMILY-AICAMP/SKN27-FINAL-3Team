# Compact Chat Composer Design

## Goal

Increase the visible conversation area by reducing the default height of the structured intake and message composer, while preserving every existing chat, attachment, authentication, and backend request contract.

## Approved interaction

- Show consultation type as a compact single-row control above the message composer.
- Keep type-specific structured fields hidden by default.
- When `과태료·범칙금` or `사고 과실비율` is selected, expose a `상세 정보` disclosure that the user opens explicitly.
- Keep the message textarea, attachment button, attachment state, and send button inside one rounded composer.
- Place the attachment button at the lower-left and a compact circular send button at the lower-right.
- Remove the always-visible drag-and-drop instructional copy. Preserve drag-and-drop behavior on the composer surface.
- Keep selected-file registration, authenticated upload guidance, capability errors, and pending-auth status visible when relevant.

## Component boundaries

`ConsultationIntakePanel` remains responsible for consultation type and structured fields. Its collapsed surface becomes the compact type row, and only the type-specific fields live in its disclosure body.

`ChatScreenV2` remains responsible for composing messages, attachment selection/registration, submission, and status feedback. The existing event handlers and state are reused without changing their signatures.

## Data and backend contracts

No API, schema, or backend changes are allowed. Submission continues to send:

- `user_text`
- `consultation_type`
- `facts`
- `attachments`
- `conversation_history`
- existing OCR and attachment-classification confirmations

The hidden file input, accepted MIME types, upload registration, login gate, and `onSubmit` callback remain unchanged.

## Responsive behavior

Desktop and tablet layouts use the single-row type control and compact composer toolbar. On narrow screens, the type label and select may wrap, but attachment and send actions remain inside the composer and retain accessible labels.

## Error handling and accessibility

- Preserve all existing alert and status regions.
- Preserve `상담 메시지 입력` and `자료 첨부` accessible names.
- Give the send button an explicit `전송` accessible name even when its visual content is an icon.
- Keep the detailed input disclosure keyboard-accessible through native `details`/`summary` behavior.

## Verification

- Update layout contract tests first and observe them fail.
- Run the frontend Node test suite.
- Run the Vite production build.
- Inspect the local page at desktop and narrow viewport widths.
- Confirm that the composer is materially shorter and that detailed fields only appear after user disclosure.
