import { useCallback, useRef, useState } from "react";

import { showToast } from "../../scripts/core/toast";
import {
  addPromptAsTask,
  removePromptAsTask,
  removePromptLike,
  savePromptLike
} from "../../scripts/prompt_share/api";
import type { PromptRecord } from "./prompt_card";

type UsePromptCardActionsOptions = {
  closePromptDropdown: () => void;
  isLoggedIn: boolean;
  triggerActionEffect: (effectId: string) => void;
  updatePromptRecord: (clientId: string, updater: (prompt: PromptRecord) => PromptRecord) => void;
};

// プロンプトカードのいいね・チャット利用設定とpending状態を管理する
// Manages prompt card like/use-in-chat actions and pending state
export function usePromptCardActions({
  closePromptDropdown,
  isLoggedIn,
  triggerActionEffect,
  updatePromptRecord
}: UsePromptCardActionsOptions) {
  const [likePendingIds, setLikePendingIds] = useState<Set<string>>(new Set());
  const [addAsTaskPendingIds, setAddAsTaskPendingIds] = useState<Set<string>>(new Set());
  const likePendingIdsRef = useRef<Set<string>>(new Set());

  // いいね操作のAPIリクエスト中に重複送信を防ぐためのフラグを管理する
  // Manages a pending flag to prevent duplicate like API requests
  const setLikePending = useCallback((clientId: string, pending: boolean) => {
    if (pending) {
      likePendingIdsRef.current.add(clientId);
    } else {
      likePendingIdsRef.current.delete(clientId);
    }
    setLikePendingIds(new Set(likePendingIdsRef.current));
  }, []);

  // タスク追加の非同期処理中に重複リクエストを防ぐためのフラグを管理する
  // Manages a pending flag to prevent duplicate add-as-task requests
  const setAddAsTaskPending = useCallback((clientId: string, pending: boolean) => {
    setAddAsTaskPendingIds((current) => {
      const next = new Set(current);
      if (pending) {
        next.add(clientId);
      } else {
        next.delete(clientId);
      }
      return next;
    });
  }, []);

  // プロンプトのチャット利用状態をトグルするAPIを呼び出す。未ログインの場合はトーストで案内する
  // Calls the use-in-chat toggle API; shows a toast guide if the user is not logged in
  const handleAddPromptAsTask = useCallback(
    async (prompt: PromptRecord) => {
      const promptId = prompt.clientId;
      closePromptDropdown();

      if (!isLoggedIn) {
        showToast("チャットで使うにはログインが必要です。", { variant: "error" });
        return;
      }

      const wasUsedInChat = Boolean(prompt.used_in_chat);
      const nextUsedInChat = !wasUsedInChat;
      updatePromptRecord(promptId, (currentPrompt) => ({
        ...currentPrompt,
        used_in_chat: nextUsedInChat
      }));
      if (nextUsedInChat) {
        triggerActionEffect(`${promptId}:use-in-chat`);
      }

      setAddAsTaskPending(promptId, true);
      try {
        const response = nextUsedInChat
          ? await addPromptAsTask(prompt)
          : await removePromptAsTask(prompt);
        const serverMessage =
          typeof response.message === "string" && response.message.trim()
            ? response.message
            : "";
        const fallbackMessage = nextUsedInChat
          ? "チャットで使えるように追加しました。"
          : "チャットで使う設定を解除しました。";
        updatePromptRecord(promptId, (currentPrompt) => ({
          ...currentPrompt,
          used_in_chat: nextUsedInChat
        }));
        showToast(serverMessage || fallbackMessage, { variant: "success" });
      } catch (error) {
        console.error("チャット利用状態の更新中にエラーが発生しました:", error);
        updatePromptRecord(promptId, (currentPrompt) => ({
          ...currentPrompt,
          used_in_chat: wasUsedInChat
        }));
        showToast("チャットで使う設定の更新中にエラーが発生しました。", { variant: "error" });
      } finally {
        setAddAsTaskPending(promptId, false);
      }
    },
    [closePromptDropdown, isLoggedIn, setAddAsTaskPending, triggerActionEffect, updatePromptRecord]
  );

  // いいね状態を楽観的UIで即座に反映し、API失敗時はロールバックする
  // Optimistically updates the like state immediately and rolls back if the API call fails
  const handleTogglePromptLike = useCallback(
    async (prompt: PromptRecord) => {
      if (!isLoggedIn) {
        showToast("いいねするにはログインが必要です。", { variant: "error" });
        return;
      }

      const promptId = prompt.clientId;
      // 処理中の場合は重複リクエストを無視する
      // Ignore duplicate requests while an operation is already in progress
      if (likePendingIdsRef.current.has(promptId)) {
        return;
      }

      const shouldLike = !prompt.liked;
      setLikePending(promptId, true);
      updatePromptRecord(promptId, (currentPrompt) => ({
        ...currentPrompt,
        liked: shouldLike
      }));
      if (shouldLike) {
        triggerActionEffect(`${promptId}:like`);
      }

      try {
        const request = shouldLike ? savePromptLike(prompt) : removePromptLike(prompt);
        await request;
      } catch (error) {
        console.error("いいね操作エラー:", error);
        // 失敗した場合は元の状態に戻す
        // Revert to the original state on failure
        updatePromptRecord(promptId, (currentPrompt) => ({
          ...currentPrompt,
          liked: !shouldLike
        }));
        showToast("いいねの更新中にエラーが発生しました。", { variant: "error" });
      } finally {
        setLikePending(promptId, false);
      }
    },
    [isLoggedIn, setLikePending, triggerActionEffect, updatePromptRecord]
  );

  return {
    addAsTaskPendingIds,
    handleAddPromptAsTask,
    handleTogglePromptLike,
    likePendingIds
  };
}
