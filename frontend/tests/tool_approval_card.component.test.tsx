import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BotMessageParts } from "../components/chat_page/bot_message_parts";
import { ToolApprovalCard } from "../components/chat_page/tool_approval_card";
import { SharedChatMessageParts } from "../components/shared_chat/shared_chat_message_parts";
import { normalizeToolApproval } from "../lib/chat_page/api_contract";
import type { ToolApprovalApi } from "../types/generated/api_schemas";

const FAR_FUTURE = "2999-01-01T00:00:00Z";

function approval(overrides: Record<string, unknown> = {}): ToolApprovalApi {
  const normalized = normalizeToolApproval({
    id: "a1",
    tool: "memo_create",
    family: "memo",
    status: "pending",
    always_allowed: true,
    preview: { kind: "memo_create", title: "買い物リスト", content: "牛乳\n卵" },
    expires_at: FAR_FUTURE,
    ...overrides,
  });
  if (!normalized) throw new Error("fixture must be a valid approval");
  return normalized;
}

function memoEdit(preview: Record<string, unknown>, overrides: Record<string, unknown> = {}) {
  return approval({
    tool: "memo_edit",
    preview: { kind: "memo_edit", memo_id: 7, memo_title: "議事録", base_revision: 3, ...preview },
    ...overrides,
  });
}

afterEach(() => {
  vi.useRealTimers();
});

describe("ToolApprovalCard", () => {
  it("offers approve once / always approve / deny and sends one decision only", async () => {
    let resolveDecision: () => void = () => {};
    const onDecide = vi.fn(() => new Promise<void>((resolve) => { resolveDecision = resolve; }));
    render(<ToolApprovalCard approval={approval()} onDecide={onDecide} />);

    expect(screen.getByRole("group", { name: "メモを作成します" })).toBeInTheDocument();
    const once = screen.getByRole("button", { name: "1度だけ承認" });
    const always = screen.getByRole("button", { name: "常に承認" });
    const deny = screen.getByRole("button", { name: "拒否" });

    fireEvent.click(always);
    fireEvent.click(once);
    fireEvent.click(deny);

    expect(onDecide).toHaveBeenCalledTimes(1);
    expect(onDecide).toHaveBeenCalledWith("a1", "approve_always");
    expect(once).toBeDisabled();
    expect(always).toBeDisabled();
    expect(deny).toBeDisabled();
    expect(screen.getByText("処理しています…")).toBeInTheDocument();

    await act(async () => resolveDecision());
    expect(once).toBeEnabled();
  });

  it("shows only approve and deny for a tool that cannot be always approved", () => {
    const onDecide = vi.fn().mockResolvedValue(undefined);
    render(<ToolApprovalCard approval={approval({ always_allowed: false })} onDecide={onDecide} />);

    expect(screen.queryByRole("button", { name: "常に承認" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "1度だけ承認" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "承認" }));
    expect(onDecide).toHaveBeenCalledWith("a1", "approve_once");
    expect(screen.queryByText(/設定の「チャットの権限」/)).not.toBeInTheDocument();
  });

  it("keeps the buttons disabled while generating or once the user wrote after the reply", () => {
    const onDecide = vi.fn();
    render(<ToolApprovalCard approval={approval()} onDecide={onDecide} disabled />);

    const deny = screen.getByRole("button", { name: "拒否" });
    expect(deny).toBeDisabled();
    fireEvent.click(deny);
    expect(onDecide).not.toHaveBeenCalled();
  });

  it("treats a pending card past its deadline as expired without asking the server", () => {
    render(<ToolApprovalCard approval={approval({ expires_at: "2020-01-01T00:00:00Z" })} onDecide={vi.fn()} />);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("期限が切れたため実行していません");
  });

  it("locks the buttons when the deadline passes on an open screen", () => {
    vi.useFakeTimers({ now: Date.parse("2026-09-24T12:00:00Z") });
    render(<ToolApprovalCard approval={approval({ expires_at: "2026-09-24T12:00:10Z" })} onDecide={vi.fn()} />);
    expect(screen.getByRole("button", { name: "拒否" })).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(11_000);
    });

    expect(screen.queryByRole("button", { name: "拒否" })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("期限が切れたため実行していません");
  });

  it("shows a succeeded card with the memo link instead of the buttons", () => {
    render(
      <ToolApprovalCard
        approval={approval({ status: "succeeded", decision: "once", result: { target_id: 12, target_title: "買い物リスト" } })}
        onDecide={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("実行しました");
    const link = screen.getByRole("link", { name: /メモを開く/ });
    expect(link).toHaveAttribute("href", "/memo");
    expect(link).toHaveTextContent("買い物リスト");
  });

  it("names an automatic run as coming from always approve", () => {
    render(<ToolApprovalCard approval={approval({ status: "succeeded", decision: "auto", result: { target_id: 1 } })} />);
    expect(screen.getByRole("status")).toHaveTextContent("「常に承認」の設定で実行しました");
  });

  it("explains a failure from its error code, with a generic sentence for unknown codes", () => {
    const { rerender } = render(
      <ToolApprovalCard
        approval={approval({ status: "failed", decision: "once", result: { error_code: "target_changed" } })}
        onDecide={vi.fn()}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("実行できませんでした");
    expect(screen.getByRole("status")).toHaveTextContent("提案の後でメモが更新されたため、上書きしませんでした。");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();

    rerender(
      <ToolApprovalCard
        approval={approval({ status: "failed", decision: "once", result: { error_code: "constructor" } })}
        onDecide={vi.fn()}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("時間をおいてもう一度お試しください。");
  });

  it.each([
    ["denied", "拒否しました。何も変更していません。"],
    ["expired", "期限が切れたため実行していません"],
    ["superseded", "新しい発言があったため無効になりました"],
    ["cancelled", "回答を止めたため取り消しました"],
  ])("shows the %s state without buttons", (status, text) => {
    render(<ToolApprovalCard approval={approval({ status })} onDecide={vi.fn()} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(text);
  });

  it("lists warnings as notes rather than errors", () => {
    render(
      <ToolApprovalCard
        approval={memoEdit(
          { mode: "edits", edits: [{ before: "a", after: "b" }] },
          { warnings: ["shared_memo", "untrusted_input_in_turn"] },
        )}
        onDecide={vi.fn()}
      />,
    );

    const warnings = screen.getAllByRole("listitem");
    expect(warnings).toHaveLength(2);
    expect(warnings[0]).toHaveTextContent("このメモは共有中です。");
    expect(warnings[1]).toHaveTextContent("外部の内容");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("renders a readonly card from another view without buttons, with a note while pending", () => {
    render(<ToolApprovalCard approval={approval({ readonly: true })} onDecide={vi.fn()} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText("承認カードは共有画面では操作できません。")).toBeInTheDocument();
  });
});

describe("MemoApprovalPreview", () => {
  it("shows the new memo's title and body, folding a long body behind a disclosure", () => {
    const longBody = Array.from({ length: 12 }, (_, index) => `${index + 1}行目`).join("\n");
    render(<ToolApprovalCard approval={approval({ preview: { kind: "memo_create", title: "", content: longBody } })} />);

    expect(screen.getByText("（題名なし）")).toBeInTheDocument();
    expect(screen.getByText(/1行目[\s\S]*6行目…/)).toBeInTheDocument();
    const disclosure = screen.getByText("全文を表示").closest("details");
    expect(disclosure).not.toBeNull();
    expect(disclosure).toHaveTextContent("12行目");
  });

  it("shows the target memo and the text to append", () => {
    render(
      <ToolApprovalCard
        approval={approval({
          tool: "memo_append",
          preview: { kind: "memo_append", memo_id: 4, memo_title: "読書メモ", text: "第3章の要点", separator: "\n\n" },
        })}
      />,
    );

    expect(screen.getByRole("group", { name: "メモに追記します" })).toBeInTheDocument();
    expect(screen.getByText("読書メモ")).toBeInTheDocument();
    expect(screen.getByText("第3章の要点")).toBeInTheDocument();
  });

  it("lists partial edits as numbered before/after pairs and marks a removal", () => {
    render(
      <ToolApprovalCard
        approval={memoEdit({
          mode: "edits",
          new_title: "議事録（確定）",
          edits: [
            { before: "来週", after: "9月30日" },
            { before: "仮の案", after: "" },
          ],
        })}
      />,
    );

    const preview = screen.getByRole("group", { name: "メモを書き換えます" });
    expect(within(preview).getByText("議事録（確定）")).toBeInTheDocument();
    const labels = Array.from(preview.querySelectorAll("dt")).map((node) => node.textContent);
    expect(labels).toEqual(["対象のメモ", "新しい題名", "変更前 1", "変更後 1", "変更前 2", "変更後 2"]);
    expect(within(preview).getByText("（削除）")).toBeInTheDocument();
  });

  it("does not number a single edit", () => {
    render(<ToolApprovalCard approval={memoEdit({ mode: "edits", edits: [{ before: "誤字", after: "正字" }] })} />);
    const labels = Array.from(document.querySelectorAll("dt")).map((node) => node.textContent);
    expect(labels).toEqual(["対象のメモ", "変更前", "変更後"]);
  });

  it("keeps a whole-body rewrite behind a disclosure", () => {
    render(<ToolApprovalCard approval={memoEdit({ mode: "content", content: "全部書き直した本文" })} />);
    const disclosure = screen.getByText("全文を表示").closest("details");
    expect(disclosure).not.toBeNull();
    expect(disclosure).not.toHaveAttribute("open");
    expect(disclosure).toHaveTextContent("全部書き直した本文");
  });
});

describe("approval cards inside messages", () => {
  it("passes decisions from a bot message and disables them on request", () => {
    const onToolApprovalDecide = vi.fn().mockResolvedValue(undefined);
    const parts = [
      { type: "text" as const, text: "メモを作る案です。" },
      { type: "tool_approval" as const, approval: approval() },
    ];
    const { rerender } = render(
      <BotMessageParts fallbackText="" parts={parts} onToolApprovalDecide={onToolApprovalDecide} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "拒否" }));
    expect(onToolApprovalDecide).toHaveBeenCalledWith("a1", "deny");

    rerender(
      <BotMessageParts fallbackText="" parts={parts} onToolApprovalDecide={onToolApprovalDecide} approvalsDisabled />,
    );
    expect(screen.getByRole("button", { name: "拒否" })).toBeDisabled();
  });

  it("shows only the status of a redacted card in the shared view", () => {
    const redacted = normalizeToolApproval({ id: "a1", tool: "memo_edit", family: "memo", status: "succeeded", decision: "once", readonly: true });
    if (!redacted) throw new Error("redacted card must be valid");
    render(<SharedChatMessageParts fallbackText="" parts={[{ type: "tool_approval", approval: redacted }]} />);

    expect(screen.getByRole("group", { name: "メモを書き換えます" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("実行しました");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
