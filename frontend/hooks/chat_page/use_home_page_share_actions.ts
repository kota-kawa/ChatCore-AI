import { useCallback, type MutableRefObject } from "react";

import { normalizeShareChatRoomPayload } from "../../lib/chat_page/api_contract";
import type { ChatRoomMode } from "../../lib/chat_page/types";
import { copyTextToClipboard } from "../../scripts/chat/message_utils";
import {
  extractApiErrorMessage,
  readJsonBodySafe,
} from "../../scripts/core/runtime_validation";
import { resilientFetch } from "../../scripts/core/resilient_fetch";

type ShareStatus = {
  message: string;
  error: boolean;
};

type UseHomePageShareActionsParams = {
  currentRoomIdRef: MutableRefObject<string | null>;
  currentRoomMode: ChatRoomMode;
  shareUrl: string;
  setShareStatus: (status: ShareStatus) => void;
  setShareUrl: (url: string) => void;
  setShareLoading: (loading: boolean) => void;
  setShareModalOpen: (open: boolean) => void;
  shareCacheRef: MutableRefObject<Map<string, string>>;
};

export function useHomePageShareActions({
  currentRoomIdRef,
  currentRoomMode,
  shareUrl,
  setShareStatus,
  setShareUrl,
  setShareLoading,
  setShareModalOpen,
  shareCacheRef,
}: UseHomePageShareActionsParams) {
  const closeShareModal = useCallback(() => {
    setShareModalOpen(false);
  }, []);

  const setShareActionLoading = useCallback((loading: boolean) => {
    setShareLoading(loading);
  }, []);

  const createShareLink = useCallback(
    async (forceRefresh = false) => {
      const roomId = currentRoomIdRef.current;
      if (!roomId) {
        setShareStatus({ message: "共有するチャットルームを選択してください。", error: true });
        setShareUrl("");
        return;
      }
      if (currentRoomMode === "temporary") {
        setShareStatus({ message: "未保存チャットは共有できません。", error: true });
        setShareUrl("");
        return;
      }

      if (!forceRefresh && shareCacheRef.current.has(roomId)) {
        const cached = shareCacheRef.current.get(roomId) || "";
        setShareUrl(cached);
        setShareStatus({ message: "共有リンクを表示しています。", error: false });
        return;
      }

      setShareActionLoading(true);
      setShareStatus({ message: "共有リンクを生成しています...", error: false });

      try {
        const response = await resilientFetch("/api/share_chat_room", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ room_id: roomId }),
        });
        const rawPayload = await readJsonBodySafe(response);
        const data = normalizeShareChatRoomPayload(rawPayload);

        if (!response.ok || !data.shareUrl) {
          throw new Error(extractApiErrorMessage(rawPayload, "共有リンクの作成に失敗しました。", response.status));
        }

        shareCacheRef.current.set(roomId, data.shareUrl);
        setShareUrl(data.shareUrl);
        setShareStatus({ message: "共有リンクを作成しました。", error: false });
      } catch (error) {
        setShareStatus({
          message: error instanceof Error ? error.message : "共有リンクの作成に失敗しました。",
          error: true,
        });
      } finally {
        setShareActionLoading(false);
      }
    },
    [currentRoomMode, setShareActionLoading],
  );

  const openShareModal = useCallback(() => {
    if (currentRoomMode === "temporary") {
      setShareStatus({ message: "未保存チャットは共有できません。", error: true });
      return;
    }
    setShareModalOpen(true);
    void createShareLink(false);
  }, [createShareLink, currentRoomMode]);

  const copyShareLink = useCallback(async () => {
    if (!shareUrl.trim()) {
      setShareStatus({ message: "先に共有リンクを生成してください。", error: true });
      return;
    }

    try {
      await copyTextToClipboard(shareUrl);
      setShareStatus({ message: "リンクをコピーしました。", error: false });
    } catch (error) {
      setShareStatus({
        message: error instanceof Error ? error.message : "リンクのコピーに失敗しました。",
        error: true,
      });
    }
  }, [shareUrl]);

  const shareWithNativeSheet = useCallback(async () => {
    if (!shareUrl.trim()) {
      setShareStatus({ message: "先に共有リンクを生成してください。", error: true });
      return;
    }
    if (!navigator.share) {
      setShareStatus({ message: "このブラウザはネイティブ共有に対応していません。", error: true });
      return;
    }

    try {
      await navigator.share({
        title: "Chat Core 共有チャット",
        text: "このチャットルームを共有しました。",
        url: shareUrl,
      });
      setShareStatus({ message: "共有シートを開きました。", error: false });
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") {
        return;
      }
      setShareStatus({
        message: error instanceof Error ? error.message : "共有に失敗しました。",
        error: true,
      });
    }
  }, [shareUrl]);

  return {
    closeShareModal,
    createShareLink,
    openShareModal,
    copyShareLink,
    shareWithNativeSheet,
  };
}
