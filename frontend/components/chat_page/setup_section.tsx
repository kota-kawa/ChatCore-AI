import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ChangeEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";

import { MAX_SETUP_INFO_LENGTH, MODEL_OPTIONS } from "../../lib/chat_page/constants";
import {
  CHAT_ATTACHMENT_ACCEPT,
  getAttachmentIconClass,
  mergeChatAttachments,
  readSelectedChatAttachments,
} from "../../lib/chat_page/file_attachments";
import type { NormalizedTask } from "../../lib/chat_page/types";
import {
  useHomePageSetupChatContext,
  useHomePageTaskContext,
  useHomePageUiContext,
} from "../../contexts/chat_page/home_page_context";

const POINTER_DRAG_START_THRESHOLD_PX = 8;

type TaskCardProps = {
  task: NormalizedTask;
  index: number;
  taskDomKey: string;
  isEditing: boolean;
  isDragging: boolean;
  isLaunching: boolean;
  setTaskWrapperRef: (taskDomKey: string, node: HTMLDivElement | null) => void;
  onTaskPointerDown: (
    event: ReactPointerEvent<HTMLDivElement>,
    index: number,
    taskDomKey: string,
  ) => void;
  onFinishPointerDrag: () => void;
  onLaunch: (task: NormalizedTask) => void | Promise<void>;
  onDelete: (taskName: string) => void | Promise<void>;
  onEdit: (task: NormalizedTask) => void;
  onShowDetail: (task: NormalizedTask) => void;
};

function TemporaryChatIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M8.2 5.75h4.95c3.15 0 5.6 2.45 5.6 5.6v1.05c0 3.15-2.45 5.6-5.6 5.6h-1.5v1.45c0 .62-.72.97-1.21.58L7.82 18H8.2c-3.15 0-5.6-2.45-5.6-5.6v-1.05c0-3.15 2.45-5.6 5.6-5.6Z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeDasharray="3 3.1"
      />
    </svg>
  );
}

function TemporaryChatCheckIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M3.25 8.35 6.45 11.15 12.75 4.85"
        stroke="currentColor"
        strokeWidth="2.15"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

const TaskCard = memo(function TaskCard({
  task,
  index,
  taskDomKey,
  isEditing,
  isDragging,
  isLaunching,
  setTaskWrapperRef,
  onTaskPointerDown,
  onFinishPointerDrag,
  onLaunch,
  onDelete,
  onEdit,
  onShowDetail,
}: TaskCardProps) {
  return (
    <div
      ref={(node) => {
        setTaskWrapperRef(taskDomKey, node);
      }}
      className={`task-wrapper ${isEditing ? "editable" : ""} ${isDragging ? "dragging" : ""}`.trim()}
      data-task-index={index}
      data-task-dom-key={taskDomKey}
      onPointerDown={(event) => {
        onTaskPointerDown(event, index, taskDomKey);
      }}
    >
      <div
        className={`prompt-card ${isEditing ? "editable" : ""}`.trim()}
        data-launching={isLaunching ? "true" : "false"}
        data-task={task.name}
        data-is_default={task.is_default ? "true" : "false"}
        onClick={() => {
          if (isEditing) return;
          void onLaunch(task);
        }}
      >
        {isEditing && (
          <>
            <div className="task-card-action-container task-card-action-container--delete">
              <button
                type="button"
                className="card-delete-btn"
                data-tooltip="このタスクを削除"
                data-tooltip-placement="top"
                onClick={(event) => {
                  event.stopPropagation();
                  onFinishPointerDrag();
                  void onDelete(task.name);
                }}
              >
                <i className="bi bi-trash"></i>
              </button>
            </div>

            <div className="task-card-action-container task-card-action-container--edit">
              <button
                type="button"
                className="card-edit-btn"
                data-tooltip="このタスクを編集"
                data-tooltip-placement="top"
                onClick={(event) => {
                  event.stopPropagation();
                  onFinishPointerDrag();
                  onEdit(task);
                }}
              >
                <i className="bi bi-pencil"></i>
              </button>
            </div>
          </>
        )}

        <div className="header-container">
          <div className="task-header">{task.name}</div>
          <button
            type="button"
            className="task-detail-toggle"
            aria-label={`${task.name}の詳細を表示`}
            data-tooltip="タスクの詳細を表示"
            data-tooltip-placement="top"
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              onFinishPointerDrag();
              onShowDetail(task);
            }}
          >
            <i className="bi bi-caret-down"></i>
          </button>
        </div>
      </div>
    </div>
  );
});
TaskCard.displayName = "TaskCard";

function SetupSectionComponent() {
  const {
    pageViewState,
    isSetupVisible,
    isChatLaunching,
    loggedIn,
    setupInfo,
    temporaryModeEnabled,
    storedSetupStateLoaded,
    selectedModel,
    modelMenuOpen,
    selectedModelLabel,
    modelSelectRef,
    setSetupInfo,
    setTemporaryModeEnabled,
    setSelectedModel,
    setModelMenuOpen,
  } = useHomePageUiContext();

  const {
    tasks,
    isTaskOrderEditing,
    isNewPromptModalOpen,
    tasksExpanded,
    taskCollapseLimit,
    showTaskToggleButton,
    visibleTaskCountText,
    launchingTaskName,
    draggingTaskIndex,
    toggleTaskOrderEditing,
    closeNewPromptModal,
    openNewPromptModal,
    isAiAgentModalOpen,
    toggleAiAgentModal,
    handleTaskDragStart,
    handleTaskDragEnd,
    handleTaskCardLaunch,
    handleTaskDelete,
    openTaskEditModal,
    setTaskDetail,
    setTasksExpanded,
  } = useHomePageTaskContext();

  const {
    handleAccessChat,
    handleSetupSendMessage,
    attachedFiles,
    setAttachedFiles,
  } = useHomePageSetupChatContext();
  const isSetupInfoWithinLimit = setupInfo.length <= MAX_SETUP_INFO_LENGTH;
  const canSendSetupMessage = setupInfo.trim().length > 0 && isSetupInfoWithinLimit && !isChatLaunching;
  const selectedModelIndex = Math.max(
    0,
    MODEL_OPTIONS.findIndex((option) => option.value === selectedModel),
  );

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const notifyAttachmentError = useCallback((message: string) => {
    import("../../scripts/core/toast").then(({ showToast }) => {
      showToast(message, { variant: "error" });
    });
  }, []);

  const handleFileInputChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const files = event.target.files;
      if (!files || files.length === 0) return;

      void readSelectedChatAttachments(Array.from(files), attachedFiles, notifyAttachmentError).then(
        (selectedFiles) => {
          if (selectedFiles.length === 0) return;
          setAttachedFiles((prev) => mergeChatAttachments(prev, selectedFiles));
        },
      );

      if (event.target) event.target.value = "";
    },
    [attachedFiles, notifyAttachmentError, setAttachedFiles],
  );

  const handleRemoveAttachedFile = useCallback(
    (fileId: string) => {
      setAttachedFiles((prev) => prev.filter((f) => f.id !== fileId));
    },
    [setAttachedFiles],
  );

  // DOM refs
  const taskWrapperRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const modelTriggerRef = useRef<HTMLButtonElement | null>(null);
  const modelOptionRefs = useRef<Array<HTMLButtonElement | null>>([]);
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

  // Keep a live ref to tasks to avoid stale closures in callbacks
  const tasksRef = useRef(tasks);
  tasksRef.current = tasks;
  const saveModeFeedbackTimeoutRef = useRef<number | null>(null);
  const hasSeenInitialTemporaryModeRef = useRef(false);
  const [saveModeFeedbackVisible, setSaveModeFeedbackVisible] = useState(false);
  const [activeModelOptionIndex, setActiveModelOptionIndex] = useState(selectedModelIndex);

  // Sync dragging index from React state → ref
  useEffect(() => {
    draggingTaskIndexRef.current = draggingTaskIndex;
  }, [draggingTaskIndex]);

  useEffect(() => {
    setActiveModelOptionIndex(selectedModelIndex);
  }, [selectedModelIndex]);

  useEffect(() => {
    if (!modelMenuOpen) return;
    window.requestAnimationFrame(() => {
      modelOptionRefs.current[activeModelOptionIndex]?.focus();
    });
  }, [activeModelOptionIndex, modelMenuOpen]);

  useEffect(() => {
    if (!storedSetupStateLoaded) return;
    if (!hasSeenInitialTemporaryModeRef.current) {
      hasSeenInitialTemporaryModeRef.current = true;
      return;
    }

    setSaveModeFeedbackVisible(true);

    if (saveModeFeedbackTimeoutRef.current !== null) {
      window.clearTimeout(saveModeFeedbackTimeoutRef.current);
    }

    saveModeFeedbackTimeoutRef.current = window.setTimeout(() => {
      setSaveModeFeedbackVisible(false);
      saveModeFeedbackTimeoutRef.current = null;
    }, 1800);

    return () => {
      if (saveModeFeedbackTimeoutRef.current !== null) {
        window.clearTimeout(saveModeFeedbackTimeoutRef.current);
        saveModeFeedbackTimeoutRef.current = null;
      }
    };
  }, [storedSetupStateLoaded, temporaryModeEnabled]);

  const getTaskDomKey = useCallback((taskObject: object) => {
    const existing = taskObjectKeyMapRef.current.get(taskObject);
    if (existing) return existing;
    const nextKey = `task-dom-${taskObjectSequenceRef.current++}`;
    taskObjectKeyMapRef.current.set(taskObject, nextKey);
    return nextKey;
  }, []);

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

      // Determine which slot this item shifts to
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

  // Find the slot closest to the dragged card's visual center and update transforms
  const updateDropTarget = useCallback(
    (draggedCenterX: number, draggedCenterY: number) => {
      const dragIndex = draggingTaskIndexRef.current;
      if (dragIndex === null) return;

      const currentTasks = tasksRef.current;
      const startRects = startRectsRef.current;

      let bestIndex = dropTargetIndexRef.current ?? dragIndex;
      let bestDist = Infinity;

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

  const finishPointerDrag = useCallback(
    (pointerId?: number) => {
      const activePointerId = activePointerIdRef.current;
      const draggingTaskDomKey = draggingTaskDomKeyRef.current;
      const hasActivePointerDrag = activePointerId !== null || draggingTaskDomKey !== null;
      if (!hasActivePointerDrag) return;

      if (typeof pointerId === "number" && activePointerId !== pointerId) return;

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
      handleTaskDragEnd(finalDragIndex, finalDropTarget);
    },
    [handleTaskDragEnd],
  );

  const focusModelOption = useCallback((index: number) => {
    const lastIndex = MODEL_OPTIONS.length - 1;
    const nextIndex = Math.min(Math.max(index, 0), lastIndex);
    setActiveModelOptionIndex(nextIndex);
    window.requestAnimationFrame(() => {
      modelOptionRefs.current[nextIndex]?.focus();
    });
  }, []);

  const selectModelOption = useCallback(
    (index: number) => {
      const option = MODEL_OPTIONS[index];
      if (!option) return;
      setSelectedModel(option.value);
      setModelMenuOpen(false);
      modelTriggerRef.current?.focus();
    },
    [setModelMenuOpen, setSelectedModel],
  );

  const openModelMenuAt = useCallback(
    (index: number) => {
      const lastIndex = MODEL_OPTIONS.length - 1;
      const nextIndex = Math.min(Math.max(index, 0), lastIndex);
      setActiveModelOptionIndex(nextIndex);
      setModelMenuOpen(true);
      window.requestAnimationFrame(() => {
        modelOptionRefs.current[nextIndex]?.focus();
      });
    },
    [setModelMenuOpen],
  );

  const handleSetupInfoKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
      if (event.nativeEvent.isComposing || event.key === "Process") return;
      if (event.key !== "Enter" || event.shiftKey) return;

      event.preventDefault();
      if (!canSendSetupMessage) return;
      finishPointerDrag();
      void handleSetupSendMessage();
    },
    [canSendSetupMessage, finishPointerDrag, handleSetupSendMessage],
  );

  const handleModelTriggerKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLButtonElement>) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        openModelMenuAt(modelMenuOpen ? Math.min(activeModelOptionIndex + 1, MODEL_OPTIONS.length - 1) : selectedModelIndex);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        openModelMenuAt(modelMenuOpen ? Math.max(activeModelOptionIndex - 1, 0) : selectedModelIndex);
        return;
      }
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openModelMenuAt(selectedModelIndex);
      }
    },
    [activeModelOptionIndex, modelMenuOpen, openModelMenuAt, selectedModelIndex],
  );

  const handleModelOptionKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLButtonElement>, index: number) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        focusModelOption(index >= MODEL_OPTIONS.length - 1 ? 0 : index + 1);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        focusModelOption(index <= 0 ? MODEL_OPTIONS.length - 1 : index - 1);
        return;
      }
      if (event.key === "Home") {
        event.preventDefault();
        focusModelOption(0);
        return;
      }
      if (event.key === "End") {
        event.preventDefault();
        focusModelOption(MODEL_OPTIONS.length - 1);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        setModelMenuOpen(false);
        modelTriggerRef.current?.focus();
        return;
      }
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectModelOption(index);
      }
    },
    [focusModelOption, selectModelOption, setModelMenuOpen],
  );

  const handleTaskPointerDown = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>, index: number, taskDomKey: string) => {
      if (!isTaskOrderEditing) return;
      if (event.pointerType !== "touch" && event.button !== 0) return;

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
        if (dragDistance < POINTER_DRAG_START_THRESHOLD_PX || dragIndex === null) return;
        isPointerDragActiveRef.current = true;
        handleTaskDragStart(dragIndex);
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
  }, [finishPointerDrag, handleTaskDragStart, isTaskOrderEditing, refreshDragGeometry, updateDropTarget]);

  useEffect(() => {
    if (pageViewState !== "setup" || isNewPromptModalOpen) {
      finishPointerDrag();
    }
  }, [finishPointerDrag, isNewPromptModalOpen, pageViewState]);

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

      // Animate dropped card snapping to its new natural position
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
  }, [isTaskOrderEditing, tasks, draggingTaskIndex]);

  return (
    <div
      id="setup-container"
      data-view={pageViewState}
      aria-hidden={isSetupVisible ? "false" : "true"}
    >
      <form className="setup-form" id="setup-form" onSubmit={(event) => event.preventDefault()}>
        <h2 className="setup-form-title">Chat Core</h2>

        <div className="form-group setup-info-group">
          <label className="form-label" htmlFor="setup-info">やりたいことを入力（任意）</label>
          <div className="setup-info-field-shell">
            <div className="chat-save-mode-control">
              <button
                id="temporary-chat-mode-btn"
                type="button"
                className={`chat-save-mode-toggle ${temporaryModeEnabled ? "is-active" : ""}`.trim()}
                aria-pressed={temporaryModeEnabled ? "true" : "false"}
                aria-label={temporaryModeEnabled ? "未保存チャットモードをオフにする" : "未保存チャットモードをオンにする"}
                data-tooltip={temporaryModeEnabled ? "未保存チャットモード: ON" : "未保存チャットモード: OFF"}
                data-tooltip-placement="top"
                title={temporaryModeEnabled ? "未保存チャットモード: ON" : "未保存チャットモード: OFF"}
                onClick={() => {
                  finishPointerDrag();
                  setTemporaryModeEnabled((previous) => !previous);
                }}
              >
                <span className="chat-save-mode-toggle__icon" aria-hidden="true">
                  <TemporaryChatIcon />
                </span>
                {temporaryModeEnabled && (
                  <span className="chat-save-mode-toggle__check" aria-hidden="true">
                    <TemporaryChatCheckIcon />
                  </span>
                )}
              </button>

              <span
                className={`chat-save-mode-feedback ${saveModeFeedbackVisible ? "is-visible" : ""} ${
                  temporaryModeEnabled ? "is-active" : ""
                }`.trim()}
                role="status"
                aria-live="polite"
              >
                {temporaryModeEnabled ? "未保存チャット" : "履歴に保存"}
              </span>
            </div>

            {attachedFiles.length > 0 && (
              <div className="setup-attached-files">
                {attachedFiles.map((file) => (
                  <div key={file.id} className="chat-attached-file-chip">
                    <i
                      className={`bi ${getAttachmentIconClass(file.name)} chat-attached-file-chip__icon`}
                      aria-hidden="true"
                    ></i>
                    <span className="chat-attached-file-chip__name" title={file.name}>{file.name}</span>
                    <span className="chat-attached-file-chip__size">
                      {file.size < 1024
                        ? `${file.size}B`
                        : file.size < 1_048_576
                        ? `${(file.size / 1024).toFixed(1)}KB`
                        : `${(file.size / 1_048_576).toFixed(1)}MB`}
                    </span>
                    <button
                      type="button"
                      className="chat-attached-file-chip__remove"
                      aria-label={`${file.name}を削除`}
                      onClick={() => handleRemoveAttachedFile(file.id)}
                    >
                      <i className="bi bi-x" aria-hidden="true"></i>
                    </button>
                  </div>
                ))}
              </div>
            )}

            <div className="setup-info-input-area">
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept={CHAT_ATTACHMENT_ACCEPT}
                className="chat-file-input-hidden"
                aria-hidden="true"
                tabIndex={-1}
                onChange={handleFileInputChange}
              />
              <textarea
                id="setup-info"
                data-agent-id="chat.setup-message"
                rows={4}
                aria-describedby={setupInfo.length > 0 ? "setup-info-counter" : undefined}
                placeholder="例：沖縄旅行のプランを考えたい　／　英語メールを添削してほしい　／　Pythonのエラーを直したい"
                value={setupInfo}
                onChange={(event) => {
                  setSetupInfo(event.target.value);
                }}
                onKeyDown={handleSetupInfoKeyDown}
              ></textarea>

              <button
                type="button"
                className="setup-attach-btn"
                aria-label="ファイルを添付"
                data-tooltip="ファイルを添付"
                data-tooltip-placement="top"
                disabled={isChatLaunching || attachedFiles.length >= 5}
                onClick={() => fileInputRef.current?.click()}
              >
                <i className="bi bi-paperclip" aria-hidden="true"></i>
              </button>

              <button
                type="button"
                className="setup-send-btn"
                data-agent-id="chat.send-setup-message"
                aria-label="入力内容を送信"
                data-tooltip="メッセージを送信"
                data-tooltip-placement="top"
                disabled={!canSendSetupMessage}
                onClick={() => {
                  if (!canSendSetupMessage) return;
                  finishPointerDrag();
                  void handleSetupSendMessage();
                }}
              >
                <i className="bi bi-send"></i>
              </button>
            </div>
          </div>
          {setupInfo.length > 0 && (
            <div
              id="setup-info-counter"
              className={`setup-info-counter${setupInfo.length > MAX_SETUP_INFO_LENGTH ? " setup-info-counter--over" : ""}`}
              role={setupInfo.length > MAX_SETUP_INFO_LENGTH ? "alert" : "status"}
            >
              {setupInfo.length > MAX_SETUP_INFO_LENGTH
                ? `文字数制限を超えています（${setupInfo.length.toLocaleString()} / ${MAX_SETUP_INFO_LENGTH.toLocaleString()}文字）`
                : `${setupInfo.length.toLocaleString()} / ${MAX_SETUP_INFO_LENGTH.toLocaleString()}文字`}
            </div>
          )}
        </div>

        <div className="form-group">
          <label className="form-label" htmlFor="ai-model">AIモデル選択</label>

          <select
            id="ai-model"
            className="model-select-native"
            value={selectedModel}
            onChange={(event) => {
              setSelectedModel(event.target.value);
            }}
          >
            {MODEL_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>

          <div ref={modelSelectRef} className={`model-select ${modelMenuOpen ? "is-open" : ""}`.trim()}>
            <button
              ref={modelTriggerRef}
              type="button"
              className="model-select-trigger"
              aria-haspopup="listbox"
              aria-expanded={modelMenuOpen ? "true" : "false"}
              aria-controls="ai-model-listbox"
              onClick={() => {
                if (!modelMenuOpen) {
                  setActiveModelOptionIndex(selectedModelIndex);
                }
                setModelMenuOpen((previous) => !previous);
              }}
              onKeyDown={handleModelTriggerKeyDown}
            >
              {selectedModelLabel}
            </button>

            <div className="model-select-menu" id="ai-model-listbox" role="listbox" aria-label="AIモデル選択">
              {MODEL_OPTIONS.map((option, index) => (
                <button
                  key={option.value}
                  ref={(node) => {
                    modelOptionRefs.current[index] = node;
                  }}
                  id={`ai-model-option-${index}`}
                  type="button"
                  className={`model-select-option ${selectedModel === option.value ? "is-selected" : ""}`.trim()}
                  role="option"
                  aria-selected={selectedModel === option.value ? "true" : "false"}
                  tabIndex={modelMenuOpen && activeModelOptionIndex === index ? 0 : -1}
                  onFocus={() => {
                    setActiveModelOptionIndex(index);
                  }}
                  onKeyDown={(event) => {
                    handleModelOptionKeyDown(event, index);
                  }}
                  onClick={() => {
                    selectModelOption(index);
                  }}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="task-selection-header">
          <p id="task-selection-text">実行したいタスクを選択（クリックで即実行）</p>

          {loggedIn && (
            <>
              <button
                id="edit-task-order-btn"
                className="primary-button"
                type="button"
                data-tooltip={isTaskOrderEditing ? "並び替え編集を終了" : "タスクの並び順を編集"}
                data-tooltip-placement="bottom"
                onClick={() => {
                  finishPointerDrag();
                  toggleTaskOrderEditing();
                }}
              >
                <i className={`bi ${isTaskOrderEditing ? "bi-check" : "bi-arrows-move"}`}></i>
              </button>

              <button
                id="openNewPromptModal"
                className={`circle-button new-prompt-modal-btn ${isNewPromptModalOpen ? "is-rotated" : ""}`.trim()}
                type="button"
                data-tooltip="新しいプロンプトを作成"
                data-tooltip-placement="bottom"
                onClick={() => {
                  if (isNewPromptModalOpen) {
                    closeNewPromptModal();
                  } else {
                    finishPointerDrag();
                    openNewPromptModal();
                  }
                }}
              >
                <i className="bi bi-plus-lg"></i>
              </button>
            </>
          )}
        </div>

        <div
          className="task-selection"
          id="task-selection"
          data-launching={launchingTaskName ? "true" : "false"}
        >
          {(isTaskOrderEditing ? tasks : tasks.slice(0, taskCollapseLimit)).map((task, index) => {
            const taskDomKey = getTaskDomKey(task);
            return (
              <TaskCard
                key={taskDomKey}
                task={task}
                index={index}
                taskDomKey={taskDomKey}
                isEditing={isTaskOrderEditing}
                isDragging={draggingTaskIndex === index}
                isLaunching={launchingTaskName === task.name}
                setTaskWrapperRef={setTaskWrapperRef}
                onTaskPointerDown={handleTaskPointerDown}
                onFinishPointerDrag={finishPointerDrag}
                onLaunch={handleTaskCardLaunch}
                onDelete={handleTaskDelete}
                onEdit={openTaskEditModal}
                onShowDetail={setTaskDetail}
              />
            );
          })}

          {showTaskToggleButton && !isTaskOrderEditing && tasks.length > taskCollapseLimit && (
            <div className={`task-overflow-container${tasksExpanded ? " is-open" : ""}`}>
              <div className="task-overflow-inner">
                {tasks.slice(taskCollapseLimit).map((task, offsetIndex) => {
                  const index = taskCollapseLimit + offsetIndex;
                  const taskDomKey = getTaskDomKey(task);
                  return (
                    <TaskCard
                      key={taskDomKey}
                      task={task}
                      index={index}
                      taskDomKey={taskDomKey}
                      isEditing={false}
                      isDragging={draggingTaskIndex === index}
                      isLaunching={launchingTaskName === task.name}
                      setTaskWrapperRef={setTaskWrapperRef}
                      onTaskPointerDown={handleTaskPointerDown}
                      onFinishPointerDrag={finishPointerDrag}
                      onLaunch={handleTaskCardLaunch}
                      onDelete={handleTaskDelete}
                      onEdit={openTaskEditModal}
                      onShowDetail={setTaskDetail}
                    />
                  );
                })}
              </div>
            </div>
          )}

          {showTaskToggleButton && (
            <button
              type="button"
              id="toggle-tasks-btn"
              className="primary-button task-toggle-btn"
              onClick={() => {
                finishPointerDrag();
                setTasksExpanded((previous) => !previous);
              }}
            >
              {tasksExpanded ? <i className="bi bi-chevron-up"></i> : <i className="bi bi-chevron-down"></i>} {visibleTaskCountText}
            </button>
          )}
        </div>

        <div className="setup-access-chat">
          {loggedIn && (
            <button
              id="access-chat-btn"
              type="button"
              className="primary-button"
              onClick={() => {
                finishPointerDrag();
                void handleAccessChat();
              }}
            >
              <i className="bi bi-chat-left-text"></i> これまでのチャットを見る
            </button>
          )}
        </div>
      </form>
    </div>
  );
}

export const SetupSection = memo(SetupSectionComponent);
SetupSection.displayName = "SetupSection";
