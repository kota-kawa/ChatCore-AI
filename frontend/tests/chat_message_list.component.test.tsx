import { describe, expect, it } from "vitest";

import { hasLaterUserMessage, isLastActionableAssistantMessage } from "../components/chat_page/chat_message_list";
import type { UiChatMessage } from "../lib/chat_page/types";

function assistantMessage(overrides: Partial<UiChatMessage> = {}): UiChatMessage {
  return {
    id: "assistant-1",
    sender: "assistant",
    text: "途中までの回答",
    ...overrides,
  };
}

describe("isLastActionableAssistantMessage", () => {
  it("keeps a continuation answer actionable when an error notice follows it", () => {
    const partial = assistantMessage({ partial: true });
    const errorNotice = assistantMessage({
      id: "assistant-error-1",
      text: "回答の続きを生成できませんでした。",
      error: true,
    });
    const rows = [
      { kind: "message", message: partial },
      { kind: "message", message: errorNotice },
    ] as const;

    expect(isLastActionableAssistantMessage(rows, 0)).toBe(true);
    expect(isLastActionableAssistantMessage(rows, 1)).toBe(false);
  });

  it("does not treat an older answer as the last actionable message", () => {
    const rows = [
      { kind: "message", message: assistantMessage() },
      {
        kind: "message",
        message: assistantMessage({ id: "assistant-2", text: "新しい回答" }),
      },
    ] as const;

    expect(isLastActionableAssistantMessage(rows, 0)).toBe(false);
    expect(isLastActionableAssistantMessage(rows, 1)).toBe(true);
  });
});

describe("hasLaterUserMessage", () => {
  // 日本語: 選択ボタンの「回答済み」は、仮想リストで行が作り直されても一覧の並びから決まる。
  // English: Whether choice buttons were answered comes from the list order, so it survives the
  // virtual list re-creating the row.
  it("treats an answer followed by a user message as answered", () => {
    const rows = [
      { kind: "message", message: assistantMessage() },
      { kind: "message", message: { id: "user-1", sender: "user", text: "はい" } },
      { kind: "message", message: assistantMessage({ id: "assistant-2", text: "移行しました。" }) },
    ] as const;

    expect(hasLaterUserMessage(rows, 0)).toBe(true);
    expect(hasLaterUserMessage(rows, 2)).toBe(false);
  });

  it("does not count a following error notice as an answer", () => {
    const rows = [
      { kind: "message", message: assistantMessage() },
      { kind: "message", message: assistantMessage({ id: "assistant-error-1", error: true }) },
    ] as const;

    expect(hasLaterUserMessage(rows, 0)).toBe(false);
  });
});
