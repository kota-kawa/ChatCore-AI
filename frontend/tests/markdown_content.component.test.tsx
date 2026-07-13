import { render, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import MarkdownContent from "../components/MarkdownContent";

describe("MarkdownContent", () => {
  it("renders sanitized markdown into the DOM after mount", async () => {
    const { container } = render(
      <MarkdownContent text={"# 見出し\n\n本文テキスト"} className="md-content" />
    );

    const host = container.querySelector(".md-content");
    expect(host).not.toBeNull();

    // マウント後に本文が挿入されることを検証する（SSR空表示バグの回帰防止）。
    // Verify the body is injected after mount (regression guard for the empty-SSR bug).
    await waitFor(() => {
      expect(host?.querySelector("h1")?.textContent).toBe("見出し");
      expect(host?.textContent).toContain("本文テキスト");
    });
  });

  it("renders nothing for empty text", async () => {
    const { container } = render(<MarkdownContent text="" className="md-content" />);
    const host = container.querySelector(".md-content");

    await waitFor(() => {
      expect(host?.innerHTML).toBe("");
    });
  });

  it("renders the provided ssrHtml as-is on the initial render", () => {
    const { container } = render(
      <MarkdownContent
        text={"# 見出し"}
        ssrHtml={"<h1>サーバー描画済み</h1>"}
        className="md-content"
      />
    );

    // ssrHtml指定時はマウント前から本文が描画される（SSR/クローラ向け出力と一致）。
    // With ssrHtml, the body is rendered before mount (matching the SSR/crawler-facing output).
    const host = container.querySelector(".md-content");
    expect(host?.querySelector("h1")?.textContent).toBe("サーバー描画済み");
  });
});
