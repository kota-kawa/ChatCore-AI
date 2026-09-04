import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import SharedMemoPage from "../pages/shared/memo/[token]";
import { LocaleProvider } from "../contexts/locale_context";

test("shared memo page keeps the shared surface uniform when a memo has a color", () => {
  const html = renderToStaticMarkup(
    React.createElement(LocaleProvider, {
      initialLocale: "ja",
      children: React.createElement(SharedMemoPage, {
        payload: {
          memo: {
            title: "色付きメモ",
            created_at: "2026-09-04T09:30:00+00:00",
            ai_response: "共有する本文です。",
            background_color: "#fce8e6"
          }
        },
        pageUrl: "https://chatcore-ai.com/shared/memo/share-token",
        ogImageUrl: "https://chatcore-ai.com/static/img.jpg"
      })
    })
  );

  assert.match(html, /class="shared-memo-shell cc-fade-in"/);
  assert.doesNotMatch(html, /--shared-memo-color/);
});

test("shared memo stylesheet does not apply a memo-specific background color", () => {
  const stylesheet = readFileSync(
    new URL("../public/static/css/pages/shared_memo.css", import.meta.url),
    "utf8"
  );

  assert.doesNotMatch(stylesheet, /--shared-memo-color/);
});
