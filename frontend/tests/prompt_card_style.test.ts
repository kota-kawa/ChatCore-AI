import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const promptShareCardCss = readFileSync(
  new URL("../public/prompt_share/static/css/pages/prompt_share.cards-actions.css", import.meta.url),
  "utf8",
);
const promptShareFoundationCss = readFileSync(
  new URL("../public/prompt_share/static/css/pages/prompt_share.foundation.css", import.meta.url),
  "utf8",
);
const promptShareDarkModeCss = readFileSync(
  new URL("../public/prompt_share/static/css/pages/prompt_share.dark-mode.css", import.meta.url),
  "utf8",
);

test("added Skills use the success color while keeping the prompt action treatment", () => {
  assert.match(promptShareFoundationCss, /--ps-skill-added:\s*var\(--ps-success\);/);

  const skillStateRule = promptShareCardCss.match(
    /\.prompt-share-page \.add-to-skill-btn\.added-to-skills\s*\{([\s\S]*?)\}/,
  );
  assert.ok(skillStateRule, "the added Skill button must have a dedicated state rule");
  assert.match(skillStateRule[1], /color:\s*var\(--ps-skill-added\);/);
  assert.match(skillStateRule[1], /background:\s*transparent;/);
  assert.match(skillStateRule[1], /box-shadow:\s*none;/);

  assert.match(
    promptShareCardCss,
    /\.add-to-skill-btn\.added-to-skills\.is-celebrating i[\s\S]*?animation:\s*prompt-action-icon-pop/,
  );
  assert.match(
    promptShareCardCss,
    /\.add-to-skill-btn\.added-to-skills\.is-celebrating::after[\s\S]*?animation:\s*prompt-action-burst/,
  );
});

test("dark mode keeps the added Skill button green", () => {
  assert.match(promptShareDarkModeCss, /--ps-skill-added:\s*#4ade80;/);
  assert.match(
    promptShareDarkModeCss,
    /\.prompt-action-btn\.add-to-skill-btn\.added-to-skills,[\s\S]*?color:\s*var\(--ps-skill-added\);/,
  );
});
