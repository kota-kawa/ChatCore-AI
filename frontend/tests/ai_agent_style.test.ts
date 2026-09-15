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
  assert.match(chacoSurface, /contain:\s*layout paint/);
  assert.match(chacoSurface, /will-change:\s*transform,\s*opacity/);
  assert.match(chacoSurface, /animation:\s*none/);
  assert.match(
    globalCss,
    /\.global-ai-agent-modal\.global-ai-agent-modal\.is-preparing\s*\{[\s\S]*?opacity:\s*0;[\s\S]*?transform:\s*translate3d\(/,
  );
  assert.match(
    globalCss,
    /\.global-ai-agent-modal\.global-ai-agent-modal\.is-open\s*\{\s*animation:\s*chacoAgentDeploy/,
  );
  assert.match(chacoAnimations, /transform:\s*translate3d\(/);
  assert.doesNotMatch(
    chacoAnimations,
    /(?:top|left|right|bottom|width|height|clip-path|filter|box-shadow|background-position)\s*:/,
  );
});

// キーボードが出ている間も入力欄が見えるように、モーダルの高さは実測した表示領域に従う。
// The modal's height follows the measured visual viewport so its input stays visible with the
// on-screen keyboard open.
test("Chaco modal sizes itself from the visual viewport, not from 100vh", () => {
  const surface = removeCssComments(globalCss).match(
    /\.global-ai-agent-modal\.global-ai-agent-modal\s*\{[\s\S]*?\n\}/,
  )?.[0] ?? "";
  assert.match(
    surface,
    /--agent-modal-available-height:\s*calc\(var\(--draggable-modal-viewport-height,\s*100vh\)\s*-\s*24px\)/,
    "the available height must come from the measured viewport with a 100vh fallback",
  );

  // 下限も表示領域に収める。素の px の下限はキーボードの上にはみ出す原因になる。
  // The floor is capped by the same value; a plain px floor is what pushed the input off-screen.
  for (const [label, block] of [
    ["desktop", surface],
    ["mobile", removeCssComments(globalCss)
      .slice(removeCssComments(globalCss).indexOf("@media (max-width: 640px)"))
      .match(/\.global-ai-agent-modal\.global-ai-agent-modal\s*\{[\s\S]*?\n\s*\}/)?.[0] ?? ""],
  ] as const) {
    assert.match(block, /height:\s*min\(\d+px,\s*var\(--agent-modal-available-height\)\)/, label);
    assert.match(block, /min-height:\s*min\(\d+px,\s*var\(--agent-modal-available-height\)\)/, label);
  }

  // モーダル側に値を渡すのは DraggableModal の責務。
  // Handing the measured height to the modal is DraggableModal's job.
  const draggableModal = readFileSync(
    new URL("../components/ui/DraggableModal.tsx", import.meta.url),
    "utf8",
  );
  assert.match(draggableModal, /"--draggable-modal-viewport-height": `\$\{viewportHeight\}px`/);
});
