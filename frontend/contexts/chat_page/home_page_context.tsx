import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, type Context, type ReactNode } from "react";

const useIsomorphicLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

type HomePageControllerState =
  ReturnType<typeof import("../../hooks/chat_page/use_home_page_controller").useHomePageController>;

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

type HomePageSetupChatContextValue = Pick<
  HomePageControllerState,
  | "chatRooms"
  | "switchChatRoom"
  | "handleAccessChat"
  | "handleSetupSendMessage"
  | "attachedFiles"
  | "setAttachedFiles"
>;

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
const HomePageLaunchPreviewContext = createContext<string | null>(null);
const HomePageTaskContext = createContext<HomePageTaskContextValue | null>(null);
const HomePageChatContext = createContext<HomePageChatContextValue | null>(null);
const HomePageSetupChatContext = createContext<HomePageSetupChatContextValue | null>(null);
const HomePageProjectContext = createContext<HomePageProjectContextValue | null>(null);

type HomePageContextProviderProps = {
  controller: HomePageControllerState;
  children: ReactNode;
};

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
