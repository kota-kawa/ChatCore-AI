import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const skillsCss = readFileSync(
  new URL("../public/static/css/pages/chat/skills.css", import.meta.url),
  "utf8",
);

function ruleBody(selector: string, css: string): string {
  const index = css.indexOf(selector);
  assert.ok(index >= 0, `${selector} must be styled`);
  const body = css.slice(index).match(/\{([\s\S]*?)\}/);
  assert.ok(body, `${selector} must have a declaration block`);
  return body[1];
}

test("every skill pill is the same size regardless of the name's length", () => {
  const section = ruleBody(":where(body.chat-page, .chat-page-shell) .skill-section {", skillsCss);
  assert.match(section, /--skill-chip-row-width:\s*\d/, "the section must declare the shared pill width");

  const row = ruleBody(":where(body.chat-page, .chat-page-shell) .skill-chip-row {", skillsCss);
  assert.match(row, /width:\s*var\(--skill-chip-row-width\)/);
  assert.match(row, /flex:\s*0 0 var\(--skill-chip-row-width\)/, "the pill must neither grow nor shrink with its name");

  const chip = ruleBody(":where(body.chat-page, .chat-page-shell) .skill-chip {", skillsCss);
  assert.match(chip, /flex:\s*1 1 auto/, "only the name area absorbs the fixed width");
  assert.doesNotMatch(chip, /max-width:/, "a max-width would make short and long names differ again");

  const name = ruleBody(":where(body.chat-page, .chat-page-shell) .skill-chip__name {", skillsCss);
  assert.match(name, /text-overflow:\s*ellipsis/);
  assert.match(name, /white-space:\s*nowrap/);

  for (const control of [".skill-chip__toggle {", ".skill-chip__delete {"]) {
    const body = ruleBody(`:where(body.chat-page, .chat-page-shell) ${control}`, skillsCss);
    assert.match(body, /flex:\s*0 0 auto/, `${control} must keep its natural size`);
  }
});

test("the stacked phone layout drops the fixed basis so rows are not 15rem tall", () => {
  const mobileCss = skillsCss.slice(skillsCss.indexOf("@media (max-width: 576px)"));
  const row = ruleBody(":where(body.chat-page, .chat-page-shell) .skill-chip-row {", mobileCss);
  assert.match(row, /flex:\s*0 0 auto/);
  assert.match(row, /width:\s*100%/);
});
