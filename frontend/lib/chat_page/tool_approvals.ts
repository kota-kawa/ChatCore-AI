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

// 承認の決定を受けて、決まった文面で会話を自動的に続けるか。最新のアシスタント発言にある
// カードがすべて決まり、1件以上が成功したときだけ続ける。全部拒否・失敗なら利用者の次の発言を待つ。
// 決めたカードが最新の発言のものでない、後ろにすでに利用者の発言がある場合も続けない。
// Whether to continue the conversation with the fixed prompt after a decision. Continue only when
// every card on the latest assistant message is settled and at least one succeeded; when all were
// denied or failed, wait for the user. Never continue for a card on an older message or once the
// user has already written after it.
export function shouldAutoContinueAfterApproval(messages: UiChatMessage[], decidedApprovalId: string): boolean {
  let latestAssistant: UiChatMessage | undefined;
  for (const message of messages) {
    if (message.sender === "assistant") latestAssistant = message;
    if (message.sender === "user") latestAssistant = undefined;
  }
  if (!latestAssistant) return false;

  const approvals = approvalsOf(latestAssistant);
  if (!approvals.some((approval) => approval.id === decidedApprovalId)) return false;
  if (approvals.some((approval) => approval.status === "pending")) return false;
  return approvals.some((approval) => approval.status === "succeeded");
}
