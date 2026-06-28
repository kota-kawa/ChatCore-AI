import { type DragEvent } from "react";

import {
  DEFAULT_LIMIT,
  MEMO_ACTION_MENU_ESTIMATED_HEIGHT,
  MEMO_ACTION_MENU_GAP,
  MEMO_ACTION_MENU_VIEWPORT_MARGIN,
  MEMO_ACTION_MENU_WIDTH,
} from "./constants";
import type { FrozenRect, MemoActionMenuPosition, MemoDropPosition, MemoSummary } from "./types";

// ---------------------------------------------------------------------------
// Memo page utilities
// ---------------------------------------------------------------------------

// メモのテキストをパースする関数。必要に応じてJSONから文字列を抽出する。
// Function to parse memo text. Extracts string from JSON if necessary.
export function parseMemoText(raw: string | null | undefined) {
  if (!raw) return "";
  try {
    const parsed = JSON.parse(raw);
    return typeof parsed === "string" ? parsed : "";
  } catch {
    return raw;
  }
}

// メモ一覧を取得するためのURLを構築する関数
// Function to build the URL for fetching the memo list
export function buildMemoListUrl(options: {
  query: string;
  sort: string;
  archiveScope: string;
  collectionId: number | null;
}) {
  const params = new URLSearchParams();
  params.set("limit", String(DEFAULT_LIMIT));
  params.set("offset", "0");
  params.set("sort", options.sort);
  params.set("pinned_first", "1");

  const tq = options.query.trim();
  if (tq) params.set("q", tq);
  if (options.archiveScope === "all") params.set("include_archived", "1");
  else if (options.archiveScope === "archived") params.set("only_archived", "1");
  if (options.collectionId !== null) params.set("collection_id", String(options.collectionId));

  return `/memo/api/recent?${params.toString()}`;
}

// メモのアクションメニューの表示位置を計算する関数
// Function to calculate the display position of the memo action menu
export function getMemoActionMenuPosition(trigger: HTMLElement): MemoActionMenuPosition {
  const rect = trigger.getBoundingClientRect();
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const width = MEMO_ACTION_MENU_WIDTH;
  const left = Math.min(
    Math.max(MEMO_ACTION_MENU_VIEWPORT_MARGIN, rect.right - width),
    Math.max(MEMO_ACTION_MENU_VIEWPORT_MARGIN, viewportWidth - width - MEMO_ACTION_MENU_VIEWPORT_MARGIN),
  );
  const spaceAbove = rect.top - MEMO_ACTION_MENU_VIEWPORT_MARGIN;
  const spaceBelow = viewportHeight - rect.bottom - MEMO_ACTION_MENU_VIEWPORT_MARGIN;
  const openBelow = spaceBelow >= MEMO_ACTION_MENU_ESTIMATED_HEIGHT || spaceBelow >= spaceAbove;
  const availableHeight = Math.max(
    120,
    (openBelow ? spaceBelow : spaceAbove) - MEMO_ACTION_MENU_GAP,
  );
  const top = openBelow
    ? Math.min(rect.bottom + MEMO_ACTION_MENU_GAP, viewportHeight - MEMO_ACTION_MENU_VIEWPORT_MARGIN - availableHeight)
    : Math.max(MEMO_ACTION_MENU_VIEWPORT_MARGIN, rect.top - MEMO_ACTION_MENU_GAP - Math.min(MEMO_ACTION_MENU_ESTIMATED_HEIGHT, availableHeight));
  return { top, left, width, maxHeight: availableHeight };
}

// メモのセクションキー（ピン留め、アーカイブ状態など）を取得する関数
// Function to get the section key for a memo (e.g., pinned or archived status)
export function getMemoSectionKey(memo: MemoSummary) {
  return `${memo.is_pinned ? "pinned" : "other"}:${memo.is_archived ? "archived" : "active"}`;
}

// ドラッグ＆ドロップ時のメモのセクション内の並び順を計算する関数
// Function to compute the projected section order of memos during drag & drop
export function computeProjectedSectionOrder(
  memos: MemoSummary[],
  draggedId: string,
  targetId: string,
  position: MemoDropPosition,
): string[] | null {
  if (!draggedId || !targetId || draggedId === targetId) return null;
  const draggedMemo = memos.find((memo) => String(memo.id) === draggedId);
  const targetMemo = memos.find((memo) => String(memo.id) === targetId);
  if (!draggedMemo || !targetMemo) return null;
  const sectionKey = getMemoSectionKey(draggedMemo);
  if (getMemoSectionKey(targetMemo) !== sectionKey) return null;

  const section = memos.filter((memo) => getMemoSectionKey(memo) === sectionKey);
  const without = section.filter((memo) => String(memo.id) !== draggedId);
  const targetIdx = without.findIndex((memo) => String(memo.id) === targetId);
  if (targetIdx < 0) return null;
  const insertIdx = position === "before" ? targetIdx : targetIdx + 1;
  const next = [...without];
  next.splice(insertIdx, 0, draggedMemo);
  return next.map((memo) => String(memo.id));
}

// Snapshot every card's geometry once, at drag start. Hit-testing during the
// drag reads these frozen rects instead of live `getBoundingClientRect()`, so a
// reorder that reflows the masonry columns can't feed back into the next
// targeting pass. That feedback loop was what made the board oscillate; with a
// frozen reference the projection is a pure function of the pointer position and
// stays rock-steady while the cards still animate aside to make room.
// 各カードの現在の位置情報のスナップショットをキャプチャする関数
// Function to capture a snapshot of current position info for each card
export function captureCardSnapshot(cardRefs: Map<string, HTMLElement>): Map<string, FrozenRect> {
  const snapshot = new Map<string, FrozenRect>();
  cardRefs.forEach((element, id) => {
    if (!element || !element.isConnected) return;
    const rect = element.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    snapshot.set(id, { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom });
  });
  return snapshot;
}

// スナップショットとポインター位置から予測される並び順を計算する関数
// Function to compute the projected order from snapshots and pointer position
export function computeProjectedOrderFromSnapshot(
  memos: MemoSummary[],
  draggedId: string,
  pointerX: number,
  pointerY: number,
  snapshot: Map<string, FrozenRect>,
): string[] | null {
  const draggedMemo = memos.find((memo) => String(memo.id) === draggedId);
  if (!draggedMemo) return null;
  const sectionKey = getMemoSectionKey(draggedMemo);
  const section = memos.filter((memo) => getMemoSectionKey(memo) === sectionKey);
  const without = section.filter((memo) => String(memo.id) !== draggedId);
  if (without.length === 0) return null;

  // Card the cursor is directly over wins; otherwise fall back to the card whose
  // frozen center is closest so dragging into a column gap still resolves a target.
  let directHit: { id: string; rect: FrozenRect } | null = null;
  let nearest: { id: string; rect: FrozenRect; distance: number } | null = null;
  for (const memo of without) {
    const id = String(memo.id);
    const rect = snapshot.get(id);
    if (!rect) continue;
    const inside =
      pointerX >= rect.left &&
      pointerX <= rect.right &&
      pointerY >= rect.top &&
      pointerY <= rect.bottom;
    if (inside && !directHit) {
      directHit = { id, rect };
    }
    const cx = (rect.left + rect.right) / 2;
    const cy = (rect.top + rect.bottom) / 2;
    const dx = pointerX - cx;
    const dy = pointerY - cy;
    const distance = dx * dx + dy * dy;
    if (!nearest || distance < nearest.distance) {
      nearest = { id, rect, distance };
    }
  }

  const chosen = directHit ?? nearest;
  if (!chosen) return null;

  // Drop before the target when the pointer sits in its upper half, after when in
  // the lower half — natural for both single-column and masonry column layouts.
  const cy = (chosen.rect.top + chosen.rect.bottom) / 2;
  const position: MemoDropPosition = pointerY < cy ? "before" : "after";
  return computeProjectedSectionOrder(memos, draggedId, chosen.id, position);
}

// 計算された並び順のプロジェクションを実際のメモ配列に適用する関数
// Function to apply the computed projection of order to the actual memo array
export function applySectionProjection(memos: MemoSummary[], projection: string[] | null): MemoSummary[] {
  if (!projection || projection.length === 0) return memos;
  const projectedSet = new Set(projection);
  const idToMemo = new Map(memos.map((memo) => [String(memo.id), memo]));
  const result: MemoSummary[] = [];
  let projIdx = 0;
  for (const memo of memos) {
    if (projectedSet.has(String(memo.id))) {
      while (projIdx < projection.length) {
        const m = idToMemo.get(projection[projIdx++]);
        if (m) {
          result.push(m);
          break;
        }
      }
    } else {
      result.push(memo);
    }
  }
  return result;
}

// ドラッグ時のカスタムイメージ（ドラッグ中要素のクローン）を設定する関数
// Function to set a custom drag image (clone of the dragged element) during drag
export function setMemoDragImage(event: DragEvent<HTMLElement>) {
  const source = event.currentTarget;
  const rect = source.getBoundingClientRect();
  const preview = source.cloneNode(true) as HTMLElement;
  preview.classList.add("memo-item--drag-preview");
  preview.classList.remove("is-dragging");
  preview.setAttribute("aria-hidden", "true");
  preview.style.width = `${rect.width}px`;
  preview.style.height = `${rect.height}px`;
  preview.style.left = `${rect.left}px`;
  preview.style.top = `${rect.top}px`;
  document.body.appendChild(preview);

  const offsetX = Math.max(0, Math.min(event.clientX - rect.left, rect.width));
  const offsetY = Math.max(0, Math.min(event.clientY - rect.top, rect.height));
  event.dataTransfer.setDragImage(preview, offsetX, offsetY);

  window.setTimeout(() => {
    preview.remove();
  }, 0);
}
