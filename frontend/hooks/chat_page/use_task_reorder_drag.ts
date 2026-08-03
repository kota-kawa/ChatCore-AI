import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  type PointerEvent as ReactPointerEvent,
} from "react";

import type { NormalizedTask } from "../../lib/chat_page/types";
import { getStableTaskKey } from "../../lib/chat_page/task_utils";

// マウス・ペンでドラッグ開始と判定するための最小移動距離（ピクセル）
// Minimum pointer movement in pixels before a mouse/pen drag gesture is recognized
const POINTER_DRAG_START_THRESHOLD_PX = 8;

// タッチは縦スクロールと並び替えが同じ縦スワイプになるため、距離ではなく長押し時間で区別する
// Touch scrolling and reordering are both vertical swipes, so touch uses hold time instead of distance
const TOUCH_DRAG_HOLD_DELAY_MS = 300;

// 長押し待機中にこの距離を超えて指が動いたらスクロール操作とみなす
// Moving further than this while waiting for the hold means the user intended to scroll
const TOUCH_DRAG_MOVE_TOLERANCE_PX = 10;

// ドラッグ中にスクロールコンテナの端へ近づいたら自動スクロールを始める距離
// Distance from the scroll container edge where drag auto-scrolling kicks in
const AUTO_SCROLL_EDGE_PX = 76;

// 自動スクロールの1フレームあたりの最大移動量
// Maximum auto-scroll distance applied per animation frame
const AUTO_SCROLL_MAX_STEP_PX = 18;

type ScrollViewport = {
  top: number;
  bottom: number;
  scrollTop: number;
  maxScrollTop: number;
};

type UseTaskReorderDragOptions = {
  tasks: NormalizedTask[];
  isTaskOrderEditing: boolean;
  // ドロップ後の後始末をタスク配列が変わらない場合にも走らせるため、ドラッグ中インデックスを監視する
  // Watching the dragging index lets the drop cleanup run even when the task array is unchanged
  draggingTaskIndex: number | null;
  // モーダル表示や画面遷移でドラッグを中断すべきかどうか
  // Whether an overlay or view change should abort any in-flight drag
  isDragInterrupted: boolean;
  onDragStart: (dragIndex: number) => void;
  onDragEnd: (dragIndex: number, dropTargetIndex: number) => void;
};

// カードの直近のスクロール可能な祖先要素を探す（見つからなければ null = ページ全体のスクロール）
// Find the nearest scrollable ancestor; null means the page itself scrolls
function resolveScrollContainer(element: HTMLElement | null): HTMLElement | null {
  let node = element?.parentElement ?? null;

  while (node) {
    // ルート要素（html / body）は要素として扱わない。矩形が文書全体の高さになり
    // 「画面端に近いか」の判定が壊れるため、ページスクロール側の経路に任せる。
    // Stop at the root elements: their rect spans the whole document rather than the
    // viewport, which would break the edge test, so page scrolling handles them.
    if (node === document.body || node === document.documentElement) return null;

    const { overflowY } = window.getComputedStyle(node);
    const isScrollable = overflowY === "auto" || overflowY === "scroll" || overflowY === "overlay";
    if (isScrollable && node.scrollHeight > node.clientHeight + 1) return node;
    node = node.parentElement;
  }

  return null;
}

// スクロールコンテナ（またはページ）の可視範囲とスクロール量をまとめて取得する
// Read the visible bounds and scroll offsets of the container (or the page) in one place
function readScrollViewport(container: HTMLElement | null): ScrollViewport {
  if (container) {
    const rect = container.getBoundingClientRect();
    return {
      top: rect.top,
      bottom: rect.bottom,
      scrollTop: container.scrollTop,
      maxScrollTop: Math.max(0, container.scrollHeight - container.clientHeight),
    };
  }

  const viewportHeight = window.visualViewport?.height ?? window.innerHeight;
  const documentElement = document.documentElement;
  return {
    top: 0,
    bottom: viewportHeight,
    scrollTop: window.scrollY,
    maxScrollTop: Math.max(0, documentElement.scrollHeight - viewportHeight),
  };
}

function applyScrollTop(container: HTMLElement | null, scrollTop: number) {
  if (container) {
    container.scrollTop = scrollTop;
    return;
  }
  window.scrollTo(window.scrollX, scrollTop);
}

// 端からの侵入量に比例した自動スクロール量を求める（端に近いほど速い）
// Scale the auto-scroll step by how deep the pointer sits inside the edge zone
function calculateAutoScrollStep(distanceFromEdge: number): number {
  const intrusion = Math.min(AUTO_SCROLL_EDGE_PX, AUTO_SCROLL_EDGE_PX - distanceFromEdge);
  if (intrusion <= 0) return 0;
  const ratio = intrusion / AUTO_SCROLL_EDGE_PX;
  return Math.max(1, Math.round(AUTO_SCROLL_MAX_STEP_PX * ratio * ratio));
}

// タスクカードのポインタードラッグによる並び替えを制御するフック
// Owns the pointer-driven drag & drop reordering behaviour of the task card list
export function useTaskReorderDrag({
  tasks,
  isTaskOrderEditing,
  draggingTaskIndex,
  isDragInterrupted,
  onDragStart,
  onDragEnd,
}: UseTaskReorderDragOptions) {
  // DOM refs
  const taskWrapperRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  // タスクオブジェクトとDOMキーの対応を管理（Reactの再レンダリング間でキーを安定させる）
  // Map task objects to stable DOM keys so drag handles survive React re-renders
  const taskObjectKeyMapRef = useRef<WeakMap<object, string>>(new WeakMap());
  const taskObjectSequenceRef = useRef(0);

  // Drag state refs
  const activePointerIdRef = useRef<number | null>(null);
  const activePointerTypeRef = useRef<string | null>(null);
  const dragStartPointRef = useRef<{ x: number; y: number } | null>(null);
  const dragPointerOffsetRef = useRef<{ x: number; y: number } | null>(null);
  const lastPointerPointRef = useRef<{ x: number; y: number } | null>(null);
  const draggingTaskDomKeyRef = useRef<string | null>(null);
  const draggingTaskIndexRef = useRef<number | null>(null);
  const dropTargetIndexRef = useRef<number | null>(null);
  const startRectsRef = useRef<Map<string, DOMRect>>(new Map());
  const isPointerDragActiveRef = useRef(false);

  // タッチの長押し判定と自動スクロール用のタイマー
  // Timers backing the touch hold gesture and the drag auto-scroll loop
  const holdTimerRef = useRef<number | null>(null);
  const autoScrollRafRef = useRef<number | null>(null);
  const scrollContainerRef = useRef<HTMLElement | null>(null);
  const blockTouchScrollHandlerRef = useRef<((event: TouchEvent) => void) | null>(null);

  // Drop completion refs (for useLayoutEffect animation)
  const justDroppedDomKeyRef = useRef<string | null>(null);
  const isDropCompletingRef = useRef(false);

  // ステートが変わるたびに最新のタスクリストをrefに同期（イベントリスナー内のクロージャ陳腐化を防ぐ）
  // Keep a live ref to tasks to avoid stale closures in callbacks
  const tasksRef = useRef(tasks);
  tasksRef.current = tasks;

  // タスクオブジェクトに対して安定したDOMキーを割り当てる（オブジェクト参照が変わっても追跡可能）
  // Assign a stable DOM key to each task object so drag state survives list mutations
  const getTaskDomKey = useCallback((taskObject: object) => {
    const task = taskObject as NormalizedTask;
    const stableKey = getStableTaskKey(task);
    if (stableKey) return stableKey;
    const existing = taskObjectKeyMapRef.current.get(taskObject);
    if (existing) return existing;
    const nextKey = `task-dom-${taskObjectSequenceRef.current++}`;
    taskObjectKeyMapRef.current.set(taskObject, nextKey);
    return nextKey;
  }, []);

  // タスクカードのDOMノードをMapに登録・解除して、ドラッグ時の位置計算に使えるようにする
  // Register or unregister task wrapper DOM nodes so their rects are available during drag
  const setTaskWrapperRef = useCallback((taskDomKey: string, node: HTMLDivElement | null) => {
    if (node) {
      taskWrapperRefs.current.set(taskDomKey, node);
      return;
    }
    taskWrapperRefs.current.delete(taskDomKey);
  }, []);

  const clearHoldTimer = useCallback(() => {
    if (holdTimerRef.current === null) return;
    window.clearTimeout(holdTimerRef.current);
    holdTimerRef.current = null;
  }, []);

  const stopAutoScroll = useCallback(() => {
    if (autoScrollRafRef.current === null) return;
    window.cancelAnimationFrame(autoScrollRafRef.current);
    autoScrollRafRef.current = null;
  }, []);

  // ドラッグ確定後はブラウザのスクロールを止めて、指の動きをすべて並び替えに使う
  // Once the drag is committed, suppress browser scrolling so the finger only moves the card
  const startBlockingTouchScroll = useCallback(() => {
    if (blockTouchScrollHandlerRef.current) return;

    const handleTouchMove = (event: TouchEvent) => {
      if (!isPointerDragActiveRef.current) return;
      if (event.cancelable) event.preventDefault();
    };

    blockTouchScrollHandlerRef.current = handleTouchMove;
    document.addEventListener("touchmove", handleTouchMove, { passive: false });
  }, []);

  const stopBlockingTouchScroll = useCallback(() => {
    const handleTouchMove = blockTouchScrollHandlerRef.current;
    if (!handleTouchMove) return;
    document.removeEventListener("touchmove", handleTouchMove);
    blockTouchScrollHandlerRef.current = null;
  }, []);

  // Apply transforms to non-dragged items to visually show where the dragged card will land
  const applyDragTransforms = useCallback(() => {
    const dragIndex = draggingTaskIndexRef.current;
    const dropTarget = dropTargetIndexRef.current;
    if (dragIndex === null || dropTarget === null) return;

    const currentTasks = tasksRef.current;
    const startRects = startRectsRef.current;

    currentTasks.forEach((task, originalIndex) => {
      const domKey = getTaskDomKey(task);
      const wrapper = taskWrapperRefs.current.get(domKey);
      if (!wrapper) return;
      if (originalIndex === dragIndex) return; // dragged card handled separately

      // ドロップ先に応じて各カードがずれるスロットを計算する
      // Determine which slot this item shifts to based on drag and drop positions
      let shiftedIndex = originalIndex;
      if (dropTarget > dragIndex && originalIndex > dragIndex && originalIndex <= dropTarget) {
        shiftedIndex = originalIndex - 1; // shift back
      } else if (dropTarget < dragIndex && originalIndex >= dropTarget && originalIndex < dragIndex) {
        shiftedIndex = originalIndex + 1; // shift forward
      }

      if (shiftedIndex === originalIndex) {
        wrapper.style.transform = "translate3d(0, 0, 0)";
        return;
      }

      // Calculate the transform using captured start rects
      const targetTask = currentTasks[shiftedIndex];
      if (!targetTask) return;
      const targetDomKey = getTaskDomKey(targetTask);
      const targetRect = startRects.get(targetDomKey);
      const myRect = startRects.get(domKey);
      if (!targetRect || !myRect) return;

      const dx = targetRect.left - myRect.left;
      const dy = targetRect.top - myRect.top;
      wrapper.style.transform = `translate3d(${dx}px, ${dy}px, 0)`;
    });
  }, [getTaskDomKey]);

  // ドラッグ中のカードの視覚的中心に最も近いスロットをドロップ先として決定する
  // Find the slot closest to the dragged card's visual center and update transforms
  const updateDropTarget = useCallback(
    (draggedCenterX: number, draggedCenterY: number) => {
      const dragIndex = draggingTaskIndexRef.current;
      if (dragIndex === null) return;

      const currentTasks = tasksRef.current;
      const startRects = startRectsRef.current;

      let bestIndex = dropTargetIndexRef.current ?? dragIndex;
      let bestDist = Infinity;

      // 各タスクのスロット中心との距離を比較して最近傍を見つける
      // Compare distances to each slot's center to find the nearest drop target
      currentTasks.forEach((task, i) => {
        const domKey = getTaskDomKey(task);
        const rect = startRects.get(domKey);
        if (!rect || rect.width === 0) return;

        const cx = rect.left + rect.width / 2;
        const cy = rect.top + rect.height / 2;
        const dist = Math.hypot(draggedCenterX - cx, draggedCenterY - cy);

        if (dist < bestDist) {
          bestDist = dist;
          bestIndex = i;
        }
      });

      if (bestIndex !== dropTargetIndexRef.current) {
        dropTargetIndexRef.current = bestIndex;
        applyDragTransforms();
      }
    },
    [getTaskDomKey, applyDragTransforms],
  );

  // ポインターの現在位置に合わせてドラッグ中のカードを動かし、ドロップ先を更新する
  // Move the dragged card to the current pointer position and refresh the drop target
  const syncDraggedCardToPointer = useCallback(() => {
    const draggingTaskDomKey = draggingTaskDomKeyRef.current;
    const pointerPoint = lastPointerPointRef.current;
    const pointerOffset = dragPointerOffsetRef.current;
    if (!draggingTaskDomKey || !pointerPoint || !pointerOffset) return;

    const draggingTaskWrapper = taskWrapperRefs.current.get(draggingTaskDomKey);
    const myStartRect = startRectsRef.current.get(draggingTaskDomKey);
    if (!draggingTaskWrapper || !myStartRect) return;

    const currentLeft = pointerPoint.x - pointerOffset.x;
    const currentTop = pointerPoint.y - pointerOffset.y;
    const deltaX = currentLeft - myStartRect.left;
    const deltaY = currentTop - myStartRect.top;
    draggingTaskWrapper.style.transform = `translate3d(${deltaX}px, ${deltaY}px, 0)`;

    updateDropTarget(currentLeft + myStartRect.width / 2, currentTop + myStartRect.height / 2);
  }, [updateDropTarget]);

  // 全カードの位置を取り直す（スクロールやリサイズで座標がずれた後の再同期に使う）
  // Recapture element rects after scroll/resize so the dragged card and transforms stay accurate
  const refreshDragGeometry = useCallback(() => {
    if (!isPointerDragActiveRef.current) return;

    const draggingTaskDomKey = draggingTaskDomKeyRef.current;
    if (!draggingTaskDomKey || !lastPointerPointRef.current || !dragPointerOffsetRef.current) return;

    taskWrapperRefs.current.forEach((wrapper) => {
      wrapper.style.transition = "none";
      wrapper.style.transform = "";
    });
    void document.body.offsetHeight;

    const nextRects = new Map<string, DOMRect>();
    taskWrapperRefs.current.forEach((element, domKey) => {
      nextRects.set(domKey, element.getBoundingClientRect());
    });
    startRectsRef.current = nextRects;

    taskWrapperRefs.current.forEach((wrapper, domKey) => {
      if (domKey !== draggingTaskDomKey) {
        wrapper.style.transition = "";
      }
    });

    syncDraggedCardToPointer();
    applyDragTransforms();
  }, [applyDragTransforms, syncDraggedCardToPointer]);

  // 端に近づいたらスクロールコンテナを自動で送り、画面外のスロットへも運べるようにする
  // Auto-scroll the container while the pointer sits near an edge so off-screen slots stay reachable
  const stepAutoScroll = useCallback(() => {
    autoScrollRafRef.current = null;
    if (!isPointerDragActiveRef.current) return;

    const pointerPoint = lastPointerPointRef.current;
    if (!pointerPoint) return;

    const container = scrollContainerRef.current;
    const viewport = readScrollViewport(container);

    let step = 0;
    const distanceFromTop = pointerPoint.y - viewport.top;
    const distanceFromBottom = viewport.bottom - pointerPoint.y;

    if (distanceFromTop < AUTO_SCROLL_EDGE_PX) {
      step = -calculateAutoScrollStep(distanceFromTop);
    } else if (distanceFromBottom < AUTO_SCROLL_EDGE_PX) {
      step = calculateAutoScrollStep(distanceFromBottom);
    }

    if (step === 0) return;

    const nextScrollTop = Math.min(Math.max(viewport.scrollTop + step, 0), viewport.maxScrollTop);
    if (nextScrollTop === viewport.scrollTop) return;

    applyScrollTop(container, nextScrollTop);
    refreshDragGeometry();
    autoScrollRafRef.current = window.requestAnimationFrame(stepAutoScroll);
  }, [refreshDragGeometry]);

  const scheduleAutoScroll = useCallback(() => {
    if (autoScrollRafRef.current !== null) return;
    if (!isPointerDragActiveRef.current) return;
    autoScrollRafRef.current = window.requestAnimationFrame(stepAutoScroll);
  }, [stepAutoScroll]);

  // ポインタードラッグを終了し、アニメーション状態をリセットしてReactに結果を通知する
  // End an in-progress pointer drag, clean up all drag state, and commit the reorder to React
  const finishPointerDrag = useCallback(
    (pointerId?: number) => {
      const activePointerId = activePointerIdRef.current;
      const draggingTaskDomKey = draggingTaskDomKeyRef.current;
      const hasActivePointerDrag = activePointerId !== null || draggingTaskDomKey !== null;
      if (!hasActivePointerDrag) return;

      if (typeof pointerId === "number" && activePointerId !== pointerId) return;

      clearHoldTimer();
      stopAutoScroll();
      stopBlockingTouchScroll();

      // ポインターキャプチャを安全に解放する（既に解放済みの場合は無視）
      // Safely release pointer capture; ignore if it was already released
      if (activePointerId !== null && draggingTaskDomKey) {
        const draggingTaskWrapper = taskWrapperRefs.current.get(draggingTaskDomKey);
        try {
          if (draggingTaskWrapper?.hasPointerCapture?.(activePointerId)) {
            draggingTaskWrapper.releasePointerCapture(activePointerId);
          }
        } catch {
          // already released
        }
      }

      const dragIndex = draggingTaskIndexRef.current;
      const dropTarget = dropTargetIndexRef.current;
      const wasPointerDragActive = isPointerDragActiveRef.current;

      if (wasPointerDragActive) {
        // Signal useLayoutEffect to run drop-completion animation
        justDroppedDomKeyRef.current = draggingTaskDomKey;
        isDropCompletingRef.current = true;
      }

      // すべてのドラッグ状態をリセットする
      // Reset all drag tracking state to its initial values
      activePointerIdRef.current = null;
      activePointerTypeRef.current = null;
      dragStartPointRef.current = null;
      dragPointerOffsetRef.current = null;
      lastPointerPointRef.current = null;
      draggingTaskDomKeyRef.current = null;
      draggingTaskIndexRef.current = null;
      dropTargetIndexRef.current = null;
      startRectsRef.current = new Map();
      scrollContainerRef.current = null;
      isPointerDragActiveRef.current = false;

      if (!wasPointerDragActive) {
        taskWrapperRefs.current.forEach((wrapper) => {
          wrapper.style.transition = "";
          wrapper.style.transform = "";
        });
        return;
      }

      const finalDragIndex = typeof dragIndex === "number" ? dragIndex : 0;
      const finalDropTarget = typeof dropTarget === "number" ? dropTarget : finalDragIndex;
      onDragEnd(finalDragIndex, finalDropTarget);
    },
    [clearHoldTimer, onDragEnd, stopAutoScroll, stopBlockingTouchScroll],
  );

  // ドラッグ操作を正式に開始する（タッチは長押し完了時、マウス・ペンはしきい値超過時）
  // Commit to dragging: after the hold for touch, or once the move threshold is passed for mouse/pen
  const activatePointerDrag = useCallback(() => {
    if (isPointerDragActiveRef.current) return;

    const dragIndex = draggingTaskIndexRef.current;
    if (dragIndex === null) return;

    clearHoldTimer();
    isPointerDragActiveRef.current = true;

    if (activePointerTypeRef.current === "touch") {
      startBlockingTouchScroll();
      // 掴んだことを触覚で伝える（未対応環境では無視される）
      // Confirm the pick-up with a short haptic pulse where the device supports it
      navigator.vibrate?.(10);
    }

    onDragStart(dragIndex);
  }, [clearHoldTimer, onDragStart, startBlockingTouchScroll]);

  // タスクカードへのPointerDownを処理し、ドラッグ操作の前準備を行う
  // Handle pointer-down on a task card to set up all state needed for a potential drag
  const handleTaskPointerDown = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>, index: number, taskDomKey: string) => {
      if (!isTaskOrderEditing) return;
      if (event.pointerType !== "touch" && event.button !== 0) return;

      // 既にドラッグ中なら2本目の指は無視する（意図しない位置での確定を防ぐ）
      // Ignore extra fingers while a drag is running so it cannot drop at an unintended slot
      if (isPointerDragActiveRef.current) return;

      // インタラクティブ要素へのクリックはドラッグとして扱わない
      // Don't start a drag when the pointer lands on an interactive child element
      const target = event.target as Element | null;
      if (target?.closest("button, a, input, textarea, select, label")) {
        return;
      }

      finishPointerDrag();

      // Clear any existing transforms and force reflow before capturing rects
      taskWrapperRefs.current.forEach((wrapper) => {
        wrapper.style.transition = "none";
        wrapper.style.transform = "";
      });
      void document.body.offsetHeight;

      // Capture start rects (natural positions, no transforms)
      const startRects = new Map<string, DOMRect>();
      taskWrapperRefs.current.forEach((element, domKey) => {
        startRects.set(domKey, element.getBoundingClientRect());
      });
      const startRect = startRects.get(taskDomKey);
      if (!startRect) {
        taskWrapperRefs.current.forEach((wrapper) => {
          wrapper.style.transition = "";
        });
        return;
      }
      startRectsRef.current = startRects;

      // Restore CSS transition on non-dragged items
      taskWrapperRefs.current.forEach((wrapper, domKey) => {
        if (domKey !== taskDomKey) {
          wrapper.style.transition = "";
        }
      });

      // ドラッグ追跡に必要な全状態を初期化する
      // Initialize all drag-tracking state from the pointer-down event
      activePointerIdRef.current = event.pointerId;
      activePointerTypeRef.current = event.pointerType;
      dragStartPointRef.current = { x: event.clientX, y: event.clientY };
      dragPointerOffsetRef.current = {
        x: event.clientX - startRect.left,
        y: event.clientY - startRect.top,
      };
      lastPointerPointRef.current = { x: event.clientX, y: event.clientY };
      draggingTaskDomKeyRef.current = taskDomKey;
      draggingTaskIndexRef.current = index;
      dropTargetIndexRef.current = index;
      isPointerDragActiveRef.current = false;
      scrollContainerRef.current = resolveScrollContainer(event.currentTarget);

      try {
        if (!event.currentTarget.hasPointerCapture?.(event.pointerId)) {
          event.currentTarget.setPointerCapture?.(event.pointerId);
        }
      } catch {
        // capture is optional; window-level listeners keep the drag working without it
      }

      if (event.pointerType !== "touch") {
        event.preventDefault();
        return;
      }

      // タッチはこの時点ではまだドラッグを開始しない。長押しが完了して初めて掴む扱いにし、
      // それまでの指の動きはブラウザの縦スクロールに任せる。
      // Touch does not grab the card yet: only a completed hold starts the drag, so any earlier
      // finger movement stays with the browser's native vertical scrolling.
      clearHoldTimer();
      holdTimerRef.current = window.setTimeout(() => {
        holdTimerRef.current = null;
        activatePointerDrag();
      }, TOUCH_DRAG_HOLD_DELAY_MS);
    },
    [activatePointerDrag, clearHoldTimer, finishPointerDrag, isTaskOrderEditing],
  );

  // 編集モードがアクティブな間、ウィンドウレベルのポインターイベントを監視してドラッグを制御する
  // Attach and clean up window-level pointer event listeners while task reorder editing is active
  useEffect(() => {
    if (!isTaskOrderEditing) {
      finishPointerDrag();
      return;
    }

    const handleWindowPointerMove = (event: PointerEvent) => {
      const activePointerId = activePointerIdRef.current;
      if (activePointerId === null || event.pointerId !== activePointerId) return;

      const dragStartPoint = dragStartPointRef.current;
      const pointerOffset = dragPointerOffsetRef.current;
      const draggingTaskDomKey = draggingTaskDomKeyRef.current;
      if (!dragStartPoint || !pointerOffset || !draggingTaskDomKey) return;

      const pointerPoint = { x: event.clientX, y: event.clientY };
      lastPointerPointRef.current = pointerPoint;
      const dragDistance = Math.hypot(pointerPoint.x - dragStartPoint.x, pointerPoint.y - dragStartPoint.y);
      const dragIndex = draggingTaskIndexRef.current;

      if (!isPointerDragActiveRef.current) {
        // タッチは長押しが完了するまで待つ。それまでに指が動いたらスクロール操作として手放す。
        // Touch waits for the hold; moving before it completes hands the gesture back to scrolling.
        if (activePointerTypeRef.current === "touch") {
          if (dragDistance > TOUCH_DRAG_MOVE_TOLERANCE_PX) finishPointerDrag(activePointerId);
          return;
        }

        // マウス・ペンはしきい値を超えた移動が検出されて初めてドラッグ開始と判断する
        // Mouse and pen only activate after the pointer moves beyond the threshold
        if (dragDistance < POINTER_DRAG_START_THRESHOLD_PX || dragIndex === null) return;
        activatePointerDrag();
      }

      syncDraggedCardToPointer();
      scheduleAutoScroll();
    };

    const handleWindowPointerUp = (event: PointerEvent) => {
      finishPointerDrag(event.pointerId);
    };

    // リサイズ・スクロールイベントをrAFで間引いてパフォーマンスを保護する
    // Debounce resize/scroll events via requestAnimationFrame to avoid layout thrashing
    let geometryRafId: number | null = null;
    const scheduleRefreshDragGeometry = () => {
      if (geometryRafId !== null) {
        window.cancelAnimationFrame(geometryRafId);
      }

      geometryRafId = window.requestAnimationFrame(() => {
        geometryRafId = null;
        refreshDragGeometry();
      });
    };

    // スクロールが起きたら座標を取り直す。長押し待機中のスクロールはスクロール意図の証拠なので候補を捨てる。
    // Re-measure after scrolling; a scroll while waiting for the hold proves the user meant to scroll.
    const handleScrollCapture = () => {
      if (isPointerDragActiveRef.current) {
        scheduleRefreshDragGeometry();
        return;
      }
      if (activePointerIdRef.current !== null) {
        finishPointerDrag(activePointerIdRef.current);
      }
    };

    // 長押し中にAndroidのコンテキストメニューが出るとドラッグが中断されるため抑止する
    // Suppress the Android long-press context menu, which would otherwise interrupt the drag
    const handleContextMenu = (event: Event) => {
      if (activePointerTypeRef.current !== "touch") return;
      event.preventDefault();
    };

    const handleWindowBlur = () => {
      finishPointerDrag();
    };

    window.addEventListener("pointermove", handleWindowPointerMove, { passive: true });
    window.addEventListener("pointerup", handleWindowPointerUp);
    window.addEventListener("pointercancel", handleWindowPointerUp);
    window.addEventListener("scroll", handleScrollCapture, { capture: true, passive: true });
    window.addEventListener("contextmenu", handleContextMenu);
    window.addEventListener("blur", handleWindowBlur);
    window.addEventListener("resize", scheduleRefreshDragGeometry);
    window.addEventListener("orientationchange", scheduleRefreshDragGeometry);
    window.visualViewport?.addEventListener("resize", scheduleRefreshDragGeometry);
    window.visualViewport?.addEventListener("scroll", scheduleRefreshDragGeometry);

    return () => {
      if (geometryRafId !== null) {
        window.cancelAnimationFrame(geometryRafId);
      }
      window.removeEventListener("pointermove", handleWindowPointerMove);
      window.removeEventListener("pointerup", handleWindowPointerUp);
      window.removeEventListener("pointercancel", handleWindowPointerUp);
      window.removeEventListener("scroll", handleScrollCapture, { capture: true });
      window.removeEventListener("contextmenu", handleContextMenu);
      window.removeEventListener("blur", handleWindowBlur);
      window.removeEventListener("resize", scheduleRefreshDragGeometry);
      window.removeEventListener("orientationchange", scheduleRefreshDragGeometry);
      window.visualViewport?.removeEventListener("resize", scheduleRefreshDragGeometry);
      window.visualViewport?.removeEventListener("scroll", scheduleRefreshDragGeometry);
    };
  }, [
    activatePointerDrag,
    finishPointerDrag,
    isTaskOrderEditing,
    refreshDragGeometry,
    scheduleAutoScroll,
    syncDraggedCardToPointer,
  ]);

  // ページ遷移やモーダル表示でセットアップ画面が非表示になったらドラッグを終了する
  // Abort any ongoing drag when the setup view is hidden or a modal interrupts interaction
  useEffect(() => {
    if (isDragInterrupted) {
      finishPointerDrag();
    }
  }, [finishPointerDrag, isDragInterrupted]);

  // コンポーネントのアンマウント時にドラッグを確実に終了する（メモリリーク防止）
  // Ensure drag is fully cleaned up when the component unmounts to prevent memory leaks
  useEffect(() => {
    return () => {
      clearHoldTimer();
      stopAutoScroll();
      stopBlockingTouchScroll();
    };
  }, [clearHoldTimer, stopAutoScroll, stopBlockingTouchScroll]);

  // Post-drop animation and cleanup
  useLayoutEffect(() => {
    if (isDropCompletingRef.current) {
      isDropCompletingRef.current = false;
      const droppedDomKey = justDroppedDomKeyRef.current;
      justDroppedDomKeyRef.current = null;

      if (!isTaskOrderEditing) {
        // Editing ended: just clear everything
        taskWrapperRefs.current.forEach((wrapper) => {
          wrapper.style.transition = "";
          wrapper.style.transform = "";
        });
        return;
      }

      // Non-dragged items are already at their correct visual positions — clear instantly
      taskWrapperRefs.current.forEach((wrapper, domKey) => {
        if (domKey === droppedDomKey) return;
        wrapper.style.transition = "none";
        wrapper.style.transform = "";
      });

      // ドロップしたカードをイージングアニメーションで自然な位置にスナップさせる
      // Animate dropped card snapping to its new natural position with an ease-out curve
      if (droppedDomKey) {
        const droppedWrapper = taskWrapperRefs.current.get(droppedDomKey);
        if (droppedWrapper) {
          droppedWrapper.style.transition = "transform 220ms cubic-bezier(0.22, 1, 0.36, 1)";
          droppedWrapper.style.transform = "";
        }
      }

      return;
    }

    if (!isTaskOrderEditing) {
      taskWrapperRefs.current.forEach((wrapper) => {
        wrapper.style.transition = "";
        wrapper.style.transform = "";
      });
    }
  }, [draggingTaskIndex, isTaskOrderEditing, tasks]);

  return {
    getTaskDomKey,
    setTaskWrapperRef,
    handleTaskPointerDown,
    finishPointerDrag,
  };
}
