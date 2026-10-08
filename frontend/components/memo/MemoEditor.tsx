import { useEffect, useEffectEvent, useRef, type RefObject } from "react";
import { Compartment, EditorState, Prec, Transaction } from "@codemirror/state";
import { EditorView, keymap, placeholder as editorPlaceholder } from "@codemirror/view";
import { defaultKeymap, history, historyKeymap, redo } from "@codemirror/commands";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { syntaxTree } from "@codemirror/language";

import { memoLivePreview } from "../../lib/memo/live_preview";
import { applyMemoEditorEdit, memoEditorViews } from "../../lib/memo/editor";
import { continueListOnEnter } from "../../lib/memo/list_editing";

type MemoEditorProps = {
  value: string;
  onChange: (value: string) => void;
  sourceMode: boolean;
  editorRef: RefObject<EditorView | null>;
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
  } catch { /* Most memos are plain Markdown. */ }
  return value;
}

export function MemoEditor({ value, onChange, sourceMode, editorRef, label, placeholder, id, agentId, focusRequest = 0 }: MemoEditorProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const preview = useRef(new Compartment());
  const editing = useRef(new Compartment());
  const attributes = useRef(new Compartment());
  const initialProps = useEffectEvent(() => ({ value, label, placeholder, id, agentId }));
  const notifyChange = useEffectEvent((text: string) => {
    // Older memos may store a JSON string. Preserve that representation when editing.
    onChange(editorText(value) === value ? text : JSON.stringify(text));
  });

  useEffect(() => {
    if (!hostRef.current) return;
    const initial = initialProps();
    const continueList = (view: EditorView) => {
      if (view.state.readOnly || view.composing) return false;
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
      parent: hostRef.current,
      state: EditorState.create({
        doc: editorText(initial.value),
        extensions: [
          history(),
          markdown({ base: markdownLanguage, completeHTMLTags: false }),
          Prec.high(keymap.of([{ key: "Enter", run: continueList }, { key: "Mod-Shift-z", run: redo }, ...historyKeymap, ...defaultKeymap])),
          EditorView.lineWrapping,
          preview.current.of([]),
          editing.current.of([]),
          attributes.current.of([]),
          EditorView.updateListener.of((update) => {
            if (update.docChanged && !update.transactions.some((transaction) => transaction.annotation(Transaction.userEvent) === "input.external")) {
              notifyChange(update.state.doc.toString());
            }
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
    editorRef.current = view;
    memoEditorViews.set(view.contentDOM, view);
    return () => {
      memoEditorViews.delete(view.contentDOM);
      editorRef.current = null;
      view.destroy();
    };
  }, [editorRef]);

  useEffect(() => {
    const view = editorRef.current;
    if (!view) return;
    const wasReadOnly = view.state.readOnly;
    view.dispatch({ effects: [
      preview.current.reconfigure(sourceMode ? [] : memoLivePreview),
      editing.current.reconfigure([
        EditorState.readOnly.of(!sourceMode),
        EditorView.editable.of(sourceMode),
      ]),
      attributes.current.reconfigure([
        EditorView.contentAttributes.of({
          id, "aria-label": label, "data-agent-id": agentId ?? "", "aria-multiline": "true", "aria-readonly": String(!sourceMode),
        }),
        editorPlaceholder(placeholder),
      ]),
    ] });
    // プレビューからの復帰では、編集中だった選択位置を保ってキーボードを戻す。
    // Resume editing at the existing selection when leaving the preview.
    if (sourceMode && wasReadOnly) view.focus();
    if (!sourceMode && view.hasFocus) view.contentDOM.blur();
  }, [sourceMode, editorRef, label, placeholder, id, agentId]);

  useEffect(() => {
    const view = editorRef.current;
    if (!view) return;
    // External updates (including AI edits) enter the same history. Keep the unchanged
    // prefix/suffix so selections in unaffected text are mapped rather than reset.
    const previous = view.state.doc.toString();
    const next = editorText(value).replace(/\r\n?/g, "\n");
    if (previous === next) return;
    let from = 0;
    while (from < previous.length && from < next.length && previous[from] === next[from]) from++;
    let oldTo = previous.length, newTo = next.length;
    while (oldTo > from && newTo > from && previous[oldTo - 1] === next[newTo - 1]) { oldTo--; newTo--; }
    view.dispatch({ changes: { from, to: oldTo, insert: next.slice(from, newTo) }, userEvent: "input.external" });
  }, [value, editorRef]);

  // A composer open request is fulfilled after this editor mounts and receives its text.
  useEffect(() => {
    const view = editorRef.current;
    if (!focusRequest || !view) return;
    view.focus();
    view.dispatch({ selection: { anchor: view.state.doc.length }, scrollIntoView: true });
  }, [focusRequest, editorRef]);

  return <div ref={hostRef} className={`memo-live-editor${sourceMode ? " memo-live-editor--source" : ""}`} />;
}
