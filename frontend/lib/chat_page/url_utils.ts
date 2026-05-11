const URL_RE = /https?:\/\/[^\s<>"'`()\[\]{}|\\^]+/gi;
const MAX_DETECTED_URLS = 3;

export function extractUrlsFromText(text: string): string[] {
  const matches = text.match(URL_RE) ?? [];
  const seen = new Set<string>();
  const result: string[] = [];
  for (const raw of matches) {
    const url = raw.replace(/[.,;:!?)\]]+$/, "");
    if (!seen.has(url)) {
      seen.add(url);
      result.push(url);
    }
    if (result.length >= MAX_DETECTED_URLS) break;
  }
  return result;
}

export function getUrlDomain(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url.slice(0, 40);
  }
}
