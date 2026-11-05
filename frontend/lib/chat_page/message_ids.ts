// ローカルで作るチャットメッセージの一意な ID を採番する。
// Generates unique ids for locally created chat messages.
import type { MutableRefObject } from "react";

// プレフィックス、時刻、連番を組み合わせる。連番は呼び出し側の ref で持つので、同じミリ秒内でも重ならない。
// Combines the prefix, the time, and a counter; the counter lives in the caller's ref, so ids stay unique within the same millisecond.
export function nextMessageId(prefix: string, seqRef: MutableRefObject<number>) {
  seqRef.current += 1;
  return `${prefix}-${Date.now()}-${seqRef.current}`;
}
