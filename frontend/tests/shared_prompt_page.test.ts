import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import SharedPromptPage from "../pages/shared/prompt/[id]/[[...slug]]";
import { LocaleProvider } from "../contexts/locale_context";

test("shared prompt page renders links to random prompt recommendations", () => {
  const html = renderToStaticMarkup(
    React.createElement(SharedPromptPage, {
      payload: {
        prompt: {
          id: 12,
          title: "現在表示しているプロンプト",
          category: "business",
          content: "このプロンプトの本文です。",
          content_format: "prompt",
          media_type: "text"
        }
      },
      recommendedPrompts: [
        {
          id: 21,
          title: "おすすめの会議メモ要約",
          category: "business",
          content: "会議の決定事項と次の行動を要約します。",
          content_format: "prompt",
          media_type: "text"
        }
      ],
      promptHtml: {
        content: "<p>このプロンプトの本文です。</p>",
        inputExamples: "",
        outputExamples: "",
        skillMarkdown: "",
        skillPythonScript: ""
      },
      pageUrl: "https://chatcore-ai.com/shared/prompt/12/current-prompt",
      defaultOgImageUrl: "https://chatcore-ai.com/static/img.jpg"
    })
  );

  assert.match(html, /おすすめのプロンプト/);
  assert.match(html, /おすすめの会議メモ要約/);
  assert.match(html, /href="\/shared\/prompt\/21/);
});

test("shared skill page renders multiple named resources with copy actions", () => {
  const html = renderToStaticMarkup(
    React.createElement(SharedPromptPage, {
      payload: {
        prompt: {
          id: 34,
          title: "複数ファイルのSKILL",
          category: "development",
          content_format: "skill",
          media_type: "text",
          skill_markdown: "# 手順",
          resources: [
            {
              path: "scripts/run.ts",
              role: "script",
              language: "typescript",
              content: "console.log('run');"
            },
            {
              path: "references/api.md",
              role: "reference",
              language: "markdown",
              content: "# API"
            }
          ]
        }
      },
      recommendedPrompts: [],
      promptHtml: {
        content: "",
        inputExamples: "",
        outputExamples: "",
        skillMarkdown: "<h1>手順</h1>",
        skillPythonScript: ""
      },
      pageUrl: "https://chatcore-ai.com/shared/prompt/34/multi-resource-skill",
      defaultOgImageUrl: "https://chatcore-ai.com/static/img.jpg"
    })
  );

  assert.match(html, /scripts\/run\.ts/);
  assert.match(html, /references\/api\.md/);
  assert.equal((html.match(/コピー/g) || []).length, 2);
});

test("shared prompt page renders labels in the requested locale during SSR", () => {
  // ラベルが <html lang> のフォールバックを使うと、SSR は日本語・クライアントは
  // 英語になり、ハイドレーション不一致（React error #418 / #425）を起こす。
  // If the labels fall back to <html lang>, SSR renders Japanese while the client
  // renders English, breaking hydration (React error #418 / #425).
  const props = {
    payload: {
      prompt: {
        id: 55,
        title: "Shared prompt in English",
        category: "business",
        content: "Body text.",
        content_format: "prompt",
        media_type: "text"
      }
    },
    recommendedPrompts: [],
    promptHtml: {
      content: "<p>Body text.</p>",
      inputExamples: "",
      outputExamples: "",
      skillMarkdown: "",
      skillPythonScript: ""
    },
    pageUrl: "https://chatcore-ai.com/shared/prompt/55/shared-prompt-in-english",
    defaultOgImageUrl: "https://chatcore-ai.com/static/img.jpg"
  };

  const renderWithLocale = (locale: "en" | "ja") => renderToStaticMarkup(
    React.createElement(LocaleProvider, {
      initialLocale: locale,
      children: React.createElement(SharedPromptPage, props)
    })
  );

  const englishHtml = renderWithLocale("en");
  const japaneseHtml = renderWithLocale("ja");

  assert.match(englishHtml, /shared-prompt-pill">Format: Prompt</);
  assert.doesNotMatch(englishHtml, /プロンプト/);
  assert.match(japaneseHtml, /shared-prompt-pill">フォーマット: プロンプト</);
});
