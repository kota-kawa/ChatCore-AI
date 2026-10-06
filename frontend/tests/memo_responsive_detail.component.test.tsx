import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MemoDetailModal } from "../components/memo/MemoDetailModal";
import { MemoPageContextProvider } from "../contexts/memo_page/memo_page_context";
import { createMemoPageControllerStub } from "./memo_page_context_harness";

vi.mock("../components/chat_page/MiniChat", () => ({
  MiniChat: function AgentStub() {
    const [draft, setDraft] = useState("");
    return <input aria-label="AI draft" value={draft} onChange={(event) => setDraft(event.target.value)} />;
  },
}));

function DetailHarness() {
  const [preview, setPreview] = useState(true);
  const [body, setBody] = useState("保存済みの本文");
  const [agent, setAgent] = useState(false);
  const [color, setColor] = useState<string | null>(null);
  const [collectionId, setCollectionId] = useState<number | null>(null);
  const controller = createMemoPageControllerStub({
    selectedMemo: { id: 7, title: "確認用", ai_response: body },
    detailEditTitle: "確認用",
    detailEditAiResponse: body,
    setDetailEditAiResponse: setBody,
    detailPreviewMode: preview,
    setDetailPreviewMode: setPreview,
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

  it("switches between memo and AI without losing either draft", async () => {
    render(<DetailHarness />);
    fireEvent.click(screen.getByRole("tab", { name: "編集" }));
    fireEvent.change(screen.getByRole("textbox", { name: "内容" }), { target: { value: "未保存の手編集" } });
    fireEvent.click(screen.getByRole("tab", { name: "このメモについてAIに質問・編集" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "AI draft" })).toBeVisible());
    expect(screen.queryByRole("textbox", { name: "内容" })).toBeNull();
    fireEvent.change(screen.getByRole("textbox", { name: "AI draft" }), { target: { value: "質問の書きかけ" } });
    fireEvent.click(screen.getByRole("tab", { name: "編集" }));
    expect(screen.getByRole("textbox", { name: "内容" })).toHaveValue("未保存の手編集");
    expect(screen.queryByRole("textbox", { name: "AI draft" })).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "このメモについてAIに質問・編集" }));
    expect(screen.getByRole("textbox", { name: "AI draft" })).toHaveValue("質問の書きかけ");
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
