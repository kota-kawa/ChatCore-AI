import type { ChatMessagePart } from "./types";
import { normalizeMessagePartsForDisplay } from "./message_parts_display";

// Only this exact fence can start the generative-UI loading state. Legacy aliases
// are still hidden from streamed prose below so malformed model output does not
// expose its raw payload, but they are never treated as a UI being generated.
const ARTIFACT_FENCE_NAME = "chatcore-artifact";
const HIDDEN_GENERATIVE_UI_FENCE_NAMES = [
  "chatcore[\\s_-]*artifact",
  "generative[\\s_-]*ui",
  "ui[\\s_-]*artifact",
  "chatcore[\\s_-]*buttons",
  "interactive[\\s_-]*buttons",
].join("|");
const COMPLETE_GENERATIVE_UI_FENCE_RE = new RegExp(
  "```[ \\t]*(?:" + HIDDEN_GENERATIVE_UI_FENCE_NAMES + ")\\b[^\\n]*\\n[\\s\\S]*?```",
  "gi",
);
const HIDDEN_GENERATIVE_UI_FENCE_START_RE = new RegExp(
  "```[ \\t]*(?:" + HIDDEN_GENERATIVE_UI_FENCE_NAMES + ")\\b[^\\n]*(?:\\n|$)",
  "gi",
);
const ARTIFACT_FENCE_START_RE = new RegExp(
  "```[ \\t]*" + ARTIFACT_FENCE_NAME + "(?:\\s+json)?[ \\t]*(?:\\n|$)",
  "i",
);
export function stripGenerativeUiFencesForStreaming(text: string) {
  const normalized = String(text || "").replace(/\r\n?/g, "\n");
  let stripped = normalized.replace(COMPLETE_GENERATIVE_UI_FENCE_RE, "\n\n");

  let incompleteFenceStart = -1;
  HIDDEN_GENERATIVE_UI_FENCE_START_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = HIDDEN_GENERATIVE_UI_FENCE_START_RE.exec(stripped)) !== null) {
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

// 生成UIの作成中（フェンスは始まったが、描画可能なパーツがまだ届いていない）かを判定する
// Whether a generative UI is still being produced: a fence has started but no
// renderable non-text part has arrived yet.
export function isGenerativeUiPending(text: string, parts?: ChatMessagePart[]) {
  if (!hasGenerativeUiFenceStart(text)) return false;
  return !parts?.some((part) => part.type !== "text");
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
    const committedText = textIndices
      .slice(0, -1)
      .map((index) => cloned[index].type === "text" ? cloned[index].text : "")
      .join("");
    let nextText = text;
    if (committedText && text.startsWith(committedText)) {
      nextText = text.slice(committedText.length).replace(/^\n+/, "");
    }
    cloned[lastTextIndex] = { type: "text", text: nextText };
    return normalizeMessagePartsForDisplay(cloned);
  }

  if (!text) return cloned;
  return normalizeMessagePartsForDisplay([{ type: "text", text }, ...cloned]);
}
