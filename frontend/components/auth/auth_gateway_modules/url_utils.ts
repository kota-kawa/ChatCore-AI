// nextパラメータのパスをサニタイズし、オープンリダイレクト攻撃を防ぐ
// Sanitize the next parameter path to prevent open redirect attacks
export function sanitizeNextPath(rawNextPath: string | null): string {
  if (!rawNextPath) return "/";
  if (!rawNextPath.startsWith("/")) return "/";

  try {
    const targetUrl = new URL(rawNextPath, window.location.origin);
    // 異なるオリジンへのリダイレクトは禁止する
    // Disallow redirects to different origins
    if (targetUrl.origin !== window.location.origin) {
      return "/";
    }
    return `${targetUrl.pathname}${targetUrl.search}${targetUrl.hash}` || "/";
  } catch {
    return "/";
  }
}

// 現在のURLのクエリパラメータを取得する
// Get the query parameters of the current URL
export function getSearchParams(): URLSearchParams {
  if (typeof window === "undefined") {
    return new URLSearchParams();
  }
  return new URLSearchParams(window.location.search);
}

// 認証後のリダイレクト先パスをクエリパラメータから取得する
// Get the post-authentication redirect path from query parameters
export function getPostAuthRedirectPath(): string {
  return sanitizeNextPath(getSearchParams().get("next"));
}

// Googleログイン用URLを構築する（nextパラメータを引き継ぐ）
// Build the Google login URL (carrying over the next parameter)
export function buildGoogleLoginUrl(): string {
  const nextPath = getPostAuthRedirectPath();
  if (nextPath === "/") {
    return "/google-login";
  }
  return `/google-login?${new URLSearchParams({ next: nextPath }).toString()}`;
}
