import { act, renderHook } from "@testing-library/react";
import { useState } from "react";
import type { KeyedMutator } from "swr";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useMemoPageBulk } from "../hooks/memo_page/use_memo_page_bulk";
import { runBulkMemoAction } from "../lib/memo/api";
import type { Collection, MemoListState, MemoSummary } from "../lib/memo/types";

vi.mock("../lib/memo/api", () => ({
  runBulkMemoAction: vi.fn(),
}));

type Updater = (memo: MemoSummary) => MemoSummary | null;

const collections: Collection[] = [{ id: 5, name: "仕事", color: "#3b82f6", memo_count: 2 }];
const makeMemo = (id: number): MemoSummary => ({ id, title: `memo ${id}` });

// モックは再レンダーを跨いで同一インスタンスである必要がある（SWR の mutate は安定参照のため）
// Mocks must stay stable across re-renders, mirroring SWR's stable mutate reference
const mutateMock = vi.fn(async () => undefined);
const mutate = mutateMock as unknown as KeyedMutator<MemoListState>;
const showFlash = vi.fn();
const updateMemoListOptimistically = vi.fn(async (_updater: Updater, _targetIds: Iterable<string | number>) => undefined);

function useBulkHarness(initialMemos: MemoSummary[]) {
  const [memos, setMemos] = useState(initialMemos);
  const bulk = useMemoPageBulk({ memos, collections, mutate, updateMemoListOptimistically, showFlash });
  return { ...bulk, setMemos };
}

async function selectMemos(result: { current: ReturnType<typeof useBulkHarness> }, ids: string[]) {
  act(() => {
    result.current.setIsBulkMode(true);
  });
  for (const id of ids) {
    act(() => {
      result.current.toggleSelectMemo(id);
    });
  }
}

describe("useMemoPageBulk", () => {
  beforeEach(() => {
    vi.mocked(runBulkMemoAction).mockResolvedValue(undefined);
  });

  it("archives the selected memos optimistically and posts numeric ids", async () => {
    const { result } = renderHook(() => useBulkHarness([makeMemo(1), makeMemo(2), makeMemo(3)]));
    await selectMemos(result, ["1", "2"]);
    expect(result.current.hasSelection).toBe(true);

    await act(async () => {
      await result.current.executeBulkAction("archive");
    });

    expect(runBulkMemoAction).toHaveBeenCalledWith({ action: "archive", memo_ids: [1, 2] }, expect.any(String));
    const [updater, targetIds] = updateMemoListOptimistically.mock.calls[0];
    expect(Array.from(targetIds)).toEqual(["1", "2"]);
    expect(updater(makeMemo(1))).toMatchObject({ id: 1, is_archived: true });
    expect(updater(makeMemo(1))?.archived_at).toEqual(expect.any(String));
    expect(showFlash).toHaveBeenCalledWith("success", expect.any(String));
    expect(mutateMock).toHaveBeenCalled();
    expect(result.current.bulkLoading).toBe(false);
    expect(result.current.selectedIds.size).toBe(2);
  });

  it("assigns the collection with its name and colour and sends collection_id", async () => {
    const { result } = renderHook(() => useBulkHarness([makeMemo(1)]));
    await selectMemos(result, ["1"]);

    await act(async () => {
      await result.current.executeBulkAction("set_collection", { collectionId: 5 });
    });

    expect(runBulkMemoAction).toHaveBeenCalledWith(
      { action: "set_collection", memo_ids: [1], collection_id: 5 },
      expect.any(String),
    );
    const [updater] = updateMemoListOptimistically.mock.calls[0];
    expect(updater(makeMemo(1))).toEqual({
      id: 1,
      title: "memo 1",
      collection_id: 5,
      collection_name: "仕事",
      collection_color: "#3b82f6",
    });
  });

  it("clears the selection after a bulk delete", async () => {
    const { result } = renderHook(() => useBulkHarness([makeMemo(1), makeMemo(2)]));
    await selectMemos(result, ["1", "2"]);

    await act(async () => {
      await result.current.executeBulkAction("delete");
    });

    const [updater] = updateMemoListOptimistically.mock.calls[0];
    expect(updater(makeMemo(1))).toBeNull();
    expect(result.current.selectedIds.size).toBe(0);
  });

  it("reports the error and revalidates when the request fails", async () => {
    vi.mocked(runBulkMemoAction).mockRejectedValueOnce(new Error("だめでした"));
    const { result } = renderHook(() => useBulkHarness([makeMemo(1)]));
    await selectMemos(result, ["1"]);

    await act(async () => {
      await result.current.executeBulkAction("pin");
    });

    expect(showFlash).toHaveBeenCalledWith("error", "だめでした");
    expect(mutateMock).toHaveBeenCalled();
    expect(result.current.bulkLoading).toBe(false);
  });

  it("drops selected ids that disappear from the list while bulk mode is on", async () => {
    const { result } = renderHook(() => useBulkHarness([makeMemo(1), makeMemo(2)]));
    await selectMemos(result, ["1", "2"]);

    act(() => {
      result.current.setMemos([makeMemo(1)]);
    });

    expect(Array.from(result.current.selectedIds)).toEqual(["1"]);
  });

  it("exits bulk mode and clears the selection", async () => {
    const { result } = renderHook(() => useBulkHarness([makeMemo(1)]));
    await selectMemos(result, ["1"]);

    act(() => {
      result.current.exitBulkMode();
    });

    expect(result.current.isBulkMode).toBe(false);
    expect(result.current.selectedIds.size).toBe(0);
  });
});
