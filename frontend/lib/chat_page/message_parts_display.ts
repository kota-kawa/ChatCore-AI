// 回答パーツの表示順・排他と件数の共通契約を適用する。
// Applies shared ordering, exclusion and count rules to answer parts.

import { isAnswerTracePart } from "./answer_trace";
import type { ChatMessagePart } from "./types";

// アシスタントメッセージのパーツ表示順を決める規約。services/message_parts_display.py と
// 同じ規則を保つ: 生成UIとWeb検索画像は1ターン内で排他、画像は最大5枚まで保持し、
// 画像パーツの挿入位置は周囲のテキストとの順序を保つ。選択ボタンは生成UIではないので
// この排他に加わらない。実行記録（回答までのステップ）は常に先頭に1つだけ置く。
// The display ordering contract for assistant message parts, mirroring
// services/message_parts_display.py: a generated UI and web-search images are
// mutually exclusive within one turn, up to five images preserve their authored
// inline position relative to the surrounding text. Choice buttons are not a
// generated UI and take no part in that exclusivity. The execution record (the
// steps to the answer) always leads as a single part.
export const MAX_WEB_SEARCH_IMAGES_PER_REPLY = 5;

function isGenerativeUiPart(part: ChatMessagePart) {
  return part.type === "sandbox_artifact";
}

// 視覚パーツの排他規約を適用し、画像は書かれた位置のまま最大5枚だけ残す
// Enforce visual exclusivity and keep at most five images at their authored positions
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

// 表示規約を適用する。視覚パーツの排他に加え、実行記録（構造化・旧形式のどちらか）を先頭へ寄せ、2つ目以降は捨てる。
// Apply the display contract: visual exclusivity, plus the execution record (structured or legacy) moves
// to the head and any second one is dropped.
export function normalizeMessagePartsForDisplay(parts: ChatMessagePart[]): ChatMessagePart[] {
  const contracted = applyVisualPartContract(parts);
  const trace = contracted.find(isAnswerTracePart);
  if (!trace) return contracted;
  return [trace, ...contracted.filter((part) => !isAnswerTracePart(part))];
}
