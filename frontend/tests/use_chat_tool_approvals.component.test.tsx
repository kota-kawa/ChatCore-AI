import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useChatToolApprovals } from "../hooks/chat_page/use_chat_tool_approvals";
import { normalizeToolApproval } from "../lib/chat_page/api_contract";
import { replaceToolApprovalInMessages } from "../lib/chat_page/tool_approvals";
import type { UiChatMessage } from "../lib/chat_page/types";
import type { ToolApprovalApi } from "../types/generated/api_schemas";

const { decideToolApprovalMock, showToastMock, routerReplaceMock, setLocaleMock } = vi.hoisted(() => ({
  decideToolApprovalMock: vi.fn(),
  showToastMock: vi.fn(),
  routerReplaceMock: vi.fn(),
  setLocaleMock: vi.fn(),
}));

vi.mock("../lib/chat_page/tool_approval_api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../lib/chat_page/tool_approval_api")>();
  return { ...original, decideToolApproval: decideToolApprovalMock };
});
vi.mock("../contexts/locale_context", () => ({
  useTranslation: () => ({
    setLocale: setLocaleMock,
    t: (key: string) => {
      if (key === "chat.toolApproval.decisionFailed") return "承認を処理できませんでした。";
      if (key === "chat.toolApproval.continuePrompt") return "承認した操作が実行されました。結果を踏まえて続けてください。";
      return key;
    },
  }),
}));
vi.mock("next/router", () => ({
  useRouter: () => ({ asPath: "/chat/room?x=1", replace: routerReplaceMock }),
}));
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

function profileApproval(overrides: Partial<ToolApprovalApi> = {}): ToolApprovalApi {
  return {
    id: "profile-a1",
    tool: "profile_settings_update",
    family: "profile",
    status: "pending",
    decision: null,
    always_allowed: false,
    preview: {
      kind: "profile_settings_update",
      display_name: null,
      bio: null,
      llm_profile_context: null,
      preferred_locale: "en",
      theme: "dark",
    },
    warnings: [],
    expires_at: "2999-01-01T00:00:00Z",
    result: null,
    readonly: false,
    ...overrides,
  };
}

function decided(entry: ToolApprovalApi, currentPreferredLocale: "ja" | "en" | null = null) {
  return { approval: entry, currentPreferredLocale };
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
  const decide = async (
    id: string,
    decision: "approve_once" | "approve_always" | "deny",
    acknowledgeWarnings = false,
  ) => {
    await act(async () => {
      await hook.result.current.handleToolApprovalDecide(id, decision, acknowledgeWarnings);
    });
    hook.rerender({ messages });
  };
  return { decide, sendMessage, applyToolApproval, getMessages: () => messages };
}

beforeEach(() => {
  decideToolApprovalMock.mockReset();
  showToastMock.mockReset();
  routerReplaceMock.mockReset().mockResolvedValue(true);
  setLocaleMock.mockReset();
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

describe("useChatToolApprovals", () => {
  it("applies the returned card and continues once the only card succeeded", async () => {
    decideToolApprovalMock.mockResolvedValue(decided(approval({ status: "succeeded", decision: "once", result: { target_id: 4 } })));
    const { decide, sendMessage, applyToolApproval } = renderApprovals(conversation([approval()]));

    await decide("a1", "approve_once");

    expect(decideToolApprovalMock).toHaveBeenCalledWith("a1", "approve_once", "承認を処理できませんでした。");
    expect(applyToolApproval).toHaveBeenCalledTimes(1);
    expect(sendMessage).toHaveBeenCalledTimes(1);
    expect(sendMessage).toHaveBeenCalledWith("承認した操作が実行されました。結果を踏まえて続けてください。");
  });

  it("applies locale and theme preferences only after a successful profile update", async () => {
    decideToolApprovalMock.mockResolvedValue(decided(profileApproval({ status: "succeeded", decision: "once" })));
    const { decide } = renderApprovals(conversation([profileApproval()]));

    await decide("profile-a1", "approve_once");

    expect(setLocaleMock).toHaveBeenCalledWith("en");
    expect(routerReplaceMock).toHaveBeenCalledWith("/chat/room?x=1", "/chat/room?x=1", { locale: "en" });
    expect(window.localStorage.getItem("chatcore-theme")).toBe("dark");
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  });

  it("uses the server's persisted locale instead of a stale card preview", async () => {
    decideToolApprovalMock.mockResolvedValue(decided(profileApproval({ status: "succeeded", decision: "once" }), "ja"));
    const { decide } = renderApprovals(conversation([profileApproval()]));

    await decide("profile-a1", "approve_once");

    expect(setLocaleMock).toHaveBeenCalledWith("ja");
    expect(setLocaleMock).not.toHaveBeenCalledWith("en");
    expect(routerReplaceMock).toHaveBeenCalledWith("/chat/room?x=1", "/chat/room?x=1", { locale: "ja" });
  });

  it("applies the theme and persisted locale from a succeeded profile card on a 409 conflict", async () => {
    // 成功応答を受け取れずに再送した場合も、確定済みカードのテーマを反映し、言語は現在値に合わせる
    // A resend after a lost success response still applies the settled theme and follows the persisted locale
    const { ToolApprovalDecisionError } = await import("../lib/chat_page/tool_approval_api");
    const settled = profileApproval({ status: "succeeded", decision: "once" });
    decideToolApprovalMock.mockRejectedValue(
      new ToolApprovalDecisionError("既に決定されています。", "approval_already_decided", 409, settled, "ja"),
    );
    const { decide, getMessages } = renderApprovals(conversation([profileApproval()]));

    await decide("profile-a1", "approve_once");

    expect(setLocaleMock).toHaveBeenCalledWith("ja");
    expect(setLocaleMock).not.toHaveBeenCalledWith("en");
    expect(window.localStorage.getItem("chatcore-theme")).toBe("dark");
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    const card = getMessages()[1].parts?.find((part) => part.type === "tool_approval");
    expect(card?.type === "tool_approval" ? card.approval.status : null).toBe("succeeded");
  });

  it("does not fall back to a conflict card's preview locale when the server sent none", async () => {
    const { ToolApprovalDecisionError } = await import("../lib/chat_page/tool_approval_api");
    const settled = profileApproval({ status: "succeeded", decision: "once" });
    decideToolApprovalMock.mockRejectedValue(
      new ToolApprovalDecisionError("既に決定されています。", "approval_already_decided", 409, settled),
    );
    const { decide } = renderApprovals(conversation([profileApproval()]));

    await decide("profile-a1", "approve_once");

    expect(setLocaleMock).not.toHaveBeenCalled();
    expect(routerReplaceMock).not.toHaveBeenCalled();
    expect(window.localStorage.getItem("chatcore-theme")).toBe("dark");
  });

  it.each(["denied", "failed", "pending"] as const)("does not apply profile preferences when the returned card is %s", async (status) => {
    decideToolApprovalMock.mockResolvedValue(decided(profileApproval({ status })));
    const { decide } = renderApprovals(conversation([profileApproval()]));

    await decide("profile-a1", "approve_once");

    expect(setLocaleMock).not.toHaveBeenCalled();
    expect(routerReplaceMock).not.toHaveBeenCalled();
    expect(window.localStorage.getItem("chatcore-theme")).toBeNull();
    expect(document.documentElement).not.toHaveAttribute("data-theme");
  });

  it("does not apply profile preferences when the returned preview kind does not match", async () => {
    decideToolApprovalMock.mockResolvedValue(decided(profileApproval({
      status: "succeeded",
      preview: { kind: "memo_append", memo_id: 4, memo_title: "読書メモ", text: "要点", separator: "" },
    })));
    const { decide } = renderApprovals(conversation([profileApproval()]));

    await decide("profile-a1", "approve_once");

    expect(setLocaleMock).not.toHaveBeenCalled();
    expect(routerReplaceMock).not.toHaveBeenCalled();
    expect(window.localStorage.getItem("chatcore-theme")).toBeNull();
    expect(document.documentElement).not.toHaveAttribute("data-theme");
  });

  it("forwards the warning acknowledgment to the decision API", async () => {
    decideToolApprovalMock.mockResolvedValue(decided(approval({ status: "succeeded", decision: "once", result: { target_id: 4 } })));
    const { decide } = renderApprovals(conversation([approval()]));

    await decide("a1", "approve_once", true);

    expect(decideToolApprovalMock).toHaveBeenCalledWith(
      "a1",
      "approve_once",
      "承認を処理できませんでした。",
      undefined,
      true,
    );
  });

  it("waits for the other card before continuing", async () => {
    decideToolApprovalMock.mockResolvedValueOnce(decided(approval({ status: "succeeded", decision: "once" })));
    const { decide, sendMessage } = renderApprovals(conversation([approval(), approval({ id: "a2" })]));

    await decide("a1", "approve_once");
    expect(sendMessage).not.toHaveBeenCalled();

    decideToolApprovalMock.mockResolvedValueOnce(decided(approval({ id: "a2", status: "denied", decision: "deny" })));
    await decide("a2", "deny");
    expect(sendMessage).toHaveBeenCalledTimes(1);
  });

  it("does not continue when every card was denied", async () => {
    decideToolApprovalMock.mockResolvedValue(decided(approval({ status: "denied", decision: "deny" })));
    const { decide, sendMessage } = renderApprovals(conversation([approval()]));

    await decide("a1", "deny");

    expect(sendMessage).not.toHaveBeenCalled();
  });

  it("does not continue while a reply is generating", async () => {
    decideToolApprovalMock.mockResolvedValue(decided(approval({ status: "succeeded", decision: "once" })));
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

  it("syncs the card to another tab's decision on a 409 conflict that carries it", async () => {
    const { ToolApprovalDecisionError } = await import("../lib/chat_page/tool_approval_api");
    const settledElsewhere = approval({ status: "denied", decision: "deny" });
    decideToolApprovalMock.mockRejectedValue(
      new ToolApprovalDecisionError("既に決定されています。", "approval_already_decided", 409, settledElsewhere),
    );
    const { decide, sendMessage, getMessages } = renderApprovals(conversation([approval()]));

    await decide("a1", "approve_once");

    const card = getMessages()[1].parts?.find((part) => part.type === "tool_approval");
    expect(card?.type === "tool_approval" ? card.approval.status : null).toBe("denied");
    expect(showToastMock).toHaveBeenCalledWith("既に決定されています。", { variant: "error" });
    expect(sendMessage).not.toHaveBeenCalled();
  });

  it("leaves the card as is on a 409 conflict without a card in the response", async () => {
    const { ToolApprovalDecisionError } = await import("../lib/chat_page/tool_approval_api");
    decideToolApprovalMock.mockRejectedValue(
      new ToolApprovalDecisionError("既に決定されています。", "approval_already_decided", 409),
    );
    const { decide, applyToolApproval } = renderApprovals(conversation([approval()]));

    await decide("a1", "approve_once");

    expect(applyToolApproval).not.toHaveBeenCalled();
    expect(showToastMock).toHaveBeenCalledWith("既に決定されています。", { variant: "error" });
  });
});
