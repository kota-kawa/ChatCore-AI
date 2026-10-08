import { useEffect, useEffectEvent, useRef, type RefObject } from "react";
import { Compartment, EditorState, Prec, Transaction } from "@codemirror/state";
import { EditorView, keymap, placeholder as editorPlaceholder } from "@codemirror/view";
import { defaultKeymap, history, historyKeymap, redo, undo } from "@codemirror/commands";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { syntaxTree } from "@codemirror/language";
import { Editor } from "@tiptap/core";

import { applyMemoEditorEdit, memoEditorViews, replaceMemoDocument, type MemoEditorHandle } from "../../lib/memo/editor";
import { continueListOnEnter, indentLines, toggleLineFormat } from "../../lib/memo/list_editing";
import { caretAtSourceOffset, sourceOffsetAtCaret } from "../../lib/memo/markdown_source_positions";
import { formatRichMemo, memoRichExtensions } from "../../lib/memo/rich_editor";

type MemoEditorProps = {
  value: string;
  onChange: (value: string) => void;
  sourceMode: boolean;
  editorRef: RefObject<MemoEditorHandle | null>;
  label: string;
  placeholder: string;
  id: string;
  agentId?: string;
  focusRequest?: number;
};

function editorText(value: string) {
  try {
    const parsed: unknown = JSON.parse(value);
    if (typeof parsed === "string") return parsed;
  } catch { /* Plain Markdown is the usual representation. */ }
  return value;
}

export function MemoEditor({ value, onChange, sourceMode, editorRef, label, placeholder, id, agentId, focusRequest = 0 }: MemoEditorProps) {
  const richHostRef = useRef<HTMLDivElement>(null);
  const sourceHostRef = useRef<HTMLDivElement>(null);
  const documentViewRef = useRef<EditorView | null>(null);
  const richViewRef = useRef<Editor | null>(null);
  const activeSourceRef = useRef(sourceMode);
  const attributes = useRef(new Compartment());
  const initialProps = useEffectEvent(() => ({ value, label, placeholder, id, agentId }));
  const notifyChange = useEffectEvent((text: string) => onChange(editorText(value) === value ? text : JSON.stringify(text)));

  useEffect(() => {
    if (!richHostRef.current || !sourceHostRef.current) return;
    const initial = initialProps();
    let syncingRich = false;
    let fromRich = false;

    const restoreRichSelection = (view: EditorView) => {
      const rich = richViewRef.current;
      if (!rich || rich.isDestroyed) return;
      const text = view.state.doc.toString();
      const { from, to } = view.state.selection.main;
      const position = (offset: number) => {
        const caret = caretAtSourceOffset(rich.view.dom, text, offset);
        return caret ? rich.view.posAtDOM(caret.node, caret.offset) : Math.max(1, rich.state.doc.content.size - 1);
      };
      syncingRich = true;
      rich.commands.setTextSelection({ from: position(from), to: position(to) });
      syncingRich = false;
    };
    const syncDocumentSelection = (editor: Editor) => {
      if (syncingRich || activeSourceRef.current) return;
      const source = view.state.doc.toString();
      const position = (pos: number) => {
        const caret = editor.view.domAtPos(pos);
        return sourceOffsetAtCaret(editor.view.dom, caret.node, caret.offset, source);
      };
      const anchor = position(editor.state.selection.anchor);
      const head = position(editor.state.selection.head);
      if (anchor === null || head === null) return;
      fromRich = true;
      view.dispatch({ selection: { anchor, head } });
      fromRich = false;
    };
    const continueList = (view: EditorView) => {
      if (view.composing) return false;
      const { from, to } = view.state.selection.main;
      for (let node = syntaxTree(view.state).resolveInner(from, -1); node; node = node.parent!) {
        if (["FencedCode", "CodeBlock", "InlineCode"].includes(node.name)) return false;
      }
      const edit = continueListOnEnter(view.state.doc.toString(), from, to);
      if (!edit) return false;
      applyMemoEditorEdit(view, edit);
      return true;
    };
    const view = new EditorView({
      parent: sourceHostRef.current,
      state: EditorState.create({
        doc: editorText(initial.value),
        extensions: [
          history(), markdown({ base: markdownLanguage, completeHTMLTags: false }),
          Prec.high(keymap.of([{ key: "Enter", run: continueList }, { key: "Mod-Shift-z", run: redo }, ...historyKeymap, ...defaultKeymap])),
          EditorView.lineWrapping, attributes.current.of([]),
          EditorView.updateListener.of((update) => {
            const rich = richViewRef.current;
            if (update.docChanged) {
              if (!update.transactions.some((transaction) => transaction.annotation(Transaction.userEvent) === "input.external")) {
                notifyChange(update.state.doc.toString());
              }
              if (rich && !fromRich) {
                syncingRich = true;
                rich.commands.setContent(update.state.doc.toString(), { contentType: "markdown", emitUpdate: false });
                syncingRich = false;
              }
            }
            if (!fromRich && (update.docChanged || update.selectionSet)) restoreRichSelection(view);
          }),
          EditorView.domEventHandlers({
            beforeinput: (event, editor) => {
              if (!["insertLineBreak", "insertParagraph"].includes(event.inputType) || event.isComposing || editor.composing) return false;
              return continueList(editor);
            },
          }),
        ],
      }),
    });
    const rich = new Editor({
      element: richHostRef.current,
      extensions: memoRichExtensions(() => initialProps().placeholder, () => undo(view), () => redo(view)),
      content: view.state.doc.toString(), contentType: "markdown", injectCSS: false,
      editorProps: { attributes: { class: "memo-rich-content", role: "textbox", "aria-multiline": "true" } },
      onUpdate: ({ editor }) => {
        if (syncingRich) return;
        fromRich = true;
        replaceMemoDocument(view, editor.getMarkdown(), "input");
        fromRich = false;
        syncDocumentSelection(editor);
      },
      onSelectionUpdate: ({ editor }) => syncDocumentSelection(editor),
    });
    const handle: MemoEditorHandle = {
      get state() { return view.state; },
      get contentDOM() { return activeSourceRef.current ? view.contentDOM : rich.view.dom; },
      dispatch: (spec) => view.dispatch(spec),
      focus: () => {
        if (activeSourceRef.current) view.focus();
        else rich.view.focus();
      },
      undo: () => undo(view), redo: () => redo(view),
      format: (format) => {
        if (!activeSourceRef.current) { formatRichMemo(rich, format); return; }
        const { from, to } = view.state.selection.main;
        const edit = format === "indent" || format === "outdent"
          ? indentLines(view.state.doc.toString(), from, to, format === "indent" ? 1 : -1)
          : toggleLineFormat(view.state.doc.toString(), from, to, format);
        if (edit) applyMemoEditorEdit(view, edit);
      },
    };
    documentViewRef.current = view;
    richViewRef.current = rich;
    editorRef.current = handle;
    memoEditorViews.set(view.contentDOM, handle);
    memoEditorViews.set(rich.view.dom, handle);
    // キーボードで入力面が縮んでも、編集中のカーソルを画面内へ戻す。
    // Keep the active rich-text caret visible when the editing surface shrinks.
    const resizeObserver = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => {
      if (!activeSourceRef.current && rich.view.hasFocus()) rich.commands.scrollIntoView();
    });
    resizeObserver?.observe(richHostRef.current);
    return () => {
      resizeObserver?.disconnect();
      memoEditorViews.delete(view.contentDOM);
      memoEditorViews.delete(rich.view.dom);
      editorRef.current = null;
      documentViewRef.current = null;
      richViewRef.current = null;
      rich.destroy(); view.destroy();
    };
  }, [editorRef]);

  useEffect(() => {
    const view = documentViewRef.current;
    const rich = richViewRef.current;
    if (!view || !rich) return;
    const modeChanged = activeSourceRef.current !== sourceMode;
    activeSourceRef.current = sourceMode;
    view.dispatch({ effects: attributes.current.reconfigure([
      EditorView.contentAttributes.of({ id: sourceMode ? id : "", "aria-label": label, "data-agent-id": sourceMode ? agentId ?? "" : "", "aria-multiline": "true" }),
      editorPlaceholder(placeholder),
    ]) });
    rich.view.dom.id = sourceMode ? "" : id;
    rich.view.dom.setAttribute("aria-label", label);
    rich.view.dom.setAttribute("data-agent-id", sourceMode ? "" : agentId ?? "");
    if (modeChanged) editorRef.current?.focus();
  }, [sourceMode, editorRef, label, placeholder, id, agentId]);

  useEffect(() => {
    const view = documentViewRef.current;
    if (view) replaceMemoDocument(view, editorText(value).replace(/\r\n?/g, "\n"), "input.external");
  }, [value]);

  useEffect(() => {
    const editor = editorRef.current;
    if (!focusRequest || !editor) return;
    editor.dispatch({ selection: { anchor: editor.state.doc.length }, scrollIntoView: true });
    editor.focus();
  }, [focusRequest, editorRef]);

  return (
    <div className={`memo-live-editor${sourceMode ? " memo-live-editor--source" : ""}`}>
      <div ref={richHostRef} className="memo-rich-editor" hidden={sourceMode} />
      <div ref={sourceHostRef} className="memo-source-editor" hidden={!sourceMode} />
    </div>
  );
}
