import assert from "node:assert/strict";
import test from "node:test";

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { SafeMarkdown, safeMarkdownUrl } from "./SafeMarkdown.js";

function render(content) {
  return renderToStaticMarkup(React.createElement(SafeMarkdown, { content }));
}

test("safe markdown renders CommonMark and GFM structure", () => {
  const html = render([
    "## 결론",
    "",
    "- 첫 번째 항목",
    "- 두 번째 항목",
    "",
    "> 확인이 필요한 안내",
    "",
    "`인라인 코드`",
    "",
    "| 구분 | 내용 |",
    "| --- | --- |",
    "| 결과 | 확인 |",
  ].join("\n"));

  assert.match(html, /<h2[^>]*>결론<\/h2>/);
  assert.match(html, /<ul[^>]*>/);
  assert.match(html, /<blockquote[^>]*>/);
  assert.match(html, /<code[^>]*>인라인 코드<\/code>/);
  assert.match(html, /class="markdown-table-scroll"/);
  assert.match(html, /<table[^>]*>/);
  assert.doesNotMatch(html, /node=|\[object Object\]/);
});

test("safe markdown drops raw HTML and unsafe URL protocols", () => {
  const html = render([
    "<script>alert('xss')</script>",
    "<img src=x onerror=alert(1)>",
    "[위험한 링크](javascript:alert(1))",
    "[데이터 링크](data:text/html,unsafe)",
  ].join("\n\n"));

  assert.doesNotMatch(html, /<script|<img|onerror|javascript:|data:text\/html/i);
  assert.equal(safeMarkdownUrl("javascript:alert(1)"), "");
  assert.equal(safeMarkdownUrl("data:text/html,unsafe"), "");
});

test("safe markdown keeps approved links and protects external tabs", () => {
  const html = render([
    "[내부](/reports/1)",
    "[외부](https://example.com/report)",
    "[메일](mailto:help@example.com)",
  ].join(" "));

  assert.match(html, /href="\/reports\/1"/);
  assert.match(html, /href="https:\/\/example\.com\/report"/);
  assert.match(html, /target="_blank"/);
  assert.match(html, /rel="noreferrer noopener"/);
  assert.match(html, /href="mailto:help@example\.com"/);
});

test("safe markdown treats non-string content as empty", () => {
  assert.equal(render({ answer: "객체 답변" }), "");
  assert.equal(render(null), "");
});
