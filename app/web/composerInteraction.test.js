import assert from "node:assert/strict";
import test from "node:test";

import { composerKeyAction } from "./composerInteraction.js";

test("Enter submits a ready non-empty composer", () => {
  assert.equal(
    composerKeyAction(
      { key: "Enter" },
      { hasContent: true, isSubmitting: false },
    ),
    "submit",
  );
});

test("Shift+Enter remains a newline", () => {
  assert.equal(
    composerKeyAction(
      { key: "Enter", shiftKey: true },
      { hasContent: true, isSubmitting: false },
    ),
    "newline",
  );
});

test("IME composition never submits", () => {
  const ready = { hasContent: true, isSubmitting: false };

  assert.equal(
    composerKeyAction({ key: "Enter", isComposing: true }, ready),
    "ignore",
  );
  assert.equal(
    composerKeyAction({ key: "Enter", nativeEvent: { isComposing: true } }, ready),
    "ignore",
  );
  assert.equal(
    composerKeyAction({ key: "Enter", keyCode: 229 }, ready),
    "ignore",
  );
});

test("empty and busy composers do not submit", () => {
  assert.equal(
    composerKeyAction(
      { key: "Enter" },
      { hasContent: false, isSubmitting: false },
    ),
    "ignore",
  );
  assert.equal(
    composerKeyAction(
      { key: "Enter" },
      { hasContent: true, isSubmitting: true },
    ),
    "ignore",
  );
});

test("unrelated keys leave the composer unchanged", () => {
  assert.equal(
    composerKeyAction(
      { key: "ArrowDown" },
      { hasContent: true, isSubmitting: false },
    ),
    "ignore",
  );
});
