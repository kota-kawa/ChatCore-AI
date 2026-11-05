// 共有先URLとWeb Share APIの共通ロジック。
// Shared social-link and Web Share API primitives used by every share surface.

export type SocialShareLinks = {
  x: string;
  line: string;
  facebook: string;
};

export type NativeSharePayload = {
  title?: string;
  text?: string;
  url: string;
};

// 共有シートの結果。shared は共有済み、cancelled は利用者のキャンセル、unsupported は非対応、failed は失敗。
// Outcome of the share sheet: shared, cancelled by the user, unsupported by the browser, or failed.
export type NativeShareResult = {
  status: "shared" | "cancelled" | "unsupported" | "failed";
  error?: unknown;
};

// 共有する URL が無いときに返す、空のリンク集。
// Empty set of links returned when there is no URL to share.
export const EMPTY_SOCIAL_SHARE_LINKS: SocialShareLinks = {
  x: "",
  line: "",
  facebook: "",
};

/** X・LINE・Facebook の 3 つの外部共有先へのリンクを組み立てる。 */
/** Build links for the three external social sharing destinations. */
export function buildSocialShareLinks(shareUrl: string, text = ""): SocialShareLinks {
  const normalizedUrl = shareUrl.trim();
  if (!normalizedUrl) return { ...EMPTY_SOCIAL_SHARE_LINKS };

  const encodedUrl = encodeURIComponent(normalizedUrl);
  const encodedText = text.trim() ? `&text=${encodeURIComponent(text)}` : "";
  return {
    x: `https://twitter.com/intent/tweet?url=${encodedUrl}${encodedText}`,
    line: `https://social-plugins.line.me/lineit/share?url=${encodedUrl}`,
    facebook: `https://www.facebook.com/sharer/sharer.php?u=${encodedUrl}`,
  };
}
/** 現在のブラウザが Web Share API を使えるかを返す。 */
/** Return whether the current browser exposes the Web Share API. */
export function isNativeShareSupported(): boolean {
  return typeof navigator !== "undefined" && typeof navigator.share === "function";
}

/**
 * ネイティブの共有シートを開き、ブラウザごとの結果を統一した形で返す。
 * 利用者が共有をキャンセルするのは通常の結果であり、エラーとしては扱わない。
 *
 * Open the native share sheet and normalize browser outcomes.
 * User cancellation is a normal outcome and is intentionally not an error.
 */
export async function shareWithNativeSheet(payload: NativeSharePayload): Promise<NativeShareResult> {
  if (!isNativeShareSupported()) {
    return { status: "unsupported" };
  }

  try {
    await navigator.share(payload);
    return { status: "shared" };
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      return { status: "cancelled" };
    }
    return { status: "failed", error };
  }
}
