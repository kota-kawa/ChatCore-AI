import { useCallback, useLayoutEffect, useMemo, useRef, useState, type DragEvent } from "react";
import type { KeyedMutator } from "swr";

import { useTranslation } from "../../contexts/locale_context";
import { reorderMemos } from "../../lib/memo/api";
import type { FlashState, FrozenRect, MemoListState, MemoSummary } from "../../lib/memo/types";
import {
  applySectionProjection,
  captureCardSnapshot,
  computeProjectedOrderFromSnapshot,
  getMemoSectionKey,
  setMemoDragImage,
} from "../../lib/memo/utils";

type UseMemoPageDragParams = {
  memos: MemoSummary[];
  mutate: KeyedMutator<MemoListState>;
  showFlash: (type: FlashState["type"], text: string) => void;
  archiveScope: string;
  sortMode: string;
  query: string;
  isBulkMode: boolean;
  closeMemoActionMenu: () => void;
};

// ドラッグ＆ドロップによる手動並び替え（投影順・FLIP アニメーション・保存）
// Drag-and-drop manual reordering (projected order, FLIP animation, persistence)
export function useMemoPageDrag({
  memos,
  mutate,
  showFlash,
  archiveScope,
  sortMode,
  query,
  isBulkMode,
  closeMemoActionMenu,
}: UseMemoPageDragParams) {
  const { t } = useTranslation();

  const [draggedMemoId, setDraggedMemoId] = useState<string>("");
  const [dragProjectedOrder, setDragProjectedOrder] = useState<string[] | null>(null);
  const [dragSaving, setDragSaving] = useState(false);
  const cardRefs = useRef<Map<string, HTMLElement>>(new Map());
  const cardPositionsRef = useRef<Map<string, DOMRect>>(new Map());
  const dragSnapshotRef = useRef<Map<string, FrozenRect>>(new Map());
  const dragScrollRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });

  // While dragging, cards animate aside to preview the new order. The projection
  // is derived from a frozen geometry snapshot (see computeProjectedOrderFromSnapshot),
  // so the live reorder stays stable instead of oscillating.
  const displayMemos = useMemo(
    () => applySectionProjection(memos, dragProjectedOrder),
    [memos, dragProjectedOrder],
  );

  const { pinnedMemos, otherMemos } = useMemo(() => {
    const pinned: MemoSummary[] = [];
    const other: MemoSummary[] = [];
    for (const memo of displayMemos) {
      if (memo.is_pinned) pinned.push(memo);
      else other.push(memo);
    }
    return { pinnedMemos: pinned, otherMemos: other };
  }, [displayMemos]);

  const canDragMemos =
    archiveScope === "active" &&
    !isBulkMode &&
    !dragSaving &&
    sortMode === "manual" &&
    !query.trim();
  const canReorderCurrentView =
    canDragMemos;

  const clearMemoDragState = useCallback(() => {
    setDraggedMemoId("");
    setDragProjectedOrder(null);
    dragSnapshotRef.current = new Map();
  }, []);

  // メモのドラッグ開始時のハンドラー
  // Handler when starting to drag a memo
  const handleMemoDragStart = useCallback((event: DragEvent<HTMLElement>, memo: MemoSummary) => {
    if (!canDragMemos) {
      event.preventDefault();
      return;
    }
    const memoId = String(memo.id);
    closeMemoActionMenu();
    setDraggedMemoId(memoId);
    setDragProjectedOrder(null);
    // Freeze the current card geometry; every dragover hit-test resolves against
    // this snapshot so live column reflow can't perturb the targeting.
    dragSnapshotRef.current = captureCardSnapshot(cardRefs.current);
    dragScrollRef.current = { x: window.scrollX, y: window.scrollY };
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", memoId);
    setMemoDragImage(event);
  }, [canDragMemos, closeMemoActionMenu]);

  // メモをドラッグ中のリスト上の判定処理
  // Handler for drag-over events on the memo list to determine drop targets
  const handleMemoSectionDragOver = useCallback((event: DragEvent<HTMLUListElement>, sectionMemos: MemoSummary[]) => {
    if (!canReorderCurrentView || !draggedMemoId || sectionMemos.length === 0) return;
    const draggedMemo = memos.find((memo) => String(memo.id) === draggedMemoId);
    if (!draggedMemo || getMemoSectionKey(draggedMemo) !== getMemoSectionKey(sectionMemos[0])) return;

    event.preventDefault();
    event.dataTransfer.dropEffect = "move";

    // Map the pointer back into the snapshot's coordinate space, accounting for
    // any page scroll that happened since the drag began.
    const pointerX = event.clientX + (window.scrollX - dragScrollRef.current.x);
    const pointerY = event.clientY + (window.scrollY - dragScrollRef.current.y);
    const order = computeProjectedOrderFromSnapshot(
      memos,
      draggedMemoId,
      pointerX,
      pointerY,
      dragSnapshotRef.current,
    );
    if (!order) return;
    setDragProjectedOrder((prev) => {
      if (prev && prev.length === order.length && prev.every((id, i) => id === order[i])) {
        return prev;
      }
      return order;
    });
  }, [canReorderCurrentView, memos, draggedMemoId]);

  // ドラッグ＆ドロップ完了時の処理。並び順の更新を行う
  // Handler for dropping a memo. Updates the order of memos
  const handleMemoDrop = useCallback(async (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    const sourceId = draggedMemoId || event.dataTransfer.getData("text/plain");
    const projection = dragProjectedOrder;

    if (!canReorderCurrentView || !sourceId || !projection) {
      clearMemoDragState();
      return;
    }

    const movedIdx = projection.findIndex((id) => id === sourceId);
    if (movedIdx < 0) {
      clearMemoDragState();
      return;
    }

    const memoId = Number(sourceId);
    const beforeId = movedIdx > 0 ? Number(projection[movedIdx - 1]) : null;
    const afterId = movedIdx < projection.length - 1 ? Number(projection[movedIdx + 1]) : null;
    if (!Number.isFinite(memoId) || (beforeId !== null && !Number.isFinite(beforeId)) || (afterId !== null && !Number.isFinite(afterId))) {
      showFlash("error", t("memo.invalidReorderId"));
      clearMemoDragState();
      return;
    }

    setDragSaving(true);
    await mutate((current) => {
      if (!current) return current;
      const next = applySectionProjection(current.memos, projection);
      return { ...current, memos: next };
    }, { revalidate: false });
    clearMemoDragState();

    try {
      await reorderMemos({ memo_id: memoId, before_id: beforeId, after_id: afterId }, t("memo.reorderFailed"));
      await mutate();
    } catch (error) {
      showFlash("error", error instanceof Error ? error.message : t("memo.reorderFailed"));
      await mutate();
    } finally {
      setDragSaving(false);
    }
  }, [
    canReorderCurrentView,
    clearMemoDragState,
    dragProjectedOrder,
    draggedMemoId,
    mutate,
    showFlash,
  ]);

  // FLIP: animate cards smoothly to their new positions after a reorder.
  useLayoutEffect(() => {
    const prevPositions = cardPositionsRef.current;
    const nextPositions = new Map<string, DOMRect>();
    cardRefs.current.forEach((el, id) => {
      if (el && el.isConnected) nextPositions.set(id, el.getBoundingClientRect());
    });
    nextPositions.forEach((nextRect, id) => {
      if (id === draggedMemoId) return;
      const prevRect = prevPositions.get(id);
      if (!prevRect) return;
      const dx = prevRect.left - nextRect.left;
      const dy = prevRect.top - nextRect.top;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;
      const el = cardRefs.current.get(id);
      if (!el) return;
      el.style.transition = "none";
      el.style.transform = `translate(${dx}px, ${dy}px)`;
      void el.offsetWidth;
      el.style.transition = "";
      el.style.transform = "";
    });
    cardPositionsRef.current = nextPositions;
  }, [displayMemos, draggedMemoId]);

  return {
    canDragMemos,
    canReorderCurrentView,
    draggedMemoId,
    cardRefs,
    displayMemos,
    pinnedMemos,
    otherMemos,
    clearMemoDragState,
    handleMemoDragStart,
    handleMemoSectionDragOver,
    handleMemoDrop,
  };
}
