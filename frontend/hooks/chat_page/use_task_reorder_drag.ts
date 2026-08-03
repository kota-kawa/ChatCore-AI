import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  type PointerEvent as ReactPointerEvent,
} from "react";

import type { NormalizedTask } from "../../lib/chat_page/types";
import { getStableTaskKey } from "../../lib/chat_page/task_utils";

// ドラッグ開始と判定するための最小移動距離（ピクセル）
// Minimum pointer movement in pixels before a drag gesture is recognized
const POINTER_DRAG_START_THRESHOLD_PX = 8;

type UseTaskReorderDragOptions = {
  tasks: NormalizedTask[];
  isTaskOrderEditing: boolean;
  draggingTaskIndex: number | null;
  // モーダル表示や画面遷移でドラッグを中断すべきかどうか
  // Whether an overlay or view change should abort any in-flight drag
  isDragInterrupted: boolean;
  onDragStart: (dragIndex: number) => void;
  onDragEnd: (dragIndex: number, dropTargetIndex: number) => void;
};

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
  const dragStartPointRef = useRef<{ x: number; y: number } | null>(null);
  const dragPointerOffsetRef = useRef<{ x: number; y: number } | null>(null);
  const lastPointerPointRef = useRef<{ x: number; y: number } | null>(null);
  const draggingTaskDomKeyRef = useRef<string | null>(null);
  const draggingTaskIndexRef = useRef<number | null>(null);
  const dropTargetIndexRef = useRef<number | null>(null);
  const startRectsRef = useRef<Map<string, DOMRect>>(new Map());
  const isPointerDragActiveRef = useRef(false);

  // Drop completion refs (for useLayoutEffect animation)
  const justDroppedDomKeyRef = useRef<string | null>(null);
  const isDropCompletingRef = useRef(false);

  // ステートが変わるたびに最新のタスクリストをrefに同期（イベントリスナー内のクロージャ陳腐化を防ぐ）
  // Keep a live ref to tasks to avoid stale closures in callbacks
  const tasksRef = useRef(tasks);
  tasksRef.current = tasks;

  // Sync dragging index from React state → ref
  useEffect(() => {
    draggingTaskIndexRef.current = draggingTaskIndex;
  }, [draggingTaskIndex]);

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

  // ポインタードラッグを終了し、アニメーション状態をリセットしてReactに結果を通知する
  // End an in-progress pointer drag, clean up all drag state, and commit the reorder to React
  const finishPointerDrag = useCallback(
    (pointerId?: number) => {
      const activePointerId = activePointerIdRef.current;
      const draggingTaskDomKey = draggingTaskDomKeyRef.current;
      const hasActivePointerDrag = activePointerId !== null || draggingTaskDomKey !== null;
      if (!hasActivePointerDrag) return;

      if (typeof pointerId === "number" && activePointerId !== pointerId) return;

      // ポインターキャプチャを安全に解放する（既に解放済みの場合は無視）
      // Safely release pointer capture; ignore if it was already released
      if (activePointerId !== null && draggingTaskDomKey) {
        const draggingTaskWrapper = taskWrapperRefs.current.get(draggingTaskDomKey);
        if (draggingTaskWrapper?.hasPointerCapture(activePointerId)) {
          try {
            draggingTaskWrapper.releasePointerCapture(activePointerId);
          } catch {
            // already released
          }
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
      dragStartPointRef.current = null;
      dragPointerOffsetRef.current = null;
      lastPointerPointRef.current = null;
      draggingTaskDomKeyRef.current = null;
      draggingTaskIndexRef.current = null;
      dropTargetIndexRef.current = null;
      startRectsRef.current = new Map();
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
    [onDragEnd],
  );

  // タスクカードへのPointerDownを処理し、ドラッグ操作の前準備を行う
  // Handle pointer-down on a task card to set up all state needed for a potential drag
  const handleTaskPointerDown = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>, index: number, taskDomKey: string) => {
      if (!isTaskOrderEditing) return;
      if (event.pointerType !== "touch" && event.button !== 0) return;

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

      if (!event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.setPointerCapture(event.pointerId);
      }
      if (event.pointerType !== "touch") {
        event.preventDefault();
      }
    },
    [finishPointerDrag, isTaskOrderEditing],
  );

  // リサイズ・スクロール後にドラッグ中のカードの位置を再計算してUIを正しく更新する
  // Recapture element rects after resize/scroll so the dragged card and transforms stay accurate
  const refreshDragGeometry = useCallback(() => {
    if (!isPointerDragActiveRef.current) return;

    const draggingTaskDomKey = draggingTaskDomKeyRef.current;
    const pointerPoint = lastPointerPointRef.current;
    const pointerOffset = dragPointerOffsetRef.current;
    if (!draggingTaskDomKey || !pointerPoint || !pointerOffset) return;

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

    const draggingTaskWrapper = taskWrapperRefs.current.get(draggingTaskDomKey);
    const myStartRect = nextRects.get(draggingTaskDomKey);
    if (!draggingTaskWrapper || !myStartRect) return;

    const currentLeft = pointerPoint.x - pointerOffset.x;
    const currentTop = pointerPoint.y - pointerOffset.y;
    const deltaX = currentLeft - myStartRect.left;
    const deltaY = currentTop - myStartRect.top;
    draggingTaskWrapper.style.transform = `translate3d(${deltaX}px, ${deltaY}px, 0)`;

    updateDropTarget(currentLeft + myStartRect.width / 2, currentTop + myStartRect.height / 2);
    applyDragTransforms();
  }, [applyDragTransforms, updateDropTarget]);

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

      // しきい値を超えた移動が検出されて初めてドラッグ開始と判断する
      // Only activate drag after the pointer moves beyond the threshold to avoid accidental drags
      if (!isPointerDragActiveRef.current) {
        if (dragDistance < POINTER_DRAG_START_THRESHOLD_PX || dragIndex === null) return;
        isPointerDragActiveRef.current = true;
        onDragStart(dragIndex);
      }

      const draggingTaskWrapper = taskWrapperRefs.current.get(draggingTaskDomKey);
      const myStartRect = startRectsRef.current.get(draggingTaskDomKey);
      if (!draggingTaskWrapper || !myStartRect) return;

      // Move dragged card to follow pointer
      const currentLeft = pointerPoint.x - pointerOffset.x;
      const currentTop = pointerPoint.y - pointerOffset.y;
      const deltaX = currentLeft - myStartRect.left;
      const deltaY = currentTop - myStartRect.top;
      draggingTaskWrapper.style.transform = `translate3d(${deltaX}px, ${deltaY}px, 0)`;

      // Compute dragged card's visual center and update drop target
      const draggedCenterX = currentLeft + myStartRect.width / 2;
      const draggedCenterY = currentTop + myStartRect.height / 2;
      updateDropTarget(draggedCenterX, draggedCenterY);
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

    window.addEventListener("pointermove", handleWindowPointerMove, { passive: true });
    window.addEventListener("pointerup", handleWindowPointerUp);
    window.addEventListener("pointercancel", handleWindowPointerUp);
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
      window.removeEventListener("resize", scheduleRefreshDragGeometry);
      window.removeEventListener("orientationchange", scheduleRefreshDragGeometry);
      window.visualViewport?.removeEventListener("resize", scheduleRefreshDragGeometry);
      window.visualViewport?.removeEventListener("scroll", scheduleRefreshDragGeometry);
    };
  }, [finishPointerDrag, isTaskOrderEditing, onDragStart, refreshDragGeometry, updateDropTarget]);

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
      finishPointerDrag();
    };
  }, [finishPointerDrag]);

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
