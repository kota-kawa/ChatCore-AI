import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useChatToolApprovals } from "../hooks/chat_page/use_chat_tool_approvals";
import { normalizeToolApproval } from "../lib/chat_page/api_contract";
import { replaceToolApprovalInMessages } from "../lib/chat_page/tool_approvals";
import type { UiChatMessage } from "../lib/chat_page/types";
import type { ToolApprovalApi } from "../types/generated/api_schemas";

const { decideToolApprovalMock, showToastMock } = vi.hoisted(() => ({
  decideToolApprovalMock: vi.fn(),
  showToastMock: vi.fn(),
}));

vi.mock("../lib/chat_page/tool_approval_api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../lib/chat_page/tool_approval_api")>();
  return { ...original, decideToolApproval: decideToolApprovalMock };
});
vi.mock("../scripts/core/toast", () => ({ showToast: showToastMock }));

function approval(overrides: Record<string, unknown> = {}): ToolApprovalApi {
  const normalized = normalizeToolApproval({
    id: "a1",
    tool: "memo_append",
    family: "memo",
    status: "pending",
    always_allowed: true,
    preview: { kind: "memo_append", memo_id: 4, memo_title: "読書メモ", text: "要点" },
    expires_at: "2999-01-01T00:00:00Z",
    ...overrides,
  });
  if (!normalized) throw new Error("fixture must be a valid approval");
  return normalized;
}

function conversation(approvals: ToolApprovalApi[]): UiChatMessage[] {
  return [
    { id: "u1", sender: "user", text: "読書メモに追記して" },
    {
      id: "m1",
      sender: "assistant",
      text: "追記案です。",
      parts: [
        { type: "text", text: "追記案です。" },
        ...approvals.map((entry) => ({ type: "tool_approval" as const, approval: entry })),
      ],
    },
  ];
}

// 実画面と同じく、applyToolApproval でメッセージを差し替えて再描画する小さな器
// A tiny harness that, like the real screen, re-renders with the messages applyToolApproval produced
function renderApprovals(initialMessages: UiChatMessage[], isGenerating = false) {
  let messages = initialMessages;
  const sendMessage = vi.fn();
  const applyToolApproval = vi.fn((next: ToolApprovalApi) => {
    messages = replaceToolApprovalInMessages(messages, next);
  });
  const hook = renderHook(
    (props: { messages: UiChatMessage[] }) =>
      useChatToolApprovals({ messages: props.messages, isGenerating, applyToolApproval, sendMessage }),
    { initialProps: { messages } },
  );
  const decide = async (id: string, decision: "approve_once" | "approve_always" | "deny") => {
    await act(async () => {
      await hook.result.current.handleToolApprovalDecide(id, decision);
    });
    hook.rerender({ messages });
  };
  return { decide, sendMessage, applyToolApproval, getMessages: () => messages };
}

beforeEach(() => {
  decideToolApprovalMock.mockReset();
  showToastMock.mockReset();
});

describe("useChatToolApprovals", () => {
  it("applies the returned card and continues once the only card succeeded", async () => {
    decideToolApprovalMock.mockResolvedValue(approval({ status: "succeeded", decision: "once", result: { target_id: 4 } }));
    const { decide, sendMessage, applyToolApproval } = renderApprovals(conversation([approval()]));

    await decide("a1", "approve_once");

    expect(decideToolApprovalMock).toHaveBeenCalledWith("a1", "approve_once", "承認を処理できませんでした。");
    expect(applyToolApproval).toHaveBeenCalledTimes(1);
    expect(sendMessage).toHaveBeenCalledTimes(1);
    expect(sendMessage).toHaveBeenCalledWith("承認した操作が実行されました。結果を踏まえて続けてください。");
  });

  it("waits for the other card before continuing", async () => {
    decideToolApprovalMock.mockResolvedValueOnce(approval({ status: "succeeded", decision: "once" }));
    const { decide, sendMessage } = renderApprovals(conversation([approval(), approval({ id: "a2" })]));

    await decide("a1", "approve_once");
    expect(sendMessage).not.toHaveBeenCalled();

    decideToolApprovalMock.mockResolvedValueOnce(approval({ id: "a2", status: "denied", decision: "deny" }));
    await decide("a2", "deny");
    expect(sendMessage).toHaveBeenCalledTimes(1);
  });

  it("does not continue when every card was denied", async () => {
    decideToolApprovalMock.mockResolvedValue(approval({ status: "denied", decision: "deny" }));
    const { decide, sendMessage } = renderApprovals(conversation([approval()]));

    await decide("a1", "deny");

    expect(sendMessage).not.toHaveBeenCalled();
  });

  it("does not continue while a reply is generating", async () => {
    decideToolApprovalMock.mockResolvedValue(approval({ status: "succeeded", decision: "once" }));
    const { decide, sendMessage } = renderApprovals(conversation([approval()]), true);

    await decide("a1", "approve_once");

    expect(sendMessage).not.toHaveBeenCalled();
  });

  it("marks the card expired when the server says it expired, and tells the user", async () => {
    const { ToolApprovalDecisionError } = await import("../lib/chat_page/tool_approval_api");
    decideToolApprovalMock.mockRejectedValue(new ToolApprovalDecisionError("承認の期限が切れています。", "approval_expired", 409));
    const { decide, sendMessage, getMessages } = renderApprovals(conversation([approval()]));

    await decide("a1", "approve_once");

    const card = getMessages()[1].parts?.find((part) => part.type === "tool_approval");
    expect(card?.type === "tool_approval" ? card.approval.status : null).toBe("expired");
    expect(showToastMock).toHaveBeenCalledWith("承認の期限が切れています。", { variant: "error" });
    expect(sendMessage).not.toHaveBeenCalled();
  });

  it("keeps the card pending on other failures so the user can try again", async () => {
    const { ToolApprovalDecisionError } = await import("../lib/chat_page/tool_approval_api");
    decideToolApprovalMock.mockRejectedValue(new ToolApprovalDecisionError("しばらく待ってください。", "rate_limited", 429));
    const { decide, applyToolApproval } = renderApprovals(conversation([approval()]));

    await decide("a1", "approve_once");

    expect(applyToolApproval).not.toHaveBeenCalled();
    expect(showToastMock).toHaveBeenCalledWith("しばらく待ってください。", { variant: "error" });
  });
});
