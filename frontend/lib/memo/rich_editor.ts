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

const MemoTaskItem = TaskItem.extend({
  renderMarkdown(node, helpers, context) {
    const checked = node.attrs?.checked ? "x" : " ";
    const number = Number(context.meta?.parentAttrs?.start ?? 1) + (context.index ?? 0);
    const prefix = context.parentType === "orderedList" ? `${number}. [${checked}] ` : `- [${checked}] `;
    return renderNestedMarkdownContent(node, helpers, prefix, context);
  },
});

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
