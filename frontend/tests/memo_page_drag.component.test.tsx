import { act, renderHook } from "@testing-library/react";
import type { DragEvent } from "react";
import type { KeyedMutator } from "swr";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useMemoPageDrag } from "../hooks/memo_page/use_memo_page_drag";
import { reorderMemos } from "../lib/memo/api";
import type { MemoListState, MemoSummary } from "../lib/memo/types";

vi.mock("../lib/memo/api", () => ({
  reorderMemos: vi.fn(),
}));
vi.mock("../lib/memo/utils", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/memo/utils")>();
  return {
    ...actual,
    captureCardSnapshot: vi.fn(() => new Map()),
    computeProjectedOrderFromSnapshot: vi.fn(() => ["2", "1", "3"]),
    setMemoDragImage: vi.fn(),
  };
});

const memos: MemoSummary[] = [{ id: 1 }, { id: 2 }, { id: 3 }];

function makeDragStartEvent() {
  return {
    preventDefault: vi.fn(),
    dataTransfer: { effectAllowed: "", setData: vi.fn() },
  } as unknown as DragEvent<HTMLElement>;
}

function makeDragOverEvent() {
  return {
    preventDefault: vi.fn(),
    clientX: 0,
    clientY: 0,
    dataTransfer: { dropEffect: "" },
  } as unknown as DragEvent<HTMLUListElement>;
}

function makeDropEvent(sourceId: string) {
  return {
    preventDefault: vi.fn(),
    dataTransfer: { getData: () => sourceId },
  } as unknown as DragEvent<HTMLElement>;
}

// モックは再レンダーを跨いで同一インスタンスである必要がある（SWR の mutate は安定参照のため）
// Mocks must stay stable across re-renders, mirroring SWR's stable mutate reference
const mutateMock = vi.fn(async (..._args: unknown[]) => undefined);
const mutate = mutateMock as unknown as KeyedMutator<MemoListState>;
const showFlash = vi.fn();
const closeMemoActionMenu = vi.fn();

function useDragHarness(isBulkMode: boolean) {
  return useMemoPageDrag({
    memos,
    mutate,
    showFlash,
    archiveScope: "active",
    sortMode: "manual",
    query: "",
    isBulkMode,
    closeMemoActionMenu,
  });
}

describe("useMemoPageDrag", () => {
  beforeEach(() => {
    vi.mocked(reorderMemos).mockResolvedValue(undefined);
  });

  it("previews the projected order while dragging and persists the neighbours on drop", async () => {
    const { result } = renderHook(() => useDragHarness(false));
    expect(result.current.canDragMemos).toBe(true);

    const startEvent = makeDragStartEvent();
    act(() => {
      result.current.handleMemoDragStart(startEvent, memos[0]);
    });
    expect(startEvent.preventDefault).not.toHaveBeenCalled();
    expect(result.current.draggedMemoId).toBe("1");
    expect(closeMemoActionMenu).toHaveBeenCalledTimes(1);

    const overEvent = makeDragOverEvent();
    act(() => {
      result.current.handleMemoSectionDragOver(overEvent, memos);
    });
    expect(overEvent.preventDefault).toHaveBeenCalled();
    expect(result.current.otherMemos.map((memo) => String(memo.id))).toEqual(["2", "1", "3"]);

    await act(async () => {
      await result.current.handleMemoDrop(makeDropEvent("1"));
    });

    expect(reorderMemos).toHaveBeenCalledWith({ memo_id: 1, before_id: 2, after_id: 3 }, expect.any(String));
    // 楽観更新（関数付き）→ 再検証（引数なし）の順で mutate される
    // mutate runs the optimistic update (with a function) and then the plain revalidation
    const mutateCalls = mutateMock.mock.calls;
    expect(mutateCalls).toHaveLength(2);
    expect(typeof mutateCalls[0][0]).toBe("function");
    expect(mutateCalls[1]).toHaveLength(0);
    expect(result.current.draggedMemoId).toBe("");
    expect(showFlash).not.toHaveBeenCalled();
  });

  it("reports the error and revalidates when the reorder request fails", async () => {
    vi.mocked(reorderMemos).mockRejectedValueOnce(new Error("並び替え失敗"));
    const { result } = renderHook(() => useDragHarness(false));

    act(() => {
      result.current.handleMemoDragStart(makeDragStartEvent(), memos[0]);
    });
    act(() => {
      result.current.handleMemoSectionDragOver(makeDragOverEvent(), memos);
    });
    await act(async () => {
      await result.current.handleMemoDrop(makeDropEvent("1"));
    });

    expect(showFlash).toHaveBeenCalledWith("error", "並び替え失敗");
    expect(mutateMock.mock.calls).toHaveLength(2);
    expect(result.current.canDragMemos).toBe(true);
  });

  it("refuses to start a drag in bulk mode", async () => {
    const { result } = renderHook(() => useDragHarness(true));
    expect(result.current.canDragMemos).toBe(false);

    const startEvent = makeDragStartEvent();
    act(() => {
      result.current.handleMemoDragStart(startEvent, memos[0]);
    });
    expect(startEvent.preventDefault).toHaveBeenCalled();
    expect(result.current.draggedMemoId).toBe("");

    await act(async () => {
      await result.current.handleMemoDrop(makeDropEvent("1"));
    });
    expect(reorderMemos).not.toHaveBeenCalled();
  });
});
