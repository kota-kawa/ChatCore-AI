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

export type NativeShareResult = {
  status: "shared" | "cancelled" | "unsupported" | "failed";
  error?: unknown;
};

export const EMPTY_SOCIAL_SHARE_LINKS: SocialShareLinks = {
  x: "",
  line: "",
  facebook: "",
};

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
/** Return whether the current browser exposes the Web Share API. */
export function isNativeShareSupported(): boolean {
  return typeof navigator !== "undefined" && typeof navigator.share === "function";
}

// Keep descriptive aliases for callers whose state naming follows the UI copy.
export const getNativeShareSupport = isNativeShareSupported;
export const supportsNativeShare = isNativeShareSupported;

/**
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
