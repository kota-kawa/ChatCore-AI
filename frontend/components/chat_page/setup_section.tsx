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
          {tasks.map((task, index) => (
            <div
              key={`${task.name}-${index}`}
              className={`task-wrapper ${isTaskOrderEditing ? "editable" : ""} ${
                draggingTaskIndex === index ? "dragging" : ""
              }`.trim()}
              draggable={isTaskOrderEditing}
              onDragStart={(event) => {
                handleTaskDragStart(event, index);
              }}
              onDragOver={(event) => {
                handleTaskDragOver(event, index);
              }}
              onDragEnd={handleTaskDragEnd}
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
          ))}

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
