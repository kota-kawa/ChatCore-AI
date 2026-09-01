import { useCallback, type MutableRefObject } from "react";

import { normalizeShareChatRoomPayload } from "../../lib/chat_page/api_contract";
import type { ChatRoomMode } from "../../lib/chat_page/types";
import { shareWithNativeSheet as openNativeShare } from "../../lib/share";
import { copyTextToClipboard } from "../../scripts/core/clipboard";
import {
  extractApiErrorMessage,
  readJsonBodySafe,
} from "../../scripts/core/runtime_validation";
import { resilientFetch } from "../../scripts/core/resilient_fetch";
import { useTranslation } from "../../contexts/locale_context";

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
  const { locale, t } = useTranslation();
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
        setShareStatus({ message: t("chat.shareRoomRequired"), error: true });
        setShareUrl("");
        return;
      }
      if (currentRoomMode === "temporary") {
        setShareStatus({ message: t("chat.temporaryCannotShare"), error: true });
        setShareUrl("");
        return;
      }

      if (!forceRefresh && shareCacheRef.current.has(roomId)) {
        const cached = shareCacheRef.current.get(roomId) || "";
        setShareUrl(cached);
        setShareStatus({ message: locale === "en" ? "Showing the existing share link." : "共有リンクを表示しています。", error: false });
        return;
      }

      setShareActionLoading(true);
      setShareStatus({ message: t("chat.generatingShare"), error: false });

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
          throw new Error(extractApiErrorMessage(rawPayload, t("chat.shareFailed"), response.status));
        }

        shareCacheRef.current.set(roomId, data.shareUrl);
        setShareUrl(data.shareUrl);
        setShareStatus({ message: t("chat.shareCreated"), error: false });
      } catch (error) {
        setShareStatus({
          message: error instanceof Error ? error.message : t("chat.shareFailed"),
          error: true,
        });
      } finally {
        setShareActionLoading(false);
      }
    },
    [currentRoomMode, locale, setShareActionLoading, t],
  );

  const openShareModal = useCallback(() => {
    if (currentRoomMode === "temporary") {
      setShareStatus({ message: t("chat.temporaryCannotShare"), error: true });
      return;
    }
    setShareModalOpen(true);
    void createShareLink(false);
  }, [createShareLink, currentRoomMode, t]);

  // 戻り値でコピー成否を返し、呼び出し側がコピーボタンのアイコンをチェックマークへ切り替えられるようにする。
  // Returns whether the copy succeeded so the caller can flip the copy button icon to a check mark.
  const copyShareLink = useCallback(async (): Promise<boolean> => {
    if (!shareUrl.trim()) {
      setShareStatus({ message: locale === "en" ? "Create a share link first." : "先に共有リンクを生成してください。", error: true });
      return false;
    }

    try {
      await copyTextToClipboard(shareUrl);
      setShareStatus({ message: t("common.copied"), error: false });
      return true;
    } catch (error) {
      setShareStatus({
        message: error instanceof Error ? error.message : t("chat.copyLinkFailed"),
        error: true,
      });
      return false;
    }
  }, [locale, shareUrl, t]);

  const shareWithNativeSheet = useCallback(async () => {
    if (!shareUrl.trim()) {
      setShareStatus({ message: locale === "en" ? "Create a share link first." : "先に共有リンクを生成してください。", error: true });
      return;
    }
    const result = await openNativeShare({
      title: locale === "en" ? "Chat Core shared chat" : "Chat Core 共有チャット",
      text: locale === "en" ? "Shared from Chat Core." : "このチャットルームを共有しました。",
      url: shareUrl,
    });
    if (result.status === "cancelled") return;
    if (result.status === "unsupported") {
      setShareStatus({ message: locale === "en" ? "This browser does not support native sharing." : "このブラウザはネイティブ共有に対応していません。", error: true });
      return;
    }
    if (result.status === "shared") {
      setShareStatus({ message: locale === "en" ? "Share sheet opened." : "共有シートを開きました。", error: false });
      return;
    }

    const error = result.error;
    setShareStatus({
      message: error instanceof Error ? error.message : (locale === "en" ? "Sharing failed." : "共有に失敗しました。"),
      error: true,
    });
  }, [locale, shareUrl]);

  return {
    closeShareModal,
    createShareLink,
    openShareModal,
    copyShareLink,
    shareWithNativeSheet,
  };
}
