# Compact Quick Examples Design

## Goal

Keep example questions discoverable for first-time users without reserving a prominent card at the top of every chat.

## Approved experience

The current `서비스 예시 작동 방식` card is removed from the persistent top area of the conversation.

Before the first message, the empty-state guidance shows a quiet prompt below its description:

> 어떤 내용을 적어야 할지 막막하신가요?
>
> 예시 질문 보기

`예시 질문 보기` is a small text-style button rather than a bordered card or primary action. It must remain readable and keyboard-accessible but visually subordinate to the conversation heading and message composer.

Selecting the button expands the existing grouped examples directly below the prompt. The examples preserve their current category labels and question text. Selecting an example:

1. copies that example into the existing chat message state through `setQuestion`;
2. returns focus toward the composer;
3. collapses the example list so the user can review or edit the inserted text.

After the first user message is sent, the empty-state prompt and example list disappear with the rest of the empty state. No additional persistent example button is added beside the composer.

## Component boundaries

`ChatScreenV2` continues to own the existing `quickQuestionGroups` data and `question` state. The quick-example disclosure moves inside the `!hasConversation` empty-state branch. No new data source or API is introduced.

The disclosure remains a native `details`/`summary` control or an equivalently keyboard-accessible button-controlled region. Its label changes from `서비스 예시 작동 방식` to `예시 질문 보기`.

## Visual hierarchy

- No outer card border, large background panel, or full-width header.
- Prompt copy uses muted secondary text.
- The disclosure trigger is compact and link-like, with a small chevron or plus indicator.
- Expanded examples use compact category headings and wrap as small chips.
- The expanded list may use a subtle local surface for separation, but it must not recreate the removed large card.
- Desktop and mobile use the same hierarchy; mobile examples stack or wrap without horizontal overflow.

## Data and backend contracts

The change is frontend-only. It does not modify:

- chat submission callbacks;
- `user_text`, `consultation_type`, `facts`, attachments, or conversation history;
- authentication or guest-session behavior;
- the text or grouping of existing example questions.

## Error handling and accessibility

- The trigger exposes its expanded state.
- Keyboard users can open the examples and select a question.
- Example buttons retain visible focus styling.
- Selecting an example never submits it automatically.
- If focus cannot be moved programmatically, the populated textarea remains available in normal document order; no error message is required.

## Verification

- Update the layout contract test before production code.
- Verify the old prominent heading and top-level quick-example block are absent.
- Verify the empty state contains `예시 질문 보기`.
- Verify example selection still calls `setQuestion(item)` and does not call `onSubmit`.
- Run the full frontend Node test suite and Vite production build.
- Inspect the initial and expanded states in the local browser at desktop and mobile widths.
