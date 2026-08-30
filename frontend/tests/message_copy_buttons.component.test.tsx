import { render } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { BotMessageHtml } from "../components/chat_page/bot_message_html";

// 本文中のコピーボタンは document 委譲で動く。以前はその初期化が initChatUi() の中だけに
// あり、その initChatUi() をどこも呼んでいなかったため、共有ページ以外ではコードブロックの
// コピーボタンが無反応だった。ボタンを描く BotMessageHtml が自分で用意することを固定する。
// The in-message copy buttons run on a delegated document listener. Its setup used to live
// only inside initChatUi(), which nothing ever called, so outside the shared page a code
// block's copy button did nothing. Pin that BotMessageHtml — which renders the buttons —
// sets the listener up itself.
beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

describe("BotMessageHtml wires the in-message copy buttons", () => {
  beforeEach(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  it("makes a code block copy button work without any page-level setup", async () => {
    const { container } = render(<BotMessageHtml text={"```python\nprint(1)\n```"} />);
    const button = container.querySelector<HTMLButtonElement>(".code-block-copy-btn");
    if (!button) throw new Error("the code block copy button was not rendered");

    button.click();

    await vi.waitFor(() => {
      expect(button.querySelector("i")).toHaveClass("bi-check-lg");
    });
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("print(1)");
    // コピーボタンはアイコンのみ。ラベル文字は持たない。
    // The copy button is icon-only and carries no text label.
    expect(button.querySelector("span")).toBeNull();
  });

  it("makes a copy card button work without any page-level setup", async () => {
    const { container } = render(<BotMessageHtml text={"```chatcore-copy 返信案\nご連絡ありがとうございます。\n```"} />);
    const button = container.querySelector<HTMLButtonElement>(".copy-block-copy-btn");
    if (!button) throw new Error("the copy card button was not rendered");

    button.click();

    await vi.waitFor(() => {
      expect(button.querySelector("i")).toHaveClass("bi-check-lg");
    });
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("ご連絡ありがとうございます。");
  });

  // 委譲は1つだけ張る。メッセージごとにリスナーが積み上がると、1クリックで同じコピーが
  // 何度も走ってしまう。
  // Only one delegation is attached. A listener per message would run the same copy
  // several times for a single click.
  it("copies once per click no matter how many messages are on screen", async () => {
    render(<BotMessageHtml text={"```chatcore-copy\n案1\n```"} />);
    render(<BotMessageHtml text={"```python\nprint(2)\n```"} />);
    const { container } = render(<BotMessageHtml text={"```chatcore-copy\n案3\n```"} />);
    const button = container.querySelector<HTMLButtonElement>(".copy-block-copy-btn");
    if (!button) throw new Error("the copy card button was not rendered");

    button.click();

    await vi.waitFor(() => {
      expect(button.querySelector("i")).toHaveClass("bi-check-lg");
    });
    expect(navigator.clipboard.writeText).toHaveBeenCalledOnce();
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("案3");
  });
});
