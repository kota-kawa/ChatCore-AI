import { useCallback, useState } from "react";
import type { KeyedMutator } from "swr";

import { useTranslation } from "../../contexts/locale_context";
import { createMemoShare, fetchMemoShare } from "../../lib/memo/api";
import type { FlashState, MemoListState, MemoSummary, SharePayload } from "../../lib/memo/types";
import { shareWithNativeSheet as openNativeShare } from "../../lib/share";
import { copyTextToClipboard } from "../../scripts/core/clipboard";
import { useShareLinks } from "../use_share";

type UseMemoPageShareParams = {
  mutate: KeyedMutator<MemoListState>;
  showFlash: (type: FlashState["type"], text: string) => void;
};

// 共有モーダル（共有リンクの取得・作成・コピー・ネイティブ共有）
// Share modal (fetch / create / copy the share link, native share sheet)
export function useMemoPageShare({ mutate, showFlash }: UseMemoPageShareParams) {
  const { t } = useTranslation();

  // Share modal
  const [isShareModalOpen, setIsShareModalOpen] = useState(false);
  const [shareState, setShareState] = useState<SharePayload | null>(null);
  const [shareStatus, setShareStatus] = useState<FlashState | null>(null);
  const [shareLoading, setShareLoading] = useState(false);

  const shareUrl = (shareState?.share_url || "").trim();
  const { socialLinks: shareSnsLinks, supportsNativeShare } = useShareLinks({
    shareUrl,
    text: t("memo.nativeShareText"),
  });

  const loadShareState = useCallback(async (memoId: string | number) => {
    const payload = await fetchMemoShare(memoId, t("memo.shareInfoFailed"));
    setShareState(payload);
    return payload;
  }, []);

  const openShareModal = useCallback(async (memo: MemoSummary) => {
    const memoId = String(memo.id || "");
    if (!memoId) { showFlash("error", t("memo.shareTargetMissing")); return; }
    setIsShareModalOpen(true);
    setShareState(null);
    setShareStatus({ type: "success", text: t("memo.loadingShareInfo") });
    setShareLoading(true);
    try {
      const payload = await loadShareState(memoId);
      if (payload.share_url && payload.is_active) {
        setShareStatus({ type: "success", text: t("memo.showingShareLink") });
        return;
      }

      setShareStatus({ type: "success", text: t("memo.creatingShareLink") });
      const createdPayload = await createMemoShare(memoId, t("memo.createShareLinkFailed"));
      setShareState(createdPayload);
      setShareStatus({ type: "success", text: t("memo.shareLinkCreated") });
      await mutate();
    } catch (error) {
      setShareStatus({ type: "error", text: error instanceof Error ? error.message : t("memo.shareInfoFailed") });
    } finally {
      setShareLoading(false);
    }
  }, [loadShareState, mutate, showFlash]);

  const closeShareModal = useCallback(() => {
    setIsShareModalOpen(false);
    setShareStatus(null);
    setShareState(null);
  }, []);

  const copyShareLink = useCallback(async (): Promise<boolean> => {
    if (!shareUrl) { setShareStatus({ type: "error", text: t("memo.createShareLinkFirst") }); return false; }
    try {
      await copyTextToClipboard(shareUrl);
      setShareStatus({ type: "success", text: t("memo.shareLinkCopied") });
      return true;
    } catch (error) {
      setShareStatus({ type: "error", text: error instanceof Error ? error.message : t("memo.copyLinkFailed") });
      return false;
    }
  }, [shareUrl]);

  const openNativeShareSheet = useCallback(async () => {
    if (!shareUrl) { setShareStatus({ type: "error", text: t("memo.createShareLinkFirst") }); return; }
    const result = await openNativeShare({ title: t("memo.nativeShareTitle"), text: t("memo.nativeShareText"), url: shareUrl });
    if (result.status === "cancelled") return;
    if (result.status === "unsupported") {
      setShareStatus({ type: "error", text: t("memo.nativeShareUnsupported") });
      return;
    }
    if (result.status === "failed") {
      setShareStatus({ type: "error", text: result.error instanceof Error ? result.error.message : t("memo.nativeShareFailed") });
    }
  }, [shareUrl, t]);

  return {
    isShareModalOpen,
    setIsShareModalOpen,
    shareUrl,
    shareStatus,
    shareLoading,
    supportsNativeShare,
    shareSnsLinks,
    openShareModal,
    closeShareModal,
    copyShareLink,
    openNativeShareSheet,
  };
}
