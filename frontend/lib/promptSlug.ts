// プロンプトのタイトルからSEOに適したURLスラッグを生成し、個別共有ページのパスを組み立てるユーティリティ。
// Utilities to build an SEO-friendly URL slug from a prompt title and assemble the individual shared page path.

// スラッグの最大長（URLが過度に長くなるのを防ぐ）。バイト数ではなく文字数で制限する。
// Maximum slug length (prevents overly long URLs). Limited by character count, not bytes.
export const MAX_PROMPT_SLUG_LENGTH = 80;

// 共有プロンプト個別ページのベースパス。
// Base path for the individual shared prompt page.
const SHARED_PROMPT_BASE_PATH = "/shared/prompt";

// 制御文字（C0範囲とDEL）にマッチする正規表現。リテラルに制御文字を埋め込まないよう明示的に構築する。
// Matches control characters (C0 range and DEL). Built explicitly to avoid embedding raw control characters in source.
const CONTROL_CHARS = new RegExp("[\\u0000-\\u001f\\u007f]+", "g");

// URLで問題になりうる記号・区切り文字にマッチする正規表現。
// Matches punctuation and delimiters that are problematic in URLs.
const URL_UNSAFE_CHARS = /[\\/?#[\]@!$&'()*+,;=:"<>{}|^`~%.]+/g;

// タイトルからURLスラッグを生成する。日本語などの非ASCII文字は保持し（ブラウザでデコード表示されSEOに有効）、
// 記号や空白はハイフンに正規化する。生成結果はパーセントエンコードされていない「生」の文字列。
// Build a URL slug from a title. Non-ASCII characters such as Japanese are kept
// (browsers display them decoded, which helps SEO); symbols and whitespace are normalized to hyphens.
// The returned value is the raw (non-percent-encoded) slug.
export function buildPromptSlug(title: string | null | undefined): string {
  if (!title) return "";
  const slug = title
    .normalize("NFKC")
    .toLowerCase()
    // 制御文字を空白へ / Replace control characters with spaces
    .replace(CONTROL_CHARS, " ")
    // URLで問題になる記号・区切り文字を空白へ / Replace URL-sensitive punctuation with spaces
    .replace(URL_UNSAFE_CHARS, " ")
    // 連続する空白をハイフンへ / Collapse whitespace runs into a single hyphen
    .replace(/\s+/g, "-")
    // 連続ハイフンを1つに / Collapse consecutive hyphens
    .replace(/-+/g, "-")
    // 前後のハイフンを除去 / Trim leading and trailing hyphens
    .replace(/^-+|-+$/g, "");
  if (slug.length <= MAX_PROMPT_SLUG_LENGTH) return slug;
  // 最大長で切り詰め、末尾に残ったハイフンを除去 / Truncate to the max length and trim a trailing hyphen
  return slug.slice(0, MAX_PROMPT_SLUG_LENGTH).replace(/-+$/g, "");
}

// プロンプトIDとタイトルから個別共有ページのパスを組み立てる。
// スラッグが生成できない場合はID単体のパスにフォールバックする。
// Build the individual shared page path from a prompt ID and title.
// Falls back to the ID-only path when no slug can be derived.
export function buildPromptPath(id: string | number, title?: string | null): string {
  const encodedId = encodeURIComponent(String(id));
  const slug = buildPromptSlug(title ?? "");
  if (!slug) return `${SHARED_PROMPT_BASE_PATH}/${encodedId}`;
  return `${SHARED_PROMPT_BASE_PATH}/${encodedId}/${encodeURIComponent(slug)}`;
}
