import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const SAFE_URL = /^(https?:|mailto:|tel:|\/|#)/i;

export function safeMarkdownUrl(value) {
  if (typeof value !== "string") return "";
  const normalized = value.trim();
  return normalized && SAFE_URL.test(normalized) ? normalized : "";
}

function markdownElement(tagName, className) {
  return function MarkdownElement({ children, node: _node, ...props }) {
    return React.createElement(tagName, { ...props, className }, children);
  };
}

const MARKDOWN_COMPONENTS = {
  h1: markdownElement("h1", "safe-markdown__heading safe-markdown__heading--1"),
  h2: markdownElement("h2", "safe-markdown__heading safe-markdown__heading--2"),
  h3: markdownElement("h3", "safe-markdown__heading safe-markdown__heading--3"),
  p: markdownElement("p", "safe-markdown__paragraph"),
  ul: markdownElement("ul", "safe-markdown__list"),
  ol: markdownElement("ol", "safe-markdown__list safe-markdown__list--ordered"),
  blockquote: markdownElement("blockquote", "safe-markdown__quote"),
  pre: markdownElement("pre", "safe-markdown__code-block"),
  code: markdownElement("code", "safe-markdown__code"),
  table: ({ children, node: _node, ...props }) => React.createElement(
    "div",
    { className: "markdown-table-scroll" },
    React.createElement("table", { ...props, className: "safe-markdown__table" }, children),
  ),
  a: ({ children, href = "", node: _node, ...props }) => {
    const safeHref = safeMarkdownUrl(href);
    const external = /^https?:\/\//i.test(safeHref);
    return React.createElement(
      "a",
      {
        ...props,
        className: "safe-markdown__link",
        href: safeHref || undefined,
        target: external ? "_blank" : undefined,
        rel: external ? "noreferrer noopener" : undefined,
      },
      children,
    );
  },
};

export function SafeMarkdown({ content = "" }) {
  const safeContent = typeof content === "string" ? content.trim() : "";
  if (!safeContent) return null;

  return React.createElement(
    "div",
    { className: "safe-markdown" },
    React.createElement(
      ReactMarkdown,
      {
        remarkPlugins: [remarkGfm],
        skipHtml: true,
        urlTransform: safeMarkdownUrl,
        components: MARKDOWN_COMPONENTS,
      },
      safeContent,
    ),
  );
}
