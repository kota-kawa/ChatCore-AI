import { render } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";

import { BotMessageHtml } from "../components/chat_page/bot_message_html";

describe("BotMessageHtml web-search citations", () => {
  it("renders a site-specific favicon and falls back when loading fails", () => {
    const response = '<a class="web-search-citation" href="https://example.com" target="_blank"><span class="web-search-citation__icon"><span class="web-search-citation__fallback">E</span><img class="web-search-citation__favicon" src="https://example.com/favicon.ico" alt="" referrerpolicy="no-referrer"></span><span class="web-search-citation__label">Example</span></a>';
    const { container } = render(<BotMessageHtml text={response} />);
    const favicon = container.querySelector<HTMLImageElement>(".web-search-citation__favicon");
    const icon = container.querySelector(".web-search-citation__icon");

    expect(favicon?.getAttribute("src")).toBe("https://example.com/favicon.ico");
    expect(favicon?.getAttribute("referrerpolicy")).toBe("no-referrer");
    favicon?.dispatchEvent(new Event("error"));
    expect(icon).toHaveClass("web-search-citation__icon--fallback");
  });

  it("renders a leading web-search trace and a safe numbered Markdown citation", () => {
    const response = [
      '<details class="web-search-sources web-search-sources--trace">',
      '<summary class="web-search-sources__summary">',
      '<span class="web-search-sources__label">回答までのステップ</span>',
      "</summary>",
      '<div class="web-search-sources__list">',
      '<a class="web-search-sources__link" href="https://source.example/report" target="_blank" onclick="alert(1)">検索結果を確認</a>',
      "</div>",
      "</details>",
      "",
      "確認できた内容です。[1](https://example.com/report?year=2026&lang=ja)",
    ].join("\n");
    const { container } = render(<BotMessageHtml text={response} />);

    const trace = container.querySelector("details.web-search-sources--trace");
    const source = container.querySelector<HTMLAnchorElement>(
      "a.web-search-sources__link",
    );
    const citation = Array.from(container.querySelectorAll<HTMLAnchorElement>("a")).find(
      (anchor) => anchor.textContent === "1",
    );

    expect(trace).not.toBeNull();
    expect(trace?.querySelector(".web-search-sources__label")).toHaveTextContent(
      "回答までのステップ",
    );
    expect(source?.getAttribute("href")).toBe("https://source.example/report");
    expect(source?.getAttribute("target")).toBe("_blank");
    expect(source?.getAttribute("rel")).toBe("noopener noreferrer");
    expect(source).not.toHaveAttribute("onclick");
    expect(citation).toHaveTextContent("1");
    expect(citation?.getAttribute("href")).toBe(
      "https://example.com/report?year=2026&lang=ja",
    );
  });

  it("removes an unsafe URL from a numbered Markdown citation", () => {
    const { container } = render(
      <BotMessageHtml text={"危険な参照です。[1](javascript:alert('xss'))"} />,
    );

    expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
    expect(container.textContent).toContain("危険な参照です。");
  });
});

// services/web_search_trace.py が実際に生成するマークアップの抜粋。
// サニタイズでアイコンやステップ種別のクラスが落ちると、タイムラインが
// 無地の箇条書きに戻ってしまうため、ここで固定する。
// An excerpt of the markup services/web_search_trace.py actually emits. If
// sanitization dropped the icons or the step-kind classes, the timeline would
// collapse back into a plain bullet list, so it is pinned here.
const ANSWER_STEPS_HTML = [
  '<details class="web-search-sources web-search-sources--trace">',
  '<summary class="web-search-sources__summary">',
  '<span class="web-search-sources__summary-main">',
  '<span class="web-search-sources__summary-icon"><i class="bi bi-list-check"></i></span>',
  '<span class="web-search-sources__summary-text">',
  '<span class="web-search-sources__label">回答までのステップ</span>',
  '<span class="web-search-sources__summary-detail">Web検索2回 · 参照サイト3件</span>',
  "</span>",
  "</span>",
  '<span class="web-search-sources__count">2ステップ</span>',
  '<span class="web-search-sources__chevron"><i class="bi bi-chevron-down"></i></span>',
  "</summary>",
  '<div class="web-search-sources__list">',
  '<ol class="web-search-sources__steps">',
  ...["Web検索", "追加検索"].map((title, index) =>
    [
      '<li class="web-search-sources__step web-search-sources__step--search web-search-sources__step--has-sources">',
      '<span class="web-search-sources__step-marker web-search-sources__step-marker--search"><i class="bi bi-search"></i></span>',
      '<details class="web-search-sources__step-details">',
      '<summary class="web-search-sources__step-summary">',
      '<span class="web-search-sources__step-main">',
      '<span class="web-search-sources__step-head">',
      `<span class="web-search-sources__step-title">${title}</span>`,
      '<span class="web-search-sources__step-badge">1件</span>',
      "</span>",
      `<span class="web-search-sources__step-query">検索語${index + 1}</span>`,
      '<span class="web-search-sources__step-detail">候補ページを取得しました。</span>',
      '<span class="web-search-sources__step-chips"><span class="web-search-sources__step-chip">example.com</span></span>',
      '<span class="web-search-sources__step-toggle">',
      '<i class="bi bi-globe2"></i>',
      '<span class="web-search-sources__step-toggle-label">参照したWebサイト</span>',
      '<span class="web-search-sources__step-toggle-count">1件</span>',
      '<span class="web-search-sources__step-chevron"><i class="bi bi-chevron-down"></i></span>',
      "</span>",
      "</span>",
      "</summary>",
      '<div class="web-search-sources__step-body">',
      '<ul class="web-search-sources__links">',
      '<li class="web-search-sources__item">',
      `<a class="web-search-sources__link" href="https://example.com/${index}" target="_blank">`,
      '<span class="web-search-citation__icon"><span class="web-search-citation__fallback">E</span>',
      '<img class="web-search-citation__favicon" src="https://example.com/favicon.ico" alt="" referrerpolicy="no-referrer"></span>',
      '<span class="web-search-sources__content">',
      `<span class="web-search-sources__title">記事${index + 1}</span>`,
      '<span class="web-search-sources__hostname">example.com</span>',
      "</span>",
      '<span class="web-search-sources__external">↗</span>',
      "</a></li></ul></div></details></li>",
    ].join(""),
  ),
  "</ol>",
  "</div>",
  "</details>",
].join("\n");

describe("BotMessageHtml answer steps", () => {
  it("keeps the step icons, kinds, and per-step source panels through sanitization", () => {
    const { container } = render(<BotMessageHtml text={`${ANSWER_STEPS_HTML}\n\n回答本文。`} />);

    const steps = container.querySelectorAll(".web-search-sources__step");
    expect(steps).toHaveLength(2);
    expect(container.querySelectorAll("i.bi.bi-search")).toHaveLength(2);
    expect(container.querySelectorAll(".web-search-sources__step-marker--search")).toHaveLength(2);
    expect(container.querySelector(".web-search-sources__summary-detail")).toHaveTextContent(
      "Web検索2回",
    );
    expect(container.querySelector(".web-search-sources__step-query")).toHaveTextContent("検索語1");
    expect(container.querySelector(".web-search-sources__step-chip")).toHaveTextContent(
      "example.com",
    );
  });

  // 1回目の検索も追加検索も、それぞれ独立して出典を開けること。
  // The first search and the follow-up search each open their own source list.
  it("opens the sources of the first and the follow-up search independently", () => {
    const { container } = render(<BotMessageHtml text={ANSWER_STEPS_HTML} />);

    const stepDetails = container.querySelectorAll<HTMLDetailsElement>(
      "details.web-search-sources__step-details",
    );
    expect(stepDetails).toHaveLength(2);
    stepDetails.forEach((details) => {
      expect(details.querySelector(".web-search-sources__links")).not.toBeNull();
      expect(details.open).toBe(false);
    });

    stepDetails[1].querySelector<HTMLElement>(".web-search-sources__step-summary")?.click();

    expect(stepDetails[1].open).toBe(true);
    expect(stepDetails[0].open).toBe(false);
  });

  // リンクをたどって到達したページの深さ表示が、サニタイズ後も残ること。
  // The depth marker on a page reached by following links survives sanitization.
  it("keeps the depth marker of a followed page", () => {
    const { container } = render(<BotMessageHtml text={DEEP_LINK_STEP_HTML} />);

    const step = container.querySelector(".web-search-sources__step--follow");
    const followed = container.querySelector(".web-search-sources__item--followed");

    expect(step).not.toBeNull();
    expect(step?.querySelector("i.bi.bi-signpost-split")).not.toBeNull();
    expect(step?.querySelector(".web-search-sources__step-badge")).toHaveTextContent(
      "1件・最大2階層",
    );
    expect(followed?.querySelector(".web-search-sources__depth")).toHaveTextContent(
      "root.example から2階層先",
    );
  });
});

const DEEP_LINK_STEP_HTML = [
  '<details class="web-search-sources web-search-sources--trace">',
  '<summary class="web-search-sources__summary">',
  '<span class="web-search-sources__label">回答までのステップ</span>',
  "</summary>",
  '<div class="web-search-sources__list">',
  '<ol class="web-search-sources__steps">',
  '<li class="web-search-sources__step web-search-sources__step--follow web-search-sources__step--has-sources">',
  '<span class="web-search-sources__step-marker web-search-sources__step-marker--follow">',
  '<i class="bi bi-signpost-split"></i>',
  "</span>",
  '<details class="web-search-sources__step-details">',
  '<summary class="web-search-sources__step-summary">',
  '<span class="web-search-sources__step-main">',
  '<span class="web-search-sources__step-head">',
  '<span class="web-search-sources__step-title">リンクをたどって深掘り</span>',
  '<span class="web-search-sources__step-badge">1件・最大2階層</span>',
  "</span>",
  "</span>",
  "</summary>",
  '<div class="web-search-sources__step-body">',
  '<ul class="web-search-sources__links">',
  '<li class="web-search-sources__item web-search-sources__item--followed">',
  '<a class="web-search-sources__link" href="https://child.example/a" target="_blank">',
  '<span class="web-search-sources__content">',
  '<span class="web-search-sources__title">たどった記事</span>',
  '<span class="web-search-sources__hostname">child.example</span>',
  '<span class="web-search-sources__depth">root.example から2階層先</span>',
  "</span>",
  "</a></li></ul></div></details></li>",
  "</ol>",
  "</div>",
  "</details>",
].join("\n");

describe("BotMessageHtml streaming reveal", () => {
  it("fades in the words of the part that is still generating", () => {
    const { container } = render(<BotMessageHtml text="流れるように出力します" streaming />);

    expect(container.querySelectorAll("span.streaming-word").length).toBeGreaterThan(0);
    expect(container.textContent).toContain("流れるように出力します");
  });

  it("leaves a finished message as plain markup", () => {
    const { container } = render(<BotMessageHtml text="出力が完了しました" />);

    expect(container.querySelector("span.streaming-word")).toBeNull();
  });

  it("drops the reveal markup once streaming ends", () => {
    const { container, rerender } = render(<BotMessageHtml text="出力の途中です" streaming />);
    expect(container.querySelectorAll("span.streaming-word").length).toBeGreaterThan(0);

    rerender(<BotMessageHtml text="出力の途中です" />);

    expect(container.querySelector("span.streaming-word")).toBeNull();
    expect(container.textContent).toContain("出力の途中です");
  });
});

const CITATION_HTML = [
  '<a class="web-search-citation" href="https://example.com" target="_blank" title="Example">',
  '<span class="web-search-citation__icon">',
  '<span class="web-search-citation__fallback">E</span>',
  '<img class="web-search-citation__favicon" src="https://example.com/favicon.ico" alt="" referrerpolicy="no-referrer">',
  "</span>",
  '<span class="web-search-citation__label">Example</span>',
  "</a>",
].join("");

const TRACE_HTML = [
  '<details class="web-search-sources">',
  '<summary class="web-search-sources__summary">',
  '<span class="web-search-sources__label">参照したWebサイト</span>',
  "</summary>",
  '<ul class="web-search-sources__list">',
  '<li class="web-search-sources__item">',
  '<a class="web-search-sources__link" href="https://source.example/report" target="_blank">レポート</a>',
  "</li>",
  "</ul>",
  "</details>",
].join("\n");

// 生成中は毎フレーム再描画されるため、出典UIのDOMが作り直されないことを守る。
// 作り直されると favicon が読み込み直しで点滅し、押した瞬間に要素が消えるので
// クリックが届かなくなる。
// Messages re-render every frame while generating, so the source UI DOM must
// survive untouched: rebuilding it makes the favicon blink through its reload
// and drops clicks because the pressed element disappears mid-interaction.
describe("BotMessageHtml streaming stability", () => {
  beforeAll(() => {
    // jsdom には scrollIntoView が無いため、開閉後の表示位置調整を無効化する。
    // jsdom has no scrollIntoView, so the post-toggle reveal is stubbed out.
    if (typeof Element.prototype.scrollIntoView !== "function") {
      Element.prototype.scrollIntoView = () => {};
    }
  });

  it("keeps the citation pill and its favicon state across streaming frames", () => {
    const { container, rerender } = render(
      <BotMessageHtml text={`出典は${CITATION_HTML}です。生成は`} streaming />,
    );
    const pill = container.querySelector("a.web-search-citation");
    const favicon = container.querySelector<HTMLImageElement>(".web-search-citation__favicon");
    favicon?.dispatchEvent(new Event("error"));
    expect(container.querySelector(".web-search-citation__icon")).toHaveClass(
      "web-search-citation__icon--fallback",
    );

    rerender(<BotMessageHtml text={`出典は${CITATION_HTML}です。生成はまだ続きます`} streaming />);

    expect(container.querySelector("a.web-search-citation")).toBe(pill);
    expect(container.querySelector(".web-search-citation__favicon")).toBe(favicon);
    expect(container.querySelector(".web-search-citation__icon")).toHaveClass(
      "web-search-citation__icon--fallback",
    );
    expect(container.textContent).toContain("まだ続きます");
  });

  it("keeps a source list the reader opened while generation continues", () => {
    const { container, rerender } = render(
      <BotMessageHtml text={`${TRACE_HTML}\n\n回答の本文です。`} streaming />,
    );
    const details = container.querySelector<HTMLDetailsElement>("details.web-search-sources");
    const summary = container.querySelector<HTMLElement>(".web-search-sources__summary");
    if (!details || !summary) throw new Error("the web search trace was not rendered");

    summary.click();
    expect(details.open).toBe(true);

    rerender(<BotMessageHtml text={`${TRACE_HTML}\n\n回答の本文です。まだ続きます`} streaming />);

    expect(container.querySelector("details.web-search-sources")).toBe(details);
    expect(details.open).toBe(true);
    expect(container.textContent).toContain("まだ続きます");
  });

  it("never rebuilds the pill while the answer grows one character at a time", () => {
    const head = `最新の情報は${CITATION_HTML}にあります。`;
    const tail = "この本文は一文字ずつ伸びます。**強調**や`コード`が確定してもpillは作り直されません。";
    const { container, rerender } = render(<BotMessageHtml text={head} streaming />);
    const pill = container.querySelector("a.web-search-citation");
    const favicon = container.querySelector(".web-search-citation__favicon");
    let rebuilds = 0;

    for (let length = 1; length <= tail.length; length += 1) {
      rerender(<BotMessageHtml text={head + tail.slice(0, length)} streaming />);
      if (container.querySelector("a.web-search-citation") !== pill) rebuilds += 1;
      if (container.querySelector(".web-search-citation__favicon") !== favicon) rebuilds += 1;
    }

    // 毎フレーム作り直されると、faviconの読み込み直しが点滅として見える。
    // Rebuilding on every frame is what showed up as a blinking favicon.
    expect(rebuilds).toBe(0);
    expect(container.textContent).toContain("作り直されません。");
  });

  it("still closes an opened source list on a second click during generation", () => {
    const { container, rerender } = render(
      <BotMessageHtml text={`${TRACE_HTML}\n\n回答の本文です。`} streaming />,
    );
    const details = container.querySelector<HTMLDetailsElement>("details.web-search-sources");
    const summary = container.querySelector<HTMLElement>(".web-search-sources__summary");
    if (!details || !summary) throw new Error("the web search trace was not rendered");

    summary.click();
    rerender(<BotMessageHtml text={`${TRACE_HTML}\n\n回答の本文です。続き`} streaming />);
    summary.click();

    expect(details.open).toBe(false);
  });
});
