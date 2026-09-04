import { act, renderHook } from "@testing-library/react";
import type { KeyedMutator } from "swr";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useMemoPageDetail } from "../hooks/memo_page/use_memo_page_detail";
import { loadMemoDetail, updateMemo } from "../lib/memo/api";
import { DETAIL_AUTOSAVE_DELAY_MS, MEMO_DETAIL_CLOSE_ANIMATION_MS } from "../lib/memo/constants";
import type { Collection, MemoDetail, MemoListState } from "../lib/memo/types";

vi.mock("../lib/memo/api", () => ({
  loadMemoDetail: vi.fn(),
  updateMemo: vi.fn(),
}));
vi.mock("../scripts/core/clipboard", () => ({
  copyTextToClipboard: vi.fn(),
}));

const baseMemo: MemoDetail = { id: 1, title: "a", ai_response: "body" };

// モックは再レンダーを跨いで同一インスタンスである必要がある（SWR の mutate は安定参照のため）
// Mocks must stay stable across re-renders, mirroring SWR's stable mutate reference
const mutateMock = vi.fn(async () => undefined);
const mutate = mutateMock as unknown as KeyedMutator<MemoListState>;
const showFlash = vi.fn();
const noCollections: Collection[] = [];

function useDetailHarness(collections: Collection[] = noCollections) {
  return useMemoPageDetail({ collections, mutate, showFlash });
}

describe("useMemoPageDetail", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(loadMemoDetail).mockResolvedValue({ ...baseMemo });
    vi.mocked(updateMemo).mockResolvedValue({ ...baseMemo });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("autosaves an edited title after the delay and keeps the submitted text as the baseline", async () => {
    const { result } = renderHook(() => useDetailHarness());

    await act(async () => {
      await result.current.openMemoDetail(1);
    });
    expect(result.current.selectedMemo?.id).toBe(1);
    expect(result.current.detailSaveStatus).toBe("saved");
    expect(result.current.detailHasUnsavedChanges).toBe(false);

    act(() => {
      result.current.setDetailEditTitle("b");
    });
    expect(result.current.detailHasUnsavedChanges).toBe(true);
    expect(result.current.detailSaveStatus).toBe("idle");
    expect(updateMemo).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(DETAIL_AUTOSAVE_DELAY_MS);
    });

    // collections が空なので collection 系のキーは付かず、背景色なしは clear フラグになる
    // With no collections the collection keys are omitted; a null colour becomes the clear flag
    expect(updateMemo).toHaveBeenCalledTimes(1);
    expect(updateMemo).toHaveBeenCalledWith(
      1,
      { title: "b", ai_response: "body", clear_background_color: true },
      expect.any(String),
    );
    expect(result.current.detailSaveStatus).toBe("saved");
    expect(result.current.selectedMemo?.title).toBe("b");
    expect(result.current.detailHasUnsavedChanges).toBe(false);
    expect(mutateMock).toHaveBeenCalled();
  });

  it("sends collection flags only when collections exist", async () => {
    const collections: Collection[] = [{ id: 7, name: "仕事", color: "#3b82f6", memo_count: 1 }];
    const { result } = renderHook(() => useDetailHarness(collections));

    await act(async () => {
      await result.current.openMemoDetail(1);
    });
    act(() => {
      result.current.setDetailEditCollectionId(7);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(DETAIL_AUTOSAVE_DELAY_MS);
    });

    expect(updateMemo).toHaveBeenCalledWith(
      1,
      { title: "a", ai_response: "body", clear_background_color: true, collection_id: 7 },
      expect.any(String),
    );
  });

  it("ignores an older save that resolves after a newer one started", async () => {
    let resolveFirst: ((value: MemoDetail) => void) | undefined;
    let resolveSecond: ((value: MemoDetail) => void) | undefined;
    vi.mocked(updateMemo)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveSecond = resolve; }));

    const { result } = renderHook(() => useDetailHarness());
    await act(async () => {
      await result.current.openMemoDetail(1);
    });

    act(() => {
      result.current.setDetailEditTitle("b");
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(DETAIL_AUTOSAVE_DELAY_MS);
    });
    expect(result.current.detailSaveStatus).toBe("saving");

    act(() => {
      result.current.setDetailEditTitle("c");
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(DETAIL_AUTOSAVE_DELAY_MS);
    });
    expect(updateMemo).toHaveBeenCalledTimes(2);
    expect(result.current.detailSaveStatus).toBe("saving");

    // 古い保存が後から解決しても、状態と基準値は上書きされない
    // The stale save resolving later must not overwrite the status or the baseline
    await act(async () => {
      resolveFirst?.({ ...baseMemo, title: "b" });
    });
    expect(result.current.detailSaveStatus).toBe("saving");
    expect(result.current.selectedMemo?.title).toBe("a");

    await act(async () => {
      resolveSecond?.({ ...baseMemo, title: "c" });
    });
    expect(result.current.detailSaveStatus).toBe("saved");
    expect(result.current.selectedMemo?.title).toBe("c");
    expect(result.current.detailEditTitle).toBe("c");
  });

  it("marks an empty body as an error without calling the API", async () => {
    const { result } = renderHook(() => useDetailHarness());
    await act(async () => {
      await result.current.openMemoDetail(1);
    });

    act(() => {
      result.current.setDetailEditAiResponse("   ");
    });
    expect(result.current.detailSaveStatus).toBe("error");
    expect(result.current.detailSaveError).not.toBe("");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(DETAIL_AUTOSAVE_DELAY_MS);
    });
    expect(updateMemo).not.toHaveBeenCalled();
  });

  it("saves pending edits before closing and clears the memo after the close animation", async () => {
    const { result } = renderHook(() => useDetailHarness());
    await act(async () => {
      await result.current.openMemoDetail(1);
    });
    act(() => {
      result.current.setDetailEditTitle("b");
    });

    await act(async () => {
      await result.current.closeMemoDetail();
    });
    expect(updateMemo).toHaveBeenCalledTimes(1);
    expect(result.current.isMemoDetailClosing).toBe(true);
    expect(result.current.selectedMemo?.id).toBe(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(MEMO_DETAIL_CLOSE_ANIMATION_MS);
    });
    expect(result.current.selectedMemo).toBeNull();
    expect(result.current.isMemoDetailClosing).toBe(false);
    expect(result.current.detailEditTitle).toBe("");
    expect(result.current.detailSaveStatus).toBe("idle");
  });
});
