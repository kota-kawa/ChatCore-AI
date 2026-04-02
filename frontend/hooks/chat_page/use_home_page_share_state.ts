import { useMemo, useRef, useState } from "react";

import type { ShareStatus } from "../../lib/chat_page/types";

const DEFAULT_SHARE_STATUS: ShareStatus = {
  message: "共有するチャットルームを選択してください。",
  error: false,
};

export function useHomePageShareState() {
  const [shareModalOpen, setShareModalOpen] = useState(false);
  const [shareStatus, setShareStatus] = useState<ShareStatus>(DEFAULT_SHARE_STATUS);
  const [shareUrl, setShareUrl] = useState("");
  const [shareLoading, setShareLoading] = useState(false);
  const shareCacheRef = useRef<Map<string, string>>(new Map());

  const shareXUrl = useMemo(() => {
    const encodedUrl = encodeURIComponent(shareUrl);
    const encodedText = encodeURIComponent("このチャットルームを共有しました。");
    return `https://twitter.com/intent/tweet?url=${encodedUrl}&text=${encodedText}`;
  }, [shareUrl]);

  const shareLineUrl = useMemo(() => {
    const encodedUrl = encodeURIComponent(shareUrl);
    return `https://social-plugins.line.me/lineit/share?url=${encodedUrl}`;
  }, [shareUrl]);

  const shareFacebookUrl = useMemo(() => {
    const encodedUrl = encodeURIComponent(shareUrl);
    return `https://www.facebook.com/sharer/sharer.php?u=${encodedUrl}`;
  }, [shareUrl]);

  const supportsNativeShare =
    typeof navigator !== "undefined"
    && typeof (navigator as Navigator & { share?: unknown }).share === "function";

  return {
    shareModalOpen,
    setShareModalOpen,
    shareStatus,
    setShareStatus,
    shareUrl,
    setShareUrl,
    shareLoading,
    setShareLoading,
    shareCacheRef,
    shareXUrl,
    shareLineUrl,
    shareFacebookUrl,
    supportsNativeShare,
  };
}
