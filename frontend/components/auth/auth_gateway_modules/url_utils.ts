export function sanitizeNextPath(rawNextPath: string | null): string {
  if (!rawNextPath) return "/";
  if (!rawNextPath.startsWith("/")) return "/";

  try {
    const targetUrl = new URL(rawNextPath, window.location.origin);
    if (targetUrl.origin !== window.location.origin) {
      return "/";
    }
    return `${targetUrl.pathname}${targetUrl.search}${targetUrl.hash}` || "/";
  } catch {
    return "/";
  }
}

export function getSearchParams(): URLSearchParams {
  if (typeof window === "undefined") {
    return new URLSearchParams();
  }
  return new URLSearchParams(window.location.search);
}

export function getPostAuthRedirectPath(): string {
  return sanitizeNextPath(getSearchParams().get("next"));
}

export function buildGoogleLoginUrl(): string {
  const nextPath = getPostAuthRedirectPath();
  if (nextPath === "/") {
    return "/google-login";
  }
  return `/google-login?${new URLSearchParams({ next: nextPath }).toString()}`;
}
