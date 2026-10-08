import { StateField, type EditorState, type Range } from "@codemirror/state";
import { syntaxTree } from "@codemirror/language";
import { Decoration, EditorView, WidgetType, type DecorationSet } from "@codemirror/view";

import { formatMemoOutput } from "../../scripts/chat/chat_ui";
import { renderSanitizedHTML } from "../../scripts/chat/message_utils";

class TaskCheckbox extends WidgetType {
  constructor(readonly checked: boolean, readonly label: string) { super(); }
  eq(other: TaskCheckbox) { return this.checked === other.checked && this.label === other.label; }
  toDOM(view: EditorView) {
    const target = document.createElement("label");
    target.className = "memo-live-preview__task-target";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = this.checked;
    box.className = "memo-live-preview__checkbox";
    box.setAttribute("aria-label", this.label);
    box.addEventListener("mousedown", (event) => event.preventDefault());
    box.addEventListener("change", () => {
      // The DOM position is resolved at the time of the click, after any preceding edits.
      const from = view.posAtDOM(target);
      if (!/^\[[ xX]\]$/.test(view.state.doc.sliceString(from, from + 3))) return;
      view.dispatch({ changes: { from: from + 1, to: from + 2, insert: box.checked ? "x" : " " }, userEvent: "input" });
    });
    target.append(box);
    return target;
  }
  updateDOM(target: HTMLElement) {
    const box = target.querySelector("input")!;
    box.checked = this.checked;
    box.setAttribute("aria-label", this.label);
    return true;
  }
  ignoreEvent() { return true; }
}

class RenderedMarkdown extends WidgetType {
  constructor(readonly source: string, readonly block: boolean) { super(); }
  eq(other: RenderedMarkdown) { return this.source === other.source && this.block === other.block; }
  toDOM() {
    const root = document.createElement(this.block ? "div" : "span");
    root.className = "memo-preview-content memo-live-preview__rendered";
    renderSanitizedHTML(root, formatMemoOutput(this.source));
    root.querySelectorAll<HTMLAnchorElement>("a[href]").forEach((link) => {
      link.target = "_blank";
      link.rel = "noopener noreferrer";
    });
    return root;
  }
  ignoreEvent() { return true; }
}

function safeLink(value: string): string | null {
  try {
    const url = new URL(value, "https://localhost/");
    return ["http:", "https:", "mailto:"].includes(url.protocol) ? value : null;
  } catch { return null; }
}

function buildPreview(state: EditorState): DecorationSet {
  const ranges: Range<Decoration>[] = [];
  const orderedListNext = new Map<number, number>();
  const itemNumbers = new Map<number, number>();
  const hide = (from: number, to: number) => {
    if (to > from) ranges.push(Decoration.replace({}).range(from, to));
  };
  const mark = (from: number, to: number, className: string) => {
    if (to > from) ranges.push(Decoration.mark({ class: className }).range(from, to));
  };
  syntaxTree(state).iterate({
    enter: ({ node, name, from, to }) => {
      if (name === "OrderedList") {
        orderedListNext.set(from, Number(state.doc.sliceString(from, to).match(/^\d+/)?.[0] ?? 1));
      }
      if (name === "ListItem" && node.parent?.name === "OrderedList") {
        const number = orderedListNext.get(node.parent.from) ?? 1;
        itemNumbers.set(from, number);
        orderedListNext.set(node.parent.from, number + 1);
      }
      if (["FencedCode", "CodeBlock", "Table", "HorizontalRule", "Image"].includes(name)) {
        const block = name !== "Image";
        ranges.push(Decoration.replace({ widget: new RenderedMarkdown(state.doc.sliceString(from, to), block), block }).range(from, to));
        return false;
      }
      if (/^(?:ATX|Setext)Heading[1-6]$/.test(name)) {
        ranges.push(Decoration.line({ class: `memo-live-preview__heading memo-live-preview__heading--${name.at(-1)}` }).range(state.doc.lineAt(from).from));
        for (let child = node.firstChild; child; child = child.nextSibling) {
          if (child.name === "HeaderMark") {
            const end = child.from === from ? child.to + (state.doc.sliceString(child.to, child.to + 1) === " " ? 1 : 0) : child.to;
            hide(child.from, end);
          }
        }
      }
      const inlineClasses: Record<string, string> = { StrongEmphasis: "strong", Emphasis: "emphasis", Strikethrough: "strike", InlineCode: "code" };
      const inlineClass = inlineClasses[name];
      if (inlineClass) {
        mark(from, to, `memo-live-preview__${inlineClass}`);
        for (let child = node.firstChild; child; child = child.nextSibling) {
          if (/^(EmphasisMark|StrikethroughMark|CodeMark)$/.test(child.name)) hide(child.from, child.to);
        }
      }
      if (name === "Link") {
        const open = node.firstChild;
        let close = open?.nextSibling;
        while (close && !(close.name === "LinkMark" && state.doc.sliceString(close.from, close.to) === "]")) close = close.nextSibling;
        const url = node.getChild("URL");
        if (open && close && url) {
          const href = safeLink(state.doc.sliceString(url.from, url.to).replace(/^<|>$/g, ""));
          hide(open.from, open.to);
          hide(close.from, to);
          if (href) ranges.push(Decoration.mark({ tagName: "a", class: "memo-live-preview__link", attributes: { href, target: "_blank", rel: "noopener noreferrer" } }).range(open.to, close.from));
        }
      }
      if (name === "TaskMarker") {
        const label = state.doc.lineAt(to).text.slice(to - state.doc.lineAt(to).from).trim();
        ranges.push(Decoration.replace({ widget: new TaskCheckbox(state.doc.sliceString(from + 1, from + 2).toLowerCase() === "x", label) }).range(from, to));
      }
      if (name === "Escape") hide(from, from + 1);
      if (name === "ListMark") {
        const after = state.doc.sliceString(to, state.doc.lineAt(to).to);
        if (node.parent && itemNumbers.has(node.parent.from)) {
          ranges.push(Decoration.replace({ widget: new ListMarker(`${itemNumbers.get(node.parent.from)}.`) }).range(from, to));
        } else if (/^\s+\[[ xX]\]/.test(after)) hide(from, to + 1);
        else if (/^[-*+]$/.test(state.doc.sliceString(from, to))) {
          ranges.push(Decoration.replace({ widget: new ListMarker("•") }).range(from, to));
        }
      }
      if (name === "QuoteMark") {
        ranges.push(Decoration.line({ class: "memo-live-preview__quote" }).range(state.doc.lineAt(from).from));
        hide(from, to + (state.doc.sliceString(to, to + 1) === " " ? 1 : 0));
      }
    },
  });
  return Decoration.set(ranges, true);
}

class ListMarker extends WidgetType {
  constructor(readonly text: string) { super(); }
  eq(other: ListMarker) { return this.text === other.text; }
  toDOM() {
    const span = document.createElement("span");
    span.textContent = this.text;
    span.className = "memo-live-preview__list-mark";
    span.setAttribute("aria-hidden", "true");
    return span;
  }
}

const previewDecorations = StateField.define<DecorationSet>({
  create: buildPreview,
  update: (_decorations, transaction) => buildPreview(transaction.state),
  provide: (field) => EditorView.decorations.from(field),
});

export const memoLivePreview = [previewDecorations];
