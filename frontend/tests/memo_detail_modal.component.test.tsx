import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MemoDetailModal } from "../components/memo/MemoDetailModal";
import { MemoPageContextProvider } from "../contexts/memo_page/memo_page_context";
import type { StepExecutionResult } from "../lib/chat_page/ai_agent";
import type { MiniChatProps } from "../lib/chat_page/mini_chat_runtime";
import type { MemoEditPayload } from "../lib/memo/agent_edits";
import type { MemoDetail } from "../lib/memo/types";
import { changeMemoEditor, memoEditorValue } from "./memo_editor_harness";
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
  const [detailSourceMode, setDetailSourceMode] = useState(false);
  const [detailEditTitle, setDetailEditTitle] = useState(TITLE);
  const [detailEditAiResponse, setDetailEditAiResponse] = useState(body);
  const controller = createMemoPageControllerStub({
    selectedMemo: memo,
    detailSourceMode,
    setDetailSourceMode,
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

describe("MemoDetailModal live editing", () => {
  it("opens with an editable formatted document and a source toggle", () => {
    render(<DetailHarness body={"# 買い物\n\n**牛乳**を買う"} />);
    expect(screen.getByRole("textbox", { name: "内容" })).toHaveAttribute("contenteditable", "true");
    expect(document.querySelector(".memo-live-preview__heading")).toHaveTextContent("買い物");
    expect(document.querySelector(".memo-live-preview__strong")).toHaveTextContent("牛乳");
    expect(screen.queryByRole("tab", { name: "プレビュー" })).toBeNull();
    const source = screen.getByRole("button", { name: "Markdown原文" });
    expect(source).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(source);
    expect(source).toHaveAttribute("aria-pressed", "true");
    expect(memoEditorValue(screen.getByRole("textbox", { name: "内容" }))).toBe("# 買い物\n\n**牛乳**を買う");
  });

  it("keeps links safe and opens them in another tab", () => {
    render(<DetailHarness />);
    const link = screen.getByRole("link", { name: "店" });
    expect(link).toHaveAttribute("href", "https://example.com");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("makes the title directly editable", () => {
    render(<DetailHarness />);
    const input = screen.getByRole("textbox", { name: "タイトル" });
    fireEvent.change(input, { target: { value: "明日の買い物" } });
    expect(input).toHaveValue("明日の買い物");
  });
});

describe("MemoDetailModal agent edits", () => {
  const AGENT_BODY = "牛乳を買う\n卵を買う";

  // エージェント面を開くとモーダルが幅を matchMedia で調べる。jsdom には無いので PC 幅として答える
  // Opening the agent panel makes the modal query matchMedia, which jsdom lacks; answer as a desktop width
  beforeEach(() => {
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: false, media: query, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }));
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
    const editor = screen.getByRole("textbox", { name: "内容" });
    const titleInput = screen.getByRole("textbox", { name: "タイトル" }) as HTMLInputElement;
    const apply = async (edit: MemoEditPayload) => {
      let result: StepExecutionResult | undefined;
      await act(async () => {
        result = await onMemoEdit!(edit);
      });
      return result;
    };
    return { editor, titleInput, apply };
  }

  it("applies a partial edit on top of unsaved manual edits", async () => {
    const { editor, titleInput, apply } = renderWithAgent();
    changeMemoEditor(editor, "牛乳を買う\n卵を買う\nパンを買う");

    const result = await apply({
      kind: "edits",
      edits: [{ old_string: "卵を買う", new_string: "卵を2個買う" }],
      title: "買い物リスト",
    });

    expect(result).toEqual({ ok: true });
    expect(memoEditorValue(editor)).toBe("牛乳を買う\n卵を2個買う\nパンを買う");
    expect(titleInput.value).toBe("買い物リスト");
  });

  it("leaves the body and title untouched when an edit no longer matches", async () => {
    const { editor, titleInput, apply } = renderWithAgent();
    changeMemoEditor(editor, "牛乳を買う\n卵を3個買う");

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
    expect(memoEditorValue(editor)).toBe("牛乳を買う\n卵を3個買う");
    expect(titleInput.value).toBe(TITLE);
  });

  it("replaces the whole body for a full replacement", async () => {
    const { editor, apply } = renderWithAgent();

    const result = await apply({ kind: "content", content: "Buy milk\nBuy eggs" });

    expect(result).toEqual({ ok: true });
    expect(memoEditorValue(editor)).toBe("Buy milk\nBuy eggs");
  });
});
