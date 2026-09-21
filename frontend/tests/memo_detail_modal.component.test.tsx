import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { MemoDetailModal } from "../components/memo/MemoDetailModal";
import { MemoPageContextProvider } from "../contexts/memo_page/memo_page_context";
import type { MemoDetail } from "../lib/memo/types";
import { createMemoPageControllerStub } from "./memo_page_context_harness";

// エージェント面は next/router に依存するので、この面の描画対象外として差し替える
// The agent panel depends on next/router and is out of scope here, so it is stubbed
vi.mock("../components/chat_page/MiniChat", () => ({ MiniChat: () => null }));

const TITLE = "買い物";
const BODY = "牛乳を買う [店](https://example.com)";
const memo: MemoDetail = { id: 1, title: TITLE, ai_response: BODY };

// モーダルが実際に依存する状態だけを持つハーネス（プレビュー／編集、タイトル、本文）
// Harness holding just the state the modal really drives: preview vs edit, title and body
function DetailHarness() {
  const [detailPreviewMode, setDetailPreviewMode] = useState(true);
  const [detailEditTitle, setDetailEditTitle] = useState(TITLE);
  const [detailEditAiResponse, setDetailEditAiResponse] = useState(BODY);
  const controller = createMemoPageControllerStub({
    selectedMemo: memo,
    detailPreviewMode,
    setDetailPreviewMode,
    detailEditTitle,
    setDetailEditTitle,
    detailEditAiResponse,
    setDetailEditAiResponse,
    detailSaveStatus: "saved",
  });
  return (
    <MemoPageContextProvider controller={controller}>
      <MemoDetailModal />
    </MemoPageContextProvider>
  );
}

function previewPane() {
  return screen.getByRole("tabpanel");
}

describe("MemoDetailModal click-to-edit", () => {
  it("switches to the editor on a preview click and puts the caret at the end", () => {
    render(<DetailHarness />);
    expect(screen.queryByRole("textbox", { name: "内容" })).toBeNull();

    fireEvent.click(previewPane());

    const textarea = screen.getByRole("textbox", { name: "内容" }) as HTMLTextAreaElement;
    expect(document.activeElement).toBe(textarea);
    expect(textarea.selectionStart).toBe(BODY.length);
    expect(textarea.selectionEnd).toBe(BODY.length);
  });

  it("enters the editor with Enter while the preview pane is focused", () => {
    render(<DetailHarness />);
    const pane = previewPane();
    pane.focus();

    fireEvent.keyDown(pane, { key: "Enter" });

    expect(document.activeElement).toBe(screen.getByRole("textbox", { name: "内容" }));
  });

  it("leaves links inside the preview alone", () => {
    render(<DetailHarness />);
    const link = previewPane().querySelector("a");
    expect(link).not.toBeNull();

    fireEvent.click(link as HTMLAnchorElement);

    expect(screen.getByRole("tabpanel")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "内容" })).toBeNull();
  });

  it("does not switch modes when the click ends a text selection", () => {
    render(<DetailHarness />);
    const pane = previewPane();
    const text = document.createTreeWalker(pane, NodeFilter.SHOW_TEXT).nextNode();
    expect(text).not.toBeNull();
    const range = document.createRange();
    range.setStart(text as Node, 0);
    range.setEnd(text as Node, 2);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);

    fireEvent.click(pane);

    expect(screen.getByRole("tabpanel")).toBeInTheDocument();
    selection?.removeAllRanges();
  });

  it("opens the title input when the title is clicked", () => {
    render(<DetailHarness />);

    fireEvent.click(screen.getByText("買い物", { selector: "h2" }));

    const input = screen.getByRole("textbox", { name: "タイトル" }) as HTMLInputElement;
    expect(document.activeElement).toBe(input);
    expect(input.selectionStart).toBe(TITLE.length);
  });
});
