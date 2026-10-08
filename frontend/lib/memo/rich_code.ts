import { Extension } from "@tiptap/core";
import CodeBlock from "@tiptap/extension-code-block";
import { Plugin } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import type { Node as DocumentNode } from "@tiptap/pm/model";
import hljs from "highlight.js";

import { renderSanitizedHTML } from "../../scripts/chat/message_utils";

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

function highlightDocument(doc: DocumentNode) {
  const decorations: Decoration[] = [];
  doc.descendants((node, pos) => {
    if (node.type.name !== "codeBlock" || !node.textContent) return;
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
        if (length && classes.length) decorations.push(Decoration.inline(pos + 1 + offset, pos + 1 + offset + length, { class: classes.join(" ") }));
        offset += length;
      } else {
        const inherited = element instanceof HTMLElement ? [...classes, ...element.classList] : classes;
        element.childNodes.forEach((child) => walk(child, inherited));
      }
    };
    walk(root, []);
  });
  return DecorationSet.create(doc, decorations);
}

export const MemoCodeHighlight = Extension.create({
  name: "memoCodeHighlight",
  addProseMirrorPlugins() {
    return [new Plugin({
      state: {
        init: (_, state) => highlightDocument(state.doc),
        apply: (transaction, previous) => transaction.docChanged ? highlightDocument(transaction.doc) : previous,
      },
      props: { decorations(state) { return this.getState(state); } },
    })];
  },
});
