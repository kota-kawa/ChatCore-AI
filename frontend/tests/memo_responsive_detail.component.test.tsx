import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MemoDetailModal } from "../components/memo/MemoDetailModal";
import { MemoPageContextProvider } from "../contexts/memo_page/memo_page_context";
import { changeMemoEditor, memoEditor, memoEditorValue } from "./memo_editor_harness";
import { createMemoPageControllerStub } from "./memo_page_context_harness";

vi.mock("../components/chat_page/MiniChat", () => ({
  MiniChat: function AgentStub() {
    const [draft, setDraft] = useState("");
    return <input aria-label="AI draft" value={draft} onChange={(event) => setDraft(event.target.value)} />;
  },
}));

// harness の再レンダーで別物にならないよう、モジュールで 1 つだけ持つ
// Kept at module scope so harness re-renders do not swap it for a new mock
const copyDetailFullText = vi.fn(async () => true);

function DetailHarness() {
  const [source, setSource] = useState(false);
  const [body, setBody] = useState("保存済みの本文");
  const [agent, setAgent] = useState(false);
  const [color, setColor] = useState<string | null>(null);
  const [collectionId, setCollectionId] = useState<number | null>(null);
  const controller = createMemoPageControllerStub({
    selectedMemo: { id: 7, title: "確認用", ai_response: body },
    detailEditTitle: "確認用",
    detailEditAiResponse: body,
    setDetailEditAiResponse: setBody,
    detailSourceMode: source,
    setDetailSourceMode: setSource,
    copyDetailFullText,
    isMemoAgentOpen: agent,
    setIsMemoAgentOpen: setAgent,
    openMemoAgent: async () => { setAgent(true); },
    detailEditBackgroundColor: color,
    setDetailEditBackgroundColor: setColor,
    detailEditCollectionId: collectionId,
    setDetailEditCollectionId: setCollectionId,
    collections: [{ id: 3, name: "仕事の長いコレクション名", color: "#3b82f6", memo_count: 1 }],
  });
  return <MemoPageContextProvider controller={controller}><MemoDetailModal /></MemoPageContextProvider>;
}

describe("memo detail on phones", () => {
  beforeEach(() => {
    vi.stubGlobal("matchMedia", () => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("opens formatting only on request and preserves the caret and draft when closing", () => {
    render(<DetailHarness />);
    expect(screen.queryByRole("toolbar", { name: "書式" })).toBeNull();
    expect(screen.queryByRole("button", { name: "書式" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "編集" }));
    const body = screen.getByRole("textbox", { name: "内容" });
    changeMemoEditor(body, "最初の行\n編集中の行");
    const editor = memoEditor(body);
    act(() => { editor.dispatch({ selection: { anchor: editor.state.doc.length } }); editor.focus(); });
    const toggle = screen.getByRole("button", { name: "書式" });
    fireEvent.mouseDown(toggle);
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("toolbar", { name: "書式" })).toHaveAttribute("id", toggle.getAttribute("aria-controls"));
    expect(body).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "箇条書き" }));
    expect(memoEditorValue(body)).toBe("最初の行\n- 編集中の行");
    const caret = editor.state.selection.main.head;
    fireEvent.mouseDown(toggle);
    fireEvent.click(toggle);
    expect(screen.queryByRole("toolbar", { name: "書式" })).toBeNull();
    expect(editor.state.selection.main.head).toBe(caret);
    expect(memoEditorValue(body)).toBe("最初の行\n- 編集中の行");
    expect(body).toHaveFocus();
  });

  it("keeps the memo and AI visible together without losing either draft", async () => {
    render(<DetailHarness />);
    const sourceToggle = screen.getByRole("button", { name: "編集" });
    expect(screen.getByRole("textbox", { name: "内容" })).toHaveAttribute("contenteditable", "false");
    fireEvent.click(sourceToggle);
    changeMemoEditor(screen.getByRole("textbox", { name: "内容" }), "未保存の手編集");
    const more = screen.getByLabelText("その他の操作");
    fireEvent.click(more);
    fireEvent.click(screen.getByRole("button", { name: "メモのチャコ" }));
    expect(more).toHaveAttribute("aria-expanded", "false");
    expect(more).toHaveFocus();
    await waitFor(() => expect(screen.getByRole("textbox", { name: "AI draft" })).toBeVisible());
    expect(screen.getByRole("textbox", { name: "内容" })).toBeVisible();
    fireEvent.change(screen.getByRole("textbox", { name: "AI draft" }), { target: { value: "質問の書きかけ" } });
    expect(sourceToggle).toHaveAccessibleName("表示");
    expect(screen.getByRole("textbox", { name: "内容" })).toHaveAttribute("contenteditable", "true");
    expect(screen.getByRole("textbox", { name: "AI draft" })).toHaveValue("質問の書きかけ");
    expect(memoEditorValue(screen.getByRole("textbox", { name: "内容" }))).toBe("未保存の手編集");
    fireEvent.click(sourceToggle);
    expect(sourceToggle).toHaveAccessibleName("編集");
    expect(screen.getByRole("textbox", { name: "内容" })).toHaveAttribute("contenteditable", "false");
    expect(memoEditorValue(screen.getByRole("textbox", { name: "内容" }))).toBe("未保存の手編集");
    fireEvent.click(screen.getAllByRole("button", { name: "メモチャットを閉じる" })[0]);
    expect(screen.queryByRole("textbox", { name: "AI draft" })).toBeNull();
    expect(screen.getByRole("textbox", { name: "内容" })).toBeVisible();
  });

  it("keeps the header to one row by moving the view tabs, AI and copy out of it", async () => {
    render(<DetailHarness />);
    expect(screen.queryByRole("button", { name: "整形表示" })).toBeNull();
    fireEvent.click(screen.getByLabelText("その他の操作"));
    const toolbar = screen.getByRole("toolbar", { name: "操作" });
    expect(toolbar).toContainElement(screen.getByRole("button", { name: "メモのチャコ" }));
    expect(toolbar).toContainElement(screen.getByRole("button", { name: "全文をコピー" }));
    fireEvent.click(screen.getByRole("button", { name: "全文をコピー" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "コピーしました" })).toBeVisible());
    expect(copyDetailFullText).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("その他の操作")).toHaveAttribute("aria-expanded", "true");
  });

  it("offers color and collection controls through a dismissible disclosure", () => {
    render(<DetailHarness />);
    const more = screen.getByLabelText("その他の操作");
    expect(more).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(more);
    fireEvent.click(screen.getByRole("option", { name: "ブルー" }));
    expect(screen.getByRole("option", { name: "ブルー" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("button", { name: "コレクション" }));
    fireEvent.click(screen.getByRole("option", { name: "仕事の長いコレクション名" }));
    expect(screen.getByRole("button", { name: "コレクション" })).toHaveTextContent("仕事の長いコレクション名");
    fireEvent.keyDown(more, { key: "Escape" });
    expect(more).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("dialog")).toHaveClass("is-open");
    expect(more).toHaveFocus();
  });
});
