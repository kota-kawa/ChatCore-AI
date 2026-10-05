import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { useState } from "react";
import type { KeyedMutator } from "swr";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MemoDetailModal } from "../components/memo/MemoDetailModal";
import { MemoMarkdown } from "../components/memo/MemoMarkdown";
import { MemoPageContextProvider } from "../contexts/memo_page/memo_page_context";
import { useMemoListContinuation } from "../hooks/memo_page/use_memo_list_continuation";
import { useMemoPageItemActions } from "../hooks/memo_page/use_memo_page_item_actions";
import { loadMemoDetail, updateMemo } from "../lib/memo/api";
import type { MemoDetail, MemoListState, MemoSummary } from "../lib/memo/types";
import { createMemoPageControllerStub } from "./memo_page_context_harness";

vi.mock("../components/chat_page/MiniChat", () => ({ MiniChat: () => null }));
vi.mock("../lib/memo/api", () => ({
  deleteMemo: vi.fn(),
  loadMemoDetail: vi.fn(),
  setMemoArchived: vi.fn(),
  setMemoPinned: vi.fn(),
  updateMemo: vi.fn(),
}));

const CHECKLIST = "- [ ] パスポート\n- [x] 常備薬\n\n[本](https://example.com/books)";

function boxes(container: HTMLElement) {
  return Array.from(container.querySelectorAll<HTMLInputElement>("input[type='checkbox']"));
}

describe("MemoMarkdown checklists and links", () => {
  it("keeps the boxes read-only without a toggle handler", () => {
    const { container } = render(<MemoMarkdown text={CHECKLIST} />);
    expect(boxes(container).map((box) => box.disabled)).toEqual([true, true]);
  });

  it("reports the tapped box with the number of rendered boxes", () => {
    const onToggleTask = vi.fn(() => true);
    const { container } = render(<MemoMarkdown text={CHECKLIST} onToggleTask={onToggleTask} />);
    expect(boxes(container).map((box) => box.disabled)).toEqual([false, false]);

    fireEvent.click(boxes(container)[1]);
    expect(onToggleTask).toHaveBeenCalledWith(1, [
      { label: "パスポート", checked: false },
      { label: "常備薬", checked: true },
    ]);
    expect(boxes(container).map((box) => box.getAttribute("aria-label"))).toEqual(["パスポート", "常備薬"]);
  });

  it("marks the click as handled so the surrounding click-to-open does not fire", () => {
    const outerClick = vi.fn((event: React.MouseEvent) => event.defaultPrevented);
    const { container } = render(
      <div onClick={outerClick}>
        <MemoMarkdown text={CHECKLIST} onToggleTask={() => true} />
      </div>,
    );
    fireEvent.click(boxes(container)[0]);
    expect(outerClick).toHaveReturnedWith(true);

    // 欄から離れた位置（jsdom の矩形は原点にある）の文字は、従来どおり外側のクリックになる
    // Text away from the box (jsdom rects sit at the origin) still counts as the outer click
    fireEvent.click(screen.getByText("パスポート", { exact: false }), { clientX: 300, clientY: 300 });
    expect(outerClick).toHaveLastReturnedWith(false);
  });

  it("opens links in a new tab", () => {
    render(<MemoMarkdown text={CHECKLIST} />);
    const link = screen.getByRole("link", { name: "本" });
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
  });
});

const memo: MemoDetail = { id: 1, title: "旅行", ai_response: CHECKLIST };

function DetailHarness() {
  const [detailPreviewMode, setDetailPreviewMode] = useState(true);
  const [detailEditTitle, setDetailEditTitle] = useState("旅行");
  const [detailEditAiResponse, setDetailEditAiResponse] = useState(CHECKLIST);
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

function bodyTextarea() {
  return document.getElementById("memo-detail-ai-response") as HTMLTextAreaElement;
}

describe("MemoDetailModal editing", () => {
  it("ticks a checklist box in the preview without entering edit mode", () => {
    render(<DetailHarness />);
    fireEvent.click(boxes(screen.getByRole("tabpanel"))[0]);

    expect(bodyTextarea().value).toBe(CHECKLIST.replace("- [ ] パスポート", "- [x] パスポート"));
    expect(bodyTextarea().hidden).toBe(true);
    expect(screen.queryByRole("tabpanel")).not.toBeNull();
  });

  it("keeps the same textarea across preview and edit so its caret and undo history survive", () => {
    render(<DetailHarness />);
    const textarea = bodyTextarea();
    expect(textarea.hidden).toBe(true);

    fireEvent.click(screen.getByRole("tab", { name: "編集" }));
    expect(bodyTextarea()).toBe(textarea);
    expect(textarea.hidden).toBe(false);
    textarea.setSelectionRange(4, 4);

    fireEvent.click(screen.getByRole("tab", { name: "プレビュー" }));
    fireEvent.click(screen.getByRole("tab", { name: "編集" }));
    expect(bodyTextarea()).toBe(textarea);
    expect(document.activeElement).toBe(textarea);
    expect(textarea.selectionStart).toBe(4);
  });

  it("shows the formatting toolbar only while editing and formats the caret line", () => {
    render(<DetailHarness />);
    expect(screen.queryByRole("toolbar", { name: "書式" })).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: "編集" }));
    const textarea = bodyTextarea();
    textarea.setSelectionRange(textarea.value.length, textarea.value.length);
    fireEvent.click(screen.getByRole("button", { name: "箇条書き" }));
    expect(textarea.value.endsWith("- [本](https://example.com/books)")).toBe(true);
    expect(document.activeElement).toBe(textarea);
  });

  it("moves from the title to the body on Enter, but not while an IME is composing", () => {
    render(<DetailHarness />);
    fireEvent.click(screen.getByRole("tab", { name: "編集" }));
    const title = screen.getByRole("textbox", { name: "タイトル" });
    title.focus();

    fireEvent.keyDown(title, { key: "Enter", isComposing: true });
    expect(document.activeElement).toBe(title);
    fireEvent.keyDown(title, { key: "Enter" });
    expect(document.activeElement).toBe(bodyTextarea());
  });
});

function ContinuationHarness() {
  useMemoListContinuation();
  const [value, setValue] = useState("- [ ] 卵");
  return (
    <>
      <textarea aria-label="memo" data-memo-editor="" value={value} onChange={(event) => setValue(event.target.value)} />
      <textarea aria-label="other" defaultValue="- [ ] 卵" />
    </>
  );
}

function pressEnter(textarea: HTMLTextAreaElement, init: InputEventInit = {}) {
  textarea.setSelectionRange(textarea.value.length, textarea.value.length);
  const event = new InputEvent("beforeinput", { inputType: "insertLineBreak", bubbles: true, cancelable: true, ...init });
  act(() => {
    textarea.dispatchEvent(event);
  });
  return event.defaultPrevented;
}

describe("useMemoListContinuation", () => {
  it("continues the list in a memo editor and leaves other textareas alone", () => {
    render(<ContinuationHarness />);
    const editor = screen.getByRole("textbox", { name: "memo" }) as HTMLTextAreaElement;
    expect(pressEnter(editor)).toBe(true);
    expect(editor.value).toBe("- [ ] 卵\n- [ ] ");
    expect(editor.selectionStart).toBe(editor.value.length);

    const other = screen.getByRole("textbox", { name: "other" }) as HTMLTextAreaElement;
    expect(pressEnter(other)).toBe(false);
    expect(other.value).toBe("- [ ] 卵");
  });

  it("does not act on the Enter that confirms an IME conversion", () => {
    render(<ContinuationHarness />);
    const editor = screen.getByRole("textbox", { name: "memo" }) as HTMLTextAreaElement;
    expect(pressEnter(editor, { isComposing: true })).toBe(false);
    expect(editor.value).toBe("- [ ] 卵");
  });
});

const mutateMock = vi.fn(async () => undefined);
const mutate = mutateMock as unknown as KeyedMutator<MemoListState>;
const showFlash = vi.fn();
const updateMemoListOptimistically = vi.fn(async (_updater: unknown, _ids: unknown) => undefined);
const noop = () => undefined;
const asyncNoop = async () => undefined;

function useItemActionsHarness() {
  return useMemoPageItemActions({
    mutate,
    updateMemoListOptimistically,
    showFlash,
    selectedMemoId: undefined,
    patchSelectedMemoOptimistically: noop,
    refreshSelectedMemoIfNeeded: asyncNoop,
    startMemoDetailCloseAnimation: noop,
  });
}

describe("ticking a checklist box on a list card", () => {
  const card: MemoSummary = { id: 7, title: "旅行", excerpt: "- [ ] パスポート\n- [x] 常備薬" };
  const shown = [{ label: "パスポート", checked: false }, { label: "常備薬", checked: true }];

  beforeEach(() => {
    vi.mocked(updateMemo).mockResolvedValue(undefined);
  });

  it("rewrites the full body, which is longer than the card excerpt, without resending the title", async () => {
    vi.mocked(loadMemoDetail).mockResolvedValue({ id: 7, title: "保存したメモ", ai_response: `${card.excerpt}\n- [ ] 続き` });
    const { result } = renderHook(() => useItemActionsHarness());
    await act(async () => {
      await result.current.handleToggleMemoTask(card, 0, shown);
    });
    expect(updateMemo).toHaveBeenCalledWith(
      7,
      { ai_response: "- [x] パスポート\n- [x] 常備薬\n- [ ] 続き" },
      expect.any(String),
    );
    // カードは保存を待たずに切り替わる
    // The card flips without waiting for the save
    const [updater] = updateMemoListOptimistically.mock.calls[0] as unknown as [(memo: MemoSummary) => MemoSummary];
    expect(updater(card).excerpt).toBe("- [x] パスポート\n- [x] 常備薬");
    expect(mutateMock).toHaveBeenCalled();
  });

  it("writes nothing when the body no longer matches what the card shows", async () => {
    vi.mocked(loadMemoDetail).mockResolvedValue({ id: 7, title: "旅行", ai_response: "- [ ] 別の端末で追加\n- [x] 常備薬" });
    const { result } = renderHook(() => useItemActionsHarness());
    await act(async () => {
      await result.current.handleToggleMemoTask(card, 0, shown);
    });
    expect(updateMemo).not.toHaveBeenCalled();
    expect(showFlash).toHaveBeenCalledWith("error", expect.any(String));
    // 取り直した一覧が、先に切り替えたカードの表示を元に戻す
    // The reloaded list puts the optimistically flipped card back
    expect(mutateMock).toHaveBeenCalled();
  });
});

describe("ticking the first line of a memo whose title came from that line", () => {
  it("re-derives the title so the card does not show the stale line as a heading", async () => {
    vi.mocked(updateMemo).mockResolvedValue(undefined);
    const card: MemoSummary = { id: 8, title: "- [ ] 牛乳", excerpt: "- [ ] 牛乳" };
    vi.mocked(loadMemoDetail).mockResolvedValue({ id: 8, title: "- [ ] 牛乳", ai_response: "- [ ] 牛乳" });
    const { result } = renderHook(() => useItemActionsHarness());
    await act(async () => {
      await result.current.handleToggleMemoTask(card, 0, [{ label: "牛乳", checked: false }]);
    });
    expect(updateMemo).toHaveBeenCalledWith(8, { title: "- [x] 牛乳", ai_response: "- [x] 牛乳" }, expect.any(String));
    const [updater] = updateMemoListOptimistically.mock.calls.at(-1) as unknown as [(memo: MemoSummary) => MemoSummary];
    expect(updater(card)).toMatchObject({ title: "- [x] 牛乳", excerpt: "- [x] 牛乳" });
  });
});

describe("links inside a list card", () => {
  it("are excluded from the click that opens the card", async () => {
    const { MemoHistoryPanel } = await import("../components/memo/MemoHistoryPanel");
    const openMemoDetail = vi.fn(async () => true);
    const memos: MemoSummary[] = [{ id: 1, title: "本", excerpt: "[本](https://example.com/books) を読む" }];
    const controller = createMemoPageControllerStub({
      memos, otherMemos: memos, pinnedMemos: [], totalMemoCount: 1, openMemoDetail,
    });
    render(
      <MemoPageContextProvider controller={controller}>
        <MemoHistoryPanel />
      </MemoPageContextProvider>,
    );
    const link = screen.getByRole("link", { name: "本" });
    link.addEventListener("click", (event) => event.preventDefault());
    fireEvent.click(link);
    expect(openMemoDetail).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText("を読む", { exact: false }), { clientX: 300, clientY: 300 });
    expect(openMemoDetail).toHaveBeenCalledWith("1");
  });
});
