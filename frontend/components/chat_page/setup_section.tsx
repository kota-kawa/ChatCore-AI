import {
  memo,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";

import { MAX_SETUP_INFO_LENGTH, MODEL_OPTIONS } from "../../lib/chat_page/constants";
import { formatModelOptionLabel } from "../../lib/chat_page/model_label";
import {
  CHAT_ATTACHMENT_ACCEPT,
  MAX_ATTACHED_FILES,
  getAttachmentIconClass,
} from "../../lib/chat_page/file_attachments";
import { KnowledgeLookupChips, SetupAttachMenu } from "./setup_attach_menu";
import { useChatAttachmentDropzone } from "../../hooks/chat_page/use_chat_attachment_dropzone";
import { useTaskReorderDrag } from "../../hooks/chat_page/use_task_reorder_drag";
import type { NormalizedTask } from "../../lib/chat_page/types";
import {
  useHomePageSetupChatContext,
  useHomePageTaskContext,
  useHomePageUiContext,
} from "../../contexts/chat_page/home_page_context";
import { useTranslation } from "../../contexts/locale_context";

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
  onDelete: (taskId: number) => void | Promise<void>;
  onEdit: (task: NormalizedTask) => void;
  onShowDetail: (task: NormalizedTask) => void;
};

// 未保存チャットモードを示すアイコン（点線の吹き出し）
// Icon indicating temporary (unsaved) chat mode, rendered as a dashed speech bubble
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

// 未保存チャットモードが有効であることを示すチェックマークアイコン
// Checkmark icon shown when temporary chat mode is currently active
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

// タスク一覧の各カードを描画するコンポーネント
// Renders a single task card with drag, edit, delete, and detail interactions
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
  const { locale, t } = useTranslation();
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
          {/* 編集モード中はクリックによるタスク起動を無効化 / Prevent launch when in edit/reorder mode */}
          if (isEditing) return;
          void onLaunch(task);
        }}
      >
        {isEditing && (
          <>
            {/* 編集モード時のみ削除・編集ボタンを表示 / Delete and edit actions visible only during edit mode */}
            <div className="task-card-action-container task-card-action-container--delete">
              <button
                type="button"
                className="card-delete-btn"
                data-tooltip={locale === "en" ? "Delete this task" : "このタスクを削除"}
                data-tooltip-placement="top"
                onClick={(event) => {
                  event.stopPropagation();
                  onFinishPointerDrag();
                  if (task.task_id !== null) void onDelete(task.task_id);
                }}
              >
                <i className="bi bi-trash"></i>
              </button>
            </div>

            <div className="task-card-action-container task-card-action-container--edit">
              <button
                type="button"
                className="card-edit-btn"
                data-tooltip={locale === "en" ? "Edit this task" : "このタスクを編集"}
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
            aria-label={t("home.taskDetailsFor", { name: task.name })}
            data-tooltip={locale === "en" ? "Show task details" : "タスクの詳細を表示"}
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

// セットアップ画面全体を管理するメインコンポーネント
// Main component that manages the setup screen: message input, model selection, and task list
function SetupSectionComponent() {
  const { locale, t } = useTranslation();
  const {
    pageViewState,
    isSetupVisible,
    isChatLaunching,
    loggedIn,
    setupInfo,
    temporaryModeEnabled,
    personalKnowledgeEnabled,
    setPersonalKnowledgeEnabled,
    sharedPromptsEnabled,
    setSharedPromptsEnabled,
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
    launchingTaskId,
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

  // 文字数制限チェックと送信可否の判定
  // Determine if the user's message is within limits and ready to send
  const isSetupInfoWithinLimit = setupInfo.length <= MAX_SETUP_INFO_LENGTH;
  const canSendSetupMessage = setupInfo.trim().length > 0 && isSetupInfoWithinLimit && !isChatLaunching;

  // 現在選択中のモデルのインデックスを特定（見つからない場合は先頭）
  // Resolve the index of the currently selected model, defaulting to the first option
  const selectedModelIndex = Math.max(
    0,
    MODEL_OPTIONS.findIndex((option) => option.value === selectedModel),
  );

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const setupInfoInputRef = useRef<HTMLTextAreaElement | null>(null);

  // ファイル添付エラーをトースト通知で表示するコールバック
  // Show attachment errors via toast notifications without importing the module at startup
  const notifyAttachmentError = useCallback((message: string) => {
    import("../../scripts/core/toast").then(({ showToast }) => {
      showToast(message, { variant: "error" });
    });
  }, []);

  const {
    attachSelectedFiles,
    isAttachmentDropActive,
    attachmentDropzoneProps,
  } = useChatAttachmentDropzone({
    attachedFiles,
    setAttachedFiles,
    isAttachmentDisabled: isChatLaunching,
    focusTargetRef: setupInfoInputRef,
    notifyAttachmentError,
  });

  // ファイル選択後にリストへ追加し、inputの値をリセットして同じファイルの再選択を可能にする
  // Append selected files and reset the input value so the same file can be picked again
  const handleFileInputChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const files = event.target.files;
      if (!files || files.length === 0) return;

      attachSelectedFiles(Array.from(files));

      if (event.target) event.target.value = "";
    },
    [attachSelectedFiles],
  );

  // 指定されたIDのファイルを添付リストから削除する
  // Remove a specific attached file from the list by its unique ID
  const handleRemoveAttachedFile = useCallback(
    (fileId: string) => {
      setAttachedFiles((prev) => prev.filter((f) => f.id !== fileId));
    },
    [setAttachedFiles],
  );

  // DOM refs
  const modelTriggerRef = useRef<HTMLButtonElement | null>(null);
  const modelOptionRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const saveModeFeedbackTimeoutRef = useRef<number | null>(null);
  const hasSeenInitialTemporaryModeRef = useRef(false);
  const [saveModeFeedbackVisible, setSaveModeFeedbackVisible] = useState(false);
  const [activeModelOptionIndex, setActiveModelOptionIndex] = useState(selectedModelIndex);

  // タスクカードの並び替えドラッグ（長押し起動・自動スクロール）は専用フックが担当する
  // The reorder drag gesture (hold to pick up, edge auto-scroll) lives in its own hook
  const {
    getTaskDomKey,
    setTaskWrapperRef,
    handleTaskPointerDown,
    finishPointerDrag,
  } = useTaskReorderDrag({
    tasks,
    isTaskOrderEditing,
    draggingTaskIndex,
    isDragInterrupted: pageViewState !== "setup" || isNewPromptModalOpen,
    onDragStart: handleTaskDragStart,
    onDragEnd: handleTaskDragEnd,
  });

  // 選択中モデルが変わったらキーボードフォーカス用のインデックスも更新する
  // Keep the keyboard-focused model option in sync when the selected model changes externally
  useEffect(() => {
    setActiveModelOptionIndex(selectedModelIndex);
  }, [selectedModelIndex]);

  // モデルメニューが開いたとき、現在アクティブな選択肢に自動フォーカスを当てる
  // Auto-focus the active model option when the dropdown opens for keyboard accessibility
  useEffect(() => {
    if (!modelMenuOpen) return;
    window.requestAnimationFrame(() => {
      modelOptionRefs.current[activeModelOptionIndex]?.focus();
    });
  }, [activeModelOptionIndex, modelMenuOpen]);

  // 未保存チャットモードが切り替わるたびにフィードバックテキストを一時表示する
  // Briefly show save-mode feedback text whenever the temporary mode toggle changes
  useEffect(() => {
    if (!storedSetupStateLoaded) return;

    // 初回ロード時はフィードバックを表示しない
    // Skip the first render so the toast doesn't flash on initial page load
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

  // キーボードでモデル選択肢にフォーカスを移動するヘルパー
  // Move keyboard focus to a model option, clamped within valid bounds
  const focusModelOption = useCallback((index: number) => {
    const lastIndex = MODEL_OPTIONS.length - 1;
    const nextIndex = Math.min(Math.max(index, 0), lastIndex);
    setActiveModelOptionIndex(nextIndex);
    window.requestAnimationFrame(() => {
      modelOptionRefs.current[nextIndex]?.focus();
    });
  }, []);

  // モデルを選択してドロップダウンを閉じ、トリガーボタンにフォーカスを戻す
  // Commit a model selection, close the dropdown, and return focus to the trigger
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

  // 指定インデックスにフォーカスを当てた状態でモデルメニューを開く
  // Open the model dropdown pre-focused on a specific option index
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

  // Enterキーで送信、IME変換中および Shift+Enterは無視する
  // Submit on Enter but skip during IME composition or when Shift is held (newline intent)
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

  // モデルトリガーボタンでの矢印キー操作をドロップダウンナビゲーションにマップする
  // Map arrow/enter/space keys on the trigger button to open or navigate the dropdown
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

  // WAI-ARIAのlistboxパターンに準拠したモデル選択肢のキーボードナビゲーション
  // Implement WAI-ARIA listbox keyboard navigation for the custom model dropdown
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

  return (
    <div
      id="setup-container"
      data-view={pageViewState}
      aria-hidden={isSetupVisible ? "false" : "true"}
    >
      <form className="setup-form" id="setup-form" onSubmit={(event) => event.preventDefault()}>
        <h2 className="setup-form-title">
          <img className="setup-form-title__icon" src="/static/favicon.png" alt="" aria-hidden="true" />
          <span>Chat Core</span>
        </h2>

        {/* 未ログイン時のみ表示する機能紹介テキスト（クロール可能な公開コンテンツを確保する） */}
        {/* Short feature intro shown only when logged out (provides crawlable public content) */}
        {!loggedIn && (
          <p className="setup-form-subtitle">
            {locale === "en" ? "ChatCore-AI brings AI research, writing, coding help, reusable prompts, and notes into one workspace. Try it below." : "ChatCore-AIは、日本語対応のAIチャットでの調べ物・文章作成・コード相談に加え、プロンプト共有やメモ保存をまとめて使えるAIワークスペースです。下の入力欄からそのまま試せます。"}
          </p>
        )}

        <div className="form-group setup-info-group">
          <label className="form-label" htmlFor="setup-info">{t("home.inputLabel")}</label>
          {/* ファイルドロップゾーンを兼ねたメッセージ入力エリア / Message input area that also serves as a file drop zone */}
          <div
            className={`setup-info-field-shell chat-attachment-dropzone ${
              isAttachmentDropActive ? "chat-attachment-dropzone--active" : ""
            }`.trim()}
            {...attachmentDropzoneProps}
          >
            <div className="chat-attachment-drop-overlay" aria-hidden="true">
              <span className="chat-attachment-drop-overlay__icon">
                <i className="bi bi-cloud-arrow-up" aria-hidden="true"></i>
              </span>
              <span className="chat-attachment-drop-overlay__text">{t("home.dropFiles")}</span>
              <span className="chat-attachment-drop-overlay__hint">PDF / Office / {locale === "en" ? "Text" : "テキスト"}</span>
            </div>
            {/* 添付ファイルのチップ一覧（ファイル名・サイズ・削除ボタン）/ Chips showing attached files with name, size, and remove button */}
            {attachedFiles.length > 0 && (
              <div className="setup-attached-files">
                {attachedFiles.map((file) => (
                  <div key={file.id} className="chat-attached-file-chip">
                    <i
                      className={`bi ${getAttachmentIconClass(file.name)} chat-attached-file-chip__icon`}
                      aria-hidden="true"
                    ></i>
                    <span className="chat-attached-file-chip__name" title={file.name}>{file.name}</span>
                    {/* バイト・KB・MBの単位を自動で切り替えて表示 / Dynamically format file size in B, KB, or MB */}
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

            <KnowledgeLookupChips
              memoLookupEnabled={personalKnowledgeEnabled}
              sharedPromptLookupEnabled={sharedPromptsEnabled}
              onToggleMemoLookup={() => setPersonalKnowledgeEnabled(false)}
              onToggleSharedPromptLookup={() => setSharedPromptsEnabled(false)}
            />

            <div className="setup-info-input-area">
              {/* 非表示のfile inputをボタン経由でプログラム的に開く / Hidden file input triggered programmatically via the attach button */}
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
                ref={setupInfoInputRef}
                id="setup-info"
                data-agent-id="chat.setup-message"
                rows={4}
                aria-describedby={setupInfo.length > 0 ? "setup-info-counter" : undefined}
                placeholder={t("home.inputPlaceholder")}
                value={setupInfo}
                onChange={(event) => {
                  setSetupInfo(event.target.value);
                }}
                onKeyDown={handleSetupInfoKeyDown}
              ></textarea>

              {/* 未保存チャットモードのトグルとフィードバック表示。添付・送信ボタンと同じ操作行の左端に置く */}
              {/* Temporary chat toggle with animated feedback label, anchored to the left of the same action row as attach/send */}
              <div className="chat-save-mode-control">
                <button
                  id="temporary-chat-mode-btn"
                  type="button"
                  className={`chat-save-mode-toggle ${temporaryModeEnabled ? "is-active" : ""}`.trim()}
                  aria-pressed={temporaryModeEnabled ? "true" : "false"}
                  aria-label={locale === "en" ? (temporaryModeEnabled ? "Turn temporary chat off" : "Turn temporary chat on") : (temporaryModeEnabled ? "未保存チャットモードをオフにする" : "未保存チャットモードをオンにする")}
                  data-tooltip={locale === "en" ? `Temporary chat: ${temporaryModeEnabled ? "ON" : "OFF"}` : `未保存チャットモード: ${temporaryModeEnabled ? "ON" : "OFF"}`}
                  data-tooltip-placement="top"
                  title={locale === "en" ? `Temporary chat: ${temporaryModeEnabled ? "ON" : "OFF"}` : `未保存チャットモード: ${temporaryModeEnabled ? "ON" : "OFF"}`}
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
                  {temporaryModeEnabled ? t("home.temporary") : t("home.savedHistory")}
                </span>
              </div>

              {/* クリップボタンは即座にファイル選択を開かず、追加メニューを開く */}
              {/* The paperclip opens the add menu instead of jumping straight to the file picker */}
              <SetupAttachMenu
                disabled={isChatLaunching}
                fileItemDisabled={attachedFiles.length >= MAX_ATTACHED_FILES}
                memoLookupEnabled={personalKnowledgeEnabled}
                memoItemDisabled={!loggedIn}
                sharedPromptLookupEnabled={sharedPromptsEnabled}
                onToggleMemoLookup={() => setPersonalKnowledgeEnabled((previous) => !previous)}
                onToggleSharedPromptLookup={() => setSharedPromptsEnabled((previous) => !previous)}
                onSelectFile={() => fileInputRef.current?.click()}
              />

              <button
                type="button"
                className="setup-send-btn"
                data-agent-id="chat.send-setup-message"
                aria-label={t("home.send")}
                data-tooltip={t("home.send")}
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
          {/* 文字数カウンター：制限超過時はalertロールで警告を通知 / Character counter that switches to alert role when the limit is exceeded */}
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
          <label className="form-label" htmlFor="ai-model">{t("home.model")}</label>

          {/* ネイティブselectは常に非表示、フォーム送信/オートフィル互換のために保持 / Native select stays visually hidden at all breakpoints; kept for form/autofill compatibility */}
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
                {formatModelOptionLabel(option, t, locale)}
              </option>
            ))}
          </select>

          {/* カスタムドロップダウンはlistboxロールでWAI-ARIAに準拠 / Custom dropdown implements listbox role for full keyboard and screen reader support */}
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

            <div className="model-select-menu" id="ai-model-listbox" role="listbox" aria-label={t("home.model")}>
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
                  {formatModelOptionLabel(option, t, locale)}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="task-selection-header">
          <p id="task-selection-text">{t("home.tasks")}</p>

          {/* ログイン済みユーザーのみ並び替え編集と新規作成ボタンを表示 / Reorder and create buttons only available to authenticated users */}
          {loggedIn && (
            <>
              <button
                id="edit-task-order-btn"
                className="primary-button"
                type="button"
                data-tooltip={locale === "en" ? (isTaskOrderEditing ? "Finish reordering" : "Reorder tasks") : (isTaskOrderEditing ? "並び替え編集を終了" : "タスクの並び順を編集")}
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
                data-tooltip={locale === "en" ? "Create a new prompt" : "新しいプロンプトを作成"}
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

        {/* 長押しで掴む操作は見た目に現れないため、編集モード中だけ操作方法を明示する */}
        {/* The hold-to-grab gesture is invisible, so spell it out while reorder mode is on */}
        {isTaskOrderEditing && (
          <p className="task-reorder-hint" role="status">
            <i className="bi bi-hand-index" aria-hidden="true"></i>
            <span>{t("home.reorderHint")}</span>
          </p>
        )}

        <div
          className={`task-selection ${isTaskOrderEditing ? "task-selection--reordering" : ""}`.trim()}
          id="task-selection"
          data-launching={launchingTaskName ? "true" : "false"}
        >
          {/* 編集モード時は全タスク、通常時は上限件数だけ表示 / Show all tasks in edit mode, otherwise limit visible count */}
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
                isLaunching={task.task_id !== null ? launchingTaskId === task.task_id : launchingTaskName === task.name}
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

          {/* 上限を超えるタスクはアニメーション付きの折りたたみエリアに収める / Tasks beyond the collapse limit live in an animated expand/collapse container */}
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
                      isLaunching={task.task_id !== null ? launchingTaskId === task.task_id : launchingTaskName === task.name}
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

          {/* 表示件数テキストを使ってタスク一覧の展開・折りたたみを切り替えるボタン / Toggle button that expands or collapses the overflow task list */}
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

        {/* ログイン済みユーザーのみ過去チャット履歴へのアクセスボタンを表示 / Chat history button is only shown to logged-in users */}
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
              <i className="bi bi-chat-left-text"></i> {t("home.viewPastChats")}
            </button>
          )}
        </div>
      </form>
    </div>
  );
}

// パフォーマンス最適化のためReact.memoでラップしてエクスポート
// Wrap with React.memo to prevent unnecessary re-renders of the heavy setup UI
export const SetupSection = memo(SetupSectionComponent);
SetupSection.displayName = "SetupSection";
