import { useCallback, useEffect, useState } from "react";
import type { KeyedMutator } from "swr";

import { useTranslation } from "../../contexts/locale_context";
import { runBulkMemoAction } from "../../lib/memo/api";
import type {
  BulkAction,
  BulkMemoActionInput,
  Collection,
  FlashState,
  MemoListState,
  MemoSummary,
} from "../../lib/memo/types";

type UseMemoPageBulkParams = {
  memos: MemoSummary[];
  collections: Collection[];
  mutate: KeyedMutator<MemoListState>;
  updateMemoListOptimistically: (
    updater: (memo: MemoSummary) => MemoSummary | null,
    targetIds: Iterable<string | number>,
  ) => Promise<void>;
  showFlash: (type: FlashState["type"], text: string) => void;
};

// 一括選択モードと一括操作（削除・アーカイブ・ピン・コレクション設定）
// Bulk-selection mode and bulk actions (delete / archive / pin / set collection)
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

  const executeBulkAction = useCallback(async (action: BulkAction, extra?: { collectionId?: number | null }) => {
    if (selectedIds.size === 0) return;
    const selectedIdList = Array.from(selectedIds);
    setBulkLoading(true);

    const now = new Date().toISOString();
    const targetCollection =
      extra?.collectionId !== undefined && extra.collectionId !== null
        ? collections.find((collection) => collection.id === extra.collectionId) ?? null
        : null;

    await updateMemoListOptimistically((memo) => {
      if (action === "delete") return null;
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
      const labels: Record<BulkAction, string> = {
        delete: t("common.delete"), archive: t("memo.archive"), unarchive: t("memo.unarchive"),
        pin: t("memo.pin"), unpin: t("memo.unpin"),
        set_collection: t("memo.setCollection"), clear_collection: t("memo.clearCollection"),
      };
      showFlash("success", t("memo.bulkActionSuccess", { count: selectedIds.size, action: labels[action] }));
      if (action === "delete") setSelectedIds(new Set());
      await mutate();
      setBulkCollectionId(null);
    } catch (error) {
      showFlash("error", error instanceof Error ? error.message : t("memo.bulkActionFailed"));
      await mutate();
    } finally {
      setBulkLoading(false);
    }
  }, [collections, mutate, selectedIds, showFlash, updateMemoListOptimistically]);

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
