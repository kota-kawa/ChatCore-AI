import { useCallback, useEffect, useRef } from "react";
import { useRouter } from "next/router";

import { useTranslation } from "../../contexts/locale_context";
import {
  decideToolApproval,
  ToolApprovalDecisionError,
  type ToolApprovalDecision,
} from "../../lib/chat_page/tool_approval_api";
import { findToolApproval } from "../../lib/chat_page/tool_approvals";
import type { UiChatMessage } from "../../lib/chat_page/types";
import type { Locale } from "../../lib/i18n/config";
import { setThemePreference } from "../../scripts/core/theme";
import { showToast } from "../../scripts/core/toast";
import type { ToolApprovalApi } from "../../types/generated/api_schemas";

type UseChatToolApprovalsOptions = {
  messages: UiChatMessage[];
  // 最新のカードで表示中のメッセージのパーツを差し替える / Replaces the displayed part with the latest card
  applyToolApproval: (approval: ToolApprovalApi) => void;
};

// チャットの承認カードの決定を送り、応答のカードでメッセージを更新する。決定してもチャットは
// 送信しない。結果は利用者の次の発言のときにサーバーが AI の文脈へ加える。
// Sends approval-card decisions and updates the message with the returned card. A decision never sends
// a chat message; the server adds the outcome to the AI's context on the user's next message.
export function useChatToolApprovals({ messages, applyToolApproval }: UseChatToolApprovalsOptions) {
  const { t, setLocale } = useTranslation();
  const router = useRouter();
  // 仮想リストは画面外の行を作り直すので、カード側の状態とは別に送信中の ID をここで持つ
  // The virtual list rebuilds off-screen rows, so in-flight ids are tracked here as well as in the card
  const inFlightRef = useRef<Set<string>>(new Set());
  const messagesRef = useRef(messages);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  const handleToolApprovalDecide = useCallback(
    async (approvalId: string, decision: ToolApprovalDecision, acknowledgeWarnings = false) => {
      if (inFlightRef.current.has(approvalId)) return;
      inFlightRef.current.add(approvalId);
      const syncProfilePreferences = (
        approval: ToolApprovalApi,
        currentPreferredLocale: Locale | null,
        usePreviewLocaleFallback: boolean,
      ) => {
        if (
          approval.tool !== "profile_settings_update"
          || approval.status !== "succeeded"
          || approval.preview?.kind !== "profile_settings_update"
        ) {
          return;
        }
        const locale = currentPreferredLocale
          ?? (usePreviewLocaleFallback ? approval.preview.preferred_locale : null);
        if (locale !== null) {
          setLocale(locale);
          void router.replace(router.asPath, router.asPath, { locale });
        }
        if (approval.preview.theme !== null) {
          setThemePreference(approval.preview.theme);
        }
      };
      try {
        const result = acknowledgeWarnings
          ? await decideToolApproval(approvalId, decision, t("chat.toolApproval.decisionFailed"), undefined, true)
          : await decideToolApproval(approvalId, decision, t("chat.toolApproval.decisionFailed"));
        const { approval } = result;
        syncProfilePreferences(approval, result.currentPreferredLocale, true);
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
            // synchronize any committed profile preferences and swap the card with it
            syncProfilePreferences(error.approval, error.currentPreferredLocale, false);
            applyToolApproval(error.approval);
          }
        }
        showToast(error instanceof Error ? error.message : t("chat.toolApproval.decisionFailed"), { variant: "error" });
      } finally {
        inFlightRef.current.delete(approvalId);
      }
    },
    [applyToolApproval, router, setLocale, t],
  );

  return { handleToolApprovalDecide };
}
