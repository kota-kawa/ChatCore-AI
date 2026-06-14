const URL_RE = /https?:\/\/[^\s<>"'`()\[\]{}|\\^]+/gi;
const MAX_DETECTED_URLS = 3;

/**
 * テキストからURLを抽出する
 * Extract URLs from text
 */
export function extractUrlsFromText(text: string): string[] {
  // 正規表現にマッチしたURLを取得。ない場合は空配列を返す
  // Get matched URLs. Return an empty array if none
  const matches = text.match(URL_RE) ?? [];
  const seen = new Set<string>();
  const result: string[] = [];
  
  for (const raw of matches) {
    // 末尾の不要な記号を削除する
    // Remove trailing punctuation marks
    const url = raw.replace(/[.,;:!?)\]]+$/, "");
    if (!seen.has(url)) {
      seen.add(url);
      result.push(url);
    }
    // 上限に達したら終了する
    // Stop if the maximum limit is reached
    if (result.length >= MAX_DETECTED_URLS) break;
  }
  return result;
}

/**
 * URLからドメイン名を取得する
 * Get the domain name from a URL
 */
export function getUrlDomain(url: string): string {
  try {
    // URLオブジェクトを使ってホスト名を取得し、'www.' を取り除く
    // Get the hostname using URL object and remove 'www.'
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    // URLのパースに失敗した場合は、文字列の一部を返す
    // If URL parsing fails, return a substring
    return url.slice(0, 40);
  }
}
