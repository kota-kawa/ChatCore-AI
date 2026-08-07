import { beforeEach, describe, expect, it } from "vitest";

import { patchElementChildren } from "../lib/chat_page/streaming_dom_patch";

// 出典pillのマークアップ。faviconのimgは中身が実行時に差し替わる代表例。
// Source pill markup; its favicon <img> is the element whose runtime state matters.
function citation(href: string, label: string) {
  return [
    `<a class="web-search-citation" href="${href}" target="_blank">`,
    '<span class="web-search-citation__icon">',
    '<span class="web-search-citation__fallback">E</span>',
    `<img class="web-search-citation__favicon" src="${href}/favicon.ico" alt="">`,
    "</span>",
    `<span class="web-search-citation__label">${label}</span>`,
    "</a>",
  ].join("");
}

describe("patchElementChildren", () => {
  let container: HTMLDivElement;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
  });

  it("fills an empty container like a plain insertion", () => {
    patchElementChildren(container, "<p>回答の途中</p>");

    expect(container.innerHTML).toBe("<p>回答の途中</p>");
  });

  it("reuses the surrounding nodes while streamed text grows", () => {
    patchElementChildren(container, `<p>参照は${citation("https://example.com", "Example")}です。</p>`);
    const paragraph = container.querySelector("p");
    const pill = container.querySelector("a.web-search-citation");
    const favicon = container.querySelector("img.web-search-citation__favicon");

    patchElementChildren(
      container,
      `<p>参照は${citation("https://example.com", "Example")}です。続きも生成中。</p>`,
    );

    // 同一ノードが残っていることが、favicon再読み込みの点滅とクリック取りこぼしを防ぐ条件。
    // Keeping the same nodes is what prevents the favicon blink and the lost clicks.
    expect(container.querySelector("p")).toBe(paragraph);
    expect(container.querySelector("a.web-search-citation")).toBe(pill);
    expect(container.querySelector("img.web-search-citation__favicon")).toBe(favicon);
    expect(container.textContent).toContain("続きも生成中。");
  });

  it("keeps an opened details and the inline styles of its animation", () => {
    const trace = '<details class="web-search-sources"><summary class="web-search-sources__summary">出典</summary><ul class="web-search-sources__list"><li>A</li></ul></details>';
    patchElementChildren(container, `${trace}<p>本文</p>`);
    const details = container.querySelector<HTMLDetailsElement>("details.web-search-sources");
    const list = container.querySelector<HTMLElement>(".web-search-sources__list");
    if (!details || !list) throw new Error("details markup was not rendered");
    details.open = true;
    details.dataset.webSearchSourcesState = "opening";
    list.style.height = "120px";

    patchElementChildren(container, `${trace}<p>本文が伸びた</p>`);

    expect(container.querySelector("details.web-search-sources")).toBe(details);
    expect(details.open).toBe(true);
    expect(details.dataset.webSearchSourcesState).toBe("opening");
    expect(list.style.height).toBe("120px");
  });

  it("keeps runtime classes that the incoming markup does not describe", () => {
    patchElementChildren(container, `<p>${citation("https://example.com", "Example")}</p>`);
    const icon = container.querySelector<HTMLElement>(".web-search-citation__icon");
    if (!icon) throw new Error("citation markup was not rendered");
    icon.classList.add("web-search-citation__icon--fallback");

    patchElementChildren(container, `<p>${citation("https://example.com", "Example")}。</p>`);

    expect(icon).toHaveClass("web-search-citation__icon--fallback");
  });

  it("replaces a citation pill that points at another source", () => {
    patchElementChildren(container, `<p>${citation("https://example.com", "Example")}</p>`);
    const pill = container.querySelector("a.web-search-citation");

    patchElementChildren(container, `<p>${citation("https://other.example", "Other")}</p>`);

    const patchedPill = container.querySelector<HTMLAnchorElement>("a.web-search-citation");
    expect(patchedPill).not.toBe(pill);
    expect(patchedPill?.getAttribute("href")).toBe("https://other.example");
    expect(container.querySelector(".web-search-citation__label")?.textContent).toBe("Other");
  });

  it("syncs attributes, replaces retyped nodes and drops removed ones", () => {
    patchElementChildren(container, '<p><a href="https://a.example" title="A">link</a></p><p>後半</p>');
    const paragraph = container.querySelector("p");

    patchElementChildren(container, '<p><a href="https://b.example">link</a></p><ul><li>後半</li></ul>');

    const anchor = container.querySelector("a");
    expect(container.querySelector("p")).toBe(paragraph);
    expect(anchor?.getAttribute("href")).toBe("https://b.example");
    expect(anchor?.hasAttribute("title")).toBe(false);
    expect(container.querySelectorAll("p").length).toBe(1);
    expect(container.querySelector("ul li")?.textContent).toBe("後半");
  });

  it("does not rewrite an image source that stayed the same", () => {
    patchElementChildren(container, `<p>${citation("https://example.com", "Example")}</p>`);
    const favicon = container.querySelector<HTMLImageElement>("img.web-search-citation__favicon");
    if (!favicon) throw new Error("favicon markup was not rendered");
    let sourceWrites = 0;
    const setAttribute = favicon.setAttribute.bind(favicon);
    favicon.setAttribute = (name: string, value: string) => {
      if (name === "src") sourceWrites += 1;
      setAttribute(name, value);
    };

    patchElementChildren(container, `<p>${citation("https://example.com", "Example")}</p>`);

    expect(sourceWrites).toBe(0);
  });
});
