import { useCallback, useEffect, useState } from "react";
import type { KeyedMutator } from "swr";

import { useTranslation } from "../../contexts/locale_context";
import { runBulkMemoAction } from "../../lib/memo/api";
import type {
  BulkAction,
  BulkMemoActionInput,
  Collection,
  FlashAction,
  FlashState,
  MemoListState,
  MemoSummary,
} from "../../lib/memo/types";
import { showConfirmModal } from "../../scripts/core/alert_modal";

type UseMemoPageBulkParams = {
  memos: MemoSummary[];
  collections: Collection[];
  mutate: KeyedMutator<MemoListState>;
  updateMemoListOptimistically: (
    updater: (memo: MemoSummary) => MemoSummary | null,
    targetIds: Iterable<string | number>,
  ) => Promise<void>;
  showFlash: (type: FlashState["type"], text: string, action?: FlashAction) => void;
};

// 通知の「元に戻す」で逆操作にする組み合わせ。ゴミ箱への移動とアーカイブだけが対象
// The actions an undo can reverse: moving to the trash and archiving only
const UNDO_ACTIONS: Partial<Record<BulkAction, BulkAction>> = { delete: "restore", archive: "unarchive", unarchive: "archive" };

// 一括選択モードと一括操作（ゴミ箱への移動と復元・完全削除・アーカイブ・ピン・コレクション設定）
// Bulk-selection mode and bulk actions (move to trash, restore, delete for good / archive / pin / set collection)
export function useMemoPageBulk({ memos, collections, mutate, updateMemoListOptimistically, showFlash }: UseMemoPageBulkParams) {
  const { t } = useTranslation();

  // Bulk selection
  const [isBulkMode, setIsBulkMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkCollectionId, setBulkCollectionId] = useState<number | null>(null);
  const [bulkLoading, setBulkLoading] = useState(false);

  // Exit bulk mode when memos change drastically
  useEffect(() => {
    if (!isBulkMode) return;
    setSelectedIds((prev) => {
      const memoIdSet = new Set(memos.map((m) => String(m.id)));
      const next = new Set([...prev].filter((id) => memoIdSet.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [memos, isBulkMode]);

  const toggleSelectMemo = useCallback((memoId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(memoId)) next.delete(memoId);
      else next.add(memoId);
      return next;
    });
  }, []);

  const selectAll = useCallback(() => {
    setSelectedIds(new Set(memos.map((m) => String(m.id))));
  }, [memos]);

  const deselectAll = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  // 完了通知の文言。復元では、共有していたメモの共有が解除されたままであることも伝える
  // The completion notice. A restore also says that memos which had been shared stay unshared
  const bulkSuccessMessage = useCallback((action: BulkAction, count: number, anyShared: boolean) => {
    if (action === "delete") return t("memo.bulkMovedToTrash", { count });
    if (action === "purge") return t("memo.bulkPurged", { count });
    if (action === "restore") return t(anyShared ? "memo.bulkRestoredShareOff" : "memo.bulkRestored", { count });
    const labels = {
      archive: t("memo.archive"), unarchive: t("memo.unarchive"),
      pin: t("memo.pin"), unpin: t("memo.unpin"),
      set_collection: t("memo.setCollection"), clear_collection: t("memo.clearCollection"),
    };
    return t("memo.bulkActionSuccess", { count, action: labels[action] });
  }, [t]);

  const executeBulk = useCallback(async (
    action: BulkAction,
    selectedIdList: string[],
    extra?: { collectionId?: number | null },
    isUndo = false,
  ) => {
    setBulkLoading(true);

    const now = new Date().toISOString();
    const targetCollection =
      extra?.collectionId !== undefined && extra.collectionId !== null
        ? collections.find((collection) => collection.id === extra.collectionId) ?? null
        : null;
    const selectedMemos = memos.filter((memo) => selectedIdList.includes(String(memo.id)));
    // 逆操作の対象は、操作で状態が実際に変わったメモだけ（元からアーカイブ済みのものまで戻さない）
    // Only memos whose state the action really changed are undone (ones already archived stay archived)
    const undoAction = UNDO_ACTIONS[action];
    const undoIds = selectedMemos
      .filter((memo) => action === "delete" || Boolean(memo.is_archived) !== (action === "archive"))
      .map((memo) => String(memo.id));
    const anyShared = selectedMemos.some((memo) => Boolean(memo.share_token));

    await updateMemoListOptimistically((memo) => {
      if (action === "delete" || action === "restore" || action === "purge") return null;
      if (action === "archive") return { ...memo, is_archived: true, archived_at: now };
      if (action === "unarchive") return { ...memo, is_archived: false, archived_at: null };
      if (action === "pin") return { ...memo, is_pinned: true, pinned_at: now };
      if (action === "unpin") return { ...memo, is_pinned: false, pinned_at: null };
      if (action === "set_collection" && targetCollection) {
        return {
          ...memo,
          collection_id: targetCollection.id,
          collection_name: targetCollection.name,
          collection_color: targetCollection.color,
        };
      }
      if (action === "clear_collection") {
        return {
          ...memo,
          collection_id: null,
          collection_name: null,
          collection_color: null,
        };
      }
      return memo;
    }, selectedIdList);

    try {
      const body: BulkMemoActionInput = {
        action,
        memo_ids: selectedIdList.map(Number),
      };
      if (extra?.collectionId !== undefined) body.collection_id = extra.collectionId;

      await runBulkMemoAction(body, t("memo.bulkActionFailed"));
      const count = selectedIdList.length;
      const undo: FlashAction | undefined =
        undoAction && !isUndo && undoIds.length > 0
          ? { label: t("memo.undo"), onAction: () => executeBulk(undoAction, undoIds, undefined, true) }
          : undefined;
      showFlash("success", bulkSuccessMessage(action, count, anyShared), undo);
      if (action === "delete" || action === "restore" || action === "purge") setSelectedIds(new Set());
      await mutate();
      setBulkCollectionId(null);
    } catch (error) {
      showFlash("error", error instanceof Error ? error.message : t("memo.bulkActionFailed"));
      await mutate();
    } finally {
      setBulkLoading(false);
    }
  }, [bulkSuccessMessage, collections, memos, mutate, showFlash, t, updateMemoListOptimistically]);

  const executeBulkAction = useCallback(async (action: BulkAction, extra?: { collectionId?: number | null }) => {
    if (selectedIds.size === 0) return;
    // 完全削除は取り消せないので、選択した件数を示して確認する
    // Deleting for good cannot be undone, so confirm with the number of selected memos
    if (action === "purge" && !(await showConfirmModal(t("memo.bulkPurgeConfirm", { count: selectedIds.size })))) return;
    await executeBulk(action, Array.from(selectedIds), extra);
  }, [executeBulk, selectedIds, t]);

  const exitBulkMode = useCallback(() => {
    setIsBulkMode(false);
    setSelectedIds(new Set());
  }, []);

  const hasSelection = selectedIds.size > 0;

  return {
    isBulkMode,
    setIsBulkMode,
    selectedIds,
    bulkCollectionId,
    setBulkCollectionId,
    bulkLoading,
    hasSelection,
    toggleSelectMemo,
    selectAll,
    deselectAll,
    executeBulkAction,
    exitBulkMode,
  };
}
