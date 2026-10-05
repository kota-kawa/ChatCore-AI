import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MemoBulkBar } from "../components/memo/MemoBulkBar";
import { MemoHistoryPanel } from "../components/memo/MemoHistoryPanel";
import { MemoSidebar } from "../components/memo/MemoSidebar";
import { MemoPageContextProvider } from "../contexts/memo_page/memo_page_context";
import type { MemoSummary } from "../lib/memo/types";
import { createMemoPageControllerStub } from "./memo_page_context_harness";

const inTenDays = new Date(Date.now() + 10 * 24 * 60 * 60 * 1000 - 60 * 1000).toISOString();
const trashed: MemoSummary = {
  id: 4,
  title: "旅行の持ち物",
  excerpt: "- [ ] パスポート\n- [x] 充電器\n\nhttps://example.com/trip",
  trash_expires_at: inTenDays,
  deleted_at: "2026-10-01T00:00:00",
  share_token: "tok",
};

function renderTrash(overrides: Parameters<typeof createMemoPageControllerStub>[0] = {}) {
  const handlers = {
    openMemoDetail: vi.fn(async () => undefined),
    handleRestoreMemo: vi.fn(async () => undefined),
    handlePurgeMemo: vi.fn(async () => undefined),
    handleEmptyTrash: vi.fn(async () => undefined),
    handleToggleMemoTask: vi.fn(async () => undefined),
    handleTogglePin: vi.fn(async () => undefined),
  };
  const controller = createMemoPageControllerStub({
    archiveScope: "trash",
    memos: [trashed],
    otherMemos: [trashed],
    totalMemoCount: 1,
    hasActiveFilters: true,
    ...handlers,
    ...overrides,
  });
  render(
    <MemoPageContextProvider controller={controller}>
      <MemoHistoryPanel />
    </MemoPageContextProvider>,
  );
  return handlers;
}

describe("the trash list", () => {
  it("explains the 30 day rule and offers to empty the trash", () => {
    const handlers = renderTrash();
    expect(screen.getByRole("heading", { level: 2, name: "ゴミ箱" })).toBeTruthy();
    expect(screen.getByText("ゴミ箱のメモは 30 日後に完全に削除されます。")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "ゴミ箱を空にする" }));
    expect(handlers.handleEmptyTrash).toHaveBeenCalledTimes(1);
  });

  it("withholds Empty trash while a search or collection shows only part of the trash, and when it is empty", () => {
    renderTrash({ query: "旅行" });
    expect(screen.queryByRole("button", { name: "ゴミ箱を空にする" })).toBeNull();
  });

  it("shows an empty trash as such", () => {
    renderTrash({ memos: [], otherMemos: [], totalMemoCount: 0 });
    expect(screen.getByText("ゴミ箱は空です。")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "ゴミ箱を空にする" })).toBeNull();
  });

  it("makes cards read-only: no opening, pinning, copying, archiving or checklist toggling", () => {
    const handlers = renderTrash();
    const card = screen.getByRole("article");

    fireEvent.click(within(card).getByRole("heading", { name: "旅行の持ち物" }));
    expect(handlers.openMemoDetail).not.toHaveBeenCalled();
    expect(within(card).queryByRole("button", { name: "ピン留め" })).toBeNull();
    expect(within(card).queryByRole("button", { name: "アーカイブ" })).toBeNull();
    expect(within(card).queryByRole("button", { name: "全文をコピー" })).toBeNull();
    expect(within(card).queryByRole("button", { name: "その他の操作" })).toBeNull();

    // 本文のチェック欄は無効のまま
    // The checkboxes in the body stay disabled
    const boxes = within(card).getAllByRole("checkbox") as HTMLInputElement[];
    expect(boxes.every((box) => box.disabled)).toBe(true);
    fireEvent.click(boxes[0]);
    expect(handlers.handleToggleMemoTask).not.toHaveBeenCalled();
  });

  it("shows the days left and offers Restore and Delete permanently on each card", () => {
    const handlers = renderTrash();
    const card = screen.getByRole("article");
    expect(within(card).getByText("あと10日で削除")).toBeTruthy();

    fireEvent.click(within(card).getByRole("button", { name: "元に戻す" }));
    expect(handlers.handleRestoreMemo).toHaveBeenCalledWith(trashed);
    fireEvent.click(within(card).getByRole("button", { name: "完全に削除" }));
    expect(handlers.handlePurgeMemo).toHaveBeenCalledWith(trashed);
  });

  it("says deleting soon once the retention period is up", () => {
    const expired = { ...trashed, trash_expires_at: new Date(Date.now() - 1000).toISOString() };
    renderTrash({ memos: [expired], otherMemos: [expired] });
    expect(screen.getByText("まもなく削除")).toBeTruthy();
  });

  it("disables both card actions while one of them is running", () => {
    renderTrash({ actionLoadingId: "4" });
    const card = screen.getByRole("article");
    expect((within(card).getByRole("button", { name: "元に戻す" }) as HTMLButtonElement).disabled).toBe(true);
    expect((within(card).getByRole("button", { name: "完全に削除" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("selects a card by tapping it in bulk mode instead of showing the card actions", () => {
    const toggleSelectMemo = vi.fn();
    renderTrash({ isBulkMode: true, toggleSelectMemo });
    const card = screen.getByRole("article");
    expect(within(card).queryByRole("button", { name: "元に戻す" })).toBeNull();

    fireEvent.click(within(card).getByRole("heading", { name: "旅行の持ち物" }));
    expect(toggleSelectMemo).toHaveBeenCalledWith("4");
  });
});

describe("the bulk bar in the trash", () => {
  it("offers only Restore and Delete permanently", () => {
    const executeBulkAction = vi.fn(async () => undefined);
    const controller = createMemoPageControllerStub({
      archiveScope: "trash",
      memos: [trashed],
      isBulkMode: true,
      hasSelection: true,
      selectedIds: new Set(["4"]),
      executeBulkAction,
    });
    render(
      <MemoPageContextProvider controller={controller}>
        <MemoBulkBar />
      </MemoPageContextProvider>,
    );

    expect(screen.queryByRole("button", { name: /ピン留め|アーカイブ/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "元に戻す" }));
    expect(executeBulkAction).toHaveBeenLastCalledWith("restore");
    fireEvent.click(screen.getByRole("button", { name: "完全に削除" }));
    expect(executeBulkAction).toHaveBeenLastCalledWith("purge");
  });
});

describe("the trash entry in the sidebar", () => {
  it("switches the scope to the trash and marks it active", () => {
    const setArchiveScope = vi.fn();
    const setActiveCollectionId = vi.fn();
    const controller = createMemoPageControllerStub({ archiveScope: "trash", setArchiveScope, setActiveCollectionId });
    render(
      <MemoPageContextProvider controller={controller}>
        <MemoSidebar />
      </MemoPageContextProvider>,
    );

    const entry = screen.getByRole("button", { name: "ゴミ箱" });
    expect(entry.className).toContain("is-active");
    fireEvent.click(entry);
    expect(setActiveCollectionId).toHaveBeenCalledWith(null);
    expect(setArchiveScope).toHaveBeenCalledWith("trash");
  });
});
