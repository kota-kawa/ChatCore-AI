import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const documentSource = readFileSync(new URL("../pages/_document.tsx", import.meta.url), "utf8");

// Chat Core は日本語と英語を別 URL で SSR する。ブラウザ自動翻訳に初期 HTML を
// 書き換えさせると React の初回描画と一致せず #418 になるため、標準属性と
// Google 向け指定の両方を文書シェルに維持する。
// Chat Core SSRs Japanese and English at separate URLs. If browser translation
// rewrites the initial HTML, React's first render no longer matches and raises #418,
// so retain both the standard attribute and Google's opt-out marker.
test("document disables browser translation before hydration", () => {
  assert.match(documentSource, /<Html\b[^>]*\btranslate="no"/);
  assert.match(documentSource, /<Html\b[^>]*\bclassName="notranslate"/);
  assert.match(documentSource, /<meta\s+name="google"\s+content="notranslate"\s*\/>/);
});
