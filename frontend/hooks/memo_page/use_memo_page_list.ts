import { useCallback, useEffect, useMemo, useState } from "react";
import useSWR from "swr";

import { loadMemoList } from "../../lib/memo/api";
import type { MemoListState, MemoSummary } from "../../lib/memo/types";
import { buildMemoListUrl } from "../../lib/memo/utils";

// メモ一覧の検索・並び替え・絞り込み状態と、一覧データの取得・楽観更新
// Search / sort / filter state for the memo list plus the list fetch and optimistic updates
export function useMemoPageList() {
  // Filter/sort state
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [sortMode, setSortMode] = useState("manual");
  const [archiveScope, setArchiveScope] = useState("active");
  const [activeCollectionId, setActiveCollectionId] = useState<number | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query), 300);
    return () => window.clearTimeout(timer);
  }, [query]);

  const listUrl = useMemo(
    () => buildMemoListUrl({ query: debouncedQuery, sort: sortMode, archiveScope, collectionId: activeCollectionId }),
    [archiveScope, debouncedQuery, sortMode, activeCollectionId],
  );

  const { data: memoList = { memos: [], total: 0 }, error: memoLoadError, isLoading: memoListLoading, mutate } =
    useSWR<MemoListState, Error>(listUrl, loadMemoList, { revalidateOnFocus: true, keepPreviousData: true, dedupingInterval: 3000 });

  const memos = memoList.memos;
  const totalMemoCount = memoList.total;

  const shouldKeepMemoInCurrentList = useCallback((memo: MemoSummary) => {
    if (archiveScope === "active" && memo.is_archived) return false;
    if (archiveScope === "archived" && !memo.is_archived) return false;
    if (activeCollectionId !== null && memo.collection_id !== activeCollectionId) return false;
    return true;
  }, [activeCollectionId, archiveScope]);

  const updateMemoListOptimistically = useCallback(
    async (updater: (memo: MemoSummary) => MemoSummary | null, targetIds: Iterable<string | number>) => {
      const targets = new Set(Array.from(targetIds, String));
      await mutate((current) => {
        if (!current) return current;
        let changed = false;
        const nextMemos: MemoSummary[] = [];

        current.memos.forEach((memo) => {
          if (!targets.has(String(memo.id))) {
            nextMemos.push(memo);
            return;
          }

          changed = true;
          const nextMemo = updater(memo);
          if (nextMemo && shouldKeepMemoInCurrentList(nextMemo)) {
            nextMemos.push(nextMemo);
          }
        });

        if (!changed) return current;
        return {
          ...current,
          memos: nextMemos,
          total: Math.max(0, current.total + nextMemos.length - current.memos.length),
        };
      }, { revalidate: false });
    },
    [mutate, shouldKeepMemoInCurrentList],
  );

  const hasActiveFilters = Boolean(query.trim()) || sortMode !== "manual" || archiveScope !== "active" || activeCollectionId !== null;

  return {
    query,
    setQuery,
    sortMode,
    setSortMode,
    archiveScope,
    setArchiveScope,
    activeCollectionId,
    setActiveCollectionId,
    memos,
    totalMemoCount,
    memoLoadError,
    memoListLoading,
    mutate,
    updateMemoListOptimistically,
    hasActiveFilters,
  };
}
