import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const memoCss = readFileSync(
  new URL("../public/memo/static/css/memo_form.css", import.meta.url),
  "utf8",
);

function ruleBody(selector: string) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = memoCss.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`));
  assert.ok(match, `missing rule: ${selector}`);
  return match[1];
}

function lineHeightOf(selector: string) {
  const match = ruleBody(selector).match(/line-height:\s*([\d.]+)/);
  assert.ok(match, `${selector} must set line-height`);
  return match[1];
}

// プレビューと編集を行き来したときに行位置が動かないよう、行間は両面で同じ値にそろえる
// Preview and editor share one line-height so switching never shifts the lines of a plain memo
test("the memo preview and the detail editor use the same line-height", () => {
  const preview = lineHeightOf(":where(body.memo-page, .memo-page-shell) .memo-preview-content");
  const editor = lineHeightOf(".memo-modal .memo-modal__edit-textarea");
  assert.equal(editor, preview);
  assert.match(
    ruleBody(":where(body.memo-page, .memo-page-shell) .memo-preview-content .memo-preserved-blank-line,\n:where(body.memo-page, .memo-page-shell) .memo-item__excerpt .memo-preserved-blank-line"),
    new RegExp(`height:\\s*${preview.replace(".", "\\.")}em`),
    "a preserved blank line must be exactly one preview line tall",
  );
});

// 見出しをブラウザ既定のままにすると、編集面から切り替えた瞬間に文字が倍のサイズへ跳ねる
// Headings left at browser defaults double in size the moment the editor switches to the preview
test("memo preview headings use a restrained scale instead of browser defaults", () => {
  const scope = ":where(body.memo-page, .memo-page-shell) .memo-preview-content";
  assert.match(ruleBody(`${scope} :is(h1, h2, h3, h4, h5, h6)`), /font-weight:\s*700/);
  const h1 = ruleBody(`${scope} h1`).match(/font-size:\s*([\d.]+)rem/);
  const h2 = ruleBody(`${scope} h2`).match(/font-size:\s*([\d.]+)rem/);
  const rest = ruleBody(`${scope} :is(h3, h4, h5, h6)`).match(/font-size:\s*([\d.]+)rem/);
  assert.ok(h1 && h2 && rest, "h1, h2 and h3+ must each set an explicit rem size");
  assert.ok(Number(h1[1]) <= 1.25, "h1 must stay within a quarter step of the body text");
  assert.ok(Number(h1[1]) > Number(h2[1]) && Number(h2[1]) > Number(rest[1]), "the scale must descend");
  assert.equal(rest[1], "1", "h3 and below stay at body size");
});

test("the first and last preview blocks carry no outer margin so text starts where the editor's does", () => {
  const scope = ":where(body.memo-page, .memo-page-shell) .memo-preview-content";
  assert.match(ruleBody(`${scope} > :first-child`), /margin-top:\s*0/);
  assert.match(ruleBody(`${scope} > :last-child`), /margin-bottom:\s*0/);
});
