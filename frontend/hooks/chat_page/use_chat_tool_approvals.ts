import { useCallback, useEffect, useRef } from "react";

import { useTranslation } from "../../contexts/locale_context";
import {
  decideToolApproval,
  ToolApprovalDecisionError,
  type ToolApprovalDecision,
} from "../../lib/chat_page/tool_approval_api";
import { findToolApproval, shouldAutoContinueAfterApproval } from "../../lib/chat_page/tool_approvals";
import type { UiChatMessage } from "../../lib/chat_page/types";
import { showToast } from "../../scripts/core/toast";
import type { ToolApprovalApi } from "../../types/generated/api_schemas";

type UseChatToolApprovalsOptions = {
  messages: UiChatMessage[];
  isGenerating: boolean;
  // 最新のカードで表示中のメッセージのパーツを差し替える / Replaces the displayed part with the latest card
  applyToolApproval: (approval: ToolApprovalApi) => void;
  // 通常の送信経路 / The ordinary send path
  sendMessage: (text: string) => void;
};

// チャットの承認カードの決定を送り、応答のカードでメッセージを更新する。最新の回答のカードが
// すべて決まり1件以上成功したら、決まった文面を通常の送信経路で送って会話を続ける。
// Sends approval-card decisions and updates the message with the returned card. Once every card on the
// latest reply is settled and at least one succeeded, the fixed prompt goes through the ordinary send
// path to continue the conversation.
export function useChatToolApprovals({
  messages,
  isGenerating,
  applyToolApproval,
  sendMessage,
}: UseChatToolApprovalsOptions) {
  const { t } = useTranslation();
  // 仮想リストは画面外の行を作り直すので、カード側の状態とは別に送信中の ID をここで持つ
  // The virtual list rebuilds off-screen rows, so in-flight ids are tracked here as well as in the card
  const inFlightRef = useRef<Set<string>>(new Set());
  const messagesRef = useRef(messages);
  // 決定を反映した後のメッセージで自動継続を判定するため、判定はメッセージの更新後まで待つ
  // The auto-continue check waits until the messages carry the decision's update
  const decidedApprovalIdRef = useRef<string | null>(null);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  const handleToolApprovalDecide = useCallback(
    async (approvalId: string, decision: ToolApprovalDecision) => {
      if (inFlightRef.current.has(approvalId)) return;
      inFlightRef.current.add(approvalId);
      try {
        const approval = await decideToolApproval(approvalId, decision, t("chat.toolApproval.decisionFailed"));
        decidedApprovalIdRef.current = approval.id;
        applyToolApproval(approval);
      } catch (error) {
        if (error instanceof ToolApprovalDecisionError) {
          if (error.code === "approval_expired") {
            // 期限切れはサーバーが expired に更新済みなので、カードも同じ状態にそろえる
            // The server has already marked an expired card, so align the card with it
            const current = findToolApproval(messagesRef.current, approvalId);
            if (current) applyToolApproval({ ...current, status: "expired" });
          } else if (error.code === "approval_already_decided" && error.approval) {
            // 別タブなどで先に決まったカードの最新状態が応答に載っているので、それに差し替える
            // The response carries the card's latest state, settled elsewhere (another tab, say);
            // swap the card with it
            applyToolApproval(error.approval);
          }
        }
        showToast(error instanceof Error ? error.message : t("chat.toolApproval.decisionFailed"), { variant: "error" });
      } finally {
        inFlightRef.current.delete(approvalId);
      }
    },
    [applyToolApproval, t],
  );

  useEffect(() => {
    const decidedApprovalId = decidedApprovalIdRef.current;
    if (decidedApprovalId === null) return;
    decidedApprovalIdRef.current = null;
    if (isGenerating) return;
    if (shouldAutoContinueAfterApproval(messages, decidedApprovalId)) {
      sendMessage(t("chat.toolApproval.continuePrompt"));
    }
    // メッセージの更新だけを合図にする。送信関数や言語の入れ替わりで判定し直さない
    // Only a messages update is the trigger; a new send function or locale must not re-run the check
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages]);

  return { handleToolApprovalDecide };
}
