import type { ChatMessagePart } from "./types";
import { normalizeMessagePartsForDisplay } from "./message_parts_display";

// Only this exact fence can start the generative-UI loading state. Legacy aliases
// are still hidden from streamed prose below so malformed model output does not
// expose its raw payload, but they are never treated as a UI being generated.
const ARTIFACT_FENCE_NAME = "chatcore-artifact";
const PROBABLE_ARTIFACT_FENCE_NAMES = [
  "chatcore[\\s_-]*artifact",
  "generative[\\s_-]*ui",
  "ui[\\s_-]*artifact",
].join("|");
// 選択ボタンは生成UIではないためローダーの対象にしないが、JSON を本文に見せないよう同じく隠す。
// Choice buttons are not a generated UI, so they never drive the loader, but their JSON is
// hidden from the prose all the same.
const CHOICE_BUTTONS_FENCE_NAMES = [
  "chatcore[\\s_-]*buttons",
  "interactive[\\s_-]*buttons",
].join("|");
const HIDDEN_FENCE_NAMES = `${PROBABLE_ARTIFACT_FENCE_NAMES}|${CHOICE_BUTTONS_FENCE_NAMES}`;
const COMPLETE_HIDDEN_FENCE_RE = new RegExp(
  "```[ \\t]*(?:" + HIDDEN_FENCE_NAMES + ")\\b[^\\n]*\\n[\\s\\S]*?```",
  "gi",
);
const HIDDEN_FENCE_START_RE = new RegExp(
  "```[ \\t]*(?:" + HIDDEN_FENCE_NAMES + ")\\b[^\\n]*(?:\\n|$)",
  "gi",
);
const ARTIFACT_FENCE_START_RE = new RegExp(
  "```[ \\t]*" + ARTIFACT_FENCE_NAME + "(?:\\s+json)?[ \\t]*(?:\\n|$)",
  "i",
);
const PROBABLE_FENCE_START_RE = new RegExp(
  "```[ \\t]*(?:" + PROBABLE_ARTIFACT_FENCE_NAMES + ")\\b[^\\n]*(?:\\n|$)",
  "i",
);
export function stripGenerativeUiFencesForStreaming(text: string) {
  const normalized = String(text || "").replace(/\r\n?/g, "\n");
  let stripped = normalized.replace(COMPLETE_HIDDEN_FENCE_RE, "\n\n");

  let incompleteFenceStart = -1;
  HIDDEN_FENCE_START_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = HIDDEN_FENCE_START_RE.exec(stripped)) !== null) {
    incompleteFenceStart = match.index;
  }

  if (incompleteFenceStart >= 0) {
    stripped = stripped.slice(0, incompleteFenceStart);
  }

  return stripped.replace(/\n{3,}/g, "\n\n").trimEnd();
}

// フェンスを取り除いた本文のみを返す。生成UIの進行はテキストではなく
// 専用ローダー（GenerativeUiLoader）で可視化する。
// Return only the prose with fences stripped; generative UI progress is
// visualized by the dedicated loader (GenerativeUiLoader), not by text.
export function getStreamingGenerativeUiDisplayText(text: string) {
  return stripGenerativeUiFencesForStreaming(text);
}

// ストリーム中のテキストに生成UIフェンスの開始が含まれるかを判定する
// Detect whether the streamed text contains the start of a generative UI fence
export function hasGenerativeUiFenceStart(text: string) {
  const normalized = String(text || "").replace(/\r\n?/g, "\n");
  return ARTIFACT_FENCE_START_RE.test(normalized);
}

// 近似フェンス（```generative-ui など）は実行できないが、本文からは隠している。
// 何も出さないと本文だけが消えたように見えるため、ローダーの対象としては同じに扱い、
// 最終的な成否は artifact_status で伝える。
// A probable fence (```generative-ui and friends) cannot execute, yet it is hidden from the
// prose. Showing nothing made the body look like it vanished, so it drives the loader too and
// the final outcome is delivered by artifact_status.
export function generativeUiFenceKind(text: string): "exact" | "probable" | null {
  const normalized = String(text || "").replace(/\r\n?/g, "\n");
  if (ARTIFACT_FENCE_START_RE.test(normalized)) return "exact";
  return PROBABLE_FENCE_START_RE.test(normalized) ? "probable" : null;
}

// 生成UIの作成中（フェンスは始まったが、描画可能なパーツがまだ届いていない）かを判定する
// Whether a generative UI is still being produced: a fence has started but no
// renderable non-text part has arrived yet.
export function isGenerativeUiPending(text: string, parts?: ChatMessagePart[]) {
  if (generativeUiFenceKind(text) === null) return false;
  return !parts?.some((part) => part.type !== "text");
}

// 確定済みのテキストパーツが全文の先頭に順に並んでいれば、その直後の位置を返す。
// パーツはトレースと本文の間の改行や空白だけの区間を落として届くため、パーツの境目に
// ある全文側の空白は読み飛ばして照合する。
// Return the offset right after the committed text parts when they lead the full
// text in order. Parts arrive without the newlines between the trace and the answer
// or whitespace-only spans, so full-text whitespace at each part boundary is skipped.
function findCommittedTextEnd(text: string, committedSegments: string[]): number | null {
  let cursor = 0;
  for (const segment of committedSegments) {
    if (!text.startsWith(segment, cursor)) {
      while (cursor < text.length && /\s/.test(text[cursor])) cursor += 1;
      if (!text.startsWith(segment, cursor)) return null;
    }
    cursor += segment.length;
  }
  return cursor;
}

export function updateStreamingTextPart(
  parts: ChatMessagePart[] | undefined,
  text: string,
): ChatMessagePart[] | undefined {
  if (!parts || parts.length === 0) return undefined;

  const cloned = parts.map((part) => ({ ...part })) as ChatMessagePart[];
  const textIndices = cloned.reduce<number[]>(
    (indices, part, index) => (part.type === "text" ? [...indices, index] : indices),
    [],
  );
  if (textIndices.length > 0) {
    const lastTextIndex = textIndices[textIndices.length - 1];
    // 画像で区切られた前半のテキストは確定済み。最後のテキストだけを
    // 現在の全文の残りで更新し、画像の挿入位置をストリーム中も維持する。
    // Text before an image is already committed. Update only the final text
    // segment with the suffix of the current full response so image positions
    // remain stable while the stream grows.
    const committedSegments = textIndices
      .slice(0, -1)
      .map((index) => cloned[index].type === "text" ? cloned[index].text : "");
    const committedEnd = committedSegments.join("") ? findCommittedTextEnd(text, committedSegments) : null;
    const nextText = committedEnd === null ? text : text.slice(committedEnd).replace(/^\n+/, "");
    cloned[lastTextIndex] = { type: "text", text: nextText };
    return normalizeMessagePartsForDisplay(cloned);
  }

  if (!text) return cloned;
  return normalizeMessagePartsForDisplay([{ type: "text", text }, ...cloned]);
}
