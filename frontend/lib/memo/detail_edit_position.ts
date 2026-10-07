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
