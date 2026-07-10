import type { ChatMessagePart } from "./types";

const GENERATIVE_UI_FENCE_NAMES = [
  "chatcore[\\s_-]*artifact",
  "generative[\\s_-]*ui",
  "ui[\\s_-]*artifact",
  "chatcore[\\s_-]*buttons",
  "interactive[\\s_-]*buttons",
].join("|");
const COMPLETE_GENERATIVE_UI_FENCE_RE = new RegExp(
  "```[ \\t]*(?:" + GENERATIVE_UI_FENCE_NAMES + ")\\b[^\\n]*\\n[\\s\\S]*?```",
  "gi",
);
const GENERATIVE_UI_FENCE_START_RE = new RegExp(
  "```[ \\t]*(?:" + GENERATIVE_UI_FENCE_NAMES + ")\\b[^\\n]*(?:\\n|$)",
  "gi",
);
export function stripGenerativeUiFencesForStreaming(text: string) {
  const normalized = String(text || "").replace(/\r\n?/g, "\n");
  let stripped = normalized.replace(COMPLETE_GENERATIVE_UI_FENCE_RE, "\n\n");

  let incompleteFenceStart = -1;
  GENERATIVE_UI_FENCE_START_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = GENERATIVE_UI_FENCE_START_RE.exec(stripped)) !== null) {
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
  GENERATIVE_UI_FENCE_START_RE.lastIndex = 0;
  return GENERATIVE_UI_FENCE_START_RE.test(normalized);
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
  const firstTextIndex = cloned.findIndex((part) => part.type === "text");
  if (firstTextIndex >= 0) {
    cloned[firstTextIndex] = { type: "text", text };
    return cloned;
  }

  if (!text) return cloned;
  return [{ type: "text", text }, ...cloned];
}
