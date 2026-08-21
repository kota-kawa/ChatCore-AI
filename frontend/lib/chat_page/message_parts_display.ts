import type { ChatMessagePart } from "./types";

// アシスタントメッセージのパーツ表示順を決める規約。services/message_parts_display.py と
// 同じ規則を保つ: 生成UIとWeb検索画像は1ターン内で排他、画像は最大5枚まで保持し、
// 画像パーツの挿入位置は周囲のテキストとの順序を保つ。
// The display ordering contract for assistant message parts, mirroring
// services/message_parts_display.py: a generated UI and web-search images are
// mutually exclusive within one turn, up to five images preserve their authored
// inline position relative to the surrounding text.
export const ANSWER_TRACE_DETAILS_CLASS = "web-search-sources web-search-sources--trace";
export const MAX_WEB_SEARCH_IMAGES_PER_REPLY = 5;

const TRACE_BLOCK_START = `<details class="${ANSWER_TRACE_DETAILS_CLASS}"`;
// トレース内部にもステップ用の <details> が入れ子になるため、開閉を数えて末尾を探す。
// Steps nest their own <details>, so the block end is found by counting tags.
const DETAILS_TAG_PATTERN = "<details\\b|</details\\s*>";

function isGenerativeUiPart(part: ChatMessagePart) {
  return part.type === "sandbox_artifact" || part.type === "interactive_buttons";
}

// 先頭にある回答トレースブロックを本文から切り離す
// Split a leading answer-trace block off the text
export function splitAnswerTraceBlock(text: string): { trace: string; remainder: string } {
  if (!text) return { trace: "", remainder: text ?? "" };
  const stripped = text.replace(/^\s+/, "");
  if (!stripped.startsWith(TRACE_BLOCK_START)) return { trace: "", remainder: text };

  const offset = text.length - stripped.length;
  const tagPattern = new RegExp(DETAILS_TAG_PATTERN, "gi");
  let depth = 0;
  let match = tagPattern.exec(stripped);
  while (match !== null) {
    depth += match[0].toLowerCase().startsWith("<details") ? 1 : -1;
    if (depth === 0) {
      const end = offset + match.index + match[0].length;
      return { trace: text.slice(0, end), remainder: text.slice(end).replace(/^\n+/, "") };
    }
    match = tagPattern.exec(stripped);
  }
  return { trace: "", remainder: text };
}

// 視覚パーツの排他規約を適用し、最大5枚の画像を本文より前に置く
// Enforce visual exclusivity and keep up to five images ahead of the explanation
export function applyVisualPartContract(parts: ChatMessagePart[]): ChatMessagePart[] {
  if (parts.some(isGenerativeUiPart)) {
    return parts.filter((part) => part.type !== "web_search_image");
  }
  let imageCount = 0;
  return parts.filter((part) => {
    if (part.type !== "web_search_image") return true;
    if (imageCount >= MAX_WEB_SEARCH_IMAGES_PER_REPLY) return false;
    imageCount += 1;
    return true;
  });
}

// 表示規約を適用する。回答トレースは独立したテキストパートへ切り出し、
// 旧形式でトレースより前に保存された画像だけをトレース直下へ移す。
// Apply the display contract, splitting the answer trace into its own text part.
// Only legacy images saved before the trace are moved below that trace.
export function normalizeMessagePartsForDisplay(parts: ChatMessagePart[]): ChatMessagePart[] {
  const contracted = applyVisualPartContract(parts);
  if (!contracted.some((part) => part.type === "web_search_image")) return contracted;
  const firstTextIndex = contracted.findIndex((part) => part.type === "text");
  if (firstTextIndex < 0) return contracted;

  const head = contracted[firstTextIndex];
  if (head.type !== "text") return contracted;
  const { trace, remainder } = splitAnswerTraceBlock(head.text);
  if (!trace) return contracted;

  const prefixParts = contracted.slice(0, firstTextIndex);
  const suffixParts = contracted.slice(firstTextIndex + 1);
  const headParts: ChatMessagePart[] = [{ type: "text", text: trace }, ...prefixParts];
  if (remainder.trim()) headParts.push({ type: "text", text: remainder });
  return [...headParts, ...suffixParts];
}
