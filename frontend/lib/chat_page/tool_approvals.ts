// チャットの承認カード（tool_approval パーツ）を扱う純関数群。React にも fetch にも依存しないので、
// メッセージ列と期待する結果だけでテストできる。
// Pure helpers for chat approval cards (tool_approval parts). They depend on neither React nor fetch,
// so they can be tested against message lists and expected results alone.

import type { ToolApprovalApi } from "../../types/generated/api_schemas";
import type { UiChatMessage } from "./types";

// 期限を過ぎた承認待ちは、サーバーが expired に更新する前でも押せないものとして扱う。
// A pending card past its deadline is treated as unpressable even before the server marks it expired.
export function isToolApprovalExpired(approval: ToolApprovalApi, nowMs: number): boolean {
  if (approval.status === "expired") return true;
  if (approval.status !== "pending" || !approval.expires_at) return false;
  const expiresAtMs = Date.parse(approval.expires_at);
  return Number.isFinite(expiresAtMs) && expiresAtMs <= nowMs;
}

// 利用者が今このカードで決められるか。共有・fork で読み取り専用になったカードは決められない。
// Whether the user can decide this card now; cards made readonly by a share or fork cannot be decided.
export function isToolApprovalDecidable(approval: ToolApprovalApi, nowMs: number): boolean {
  return approval.status === "pending" && !approval.readonly && !isToolApprovalExpired(approval, nowMs);
}

function approvalsOf(message: UiChatMessage): ToolApprovalApi[] {
  return (message.parts ?? []).flatMap((part) => (part.type === "tool_approval" ? [part.approval] : []));
}

// 承認 API が返した最新のカードで、同じ ID のパーツを差し替える。見つからなければ元の配列を返す。
// Replace the part with the same id by the latest card from the approval API; return the list as is
// when no part matches.
export function replaceToolApprovalInMessages(
  messages: UiChatMessage[],
  approval: ToolApprovalApi,
): UiChatMessage[] {
  let replaced = false;
  const nextMessages = messages.map((message) => {
    if (!message.parts?.some((part) => part.type === "tool_approval" && part.approval.id === approval.id)) {
      return message;
    }
    replaced = true;
    return {
      ...message,
      parts: message.parts.map((part) =>
        part.type === "tool_approval" && part.approval.id === approval.id ? { ...part, approval } : part,
      ),
    };
  });
  return replaced ? nextMessages : messages;
}

export function findToolApproval(messages: UiChatMessage[], approvalId: string): ToolApprovalApi | undefined {
  for (const message of messages) {
    const approval = approvalsOf(message).find((candidate) => candidate.id === approvalId);
    if (approval) return approval;
  }
  return undefined;
}
