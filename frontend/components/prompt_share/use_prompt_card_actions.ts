import { useCallback, useRef, useState } from "react";

import { showToast } from "../../scripts/core/toast";
import {
  addPromptAsTask,
  addPromptAsSkill,
  removePromptAsTask,
  removePromptLike,
  savePromptAsMemo,
  savePromptLike
} from "../../scripts/prompt_share/api";
import { normalizePromptContentFormat } from "../../scripts/prompt_share/formatters";
import type { PromptRecord } from "./prompt_card";
import { useTranslation } from "../../contexts/locale_context";

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
  const { t } = useTranslation();
  const [likePendingIds, setLikePendingIds] = useState<Set<string>>(new Set());
  const [addAsTaskPendingIds, setAddAsTaskPendingIds] = useState<Set<string>>(new Set());
  const [memoSavePendingIds, setMemoSavePendingIds] = useState<Set<string>>(new Set());
  const likePendingIdsRef = useRef<Set<string>>(new Set());
  const memoSavePendingIdsRef = useRef<Set<string>>(new Set());

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

  // メモ保存の送信中状態をrefとstateで同期し、連打による重複保存を防ぐ
  // Keeps memo-save pending state in a ref and state to prevent duplicate saves on rapid clicks
  const setMemoSavePending = useCallback((clientId: string, pending: boolean) => {
    if (pending) {
      memoSavePendingIdsRef.current.add(clientId);
    } else {
      memoSavePendingIdsRef.current.delete(clientId);
    }
    setMemoSavePendingIds(new Set(memoSavePendingIdsRef.current));
  }, []);

  // 共有プロンプトのタイトルと本文を既存のメモ作成APIへ保存する
  // Saves the shared prompt title and body through the existing memo creation API
  const handleSavePromptAsMemo = useCallback(
    async (prompt: PromptRecord) => {
      const promptId = prompt.clientId;
      closePromptDropdown();

      if (!isLoggedIn) {
        showToast(t("promptShare.loginToSaveMemo"), { variant: "error" });
        return;
      }

      if (memoSavePendingIdsRef.current.has(promptId)) {
        return;
      }

      setMemoSavePending(promptId, true);
      try {
        await savePromptAsMemo(prompt);
        showToast(t("promptShare.savedToMemo"), { variant: "success" });
      } catch (error) {
        console.error("プロンプトのメモ保存中にエラーが発生しました:", error);
        showToast(error instanceof Error ? error.message : t("promptShare.saveMemoFailed"), {
          variant: "error"
        });
      } finally {
        setMemoSavePending(promptId, false);
      }
    },
    [closePromptDropdown, isLoggedIn, setMemoSavePending, t]
  );

  // プロンプトのチャット利用状態、またはSkill追加を更新する。未ログインの場合はトーストで案内する
  // Updates either the use-in-chat toggle or shared-Skill import; guides anonymous users with a toast
  const handleAddPromptAsTask = useCallback(
    async (prompt: PromptRecord) => {
      const promptId = prompt.clientId;
      closePromptDropdown();

      const isSkill = normalizePromptContentFormat(String(prompt.content_format || "")) === "skill";
      if (!isLoggedIn) {
        showToast(t(isSkill ? "promptShare.loginToAddSkill" : "promptShare.loginToUse"), { variant: "error" });
        return;
      }

      if (isSkill && prompt.added_to_skills) {
        return;
      }

      const wasUsedInChat = Boolean(prompt.used_in_chat);
      const wasAddedToSkills = Boolean(prompt.added_to_skills);
      const nextUsedInChat = !wasUsedInChat;
      if (isSkill) {
        updatePromptRecord(promptId, (currentPrompt) => ({
          ...currentPrompt,
          added_to_skills: true
        }));
        triggerActionEffect(`${promptId}:add-skill`);
      } else {
        updatePromptRecord(promptId, (currentPrompt) => ({
          ...currentPrompt,
          used_in_chat: nextUsedInChat
        }));
        if (nextUsedInChat) {
          triggerActionEffect(`${promptId}:use-in-chat`);
        }
      }

      setAddAsTaskPending(promptId, true);
      try {
        const response = isSkill
          ? await addPromptAsSkill(prompt)
          : nextUsedInChat
            ? await addPromptAsTask(prompt)
            : await removePromptAsTask(prompt);
        const serverMessage =
          typeof response.message === "string" && response.message.trim()
            ? response.message
            : "";
        const fallbackMessage = isSkill
          ? t("promptShare.addedToSkills")
          : nextUsedInChat
            ? t("promptShare.addedToChat")
            : t("promptShare.removedFromChat");
        updatePromptRecord(promptId, (currentPrompt) => isSkill
          ? { ...currentPrompt, added_to_skills: true }
          : { ...currentPrompt, used_in_chat: nextUsedInChat });
        showToast(serverMessage || fallbackMessage, { variant: "success" });
      } catch (error) {
        console.error(isSkill ? "Skill追加中にエラーが発生しました:" : "チャット利用状態の更新中にエラーが発生しました:", error);
        updatePromptRecord(promptId, (currentPrompt) => isSkill
          ? { ...currentPrompt, added_to_skills: wasAddedToSkills }
          : { ...currentPrompt, used_in_chat: wasUsedInChat });
        showToast(error instanceof Error && error.message ? error.message : t(isSkill ? "promptShare.addSkillFailed" : "promptShare.updateChatFailed"), { variant: "error" });
      } finally {
        setAddAsTaskPending(promptId, false);
      }
    },
    [closePromptDropdown, isLoggedIn, setAddAsTaskPending, t, triggerActionEffect, updatePromptRecord]
  );

  // いいね状態を楽観的UIで即座に反映し、API失敗時はロールバックする
  // Optimistically updates the like state immediately and rolls back if the API call fails
  const handleTogglePromptLike = useCallback(
    async (prompt: PromptRecord) => {
      if (!isLoggedIn) {
        showToast(t("promptShare.loginToLike"), { variant: "error" });
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
        showToast(t("promptShare.likeUpdateFailed"), { variant: "error" });
      } finally {
        setLikePending(promptId, false);
      }
    },
    [isLoggedIn, setLikePending, t, triggerActionEffect, updatePromptRecord]
  );

  return {
    addAsTaskPendingIds,
    handleAddPromptAsTask,
    handleSavePromptAsMemo,
    handleTogglePromptLike,
    likePendingIds,
    memoSavePendingIds
  };
}
