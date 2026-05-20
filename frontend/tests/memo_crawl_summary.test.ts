import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { MemoCrawlSummary } from "../pages/memo";

test("memo page renders crawlable public content without private memo data", () => {
  const html = renderToStaticMarkup(React.createElement(MemoCrawlSummary));

  assert.match(html, /AIとの作業ログを整理するノート画面/);
  assert.match(html, /Chat Coreのメモ画面/);
  assert.match(html, /AIチャットの回答をメモとして保存/);
  assert.match(html, /共有リンクで必要なメモだけ公開/);
});
