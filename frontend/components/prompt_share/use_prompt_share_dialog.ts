import { useCallback, useRef, useState } from "react";

import { copyTextToClipboard } from "../../scripts/core/clipboard";
import { shareWithNativeSheet as openNativeShare } from "../../lib/share";
import { buildPromptPath } from "../../lib/promptSlug";
import type { PromptRecord } from "./prompt_card";
import { getPromptId } from "./prompt_share_page_utils";
import { useTranslation } from "../../contexts/locale_context";
import { useShareLinks } from "../../hooks/use_share";

// 共有モーダルのURL生成・SNSリンク・コピー・Web Share操作を管理する
// Manages share modal URL creation, SNS links, copy action, and Web Share action
export function usePromptShareDialog() {
  const { t } = useTranslation();
  const [shareUrl, setShareUrl] = useState("");
  const [shareStatus, setShareStatus] = useState({
    text: t("promptShare.selectToShare"),
    isError: false
  });
  const [shareActionLoading, setShareActionLoading] = useState(false);
  const cachedPromptShareUrlsRef = useRef<Map<string, string>>(new Map());

  const { socialLinks: shareSnsLinks } = useShareLinks({
    shareUrl,
    text: t("promptShare.shareHelp"),
  });

  // プロンプトIDとタイトルをもとに、SEOに適したスラッグ付きの外部共有パーマリンクを生成する
  // Generates a permanent shareable link from the prompt's ID and title, including an SEO-friendly slug
  const buildPromptShareUrl = useCallback((prompt: PromptRecord | null) => {
    const promptId = getPromptId(prompt);
    if (!promptId) {
      throw new Error(t("promptShare.shareTargetMissing"));
    }
    return `${window.location.origin}${buildPromptPath(promptId, prompt?.title)}`;
  }, [t]);

  // 共有モーダルのステータステキストをisErrorフラグと一緒に更新するヘルパー
  // Helper to update the share modal status text alongside the isError flag
  const setPromptShareStatus = useCallback((text: string, isError = false) => {
    setShareStatus({ text, isError });
  }, []);

  // キャッシュされた共有URLがあれば再利用し、なければ新たにURLを生成する
  // Reuses a cached share URL when available to avoid regenerating it unnecessarily
  const createPromptShareLink = useCallback(
    async (prompt: PromptRecord | null, forceRefresh = false) => {
      const promptId = getPromptId(prompt);
      if (!prompt || !promptId) {
        setShareUrl("");
        setPromptShareStatus(t("promptShare.selectToShare"), true);
        return;
      }

      if (!forceRefresh && cachedPromptShareUrlsRef.current.has(promptId)) {
        setShareUrl(cachedPromptShareUrlsRef.current.get(promptId) || "");
        setPromptShareStatus(t("promptShare.showingShareLink"));
        return;
      }

      setShareActionLoading(true);
      setPromptShareStatus(t("promptShare.preparingShareLink"));

      try {
        const generatedShareUrl = buildPromptShareUrl(prompt);
        cachedPromptShareUrlsRef.current.set(promptId, generatedShareUrl);
        setShareUrl(generatedShareUrl);
        setPromptShareStatus(t("promptShare.showingShareLink"));
      } catch (error) {
        setPromptShareStatus(error instanceof Error ? error.message : String(error), true);
      } finally {
        setShareActionLoading(false);
      }
    },
    [buildPromptShareUrl, setPromptShareStatus, t]
  );

  // 共有URLをクリップボードにコピーし、結果をステータスメッセージとして表示する
  // Copies the share URL to the clipboard and reflects the outcome in the status message
  const handleCopyShareLink = useCallback(async (): Promise<boolean> => {
    const currentShareUrl = shareUrl.trim();
    if (!currentShareUrl) {
      setPromptShareStatus(t("promptShare.showLinkFirst"), true);
      return false;
    }

    try {
      await copyTextToClipboard(currentShareUrl);
      setPromptShareStatus(t("promptShare.linkCopied"));
      return true;
    } catch (error) {
      setPromptShareStatus(error instanceof Error ? error.message : String(error), true);
      return false;
    }
  }, [setPromptShareStatus, shareUrl, t]);

  // Web Share APIを呼び出し、ネイティブ共有シートを表示する（非対応ブラウザでは使用不可）
  // Invokes the Web Share API to open the native share sheet (unavailable on unsupported browsers)
  const handleNativeShare = useCallback(async () => {
    const currentShareUrl = shareUrl.trim();
    if (!currentShareUrl) {
      setPromptShareStatus(t("promptShare.showLinkFirst"), true);
      return;
    }

    const result = await openNativeShare({
        title: t("promptShare.sharePrompt"),
        text: t("promptShare.shareHelp"),
        url: currentShareUrl
    });
    if (result.status === "cancelled") return;
    if (result.status === "unsupported") {
      setPromptShareStatus(t("promptShare.nativeShareUnsupported"), true);
      return;
    }
    if (result.status === "shared") {
      setPromptShareStatus(t("promptShare.shareSheetOpened"));
      return;
    }

    setPromptShareStatus(
      result.error instanceof Error ? result.error.message : "Native sharing failed.",
      true,
    );
  }, [setPromptShareStatus, shareUrl, t]);

  return {
    createPromptShareLink,
    handleCopyShareLink,
    handleNativeShare,
    shareActionLoading,
    shareSnsLinks,
    shareStatus,
    shareUrl
  };
}
