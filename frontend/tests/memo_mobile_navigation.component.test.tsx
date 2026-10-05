import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MemoComposer } from "../components/memo/MemoComposer";
import { MemoDetailModal } from "../components/memo/MemoDetailModal";
import { MemoPageContextProvider } from "../contexts/memo_page/memo_page_context";
import { useMemoDetailRoute } from "../hooks/memo_page/use_memo_detail_route";
import type { MemoComposeFormState, MemoDetail } from "../lib/memo/types";
import { createMemoPageControllerStub } from "./memo_page_context_harness";

vi.mock("../components/chat_page/MiniChat", () => ({ MiniChat: () => null }));

// next/router の代わり。push / replace / back は URL のクエリを書き換え、再描画はテスト側で起こす
// Stand-in for next/router: push / replace / back rewrite the query; the test triggers re-renders
const routerState = vi.hoisted(() => ({
  query: {} as Record<string, string>,
  history: [] as Record<string, string>[],
}));
const routerMock = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  back: vi.fn(),
}));
vi.mock("next/router", () => ({
  useRouter: () => ({ isReady: true, pathname: "/memo", query: routerState.query, ...routerMock }),
}));

describe("useMemoDetailRoute", () => {
  const openMemoDetail = vi.fn(async () => undefined);
  const closeMemoDetail = vi.fn(async () => undefined);

  beforeEach(() => {
    routerState.query = {};
    routerState.history = [];
    routerMock.push.mockImplementation(async (url: { query: Record<string, string> }) => {
      routerState.history.push(routerState.query);
      routerState.query = url.query;
      return true;
    });
    routerMock.replace.mockImplementation(async (url: { query: Record<string, string> }) => {
      routerState.query = url.query;
      return true;
    });
    routerMock.back.mockImplementation(() => {
      routerState.query = routerState.history.pop() ?? {};
    });
  });

  function renderRoute(initialOpen: string | null = null) {
    return renderHook(({ open }: { open: string | null }) => useMemoDetailRoute({ openMemoId: open, openMemoDetail, closeMemoDetail }), {
      initialProps: { open: initialOpen },
    });
  }

  it("adds a history entry when a memo opens and goes back when it is closed from the UI", () => {
    const { rerender } = renderRoute();
    expect(routerMock.push).not.toHaveBeenCalled();

    rerender({ open: "12" });
    expect(routerMock.push).toHaveBeenCalledTimes(1);
    expect(routerState.query).toEqual({ memo: "12" });

    rerender({ open: null });
    expect(routerMock.back).toHaveBeenCalledTimes(1);
    expect(routerState.query).toEqual({});
    expect(closeMemoDetail).not.toHaveBeenCalled();
  });

  it("closes the detail when the back button removes the memo from the URL", () => {
    const { rerender } = renderRoute();
    rerender({ open: "12" });
    // 実際のルーターは push のあと URL を反映して再描画する
    // The real router re-renders with the new URL after the push
    rerender({ open: "12" });

    // 「戻る」: URL から memo が消えるが、詳細はまだ開いている
    // Back: the memo leaves the URL while the detail is still open
    routerState.query = {};
    rerender({ open: "12" });
    expect(closeMemoDetail).toHaveBeenCalledTimes(1);
    expect(routerMock.push).toHaveBeenCalledTimes(1);

    rerender({ open: null });
    expect(routerMock.back).not.toHaveBeenCalled();
  });

  it("ignores a memo value in the URL that is not an id", () => {
    // この値は API のパスに入る。数字以外を通すと別の API を叩かせられる
    // The value ends up in an API path; anything but digits could aim the request elsewhere
    routerState.query = { memo: "../../logout" };
    renderRoute();
    expect(openMemoDetail).not.toHaveBeenCalled();
  });

  it("opens the memo named in a directly opened URL and drops it from the URL without going back", () => {
    routerState.query = { memo: "7", saved: "0" };
    const { rerender } = renderRoute();
    expect(openMemoDetail).toHaveBeenCalledWith("7");

    rerender({ open: "7" });
    expect(routerMock.push).not.toHaveBeenCalled();

    rerender({ open: null });
    expect(routerMock.back).not.toHaveBeenCalled();
    expect(routerMock.replace).toHaveBeenCalledTimes(1);
    expect(routerState.query).toEqual({ saved: "0" });
  });
});

const emptyForm: MemoComposeFormState = { ai_response: "", title: "", collection_id: null, background_color: null };

function ComposerHarness({ initial, onSubmit }: { initial: MemoComposeFormState; onSubmit: () => void }) {
  const [formState, setFormState] = useState(initial);
  const [isComposeExpanded, setIsComposeExpanded] = useState(true);
  const hasComposeDraft = Boolean(formState.ai_response.trim() || formState.title.trim() || formState.background_color);
  const controller = createMemoPageControllerStub({
    formState,
    setFormState,
    hasComposeDraft,
    composeIsExpanded: isComposeExpanded || hasComposeDraft,
    setIsComposeExpanded,
    handleFormChange: (event) => setFormState((prev) => ({ ...prev, [event.target.name]: event.target.value })),
    handleSubmitMemo: async (event) => {
      event.preventDefault();
      onSubmit();
    },
  });
  return (
    <MemoPageContextProvider controller={controller}>
      <MemoComposer />
      <button type="button">outside</button>
      <div role="listbox"><button type="button">picker option</button></div>
    </MemoPageContextProvider>
  );
}

describe("MemoComposer outside click", () => {
  it("saves a memo that has a body", () => {
    const onSubmit = vi.fn();
    render(<ComposerHarness initial={{ ...emptyForm, ai_response: "牛乳" }} onSubmit={onSubmit} />);
    fireEvent.click(screen.getByRole("button", { name: "outside" }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("collapses an untouched composer and keeps a title-only draft open", () => {
    const onSubmit = vi.fn();
    const { unmount } = render(<ComposerHarness initial={emptyForm} onSubmit={onSubmit} />);
    fireEvent.click(screen.getByRole("button", { name: "outside" }));
    expect(screen.queryByRole("textbox", { name: "本文" })).toBeNull();
    unmount();

    render(<ComposerHarness initial={{ ...emptyForm, title: "題だけ" }} onSubmit={onSubmit} />);
    fireEvent.click(screen.getByRole("button", { name: "outside" }));
    expect(screen.queryByRole("textbox", { name: "本文" })).not.toBeNull();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("ignores clicks inside the composer and in pickers rendered outside it", () => {
    const onSubmit = vi.fn();
    render(<ComposerHarness initial={{ ...emptyForm, ai_response: "牛乳" }} onSubmit={onSubmit} />);
    fireEvent.click(screen.getByRole("textbox", { name: "本文" }));
    fireEvent.click(screen.getByRole("button", { name: "picker option" }));
    expect(onSubmit).not.toHaveBeenCalled();
  });
});

describe("MemoDetailModal actions while reading", () => {
  const memo: MemoDetail = { id: 3, title: "旅行", ai_response: "本文", is_pinned: true };

  function renderDetail(previewMode: boolean) {
    const handlers = {
      handleTogglePin: vi.fn(async () => undefined),
      handleToggleArchive: vi.fn(async () => undefined),
      handleDeleteMemo: vi.fn(async () => undefined),
      openShareModal: vi.fn(async () => undefined),
    };
    const controller = createMemoPageControllerStub({
      selectedMemo: memo,
      detailPreviewMode: previewMode,
      detailEditTitle: "旅行",
      detailEditAiResponse: "本文",
      detailSaveStatus: "saved",
      ...handlers,
    });
    render(
      <MemoPageContextProvider controller={controller}>
        <MemoDetailModal />
      </MemoPageContextProvider>,
    );
    return handlers;
  }

  it("offers pin, archive, share and delete for the open memo", () => {
    const handlers = renderDetail(true);
    const toolbar = screen.getByRole("toolbar", { name: "操作" });
    expect(toolbar).not.toBeNull();

    const pin = screen.getByRole("button", { name: "ピン留め解除" });
    expect(pin.getAttribute("aria-pressed")).toBe("true");
    act(() => { fireEvent.click(pin); });
    fireEvent.click(screen.getByRole("button", { name: "アーカイブ" }));
    fireEvent.click(screen.getByRole("button", { name: "共有設定" }));
    fireEvent.click(screen.getByRole("button", { name: "削除" }));
    expect(handlers.handleTogglePin).toHaveBeenCalledWith(memo);
    expect(handlers.handleToggleArchive).toHaveBeenCalledWith(memo);
    expect(handlers.openShareModal).toHaveBeenCalledWith(memo);
    expect(handlers.handleDeleteMemo).toHaveBeenCalledWith(memo);
  });

  it("gives the slot to the formatting toolbar while editing", () => {
    renderDetail(false);
    expect(screen.queryByRole("toolbar", { name: "操作" })).toBeNull();
    expect(screen.queryByRole("toolbar", { name: "書式" })).not.toBeNull();
  });
});

describe("list card titles", () => {
  it("drops a title that only repeats the first line of the body", async () => {
    const { MemoHistoryPanel } = await import("../components/memo/MemoHistoryPanel");
    const memos = [
      { id: 1, title: "歯医者 10/12 15:00 予約", excerpt: "歯医者 10/12 15:00 予約" },
      { id: 2, title: "買い物", excerpt: "牛乳を買う" },
    ];
    const controller = createMemoPageControllerStub({ memos, otherMemos: memos, pinnedMemos: [], totalMemoCount: 2 });
    render(
      <MemoPageContextProvider controller={controller}>
        <MemoHistoryPanel />
      </MemoPageContextProvider>,
    );
    expect(screen.getAllByText("歯医者 10/12 15:00 予約")).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "買い物" })).not.toBeNull();
  });
});
