import { useCallback, useMemo, useRef, useState } from "react";

import { copyTextToClipboard } from "../../scripts/chat/message_utils";
import { PROMPT_SHARE_TEXT, PROMPT_SHARE_TITLE } from "../../scripts/prompt_share/constants";
import { buildPromptPath } from "../../lib/promptSlug";
import type { PromptRecord } from "./prompt_card";
import { getPromptId } from "./prompt_share_page_utils";

// 共有モーダルのURL生成・SNSリンク・コピー・Web Share操作を管理する
// Manages share modal URL creation, SNS links, copy action, and Web Share action
export function usePromptShareDialog() {
  const [shareUrl, setShareUrl] = useState("");
  const [shareStatus, setShareStatus] = useState({
    text: "共有するプロンプトを選択してください。",
    isError: false
  });
  const [shareActionLoading, setShareActionLoading] = useState(false);
  const cachedPromptShareUrlsRef = useRef<Map<string, string>>(new Map());

  // SNS共有リンクを共有URLから動的に生成する。URLが未設定の場合は無効なリンクを返す
  // Derives SNS share links from the share URL; returns placeholder links if none is set
  const shareSnsLinks = useMemo(() => {
    if (!shareUrl) {
      return {
        x: "#",
        line: "#",
        facebook: "#"
      };
    }
    const encodedUrl = encodeURIComponent(shareUrl);
    const encodedText = encodeURIComponent(PROMPT_SHARE_TEXT);
    return {
      x: `https://twitter.com/intent/tweet?url=${encodedUrl}&text=${encodedText}`,
      line: `https://social-plugins.line.me/lineit/share?url=${encodedUrl}`,
      facebook: `https://www.facebook.com/sharer/sharer.php?u=${encodedUrl}`
    };
  }, [shareUrl]);

  // プロンプトIDとタイトルをもとに、SEOに適したスラッグ付きの外部共有パーマリンクを生成する
  // Generates a permanent shareable link from the prompt's ID and title, including an SEO-friendly slug
  const buildPromptShareUrl = useCallback((prompt: PromptRecord | null) => {
    const promptId = getPromptId(prompt);
    if (!promptId) {
      throw new Error("共有対象のプロンプトIDが見つかりません。");
    }
    return `${window.location.origin}${buildPromptPath(promptId, prompt?.title)}`;
  }, []);

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
        setPromptShareStatus("共有するプロンプトを選択してください。", true);
        return;
      }

      if (!forceRefresh && cachedPromptShareUrlsRef.current.has(promptId)) {
        setShareUrl(cachedPromptShareUrlsRef.current.get(promptId) || "");
        setPromptShareStatus("共有リンクを表示しています。");
        return;
      }

      setShareActionLoading(true);
      setPromptShareStatus("共有リンクを準備しています...");

      try {
        const generatedShareUrl = buildPromptShareUrl(prompt);
        cachedPromptShareUrlsRef.current.set(promptId, generatedShareUrl);
        setShareUrl(generatedShareUrl);
        setPromptShareStatus("共有リンクを表示しています。");
      } catch (error) {
        setPromptShareStatus(error instanceof Error ? error.message : String(error), true);
      } finally {
        setShareActionLoading(false);
      }
    },
    [buildPromptShareUrl, setPromptShareStatus]
  );

  // 共有URLをクリップボードにコピーし、結果をステータスメッセージとして表示する
  // Copies the share URL to the clipboard and reflects the outcome in the status message
  const handleCopyShareLink = useCallback(async () => {
    const currentShareUrl = shareUrl.trim();
    if (!currentShareUrl) {
      setPromptShareStatus("先に共有リンクを表示してください。", true);
      return;
    }

    try {
      await copyTextToClipboard(currentShareUrl);
      setPromptShareStatus("リンクをコピーしました。");
    } catch (error) {
      setPromptShareStatus(error instanceof Error ? error.message : String(error), true);
    }
  }, [setPromptShareStatus, shareUrl]);

  // Web Share APIを呼び出し、ネイティブ共有シートを表示する（非対応ブラウザでは使用不可）
  // Invokes the Web Share API to open the native share sheet (unavailable on unsupported browsers)
  const handleNativeShare = useCallback(async () => {
    const currentShareUrl = shareUrl.trim();
    if (!currentShareUrl) {
      setPromptShareStatus("先に共有リンクを表示してください。", true);
      return;
    }

    if (typeof navigator.share !== "function") {
      setPromptShareStatus("このブラウザはネイティブ共有に対応していません。", true);
      return;
    }

    try {
      await navigator.share({
        title: PROMPT_SHARE_TITLE,
        text: PROMPT_SHARE_TEXT,
        url: currentShareUrl
      });
      setPromptShareStatus("共有シートを開きました。");
    } catch (error) {
      // ユーザーが共有シートをキャンセルした場合はエラーとして扱わない
      // User-initiated cancellation of the share sheet is not treated as an error
      if (error instanceof Error && error.name === "AbortError") {
        return;
      }
      setPromptShareStatus(error instanceof Error ? error.message : String(error), true);
    }
  }, [setPromptShareStatus, shareUrl]);

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
