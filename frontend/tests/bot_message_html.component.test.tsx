import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BotMessageHtml } from "../components/chat_page/bot_message_html";

describe("BotMessageHtml web-search citations", () => {
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
