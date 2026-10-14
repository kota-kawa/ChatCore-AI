import { Editor } from "@tiptap/core";
import hljs from "highlight.js";
import { describe, expect, it, vi } from "vitest";

import { memoRichExtensions } from "../lib/memo/rich_editor";

describe("MemoCodeHighlight", () => {
  it("reuses unchanged highlights across position changes and re-highlights changed blocks", () => {
    const highlight = vi.spyOn(hljs, "highlight").mockClear();
    const initial = [
      "before",
      "",
      "```javascript",
      "const value = 1;",
      "```",
      "",
      "```python",
      "def value():",
      "    return 1",
      "```",
    ].join("\n");
    const editor = new Editor({
      element: document.createElement("div"),
      extensions: memoRichExtensions(() => "", () => false, () => false),
      content: initial,
      contentType: "markdown",
      injectCSS: false,
    });

    try {
      const view = editor.view;
      const codeBlocks = () => Array.from(view.dom.querySelectorAll<HTMLElement>(".memo-rich-code-block"));
      const initialHtml = codeBlocks().map((block) => block.innerHTML);
      const initialHighlightCalls = highlight.mock.calls.length;
      expect(initialHighlightCalls).toBe(2);

      view.dispatch(view.state.tr.insertText("prefix ", 1));

      expect(highlight).toHaveBeenCalledTimes(initialHighlightCalls);
      expect(codeBlocks().map((block) => block.innerHTML)).toEqual(initialHtml);

      editor.commands.setContent(initial.replace("before", "source mode"), {
        contentType: "markdown",
        emitUpdate: false,
      });

      expect(highlight).toHaveBeenCalledTimes(initialHighlightCalls);
      expect(codeBlocks().map((block) => block.innerHTML)).toEqual(initialHtml);

      let firstBlockPos = -1;
      view.state.doc.descendants((node, pos) => {
        if (firstBlockPos === -1 && node.type.name === "codeBlock") firstBlockPos = pos;
      });
      view.dispatch(view.state.tr.insertText("// added\n", firstBlockPos + 1));

      expect(highlight).toHaveBeenCalledTimes(initialHighlightCalls + 1);
      expect(codeBlocks()[1].innerHTML).toBe(initialHtml[1]);

      let changedBlockPos = -1;
      let changedBlockAttrs: Record<string, unknown> = {};
      view.state.doc.descendants((node, pos) => {
        if (changedBlockPos === -1 && node.type.name === "codeBlock") {
          changedBlockPos = pos;
          changedBlockAttrs = node.attrs;
        }
      });
      view.dispatch(view.state.tr.setNodeMarkup(changedBlockPos, undefined, { ...changedBlockAttrs, language: "python" }));

      expect(highlight).toHaveBeenCalledTimes(initialHighlightCalls + 2);
      expect(codeBlocks()[0]).toHaveTextContent("python");
      expect(codeBlocks()[1].innerHTML).toBe(initialHtml[1]);
    } finally {
      editor.destroy();
    }
  });

  it("reuses previous-document spans for duplicate, unknown, and auto-detected languages", () => {
    const highlight = vi.spyOn(hljs, "highlight").mockClear();
    const highlightAuto = vi.spyOn(hljs, "highlightAuto").mockClear();
    const initial = [
      "before",
      "",
      "```javascript",
      "const duplicate = 1;",
      "```",
      "",
      "```javascript",
      "const duplicate = 1;",
      "```",
      "",
      "```memo-unknown-language",
      "function unknown() { return 1; }",
      "```",
      "",
      "```",
      "const inferred = 1;",
      "```",
    ].join("\n");
    const editor = new Editor({
      element: document.createElement("div"),
      extensions: memoRichExtensions(() => "", () => false, () => false),
      content: initial,
      contentType: "markdown",
      injectCSS: false,
    });

    try {
      const codeBlocks = (target: Editor) => Array.from(target.view.dom.querySelectorAll<HTMLElement>(".memo-rich-code-block"));
      const beforeHtml = codeBlocks(editor).map((block) => block.innerHTML);
      const highlightCalls = highlight.mock.calls.length;
      const autoCalls = highlightAuto.mock.calls.length;
      expect(beforeHtml).toHaveLength(4);
      expect(highlightCalls).toBe(2);
      expect(autoCalls).toBe(2);

      const moved = [
        "source mode update",
        "",
        "```memo-unknown-language",
        "function unknown() { return 1; }",
        "```",
        "",
        "```",
        "const inferred = 1;",
        "```",
        "",
        "```javascript",
        "const duplicate = 1;",
        "```",
        "",
        "```javascript",
        "const duplicate = 1;",
        "```",
      ].join("\n");
      editor.commands.setContent(moved, { contentType: "markdown", emitUpdate: false });

      expect(highlight).toHaveBeenCalledTimes(highlightCalls);
      expect(highlightAuto).toHaveBeenCalledTimes(autoCalls);
      expect(codeBlocks(editor).map((block) => block.innerHTML)).toEqual([
        beforeHtml[2],
        beforeHtml[3],
        beforeHtml[0],
        beforeHtml[1],
      ]);

      let unknownBlockPos = -1;
      let unknownBlockAttrs: Record<string, unknown> = {};
      editor.state.doc.descendants((node, pos) => {
        if (unknownBlockPos === -1 && node.type.name === "codeBlock" && node.attrs.language === "memo-unknown-language") {
          unknownBlockPos = pos;
          unknownBlockAttrs = node.attrs;
        }
      });
      const unknownCodeHtml = codeBlocks(editor)[0].querySelector("code")?.innerHTML;
      editor.view.dispatch(editor.state.tr.setNodeMarkup(unknownBlockPos, undefined, {
        ...unknownBlockAttrs,
        language: "another-unknown-language",
      }));

      expect(highlightAuto).toHaveBeenCalledTimes(autoCalls + 1);
      expect(codeBlocks(editor)[0].querySelector("code")?.innerHTML).toBe(unknownCodeHtml);

      const freshEditor = new Editor({
        element: document.createElement("div"),
        extensions: memoRichExtensions(() => "", () => false, () => false),
        content: editor.state.doc.toJSON(),
        injectCSS: false,
      });
      try {
        expect(codeBlocks(editor).map((block) => block.innerHTML)).toEqual(codeBlocks(freshEditor).map((block) => block.innerHTML));
      } finally {
        freshEditor.destroy();
      }
    } finally {
      editor.destroy();
    }
  });
});
