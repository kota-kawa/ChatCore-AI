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

/** Keep social URL derivation and Web Share capability checks consistent. */
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
