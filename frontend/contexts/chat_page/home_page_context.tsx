// ホーム画面（pages/index.tsx）のコントローラー（useHomePageController）の戻り値を、用途別の Context に分けて配る。必要な値が変わった部分だけが再描画されるようにする。
// Distributes the home page controller (useHomePageController) state through purpose-specific contexts, so only the parts whose values changed re-render.
import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, type Context, type ReactNode } from "react";

// SSR では useEffect、ブラウザでは useLayoutEffect を使う（SSR 時の警告を避けるため）
// useEffect on the server and useLayoutEffect in the browser (avoids the SSR warning)
const useIsomorphicLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

// コントローラー hook の戻り値の型。各 Context の値の型はここから Pick で切り出す
// Return type of the controller hook; each context value type is a Pick over it
type HomePageControllerState =
  ReturnType<typeof import("../../hooks/chat_page/use_home_page_controller").useHomePageController>;

// セットアップ画面・モデル選択・各種モードなど、画面全体の UI 状態
// Page-wide UI state: setup screen, model selection and mode toggles
type HomePageUiContextValue = Pick<
  HomePageControllerState,
  | "loggedIn"
  | "pageViewState"
  | "isChatVisible"
  | "isSetupVisible"
  | "isChatLaunching"
  | "setupInfo"
  | "temporaryModeEnabled"
  | "personalKnowledgeEnabled"
  | "sharedPromptsEnabled"
  | "storedSetupStateLoaded"
  | "selectedModel"
  | "modelMenuOpen"
  | "selectedModelLabel"
  | "selectedModelShortLabel"
  | "modelSelectRef"
  | "chatHeaderModelMenuOpen"
  | "chatHeaderModelSelectRef"
  | "setSetupInfo"
  | "setTemporaryModeEnabled"
  | "setPersonalKnowledgeEnabled"
  | "setSharedPromptsEnabled"
  | "setSelectedModel"
  | "setModelMenuOpen"
  | "setChatHeaderModelMenuOpen"
  | "showSetupForm"
>;

// タスクカードの一覧・並べ替え・起動と、AI エージェントのモーダル
// Task cards (list, reordering, launch) and the AI agent modal
type HomePageTaskContextValue = Pick<
  HomePageControllerState,
  | "tasks"
  | "isTaskOrderEditing"
  | "isNewPromptModalOpen"
  | "tasksExpanded"
  | "taskCollapseLimit"
  | "showTaskToggleButton"
  | "visibleTaskCountText"
  | "launchingTaskName"
  | "launchingTaskId"
  | "draggingTaskIndex"
  | "toggleTaskOrderEditing"
  | "closeNewPromptModal"
  | "openNewPromptModal"
  | "handleTaskDragStart"
  | "handleTaskDragEnd"
  | "handleTaskCardLaunch"
  | "handleTaskDelete"
  | "openTaskEditModal"
  | "setTaskDetail"
  | "setTasksExpanded"
  | "isAiAgentModalOpen"
  | "openAiAgentModal"
  | "closeAiAgentModal"
  | "toggleAiAgentModal"
>;

// チャット画面の中央ペイン（chat_main_section.tsx）が読む UI 状態。UI 用 Context の一部だけを切り出し、無関係な変更で再描画されないようにする
// UI state read by the chat center pane (chat_main_section.tsx); a subset of the UI context so unrelated changes do not re-render it
type HomePageChatUiContextValue = Pick<
  HomePageUiContextValue,
  | "pageViewState"
  | "isChatVisible"
  | "isChatLaunching"
  | "loggedIn"
  | "personalKnowledgeEnabled"
  | "sharedPromptsEnabled"
  | "chatHeaderModelMenuOpen"
  | "selectedModel"
  | "selectedModelShortLabel"
  | "chatHeaderModelSelectRef"
  | "setPersonalKnowledgeEnabled"
  | "setSharedPromptsEnabled"
  | "showSetupForm"
  | "setChatHeaderModelMenuOpen"
  | "setSelectedModel"
>;

// ルーム一覧・メッセージ・入力欄・送信など、チャット本体の状態と操作
// Chat core state and actions: rooms, messages, input and sending
type HomePageChatContextValue = Pick<
  HomePageControllerState,
  | "handleAccessChat"
  | "hasCurrentRoom"
  | "sidebarOpen"
  | "chatRooms"
  | "chatRoomsHasMore"
  | "isChatRoomsInitialLoading"
  | "isLoadingMoreChatRooms"
  | "currentRoomId"
  | "currentRoomMode"
  | "openRoomActionsFor"
  | "isRoomSelectionMode"
  | "selectedRoomIds"
  | "isBulkDeletingRooms"
  | "chatMessageListResetKey"
  | "historyHasMore"
  | "historyNextBeforeId"
  | "isLoadingOlder"
  | "messages"
  | "chatMessagesRef"
  | "chatInput"
  | "isGenerating"
  | "openShareModal"
  | "handleNewChat"
  | "switchChatRoom"
  | "setOpenRoomActionsFor"
  | "handleRenameRoom"
  | "handleToggleRoomPin"
  | "handleDeleteRoom"
  | "handleBulkDeleteRooms"
  | "enterRoomSelectionMode"
  | "toggleRoomSelection"
  | "cancelRoomSelection"
  | "setSidebarOpen"
  | "loadMoreChatRooms"
  | "loadOlderChatHistory"
  | "setChatInput"
  | "attachedFiles"
  | "setAttachedFiles"
  | "handleChatInputKeyDown"
  | "handleSendMessage"
  | "handleRegenerateMessage"
  | "handleEditAndRegenerateMessage"
  | "handleSwitchBranch"
  | "applyToolApproval"
>;

// セットアップ画面から最初のメッセージを送るために必要な、チャット側の値
// The chat-side values the setup screen needs to send the first message
type HomePageSetupChatContextValue = Pick<
  HomePageControllerState,
  | "chatRooms"
  | "switchChatRoom"
  | "handleAccessChat"
  | "handleSetupSendMessage"
  | "attachedFiles"
  | "setAttachedFiles"
>;

// プロジェクトの一覧・詳細・作成・更新・削除
// Projects: list, detail, create, update and delete
type HomePageProjectContextValue = Pick<
  HomePageControllerState,
  | "projects"
  | "isProjectsLoading"
  | "activeProjectId"
  | "activeProjectDetail"
  | "isProjectDetailLoading"
  | "isProjectModalOpen"
  | "isSavingProject"
  | "pendingProjectId"
  | "loadProjects"
  | "openProject"
  | "closeProject"
  | "refreshProjectDetail"
  | "openNewProjectModal"
  | "closeNewProjectModal"
  | "createProject"
  | "updateProject"
  | "deleteProject"
  | "assignRoomToProject"
  | "setNewChatProject"
>;

const HomePageUiContext = createContext<HomePageUiContextValue | null>(null);
const HomePageChatUiContext = createContext<HomePageChatUiContextValue | null>(null);
// チャット起動中にだけ、セットアップ時に入力された内容（setupInfo）を配る。それ以外は null
// Carries the setup input (setupInfo) only while a chat is launching; null otherwise
const HomePageLaunchPreviewContext = createContext<string | null>(null);
const HomePageTaskContext = createContext<HomePageTaskContextValue | null>(null);
const HomePageChatContext = createContext<HomePageChatContextValue | null>(null);
const HomePageSetupChatContext = createContext<HomePageSetupChatContextValue | null>(null);
const HomePageProjectContext = createContext<HomePageProjectContextValue | null>(null);

type HomePageContextProviderProps = {
  controller: HomePageControllerState;
  children: ReactNode;
};

// コントローラーの値を各 Context の値にまとめ直して配る。値ごとに useMemo で参照を保ち、依存する値が変わらない限り子を再描画させない
// Regroup the controller's values into each context value; each is memoized so consumers do not re-render unless the values they depend on change
export function HomePageContextProvider({ controller, children }: HomePageContextProviderProps) {
  // setupInfo に依存する操作の参照を安定させ、確定した描画の controller へ渡す。
  // 中断された描画の操作を既存 UI へ混ぜないよう、参照の更新は commit 後に行う。
  // Keep setup-dependent actions stable and update their refs after commit so
  // an interrupted render cannot replace the callbacks used by the current UI.
  const handleTaskCardLaunchRef = useRef(controller.handleTaskCardLaunch);
  const handleTaskCardLaunch = useCallback(
    (...args: Parameters<HomePageControllerState["handleTaskCardLaunch"]>) => handleTaskCardLaunchRef.current(...args),
    [],
  );

  // setupInfo に依存する handleSetupSendMessage も、ref 経由の安定した関数として配る
  // handleSetupSendMessage, which also depends on setupInfo, is likewise exposed as a stable function through a ref
  const handleSetupSendMessageRef = useRef(controller.handleSetupSendMessage);
  useIsomorphicLayoutEffect(() => {
    handleTaskCardLaunchRef.current = controller.handleTaskCardLaunch;
    handleSetupSendMessageRef.current = controller.handleSetupSendMessage;
  }, [controller.handleTaskCardLaunch, controller.handleSetupSendMessage]);

  const handleSetupSendMessage = useCallback(
    (...args: Parameters<HomePageControllerState["handleSetupSendMessage"]>) => handleSetupSendMessageRef.current(...args),
    [],
  );

  const uiValue = useMemo<HomePageUiContextValue>(
    () => ({
      loggedIn: controller.loggedIn,
      pageViewState: controller.pageViewState,
      isChatVisible: controller.isChatVisible,
      isSetupVisible: controller.isSetupVisible,
      isChatLaunching: controller.isChatLaunching,
      setupInfo: controller.setupInfo,
      temporaryModeEnabled: controller.temporaryModeEnabled,
      personalKnowledgeEnabled: controller.personalKnowledgeEnabled,
      sharedPromptsEnabled: controller.sharedPromptsEnabled,
      storedSetupStateLoaded: controller.storedSetupStateLoaded,
      selectedModel: controller.selectedModel,
      modelMenuOpen: controller.modelMenuOpen,
      selectedModelLabel: controller.selectedModelLabel,
      selectedModelShortLabel: controller.selectedModelShortLabel,
      modelSelectRef: controller.modelSelectRef,
      chatHeaderModelMenuOpen: controller.chatHeaderModelMenuOpen,
      chatHeaderModelSelectRef: controller.chatHeaderModelSelectRef,
      setSetupInfo: controller.setSetupInfo,
      setTemporaryModeEnabled: controller.setTemporaryModeEnabled,
      setPersonalKnowledgeEnabled: controller.setPersonalKnowledgeEnabled,
      setSharedPromptsEnabled: controller.setSharedPromptsEnabled,
      setSelectedModel: controller.setSelectedModel,
      setModelMenuOpen: controller.setModelMenuOpen,
      setChatHeaderModelMenuOpen: controller.setChatHeaderModelMenuOpen,
      showSetupForm: controller.showSetupForm,
    }),
    [
      controller.loggedIn,
      controller.pageViewState,
      controller.isChatVisible,
      controller.isSetupVisible,
      controller.isChatLaunching,
      controller.setupInfo,
      controller.temporaryModeEnabled,
      controller.personalKnowledgeEnabled,
      controller.sharedPromptsEnabled,
      controller.storedSetupStateLoaded,
      controller.selectedModel,
      controller.modelMenuOpen,
      controller.selectedModelLabel,
      controller.selectedModelShortLabel,
      controller.modelSelectRef,
      controller.chatHeaderModelMenuOpen,
      controller.chatHeaderModelSelectRef,
      controller.setSetupInfo,
      controller.setTemporaryModeEnabled,
      controller.setPersonalKnowledgeEnabled,
      controller.setSharedPromptsEnabled,
      controller.setSelectedModel,
      controller.setModelMenuOpen,
      controller.setChatHeaderModelMenuOpen,
      controller.showSetupForm,
    ],
  );

  const chatUiValue = useMemo<HomePageChatUiContextValue>(
    () => ({
      pageViewState: controller.pageViewState,
      isChatVisible: controller.isChatVisible,
      isChatLaunching: controller.isChatLaunching,
      loggedIn: controller.loggedIn,
      personalKnowledgeEnabled: controller.personalKnowledgeEnabled,
      sharedPromptsEnabled: controller.sharedPromptsEnabled,
      chatHeaderModelMenuOpen: controller.chatHeaderModelMenuOpen,
      selectedModel: controller.selectedModel,
      selectedModelShortLabel: controller.selectedModelShortLabel,
      chatHeaderModelSelectRef: controller.chatHeaderModelSelectRef,
      setPersonalKnowledgeEnabled: controller.setPersonalKnowledgeEnabled,
      setSharedPromptsEnabled: controller.setSharedPromptsEnabled,
      showSetupForm: controller.showSetupForm,
      setChatHeaderModelMenuOpen: controller.setChatHeaderModelMenuOpen,
      setSelectedModel: controller.setSelectedModel,
    }),
    [
      controller.pageViewState,
      controller.isChatVisible,
      controller.isChatLaunching,
      controller.loggedIn,
      controller.personalKnowledgeEnabled,
      controller.sharedPromptsEnabled,
      controller.chatHeaderModelMenuOpen,
      controller.selectedModel,
      controller.selectedModelShortLabel,
      controller.chatHeaderModelSelectRef,
      controller.setPersonalKnowledgeEnabled,
      controller.setSharedPromptsEnabled,
      controller.showSetupForm,
      controller.setChatHeaderModelMenuOpen,
      controller.setSelectedModel,
    ],
  );

  // 起動中だけ setupInfo を渡す。購読するのは起動プレビューだけなので、セットアップ中の入力変更が非表示のチャットへ広がらない
  // Pass setupInfo only while launching; only the launch preview subscribes, so setup edits do not spread to the hidden chat
  const launchPreviewSetupInfo = controller.isChatLaunching ? controller.setupInfo : null;

  const taskValue = useMemo<HomePageTaskContextValue>(
    () => ({
      tasks: controller.tasks,
      isTaskOrderEditing: controller.isTaskOrderEditing,
      isNewPromptModalOpen: controller.isNewPromptModalOpen,
      tasksExpanded: controller.tasksExpanded,
      taskCollapseLimit: controller.taskCollapseLimit,
      showTaskToggleButton: controller.showTaskToggleButton,
      visibleTaskCountText: controller.visibleTaskCountText,
      launchingTaskName: controller.launchingTaskName,
      launchingTaskId: controller.launchingTaskId,
      draggingTaskIndex: controller.draggingTaskIndex,
      toggleTaskOrderEditing: controller.toggleTaskOrderEditing,
      closeNewPromptModal: controller.closeNewPromptModal,
      openNewPromptModal: controller.openNewPromptModal,
      handleTaskDragStart: controller.handleTaskDragStart,
      handleTaskDragEnd: controller.handleTaskDragEnd,
      handleTaskCardLaunch,
      handleTaskDelete: controller.handleTaskDelete,
      openTaskEditModal: controller.openTaskEditModal,
      setTaskDetail: controller.setTaskDetail,
      setTasksExpanded: controller.setTasksExpanded,
      isAiAgentModalOpen: controller.isAiAgentModalOpen,
      openAiAgentModal: controller.openAiAgentModal,
      closeAiAgentModal: controller.closeAiAgentModal,
      toggleAiAgentModal: controller.toggleAiAgentModal,
    }),
    [
      controller.tasks,
      controller.isTaskOrderEditing,
      controller.isNewPromptModalOpen,
      controller.tasksExpanded,
      controller.taskCollapseLimit,
      controller.showTaskToggleButton,
      controller.visibleTaskCountText,
      controller.launchingTaskName,
      controller.launchingTaskId,
      controller.draggingTaskIndex,
      controller.toggleTaskOrderEditing,
      controller.closeNewPromptModal,
      controller.openNewPromptModal,
      controller.handleTaskDragStart,
      controller.handleTaskDragEnd,
      handleTaskCardLaunch,
      controller.handleTaskDelete,
      controller.openTaskEditModal,
      controller.setTaskDetail,
      controller.setTasksExpanded,
      controller.isAiAgentModalOpen,
      controller.openAiAgentModal,
      controller.closeAiAgentModal,
      controller.toggleAiAgentModal,
    ],
  );

  const chatValue = useMemo<HomePageChatContextValue>(
    () => ({
      handleAccessChat: controller.handleAccessChat,
      hasCurrentRoom: controller.hasCurrentRoom,
      sidebarOpen: controller.sidebarOpen,
      chatRooms: controller.chatRooms,
      chatRoomsHasMore: controller.chatRoomsHasMore,
      isChatRoomsInitialLoading: controller.isChatRoomsInitialLoading,
      isLoadingMoreChatRooms: controller.isLoadingMoreChatRooms,
      currentRoomId: controller.currentRoomId,
      currentRoomMode: controller.currentRoomMode,
      openRoomActionsFor: controller.openRoomActionsFor,
      isRoomSelectionMode: controller.isRoomSelectionMode,
      selectedRoomIds: controller.selectedRoomIds,
      isBulkDeletingRooms: controller.isBulkDeletingRooms,
      chatMessageListResetKey: controller.chatMessageListResetKey,
      historyHasMore: controller.historyHasMore,
      historyNextBeforeId: controller.historyNextBeforeId,
      isLoadingOlder: controller.isLoadingOlder,
      messages: controller.messages,
      chatMessagesRef: controller.chatMessagesRef,
      chatInput: controller.chatInput,
      isGenerating: controller.isGenerating,
      openShareModal: controller.openShareModal,
      handleNewChat: controller.handleNewChat,
      switchChatRoom: controller.switchChatRoom,
      setOpenRoomActionsFor: controller.setOpenRoomActionsFor,
      handleRenameRoom: controller.handleRenameRoom,
      handleToggleRoomPin: controller.handleToggleRoomPin,
      handleDeleteRoom: controller.handleDeleteRoom,
      handleBulkDeleteRooms: controller.handleBulkDeleteRooms,
      enterRoomSelectionMode: controller.enterRoomSelectionMode,
      toggleRoomSelection: controller.toggleRoomSelection,
      cancelRoomSelection: controller.cancelRoomSelection,
      setSidebarOpen: controller.setSidebarOpen,
      loadMoreChatRooms: controller.loadMoreChatRooms,
      loadOlderChatHistory: controller.loadOlderChatHistory,
      setChatInput: controller.setChatInput,
      attachedFiles: controller.attachedFiles,
      setAttachedFiles: controller.setAttachedFiles,
      handleChatInputKeyDown: controller.handleChatInputKeyDown,
      handleSendMessage: controller.handleSendMessage,
      handleRegenerateMessage: controller.handleRegenerateMessage,
      handleEditAndRegenerateMessage: controller.handleEditAndRegenerateMessage,
      handleSwitchBranch: controller.handleSwitchBranch,
      applyToolApproval: controller.applyToolApproval,
    }),
    [
      controller.handleAccessChat,
      controller.hasCurrentRoom,
      controller.sidebarOpen,
      controller.chatRooms,
      controller.chatRoomsHasMore,
      controller.isChatRoomsInitialLoading,
      controller.isLoadingMoreChatRooms,
      controller.currentRoomId,
      controller.currentRoomMode,
      controller.openRoomActionsFor,
      controller.isRoomSelectionMode,
      controller.selectedRoomIds,
      controller.isBulkDeletingRooms,
      controller.chatMessageListResetKey,
      controller.historyHasMore,
      controller.historyNextBeforeId,
      controller.isLoadingOlder,
      controller.messages,
      controller.chatMessagesRef,
      controller.chatInput,
      controller.isGenerating,
      controller.openShareModal,
      controller.handleNewChat,
      controller.switchChatRoom,
      controller.setOpenRoomActionsFor,
      controller.handleRenameRoom,
      controller.handleToggleRoomPin,
      controller.handleDeleteRoom,
      controller.handleBulkDeleteRooms,
      controller.enterRoomSelectionMode,
      controller.toggleRoomSelection,
      controller.cancelRoomSelection,
      controller.setSidebarOpen,
      controller.loadMoreChatRooms,
      controller.loadOlderChatHistory,
      controller.setChatInput,
      controller.attachedFiles,
      controller.setAttachedFiles,
      controller.handleChatInputKeyDown,
      controller.handleSendMessage,
      controller.handleRegenerateMessage,
      controller.handleEditAndRegenerateMessage,
      controller.handleSwitchBranch,
      controller.applyToolApproval,
    ],
  );

  const setupChatValue = useMemo<HomePageSetupChatContextValue>(
    () => ({
      chatRooms: controller.chatRooms,
      switchChatRoom: controller.switchChatRoom,
      handleAccessChat: controller.handleAccessChat,
      handleSetupSendMessage,
      attachedFiles: controller.attachedFiles,
      setAttachedFiles: controller.setAttachedFiles,
    }),
    [
      controller.chatRooms,
      controller.switchChatRoom,
      controller.handleAccessChat,
      handleSetupSendMessage,
      controller.attachedFiles,
      controller.setAttachedFiles,
    ],
  );

  const projectValue = useMemo<HomePageProjectContextValue>(
    () => ({
      projects: controller.projects,
      isProjectsLoading: controller.isProjectsLoading,
      activeProjectId: controller.activeProjectId,
      activeProjectDetail: controller.activeProjectDetail,
      isProjectDetailLoading: controller.isProjectDetailLoading,
      isProjectModalOpen: controller.isProjectModalOpen,
      isSavingProject: controller.isSavingProject,
      pendingProjectId: controller.pendingProjectId,
      loadProjects: controller.loadProjects,
      openProject: controller.openProject,
      closeProject: controller.closeProject,
      refreshProjectDetail: controller.refreshProjectDetail,
      openNewProjectModal: controller.openNewProjectModal,
      closeNewProjectModal: controller.closeNewProjectModal,
      createProject: controller.createProject,
      updateProject: controller.updateProject,
      deleteProject: controller.deleteProject,
      assignRoomToProject: controller.assignRoomToProject,
      setNewChatProject: controller.setNewChatProject,
    }),
    [
      controller.projects,
      controller.isProjectsLoading,
      controller.activeProjectId,
      controller.activeProjectDetail,
      controller.isProjectDetailLoading,
      controller.isProjectModalOpen,
      controller.isSavingProject,
      controller.pendingProjectId,
      controller.loadProjects,
      controller.openProject,
      controller.closeProject,
      controller.refreshProjectDetail,
      controller.openNewProjectModal,
      controller.closeNewProjectModal,
      controller.createProject,
      controller.updateProject,
      controller.deleteProject,
      controller.assignRoomToProject,
      controller.setNewChatProject,
    ],
  );

  return (
    <HomePageUiContext.Provider value={uiValue}>
      <HomePageChatUiContext.Provider value={chatUiValue}>
        <HomePageLaunchPreviewContext.Provider value={launchPreviewSetupInfo}>
          <HomePageTaskContext.Provider value={taskValue}>
            <HomePageSetupChatContext.Provider value={setupChatValue}>
              <HomePageProjectContext.Provider value={projectValue}>
                <HomePageChatContext.Provider value={chatValue}>{children}</HomePageChatContext.Provider>
              </HomePageProjectContext.Provider>
            </HomePageSetupChatContext.Provider>
          </HomePageTaskContext.Provider>
        </HomePageLaunchPreviewContext.Provider>
      </HomePageChatUiContext.Provider>
    </HomePageUiContext.Provider>
  );
}

// Provider の外で使われたら、原因が分かるエラーを投げる
// Throw a descriptive error when used outside the provider
function useRequiredContext<T>(context: Context<T | null>, contextName: string): T {
  const value = useContext(context);
  if (!value) {
    throw new Error(`${contextName} must be used within HomePageContextProvider.`);
  }
  return value;
}

export function useHomePageUiContext() {
  return useRequiredContext(HomePageUiContext, "HomePageUiContext");
}

export function useHomePageChatUiContext() {
  return useRequiredContext(HomePageChatUiContext, "HomePageChatUiContext");
}

// この Context だけは null が正常値（起動中でない状態）なので、必須チェックをしない
// Unlike the others, null is a valid value here (not launching), so no required check is applied
export function useHomePageLaunchPreviewContext() {
  return useContext(HomePageLaunchPreviewContext);
}

export function useHomePageTaskContext() {
  return useRequiredContext(HomePageTaskContext, "HomePageTaskContext");
}

export function useHomePageChatContext() {
  return useRequiredContext(HomePageChatContext, "HomePageChatContext");
}

export function useHomePageSetupChatContext() {
  return useRequiredContext(HomePageSetupChatContext, "HomePageSetupChatContext");
}

export function useHomePageProjectContext() {
  return useRequiredContext(HomePageProjectContext, "HomePageProjectContext");
}
