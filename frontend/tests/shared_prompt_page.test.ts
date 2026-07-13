import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import SharedPromptPage from "../pages/shared/prompt/[id]/[[...slug]]";

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
