import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MemoHistoryPanel } from "../components/memo/MemoHistoryPanel";
import { MemoMarkdown } from "../components/memo/MemoMarkdown";
import { MemoPageContextProvider } from "../contexts/memo_page/memo_page_context";
import type { MemoSummary } from "../lib/memo/types";
import { createMemoPageControllerStub } from "./memo_page_context_harness";

describe("search highlighting on cards", () => {
  it("marks the title and the excerpt, ignoring case and the hiragana/katakana difference", () => {
    const memo: MemoSummary = { id: 1, title: "Passport メモ", excerpt: "持ち物: パスポート と 充電器" };
    const controller = createMemoPageControllerStub({
      query: "ぱすぽーと passport",
      memos: [memo],
      otherMemos: [memo],
      totalMemoCount: 1,
    });
    render(
      <MemoPageContextProvider controller={controller}>
        <MemoHistoryPanel />
      </MemoPageContextProvider>,
    );

    const marks = Array.from(document.querySelectorAll("mark.memo-search-hit")).map((mark) => mark.textContent);
    expect(marks).toEqual(["Passport", "パスポート"]);
  });

  it("does not mark the placeholder shown for an untitled memo", () => {
    const memo: MemoSummary = { id: 2, title: "", excerpt: "本文" };
    const controller = createMemoPageControllerStub({ query: "メモ", memos: [memo], otherMemos: [memo], totalMemoCount: 1 });
    render(
      <MemoPageContextProvider controller={controller}>
        <MemoHistoryPanel />
      </MemoPageContextProvider>,
    );
    expect(document.querySelector("mark")).toBeNull();
  });
});

describe("MemoMarkdown highlight", () => {
  const text = "- [ ] パスポート\n- [x] 充電器\n\n[パスポートの申請](https://example.com/passport)";

  it("leaves the markup, link hrefs and checkboxes intact and changes only the text nodes", () => {
    const { container: plain } = render(<MemoMarkdown text={text} />);
    const { container: marked } = render(<MemoMarkdown text={text} highlight="ぱすぽーと" />);

    expect(marked.querySelectorAll("mark.memo-search-hit")).toHaveLength(2);
    // 強調しても本文の文字列、リンク先、チェック欄の数と状態は変わらない
    // Text, link targets and the number and state of checkboxes do not change
    expect(marked.textContent).toBe(plain.textContent);
    expect(marked.querySelector("a")?.getAttribute("href")).toBe("https://example.com/passport");
    expect(marked.querySelector("a mark")?.textContent).toBe("パスポート");
    const states = (root: HTMLElement) => Array.from(root.querySelectorAll<HTMLInputElement>("input[type=checkbox]")).map((box) => box.checked);
    expect(states(marked)).toEqual(states(plain));
    expect(states(marked)).toEqual([false, true]);
  });

  it("does not change the rendering when no highlight is given", () => {
    const { container } = render(<MemoMarkdown text={text} highlight="" />);
    expect(container.querySelector("mark")).toBeNull();
  });

  it("passes the row text of a checkbox to onToggleTask unchanged by the marks", () => {
    const onToggleTask = vi.fn(() => true);
    const { container } = render(<MemoMarkdown text={text} highlight="パスポート" onToggleTask={onToggleTask} />);

    fireEvent.click(container.querySelector("input[type=checkbox]") as HTMLInputElement);

    expect(onToggleTask).toHaveBeenCalledTimes(1);
    const [index, rendered] = onToggleTask.mock.calls[0] as unknown as [number, { label: string; checked: boolean }[]];
    expect(index).toBe(0);
    expect(rendered[0].label).toBe("パスポート");
    expect(rendered[1].label).toBe("充電器");
    expect(container.querySelector("input[type=checkbox]")?.getAttribute("aria-label")).toBe("パスポート");
  });
});
