import { useCallback, useEffect, useMemo, useState } from "react";
import useSWR from "swr";

import { loadMemoList } from "../../lib/memo/api";
import { DEFAULT_LIMIT } from "../../lib/memo/constants";
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

  // 取得件数の上限。「もっと読み込む」で DEFAULT_LIMIT ずつ増やし、絞り込み条件が変わったら初期値へ戻す。
  // 条件の署名を state に同梱して「署名が一致するときだけ積み増した上限を使う」ことで、
  // リセットを useEffect でやった場合に起きる「古い上限での余計な1回の再取得」を避けている。
  // Ceiling on how many memos are fetched. "Load more" raises it by DEFAULT_LIMIT, and any filter change
  // drops it back to the default. The filter signature is stored alongside the value so the raised ceiling
  // only applies while the signature matches; resetting in an effect would instead fire one extra fetch
  // with the stale ceiling before the reset landed.
  const filterKey = useMemo(
    () => JSON.stringify([debouncedQuery, sortMode, archiveScope, activeCollectionId]),
    [activeCollectionId, archiveScope, debouncedQuery, sortMode],
  );
  const [limitState, setLimitState] = useState({ filterKey, limit: DEFAULT_LIMIT });
  const limit = limitState.filterKey === filterKey ? limitState.limit : DEFAULT_LIMIT;

  const loadMoreMemos = useCallback(() => {
    setLimitState((previous) => ({
      filterKey,
      limit: (previous.filterKey === filterKey ? previous.limit : DEFAULT_LIMIT) + DEFAULT_LIMIT,
    }));
  }, [filterKey]);

  const listUrl = useMemo(
    () => buildMemoListUrl({ query: debouncedQuery, sort: sortMode, archiveScope, collectionId: activeCollectionId, limit }),
    [archiveScope, debouncedQuery, sortMode, activeCollectionId, limit],
  );

  const { data: memoList = { memos: [], total: 0 }, error: memoLoadError, isLoading: memoListLoading, mutate } =
    useSWR<MemoListState, Error>(listUrl, loadMemoList, { revalidateOnFocus: true, keepPreviousData: true, dedupingInterval: 3000 });

  const memos = memoList.memos;
  const totalMemoCount = memoList.total;

  // まだ取得していないメモが残っているときだけ「もっと読み込む」を出す
  // The "load more" control is only offered while unfetched memos remain
  const remainingMemoCount = Math.max(0, totalMemoCount - memos.length);
  const canLoadMoreMemos = remainingMemoCount > 0;
  // keepPreviousData により読み込み中も前回の一覧が残るので、その間だけボタンを待機表示にする
  // keepPreviousData keeps the previous list on screen while fetching, so the button shows a busy state
  const isLoadingMoreMemos = memoListLoading && memos.length > 0;

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
    remainingMemoCount,
    canLoadMoreMemos,
    isLoadingMoreMemos,
    loadMoreMemos,
    memoLoadError,
    memoListLoading,
    mutate,
    updateMemoListOptimistically,
    hasActiveFilters,
  };
}
