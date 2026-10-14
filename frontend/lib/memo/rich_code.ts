import { Extension } from "@tiptap/core";
import CodeBlock from "@tiptap/extension-code-block";
import { Plugin } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import type { Node as DocumentNode } from "@tiptap/pm/model";
import hljs from "highlight.js";

import { renderSanitizedHTML } from "../../scripts/chat/message_utils";

type HighlightedCodeBlock = {
  text: string;
  language: string | null;
  spans: HighlightedCodeSpan[];
};

type HighlightedCodeSpan = {
  from: number;
  to: number;
  className: string;
};

type MemoCodeHighlightState = {
  decorations: DecorationSet;
  blocks: HighlightedCodeBlock[];
};

export const MemoCodeBlock = CodeBlock.extend({
  addNodeView() {
    return ({ node }) => {
      const dom = document.createElement("div");
      dom.className = "memo-rich-code-block";
      const language = document.createElement("div");
      language.className = "memo-rich-code-language";
      language.contentEditable = "false";
      language.textContent = node.attrs.language || "text";
      const pre = document.createElement("pre");
      const contentDOM = document.createElement("code");
      pre.append(contentDOM);
      dom.append(language, pre);
      return {
        dom, contentDOM,
        update(updated) {
          if (updated.type !== node.type) return false;
          language.textContent = updated.attrs.language || "text";
          return true;
        },
      };
    };
  },
});

function highlightCodeBlock(node: DocumentNode): HighlightedCodeSpan[] {
  const spans: HighlightedCodeSpan[] = [];
  if (!node.textContent) return spans;

  const language = node.attrs.language;
  const highlighted = language && hljs.getLanguage(language)
    ? hljs.highlight(node.textContent, { language }).value
    : hljs.highlightAuto(node.textContent).value;
  const root = document.createElement("div");
  renderSanitizedHTML(root, highlighted);
  let offset = 0;
  const walk = (element: Node, classes: string[]) => {
    if (element.nodeType === Node.TEXT_NODE) {
      const length = element.textContent?.length ?? 0;
      if (length && classes.length) spans.push({ from: offset, to: offset + length, className: classes.join(" ") });
      offset += length;
    } else {
      const inherited = element instanceof HTMLElement ? [...classes, ...element.classList] : classes;
      element.childNodes.forEach((child) => walk(child, inherited));
    }
  };
  walk(root, []);
  return spans;
}

function createBlockDecorations(pos: number, spans: HighlightedCodeSpan[]) {
  return spans.map(({ from, to, className }) => Decoration.inline(pos + 1 + from, pos + 1 + to, { class: className }));
}

function createBlockState(text: string, language: string | null, spans: HighlightedCodeSpan[]): HighlightedCodeBlock {
  return { text, language, spans };
}

function highlightDocument(doc: DocumentNode, previousBlocks: HighlightedCodeBlock[] = []): MemoCodeHighlightState {
  const decorations: Decoration[] = [];
  const blocks: HighlightedCodeBlock[] = [];
  const previousSpans = new Map<string | null, Map<string, HighlightedCodeSpan[]>>();
  for (const block of previousBlocks) {
    let spansByText = previousSpans.get(block.language);
    if (!spansByText) {
      spansByText = new Map();
      previousSpans.set(block.language, spansByText);
    }
    spansByText.set(block.text, block.spans);
  }

  doc.descendants((node, pos) => {
    if (node.type.name !== "codeBlock") return;
    const text = node.textContent;
    const language = typeof node.attrs.language === "string" ? node.attrs.language : null;
    const cachedSpans = previousSpans.get(language)?.get(text);
    const block = createBlockState(text, language, cachedSpans ?? highlightCodeBlock(node));
    blocks.push(block);
    decorations.push(...createBlockDecorations(pos, block.spans));
  });
  return { decorations: DecorationSet.create(doc, decorations), blocks };
}

export const MemoCodeHighlight = Extension.create({
  name: "memoCodeHighlight",
  addProseMirrorPlugins() {
    return [new Plugin({
      state: {
        init: (_, state) => highlightDocument(state.doc),
        apply: (transaction, previous) => transaction.docChanged ? highlightDocument(transaction.doc, previous.blocks) : previous,
      },
      props: { decorations(state) { return this.getState(state)?.decorations; } },
    })];
  },
});
