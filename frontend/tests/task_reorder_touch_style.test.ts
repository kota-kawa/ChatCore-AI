import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const taskOrderCss = readFileSync(
  new URL("../public/static/css/pages/chat/tasks_order/tasks_order.css", import.meta.url),
  "utf8",
);

const setupCss = readFileSync(
  new URL("../public/static/css/pages/chat/setup.css", import.meta.url),
  "utf8",
);

// 指定した @media クエリのブロックだけを取り出す（ネストしたルールの括弧を数えて終端を探す）
// Extract a single @media block by balancing braces so nested rules stay inside
function extractMediaBlock(css: string, query: string): string | null {
  const start = css.indexOf(query);
  if (start === -1) return null;

  const bodyStart = css.indexOf("{", start);
  if (bodyStart === -1) return null;

  let depth = 0;
  for (let index = bodyStart; index < css.length; index += 1) {
    if (css[index] === "{") depth += 1;
    if (css[index] === "}") {
      depth -= 1;
      if (depth === 0) return css.slice(bodyStart + 1, index);
    }
  }

  return null;
}

// セレクタ完全一致でルール本文を取り出す（.editable と .editable.dragging を取り違えないようにする）
// Read a rule body by exact selector so .editable and .editable.dragging never get mixed up
function extractRuleBody(css: string, selector: string): string | null {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = css.match(new RegExp(`(^|[};/])\\s*${escaped}\\s*\\{([^}]*)\\}`, "m"));
  return match?.[2] ?? null;
}

const EDITABLE_SELECTOR = ":where(body.chat-page, .chat-page-shell) .task-wrapper.editable";
const DRAGGING_SELECTOR = ":where(body.chat-page, .chat-page-shell) .task-wrapper.editable.dragging";

// カードが画面を覆うスマホでは、カード上から始めた縦スワイプでもページを送れないと操作不能になる
// Cards cover the phone screen, so a swipe starting on a card must still scroll the page
test("editable task cards leave vertical panning to the browser", () => {
  const editableTaskRule = extractRuleBody(taskOrderCss, EDITABLE_SELECTOR);

  assert.ok(editableTaskRule, "editable task card styles must be present");
  assert.match(
    editableTaskRule,
    /touch-action:\s*pan-y\s*;/,
    "a plain vertical swipe on a card must keep scrolling the page",
  );
});

test("the mobile breakpoint keeps the same panning rule", () => {
  const mobileBlock = extractMediaBlock(setupCss, "@media (max-width: 576px)");
  assert.ok(mobileBlock, "mobile media block must be present");

  const editableTaskRule = extractRuleBody(mobileBlock, EDITABLE_SELECTOR);
  assert.ok(editableTaskRule, "the mobile override for editable cards must be present");
  assert.match(
    editableTaskRule,
    /touch-action:\s*pan-y\s*;/,
    "the mobile override must not reintroduce touch-action: none and block scrolling",
  );
});

// 掴んだ後まで pan-y のままだと、並び替え中にページが一緒に動いてしまう
// Staying on pan-y after the pick-up would let the page scroll along with the drag
test("a picked-up card claims the whole gesture", () => {
  const sources: Array<[string, string]> = [
    ["tasks_order.css", taskOrderCss],
    ["setup.css mobile block", extractMediaBlock(setupCss, "@media (max-width: 576px)") ?? ""],
  ];

  for (const [name, css] of sources) {
    const draggingRule = extractRuleBody(css, DRAGGING_SELECTOR);
    assert.ok(draggingRule, `${name} must style the dragging card`);
    assert.match(
      draggingRule,
      /touch-action:\s*none\s*;/,
      `${name} must stop browser panning once the card is being dragged`,
    );
  }
});

test("long-press cards suppress the iOS callout menu", () => {
  const editableTaskRule = extractRuleBody(taskOrderCss, EDITABLE_SELECTOR);

  assert.ok(editableTaskRule, "editable task card styles must be present");
  assert.match(
    editableTaskRule,
    /-webkit-touch-callout:\s*none\s*;/,
    "the long-press gesture must not open the iOS callout menu instead of grabbing the card",
  );
});
