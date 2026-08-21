import type { ChatMessagePart } from "./types";

// アシスタントメッセージのパーツ表示順を決める規約。services/message_parts_display.py と
// 同じ規則を保つ: 生成UIとWeb検索画像は1ターン内で排他、画像は「回答までのステップ」
// （回答トレース）の直下・本文の上に置く。
// The display ordering contract for assistant message parts, mirroring
// services/message_parts_display.py: a generated UI and a web-search image are
// mutually exclusive within one turn, and the image belongs directly below the
// answer-trace block ("回答までのステップ") and above the explanation.
export const ANSWER_TRACE_DETAILS_CLASS = "web-search-sources web-search-sources--trace";

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

// 視覚パーツの排他規約を適用し、画像を本文より前に置く
// Enforce visual exclusivity and keep the image ahead of the explanation
export function applyVisualPartContract(parts: ChatMessagePart[]): ChatMessagePart[] {
  if (parts.some(isGenerativeUiPart)) {
    return parts.filter((part) => part.type !== "web_search_image");
  }
  const imageParts = parts.filter((part) => part.type === "web_search_image");
  const otherParts = parts.filter((part) => part.type !== "web_search_image");
  return [...imageParts, ...otherParts];
}

// 表示規約を適用する。回答トレースは独立したテキストパートへ切り出し、
// Web検索画像がその下に来るようにする。
// Apply the display contract, splitting the answer trace into its own text part
// so the web-search image renders below it.
export function normalizeMessagePartsForDisplay(parts: ChatMessagePart[]): ChatMessagePart[] {
  const contracted = applyVisualPartContract(parts);
  const imageParts = contracted.filter((part) => part.type === "web_search_image");
  if (imageParts.length === 0) return contracted;

  const otherParts = contracted.filter((part) => part.type !== "web_search_image");
  const head = otherParts[0];
  if (!head || head.type !== "text") return [...imageParts, ...otherParts];

  const { trace, remainder } = splitAnswerTraceBlock(head.text);
  if (!trace) return [...imageParts, ...otherParts];

  const bodyParts: ChatMessagePart[] = remainder.trim() ? [{ type: "text", text: remainder }] : [];
  return [{ type: "text", text: trace }, ...imageParts, ...bodyParts, ...otherParts.slice(1)];
}
