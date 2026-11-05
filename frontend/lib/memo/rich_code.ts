// リッチエディタ（TipTap）のコードブロックの表示と、highlight.js による構文ハイライト。
// 言語名のラベルつきのコードブロックを描画し、本文が変わったときだけ色分けをかけ直す。
// Code block rendering and highlight.js syntax highlighting for the rich editor (TipTap).
// Renders code blocks with a language label and re-highlights only when the document changes.
// Used by lib/memo/rich_editor.ts.

import { Extension } from "@tiptap/core";
import CodeBlock from "@tiptap/extension-code-block";
import { Plugin } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import type { Node as DocumentNode } from "@tiptap/pm/model";
import hljs from "highlight.js";

import { renderSanitizedHTML } from "../../scripts/chat/message_utils";

// ハイライト済みのコードブロック 1 つ分。同じ言語と本文なら前回の結果を使い回すために保持する。
// One highlighted code block, kept so the previous result can be reused for the same language and text.
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

// プラグインの状態。エディタに適用する装飾（decorations）と、ブロックごとのハイライト結果。
// Plugin state: the decorations applied to the editor and the highlight result per block.
type MemoCodeHighlightState = {
  decorations: DecorationSet;
  blocks: HighlightedCodeBlock[];
};

// コードブロックの表示を差し替える。言語名を示す編集不可のラベルと、本文を入力する pre/code を並べる。
// Replaces the code block view: a non-editable label showing the language, followed by the editable pre/code.
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

// コードブロックの本文を highlight.js で色分けし、文字位置ごとの CSS クラスの一覧にする。言語が分からなければ自動判定する。
// Highlights the block's text with highlight.js and returns CSS classes per character range; the language is auto-detected when unknown.
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

// 文書内の全コードブロックの装飾を作る。言語と本文が前回と同じブロックは、再計算せず前回の結果を使い回す。
// Builds decorations for every code block in the document; blocks with the same language and text as before reuse the previous result instead of re-highlighting.
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

// コードブロックの色分けを ProseMirror のプラグインとして組み込む拡張。文書が変更されたトランザクションのときだけ計算し直す。
// Extension that wires code highlighting in as a ProseMirror plugin, recomputing only on transactions that change the document.
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
