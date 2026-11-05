// メモのリッチエディタ（TipTap）の拡張の組み合わせと、ツールバーの書式指定をエディタの操作へ対応づける処理。
// Assembles the TipTap extensions for the memo's rich editor and maps toolbar format requests to editor commands.
// Used by components/memo/MemoEditor.tsx.

import { Editor, Extension, renderNestedMarkdownContent } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import { Markdown } from "@tiptap/markdown";
import { TableKit } from "@tiptap/extension-table";
import { OrderedList, TaskItem, TaskList } from "@tiptap/extension-list";
import Image from "@tiptap/extension-image";
import Placeholder from "@tiptap/extension-placeholder";

import type { MemoFormat } from "./editor";
import { MemoCodeBlock, MemoCodeHighlight } from "./rich_code";

// 既存の番号付きチェックリストも、番号とチェック欄を保って編集できるようにする。
// Preserve numbered checklists supported by existing memos.
// 番号付きリストの項目に taskItem も入れられるようにし、Markdown の「1. [ ] 項目」を読み込むとチェック欄つきの項目として扱う。
// Lets ordered lists hold taskItem too, and reads Markdown like "1. [ ] item" as a checklist item.
const MemoOrderedList = OrderedList.extend({
  content: "(listItem | taskItem)+",
  parseMarkdown(token, helpers) {
    const parsed = this.parent?.(token, helpers);
    const lists = Array.isArray(parsed) ? parsed : parsed ? [parsed] : [];
    for (const list of lists) for (const item of list.content ?? []) {
      const content = item.content?.[0]?.content;
      const first = content?.[0];
      const marker = first?.type === "text" ? first.text?.match(/^\[([ xX])\]\s+/) : null;
      if (!marker || !first || !content) continue;
      item.type = "taskItem";
      item.attrs = { ...item.attrs, checked: marker[1].toLowerCase() === "x" };
      first.text = first.text!.slice(marker[0].length);
      if (!first.text) content.shift();
    }
    return parsed ?? [];
  },
});

// チェック項目を Markdown に書き出すときの接頭辞を決める。番号付きリストの中なら「1. [x] 」、それ以外は「- [x] 」。
// Chooses the prefix when writing a checklist item back to Markdown: "1. [x] " inside an ordered list, otherwise "- [x] ".
const MemoTaskItem = TaskItem.extend({
  renderMarkdown(node, helpers, context) {
    const checked = node.attrs?.checked ? "x" : " ";
    const number = Number(context.meta?.parentAttrs?.start ?? 1) + (context.index ?? 0);
    const prefix = context.parentType === "orderedList" ? `${number}. [${checked}] ` : `- [${checked}] `;
    return renderNestedMarkdownContent(node, helpers, prefix, context);
  },
});

// リッチエディタに使う拡張の一覧を返す。取り消し／やり直しは TipTap 標準の履歴ではなく、受け取った undo/redo のコールバックに任せる。
// Returns the extension list for the rich editor; undo/redo are delegated to the supplied callbacks instead of TipTap's built-in history.
export function memoRichExtensions(placeholder: () => string, undo: () => boolean, redo: () => boolean) {
  return [
    StarterKit.configure({ codeBlock: false, orderedList: false, undoRedo: false, underline: false, trailingNode: false, link: { openOnClick: true, autolink: false, HTMLAttributes: { rel: "noopener noreferrer", target: "_blank" } } }),
    MemoCodeBlock, MemoCodeHighlight,
    MemoOrderedList,
    TableKit,
    TaskList,
    MemoTaskItem.configure({ nested: true, HTMLAttributes: { "data-type": "taskItem" }, a11y: { checkboxLabel: (node) => node.textContent } }),
    Image.configure({ inline: true }),
    Placeholder.configure({ placeholder }),
    Markdown.configure({ markedOptions: { gfm: true, breaks: true } }),
    Extension.create({
      name: "memoHistory",
      addKeyboardShortcuts: () => ({ "Mod-z": undo, "Mod-Shift-z": redo, "Mod-y": redo }),
    }),
  ];
}

// ツールバーの書式指定（チェック・箇条書き・番号・見出し・字下げ・字上げ）を、TipTap のコマンドとして実行する。
// Runs a toolbar format request (checklist, bullet, number, heading, indent, outdent) as the corresponding TipTap command.
export function formatRichMemo(editor: Editor, format: MemoFormat) {
  const chain = editor.chain().focus();
  switch (format) {
    case "task": chain.toggleTaskList().run(); break;
    case "bullet": chain.toggleBulletList().run(); break;
    case "number": chain.toggleOrderedList().run(); break;
    case "heading": chain.toggleHeading({ level: 2 }).run(); break;
    case "indent": chain.sinkListItem(editor.isActive("taskItem") ? "taskItem" : "listItem").run(); break;
    case "outdent": chain.liftListItem(editor.isActive("taskItem") ? "taskItem" : "listItem").run(); break;
  }
  editor.view.focus();
}
