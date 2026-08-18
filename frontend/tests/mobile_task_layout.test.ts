import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const setupCss = readFileSync(
  new URL("../public/static/css/pages/chat/setup.css", import.meta.url),
  "utf8",
);

const taskStateSource = readFileSync(
  new URL("../hooks/chat_page/use_home_page_task_state.ts", import.meta.url),
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

test("task cards span the full width on phones so titles are not forced to wrap", () => {
  const mobileBlock = extractMediaBlock(setupCss, "@media (max-width: 576px)");
  assert.ok(mobileBlock, "mobile media block must be present");

  const taskWrapperRule = mobileBlock.match(
    /\.task-selection \.task-wrapper,[^{]*\{([^}]*)\}/,
  );

  assert.ok(taskWrapperRule, "mobile task wrapper sizing must be present");
  assert.match(
    taskWrapperRule[1] ?? "",
    /flex:\s*1 1 100%\s*;/,
    "phones must lay the task cards out in a single column",
  );
  assert.match(
    taskWrapperRule[1] ?? "",
    /max-width:\s*100%\s*;/,
    "a single-column card must be allowed to use the full row width",
  );
});

test("tablet and desktop keep the two-column task layout", () => {
  const baseRule = setupCss.match(
    /:where\(body\.chat-page, \.chat-page-shell\) \.task-selection \.task-wrapper \{([^}]*)\}/,
  );

  assert.ok(baseRule, "base task wrapper sizing must be present");
  assert.match(
    baseRule[1] ?? "",
    /flex:\s*0 0 calc\(50% - 0\.5rem\)\s*;/,
    "the two-column layout must survive above the mobile breakpoint",
  );
});

test("task buttons do not cast a shadow in any visual state", () => {
  const promptCardRule = setupCss.match(
    /:where\(body\.chat-page, \.chat-page-shell\) \.prompt-card \{([^}]*)\}/,
  );
  const promptCardHoverRule = setupCss.match(
    /:where\(body\.chat-page, \.chat-page-shell\) \.prompt-card:hover \{([^}]*)\}/,
  );
  const darkPromptCardRule = setupCss.match(
    /\[data-theme="dark"\] :where\(body\.chat-page, \.chat-page-shell\) \.prompt-card \{([^}]*)\}/,
  );
  const darkPromptCardHoverRule = setupCss.match(
    /\[data-theme="dark"\] :where\(body\.chat-page, \.chat-page-shell\) \.prompt-card:hover \{([^}]*)\}/,
  );
  const taskDetailToggleRule = setupCss.match(
    /:where\(body\.chat-page, \.chat-page-shell\) \.task-detail-toggle \{([^}]*)\}/,
  );
  const darkTaskDetailToggleRule = setupCss.match(
    /\[data-theme="dark"\] :where\(body\.chat-page, \.chat-page-shell\) \.task-detail-toggle \{([^}]*)\}/,
  );

  for (const rule of [
    promptCardRule,
    promptCardHoverRule,
    darkPromptCardRule,
    darkPromptCardHoverRule,
    taskDetailToggleRule,
    darkTaskDetailToggleRule,
  ]) {
    assert.ok(rule, "task button shadow rule must be present");
    assert.match(rule[1] ?? "", /box-shadow:\s*none(?:\s*!important)?\s*;/);
  }
});

test("phones collapse the task list to three cards to keep the setup screen on one viewport", () => {
  const mobileLimit = taskStateSource.match(/const MOBILE_TASK_COLLAPSE_LIMIT = (\d+);/);

  assert.ok(mobileLimit, "mobile collapse limit must be defined");
  assert.equal(
    mobileLimit[1],
    "3",
    "a single-column list costs twice the height per task, so more than three overflows the viewport",
  );
});
