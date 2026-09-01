import { useRef, useState } from "react";

import type { ShareStatus } from "../../lib/chat_page/types";
import { useTranslation } from "../../contexts/locale_context";
import { useShareLinks } from "../use_share";

export function useHomePageShareState() {
  const { locale, t } = useTranslation();
  const [shareModalOpen, setShareModalOpen] = useState(false);
  const [shareStatus, setShareStatus] = useState<ShareStatus>(() => ({ message: t("chat.shareRoomRequired"), error: false }));
  const [shareUrl, setShareUrl] = useState("");
  const [shareLoading, setShareLoading] = useState(false);
  const shareCacheRef = useRef<Map<string, string>>(new Map());
  const { socialLinks, supportsNativeShare } = useShareLinks({
    shareUrl,
    text: locale === "en" ? "Shared from Chat Core." : "このチャットルームを共有しました。",
  });

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
    shareXUrl: socialLinks.x,
    shareLineUrl: socialLinks.line,
    shareFacebookUrl: socialLinks.facebook,
    supportsNativeShare,
  };
}
