import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const globalCss = readFileSync(
  new URL("../styles/globals.css", import.meta.url),
  "utf8",
);
const promptShareAgentCss = readFileSync(
  new URL("../public/prompt_share/static/css/pages/prompt_share.ai-agent.css", import.meta.url),
  "utf8",
);
const promptShareDarkModeCss = readFileSync(
  new URL("../public/prompt_share/static/css/pages/prompt_share.dark-mode.css", import.meta.url),
  "utf8",
);

function removeCssComments(css: string) {
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}

// プロンプト共有ページのCSSは、bodyクラス経由でグローバルエージェントを上書きしてはいけない。
// Prompt-share CSS must not override the global agent through the page's body class.
test("prompt-share styles leave the shared support agent appearance to global CSS", () => {
  const promptShareCss = removeCssComments(`${promptShareAgentCss}\n${promptShareDarkModeCss}`);

  assert.doesNotMatch(
    promptShareCss,
    /\.(?:global-ai-agent|ai-agent|mini-chat|modal-close-btn)[-\w]*/,
    "prompt-share styles must not define selectors for the shared support agent",
  );
  assert.match(globalCss, /\.global-ai-agent-button\s*\{/);
  assert.match(globalCss, /\.global-ai-agent-modal\.global-ai-agent-modal\s*\{/);
});

test("Chaco modal entry animation stays on compositor-friendly properties", () => {
  const chacoSurface = Array.from(
    globalCss.matchAll(/\.global-ai-agent-modal\.global-ai-agent-modal\s*\{[\s\S]*?\n\}/g),
  ).find(([block]) => block.includes("--chaco-ink"))?.[0] ?? "";
  const animationStart = globalCss.indexOf("@keyframes chacoAgentDeploy");
  const animationEnd = globalCss.indexOf("/* Dark mode keeps Chaco's pastel accents", animationStart);
  const chacoAnimations = globalCss.slice(animationStart, animationEnd);

  assert.match(chacoSurface, /backdrop-filter:\s*none/);
  assert.match(chacoSurface, /-webkit-backdrop-filter:\s*none/);
  assert.match(chacoSurface, /will-change:\s*transform,\s*opacity/);
  assert.match(chacoAnimations, /transform:\s*translate3d\(/);
  assert.doesNotMatch(chacoAnimations, /clip-path|filter:/);
});
