import { act, renderHook } from "@testing-library/react";
import type { KeyedMutator } from "swr";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useMemoPageItemActions } from "../hooks/memo_page/use_memo_page_item_actions";
import { deleteMemo, emptyMemoTrash, purgeMemo, restoreMemo, setMemoArchived } from "../lib/memo/api";
import type { FlashAction, MemoListState, MemoSummary } from "../lib/memo/types";
import { showConfirmModal } from "../scripts/core/alert_modal";

vi.mock("../lib/memo/api", () => ({
  deleteMemo: vi.fn(),
  emptyMemoTrash: vi.fn(),
  loadMemoDetail: vi.fn(),
  purgeMemo: vi.fn(),
  restoreMemo: vi.fn(),
  setMemoArchived: vi.fn(),
  setMemoPinned: vi.fn(),
  updateMemo: vi.fn(),
}));
vi.mock("../scripts/core/alert_modal", () => ({ showConfirmModal: vi.fn() }));

// モックは再レンダーを跨いで同一インスタンスにする（SWR の mutate は安定参照のため）
// Mocks stay one instance across re-renders, mirroring SWR's stable mutate reference
const mutateMock = vi.fn(async () => undefined);
const mutate = mutateMock as unknown as KeyedMutator<MemoListState>;
const updateMemoListOptimistically = vi.fn(async () => undefined);
const showFlash = vi.fn();
const patchSelectedMemoOptimistically = vi.fn();
const refreshSelectedMemoIfNeeded = vi.fn(async (_memoId: string | number) => undefined);
const saveSelectedMemoEdits = vi.fn(async () => true);
const startMemoDetailCloseAnimation = vi.fn();

function useItemActionsHarness(selectedMemoId?: number) {
  return useMemoPageItemActions({
    mutate,
    updateMemoListOptimistically,
    showFlash,
    selectedMemoId,
    patchSelectedMemoOptimistically,
    refreshSelectedMemoIfNeeded,
    saveSelectedMemoEdits,
    startMemoDetailCloseAnimation,
  });
}

const memo: MemoSummary = { id: 7, title: "旅行" };

function lastUndo(): FlashAction {
  const action = showFlash.mock.calls[showFlash.mock.calls.length - 1][2] as FlashAction | undefined;
  if (!action) throw new Error("the notice carries no undo");
  return action;
}

describe("useMemoPageItemActions trash and undo", () => {
  beforeEach(() => {
    vi.mocked(deleteMemo).mockResolvedValue(undefined);
    vi.mocked(restoreMemo).mockResolvedValue(undefined);
    vi.mocked(purgeMemo).mockResolvedValue(undefined);
    vi.mocked(setMemoArchived).mockResolvedValue(undefined);
    vi.mocked(emptyMemoTrash).mockResolvedValue(3);
  });

  it("moves a memo to the trash without asking, and the undo restores it", async () => {
    const { result } = renderHook(() => useItemActionsHarness());

    await act(async () => {
      await result.current.handleDeleteMemo(memo);
    });

    expect(showConfirmModal).not.toHaveBeenCalled();
    expect(deleteMemo).toHaveBeenCalledWith(7, expect.any(String));
    expect(showFlash).toHaveBeenLastCalledWith("success", "ゴミ箱に移動しました。", expect.objectContaining({ label: "元に戻す" }));

    await act(async () => {
      await lastUndo().onAction();
    });

    expect(restoreMemo).toHaveBeenCalledWith(7, expect.any(String));
    expect(showFlash).toHaveBeenLastCalledWith("success", "元に戻しました。");
    expect(mutateMock).toHaveBeenCalledTimes(2);
  });

  it("closes the detail when the open memo is trashed, and leaves it alone for another memo", async () => {
    const { result, rerender } = renderHook(({ id }: { id?: number }) => useItemActionsHarness(id), { initialProps: { id: 7 } });
    await act(async () => {
      await result.current.handleDeleteMemo(memo);
    });
    expect(startMemoDetailCloseAnimation).toHaveBeenCalledTimes(1);

    rerender({ id: 99 });
    await act(async () => {
      await result.current.handleDeleteMemo(memo);
    });
    expect(startMemoDetailCloseAnimation).toHaveBeenCalledTimes(1);
  });

  it("does not offer an undo when the move to the trash fails", async () => {
    vi.mocked(deleteMemo).mockRejectedValueOnce(new Error("失敗"));
    const { result } = renderHook(() => useItemActionsHarness());

    await act(async () => {
      await result.current.handleDeleteMemo(memo);
    });

    expect(showFlash).toHaveBeenLastCalledWith("error", "失敗");
    expect(startMemoDetailCloseAnimation).not.toHaveBeenCalled();
  });

  it("tells the user that sharing stays off when a memo that was shared is restored from the trash", async () => {
    const { result } = renderHook(() => useItemActionsHarness());

    await act(async () => {
      await result.current.handleRestoreMemo({ ...memo, deleted_at: "2026-10-05T00:00:00", share_token: "tok" });
    });

    expect(showFlash).toHaveBeenLastCalledWith("success", "元に戻しました。共有は解除されたままです。");
  });

  it("mentions sharing on an undo only when the memo was shared at the moment it was deleted", async () => {
    const { result } = renderHook(() => useItemActionsHarness());

    // 以前に共有して、すでに解除してあったメモ: 共有の話は出さない
    // Shared once and already turned off: nothing to say about sharing
    await act(async () => {
      await result.current.handleRestoreMemo({ ...memo, share_token: "tok", is_active: false });
    });
    expect(showFlash).toHaveBeenLastCalledWith("success", "元に戻しました。");

    await act(async () => {
      await result.current.handleRestoreMemo({ ...memo, share_token: "tok", is_active: true });
    });
    expect(showFlash).toHaveBeenLastCalledWith("success", "元に戻しました。共有は解除されたままです。");
  });

  it("saves the open detail's pending edits before trashing that memo", async () => {
    const { result } = renderHook(() => useItemActionsHarness(7));
    await act(async () => {
      await result.current.handleDeleteMemo(memo);
    });
    expect(saveSelectedMemoEdits).toHaveBeenCalledTimes(1);
    expect(saveSelectedMemoEdits.mock.invocationCallOrder[0]).toBeLessThan(vi.mocked(deleteMemo).mock.invocationCallOrder[0]);
  });

  it("does not save the open detail when another memo is trashed", async () => {
    const { result } = renderHook(() => useItemActionsHarness(99));
    await act(async () => {
      await result.current.handleDeleteMemo(memo);
    });
    expect(saveSelectedMemoEdits).not.toHaveBeenCalled();
  });

  it("refreshes the detail for the archived memo's id, never for whatever was open when the action was created", async () => {
    const { result } = renderHook(() => useItemActionsHarness(7));
    await act(async () => {
      await result.current.handleToggleArchive(memo);
    });
    expect(refreshSelectedMemoIfNeeded).toHaveBeenLastCalledWith(7);
  });

  it("reports a failed restore as an error", async () => {
    vi.mocked(restoreMemo).mockRejectedValueOnce(new Error("戻せません"));
    const { result } = renderHook(() => useItemActionsHarness());

    await act(async () => {
      await result.current.handleRestoreMemo(memo);
    });

    expect(showFlash).toHaveBeenLastCalledWith("error", "戻せません");
  });

  it("archives with an undo that unarchives, and the undo carries no undo of its own", async () => {
    const { result } = renderHook(() => useItemActionsHarness());

    await act(async () => {
      await result.current.handleToggleArchive(memo);
    });
    expect(setMemoArchived).toHaveBeenLastCalledWith(7, true, expect.any(String));
    expect(showFlash).toHaveBeenLastCalledWith("success", "アーカイブしました。", expect.objectContaining({ label: "元に戻す" }));

    await act(async () => {
      await lastUndo().onAction();
    });
    expect(setMemoArchived).toHaveBeenLastCalledWith(7, false, expect.any(String));
    expect(showFlash).toHaveBeenLastCalledWith("success", "アーカイブを解除しました。", undefined);
  });

  it("unarchives with an undo that archives again", async () => {
    const { result } = renderHook(() => useItemActionsHarness());

    await act(async () => {
      await result.current.handleToggleArchive({ ...memo, is_archived: true });
    });
    expect(setMemoArchived).toHaveBeenLastCalledWith(7, false, expect.any(String));

    await act(async () => {
      await lastUndo().onAction();
    });
    expect(setMemoArchived).toHaveBeenLastCalledWith(7, true, expect.any(String));
  });

  it("deletes one trashed memo for good only after a confirmation", async () => {
    vi.mocked(showConfirmModal).mockResolvedValueOnce(false);
    const { result } = renderHook(() => useItemActionsHarness());

    await act(async () => {
      await result.current.handlePurgeMemo(memo);
    });
    expect(showConfirmModal).toHaveBeenCalledWith(expect.stringContaining("旅行"));
    expect(purgeMemo).not.toHaveBeenCalled();

    vi.mocked(showConfirmModal).mockResolvedValueOnce(true);
    await act(async () => {
      await result.current.handlePurgeMemo(memo);
    });
    expect(purgeMemo).toHaveBeenCalledWith(7, expect.any(String));
    expect(showFlash).toHaveBeenLastCalledWith("success", "完全に削除しました。");
  });

  it("empties the trash after a confirmation and reports how many were deleted", async () => {
    vi.mocked(showConfirmModal).mockResolvedValueOnce(true);
    const { result } = renderHook(() => useItemActionsHarness());

    await act(async () => {
      await result.current.handleEmptyTrash();
    });

    expect(emptyMemoTrash).toHaveBeenCalledTimes(1);
    expect(showFlash).toHaveBeenLastCalledWith("success", "ゴミ箱を空にしました（3件）。");
    expect(result.current.emptyingTrash).toBe(false);
    expect(mutateMock).toHaveBeenCalled();
  });

  it("does not empty the trash when the confirmation is declined", async () => {
    vi.mocked(showConfirmModal).mockResolvedValueOnce(false);
    const { result } = renderHook(() => useItemActionsHarness());

    await act(async () => {
      await result.current.handleEmptyTrash();
    });

    expect(emptyMemoTrash).not.toHaveBeenCalled();
  });
});
