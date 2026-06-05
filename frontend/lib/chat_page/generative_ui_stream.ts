import type { ChatMessagePart } from "./types";

const GENERATIVE_UI_FENCE_NAMES = [
  "chatcore-artifact",
  "generative-ui",
  "generative_ui",
  "ui_artifact",
  "chatcore-buttons",
  "interactive-buttons",
  "interactive_buttons",
].join("|");
const COMPLETE_GENERATIVE_UI_FENCE_RE = new RegExp(
  "```[ \\t]*(?:" + GENERATIVE_UI_FENCE_NAMES + ")\\b[^\\n]*\\n[\\s\\S]*?```",
  "gi",
);
const GENERATIVE_UI_FENCE_START_RE = new RegExp(
  "```[ \\t]*(?:" + GENERATIVE_UI_FENCE_NAMES + ")\\b[^\\n]*(?:\\n|$)",
  "gi",
);
const GENERATIVE_UI_IN_PROGRESS_TEXT = "生成UIを作成中です...";

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

export function getStreamingGenerativeUiDisplayText(text: string) {
  const stripped = stripGenerativeUiFencesForStreaming(text);
  if (stripped.trim()) return stripped;
  GENERATIVE_UI_FENCE_START_RE.lastIndex = 0;
  return GENERATIVE_UI_FENCE_START_RE.test(text) ? GENERATIVE_UI_IN_PROGRESS_TEXT : stripped;
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
