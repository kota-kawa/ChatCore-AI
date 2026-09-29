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
// 一部モデルはフェンスの代わりに <chatcore_button>/<chatcore_buttons> タグでJSONを包むため、
// バックエンドの services/interactive_buttons.py と同じタグ名をストリーミング中も隠す。
// Choice buttons are not a generated UI, so they never drive the loader, but their JSON is
// hidden from the prose all the same. Some models wrap the JSON in <chatcore_button>/
// <chatcore_buttons> tags instead of a fence; those tag names mirror the backend's
// services/interactive_buttons.py and are hidden from the stream the same way.
const CHOICE_BUTTONS_FENCE_NAMES = [
  "chatcore[\\s_-]*buttons",
  "interactive[\\s_-]*buttons",
].join("|");
const CHOICE_BUTTONS_TAG_NAME = "chatcore_buttons?";
const HIDDEN_FENCE_NAMES = `${PROBABLE_ARTIFACT_FENCE_NAMES}|${CHOICE_BUTTONS_FENCE_NAMES}`;
const COMPLETE_HIDDEN_FENCE_RE = new RegExp(
  "```[ \\t]*(?:" + HIDDEN_FENCE_NAMES + ")\\b[^\\n]*\\n[\\s\\S]*?```",
  "gi",
);
const HIDDEN_FENCE_START_RE = new RegExp(
  "```[ \\t]*(?:" + HIDDEN_FENCE_NAMES + ")\\b[^\\n]*(?:\\n|$)",
  "gi",
);
// 閉じタグは単数形・複数形のどちらでも閉じたとみなす。開きタグは ">" 到着前から隠す。
// Either closing tag name ends a block. Hide an opening tag even before its ">" arrives.
const COMPLETE_TAG_OPEN_RE = /<chatcore_buttons?>/gi;
const HIDDEN_TAG_START_RE = new RegExp(
  "<" + CHOICE_BUTTONS_TAG_NAME + "\\b[^>]*(?:>|$)",
  "gi",
);

function isEscaped(source: string, index: number): boolean {
  let backslashes = 0;
  for (let cursor = index - 1; cursor >= 0 && source[cursor] === "\\"; cursor -= 1) backslashes += 1;
  return backslashes % 2 === 1;
}

function isInsideMarkdownCode(text: string, position: number): boolean {
  if (position < 0 || position >= text.length) return false;

  const fencedRanges: Array<{ start: number; end: number }> = [];
  const fencedOpeningLines: Array<{ start: number; end: number }> = [];
  let fenceStart: number | null = null;
  let fenceCharacter: "`" | "~" | null = null;
  let fenceLength = 0;
  let lineStart = 0;
  while (lineStart < text.length) {
    const newline = text.indexOf("\n", lineStart);
    const lineEnd = newline < 0 ? text.length : newline + 1;
    const line = text.slice(lineStart, lineEnd).replace(/\r?\n$/, "");
    const fence = /^ {0,3}(`{3,}|~{3,})/.exec(line);

    if (fenceCharacter) {
      if (fence) {
        const marker = fence[1];
        const rest = line.slice(fence[0].length);
        if (marker[0] === fenceCharacter && marker.length >= fenceLength && !rest.trim()) {
          if (fenceStart !== null) fencedRanges.push({ start: fenceStart, end: lineEnd });
          fenceStart = null;
          fenceCharacter = null;
          fenceLength = 0;
        }
      }
    } else if (fence) {
      fenceStart = lineStart;
      fencedOpeningLines.push({ start: lineStart, end: lineEnd });
      fenceCharacter = fence[1][0] as "`" | "~";
      fenceLength = fence[1].length;
    }

    lineStart = lineEnd;
  }

  if (fenceStart !== null) fencedRanges.push({ start: fenceStart, end: text.length });
  if (fencedOpeningLines.some(({ start, end }) => start <= position && position < end)) return false;
  if (fencedRanges.some(({ start, end }) => start <= position && position < end)) return true;

  const fenceEndAt = (offset: number) => fencedRanges.find(({ start, end }) => start <= offset && offset < end)?.end;
  const delimiter = /`+/g;
  let cursor = 0;
  while (cursor < text.length) {
    const activeFenceEnd = fenceEndAt(cursor);
    if (activeFenceEnd !== undefined) {
      cursor = activeFenceEnd;
      continue;
    }

    delimiter.lastIndex = cursor;
    const opening = delimiter.exec(text);
    if (!opening) return false;
    const openingFenceEnd = fenceEndAt(opening.index);
    if (openingFenceEnd !== undefined) {
      cursor = openingFenceEnd;
      continue;
    }
    if (isEscaped(text, opening.index)) {
      cursor = delimiter.lastIndex;
      continue;
    }

    const delimiterLength = opening[0].length;
    let searchCursor = delimiter.lastIndex;
    let foundClosing = false;
    while (searchCursor < text.length) {
      delimiter.lastIndex = searchCursor;
      const closing = delimiter.exec(text);
      if (!closing) break;
      const closingFenceEnd = fenceEndAt(closing.index);
      if (closingFenceEnd !== undefined) {
        searchCursor = closingFenceEnd;
        continue;
      }
      if (isEscaped(text, closing.index) || closing[0].length !== delimiterLength) {
        searchCursor = delimiter.lastIndex;
        continue;
      }
      if (opening.index + delimiterLength <= position && position < closing.index) return true;
      cursor = delimiter.lastIndex;
      foundClosing = true;
      break;
    }
    if (!foundClosing) cursor = opening.index + delimiterLength;
  }

  return false;
}

function choiceJsonEnd(text: string, start: number): number | null {
  let index = start;
  while (/\s/.test(text[index] ?? "") && index < text.length) index += 1;
  if (text[index] !== "{") return null;
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (; index < text.length; index += 1) {
    const char = text[index];
    if (inString) {
      if (escaped) escaped = false;
      else if (char === "\\") escaped = true;
      else if (char === '"') inString = false;
      continue;
    }
    if (char === '"') inString = true;
    else if (char === "{") depth += 1;
    else if (char === "}" && --depth === 0) return index + 1;
  }
  return null;
}

function isInsideJsonString(text: string, start: number, end: number): boolean {
  let index = start;
  while (/\s/.test(text[index] ?? "") && index < end) index += 1;
  if (text[index] !== "{") return false;
  let inString = false;
  let escaped = false;
  for (; index < end; index += 1) {
    const char = text[index];
    if (inString) {
      if (escaped) escaped = false;
      else if (char === "\\") escaped = true;
      else if (char === '"') inString = false;
    } else if (char === '"') {
      inString = true;
    }
  }
  return inString;
}

function findMalformedChoiceClose(text: string, start: number): number {
  const closeMatcher = /<\/chatcore_buttons?>/gi;
  closeMatcher.lastIndex = start;
  let close: RegExpExecArray | null;
  while ((close = closeMatcher.exec(text)) !== null) {
    if (isInsideMarkdownCode(text, close.index)) continue;
    const lineStart = text.lastIndexOf("\n", close.index - 1) + 1;
    const startsLine = !text.slice(lineStart, close.index).trim();
    const closeEnd = close.index + close[0].length;
    if (startsLine || !isInsideJsonString(text, start, close.index)) return closeEnd;
  }
  return -1;
}

function stripChoiceTagsForStreaming(text: string): string {
  let stripped = "";
  let cursor = 0;
  COMPLETE_TAG_OPEN_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = COMPLETE_TAG_OPEN_RE.exec(text)) !== null) {
    if (isInsideMarkdownCode(text, match.index)) continue;
    stripped += text.slice(cursor, match.index);
    const jsonEnd = choiceJsonEnd(text, COMPLETE_TAG_OPEN_RE.lastIndex);
    if (jsonEnd === null) {
      const nextOpen = /(?:^|\n)[ \t]*<chatcore_buttons?>/gi;
      nextOpen.lastIndex = COMPLETE_TAG_OPEN_RE.lastIndex;
      let later = nextOpen.exec(text);
      while (later && isInsideMarkdownCode(text, later.index + later[0].lastIndexOf("<"))) {
        later = nextOpen.exec(text);
      }
      const closeEnd = findMalformedChoiceClose(text, COMPLETE_TAG_OPEN_RE.lastIndex);
      if (closeEnd >= 0 && (!later || closeEnd < later.index + later[0].lastIndexOf("<"))) {
        cursor = closeEnd;
        while (/[ \t]/.test(text[cursor] ?? "")) cursor += 1;
        stripped += "\n\n";
        COMPLETE_TAG_OPEN_RE.lastIndex = cursor;
        continue;
      }
      if (!later) return stripped;
      const nextTag = later.index + later[0].lastIndexOf("<");
      cursor = nextTag;
      let lineStart = text.indexOf("\n", COMPLETE_TAG_OPEN_RE.lastIndex) + 1;
      while (lineStart > 0 && lineStart < nextTag) {
        const lineEnd = text.indexOf("\n", lineStart);
        const line = text.slice(lineStart, lineEnd < 0 ? nextTag : Math.min(lineEnd, nextTag)).trim();
        const looksLikeJsonLine =
          ["{", "}", "[", "]", ",", ":", '"'].some((prefix) => line.startsWith(prefix)) ||
          /^(?:true|false|null|-?\d+(?:\.\d+)?)\s*[,}\]]?$/.test(line);
        if (line && !looksLikeJsonLine) {
          cursor = lineStart;
          break;
        }
        lineStart = lineEnd < 0 ? nextTag : lineEnd + 1;
      }
      stripped += "\n\n";
      COMPLETE_TAG_OPEN_RE.lastIndex = nextTag;
      continue;
    }
    let afterJson = jsonEnd;
    while (/\s/.test(text[afterJson] ?? "") && afterJson < text.length) afterJson += 1;
    const close = /^<\/chatcore_buttons?>/i.exec(text.slice(afterJson));
    cursor = close ? afterJson + close[0].length : jsonEnd;
    stripped += "\n\n";
    COMPLETE_TAG_OPEN_RE.lastIndex = cursor;
  }
  return stripped + text.slice(cursor);
}
const ARTIFACT_FENCE_START_RE = new RegExp(
  "```[ \\t]*" + ARTIFACT_FENCE_NAME + "(?:\\s+json)?[ \\t]*(?:\\n|$)",
  "i",
);
const PROBABLE_FENCE_START_RE = new RegExp(
  "```[ \\t]*(?:" + PROBABLE_ARTIFACT_FENCE_NAMES + ")\\b[^\\n]*(?:\\n|$)",
  "i",
);
function findLastMatchIndexOutsideMarkdownCode(re: RegExp, text: string): number {
  re.lastIndex = 0;
  let lastIndex = -1;
  let match: RegExpExecArray | null;
  while ((match = re.exec(text)) !== null) {
    if (!isInsideMarkdownCode(text, match.index)) lastIndex = match.index;
  }
  return lastIndex;
}

function findLastChoiceTagStartIndex(text: string): number {
  HIDDEN_TAG_START_RE.lastIndex = 0;
  let lastIndex = -1;
  let match: RegExpExecArray | null;
  while ((match = HIDDEN_TAG_START_RE.exec(text)) !== null) {
    if (!isInsideMarkdownCode(text, match.index)) lastIndex = match.index;
  }
  return lastIndex;
}

export function stripGenerativeUiFencesForStreaming(text: string) {
  const normalized = String(text || "").replace(/\r\n?/g, "\n");
  const withoutCompleteFences = normalized.replace(COMPLETE_HIDDEN_FENCE_RE, (match, offset: number) =>
    isInsideMarkdownCode(normalized, offset) ? match : "\n\n",
  );
  let stripped = stripChoiceTagsForStreaming(withoutCompleteFences);

  const fenceStart = findLastMatchIndexOutsideMarkdownCode(HIDDEN_FENCE_START_RE, stripped);
  const tagStart = findLastChoiceTagStartIndex(stripped);
  const candidateStarts = [fenceStart, tagStart].filter((index) => index >= 0);
  const incompleteFenceStart = candidateStarts.length > 0 ? Math.min(...candidateStarts) : -1;

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

// Keep the message parts in the same sanitized state as the fallback prose. Text
// parts are scanned cumulatively so a hidden block split across adjacent parts
// cannot leak its tail after an image or another non-text part.
export function sanitizeTextPartsForStreaming(parts: ChatMessagePart[] | undefined) {
  if (!parts) return undefined;

  const sanitized = parts.map((part) => (part.type === "text" ? { ...part, text: "" } : { ...part }));
  const textPartIndices: number[] = [];
  let rawText = "";
  let visibleText = "";

  parts.forEach((part, index) => {
    if (part.type !== "text") return;
    rawText += part.text;
    const nextVisibleText = getStreamingGenerativeUiDisplayText(rawText);
    if (nextVisibleText.startsWith(visibleText)) {
      sanitized[index] = { type: "text", text: nextVisibleText.slice(visibleText.length) };
    } else {
      // A sanitizer decision can change when a later part closes an unfinished
      // block. In that case keep the safe cumulative result once, at this point.
      for (const previousIndex of textPartIndices) {
        sanitized[previousIndex] = { type: "text", text: "" };
      }
      sanitized[index] = { type: "text", text: nextVisibleText };
    }
    textPartIndices.push(index);
    visibleText = nextVisibleText;
  });

  return sanitized;
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
