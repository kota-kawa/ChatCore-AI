import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  type PointerEvent as ReactPointerEvent,
} from "react";

import { MODEL_OPTIONS } from "../../lib/chat_page/constants";
import { useHomePageChatContext, useHomePageTaskContext, useHomePageUiContext } from "../../contexts/chat_page/home_page_context";

export function SetupSection() {
  const {
    isChatVisible,
    loggedIn,
    setupInfo,
    selectedModel,
    modelMenuOpen,
    selectedModelLabel,
    modelSelectRef,
    setSetupInfo,
    setSelectedModel,
    setModelMenuOpen,
  } = useHomePageUiContext();

  const {
    tasks,
    isTaskOrderEditing,
    isNewPromptModalOpen,
    tasksExpanded,
    showTaskToggleButton,
    visibleTaskCountText,
    draggingTaskIndex,
    toggleTaskOrderEditing,
    closeNewPromptModal,
    openNewPromptModal,
    handleTaskDragStart,
    handleTaskDragOver,
    handleTaskDragEnd,
    handleTaskCardLaunch,
    handleTaskDelete,
    openTaskEditModal,
    setTaskDetail,
    setTasksExpanded,
  } = useHomePageTaskContext();

  const { handleAccessChat } = useHomePageChatContext();
  const taskWrapperRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const previousTaskRectsRef = useRef<Map<string, DOMRect>>(new Map());
  const taskObjectKeyMapRef = useRef<WeakMap<object, string>>(new WeakMap());
  const taskObjectSequenceRef = useRef(0);
  const activePointerIdRef = useRef<number | null>(null);
  const dragStartPointRef = useRef<{ x: number; y: number } | null>(null);
  const draggingTaskDomKeyRef = useRef<string | null>(null);

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

  const clearDraggedTaskTransform = useCallback(() => {
    const draggingTaskDomKey = draggingTaskDomKeyRef.current;
    if (!draggingTaskDomKey) return;

    const draggingTaskWrapper = taskWrapperRefs.current.get(draggingTaskDomKey);
    if (!draggingTaskWrapper) return;

    draggingTaskWrapper.style.transform = "";
  }, []);

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
            // pointer capture is already released
          }
        }
      }

      clearDraggedTaskTransform();
      activePointerIdRef.current = null;
      dragStartPointRef.current = null;
      draggingTaskDomKeyRef.current = null;
      handleTaskDragEnd();
    },
    [clearDraggedTaskTransform, handleTaskDragEnd],
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

      activePointerIdRef.current = event.pointerId;
      dragStartPointRef.current = { x: event.clientX, y: event.clientY };
      draggingTaskDomKeyRef.current = taskDomKey;
      handleTaskDragStart(index);

      if (!event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.setPointerCapture(event.pointerId);
      }
      event.preventDefault();
    },
    [finishPointerDrag, handleTaskDragStart, isTaskOrderEditing],
  );

  useEffect(() => {
    if (!isTaskOrderEditing) {
      finishPointerDrag();
      return;
    }

    const handleWindowPointerMove = (event: PointerEvent) => {
      const activePointerId = activePointerIdRef.current;
      if (activePointerId === null || event.pointerId !== activePointerId) return;

      const dragStartPoint = dragStartPointRef.current;
      const draggingTaskDomKey = draggingTaskDomKeyRef.current;
      if (!dragStartPoint || !draggingTaskDomKey) return;

      const draggingTaskWrapper = taskWrapperRefs.current.get(draggingTaskDomKey);
      if (draggingTaskWrapper) {
        const deltaX = event.clientX - dragStartPoint.x;
        const deltaY = event.clientY - dragStartPoint.y;
        draggingTaskWrapper.style.transform = `translate3d(${deltaX}px, ${deltaY}px, 0)`;
      }

      const hoveredElement = document.elementFromPoint(event.clientX, event.clientY);
      const hoveredTaskWrapper = hoveredElement?.closest<HTMLDivElement>(".task-wrapper[data-task-index]");
      if (hoveredTaskWrapper) {
        const hoverIndexRaw = hoveredTaskWrapper.dataset.taskIndex;
        const hoverIndex = hoverIndexRaw ? Number.parseInt(hoverIndexRaw, 10) : Number.NaN;
        if (Number.isFinite(hoverIndex)) {
          handleTaskDragOver(hoverIndex);
        }
      }

      if (event.cancelable) {
        event.preventDefault();
      }
    };

    const handleWindowPointerUp = (event: PointerEvent) => {
      finishPointerDrag(event.pointerId);
    };

    window.addEventListener("pointermove", handleWindowPointerMove, { passive: false });
    window.addEventListener("pointerup", handleWindowPointerUp);
    window.addEventListener("pointercancel", handleWindowPointerUp);

    return () => {
      window.removeEventListener("pointermove", handleWindowPointerMove);
      window.removeEventListener("pointerup", handleWindowPointerUp);
      window.removeEventListener("pointercancel", handleWindowPointerUp);
      finishPointerDrag();
    };
  }, [finishPointerDrag, handleTaskDragOver, isTaskOrderEditing]);

  useLayoutEffect(() => {
    const nextTaskRects = new Map<string, DOMRect>();
    taskWrapperRefs.current.forEach((element, taskDomKey) => {
      nextTaskRects.set(taskDomKey, element.getBoundingClientRect());
    });

    const previousTaskRects = previousTaskRectsRef.current;
    if (isTaskOrderEditing && previousTaskRects.size > 0) {
      const flipTargets: Array<{
        taskWrapper: HTMLDivElement;
        deltaX: number;
        deltaY: number;
      }> = [];

      nextTaskRects.forEach((nextRect, taskDomKey) => {
        const previousRect = previousTaskRects.get(taskDomKey);
        if (!previousRect) return;

        const taskWrapper = taskWrapperRefs.current.get(taskDomKey);
        if (!taskWrapper || taskWrapper.classList.contains("dragging")) return;

        const deltaX = previousRect.left - nextRect.left;
        const deltaY = previousRect.top - nextRect.top;
        if (Math.abs(deltaX) < 0.5 && Math.abs(deltaY) < 0.5) return;

        flipTargets.push({
          taskWrapper,
          deltaX,
          deltaY,
        });
      });

      if (flipTargets.length > 0) {
        flipTargets.forEach(({ taskWrapper, deltaX, deltaY }) => {
          taskWrapper.style.transition = "none";
          taskWrapper.style.transform = `translate3d(${deltaX}px, ${deltaY}px, 0)`;
        });

        void document.body.offsetHeight;

        flipTargets.forEach(({ taskWrapper }) => {
          taskWrapper.style.transition = "";
          taskWrapper.style.transform = "translate3d(0, 0, 0)";
        });
      }
    } else if (!isTaskOrderEditing) {
      taskWrapperRefs.current.forEach((taskWrapper) => {
        taskWrapper.style.transition = "";
        taskWrapper.style.transform = "";
      });
    }

    previousTaskRectsRef.current = nextTaskRects;
  }, [isTaskOrderEditing, tasks]);

  return (
    <div id="setup-container" data-visible={isChatVisible ? "false" : "true"}>
      <form className="setup-form" id="setup-form" onSubmit={(event) => event.preventDefault()}>
        <h2 className="setup-form-title">Chat Core</h2>

        <div className="form-group">
          <label className="form-label">現在の状況・作業環境（入力なしでもOK）</label>
          <textarea
            id="setup-info"
            rows={4}
            placeholder="例：大学生、リモートワーク中　／　自宅のデスク、周囲は静か"
            value={setupInfo}
            onChange={(event) => {
              setSetupInfo(event.target.value);
            }}
          ></textarea>
        </div>

        <div className="form-group">
          <label className="form-label">AIモデル選択</label>

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
              type="button"
              className="model-select-trigger"
              aria-haspopup="listbox"
              aria-expanded={modelMenuOpen ? "true" : "false"}
              onClick={() => {
                setModelMenuOpen((previous) => !previous);
              }}
            >
              {selectedModelLabel}
            </button>

            <div className="model-select-menu" role="listbox">
              {MODEL_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className={`model-select-option ${selectedModel === option.value ? "is-selected" : ""}`.trim()}
                  role="option"
                  aria-selected={selectedModel === option.value ? "true" : "false"}
                  onClick={() => {
                    setSelectedModel(option.value);
                    setModelMenuOpen(false);
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
          className={`task-selection ${
            tasks.length > 6 ? "tasks-collapsed" : ""
          } ${tasksExpanded || isTaskOrderEditing ? "tasks-expanded" : ""}`.trim()}
          id="task-selection"
        >
          {tasks.map((task, index) => {
            const taskDomKey = getTaskDomKey(task);
            return (
              <div
                key={taskDomKey}
                ref={(node) => {
                  setTaskWrapperRef(taskDomKey, node);
                }}
                className={`task-wrapper ${isTaskOrderEditing ? "editable" : ""} ${
                  draggingTaskIndex === index ? "dragging" : ""
                }`.trim()}
                data-task-index={index}
                data-task-dom-key={taskDomKey}
                onPointerDown={(event) => {
                  handleTaskPointerDown(event, index, taskDomKey);
                }}
              >
                <div
                  className={`prompt-card ${isTaskOrderEditing ? "editable" : ""}`.trim()}
                  data-task={task.name}
                  data-prompt_template={task.prompt_template}
                  data-response_rules={task.response_rules}
                  data-output_skeleton={task.output_skeleton}
                  data-input_examples={task.input_examples}
                  data-output_examples={task.output_examples}
                  data-is_default={task.is_default ? "true" : "false"}
                  onClick={() => {
                    if (isTaskOrderEditing) return;
                    void handleTaskCardLaunch(task);
                  }}
                >
                  {isTaskOrderEditing && (
                    <>
                      <div className="task-card-action-container task-card-action-container--delete">
                        <button
                          type="button"
                          className="card-delete-btn"
                          data-tooltip="このタスクを削除"
                          data-tooltip-placement="top"
                          onClick={(event) => {
                            event.stopPropagation();
                            void handleTaskDelete(task.name);
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
                            openTaskEditModal(task);
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
                      onClick={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        setTaskDetail(task);
                      }}
                    >
                      <i className="bi bi-caret-down"></i>
                    </button>
                  </div>
                </div>
              </div>
            );
          })}

          {showTaskToggleButton && (
            <button
              type="button"
              id="toggle-tasks-btn"
              className="primary-button task-toggle-btn"
              onClick={() => {
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
