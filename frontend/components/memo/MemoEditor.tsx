// メモ本文のエディタ。Markdown ソース用の CodeMirror と、リッチ表示用の TipTap を同じ文書として同期させ、sourceMode で表示を切り替える。MemoComposer と MemoDetailModal から使われる。
// Memo body editor: keeps a CodeMirror Markdown source editor and a TipTap rich editor in sync as one document, switched by sourceMode; used by MemoComposer and MemoDetailModal.
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

// value は Markdown 文字列、または JSON 文字列に包まれた Markdown。focusRequest が増えるたびに末尾へカーソルを移す。
// value is Markdown text or Markdown wrapped in a JSON string; each increase of focusRequest moves the caret to the end.
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

// 保存値が JSON 文字列として包まれている場合は中身を取り出し、そうでなければ Markdown としてそのまま返す。
// Unwraps a value stored as a JSON string; otherwise returns it as plain Markdown.
function editorText(value: string) {
  try {
    const parsed: unknown = JSON.parse(value);
    if (typeof parsed === "string") return parsed;
  } catch { /* 通常の表現にはプレーンなMarkdownを使う。
    Plain Markdown is the usual representation. */ }
  return value;
}

// 文書の正は CodeMirror 側が持つ。リッチ側の編集は Markdown に直して CodeMirror の文書へ反映し、
// CodeMirror の変更はリッチ側へ流し込む。両方向の更新が反響しないよう、syncingRich / fromRich の旗で自分起点の更新を無視する。
// The document of record lives in CodeMirror: rich edits are serialized to Markdown into it, and its changes are pushed to the rich side;
// the syncingRich / fromRich flags stop each side from reacting to its own echo.
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
    // syncingRich: リッチ側を更新中。fromRich: リッチ側起点で CodeMirror を更新中。どちらも更新の往復（無限ループ）を防ぐ。
    // syncingRich: the rich editor is being updated; fromRich: CodeMirror is being updated from the rich side. Both prevent update ping-pong.
    let syncingRich = false;
    let fromRich = false;

    // CodeMirror の選択範囲を、リッチ側の同じ位置に対応づけて反映する。
    // Maps the CodeMirror selection onto the matching position in the rich editor.
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
    // リッチ側の選択範囲を、Markdown ソース上のオフセットに直して CodeMirror に反映する。
    // Converts the rich editor selection to Markdown source offsets and applies it to CodeMirror.
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
    // Enter でリスト項目を継続する。IME 変換中とコードブロック内では何もしない。
    // Continues a list item on Enter; does nothing during IME composition or inside code.
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
    // 外部（ツールバーなど）へ公開する操作窓口。いま表示中の側（ソース／リッチ）に合わせて動作を切り替える。
    // Handle exposed to outside code such as the toolbar; its behavior follows whichever side (source or rich) is active.
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
