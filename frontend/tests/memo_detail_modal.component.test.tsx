import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MemoDetailModal } from "../components/memo/MemoDetailModal";
import { MemoPageContextProvider } from "../contexts/memo_page/memo_page_context";
import type { StepExecutionResult } from "../lib/chat_page/ai_agent";
import type { MiniChatProps } from "../lib/chat_page/mini_chat_runtime";
import type { MemoEditPayload } from "../lib/memo/agent_edits";
import type { MemoDetail } from "../lib/memo/types";
import { createMemoPageControllerStub } from "./memo_page_context_harness";

// エージェント面は next/router に依存するので描画せず、モーダルが渡す props だけを受け取る
// The agent panel depends on next/router, so it is not rendered; the stub only records the props the modal passes
const miniChatMock = vi.hoisted(() => vi.fn((_props: MiniChatProps) => null));
vi.mock("../components/chat_page/MiniChat", () => ({ MiniChat: miniChatMock }));

const TITLE = "買い物";
const BODY = "牛乳を買う [店](https://example.com)";
const memo: MemoDetail = { id: 1, title: TITLE, ai_response: BODY };

// モーダルが実際に依存する状態だけを持つハーネス（プレビュー／編集、タイトル、本文、エージェント面の開閉）
// Harness holding just the state the modal really drives: preview vs edit, title, body and the agent panel
function DetailHarness({ body = BODY, agentOpen = false }: { body?: string; agentOpen?: boolean }) {
  const [detailPreviewMode, setDetailPreviewMode] = useState(true);
  const [detailEditTitle, setDetailEditTitle] = useState(TITLE);
  const [detailEditAiResponse, setDetailEditAiResponse] = useState(body);
  const controller = createMemoPageControllerStub({
    selectedMemo: memo,
    detailPreviewMode,
    setDetailPreviewMode,
    detailEditTitle,
    setDetailEditTitle,
    detailEditAiResponse,
    setDetailEditAiResponse,
    detailSaveStatus: "saved",
    isMemoAgentOpen: agentOpen,
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
  it("switches to the editor at the clicked character", () => {
    render(<DetailHarness />);
    expect(screen.queryByRole("textbox", { name: "内容" })).toBeNull();

    const text = document.createTreeWalker(previewPane(), NodeFilter.SHOW_TEXT).nextNode()!;
    const hitTest = vi.fn(() => ({ offsetNode: text, offset: 3 }));
    Object.defineProperty(document, "caretPositionFromPoint", { configurable: true, value: hitTest });
    fireEvent.click(previewPane(), { clientX: 120, clientY: 80 });
    delete (document as unknown as { caretPositionFromPoint?: unknown }).caretPositionFromPoint;
    expect(hitTest).toHaveBeenCalledWith(120, 80);

    const textarea = screen.getByRole("textbox", { name: "内容" }) as HTMLTextAreaElement;
    expect(document.activeElement).toBe(textarea);
    expect(textarea.selectionStart).toBe(3);
    expect(textarea.selectionEnd).toBe(3);
  });

  it("converts CRLF source offsets to the textarea's LF offsets", () => {
    render(<DetailHarness body={"# title\r\n\r\n次の行"} />);
    const text = screen.getByText("次の行").firstChild!;
    Object.defineProperty(document, "caretPositionFromPoint", {
      configurable: true, value: () => ({ offsetNode: text, offset: 1 }),
    });
    fireEvent.click(previewPane(), { clientX: 120, clientY: 80 });
    delete (document as unknown as { caretPositionFromPoint?: unknown }).caretPositionFromPoint;
    const textarea = screen.getByRole("textbox", { name: "内容" }) as HTMLTextAreaElement;
    expect(textarea.selectionStart).toBe("# title\n\n次".length);
  });

  it("enters the editor with Enter while the preview pane is focused", () => {
    render(<DetailHarness />);
    const pane = previewPane();
    pane.focus();

    fireEvent.keyDown(pane, { key: "Enter" });

    const textarea = screen.getByRole("textbox", { name: "内容" }) as HTMLTextAreaElement;
    expect(document.activeElement).toBe(textarea);
    expect(textarea.selectionStart).toBe(BODY.length);
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

    const title = screen.getByText("買い物", { selector: "h2" });
    const range = document.createRange();
    range.setStart(title.firstChild!, 1);
    range.collapse(true);
    Object.defineProperty(document, "caretRangeFromPoint", { configurable: true, value: () => range });
    fireEvent.click(title, { clientX: 40, clientY: 40 });
    delete (document as unknown as { caretRangeFromPoint?: unknown }).caretRangeFromPoint;

    const input = screen.getByRole("textbox", { name: "タイトル" }) as HTMLInputElement;
    expect(document.activeElement).toBe(input);
    expect(input.selectionStart).toBe(1);
  });
});

describe("MemoDetailModal agent edits", () => {
  const AGENT_BODY = "牛乳を買う\n卵を買う";

  // エージェント面を開くとモーダルが幅を matchMedia で調べる。jsdom には無いので PC 幅として答える
  // Opening the agent panel makes the modal query matchMedia, which jsdom lacks; answer as a desktop width
  beforeEach(() => {
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: false, media: query }));
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  // 最初の描画で渡されたハンドラを返す。後の手編集を ref で拾えているか（古い本文を掴んでいないか）を確かめるため
  // Returns the handler from the first render, so the tests prove later manual edits are read through the ref
  function renderWithAgent() {
    render(<DetailHarness body={AGENT_BODY} agentOpen />);
    const onMemoEdit = miniChatMock.mock.calls[0]?.[0].onMemoEdit;
    expect(onMemoEdit).toBeTypeOf("function");
    fireEvent.click(screen.getByRole("tab", { name: "編集" }));
    const textarea = screen.getByRole("textbox", { name: "内容" }) as HTMLTextAreaElement;
    const titleInput = screen.getByRole("textbox", { name: "タイトル" }) as HTMLInputElement;
    const apply = async (edit: MemoEditPayload) => {
      let result: StepExecutionResult | undefined;
      await act(async () => {
        result = await onMemoEdit!(edit);
      });
      return result;
    };
    return { textarea, titleInput, apply };
  }

  it("applies a partial edit on top of unsaved manual edits", async () => {
    const { textarea, titleInput, apply } = renderWithAgent();
    fireEvent.change(textarea, { target: { value: "牛乳を買う\n卵を買う\nパンを買う" } });

    const result = await apply({
      kind: "edits",
      edits: [{ old_string: "卵を買う", new_string: "卵を2個買う" }],
      title: "買い物リスト",
    });

    expect(result).toEqual({ ok: true });
    expect(textarea.value).toBe("牛乳を買う\n卵を2個買う\nパンを買う");
    expect(titleInput.value).toBe("買い物リスト");
  });

  it("leaves the body and title untouched when an edit no longer matches", async () => {
    const { textarea, titleInput, apply } = renderWithAgent();
    fireEvent.change(textarea, { target: { value: "牛乳を買う\n卵を3個買う" } });

    const result = await apply({
      kind: "edits",
      edits: [
        { old_string: "牛乳を買う", new_string: "牛乳を1本買う" },
        { old_string: "卵を買う", new_string: "卵を2個買う" },
      ],
      title: "買い物リスト",
    });

    expect(result).toEqual({
      ok: false,
      message: "メモが変更されたため、この編集を適用できませんでした。もう一度編集を依頼してください。",
      needsReplan: false,
    });
    expect(textarea.value).toBe("牛乳を買う\n卵を3個買う");
    expect(titleInput.value).toBe(TITLE);
  });

  it("replaces the whole body for a full replacement", async () => {
    const { textarea, apply } = renderWithAgent();

    const result = await apply({ kind: "content", content: "Buy milk\nBuy eggs" });

    expect(result).toEqual({ ok: true });
    expect(textarea.value).toBe("Buy milk\nBuy eggs");
  });
});
