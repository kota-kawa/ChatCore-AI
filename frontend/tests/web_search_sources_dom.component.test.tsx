import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import {
  bindWebSearchSourcesInteractions,
} from "../lib/chat_page/web_search_sources_dom";

// jsdom は prefers-reduced-motion を持たないため、アニメーション経路を必ず通す。
// jsdom has no prefers-reduced-motion, so force the animated path.
vi.mock("../lib/chat_page/dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/chat_page/dom")>()),
  prefersReducedMotion: () => false,
}));

// 仮想リストの行は内容なりの高さで測られる。開閉アニメーションが終了値を
// 適用したまま残ると、外側パネルの高さが開いた瞬間の値で固定され、あとから
// ステップの「参照したWebサイト」を開いても伸びず、あふれた内容が下の
// メッセージへ重なる。ここではその固定が必ず解除されることを守る。
// Virtual-list rows are measured from their content. If the open/close animation
// keeps applying its end value, the outer panel stays frozen at the height it had
// when it opened, so a step expanded later overflows onto the messages below.
// These tests pin down that the pinned height is always released.

const TRACE_HTML = [
  '<details class="web-search-sources web-search-sources--trace">',
  '<summary class="web-search-sources__summary">回答までのステップ</summary>',
  '<div class="web-search-sources__list">',
  '<ol class="web-search-sources__steps">',
  '<li class="web-search-sources__step web-search-sources__step--has-sources">',
  '<details class="web-search-sources__step-details">',
  '<summary class="web-search-sources__step-summary">Web検索</summary>',
  '<div class="web-search-sources__step-body">出典</div>',
  "</details></li></ol></div></details>",
].join("");

type FakeAnimation = {
  cancel: ReturnType<typeof vi.fn>;
  finish: () => void;
  onfinish: (() => void) | null;
  oncancel: (() => void) | null;
};

const animations: FakeAnimation[] = [];
let cleanup: (() => void) | null = null;

function mountTrace() {
  const container = document.createElement("div");
  container.className = "bot-message";
  container.innerHTML = TRACE_HTML;
  document.body.appendChild(container);
  // jsdom はレイアウトしないので、アニメーションが必要と判断できる高さを与える。
  // jsdom does not lay out, so give the list a height the animation can act on.
  const list = container.querySelector<HTMLElement>(".web-search-sources__list");
  if (list) Object.defineProperty(list, "scrollHeight", { value: 240, configurable: true });
  cleanup = bindWebSearchSourcesInteractions(container);
  return container;
}

beforeAll(() => {
  if (typeof Element.prototype.scrollIntoView !== "function") {
    Element.prototype.scrollIntoView = () => {};
  }
  // jsdom には Web Animations API が無いため、終了と cancel を観測できる最小の
  // スタブを置く。fill: "both" の「終了後も効き続ける」性質を再現する。
  // jsdom has no Web Animations API, so stub the minimum needed to observe finish
  // and cancel, mirroring how a fill: "both" animation keeps applying its end value.
  Element.prototype.animate = function animate(this: Element) {
    const element = this as HTMLElement;
    const animation: FakeAnimation = {
      cancel: vi.fn(() => {
        element.dataset.animationFill = "released";
      }),
      onfinish: null,
      oncancel: null,
      finish() {
        element.dataset.animationFill = "pinned";
        this.onfinish?.();
      },
    };
    animations.push(animation);
    return animation as unknown as Animation;
  } as typeof Element.prototype.animate;

  Element.prototype.getAnimations = function getAnimations(this: Element) {
    const element = this as HTMLElement;
    if (element.dataset.animationFill !== "pinned") return [];
    return animations
      .filter((animation) => animation.cancel.mock.calls.length === 0)
      .map((animation) => animation as unknown as Animation);
  } as typeof Element.prototype.getAnimations;
});

afterEach(() => {
  cleanup?.();
  cleanup = null;
  animations.length = 0;
  document.body.innerHTML = "";
});

describe("web search sources height lock", () => {
  it("releases the animated height once the panel finished opening", () => {
    const container = mountTrace();
    const summary = container.querySelector<HTMLElement>(".web-search-sources__summary");
    const list = container.querySelector<HTMLElement>(".web-search-sources__list");
    if (!summary || !list) throw new Error("the trace was not rendered");

    summary.click();
    expect(animations).toHaveLength(1);

    animations[0].finish();

    // 終了値が残っていると、あとから伸びられずにあふれる。
    // A lingering end value is what stops the panel from growing later.
    expect(animations[0].cancel).toHaveBeenCalled();
    expect(list.style.height).toBe("");
    expect(list.style.overflow).toBe("");
  });

  it("releases a stale height lock when a step is expanded", () => {
    const container = mountTrace();
    const list = container.querySelector<HTMLElement>(".web-search-sources__list");
    const stepDetails = container.querySelector<HTMLDetailsElement>(
      "details.web-search-sources__step-details",
    );
    if (!list || !stepDetails) throw new Error("the trace was not rendered");

    // 高さが固定されたまま残っている状態を作る。
    // Simulate a height that stayed pinned.
    list.dataset.animationFill = "pinned";
    list.style.height = "120px";
    animations.push({
      cancel: vi.fn(() => {
        list.dataset.animationFill = "released";
      }),
      onfinish: null,
      oncancel: null,
      finish() {},
    });

    stepDetails.open = true;
    stepDetails.dispatchEvent(new Event("toggle"));

    expect(animations[0].cancel).toHaveBeenCalled();
    expect(list.style.height).toBe("");
  });
});
