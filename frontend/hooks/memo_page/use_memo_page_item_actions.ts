import { useCallback, useState } from "react";
import type { KeyedMutator } from "swr";

import { useTranslation } from "../../contexts/locale_context";
import { deleteMemo, loadMemoDetail, setMemoArchived, setMemoPinned } from "../../lib/memo/api";
import type { FlashState, MemoDetail, MemoListState, MemoSummary } from "../../lib/memo/types";
import { parseMemoText } from "../../lib/memo/utils";
import { showConfirmModal } from "../../scripts/core/alert_modal";
import { copyTextToClipboard } from "../../scripts/core/clipboard";

type UseMemoPageItemActionsParams = {
  mutate: KeyedMutator<MemoListState>;
  updateMemoListOptimistically: (
    updater: (memo: MemoSummary) => MemoSummary | null,
    targetIds: Iterable<string | number>,
  ) => Promise<void>;
  showFlash: (type: FlashState["type"], text: string) => void;
  selectedMemoId: string | number | undefined;
  patchSelectedMemoOptimistically: (memoId: string | number, patch: Partial<MemoDetail>) => void;
  refreshSelectedMemoIfNeeded: () => Promise<void>;
  startMemoDetailCloseAnimation: () => void;
};

// メモカード単体への操作（ピン・アーカイブ・削除・全文コピー）
// Actions on a single memo card (pin / archive / delete / copy full text)
export function useMemoPageItemActions({
  mutate,
  updateMemoListOptimistically,
  showFlash,
  selectedMemoId,
  patchSelectedMemoOptimistically,
  refreshSelectedMemoIfNeeded,
  startMemoDetailCloseAnimation,
}: UseMemoPageItemActionsParams) {
  const { t } = useTranslation();

  const [actionLoadingId, setActionLoadingId] = useState<string>("");
  const [copyingMemoId, setCopyingMemoId] = useState<string>("");

  const withActionLoading = useCallback(async (memoId: string | number, action: () => Promise<void>) => {
    const id = String(memoId);
    setActionLoadingId(id);
    try { await action(); } finally { setActionLoadingId(""); }
  }, []);

  // ピン留め状態を切り替えるハンドラー
  // Handler to toggle the pinned state
  const handleTogglePin = useCallback(async (memo: MemoSummary) => {
    await withActionLoading(memo.id, async () => {
      const enabled = !memo.is_pinned;
      const pinnedAt = enabled ? new Date().toISOString() : null;
      await updateMemoListOptimistically(
        (current) => ({
          ...current,
          is_pinned: enabled,
          pinned_at: pinnedAt,
        }),
        [memo.id],
      );
      patchSelectedMemoOptimistically(memo.id, { is_pinned: enabled, pinned_at: pinnedAt });
      try {
        await setMemoPinned(memo.id, enabled, t("memo.pinUpdateFailed"));
        showFlash("success", memo.is_pinned ? t("memo.unpinnedSuccess") : t("memo.pinnedSuccess"));
        await mutate();
        await refreshSelectedMemoIfNeeded();
      } catch (error) {
        showFlash("error", error instanceof Error ? error.message : t("memo.pinUpdateFailed"));
        await mutate();
        await refreshSelectedMemoIfNeeded();
      }
    });
  }, [mutate, patchSelectedMemoOptimistically, refreshSelectedMemoIfNeeded, showFlash, updateMemoListOptimistically, withActionLoading]);

  // アーカイブ状態を切り替えるハンドラー
  // Handler to toggle the archived state
  const handleToggleArchive = useCallback(async (memo: MemoSummary) => {
    await withActionLoading(memo.id, async () => {
      const enabled = !memo.is_archived;
      const archivedAt = enabled ? new Date().toISOString() : null;
      await updateMemoListOptimistically(
        (current) => ({
          ...current,
          is_archived: enabled,
          archived_at: archivedAt,
        }),
        [memo.id],
      );
      patchSelectedMemoOptimistically(memo.id, { is_archived: enabled, archived_at: archivedAt });
      try {
        await setMemoArchived(memo.id, enabled, t("memo.archiveUpdateFailed"));
        showFlash("success", memo.is_archived ? t("memo.unarchivedSuccess") : t("memo.archivedSuccess"));
        await mutate();
        await refreshSelectedMemoIfNeeded();
      } catch (error) {
        showFlash("error", error instanceof Error ? error.message : t("memo.archiveUpdateFailed"));
        await mutate();
        await refreshSelectedMemoIfNeeded();
      }
    });
  }, [mutate, patchSelectedMemoOptimistically, refreshSelectedMemoIfNeeded, showFlash, updateMemoListOptimistically, withActionLoading]);

  // メモを削除するハンドラー
  // Handler to delete a memo
  const handleDeleteMemo = useCallback(async (memo: MemoSummary) => {
    const confirmed = await showConfirmModal(t("memo.deleteConfirm", { title: memo.title || t("memo.savedMemo") }));
    if (!confirmed) return;
    await withActionLoading(memo.id, async () => {
      await updateMemoListOptimistically(() => null, [memo.id]);
      try {
        await deleteMemo(memo.id, t("memo.memoDeleteFailed"));
        showFlash("success", t("memo.memoDeleted"));
        if (selectedMemoId && String(selectedMemoId) === String(memo.id)) startMemoDetailCloseAnimation();
        await mutate();
      } catch (error) {
        showFlash("error", error instanceof Error ? error.message : t("memo.memoDeleteFailed"));
        await mutate();
      }
    });
  }, [mutate, selectedMemoId, showFlash, startMemoDetailCloseAnimation, updateMemoListOptimistically, withActionLoading]);

  // コピー成否は共通の CopyButton がアイコン表示に使う。取得中のスピナーだけここで面倒を見る。
  // The shared CopyButton uses the returned success flag for its icon; only the "loading" spinner is tracked here.
  const copyMemoFullText = useCallback(async (memo: MemoSummary): Promise<boolean> => {
    const memoId = String(memo.id);
    setCopyingMemoId(memoId);
    try {
      const detail = await loadMemoDetail(memo.id);
      const fullText = detail?.ai_response || memo.excerpt || "";
      const content = `${detail?.title || memo.title || t("memo.savedMemo")}\n\n${parseMemoText(fullText)}`;
      await copyTextToClipboard(content.trim());
      return true;
    } catch (error) {
      showFlash("error", error instanceof Error ? error.message : t("memo.copyFailed"));
      return false;
    }
    finally { setCopyingMemoId(""); }
  }, [showFlash]);

  return {
    actionLoadingId,
    copyingMemoId,
    handleTogglePin,
    handleToggleArchive,
    handleDeleteMemo,
    copyMemoFullText,
  };
}
