import { describe, expect, it } from "vitest";

import { isLastActionableAssistantMessage } from "../components/chat_page/chat_message_list";
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
