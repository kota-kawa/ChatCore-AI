import { render } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { BotMessageHtml } from "../components/chat_page/bot_message_html";
import { initMessageCopyButtons } from "../scripts/chat/message_copy_buttons";

const EMAIL_BODY = ["開発チーム各位", "", "お疲れさまです。4月25日に説明会を実施します。"].join("\n");
const COPY_FENCE = ["```chatcore-copy メール本文", EMAIL_BODY, "```"].join("\n");

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn();
  // 委譲は document に一度だけ張られるので、テストファイル単位で先に初期化しておく。
  // The delegation attaches to document once, so initialise it up front for the file.
  initMessageCopyButtons();
});

describe("copy card rendering", () => {
  it("renders a copy fence as a card whose text survives sanitization", () => {
    const { container } = render(<BotMessageHtml text={COPY_FENCE} />);
    const card = container.querySelector(".copy-block-container");

    expect(card).not.toBeNull();
    expect(card?.querySelector(".copy-block-label")).toHaveTextContent("メール本文");
    expect(card?.querySelector(".copy-block-copy-btn")).not.toBeNull();
    // DOMPurify と class ホワイトリストを通過しても、枠のクラスが残っていること。
    // The card classes must survive DOMPurify and the class whitelist.
    expect(card?.querySelector(".copy-block-text")?.textContent).toBe(EMAIL_BODY);
  });

  it("keeps the card out of the code block treatment", () => {
    const { container } = render(<BotMessageHtml text={COPY_FENCE} />);

    expect(container.querySelector(".code-block-container")).toBeNull();
    expect(container.querySelector(".hljs")).toBeNull();
    expect(container.textContent).not.toContain("chatcore-copy");
  });
});

describe("copy card clipboard behaviour", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("copies exactly the text shown in the card", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });

    const { container } = render(<BotMessageHtml text={COPY_FENCE} />);
    const button = container.querySelector<HTMLButtonElement>(".copy-block-copy-btn");
    const shownText = container.querySelector(".copy-block-text")?.textContent;
    if (!button) throw new Error("the copy button was not rendered");

    button.click();
    await vi.waitFor(() => {
      expect(button.querySelector("i")).toHaveClass("bi-check-lg");
    });

    expect(writeText).toHaveBeenCalledOnce();
    expect(writeText).toHaveBeenCalledWith(shownText);

    await vi.advanceTimersByTimeAsync(2000);
    expect(button.querySelector("i")).toHaveClass("bi-clipboard");
  });

  it("shows the failure icon when the clipboard refuses", async () => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
    });
    Object.defineProperty(document, "execCommand", { configurable: true, value: vi.fn(() => false) });
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

    const { container } = render(<BotMessageHtml text={COPY_FENCE} />);
    const button = container.querySelector<HTMLButtonElement>(".copy-block-copy-btn");
    if (!button) throw new Error("the copy button was not rendered");

    button.click();
    await vi.waitFor(() => {
      expect(button.querySelector("i")).toHaveClass("bi-x-lg");
    });

    await vi.advanceTimersByTimeAsync(2000);
    expect(button.querySelector("i")).toHaveClass("bi-clipboard");
    consoleError.mockRestore();
  });
});

describe("copy card while the answer streams", () => {
  it("shows the card before the closing fence arrives without reflowing the body", () => {
    // key:value に見える行は、フェンス外なら箇条書きへ整形される。生成中の
    // メール本文がその整形に掛かると、閉じフェンスが届いた瞬間に組み替わる。
    // Lines that look like key:value are turned into bullets outside a fence. If a
    // half-written email were reshaped that way, it would jump when the fence closes.
    const partial = ["本文です。", "", "```chatcore-copy メール本文", "件名: 説明会のご案内", "日時: 4月25日"].join("\n");
    const { container } = render(<BotMessageHtml text={partial} streaming />);

    expect(container.querySelector(".copy-block-container")).not.toBeNull();
    expect(container.querySelector(".copy-block-text")?.textContent).toBe("件名: 説明会のご案内\n日時: 4月25日");
    expect(container.querySelector("li")).toBeNull();
  });

  it("reuses the card and button nodes as the body grows", () => {
    const growing = "```chatcore-copy メール本文\n開発チーム各位\n\nお疲れさまです。";
    const tail = "4月25日に説明会を実施します。";
    const { container, rerender } = render(<BotMessageHtml text={growing} streaming />);
    const button = container.querySelector(".copy-block-copy-btn");
    const card = container.querySelector(".copy-block-container");

    // 1文字ずつ追記して、毎フレームのDOMパッチで枠とボタンが作り直されないことを確認する。
    // 作り直されると pointerdown と click の間にノードが消え、生成中のクリックが届かない。
    // Append one character at a time and confirm the per-frame patch reuses both nodes.
    // Recreating them would drop the node between pointerdown and click, swallowing it.
    tail.split("").forEach((_character, index) => {
      rerender(<BotMessageHtml text={growing + tail.slice(0, index + 1)} streaming />);
    });

    expect(container.querySelector(".copy-block-copy-btn")).toBe(button);
    expect(container.querySelector(".copy-block-container")).toBe(card);
    expect(container.querySelector(".copy-block-text")?.textContent).toContain(tail);
  });

  it("keeps the copy feedback visible when the next chunk arrives", async () => {
    // 差分パッチはアイコンの class を目標HTMLへ揃えるため、ボタンを据え置き対象に
    // していないと「コピーしました」の表示が次のチャンクで消える。
    // The patch aligns the icon class with the target HTML, so without the button being
    // a preserved subtree the "copied" feedback disappears on the next chunk.
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });

    const growing = "```chatcore-copy メール本文\n開発チーム各位\n\nお疲れさまです。";
    const { container, rerender } = render(<BotMessageHtml text={growing} streaming />);
    const button = container.querySelector<HTMLButtonElement>(".copy-block-copy-btn");
    if (!button) throw new Error("the copy button was not rendered");

    button.click();
    await vi.waitFor(() => {
      expect(button.querySelector("i")).toHaveClass("bi-check-lg");
    });

    rerender(<BotMessageHtml text={`${growing}4月25日に説明会を実施します。`} streaming />);

    expect(container.querySelector(".copy-block-copy-btn")?.querySelector("i")).toHaveClass("bi-check-lg");
  });

  it("leaves the card body out of the word reveal animation", () => {
    const { container } = render(<BotMessageHtml text={`説明文です。\n\n${COPY_FENCE}`} streaming />);
    const card = container.querySelector(".copy-block-container");

    expect(card?.querySelector(".streaming-word")).toBeNull();
    expect(card?.querySelector(".copy-block-text")?.textContent).toBe(EMAIL_BODY);
  });
});
