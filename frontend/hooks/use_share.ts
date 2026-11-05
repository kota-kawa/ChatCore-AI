// 共有 URL から SNS 共有リンク（X・LINE・Facebook）を作り、ブラウザが Web Share API に対応しているかを返すフック。チャットとメモの共有モーダルが使う。
// Hook that builds social share links (X, LINE, Facebook) from a share URL and reports Web Share API support; used by the chat and memo share modals.
import { useEffect, useMemo, useState } from "react";

import {
  buildSocialShareLinks,
  isNativeShareSupported,
  type SocialShareLinks,
} from "../lib/share";

type UseShareLinksOptions = {
  shareUrl: string;
  text?: string;
};

export type UseShareLinksResult = {
  socialLinks: SocialShareLinks;
  supportsNativeShare: boolean;
};

/**
 * SNS 共有 URL の組み立てと Web Share 対応の判定を 1 か所にまとめ、画面間でずれないようにする。
 *
 * Keep social URL derivation and Web Share capability checks consistent.
 */
export function useShareLinks({ shareUrl, text = "" }: UseShareLinksOptions): UseShareLinksResult {
  const socialLinks = useMemo(
    () => buildSocialShareLinks(shareUrl, text),
    [shareUrl, text],
  );
  // Web Share API はブラウザにしか存在しないため、SSR時は常にfalseで描画し、
  // hydration後のeffectで能力を反映する。初回HTMLとクライアントHTMLの不一致を防ぐ。
  // The Web Share API only exists in a browser. Render false during SSR and resolve
  // capability after hydration so the initial server/client markup always matches.
  const [supportsNativeShare, setSupportsNativeShare] = useState(false);

  useEffect(() => {
    setSupportsNativeShare(isNativeShareSupported());
  }, []);

  return {
    socialLinks,
    supportsNativeShare,
  };
}
