import { sourceOffsetAtCaret } from "./markdown_source_positions";

export interface MemoEditPosition {
  offset: number | null;
  clientY: number;
  scrollTop: number;
}

export function captureMemoEditPosition(
  root: HTMLElement, source: string, clientX: number, clientY: number, markdown = true,
): MemoEditPosition {
  const doc = root.ownerDocument;
  const position = doc.caretPositionFromPoint?.(clientX, clientY);
  const range = position ? null : doc.caretRangeFromPoint?.(clientX, clientY);
  const selection = doc.getSelection();
  const node = position?.offsetNode ?? range?.startContainer ?? selection?.anchorNode;
  const offset = position?.offset ?? range?.startOffset ?? selection?.anchorOffset ?? 0;
  let sourceOffset: number | null = null;
  if (node && root.contains(node)) {
    if (markdown) {
      sourceOffset = sourceOffsetAtCaret(root, node, offset, source);
    } else {
      const prefix = doc.createRange();
      prefix.selectNodeContents(root);
      prefix.setEnd(node, offset);
      sourceOffset = prefix.toString().length;
    }
  }
  // Keep the existing viewport if neither hit-testing nor source mapping is available.
  return { offset: sourceOffset === null ? null : Math.min(sourceOffset, source.length), clientY, scrollTop: root.scrollTop };
}

// A mirror uses the textarea's actual font and wrapping width, including its scrollbar.
// Counting newlines alone loses the clicked line whenever a long paragraph wraps.
export function alignTextareaToClick(textarea: HTMLTextAreaElement, position: MemoEditPosition) {
  if (position.offset === null) {
    textarea.scrollTop = position.scrollTop;
    return;
  }
  const doc = textarea.ownerDocument;
  const style = getComputedStyle(textarea);
  const mirror = doc.createElement("div");
  for (const property of [
    "font-family", "font-size", "font-weight", "font-style", "line-height", "letter-spacing",
    "word-spacing", "text-indent", "text-transform", "tab-size", "padding-top", "padding-right",
    "padding-bottom", "padding-left", "direction",
  ]) mirror.style.setProperty(property, style.getPropertyValue(property));
  Object.assign(mirror.style, {
    position: "fixed", top: "0", left: "0", visibility: "hidden", pointerEvents: "none",
    boxSizing: "border-box", width: `${textarea.clientWidth}px`, whiteSpace: "pre-wrap", overflowWrap: "break-word",
  });
  mirror.textContent = textarea.value.slice(0, position.offset);
  const marker = doc.createElement("span");
  marker.textContent = textarea.value.slice(position.offset) || "\u200b";
  mirror.append(marker);
  doc.body.append(mirror);
  try {
    const line = marker.getClientRects?.()[0];
    if (!line || !textarea.clientHeight) {
      textarea.scrollTop = position.scrollTop;
      return;
    }
    const rect = textarea.getBoundingClientRect();
    const lineHeight = Number.parseFloat(style.lineHeight) || line.height;
    const clickY = Math.max(lineHeight / 2, Math.min(position.clientY - rect.top, textarea.clientHeight - lineHeight / 2));
    textarea.scrollTop = line.top - mirror.getBoundingClientRect().top + line.height / 2 - clickY;
  } finally {
    mirror.remove();
  }
}
