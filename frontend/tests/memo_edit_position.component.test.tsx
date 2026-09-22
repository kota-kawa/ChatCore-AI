import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MemoMarkdown } from "../components/memo/MemoMarkdown";
import { alignTextareaToClick, captureMemoEditPosition } from "../lib/memo/detail_edit_position";
import { sourceOffsetAtCaret } from "../lib/memo/markdown_source_positions";

function preview(source: string) {
  return render(<MemoMarkdown text={source} />).container.firstElementChild as HTMLElement;
}

function textNode(root: HTMLElement, text: string, occurrence = 0) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (node.textContent === text && occurrence-- === 0) return node;
  }
  throw new Error(`Missing preview text: ${text}: ${root.innerHTML}`);
}

describe("memo preview source positions", () => {
  it.each([
    ["# 見出し\n\n本文 **強調** の続き", "強調", 1, 13],
    ["[同じ](同じ) 同じ", " 同じ", 2, 10],
    ["> 引用 **同じ**\n> 次の行", "次の行", 2, 16],
    ["- [x] 完了\n- 次の項目", "次の項目", 2, 13],
    ["| A | B |\n|---|---|\n| C | D |", "D", 1, 27],
    ["# title\r\n\r\n次の行", "次の行", 1, 12],
    ["先頭 &amp; 続き", "先頭 & 続き", 6, 10],
    ["絵文字😀の続き", "絵文字😀の続き", 5, 5],
    ["本文 <b>強調</b> 続き", "本文 強調 続き", 4, 7],
  ] as const)("maps Markdown %s to its source", (source, text, offset, expected) => {
    const root = preview(source);
    expect(sourceOffsetAtCaret(root, textNode(root, text), offset, source)).toBe(expected);
  });

  it("keeps repeated paragraphs distinct", () => {
    const source = "同じ文章\n\n同じ文章\n\n同じ文章";
    const root = preview(source);
    expect(sourceOffsetAtCaret(root, textNode(root, "同じ文章", 2), 2, source)).toBe(source.lastIndexOf("同じ文章") + 2);
  });

  it("maps an element boundary beside a paragraph to that paragraph", () => {
    const source = "前の文章\n\n次の文章";
    const root = preview(source);
    const next = textNode(root, "次の文章").parentElement!;
    expect(sourceOffsetAtCaret(root, next, 0, source)).toBe(source.indexOf("次の文章"));
  });

  it("maps highlighted code without matching its language label", () => {
    const source = "```js\nconst js = 1;\n```\n\njs";
    const root = preview(source);
    const walker = document.createTreeWalker(root.querySelector("code")!, NodeFilter.SHOW_TEXT);
    const node = walker.nextNode()!;
    expect(sourceOffsetAtCaret(root, node, 2, source)).toBe(source.indexOf("const") + 2);
    expect(sourceOffsetAtCaret(root, textNode(root, "js", 1), 1, source)).toBe(source.lastIndexOf("js") + 1);
  });

  it("keeps the preview scroll offset when layout measurement is unavailable", () => {
    const root = preview("文章");
    root.scrollTop = 350;
    const position = captureMemoEditPosition(root, "文章", 120, 80);
    const textarea = document.createElement("textarea");
    alignTextareaToClick(textarea, position);
    expect(textarea.scrollTop).toBe(350);
    expect(position.offset).toBeNull();
  });

  it("aligns the measured wrapped line with the click and removes the mirror", () => {
    const textarea = document.createElement("textarea");
    textarea.value = "長い段落".repeat(200);
    textarea.style.lineHeight = "24px";
    Object.defineProperties(textarea, { clientWidth: { value: 420 }, clientHeight: { value: 400 } });
    vi.spyOn(textarea, "getBoundingClientRect").mockReturnValue({ top: 100 } as DOMRect);
    vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([{ top: 800, height: 20 }] as unknown as DOMRectList);
    const childCount = document.body.childElementCount;
    alignTextareaToClick(textarea, { offset: 600, clientY: 210, scrollTop: 100 });
    expect(textarea.scrollTop).toBe(700);
    expect(document.body.childElementCount).toBe(childCount);
  });
});
